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
        sub._write.assert_not_called()

        await pub.write(42.0, [self])
        sub._write.assert_called_once_with(42.0, [self, pub, unittest.mock.ANY])

        sub._write.reset_mock()
        await control.write(False, [self])
        await pub.write(56.0, [self])
        sub._write.assert_not_called()

        await control.write(True, [self])
        sub._write.assert_called_once_with(56.0, [self, control, unittest.mock.ANY])
