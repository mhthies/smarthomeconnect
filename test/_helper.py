import asyncio
import concurrent.futures
import functools
import heapq
import threading
import time
import unittest.mock
import datetime
from typing import Callable, Any, Awaitable, TypeVar, Generic, Type, List, Union, Tuple, Set, Optional

from shc import base


# #############################################
# General helper classes for testing async code
# #############################################

def async_test(f: Callable[..., Awaitable[Any]]) -> Callable[..., Any]:
    """
    Decorator to transform async unittest coroutines into normal test methods
    """
    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        loop = asyncio.get_event_loop()
        loop.run_until_complete(f(*args, **kwargs))
    return wrapper


class AsyncMock(unittest.mock.MagicMock):
    """
    Mock class which mimics an async coroutine (which can be called and then awaited) and an async context manager
    (which can be used in an `async with` block).

    This class is a simple replacement for unittest.mock.AsyncMock, which is only available since Python 3.8. This
    class does not have the assert_awaited features of the official AsyncMock.

    The async calls are passed to the normal call/enter/exit methods of the super class to use its usual builtin
    evaluation/assertion functionality (e.g. :meth:`unittest.mock.NonCallableMock.assert_called_with`).
    """
    async def __call__(self, *args, **kwargs):
        return super().__call__(*args, **kwargs)

    async def __aenter__(self, *args, **kwargs):
        return self.__enter__(*args, **kwargs)

    async def __aexit__(self, *args, **kwargs):
        return self.__exit__(*args, **kwargs)


class ClockMock:
    """
    A mock/patch for the wall clock.

    When used as context managers, objects of this class patch the :meth:`datetime.datetime.now` and
    :meth:`datetime.date.today` to return the mocked time instead of the real wall clock time, was well as the
    :func:`time.sleep` and :func:`asyncio.sleep` functions to enhance the mocked time instead of actually sleeping.
    Optionally, the patched sleep methods can actually sleep for a predefined time to allow concurrent things to happen
    in the mean time (which would normally happen during the sleep). This also allows to let the ClockMock synchronize
    multiple threads or AsyncIO coroutines, sleeping for different times in parallel.

    Before using `ClockMock`s, the :meth:`enable` class method must be called once to make the `date` and `datetime`
    classes patchable.
    """
    def __init__(self, start_time: datetime.datetime, overshoot: datetime.timedelta = datetime.timedelta(),
                 actual_sleep: float = 0.0):
        self.current_time = start_time
        self.overshoot = overshoot
        self.actual_sleep = actual_sleep
        self.original_sleep = time.sleep
        self.original_async_sleep = asyncio.sleep
        # A Mutex to make the the `queue` of sleeping Threads/Coroutines thread-safe
        self.mutex = threading.RLock()
        # Priority queue (heapq) of waiting Threads/Coroutines ordered by their wakeup time
        self.queue: List[Tuple[datetime.datetime, int, Union[int, asyncio.Task]]] = []
        # A counter for sleep times to make all entries in the queue unique
        self.counter = 0
        # Set of counter values of invalidated entries in the `queue`. Those must be skipped when checking if a
        # Thread/Couroutine is the next to wake up
        self.invalid_queue: Set[int] = set()

    def tidy_queue(self):
        while True:
            if self.queue[0][1] in self.invalid_queue:
                self.invalid_queue.remove(self.queue[0][1])
                heapq.heappop(self.queue)
            else:
                return

    def sleep(self, seconds: float) -> None:
        thread_id = threading.get_ident()
        # Add us to the queue of waiting threads/coroutines
        with self.mutex:
            target_time = self.current_time + datetime.timedelta(seconds=seconds) + self.overshoot
            heapq.heappush(self.queue, (target_time, self.counter, thread_id))
            self.counter += 1
        # Actually sleep while other thread/coroutine work or sleep (but shorter than we do in emulated time)
        while True:
            self.original_sleep(self.actual_sleep)
            with self.mutex:
                self.tidy_queue()
                if self.queue[0][2] == thread_id:
                    heapq.heappop(self.queue)
                    break
        # Update emulated wall clock to the target sleep time
        self.current_time = target_time

    async def async_sleep(self, seconds: float) -> None:
        current_task = asyncio.current_task()
        target_time = self.current_time + datetime.timedelta(seconds=seconds) + self.overshoot
        # Add us to the queue of waiting threads/coroutines
        with self.mutex:
            count = self.counter
            heapq.heappush(self.queue, (target_time, count, current_task))  # type: ignore
            self.counter += 1
        # Actually sleep while other thread/coroutine work or sleep (but shorter than we do in emulated time)
        while True:
            try:
                await self.original_async_sleep(self.actual_sleep)
            except asyncio.CancelledError:
                # If the sleep is ended by cancelling the task, we must make sure to invalidate our queue entry.
                # Otherwise, other threads/coroutines would sleep infinitely waiting for us to wake up
                with self.mutex:
                    self.invalid_queue.add(count)
                raise
            # Check if we are next to wake up or if another thread/coroutine should wake up before us, according to
            # emulated time
            with self.mutex:
                self.tidy_queue()
                if self.queue[0][2] is current_task:
                    heapq.heappop(self.queue)
                    break
        # Update emulated wall clock to the target sleep time
        self.current_time = target_time

    def now(self) -> datetime.datetime:
        return self.current_time

    def today(self) -> datetime.date:
        return self.current_time.date()

    def __enter__(self) -> "ClockMock":
        self.patches = (
            unittest.mock.patch('time.sleep', new=self.sleep),
            unittest.mock.patch('asyncio.sleep', new=self.async_sleep),
            unittest.mock.patch('datetime.datetime.now', new=self.now),
            unittest.mock.patch('datetime.date.today', new=self.today),
        )
        for p in self.patches:
            p.__enter__()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        for p in self.patches:
            p.__exit__(exc_type, exc_val, exc_tb)

    @staticmethod
    def enable() -> None:
        """
        Monkey-patch the datetime module with custom `date` and `datetime` classes to allow patching their methods. The
        new classes don't change any behaviour by theirselves, but enable `ClockMock` to do so.

        This classmethod must be called once, before using a ClockMock, e.g. in a TestCase's
        :meth:`unittest.TestCase.setUp` method.
        """
        import datetime

        class NewDate(datetime.date):
            pass
        datetime.date = NewDate  # type: ignore

        class NewDateTime(datetime.datetime):
            pass
        datetime.datetime = NewDateTime  # type: ignore

# ###########################
# Example Connectable objects
# ###########################

T = TypeVar('T')


class ExampleReadable(base.Readable[T], Generic[T]):
    def __init__(self, type_: Type[T], value: T, side_effect=None):
        self.type = type_
        super().__init__()
        self.read = AsyncMock(return_value=value, side_effect=side_effect)  # type: ignore

    async def read(self) -> T: ...


class ExampleSubscribable(base.Subscribable[T], Generic[T]):
    def __init__(self, type_: Type[T]):
        self.type = type_
        super().__init__()

    async def publish(self, val: T, origin: List[Any]) -> None:
        await self._publish(val, origin)


class ExampleWritable(base.Writable[T], Generic[T]):
    def __init__(self, type_: Type[T]):
        self.type = type_
        super().__init__()
        self._write = AsyncMock()  # type: ignore

    async def _write(self, value: T, origin: List[Any]) -> None: ...


class ExampleReading(base.Reading[T], Generic[T]):
    def __init__(self, type_: Type[T], optional: bool):
        self.is_reading_optional = optional
        self.type = type_
        super().__init__()

    async def do_read(self) -> Optional[T]:
        return await self._from_provider()


class SimpleIntRepublisher(base.Writable, base.Subscribable):
    type = int

    async def _write(self, value: T, origin: List[Any]):
        await self._publish(value, origin)


class InterfaceThreadRunner:
    """
    Some magic for running an SHC interface in a separate AsyncIO event loop in a background thread. This is helpful
    for testing the interface's features from the main thread, using blocking functions (e.g. selenium for web testing).

    The interface must not contain AsyncIO futures which are created at construction time and used by the
    start/wait/stop coroutines.

    The interface will most probably not be thread-safe internally (as SHC usually runs in only one AsyncIO event loop
    in a single thread). Thus, after starting the interface via the `InterfaceThreadRunner`, its methods/coroutines must
    only be called within the `InterfaceThreadRunner`s AsnycIO event loop::

        interface = SomeSHCInterface()
        runner = InterfaceThreadRunner(interface)
        runner.start()
        asyncio.run_coroutine_threadsafe(interface.some_coro(*args), loop=runner.loop).result()
        runner.loop.call_soon_threadsafe(interface.some_method(*args))
        runner.stop()

    :ivar loop: The event loop of the background thread, in which the interface is running. This variable is only
        available after :meth:`start` has successfully completed.
    :ivar interface: The wrapped interface (passed to the constructor).
    """

    def __init__(self, interface):
        self.interface = interface
        self._server_started_future = concurrent.futures.Future()

    def start(self) -> None:
        """
        Start the interface in a background thread.

        This method blocks until the successful startup of the interface (completion of its start() coroutine).
        :raises TimeoutError: If the interface does not come up (complete its `start()` coroutine) within 5 seconds.
        :raises Exception: If the interface raised an Exception in its `start()` coroutine.
        """
        executor = concurrent.futures.ThreadPoolExecutor()
        self.future = executor.submit(self._run)
        self._server_started_future.result(timeout=5)

    def _run(self) -> None:
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self.loop.run_until_complete(self._run_coro())

    async def _run_coro(self) -> None:
        try:
            await self.interface.start()
            self._server_started_future.set_result(None)
        except Exception as e:
            self._server_started_future.set_exception(e)
            return
        await self.interface.wait()

    def stop(self) -> None:
        """
        Stop the interface via its stop() coroutine and block until it is fully shutdown.
        """
        stop_future = asyncio.run_coroutine_threadsafe(self.interface.stop(), self.loop)
        stop_future.result()
        self.future.result()
