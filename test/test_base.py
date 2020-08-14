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


class SimpleIntRepublisher(base.Writable, base.Subscribable):
    type = int

    async def _write(self, value: T, origin: List[Any]):
        await self._publish(value, origin)


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
        a = ExampleSubscribable(int)
        handler = AsyncMock()
        handler.__name__ = "handler_mock"
        wrapped_handler = base.handler()(handler)  # type: ignore
        a.trigger(wrapped_handler)
        await a.publish(TOTALLY_RANDOM_NUMBER, [self])
        handler.assert_called_once_with(TOTALLY_RANDOM_NUMBER, [self, a])

    @async_test
    async def test_magic_origin_passing(self):
        a = ExampleSubscribable(int)
        b = ExampleWritable(int)

        @a.trigger
        @base.handler()
        async def test_handler(value, _origin):
            await b.write(value)

        await a.publish(TOTALLY_RANDOM_NUMBER, [self])
        b._write.assert_called_once_with(TOTALLY_RANDOM_NUMBER, [self, a, test_handler])

    @async_test
    async def test_reset_origin(self):
        a = ExampleSubscribable(int)
        b = ExampleWritable(int)

        @a.trigger
        @base.handler(reset_origin=True)
        async def test_handler(value, _origin):
            await b.write(value)

        await a.publish(TOTALLY_RANDOM_NUMBER, [self])
        b._write.assert_called_once_with(TOTALLY_RANDOM_NUMBER, [test_handler])

    @async_test
    async def test_no_recursion(self):
        a = SimpleIntRepublisher()
        self.call_counter = 0

        @a.trigger
        @base.handler()
        async def a_test_handler(value, _origin):
            self.call_counter += 1
            if value > TOTALLY_RANDOM_NUMBER:
                return
            await a.write(value + 1)

        await a_test_handler(TOTALLY_RANDOM_NUMBER, [])
        self.assertEqual(1, self.call_counter)

    @async_test
    async def test_allow_recursion(self):
        a = SimpleIntRepublisher()
        self.call_counter = 0

        @a.trigger
        @base.handler(allow_recursion=True)
        async def another_test_handler(value, _origin):
            self.call_counter += 1
            if value > TOTALLY_RANDOM_NUMBER:
                return
            await a.write(value + 1)

        await another_test_handler(TOTALLY_RANDOM_NUMBER, [])
        self.assertEqual(2, self.call_counter)


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
        a = ExampleSubscribable(int)
        b = ExampleWritable(int)
        a.connect(b, receive=False)  # `read` should not have an effect here
        self.assertIn(b, [s[0] for s in a._subscribers])

        a = ExampleSubscribable(int)
        b = ExampleWritable(int)
        b.connect(a, send=False)  # `provide` should not have an effect here
        self.assertIn(b, [s[0] for s in a._subscribers])

        # Explicit override
        a = ExampleSubscribable(int)
        b = ExampleWritable(int)
        a.connect(b, send=False)
        self.assertNotIn(b, [s[0] for s in a._subscribers])

        a = ExampleSubscribable(int)
        b = ExampleWritable(int)
        b.connect(a, receive=False)
        self.assertNotIn(b, [s[0] for s in a._subscribers])

        # Exceptions
        a = ExampleSubscribable(int)
        b = ExampleWritable(int)
        with self.assertRaises(TypeError):
            a.connect(b, receive=True)
        with self.assertRaises(TypeError):
            b.connect(a, send=True)

    def test_mandatory_reading(self):
        # Since Reading is mandatory, a should be registered with b by default
        a = ExampleReable(int, TOTALLY_RANDOM_NUMBER)
        b = ExampleReading(int, False)
        a.connect(b, read=False)  # `read=False` should not have an effect here
        self.assertIs(b._default_provider[0], a)

        a = ExampleReable(int, TOTALLY_RANDOM_NUMBER)
        b = ExampleReading(int, False)
        b.connect(a, provide=False)  # `provide=False` should not have an effect here
        self.assertIs(b._default_provider[0], a)

        # Explicit override
        a = ExampleReable(int, TOTALLY_RANDOM_NUMBER)
        b = ExampleReading(int, False)
        a.connect(b, provide=False)
        self.assertIsNone(b._default_provider)

        a = ExampleReable(int, TOTALLY_RANDOM_NUMBER)
        b = ExampleReading(int, False)
        b.connect(a, read=False)
        self.assertIsNone(b._default_provider)

        # Exceptions
        a = ExampleReable(int, TOTALLY_RANDOM_NUMBER)
        b = ExampleReading(int, False)
        with self.assertRaises(TypeError):
            a.connect(b, read=True)
        with self.assertRaises(TypeError):
            b.connect(a, provide=True)

    def test_optional_reading(self):
        a = ExampleReable(int, TOTALLY_RANDOM_NUMBER)
        b = ExampleReading(int, True)
        a.connect(b)
        self.assertIsNone(b._default_provider)

        a = ExampleReable(int, TOTALLY_RANDOM_NUMBER)
        b = ExampleReading(int, True)
        b.connect(a, read=True)
        self.assertIs(b._default_provider[0], a)

    def test_type_conversion(self):
        # TODO
        pass

    def test_connectable_wrapper(self):
        # TODO
        pass

