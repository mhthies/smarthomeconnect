import asyncio
import datetime
import unittest
import unittest.mock
from typing import Optional, List

from shc import timer, base
from ._helper import ClockMock, async_test


class LogarithmicSleepTest(unittest.TestCase):
    def setUp(self) -> None:
        ClockMock.enable()

    @async_test
    async def test_long_sleep(self) -> None:
        with ClockMock(datetime.datetime(2020, 1, 1, 15, 0, 0)) as clock:
            await timer._logarithmic_sleep(datetime.datetime(2020, 1, 17, 18, 5, 13).astimezone())
            self.assertEqual(datetime.datetime(2020, 1, 17, 18, 5, 13), clock.now())

    @async_test
    async def test_short_sleep(self) -> None:
        with ClockMock(datetime.datetime(2020, 1, 1, 15, 0, 0)) as clock:
            await timer._logarithmic_sleep(datetime.datetime(2020, 1, 1, 15, 0, 1, 17600).astimezone())
            self.assertEqual(datetime.datetime(2020, 1, 1, 15, 0, 1, 17600), clock.now())

    @async_test
    async def test_sleep_overshoot(self) -> None:
        with ClockMock(datetime.datetime(2020, 1, 1, 15, 0, 0), datetime.timedelta(microseconds=27600)) as clock:
            await timer._logarithmic_sleep(datetime.datetime(2020, 1, 1, 18, 37, 10).astimezone())
            miss_by = clock.now() - datetime.datetime(2020, 1, 1, 18, 37, 10)
            self.assertGreaterEqual(miss_by, datetime.timedelta(0))
            self.assertLess(miss_by, 2 * datetime.timedelta(microseconds=27600))

    @async_test
    async def test_negative_delay(self) -> None:
        with ClockMock(datetime.datetime(2020, 1, 1, 15, 0, 0)) as clock:
            await timer._logarithmic_sleep(datetime.datetime(2020, 1, 1, 14, 59, 25).astimezone())
            self.assertEqual(datetime.datetime(2020, 1, 1, 15, 0, 0), clock.now())


class AbstractTimerTest(unittest.TestCase):
    def setUp(self):
        ClockMock.enable()

    class TestTimer(timer._AbstractTimer):
        def __init__(self, times: List[datetime.datetime]):
            super().__init__()
            self.times = times
            self.index = -1

        def _next_execution(self) -> Optional[datetime.datetime]:
            self.index += 1
            if self.index >= len(self.times):
                return None
            return self.times[self.index]

    @async_test
    async def test_run(self) -> None:
        clock_mock = ClockMock(datetime.datetime(2020, 8, 20, 21, 8, 0), actual_sleep=0.01)
        expected_events = [datetime.datetime(2020, 8, 20, 21, 8, 2).astimezone(), datetime.datetime(2020, 8, 20, 22, 0, 0).astimezone()]
        events = []

        async def store_time(*args, **kwargs):
            events.append(clock_mock.now().astimezone())

        t = self.TestTimer(expected_events)
        with unittest.mock.patch('shc.timer._AbstractTimer._publish', new=store_time):
            with clock_mock:
                await t.run()
        await asyncio.sleep(0.01)  # Allow async tasks to run to make sure all _publish tasks have been executed
        self.assertListEqual(expected_events, events)


class EveryTimerTest(unittest.TestCase):
    def test_decorator(self) -> None:
        async def my_function(_val, _origin):
            return

        with unittest.mock.patch('shc.base.Subscribable.trigger',
                                 autospec=True, side_effect=lambda s, t: t) as trigger_mock:
            returned = timer.every(datetime.timedelta(seconds=5))(my_function)

        trigger_mock.assert_called_once()
        self.assertIsInstance(trigger_mock.call_args[0][0], timer.Every)
        self.assertEqual(trigger_mock.call_args[0][0].delta, datetime.timedelta(seconds=5))
        self.assertIs(trigger_mock.call_args[0][1], my_function)
        self.assertIs(trigger_mock.call_args[0][1], returned)
