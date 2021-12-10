# Copyright 2020-2021 Michael Thies <mail@mhthies.de>
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may not use this file except in compliance with
# the License. You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software distributed under the License is distributed on an
# "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the License for the
# specific language governing permissions and limitations under the License.
import abc
import asyncio
import enum
import functools
import logging
import signal
from typing import Set, NamedTuple, Dict, Any, Union, Iterable

from .timer import timer_supervisor
from .variables import read_initialize_variables

logger = logging.getLogger(__name__)

_REGISTERED_INTERFACES: Set["AbstractInterface"] = set()

event_loop = asyncio.get_event_loop()
_EXIT_CODE = 0
_SHC_STOPPED = asyncio.Event()
_SHC_STOPPED.set()


class ServiceCriticality(enum.Enum):
    """
    Enum of possible criticality values of interfaces.
    """
    INFO = 0
    WARNING = 1
    CRITICAL = 2


class AbstractInterface(metaclass=abc.ABCMeta):
    """
    Abstract base class for all SHC interface implementations

    An interface is an object that is 'started' at SHC startup. This is typically used to run interfaces to the outside
    world, using network connections (or serial device connections) and background asyncio Tasks for handling incoming
    messages and forwarding them to *Subscribable* objects.

    If an interface inherits from this base class, it is automatically registered for startup via :func:`main`.

    :ivar criticality: Defines to which extend the interface's status is considered when determining the overall SHC
        system state, e.g. when reporting to a monitoring system or creating alerts in a user interface. A critical
        failure of a *CRITICAL* system is considered a critical state, whereas a critical failure of an *INFO* system
        only triggers an information message.
    """
    criticality: ServiceCriticality = ServiceCriticality.CRITICAL

    def __init__(self):
        register_interface(self)

    @abc.abstractmethod
    async def start(self) -> None:
        """
        This coroutine is called once on each interface when the SHC application is started via :func:`main`.

        It may be used to initialize network connections and start background Tasks for message handling and event
        generation. The `start` coroutines of all interfaces are started in parallel. Timers and Variable's are only
        initialized when *all* `start` coroutines have returned successfully.

        The method should await the completion of the interface startup, i.e. only return when the interface is fully
        functional. In case of an error, this method may raise and exception or call :func:`interface_failure` to
        terminate the SHC application.
        """
        pass

    @abc.abstractmethod
    async def stop(self) -> None:
        """
        This coroutine is called once on each interface to shut down the SHC application.

        This may happen when a SIGTERM (or similar) is received or when a critical error in an interface is reported
        (via :func:`interface_failure` or an exception raised by an interface's :meth:`start` method). Thus, the `stop`
        method may even be called while :meth:`start` is still running. It shall be able to handle that situation and
        stop the half-started interface.

        In any case, the `stop` method shall cause the termination of all pending background task of the interface
        within a few seconds and only return when all tasks have terminated.
        """
        pass

    async def get_status(self) -> "InterfaceStatus":
        """
        Get the current status of the interface for monitoring purposes.

        This is especially required for interfaces that do not shut down the SHC application via
        :func:`interface_failure` on every disruption, but instead keep trying to recover operation. In the meantime,
        ServiceStatus.CRITICAL shall be reported via this method.
        """
        return InterfaceStatus()


class ServiceStatus(enum.Enum):
    """
    Enum of possible service status, derived from Nagios/Icinga status.
    """
    OK = 0
    WARNING = 1
    CRITICAL = 2
    UNKNOWN = 3


class InterfaceStatus(NamedTuple):
    """
    Interface status information as returned by :meth:`AbstractInterface.get_status`.

    Contains the overall interface status (:attr:`status`), a human readable :attr:`message`, typically describing the
    error if any, and a map of :attr:`indicators`, which contain interface-specific performance values.
    """
    status: ServiceStatus = ServiceStatus.OK  #: Overall status of the interface.
    message: str = ""  #: A textual description of the error. E.g. an error message, if status != ServiceStatus.OK
    #: Additional monitoring indicators like performance values, identified by a unique string.
    indicators: Dict[str, Union[bool, int, float, str]] = {}


def register_interface(interface: AbstractInterface) -> None:
    _REGISTERED_INTERFACES.add(interface)


def get_interfaces() -> Iterable[AbstractInterface]:
    return _REGISTERED_INTERFACES


async def interface_failure(interface_name: str = "n/a") -> None:
    """
    Shut down the SHC application due to a critical error in an interface

    This coroutine shall be called from an interface's background Task on a critical failure.
    It will shut down the SHC system gracefully and lets the Python process return with exit code 1.

    :param interface_name: String identifying the interface which caused the shutdown.
    """
    logger.warning("Shutting down SHC due to error in interface %s", interface_name)
    global _EXIT_CODE
    _EXIT_CODE = 1
    asyncio.create_task(stop())


async def run():
    _SHC_STOPPED.clear()
    logger.info("Starting up interfaces ...")
    # TODO catch errors and stop() in case of an exception
    await asyncio.gather(*(interface.start() for interface in _REGISTERED_INTERFACES))
    logger.info("All interfaces started successfully. Initializing variables ...")
    await read_initialize_variables()
    logger.info("Variables initialized successfully. Starting timers ...")
    await timer_supervisor.start()
    logger.info("Timers initialized successfully. SHC startup finished.")
    # Now, keep this task awaiting until SHC is stopped via stop()
    await _SHC_STOPPED.wait()


async def stop():
    logger.info("Shutting down interfaces ...")
    await asyncio.gather(*(interface.stop() for interface in _REGISTERED_INTERFACES), timer_supervisor.stop(),
                         return_exceptions=True)
    _SHC_STOPPED.set()


def handle_signal(sig: int, loop: asyncio.AbstractEventLoop):
    logger.info("Got signal {}. Initiating shutdown ...".format(sig))
    loop.create_task(stop())


def main() -> int:
    """
    Main entry point for running an SHC application

    This function starts an asyncio event loop to run the timers and interfaces. It registers signal handlers for
    SIGINT, SIGTERM, and SIGHUP to shut down all interfaces gracefully when such a signal is received. The `main`
    function blocks until shutdown is completed and returns the exit code. Thus, it should be used with
    :func:`sys.exit`::

        import sys
        import shc

        # setup interfaces, connect objects, etc.

        sys.exit(shc.main())

    A shutdown can also be triggered by a critical error in an interface (indicated via :func:`interface_failure`), in
    which case the the exit code will be != 0.

    :return: application exit code to be passed to sys.exit()
    """
    for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        event_loop.add_signal_handler(sig, functools.partial(handle_signal, sig, event_loop))
    event_loop.run_until_complete(run())
    return _EXIT_CODE
