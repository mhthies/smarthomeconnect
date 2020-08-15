import asyncio
import functools
import unittest.mock
from typing import Callable, Any, Awaitable, TypeVar, Generic, Type, List

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

    The async calls are passed to the normal call/enter/exit methods of the super class to use its usual builtin
    evaluation/assertion functionality (e.g. :meth:`unittest.mock.NonCallableMock.assert_called_with`).
    """
    async def __call__(self, *args, **kwargs):
        return super().__call__(*args, **kwargs)

    async def __aenter__(self, *args, **kwargs):
        return self.__enter__(*args, **kwargs)

    async def __aexit__(self, *args, **kwargs):
        return self.__exit__(*args, **kwargs)


# ###########################
# Example Connectable objects
# ###########################

T = TypeVar('T')


class ExampleReadable(base.Readable[T], Generic[T]):
    def __init__(self, type_: Type[T], value: T, side_effect=None):
        self.type = type_
        super().__init__()
        self.read = AsyncMock(return_value=value, side_effect=side_effect)

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
        self._write = AsyncMock()

    async def _write(self, value: T, origin: List[Any]) -> None: ...


class ExampleReading(base.Reading[T], Generic[T]):
    def __init__(self, type_: Type[T], optional: bool):
        self.is_reading_optional = optional
        self.type = type_
        super().__init__()

    async def do_read(self) -> T:
        return await self._from_provider()


class SimpleIntRepublisher(base.Writable, base.Subscribable):
    type = int

    async def _write(self, value: T, origin: List[Any]):
        await self._publish(value, origin)

