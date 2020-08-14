import unittest
import unittest.mock
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


class ExampleWrapper(base.ConnectableWrapper, Generic[T]):
    def __init__(self, type_: Type[T]):
        self.type = type_
        self.connect = unittest.mock.Mock()

    def connect(self, *args, **kwargs) -> "Connectable": ...


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

        with unittest.mock.patch.object(a, 'subscribe') as mock_subscribe:
            a.connect(b, receive=False)  # `read` should not have an effect here
            mock_subscribe.assert_called_once_with(b, convert=False)

            mock_subscribe.reset_mock()
            b.connect(a, send=False)  # `provide` should not have an effect here
            mock_subscribe.assert_called_once_with(b, convert=False)

            # Explicit override
            mock_subscribe.reset_mock()
            a.connect(b, send=False)
            mock_subscribe.assert_not_called()

            b.connect(a, receive=False)
            mock_subscribe.reset_mock()
            mock_subscribe.assert_not_called()

        # Exceptions
        with self.assertRaises(TypeError):
            a.connect(b, receive=True)
        with self.assertRaises(TypeError):
            b.connect(a, send=True)

    def test_mandatory_reading(self):
        a = ExampleReable(int, TOTALLY_RANDOM_NUMBER)
        b = ExampleReading(int, False)

        with unittest.mock.patch.object(b, 'set_provider') as mock_set_provider:
            # Since Reading is mandatory, a should be registered with b by default
            a.connect(b, read=False)  # `read=False` should not have an effect here
            mock_set_provider.assert_called_once_with(a, convert=False)

            mock_set_provider.reset_mock()
            b.connect(a, provide=False)  # `provide=False` should not have an effect here
            mock_set_provider.assert_called_once_with(a, convert=False)

            # Explicit override
            mock_set_provider.reset_mock()
            a.connect(b, provide=False)
            mock_set_provider.assert_not_called()

            mock_set_provider.reset_mock()
            b.connect(a, read=False)
            mock_set_provider.assert_not_called()

        # Exceptions
        with self.assertRaises(TypeError):
            a.connect(b, read=True)
        with self.assertRaises(TypeError):
            b.connect(a, provide=True)

    def test_optional_reading(self):
        a = ExampleReable(int, TOTALLY_RANDOM_NUMBER)
        b = ExampleReading(int, True)

        with unittest.mock.patch.object(b, 'set_provider') as mock_set_provider:
            a.connect(b)
            mock_set_provider.assert_not_called()

            mock_set_provider.reset_mock()
            b.connect(a, read=True)
            mock_set_provider.assert_called_once_with(a, convert=False)

    def test_type_conversion(self):
        # TODO
        pass

    def test_connectable_wrapper(self):
        # TODO
        pass

