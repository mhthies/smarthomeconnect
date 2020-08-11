import asyncio
import functools
import unittest.mock
from typing import Callable, Any, Awaitable


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
    async def __call__(self, *args, **kwargs):
        return super().__call__(*args, **kwargs)

    async def __aenter__(self, *args, **kwargs):
        return self.__enter__(*args, **kwargs)

    async def __aexit__(self, *args, **kwargs):
        return self.__exit__(*args, **kwargs)
