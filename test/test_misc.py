import asyncio
import unittest
import unittest.mock

import shc.misc
from test._helper import ExampleSubscribable, ExampleWritable, async_test, ExampleReadable


class MiscTests(unittest.TestCase):

    @async_test
    async def test_two_way_pipe(self) -> None:
        pipe = shc.misc.TwoWayPipe(float)

        pub_left = ExampleSubscribable(float)
        pub_right = ExampleSubscribable(float)
        sub_left = ExampleWritable(float)
        sub_right = ExampleWritable(float)

        pipe.connect_left(pub_left)
        sub_left.connect(pipe)
        pipe.connect_right(pub_right)
        pipe.connect_right(sub_right)

        await pub_left.publish(42.0, [self])
        sub_right._write.assert_called_once_with(42.0, [self, pub_left, pipe.right])
        sub_left._write.assert_not_called()

        sub_right._write.reset_mock()
        await pub_right.publish(36.0, [self])
        sub_left._write.assert_called_once_with(36.0, [self, pub_right, pipe.left])
        sub_right._write.assert_not_called()

    @async_test
    async def test_two_way_pipe_concurrent_update(self) -> None:
        var1 = shc.Variable(int)
        pipe = shc.misc.TwoWayPipe(int).connect_left(var1)
        var2 = shc.Variable(int).connect(pipe.right)

        await asyncio.gather(var1.write(42, []), var2.write(56, []))
        self.assertEqual(await var1.read(), await var2.read())

    @async_test
    async def test_breakable_subscription_simple(self) -> None:
        pub = ExampleSubscribable(float)
        control = ExampleReadable(bool, True)
        sub = ExampleWritable(float)

        sub.connect(shc.misc.BreakableSubscription(pub, control))

        await pub.publish(42.0, [self])
        sub._write.assert_called_once_with(42.0, [self, pub, unittest.mock.ANY])

        sub._write.reset_mock()
        control.read.side_effect = (False,)
        await pub.publish(36.0, [self])
        sub._write.assert_not_called()

        sub._write.reset_mock()
        control.read.side_effect = (True,)
        await pub.publish(56.0, [self])
        sub._write.assert_called_once_with(56, unittest.mock.ANY)

    @async_test
    async def test_breakable_subscription_readsubscribable(self) -> None:
        pub = shc.Variable(float)
        control = shc.Variable(bool, initial_value=False)
        sub = ExampleWritable(float)

        sub.connect(shc.misc.BreakableSubscription(pub, control))

        # pub is uninitialized, so we should not receive anything, when control changes to True
        await control.write(True, [self])
        await asyncio.sleep(0.01)
        sub._write.assert_not_called()

        await pub.write(42.0, [self])
        await asyncio.sleep(0.01)
        sub._write.assert_called_once_with(42.0, [self, pub, unittest.mock.ANY])

        sub._write.reset_mock()
        await control.write(False, [self])
        await pub.write(56.0, [self])
        await asyncio.sleep(0.01)
        sub._write.assert_not_called()

        await control.write(True, [self])
        await asyncio.sleep(0.01)
        sub._write.assert_called_once_with(56.0, [self, control, unittest.mock.ANY])

    @async_test
    async def test_hysteresis(self) -> None:
        pub = ExampleSubscribable(float)
        hystersis = shc.misc.Hysteresis(pub, 42.0, 56.0)
        sub = ExampleWritable(bool).connect(hystersis)

        # Check initial value
        self.assertEqual(False, await hystersis.read())

        # Check climbing value
        await pub.publish(41.0, [self])
        await pub.publish(43.5, [self])
        await pub.publish(44.5, [self])
        self.assertEqual(False, await hystersis.read())
        sub._write.assert_not_called()

        await pub.publish(57.4, [self])
        sub._write.assert_called_once_with(True, [self, pub, hystersis])
        self.assertEqual(True, await hystersis.read())

        sub._write.reset_mock()
        await pub.publish(58, [self])
        sub._write.assert_not_called()
        self.assertEqual(True, await hystersis.read())

        # Check descending value
        await pub.publish(44.5, [self])
        self.assertEqual(True, await hystersis.read())
        sub._write.assert_not_called()

        await pub.publish(41.4, [self])
        sub._write.assert_called_once_with(False, [self, pub, hystersis])
        self.assertEqual(False, await hystersis.read())

        sub._write.reset_mock()
        await pub.publish(40.0, [self])
        sub._write.assert_not_called()
        self.assertEqual(False, await hystersis.read())

        # Check jumps
        await pub.publish(57.4, [self])
        sub._write.assert_called_once_with(True, [self, pub, hystersis])
        self.assertEqual(True, await hystersis.read())
        sub._write.reset_mock()
        await pub.publish(41.4, [self])
        sub._write.assert_called_once_with(False, [self, pub, hystersis])
        self.assertEqual(False, await hystersis.read())

    @async_test
    async def test_fade_step_adapter(self) -> None:
        subscribable1 = ExampleSubscribable(shc.datatypes.FadeStep)
        variable1 = shc.Variable(shc.datatypes.RangeFloat1)\
            .connect(shc.misc.FadeStepAdapter(subscribable1))

        with self.assertLogs() as logs:
            await subscribable1.publish(shc.datatypes.FadeStep(0.5), [self])
            await asyncio.sleep(0.05)
        self.assertIn("Cannot apply FadeStep", logs.records[0].msg)  # type: ignore

        await variable1.write(shc.datatypes.RangeFloat1(0.5), [self])
        await asyncio.sleep(0.05)

        await subscribable1.publish(shc.datatypes.FadeStep(0.25), [self])
        await asyncio.sleep(0.05)
        self.assertEqual(shc.datatypes.RangeFloat1(0.75), await variable1.read())

        await subscribable1.publish(shc.datatypes.FadeStep(0.5), [self])
        await asyncio.sleep(0.05)
        self.assertEqual(shc.datatypes.RangeFloat1(1.0), await variable1.read())

    @async_test
    async def test_convert_subscription(self) -> None:
        pub = ExampleSubscribable(shc.datatypes.RangeUInt8)
        sub = ExampleWritable(shc.datatypes.RangeFloat1)

        sub.connect(shc.misc.ConvertSubscription(pub, shc.datatypes.RangeFloat1))

        await pub.publish(shc.datatypes.RangeUInt8(255), [self])
        sub._write.assert_called_once_with(shc.datatypes.RangeFloat1(1.0), [self, pub, unittest.mock.ANY])
        self.assertIsInstance(sub._write.call_args[0][0], shc.datatypes.RangeFloat1)
