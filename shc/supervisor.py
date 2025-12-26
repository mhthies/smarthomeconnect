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
import logging
import signal
from typing import Iterable, NamedTuple, Optional, Set

from .base import Readable
from .timer import timer_supervisor
from .variables import read_initialize_variables

logger = logging.getLogger(__name__)

_REGISTERED_INTERFACES: Set["AbstractInterface"] = set()

_SUPERVISOR: Optional["_Supervisor"] = None


class ServiceCriticality(enum.Enum):
    """
    Enum of possible criticality values of interfaces.
    """

    INFO = 0
    WARNING = 1
    CRITICAL = 2


class AbstractInterface(metaclass=abc.ABCMeta):
    """
    Abstract base class for all SHC interface implementations.

    An interface is an object that is 'started' at SHC startup. This is typically used to run interfaces to the outside
    world, using network connections (or serial device connections) and background asyncio Tasks for handling incoming
    messages and forwarding them to *Subscribable* objects.

    If an interface inherits from this base class, it is automatically registered for startup via :func:`main`.
    """

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

    def monitoring_connector(self) -> Readable["InterfaceStatus"]:
        """
        Get a connector which represents the current status of this interface for monitoring purposes.

        The returned connector object must be of value type :class:`InterfaceStatus` and be at least *readable*. The
        connector *may* also be *subscribable*. In this case, the interface is expected to monitor its status
        continuously and publish any status changes asynchronously. This is typically implemented by client interfaces
        that actively monitor a connection to some server. *Reading* from the connector shall also return the current
        interface status.

        In the case of a *readable*-only connector, the interface will typically perform its health checks on-demand
        when the connector's ``read()`` method is called.

        Concrete interface implementation should override this method to provide their own monitoring connector
        implementation. There are different more specific interface base classes that to help with that:

        - :class:`ReadableStatusInterface <shc.interfaces._helper.ReadableStatusInterface>` is a simple helper for
          implementing a *readable* monitoring connector, calling an async health check method on the interface on
          demand
        - :class:`SubscribableStatusInterface <shc.interfaces._helper.SubscribableStatusInterface>` is a simple helper
          for implementing a *subscribable* monitoring connector, which can be updated when a status change is detected
        - :class:`SupervisedClientInterface <shc.interfaces._helper.SupervisedClientInterface>` implements logic for
          supervision, error handling and automatic reconnect of connection clients. It provides a subscribable
          monitoring connector.

        If the interface does not allow any reasonable status monitoring (e.g. when it's completely stateless or
        failsafe or implemented to shut down the overall SHC process on error), the default implementation of this
        method can be used, which raises a :class:`NotImplementedError`.

        :raises NotImplementedError: when the interface does not provide any health monitoring
        """
        raise NotImplementedError()


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
    current status, especially the error if any.
    """

    status: ServiceStatus = ServiceStatus.OK  #: Overall status of the interface.
    message: str = ""  #: A textual description of the error. E.g. an error message, if status != ServiceStatus.OK


def register_interface(interface: AbstractInterface) -> None:
    _REGISTERED_INTERFACES.add(interface)


def get_interfaces() -> Iterable[AbstractInterface]:
    return _REGISTERED_INTERFACES


async def interface_failure(interface_name: str = "n/a") -> None:
    """
    Shut down the SHC application due to a critical error in an interface.

    This coroutine shall be called from an interface's background Task on a critical failure.
    It will shut down the SHC system gracefully and lets the Python process return with exit code 1.

    For a normal shutdown, use `stop()` instead.

    :param interface_name: String identifying the interface which caused the shutdown.
    """
    global _SUPERVISOR
    if _SUPERVISOR is None:
        logger.error(
            f"Tried to shutdown SHC supervisor due to failure in interface {interface_name}, but SHC supervisor is not "
            "running."
        )
        return
    _SUPERVISOR.interface_failure(interface_name)


async def stop():
    """
    Gracefully stop the SHC supervisor and await its shutdown.

    When shutting down due to a critical error in an interface, use interface_failure() instead, which will set the
    program's exit code to 1.
    """
    global _SUPERVISOR
    if _SUPERVISOR is not None:
        await _SUPERVISOR.stop()


class _Supervisor:
    """
    Main entry class for running an SHC application including ordered startup and graceful shutdown.

    This class should not be used directly. Use the free methods :func:`run` or :func:`main` of this module to
    instantiate and invoke this class.

    This class is meant to be instantiated as a singleton. Its :meth:`run()` coroutine method should be called as the
    asynchronous main entry point to start up the SHC application and await its shutdown.

    The class is primarily used to wrap the _shc_stopped Event, which can only be instantiated from within the running
    asyncio event loop. It also includes setting up the SIGTERM / keyboard interrupt handling and handling of the exit
    code.
    """

    def __init__(self):
        self._loop = asyncio.get_running_loop()
        self._shc_stopped = asyncio.Event()
        self._exit_code = 0

    @staticmethod
    async def _start_interface(interface: AbstractInterface) -> None:
        try:
            await interface.start()
        except Exception as e:
            logger.critical("Exception while starting interface %s:", repr(interface), exc_info=e)
            raise RuntimeError()

    async def run(self) -> int:
        for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
            self._loop.add_signal_handler(sig, self._handle_signal, sig)
        self._shc_stopped.clear()
        logger.info("Starting up interfaces ...")
        try:
            await asyncio.gather(*(self._start_interface(interface) for interface in _REGISTERED_INTERFACES))
        except RuntimeError:
            logger.warning("Shutting down SHC due to error while starting up interfaces.")
            await self.stop()
            return 1
        logger.info("All interfaces started successfully. Initializing variables ...")
        await read_initialize_variables()
        logger.info("Variables initialized successfully. Starting timers ...")
        await timer_supervisor.start()
        logger.info("Timers initialized successfully. SHC startup finished.")
        # Now, keep this task awaiting SHC begin stopped via stop()
        await self._shc_stopped.wait()
        return self._exit_code

    def interface_failure(self, interface_name: str) -> None:
        logger.warning("Shutting down SHC due to error in interface %s", interface_name)
        self._exit_code = 1
        asyncio.create_task(self.stop())

    async def stop(self):
        logger.info("Shutting down interfaces ...")
        await asyncio.gather(
            *(interface.stop() for interface in _REGISTERED_INTERFACES), timer_supervisor.stop(), return_exceptions=True
        )
        self._shc_stopped.set()

    def _handle_signal(self, sig: int):
        logger.info("Got signal {}. Initiating shutdown ...".format(sig))
        self._loop.create_task(self.stop())


async def run() -> int:
    """
    Async main entry point for running an SHC application.

    It uses the :class:`_Supervisor` singleton class to

    * register signal handlers for SIGINT, SIGTERM, and SIGHUP to shut down all interfaces gracefully when such a
      signal is received.
    * start up all constructed SHC interfaces
    * await the shutdown of all SHC interfaces, either due to a critical error in an interface (indicated via
      :func:`interface_failure`) or triggered via one of the signals.

    :return: application exit code to be passed to sys.exit()
    """
    global _SUPERVISOR
    if _SUPERVISOR is None:
        _SUPERVISOR = _Supervisor()
    exit_code = await _SUPERVISOR.run()
    _SUPERVISOR = None
    return exit_code


def main() -> int:
    """
    Main entry point for running an SHC application.

    This function starts the :func:`run()` coroutine in a new asyncio event loop. It starts up everything and blocks
    until shutdown is completed (either due to critical errors or when stopped via signal) and returns the program exit
    code.

     Typical usage::

        import sys
        import shc

        # setup interfaces, connect objects, etc.

        sys.exit(shc.main())

    :return: application exit code to be passed to sys.exit()
    """
    return asyncio.run(run())
