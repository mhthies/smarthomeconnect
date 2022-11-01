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
import collections
import enum
import functools
import logging
import signal
from typing import Set, NamedTuple, Dict, Any, Union, Iterable

from .base import Readable
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

    :ivar criticality: Defines to which extent the interface's status is considered when determining the overall SHC
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


StatusMetrics = Dict[str, Union[bool, int, float, str]]


class InterfaceStatus(NamedTuple):
    """
    Interface status information as returned by :meth:`AbstractInterface.get_status`.

    Contains the overall interface status (:attr:`status`), a human readable :attr:`message`, typically describing the
    error if any, and a map of :attr:`metrics`, which contain interface-specific performance values.
    """
    status: ServiceStatus = ServiceStatus.OK  #: Overall status of the interface.
    message: str = ""  #: A textual description of the error. E.g. an error message, if status != ServiceStatus.OK
    #: Additional monitoring metrics like performance values, identified by a unique string.
    metrics: StatusMetrics = {}


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


class EventLoopMonitor(AbstractInterface):
    """
    A special SHC interface class for monitoring the health of the asyncio Event Loop.

    This interface does not provide any connectors, but only implements the :meth:`get_status` method for allowing
    external monitoring systems to monitor the health of this application's event loop.

    For this purpose, when started, it regularly checks the current number of asyncio tasks and the delay of scheduled
    function calls in the event loop. These values are reported in the metrics dict of the interface status. The
    interface's service status is determined by comparing these metrics to fixed threshold values.

    There should only be single instance of this class, which can be accessed at
    :var:`shc.supervisor.LOOP_MONITOR_INTERFACE`.
    """
    def __init__(self, lag_warning: float = 0.005, lag_error: float = 0.02, tasks_warning: int = 1000,
                 tasks_error: int = 10000):
        super().__init__()
        self.interval = 5.0
        self.num_aggr_samples = 60
        self.samples = collections.deque()
        self.task: asyncio.Task
        self.tic = 0.0

        self.lag_warning = lag_warning
        self.lag_error = lag_error
        self.tasks_warning = tasks_warning
        self.tasks_error = tasks_error

    async def start(self) -> None:
        self.task = asyncio.create_task(self._monitor_loop())

    async def stop(self) -> None:
        self.task.cancel()
        await self.task

    async def _monitor_loop(self) -> None:
        loop = asyncio.get_running_loop()
        while True:
            self.tic = loop.time()
            loop.call_soon(self._measure_delay)
            try:
                await asyncio.sleep(self.interval)
            except asyncio.CancelledError:
                return

    def _measure_delay(self) -> None:
        lag = asyncio.get_running_loop().time() - self.tic
        queue_length = sum(1 for task in asyncio.all_tasks() if not task.done())
        self.samples.append((lag, queue_length))
        while len(self.samples) > self.num_aggr_samples:
            self.samples.popleft()

    async def _get_status(self) -> "InterfaceStatus":
        lag_max, tasks_max = functools.reduce(lambda a, i: (max(a[0], i[0]), max(a[1], i[1])), self.samples, (0.0, 0))
        warning = lag_max >= self.lag_warning or tasks_max >= self.tasks_warning
        error = lag_max >= self.lag_error or tasks_max >= self.tasks_error
        return InterfaceStatus(
            ServiceStatus.UNKNOWN if len(self.samples) == 0
            else ServiceStatus.CRITICAL if error
            else ServiceStatus.WARNING if warning
            else ServiceStatus.OK,
            "",
            {
                'lag_max': lag_max,
                'tasks_max': tasks_max
            }
        )

    def __repr__(self) -> str:
        return "EventLoopMonitor"


LOOP_MONITOR_INTERFACE = EventLoopMonitor()


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
