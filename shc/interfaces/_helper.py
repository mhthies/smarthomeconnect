# Copyright 2021 Michael Thies <mail@mhthies.de>
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
import logging
from typing import Set, Optional

from ..supervisor import AbstractInterface, interface_failure, InterfaceStatus, ServiceStatus

logger = logging.getLogger(__name__)


class SupervisedClientInterface(AbstractInterface, metaclass=abc.ABCMeta):
    """
    Abstract base class for client interfaces, providing run task supervision and automatic reconnects

    This class can be used as a base class for client interface implementations to simplify error handling and automatic
    reconnection attempts. The core of its functionality is the `_supervise` Task. It is started at interface `start()`
    and runs until shutdown of the interface. It starts and supervises the implementation-specific :meth:`_run` Task,
    which typically contains a loop for handling incoming messages. In addition, it calls :meth:`_connect` **before**
    and :meth:`_subscribe` **after** starting the run task. If the run task exits unexpectedly and
    :attr:`auto_reconnect` is enabled, reconnecting the interface via `_connect`, `_run` and `_subscribe` is attempted.
    For shutting down the interface (and stopping the run task in case of a subscribe error), `_disconnect` must be
    implemented in such a way, that it shuts down the run task.
    """
    def __init__(self, auto_reconnect: bool = True, failsafe_start: bool = False):
        super().__init__()
        """
        :param auto_reconnect: If True (default), the supervisor tries to reconnect the interface automatically with
            exponential backoff (`backoff_base` * `backoff_exponent` ^ n seconds sleep), when `_run` exits unexpectedly
            or any of _connect, _run or _subscribe raise an exception. Otherwise, the complete SHC system is shut down
            on connection errors.
        :param failsafe_start: If True and auto_reconnect is True, the interface allows SHC to start up, even if the
            `_connect` or `_subscribe` fails in the first try. The connection is retried in background with exponential
            backoff (see `auto_reconnect` option). Otherwise (default), the first connection attempt on startup is not
            retried and will raise an exception from `start()` on failure, even if `auto_reconnect` is True.
        """
        self.auto_reconnect = auto_reconnect
        self.failsafe_start = failsafe_start and auto_reconnect
        self.backoff_base = 1.0  #: First wait interval for exponential backoff in seconds
        self.backoff_exponent = 1.25  #: Multiplier for wait intervals for exponential backoff
        self._supervise_task: Optional[asyncio.Task] = None
        loop = asyncio.get_event_loop()
        self._started = loop.create_future()
        self._stopping = asyncio.Event()
        self._running = asyncio.Event()
        self._last_error: str = "Interface has not been started yet"

    async def start(self) -> None:
        logger.debug("Starting supervisor task for interface %s and waiting for it to come up ...", self)
        self._supervise_task = asyncio.create_task(self._supervise())
        await self._started

    async def stop(self) -> None:
        if self._stopping.is_set():
            return
        self._stopping.set()
        await self._disconnect()
        if self._supervise_task is not None:
            await self._supervise_task

    async def get_status(self) -> InterfaceStatus:
        return InterfaceStatus(ServiceStatus.OK if self._running.is_set() else ServiceStatus.CRITICAL,
                               self._last_error if not self._running.is_set() else "",
                               {})

    async def wait_running(self, timeout: Optional[float] = None) -> None:
        """
        Wait for the interface to be running.

        Attention: This must be called *after* :meth:`start` has initially been called (not neccessarily after it has
        returned).

        :param timeout: If given, this method will raise an :class:`asyncio.TimeoutError` after the given timeout in
            seconds, if the interface has not come up by this time.
        """
        await asyncio.wait_for(self._running.wait(), timeout)

    @abc.abstractmethod
    async def _run(self) -> None:
        """
        Entrypoint for the run task, which handles messages etc. while the connection is active.

        This coroutine is started in a separate task *after* :meth:`_connect` has completed sucessfully. As soon as it
        is ready, it must set the :attr:`_running` event. Only then the :meth:`_subscribe` method is called and the
        startup of the interface is reported as finished.

        The `_run` coroutine should be stoppable by calling :meth:`_disconnect` (i.e. it should return or raise an
        exception when `_disconnect` is called). If in doubt, just add a new :class:`asyncio.Event` and use
        :func:`asyncio.wait` with the event's `.wait()` method and your original future in all places, where you need to
        await a future. In addition, `_run` should return or raise an exception when a client error occurs, in order to
        trigger a reconnect attempt.
        """
        pass

    @abc.abstractmethod
    async def _connect(self) -> None:
        """
        This coroutine is run to connect the client.

        This will happen at start up and after any error (if auto_reconnect is enabled). In case of an error, *no*
        disconnect is attempted before calling `_connect`. Thus, this coroutine should be able to handle any connection
        state (not yet connected, not connected due to failed `_connect` attempt, broken connection, open connection
        with failed `_subscribe` call).

        This method is called *before* starting the :meth:`_run` task.
        """
        pass

    @abc.abstractmethod
    async def _disconnect(self) -> None:
        """
        This coroutine is called to disconnect the client and stop the _run task.

        This may happen either to shut down the interface (when stop() is called by the supervisor) or when an error
        occurs during :meth:`_subscribe` or when any error occurred and no auto_reconnect is attempted. Thus, disconnect
        should be able to shut down the client in a failed state as well. It should also be idempotent, i.e. allow to be
        called multiple times without reconnect. This method should not raise Exceptions but instead try its best to
        shut down the interface.

        Calling this coroutine must somehow stop the run task. I.e. :meth:`_run` should return or raise an exception
        shortly afterwards.
        """
        pass

    @abc.abstractmethod
    async def _subscribe(self) -> None:
        """
        This coroutine is called *after* :meth:`connecting <_connect>` the client and starting the :meth:`_run` task.

        It can be used to subscribe to topics, send initialization messages, etc. It will be called again after a
        reconnect, when an error occurs and `auto_reconnect` is enabled.
        """
        pass

    async def _supervise(self) -> None:
        sleep_interval = self.backoff_base

        while True:
            exception = None
            wait_stopping = asyncio.create_task(self._stopping.wait())
            try:
                # Connect
                logger.debug("Running _connect for interface %s ...", self)
                connect_task = asyncio.create_task(self._connect())
                # TODO timeout
                done, _ = await asyncio.wait((connect_task, wait_stopping), return_when=asyncio.FIRST_COMPLETED)
                if connect_task not in done:
                    logger.debug("Interface %s stopped before _connect finished", self)
                    connect_task.cancel()
                connect_task.result()  # raise exception if any

                # Start _run task and wait for _running
                logger.debug("Starting _run task for interface %s ...", self)
                run_task = asyncio.create_task(self._run())
                wait_running = asyncio.create_task(self._running.wait())
                # TODO timeout
                logger.debug("Waiting for interface %s to report it is running ...", self)
                done, _ = await asyncio.wait((wait_running, run_task), return_when=asyncio.FIRST_COMPLETED)
                if wait_running not in done:
                    wait_running.cancel()
                    if run_task not in done:  # This should not happen (without timeout)
                        await self._disconnect()
                        await run_task
                    raise RuntimeError("Run task stopped before _running has been set")

                # Subscribe
                logger.debug("Starting _subscribe task for interface %s ...", self)
                subscribe_task = asyncio.create_task(self._subscribe())
                # TODO timeout
                done, _ = await asyncio.wait((subscribe_task, run_task), return_when=asyncio.FIRST_COMPLETED)
                if subscribe_task not in done:
                    if run_task not in done:  # This should not happen (without timeout)
                        await self._disconnect()
                        await run_task
                    raise RuntimeError("Run task stopped before _subscribe task finished")
                subscribe_exception = subscribe_task.exception()
                if subscribe_exception is not None:
                    await self._disconnect()
                    try:
                        await run_task
                    except Exception as e:
                        logger.debug("Ignoring Exception %s in run task of interface %s, during shutdown due to "
                                     "exception in _subscribe task", repr(e), self)
                    raise subscribe_exception

                logger.debug("Starting up interface %s completed", self)
                if not self._started.done():
                    self._started.set_result(None)
                # Reset reconnect backoff interval
                sleep_interval = self.backoff_base

                # Wait for run task to return (due to stopping or error)
                await run_task

            except Exception as e:
                exception = e
                pass
            finally:
                wait_stopping.cancel()
            self._running.clear()

            # If we have not been started successfully yet, report startup as finished (if failsafe) or report startup
            # error and quit
            if not self._started.done():
                if self.failsafe_start:
                    self._started.set_result(None)
                else:
                    logger.debug("Startup of interface %s has not been finished due to exception", self)
                    self._started.set_exception(exception if exception is not None else asyncio.CancelledError())
                    await self._disconnect()
                    return

            # Return if we are stopping
            if self._stopping.is_set():
                if exception:
                    logger.debug("Ignoring exception %s in interface %s while stopping", repr(exception), self)
                return

            # Shut down SHC if no auto_reconnect shall be attempted
            if not self.auto_reconnect:
                if exception:
                    logger.critical("Error in interface %s:", exc_info=exception)
                else:
                    logger.critical("Unexpected shutdown of interface %s", self)
                asyncio.create_task(interface_failure(repr(self)))
                return

            if exception:
                logger.error("Error in interface %s. Attempting reconnect ...", self, exc_info=exception)
                self._last_error = str(exception)
            else:
                logger.error("Unexpected shutdown of interface %s. Attempting reconnect ...", self)
                self._last_error = "Unexpected shutdown of interface"

            # Sleep before reconnect
            logger.info("Waiting %s seconds before reconnect of interface %s ...", sleep_interval, self)
            wait_stopping = asyncio.create_task(self._stopping.wait())
            done, _ = await asyncio.wait((wait_stopping,), timeout=sleep_interval)
            if wait_stopping in done:
                logger.debug("Stopped interface %s while waiting for reconnect", self)
                return
            else:
                wait_stopping.cancel()
            sleep_interval *= self.backoff_exponent
            logger.info("Attempting reconnect of interface %s ...", self)
