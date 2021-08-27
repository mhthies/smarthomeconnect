import asyncio
import unittest
import unittest.mock

from shc.interfaces import ping
from test._helper import async_test, ExampleSubscribable, ExampleWritable


class PingTest(unittest.TestCase):
    @async_test
    async def test_ping(self) -> None:
        timer_mock = ExampleSubscribable(type(None))
        with unittest.mock.patch('shc.interfaces.ping.Every', return_value=timer_mock):
            ping_localhost1 = ping.Ping("localhost", number=3, timeout=0.5)
            ping_localhost2 = ping.Ping("127.0.0.1", number=3, timeout=0.5)
            ping_unreachable = ping.Ping("192.0.2.0", number=3, timeout=0.5)
            ping_non_existent = ping.Ping("this-host-does-defiantly-not-exist.mhthies.de", number=3, timeout=0.5)
        target_1 = ExampleWritable(bool).connect(ping_localhost1)
        target_2 = ExampleWritable(bool).connect(ping_localhost2)
        target_3 = ExampleWritable(bool).connect(ping_unreachable)
        target_4 = ExampleWritable(bool).connect(ping_non_existent)
        await timer_mock.publish(None, [self])
        await asyncio.sleep(3.5)
        target_1._write.assert_called_once_with(True, [ping_localhost1])
        target_2._write.assert_called_once_with(True, [ping_localhost2])
        target_3._write.assert_called_once_with(False, [ping_unreachable])
        target_4._write.assert_called_once_with(False, [ping_non_existent])
