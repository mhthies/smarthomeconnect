import asyncio
import datetime
import unittest
import unittest.mock
from typing import Optional, List

from shc import timer, base
from ._helper import ClockMock, async_test, ExampleSubscribable, AsyncMock


class LogarithmicSleepTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
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

    class TestTimer(timer._AbstractScheduleTimer):
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
        expected_events = [datetime.datetime(2020, 8, 20, 21, 8, 2).astimezone(),
                           datetime.datetime(2020, 8, 20, 22, 0, 0).astimezone()]
        events = []

        async def store_time(*args, **kwargs):
            events.append(clock_mock.now().astimezone())

        t = self.TestTimer(expected_events)
        with unittest.mock.patch('shc.timer._AbstractScheduleTimer._publish', new=store_time):
            with clock_mock:
                await t.run()
        await asyncio.sleep(0.01)  # Allow async tasks to run to make sure all _publish tasks have been executed
        self.assertListEqual(expected_events, events)

        assert(t.last_execution is not None)
        self.assertAlmostEqual(t.last_execution,
                               expected_events[-1],
                               delta=datetime.timedelta(seconds=1))


class TimerDecoratorText(unittest.TestCase):
    def test_decorators(self) -> None:
        for decorator, timer_class, attr in ((timer.every, timer.Every, {'delta': datetime.timedelta(seconds=5)}),
                                             (timer.once, timer.Once, {'offset': datetime.timedelta(seconds=7)}),
                                             (timer.at, timer.At, {'random': datetime.timedelta(seconds=20)}),):
            with self.subTest(decorator=decorator.__name__):
                async def my_function(_val, _origin):
                    return

                with unittest.mock.patch('shc.base.Subscribable.trigger',
                                         autospec=True, side_effect=lambda s, t: t) as trigger_mock:
                    returned = decorator(**attr)(my_function)

                trigger_mock.assert_called_once()
                self.assertIsInstance(trigger_mock.call_args[0][0], timer_class)
                for attr_name, attr_value in attr.items():
                    self.assertEqual(getattr(trigger_mock.call_args[0][0], attr_name), attr_value)
                self.assertIs(trigger_mock.call_args[0][1], my_function)
                self.assertIs(trigger_mock.call_args[0][1], returned)


class EveryTimerTest(unittest.TestCase):
    def test_unaligned(self) -> None:
        with ClockMock(datetime.datetime(2020, 1, 1, 15, 7, 17)) as clock:
            every_timer = timer.Every(datetime.timedelta(minutes=5), align=False)
            next_execution = every_timer._next_execution()
            assert(next_execution is not None)
            self.assertAlmostEqual(clock.now().astimezone(), next_execution,
                                   delta=datetime.timedelta(seconds=1))
            every_timer.last_execution = clock.now().astimezone()
            next_execution = every_timer._next_execution()
            assert(next_execution is not None)
            self.assertAlmostEqual(clock.now().astimezone() + datetime.timedelta(minutes=5), next_execution,
                                   delta=datetime.timedelta(seconds=1))
            clock.sleep(5 * 60)
            every_timer.last_execution = clock.now().astimezone()
            next_execution = every_timer._next_execution()
            assert(next_execution is not None)
            self.assertAlmostEqual(clock.now().astimezone() + datetime.timedelta(minutes=5), next_execution,
                                   delta=datetime.timedelta(seconds=1))

    def test_unaligned_random(self) -> None:
        with ClockMock(datetime.datetime(2020, 1, 1, 15, 7, 17)) as clock:
            every_timer = timer.Every(datetime.timedelta(minutes=5), align=False, random=datetime.timedelta(seconds=20))
            self.assertGreaterEqual(every_timer._next_execution(),
                                    clock.now().astimezone() - datetime.timedelta(seconds=20))
            self.assertLessEqual(every_timer._next_execution(),
                                 clock.now().astimezone() + datetime.timedelta(seconds=20))
            every_timer.last_execution = clock.now().astimezone()
            self.assertGreaterEqual(every_timer._next_execution(),
                                    clock.now().astimezone() + datetime.timedelta(minutes=5, seconds=-20))
            self.assertLessEqual(every_timer._next_execution(),
                                 clock.now().astimezone() + datetime.timedelta(minutes=5, seconds=20))
            clock.sleep(5 * 60 + 20)
            every_timer.last_execution = clock.now().astimezone()
            self.assertGreaterEqual(every_timer._next_execution(),
                                    clock.now().astimezone() + datetime.timedelta(minutes=5, seconds=-20))
            self.assertLessEqual(every_timer._next_execution(),
                                 clock.now().astimezone() + datetime.timedelta(minutes=5, seconds=20))
    
    def test_aligned(self) -> None:
        with ClockMock(datetime.datetime(2020, 1, 1, 15, 7, 17)) as clock:
            every_timer = timer.Every(datetime.timedelta(minutes=5), align=True)
            base = every_timer._next_execution()
            assert(base is not None)
            self.assertGreaterEqual(base - clock.now().astimezone(), datetime.timedelta(0))
            self.assertLessEqual(base - clock.now().astimezone(), datetime.timedelta(minutes=5))

            clock.current_time = base + datetime.timedelta(microseconds=1)  # We slept till the first execution
            next_execution = every_timer._next_execution()
            assert(next_execution is not None)
            self.assertAlmostEqual(clock.now().astimezone() + datetime.timedelta(minutes=5),
                                   next_execution,
                                   delta=datetime.timedelta(seconds=1))

        # A new timer (after a restart 5 minutes later) should give us exactly base + 5 minutes as the first execution
        with ClockMock(datetime.datetime(2020, 1, 1, 15, 7, 17) + datetime.timedelta(minutes=5)) as clock:
            every_timer = timer.Every(datetime.timedelta(minutes=5), align=True)
            next_execution = every_timer._next_execution()
            assert(next_execution is not None)
            self.assertAlmostEqual(base + datetime.timedelta(minutes=5),
                                   next_execution,
                                   delta=datetime.timedelta(seconds=1))


class OnceTimerTest(unittest.TestCase):
    def test_immediate(self) -> None:
        with ClockMock(datetime.datetime(2020, 1, 1, 15, 7, 17)) as clock:
            once_timer = timer.Once()
            next_execution = once_timer._next_execution()
            assert(next_execution is not None)
            self.assertAlmostEqual(clock.now().astimezone(), next_execution,
                                   delta=datetime.timedelta(seconds=1))
            clock.sleep(1)
            once_timer.last_execution = clock.now().astimezone()
            self.assertIsNone(once_timer._next_execution())

    def test_offset(self) -> None:
        with ClockMock(datetime.datetime(2020, 1, 1, 15, 7, 17)) as clock:
            once_timer = timer.Once(datetime.timedelta(hours=1))
            next_execution = once_timer._next_execution()
            assert(next_execution is not None)
            self.assertAlmostEqual(clock.now().astimezone() + datetime.timedelta(hours=1), next_execution,
                                   delta=datetime.timedelta(seconds=1))
            clock.sleep(60*60)
            once_timer.last_execution = clock.now().astimezone()
            self.assertIsNone(once_timer._next_execution())

    def test_offset_random(self) -> None:
        with ClockMock(datetime.datetime(2020, 1, 1, 15, 7, 17)) as clock:
            once_timer = timer.Once(datetime.timedelta(hours=1), random=datetime.timedelta(seconds=20))
            next_execution = once_timer._next_execution()
            self.assertGreaterEqual(next_execution,
                                    clock.now().astimezone() + datetime.timedelta(hours=1, seconds=-20))
            self.assertLessEqual(next_execution,
                                 clock.now().astimezone() + datetime.timedelta(hours=1, seconds=20))
            clock.sleep(60*60)
            once_timer.last_execution = clock.now().astimezone()
            self.assertIsNone(once_timer._next_execution())


class AtTimerTest(unittest.TestCase):
    def _assert_datetime(self, expected: datetime.datetime, actual: Optional[datetime.datetime]) -> None:
        assert(actual is not None)
        self.assertAlmostEqual(expected.astimezone(), actual, delta=datetime.timedelta(seconds=.1))

    def test_simple_next(self) -> None:
        with ClockMock(datetime.datetime(2020, 1, 1, 15, 7, 17)) as clock:
            once_timer = timer.At(hour=15, minute=7, second=17, millis=200)
            self._assert_datetime(datetime.datetime(2020, 1, 1, 15, 7, 17, 200000), once_timer._next_execution())
            once_timer = timer.At(hour=15, minute=7, second=25)
            self._assert_datetime(datetime.datetime(2020, 1, 1, 15, 7, 25), once_timer._next_execution())
            once_timer = timer.At(hour=15, minute=12)
            self._assert_datetime(datetime.datetime(2020, 1, 1, 15, 12, 0), once_timer._next_execution())
            once_timer = timer.At(hour=16)
            self._assert_datetime(datetime.datetime(2020, 1, 1, 16, 0, 0), once_timer._next_execution())
            once_timer = timer.At(day=19)
            self._assert_datetime(datetime.datetime(2020, 1, 19, 0, 0, 0), once_timer._next_execution())
            once_timer = timer.At(month=8)
            self._assert_datetime(datetime.datetime(2020, 8, 1, 0, 0, 0), once_timer._next_execution())
            once_timer = timer.At(year=2021)
            self._assert_datetime(datetime.datetime(2021, 1, 1, 0, 0, 0), once_timer._next_execution())
            once_timer = timer.At(weekday=5)
            self._assert_datetime(datetime.datetime(2020, 1, 3, 0, 0, 0), once_timer._next_execution())
            once_timer = timer.At(weeknum=15)
            self._assert_datetime(datetime.datetime(2020, 4, 6, 0, 0, 0), once_timer._next_execution())

    def test_spec_forms(self) -> None:
        with ClockMock(datetime.datetime(2020, 1, 1, 15, 7, 17)) as clock:
            once_timer = timer.At(hour=timer.EveryNth(2))
            self._assert_datetime(datetime.datetime(2020, 1, 1, 16, 0, 0), once_timer._next_execution())
            once_timer = timer.At(hour=timer.EveryNth(6))
            self._assert_datetime(datetime.datetime(2020, 1, 1, 18, 0, 0), once_timer._next_execution())
            once_timer = timer.At(hour=[13, 17, 20])
            self._assert_datetime(datetime.datetime(2020, 1, 1, 17, 0, 0), once_timer._next_execution())
            once_timer = timer.At(hour=None, minute=18)
            self._assert_datetime(datetime.datetime(2020, 1, 1, 15, 18, 0), once_timer._next_execution())
            once_timer = timer.At(hour=timer.EveryNth(3), minute=None, second=None)
            self._assert_datetime(datetime.datetime(2020, 1, 1, 15, 7, 17), once_timer._next_execution())

    def test_stepback(self) -> None:
        with ClockMock(datetime.datetime(2020, 1, 1, 15, 7, 17)) as clock:
            once_timer = timer.At(hour=None, minute=0)
            self._assert_datetime(datetime.datetime(2020, 1, 1, 16, 0, 0), once_timer._next_execution())
            once_timer = timer.At(hour=15, minute=0)
            self._assert_datetime(datetime.datetime(2020, 1, 2, 15, 0, 0), once_timer._next_execution())
            once_timer = timer.At(month=1, day=1, hour=timer.EveryNth(15), minute=[5, 7], second=16)
            self._assert_datetime(datetime.datetime(2021, 1, 1, 0, 5, 16), once_timer._next_execution())

    def test_overflows(self) -> None:
        with ClockMock(datetime.datetime(2020, 12, 31, 23, 59, 46)) as clock:
            once_timer = timer.At(hour=None, minute=None, second=timer.EveryNth(15))
            self._assert_datetime(datetime.datetime(2021, 1, 1, 0, 0, 0), once_timer._next_execution())
        with ClockMock(datetime.datetime(2019, 2, 1, 15, 7, 17)) as clock:
            once_timer = timer.At(day=29)
            self._assert_datetime(datetime.datetime(2019, 3, 29, 0, 0, 0), once_timer._next_execution())
        with ClockMock(datetime.datetime(2020, 2, 1, 15, 7, 17)) as clock:
            once_timer = timer.At(day=29)
            self._assert_datetime(datetime.datetime(2020, 2, 29, 0, 0, 0), once_timer._next_execution())
        with ClockMock(datetime.datetime(2020, 4, 1, 15, 7, 17)) as clock:
            once_timer = timer.At(day=31)
            self._assert_datetime(datetime.datetime(2020, 5, 31, 0, 0, 0), once_timer._next_execution())
        with ClockMock(datetime.datetime(2019, 1, 1, 15, 7, 17)) as clock:
            once_timer = timer.At(weeknum=53)
            self._assert_datetime(datetime.datetime(2020, 12, 28, 0, 0, 0), once_timer._next_execution())
        with ClockMock(datetime.datetime(2020, 1, 1, 0, 0, 0)) as clock:
            once_timer = timer.At(year=2019)
            self.assertIsNone(once_timer._next_execution())

    def test_exception(self) -> None:
        with self.assertRaises(ValueError):
            once_timer = timer.At(day=[1,5,15], weeknum=timer.EveryNth(2))


class BoolTimerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        ClockMock.enable()

    @async_test
    async def test_ton(self) -> None:
        begin = datetime.datetime(2020, 12, 31, 23, 59, 46)
        call_times = []

        def save_time(*args):
            call_times.append(datetime.datetime.now())

        base = ExampleSubscribable(bool)
        ton = timer.TOn(base, datetime.timedelta(seconds=42))

        with unittest.mock.patch.object(ton, "_publish", new=AsyncMock(side_effect=save_time)) as publish_mock:
            with ClockMock(begin, actual_sleep=0.05) as clock:
                self.assertFalse(await ton.read())

                # False should not be forwarded, when value is already False
                await base.publish(False, [self])
                await asyncio.sleep(0.01)
                publish_mock.assert_not_called()

                # True should be forwarded with delay
                await base.publish(True, [self])
                await asyncio.sleep(45)
                publish_mock.assert_called_with(True, unittest.mock.ANY)
                self.assertAlmostEqual(begin + datetime.timedelta(seconds=42.01), call_times[-1],
                                       delta=datetime.timedelta(seconds=.01))

                # False should now be forwarded immediately
                publish_mock.reset_mock()
                await base.publish(False, [self])
                await asyncio.sleep(0.01)
                publish_mock.assert_called_with(False, unittest.mock.ANY)

                # True delay should be suppressable with False ...
                publish_mock.reset_mock()
                await base.publish(True, [self])
                await asyncio.sleep(20)
                await base.publish(False, [self])
                await asyncio.sleep(30)
                publish_mock.assert_not_called()

                # ... and not extendable with True
                publish_mock.reset_mock()
                tic = datetime.datetime.now()
                await base.publish(True, [self])
                await asyncio.sleep(20)
                await base.publish(True, [self])
                await asyncio.sleep(30)
                publish_mock.assert_called_with(True, unittest.mock.ANY)
                self.assertAlmostEqual(tic + datetime.timedelta(seconds=42), call_times[-1],
                                       delta=datetime.timedelta(seconds=.01))

    @async_test
    async def test_toff(self) -> None:
        begin = datetime.datetime(2020, 12, 31, 23, 59, 46)
        call_times = []

        def save_time(*args):
            call_times.append(datetime.datetime.now())

        base = ExampleSubscribable(bool)
        toff = timer.TOff(base, datetime.timedelta(seconds=42))

        with unittest.mock.patch.object(toff, "_publish", new=AsyncMock(side_effect=save_time)) as publish_mock:
            with ClockMock(begin, actual_sleep=0.05) as clock:
                self.assertFalse(await toff.read())

                # False should not be forwarded, when value is already False
                await base.publish(False, [self])
                await asyncio.sleep(0.01)
                publish_mock.assert_not_called()

                # True should be forwarded with immediately
                await base.publish(True, [self])
                await asyncio.sleep(0.01)
                publish_mock.assert_called_with(True, unittest.mock.ANY)

                # False should now be forwarded with delay
                publish_mock.reset_mock()
                await base.publish(False, [self])
                await asyncio.sleep(45)
                publish_mock.assert_called_with(False, unittest.mock.ANY)
                self.assertAlmostEqual(begin + datetime.timedelta(seconds=42.01), call_times[-1],
                                       delta=datetime.timedelta(seconds=.01))

                # False delay should be suppressable with True ...
                await base.publish(True, [self])
                await asyncio.sleep(0.01)
                publish_mock.reset_mock()
                await base.publish(False, [self])
                await asyncio.sleep(20)
                await base.publish(True, [self])
                await asyncio.sleep(30)
                publish_mock.assert_not_called()

                # ... and not extendable with False
                publish_mock.reset_mock()
                tic = datetime.datetime.now()
                await base.publish(False, [self])
                await asyncio.sleep(20)
                await base.publish(False, [self])
                await asyncio.sleep(30)
                publish_mock.assert_called_with(False, unittest.mock.ANY)
                self.assertAlmostEqual(tic + datetime.timedelta(seconds=42), call_times[-1],
                                       delta=datetime.timedelta(seconds=.01))

    @async_test
    async def test_pulse(self) -> None:
        begin = datetime.datetime(2020, 12, 31, 23, 59, 46)
        call_times = []

        def save_time(*args):
            call_times.append(datetime.datetime.now())

        base = ExampleSubscribable(bool)
        tpulse = timer.TPulse(base, datetime.timedelta(seconds=42))

        with unittest.mock.patch.object(tpulse, "_publish", new=AsyncMock(side_effect=save_time)) as publish_mock:
            with ClockMock(begin, actual_sleep=0.05) as clock:
                self.assertFalse(await tpulse.read())

                # False should not be forwarded
                await base.publish(False, [self])
                await asyncio.sleep(0.01)
                publish_mock.assert_not_called()

                # True should be forwarded with immediately and automatically result in a later False
                await base.publish(True, [self])
                await asyncio.sleep(0.01)
                publish_mock.assert_called_with(True, unittest.mock.ANY)
                await asyncio.sleep(45)
                self.assertEqual(2, publish_mock.call_count)
                publish_mock.assert_called_with(False, unittest.mock.ANY)
                self.assertAlmostEqual(begin + datetime.timedelta(seconds=42.01), call_times[-1],
                                       delta=datetime.timedelta(seconds=.01))

                # Pulse should not be stoppable with False
                publish_mock.reset_mock()
                start = clock.now()
                await base.publish(True, [self])
                await asyncio.sleep(0.01)
                publish_mock.assert_called_with(True, unittest.mock.ANY)
                await asyncio.sleep(20)
                await base.publish(False, [self])
                await asyncio.sleep(0.01)
                self.assertEqual(1, publish_mock.call_count)
                await asyncio.sleep(45)
                self.assertEqual(2, publish_mock.call_count)
                publish_mock.assert_called_with(False, unittest.mock.ANY)
                self.assertAlmostEqual(start + datetime.timedelta(seconds=42.01), call_times[-1],
                                       delta=datetime.timedelta(seconds=.01))

                # ... or extendable with True
                publish_mock.reset_mock()
                start = clock.now()
                await base.publish(True, [self])
                await asyncio.sleep(0.01)
                publish_mock.assert_called_with(True, unittest.mock.ANY)
                await asyncio.sleep(20)
                await base.publish(True, [self])
                await asyncio.sleep(0.01)
                self.assertEqual(1, publish_mock.call_count)
                await asyncio.sleep(45)
                self.assertEqual(2, publish_mock.call_count)
                publish_mock.assert_called_with(False, unittest.mock.ANY)
                self.assertAlmostEqual(start + datetime.timedelta(seconds=42.01), call_times[-1],
                                       delta=datetime.timedelta(seconds=.01))
