import asyncio
import logging
import threading
import unittest
import unittest.mock
from typing import List, Any

from shc.base import PublishError
from ._helper import async_test, AsyncMock, ExampleReadable, ExampleSubscribable, ExampleWritable, ExampleReading, \
    LockedIntRepublisher
from shc import base


TOTALLY_RANDOM_NUMBER = 42


class TestSubscribe(unittest.TestCase):
    @async_test
    async def test_simple_subscribe(self) -> None:
        a = ExampleSubscribable(int)
        b = ExampleWritable(int)
        a.subscribe(b)
        await a.publish(TOTALLY_RANDOM_NUMBER, [self])
        b._write.assert_called_once_with(TOTALLY_RANDOM_NUMBER, [self, a])

    @async_test
    async def test_loopback_protection(self) -> None:
        a = ExampleSubscribable(int)
        b = ExampleWritable(int)
        a.subscribe(b)
        await a.publish(TOTALLY_RANDOM_NUMBER, [b])
        self.assertEqual(b._write.call_count, 0)
        await a.publish(TOTALLY_RANDOM_NUMBER, [b, self])
        self.assertEqual(b._write.call_count, 0)

    @async_test
    async def test_error_handling(self) -> None:
        a = ExampleSubscribable(int)
        b = ExampleWritable(int)
        b._write.side_effect = RuntimeError("Really unexpected error in _write")
        a.subscribe(b)
        with self.assertLogs(level=logging.ERROR) as ctx:
            with self.assertRaises(PublishError) as ctx2:
                await a.publish(TOTALLY_RANDOM_NUMBER, [self])
        self.assertIn("unexpected error in _write", "\n".join(ctx.output))
        exception = ctx2.exception
        self.assertEqual(1, len(exception.errors))
        self.assertIsInstance(exception.errors[0][0], RuntimeError)
        self.assertIn("unexpected error in _write", str(exception.errors[0][0]))
        self.assertIs(a, exception.errors[0][1])
        self.assertIs(b, exception.errors[0][2])

    @async_test
    async def test_type_conversion(self) -> None:
        a = ExampleSubscribable(int)
        b = ExampleWritable(float)

        with self.assertRaises(TypeError):
            a.subscribe(b)
        a.subscribe(b, convert=True)
        await a.publish(TOTALLY_RANDOM_NUMBER, [self])
        b._write.assert_called_once()
        self.assertEqual(float(TOTALLY_RANDOM_NUMBER), b._write.call_args[0][0])
        self.assertIsInstance(b._write.call_args[0][0], float)

        c = ExampleWritable(list)
        with self.assertRaises(TypeError):
            a.subscribe(c)

    @async_test
    async def test_explicit_conversion(self) -> None:
        a = ExampleSubscribable(int)
        b = ExampleWritable(float)

        converter = unittest.mock.Mock(side_effect=(56.5,))

        a.subscribe(b, convert=converter)
        await a.publish(TOTALLY_RANDOM_NUMBER, [self])
        converter.assert_called_once_with(TOTALLY_RANDOM_NUMBER)
        b._write.assert_called_once_with(56.5, unittest.mock.ANY)

    @async_test
    async def test_lock_sharing_and_asynchronous_subscribe(self) -> None:
        class BlockingWritable(base.Writable[int]):
            type = int

            def __init__(self):
                super().__init__()
                self.event = asyncio.Event()

            async def _write(self, _value: int, _origin: List[Any]) -> None:
                await self.event.wait()
                self.event.clear()

        # Let's test the lock sharing between synchronously connected HasSharedLock objects
        a = LockedIntRepublisher()
        b = LockedIntRepublisher()
        blocking_sub = BlockingWritable()
        another_blocking_sub = BlockingWritable()
        sub = ExampleWritable(int)
        a.subscribe(b, sync=True)
        a.subscribe(sub)
        b.subscribe(blocking_sub, sync=True)
        b.subscribe(another_blocking_sub, sync=False)
        self.assertIs(a._shared_lock.lock, b._shared_lock.lock)

        asyncio.create_task(a.write(42, [self]))
        await asyncio.sleep(0.05)
        asyncio.create_task(a.write(56, [self]))
        await asyncio.sleep(0.05)
        # The second value update should be blocked by the first (incomplete) value update, so only one call to
        # sub.write by now
        sub._write.assert_called_once_with(42, unittest.mock.ANY)
        sub._write.reset_mock()
        # Releasing the first value update should allow the second value update to pass through
        # The asynchronously subscribed blocking sub should not be a problem ...
        blocking_sub.event.set()
        await asyncio.sleep(0.05)
        sub._write.assert_called_once_with(56, unittest.mock.ANY)
        # Clean up pending tasks
        blocking_sub.event.set()
        another_blocking_sub.event.set()
        await asyncio.sleep(0.05)
        another_blocking_sub.event.set()

        # Now, let's test asynchronous subscriptions
        a2 = LockedIntRepublisher()
        b2 = LockedIntRepublisher()
        sub2 = ExampleWritable(int)
        blocking_sub2 = BlockingWritable()
        a2.connect(b2, send_sync=False, receive=False)
        a2.subscribe(sub2)
        b2.subscribe(blocking_sub2, sync=True)
        self.assertIsNot(a2._shared_lock.lock, b2._shared_lock.lock)

        # With a2 and b2 connected asynchronously, the blocking synchronous subscriber at b2 should not be a problem
        asyncio.create_task(a2.write(42, [self]))
        await asyncio.sleep(0.05)
        asyncio.create_task(a2.write(56, [self]))
        await asyncio.sleep(0.05)
        self.assertEqual(2, sub2._write.call_count)
        # Clean up pending tasks
        blocking_sub2.event.set()
        await asyncio.sleep(0.05)
        blocking_sub2.event.set()
        await asyncio.sleep(0.05)

        # The cases of a not being HasSharedLock or b not being HasSharedLock are already covered by many other tests

    @async_test
    async def test_publish_error_propagation(self) -> None:
        async def some_handler(_v: int, _o: List[Any]) -> None:
            raise RuntimeError("Some error from handler")

        sub = ExampleWritable(int)
        sub._write.side_effect = RuntimeError("Some error from Writable")

        a = LockedIntRepublisher()
        a.subscribe(sub)
        b = LockedIntRepublisher()\
            .connect(a)
        b.trigger(some_handler, sync=True)

        with self.assertRaises(PublishError) as ctx:
            await a.write(42, [self])
        exception = ctx.exception
        self.assertEqual(2, len(exception.errors))
        handler_error_index = 0 if exception.errors[0][2] is some_handler else 1
        sub_error_index = 1 - handler_error_index
        self.assertIsInstance(exception.errors[handler_error_index][0], RuntimeError)
        self.assertIn("from handler", str(exception.errors[handler_error_index][0]))
        self.assertIs(exception.errors[handler_error_index][1], b)
        self.assertIs(exception.errors[handler_error_index][2], some_handler)
        self.assertIsInstance(exception.errors[sub_error_index][0], RuntimeError)
        self.assertIn("from Writable", str(exception.errors[sub_error_index][0]))
        self.assertIs(exception.errors[sub_error_index][1], a)
        self.assertIs(exception.errors[sub_error_index][2], sub)

        # Asynchronous subscribing/triggering should not propagate exception
        # Logging is already tested in test_error_handling()
        c = LockedIntRepublisher()
        c.trigger(some_handler, sync=False)
        c.subscribe(sub, sync=False)
        await c.write(56, [self])
        await asyncio.sleep(0.05)


class TestHandler(unittest.TestCase):
    @async_test
    async def test_basic_trigger(self) -> None:
        a = ExampleSubscribable(int)
        handler = AsyncMock()
        handler.__name__ = "handler_mock"
        wrapped_handler = base.handler()(handler)  # type: ignore
        a.trigger(wrapped_handler)
        await a.publish(TOTALLY_RANDOM_NUMBER, [self])
        await asyncio.sleep(0.05)
        handler.assert_called_once_with(TOTALLY_RANDOM_NUMBER, [self, a])

    @async_test
    async def test_magic_origin_passing(self) -> None:
        a = ExampleSubscribable(int)
        b = ExampleWritable(int)

        @a.trigger
        @base.handler()
        async def test_handler(value, _origin) -> None:
            await b.write(value)

        await a.publish(TOTALLY_RANDOM_NUMBER, [self])
        await asyncio.sleep(0.05)
        b._write.assert_called_once_with(TOTALLY_RANDOM_NUMBER, [self, a, test_handler])

    @async_test
    async def test_reset_origin(self) -> None:
        a = ExampleSubscribable(int)
        b = ExampleWritable(int)

        @a.trigger
        @base.handler(reset_origin=True)
        async def test_handler(value, _origin) -> None:
            await b.write(value)

        await a.publish(TOTALLY_RANDOM_NUMBER, [self])
        await asyncio.sleep(0.05)
        b._write.assert_called_once_with(TOTALLY_RANDOM_NUMBER, [test_handler])

    @async_test
    async def test_no_recursion(self) -> None:
        a = LockedIntRepublisher()  # locking is irrelevant here since we use async triggering
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
    async def test_allow_recursion(self) -> None:
        a = LockedIntRepublisher()  # locking is irrelevant here since we use async triggering
        self.call_counter = 0

        @a.trigger
        @base.handler(allow_recursion=True)
        async def another_test_handler(value, _origin):
            self.call_counter += 1
            if value > TOTALLY_RANDOM_NUMBER:
                return
            await a.write(value + 1)

        await another_test_handler(TOTALLY_RANDOM_NUMBER, [])
        await asyncio.sleep(0.05)
        self.assertEqual(2, self.call_counter)

    @async_test
    async def test_error_handling(self) -> None:
        a = ExampleSubscribable(int)
        mock = AsyncMock(side_effect=RuntimeError("Really unexpected error in _write"))

        @a.trigger
        @base.handler()
        async def test_handler(value, _origin) -> None:
            await mock()

        with self.assertLogs(level=logging.ERROR) as ctx:
            await a.publish(TOTALLY_RANDOM_NUMBER, [self])
            await asyncio.sleep(0.05)
        self.assertIn("unexpected error in _write", "\n".join(ctx.output))

    # TODO add test for synchronous triggers


class TestBlockingHandler(unittest.TestCase):
    @async_test
    async def test_basic_trigger(self) -> None:
        a = ExampleSubscribable(int)
        thread_id_container = []

        def save_thread(*args):
            thread_id_container.append(threading.get_ident())

        handler = unittest.mock.Mock(side_effect=save_thread)
        handler.__name__ = "handler_mock"
        wrapped_handler = base.blocking_handler()(handler)  # type: ignore
        a.trigger(wrapped_handler)
        await a.publish(TOTALLY_RANDOM_NUMBER, [self])
        await asyncio.sleep(0.05)
        handler.assert_called_once_with(TOTALLY_RANDOM_NUMBER, [self, a])
        self.assertIsInstance(thread_id_container[0], int)
        self.assertNotEqual(thread_id_container[0], threading.get_ident())

    @async_test
    async def test_magic_origin_receiving(self) -> None:
        a = ExampleSubscribable(int)
        mock = unittest.mock.Mock()

        @a.trigger
        @base.handler()
        async def test_handler(value, _origin) -> None:
            await blocking_test_handler(value)  # type: ignore  # MyPy doesn't get that @blocking_handler() changes args

        @base.blocking_handler()
        def blocking_test_handler(value, _origin):
            mock(value, _origin)

        await a.publish(TOTALLY_RANDOM_NUMBER, [self])
        await asyncio.sleep(0.05)
        mock.assert_called_once_with(TOTALLY_RANDOM_NUMBER, [self, a, test_handler])


class TestReading(unittest.TestCase):
    @async_test
    async def test_simple_reading(self) -> None:
        a = ExampleReadable(int, TOTALLY_RANDOM_NUMBER)
        b = ExampleReading(int, False)
        b.set_provider(a)
        result = await b.do_read()
        self.assertEqual(result, TOTALLY_RANDOM_NUMBER)

    @async_test
    async def test_type_conversion(self) -> None:
        a = ExampleReadable(int, TOTALLY_RANDOM_NUMBER)
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

    @async_test
    async def test_explicit_conversion(self) -> None:
        a = ExampleReadable(int, TOTALLY_RANDOM_NUMBER)
        b = ExampleReading(float, False)

        converter = unittest.mock.Mock(side_effect=(56.5,))

        b.set_provider(a, convert=converter)

        result = await b.do_read()
        converter.assert_called_once_with(TOTALLY_RANDOM_NUMBER)
        self.assertEqual(result, 56.5)


class DummyIntReadSubscribable(base.Readable[int], base.Subscribable[int]):
    type = int

    def __init__(self):
        super().__init__()

    async def read(self) -> int:
        pass


class DummyFloatReadingWritable(base.Reading[float], base.Writable[float]):
    is_reading_optional = False
    type = float

    def __init__(self):
        super().__init__()

    async def _write(self, value: float, origin: List[Any]):
        pass


class DummyIntWrapper(base.ConnectableWrapper[int]):
    type = int
    connect: unittest.mock.Mock  # required to let MyPy know that we can use Mock's methods

    def __init__(self):
        self.connect = unittest.mock.Mock()

    def connect(self, *args, **kwargs) -> "DummyIntWrapper": ...  # type: ignore


class TestConnecting(unittest.TestCase):
    def test_subscribing(self) -> None:
        a = ExampleSubscribable(int)
        b = ExampleWritable(int)

        with unittest.mock.patch.object(a, 'subscribe') as mock_subscribe:
            a.connect(b, receive=False)  # `read` should not have an effect here
            mock_subscribe.assert_called_once_with(b, convert=False, sync=unittest.mock.ANY)

            mock_subscribe.reset_mock()
            b.connect(a, send=False)  # `provide` should not have an effect here
            mock_subscribe.assert_called_once_with(b, convert=False, sync=unittest.mock.ANY)

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

    def test_mandatory_reading(self) -> None:
        a = ExampleReadable(int, TOTALLY_RANDOM_NUMBER)
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

    def test_optional_reading(self) -> None:
        a = ExampleReadable(int, TOTALLY_RANDOM_NUMBER)
        b = ExampleReading(int, True)

        with unittest.mock.patch.object(b, 'set_provider') as mock_set_provider:
            a.connect(b)
            mock_set_provider.assert_not_called()

            mock_set_provider.reset_mock()
            b.connect(a, read=True)
            mock_set_provider.assert_called_once_with(a, convert=False)

    # TODO test None return values of _from_provider

    def test_type_conversion(self) -> None:
        a = DummyIntReadSubscribable()
        b = DummyFloatReadingWritable()

        with self.assertRaises(TypeError):
            a.connect(b)

        with self.assertRaises(TypeError):
            b.connect(a)

        with unittest.mock.patch.object(a, 'subscribe') as mock_subscribe,\
                unittest.mock.patch.object(b, 'set_provider') as mock_set_provider:
            a.connect(b, convert=True)
            mock_subscribe.assert_called_once_with(b, convert=True, sync=unittest.mock.ANY)
            mock_set_provider.assert_called_once_with(a, convert=True)

            mock_subscribe.reset_mock()
            mock_set_provider.reset_mock()
            b.connect(a, convert=True)
            mock_subscribe.assert_called_once_with(b, convert=True, sync=unittest.mock.ANY)
            mock_set_provider.assert_called_once_with(a, convert=True)

    def test_explict_conversion(self) -> None:
        a = DummyIntReadSubscribable()
        b = DummyFloatReadingWritable()

        def a2b(x: int) -> float:
            return float(x/255)

        def b2a(x: float) -> int:
            return round(x*255)

        with unittest.mock.patch.object(a, 'subscribe') as mock_subscribe,\
                unittest.mock.patch.object(b, 'set_provider') as mock_set_provider:
            a.connect(b, convert=(a2b, b2a))
            mock_subscribe.assert_called_once_with(b, convert=a2b, sync=unittest.mock.ANY)
            mock_set_provider.assert_called_once_with(a, convert=a2b)

            mock_subscribe.reset_mock()
            mock_set_provider.reset_mock()
            b.connect(a, convert=(b2a, a2b))
            mock_subscribe.assert_called_once_with(b, convert=a2b, sync=unittest.mock.ANY)
            mock_set_provider.assert_called_once_with(a, convert=a2b)

    def test_connectable_wrapper(self) -> None:
        a = DummyIntReadSubscribable()
        b = DummyIntWrapper()

        def a2b(x: int) -> int:
            return x*2

        def b2a(x: int) -> int:
            return x//2

        a.connect(b, read=False, provide=True, convert=True)
        b.connect.assert_called_once_with(a, send=None, receive=None, read=True, provide=False, convert=True)

        b.connect.reset_mock()
        a.connect(b, send=False, receive=True, convert=(a2b, b2a))
        b.connect.assert_called_once_with(a, send=True, receive=False, read=None, provide=None, convert=(b2a, a2b))
