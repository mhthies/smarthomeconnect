import asyncio
import unittest
from typing import List, Any, Type, TypeVar, Generic

from ._helper import async_test, AsyncMock
from shc import base


TOTALLY_RANDOM_NUMBER = 42
T = TypeVar('T')


class ExampleReable(base.Readable[T], Generic[T]):
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


class TestSubscribe(unittest.TestCase):
    @async_test
    async def test_simple_subscribe(self):
        a = ExampleSubscribable(int)
        b = ExampleWritable(int)
        a.subscribe(b)
        await a.publish(TOTALLY_RANDOM_NUMBER, [self])
        b._write.assert_called_once_with(TOTALLY_RANDOM_NUMBER, [self, a])

    @async_test
    async def test_loopback_protection(self):
        a = ExampleSubscribable(int)
        b = ExampleWritable(int)
        a.subscribe(b)
        await a.publish(TOTALLY_RANDOM_NUMBER, [b])
        self.assertEqual(b._write.call_count, 0)
        await a.publish(TOTALLY_RANDOM_NUMBER, [b, self])
        self.assertEqual(b._write.call_count, 0)

    @async_test
    async def test_type_conversion(self):
        a = ExampleSubscribable(int)
        b = ExampleWritable(float)

        with self.assertRaises(TypeError):
            a.subscribe(b)
        a.subscribe(b, convert=True)
        await a.publish(TOTALLY_RANDOM_NUMBER, [self])
        b._write.assert_called_once()
        self.assertEqual(float(TOTALLY_RANDOM_NUMBER), b._write.call_args.args[0])
        self.assertIsInstance(b._write.call_args.args[0], float)

        c = ExampleWritable(list)
        with self.assertRaises(TypeError):
            a.subscribe(c)


class TestHandler(unittest.TestCase):
    @async_test
    async def test_basic_trigger(self):
        # TODO
        pass

    @async_test
    async def test_magic_source_passing(self):
        # TODO
        pass

    @async_test
    async def test_allow_recursion(self):
        # TODO
        pass


class TestReading(unittest.TestCase):
    @async_test
    async def test_simple_reading(self):
        a = ExampleReable(int, TOTALLY_RANDOM_NUMBER)
        b = ExampleReading(int, False)
        b.set_provider(a)
        result = await b.do_read()
        self.assertEqual(result, TOTALLY_RANDOM_NUMBER)

    @async_test
    async def test_type_conversion(self):
        a = ExampleReable(int, TOTALLY_RANDOM_NUMBER)
        b = ExampleReading(float, False)
        with self.assertRaises(TypeError):
            b.set_provider(a)

        b.set_provider(a, convert=True)
        result = await b.do_read()
        self.assertEqual(result, float(TOTALLY_RANDOM_NUMBER))
        self.assertIsInstance(result, float)

        c = ExampleReading(list, False)
        with self.assertRaises(TypeError):
            c.set_provider(a, convert=True)


class TestConnecting(unittest.TestCase):
    def test_subscribing(self):
        # TODO
        pass

    def test_mandatory_reading(self):
        # TODO
        pass

    def test_optional_reading(self):
        # TODO
        pass

    def test_connectable_wrapper(self):
        # TODO
        pass

