import asyncio
import datetime
import unittest
from typing import List, Tuple, Generic, Type, Iterable, Any

import shc.data_logging
from shc.base import T, UninitializedError, Readable
from ._helper import async_test, ClockMock

time_series_1 = [
    (datetime.datetime(2020, 1, 1, 0, 0, 0), 20.0),
    (datetime.datetime(2020, 1, 1, 0, 0, 5), 40.0),
    (datetime.datetime(2020, 1, 1, 0, 0, 15), 20.0),
    (datetime.datetime(2020, 1, 1, 0, 0, 26), 40.0),
    (datetime.datetime(2020, 1, 1, 0, 0, 27), 40.0),
    (datetime.datetime(2020, 1, 1, 0, 0, 35), 20.0),
]
time_series_2 = [
    (datetime.datetime(2020, 1, 1, 0, 0, 0), False),
    (datetime.datetime(2020, 1, 1, 0, 0, 5), True),
    (datetime.datetime(2020, 1, 1, 0, 0, 15), False),
    (datetime.datetime(2020, 1, 1, 0, 0, 26), True),
    (datetime.datetime(2020, 1, 1, 0, 0, 27), True),
    (datetime.datetime(2020, 1, 1, 0, 0, 35), False),
]


class ExampleLogVariable(shc.data_logging.DataLogVariable[T], Generic[T]):
    def __init__(self, time_series: List[Tuple[datetime.datetime, T]]):
        self.type = type(time_series[0][1])
        self.data = time_series

    async def retrieve_log(self, start_time: datetime.datetime, end_time: datetime.datetime,
                           include_previous: bool = True) -> List[Tuple[datetime.datetime, T]]:
        return self.data


class LiveDataLogViewMock:
    def __init__(self):
        self.result = []

    async def _new_log_values_written(self, values: List[Tuple[datetime.datetime, Any]]) -> None:
        self.result.extend(values)


class AbstractLoggingTest(unittest.TestCase):
    do_write_tests: bool = False
    do_subscribe_tests: bool = False

    # Override this method in a derived test case class to run these tests for an actual DataLogVariable implementation
    async def _create_log_variable_with_data(self, _type: Type[T], data: Iterable[Tuple[datetime.datetime, T]]) \
            -> shc.data_logging.DataLogVariable[T]:
        return ExampleLogVariable(list(data))

    @async_test
    async def test_maxmin_aggregation(self) -> None:
        variable = await self._create_log_variable_with_data(float, time_series_1)
        result = await variable.retrieve_aggregated_log(start_time=datetime.datetime(2020, 1, 1, 0, 0, 10),
                                                        end_time=datetime.datetime(2020, 1, 1, 0, 0, 30),
                                                        aggregation_method=shc.data_logging.AggregationMethod.MAXIMUM,
                                                        aggregation_interval=datetime.timedelta(seconds=10))
        self.assertEqual(2, len(result))
        self.assertAlmostEqual(40.0, result[0][1])
        self.assertAlmostEqual(40.0, result[1][1])
        self.assertAlmostEqual(datetime.datetime(2020, 1, 1, 0, 0, 10), result[0][0],
                               delta=datetime.timedelta(milliseconds=10))
        self.assertAlmostEqual(datetime.datetime(2020, 1, 1, 0, 0, 20), result[1][0],
                               delta=datetime.timedelta(milliseconds=10))

        result = await variable.retrieve_aggregated_log(start_time=datetime.datetime(2020, 1, 1, 0, 0, 30),
                                                        end_time=datetime.datetime(2020, 1, 1, 0, 0, 50),
                                                        aggregation_method=shc.data_logging.AggregationMethod.MINIMUM,
                                                        aggregation_interval=datetime.timedelta(seconds=10))
        self.assertEqual(2, len(result))
        self.assertAlmostEqual(20.0, result[0][1])

        result = await variable.retrieve_aggregated_log(start_time=datetime.datetime(2020, 1, 1, 0, 0, 0),
                                                        end_time=datetime.datetime(2020, 1, 1, 0, 0, 10),
                                                        aggregation_method=shc.data_logging.AggregationMethod.MINIMUM,
                                                        aggregation_interval=datetime.timedelta(seconds=10))
        self.assertEqual(1, len(result))
        self.assertAlmostEqual(20.0, result[0][1])

    @async_test
    async def test_average_aggregation(self) -> None:
        variable = await self._create_log_variable_with_data(float, time_series_1)
        result = await variable.retrieve_aggregated_log(start_time=datetime.datetime(2020, 1, 1, 0, 0, 10),
                                                        end_time=datetime.datetime(2020, 1, 1, 0, 0, 30),
                                                        aggregation_method=shc.data_logging.AggregationMethod.AVERAGE,
                                                        aggregation_interval=datetime.timedelta(seconds=10))
        self.assertEqual(2, len(result))
        self.assertAlmostEqual(30.0, result[0][1])
        self.assertAlmostEqual(28.0, result[1][1])
        self.assertAlmostEqual(datetime.datetime(2020, 1, 1, 0, 0, 10), result[0][0],
                               delta=datetime.timedelta(milliseconds=10))
        self.assertAlmostEqual(datetime.datetime(2020, 1, 1, 0, 0, 20), result[1][0],
                               delta=datetime.timedelta(milliseconds=10))

        result = await variable.retrieve_aggregated_log(start_time=datetime.datetime(2020, 1, 1, 0, 0, 25),
                                                        end_time=datetime.datetime(2020, 1, 1, 0, 0, 50),
                                                        aggregation_method=shc.data_logging.AggregationMethod.AVERAGE,
                                                        aggregation_interval=datetime.timedelta(seconds=2.5))
        self.assertEqual(10, len(result))
        self.assertAlmostEqual(32.0, result[0][1])  # 25
        self.assertAlmostEqual(40.0, result[1][1])
        self.assertAlmostEqual(40.0, result[2][1])  # 30
        self.assertAlmostEqual(40.0, result[3][1])
        self.assertAlmostEqual(20.0, result[4][1])  # 35
        self.assertAlmostEqual(20.0, result[5][1])

        result = await variable.retrieve_aggregated_log(start_time=datetime.datetime(2020, 1, 1, 0, 0, 0),
                                                        end_time=datetime.datetime(2020, 1, 1, 0, 0, 10),
                                                        aggregation_method=shc.data_logging.AggregationMethod.AVERAGE,
                                                        aggregation_interval=datetime.timedelta(seconds=10))
        self.assertEqual(1, len(result))
        self.assertAlmostEqual(30.0, result[0][1])

        result = await variable.retrieve_aggregated_log(start_time=datetime.datetime(2020, 1, 1, 0, 0, 10),
                                                        end_time=datetime.datetime(2020, 1, 1, 0, 0, 20),
                                                        aggregation_method=shc.data_logging.AggregationMethod.AVERAGE,
                                                        aggregation_interval=datetime.timedelta(seconds=2.5))
        self.assertEqual(4, len(result))
        self.assertAlmostEqual(40.0, result[0][1])
        self.assertAlmostEqual(40.0, result[1][1])
        self.assertAlmostEqual(20.0, result[2][1])
        self.assertAlmostEqual(20.0, result[3][1])

    @async_test
    async def test_ontime_aggregation(self) -> None:
        variable = await self._create_log_variable_with_data(bool, time_series_2)
        result = await variable.retrieve_aggregated_log(start_time=datetime.datetime(2020, 1, 1, 0, 0, 10),
                                                        end_time=datetime.datetime(2020, 1, 1, 0, 0, 30),
                                                        aggregation_method=shc.data_logging.AggregationMethod.ON_TIME,
                                                        aggregation_interval=datetime.timedelta(seconds=10))
        self.assertEqual(2, len(result))
        self.assertAlmostEqual(5.0, result[0][1])
        self.assertAlmostEqual(4.0, result[1][1])
        self.assertAlmostEqual(datetime.datetime(2020, 1, 1, 0, 0, 10), result[0][0],
                               delta=datetime.timedelta(milliseconds=10))
        self.assertAlmostEqual(datetime.datetime(2020, 1, 1, 0, 0, 20), result[1][0],
                               delta=datetime.timedelta(milliseconds=10))

        result = await variable.retrieve_aggregated_log(start_time=datetime.datetime(2020, 1, 1, 0, 0, 25),
                                                        end_time=datetime.datetime(2020, 1, 1, 0, 0, 50),
                                                        aggregation_method=shc.data_logging.AggregationMethod.ON_TIME,
                                                        aggregation_interval=datetime.timedelta(seconds=2.5))
        self.assertEqual(10, len(result))
        self.assertAlmostEqual(1.5, result[0][1])
        self.assertAlmostEqual(2.5, result[1][1])
        self.assertAlmostEqual(2.5, result[2][1])
        self.assertAlmostEqual(2.5, result[3][1])
        self.assertAlmostEqual(0.0, result[4][1])
        self.assertAlmostEqual(0.0, result[4][1])

        result = await variable.retrieve_aggregated_log(
            start_time=datetime.datetime(2020, 1, 1, 0, 0, 0),
            end_time=datetime.datetime(2020, 1, 1, 0, 0, 10),
            aggregation_method=shc.data_logging.AggregationMethod.ON_TIME_RATIO,
            aggregation_interval=datetime.timedelta(seconds=10))
        self.assertEqual(1, len(result))
        self.assertAlmostEqual(0.5, result[0][1])

        result = await variable.retrieve_aggregated_log(
            start_time=datetime.datetime(2020, 1, 1, 0, 0, 10),
            end_time=datetime.datetime(2020, 1, 1, 0, 0, 20),
            aggregation_method=shc.data_logging.AggregationMethod.ON_TIME_RATIO,
            aggregation_interval=datetime.timedelta(seconds=2.5))
        self.assertEqual(4, len(result))
        self.assertAlmostEqual(1.0, result[0][1])
        self.assertAlmostEqual(1.0, result[1][1])
        self.assertAlmostEqual(0.0, result[2][1])
        self.assertAlmostEqual(0.0, result[3][1])

    @async_test
    async def test_empty_aggregation(self) -> None:
        variable = await self._create_log_variable_with_data(float, time_series_1)
        result = await variable.retrieve_aggregated_log(start_time=datetime.datetime(2020, 1, 1, 0, 0, 40),
                                                        end_time=datetime.datetime(2020, 1, 1, 0, 0, 50),
                                                        aggregation_method=shc.data_logging.AggregationMethod.MINIMUM,
                                                        aggregation_interval=datetime.timedelta(seconds=2.5))
        self.assertEqual(4, len(result))
        self.assertEqual(20.0, result[0][1])

        result = await variable.retrieve_aggregated_log(start_time=datetime.datetime(2020, 1, 1, 0, 0, 40),
                                                        end_time=datetime.datetime(2020, 1, 1, 0, 0, 50),
                                                        aggregation_method=shc.data_logging.AggregationMethod.AVERAGE,
                                                        aggregation_interval=datetime.timedelta(seconds=2.5))
        self.assertEqual(4, len(result))
        self.assertEqual(20.0, result[0][1])

        result = await variable.retrieve_aggregated_log(
            start_time=datetime.datetime(2020, 1, 1, 0, 0, 40),
            end_time=datetime.datetime(2020, 1, 1, 0, 0, 50),
            aggregation_method=shc.data_logging.AggregationMethod.ON_TIME_RATIO,
            aggregation_interval=datetime.timedelta(seconds=2.5))
        self.assertEqual(4, len(result))
        self.assertEqual(1.0, result[0][1])

        result = await variable.retrieve_aggregated_log(start_time=datetime.datetime(2019, 1, 1, 0, 0, 40),
                                                        end_time=datetime.datetime(2019, 1, 1, 0, 0, 50),
                                                        aggregation_method=shc.data_logging.AggregationMethod.MAXIMUM,
                                                        aggregation_interval=datetime.timedelta(seconds=2.5))
        self.assertEqual(0, len(result))

        result = await variable.retrieve_aggregated_log(start_time=datetime.datetime(2019, 1, 1, 0, 0, 40),
                                                        end_time=datetime.datetime(2019, 1, 1, 0, 0, 50),
                                                        aggregation_method=shc.data_logging.AggregationMethod.AVERAGE,
                                                        aggregation_interval=datetime.timedelta(seconds=2.5))
        self.assertEqual(0, len(result))

        result = await variable.retrieve_aggregated_log(start_time=datetime.datetime(2019, 1, 1, 0, 0, 40),
                                                        end_time=datetime.datetime(2019, 1, 1, 0, 0, 50),
                                                        aggregation_method=shc.data_logging.AggregationMethod.ON_TIME,
                                                        aggregation_interval=datetime.timedelta(seconds=2.5))
        self.assertEqual(0, len(result))

    @async_test
    async def test_aggregation_type_error(self) -> None:
        variable = await self._create_log_variable_with_data(str, [(datetime.datetime(2020, 1, 1, 0, 0, 0), "foo")])
        with self.assertRaises(TypeError):
            await variable.retrieve_aggregated_log(start_time=datetime.datetime(2020, 1, 1, 0, 0, 40),
                                                   end_time=datetime.datetime(2020, 1, 1, 0, 0, 50),
                                                   aggregation_method=shc.data_logging.AggregationMethod.MINIMUM,
                                                   aggregation_interval=datetime.timedelta(seconds=2.5))

    @async_test
    async def test_simple_write_and_retrieval(self) -> None:
        if not self.do_write_tests:
            self.skipTest("Write tests are disabled for this data logging interface")
        var1 = await self._create_log_variable_with_data(int, [])
        start_ts = datetime.datetime.now().astimezone()
        await var1.write(1, [self])
        await asyncio.sleep(0.2)
        await var1.write(2, [self])
        await asyncio.sleep(0.1)
        await var1.write(3, [self])
        await asyncio.sleep(0.7)
        await var1.write(4, [self])
        await asyncio.sleep(0.05)
        await var1.write(5, [self])

        # Check data retrieval
        data = await var1.retrieve_log(start_ts + datetime.timedelta(seconds=0.1),
                                       start_ts + datetime.timedelta(days=200))
        self.assertEqual(4, len(data))
        self.assertListEqual([2, 3, 4, 5], [v for _ts, v in data])
        self.assertAlmostEqual(data[0][0], start_ts + datetime.timedelta(seconds=0.2),
                               delta=datetime.timedelta(milliseconds=50))
        self.assertAlmostEqual(data[-1][0], start_ts + datetime.timedelta(seconds=1.05),
                               delta=datetime.timedelta(milliseconds=50))

        # Check reading
        self.assertEqual(5, await var1.read())

    @async_test
    async def test_subscribe_log(self) -> None:
        if not self.do_subscribe_tests:
            self.skipTest("Subscribe tests are disabled for this data logging interface")
        var1 = await self._create_log_variable_with_data(int, [])
        view1 = LiveDataLogViewMock()
        view2 = LiveDataLogViewMock()
        var1.subscribe_data_log(view1)  # type: ignore
        var1.subscribe_data_log(view2)  # type: ignore

        start_ts = datetime.datetime.now().astimezone()

        await var1.write(1, [self])
        await asyncio.sleep(0.1)
        await var1.write(2, [self])
        await asyncio.sleep(0.2)
        await var1.write(3, [self])

        view1.result = await var1.retrieve_log(start_ts, start_ts + datetime.timedelta(seconds=0.35))

        await asyncio.sleep(0.6)
        await var1.write(4, [self])

        view2.result = await var1.retrieve_log(start_ts, start_ts + datetime.timedelta(seconds=1.05))

        await asyncio.sleep(0.15)
        await var1.write(5, [self])

        self.assertListEqual([v for _t, v in view1.result], [1, 2, 3, 4, 5])
        self.assertListEqual([v for _t, v in view2.result], [1, 2, 3, 4, 5])
        # TODO check timestamps

    @async_test
    async def test_subscribe_log_sync(self) -> None:
        if not self.do_subscribe_tests:
            self.skipTest("Subscribe tests are disabled for this data logging interface")
        var1 = await self._create_log_variable_with_data(int, [])
        view1 = LiveDataLogViewMock()
        view2 = LiveDataLogViewMock()
        var1.subscribe_data_log(view1)  # type: ignore
        var1.subscribe_data_log(view2)  # type: ignore

        async def producer() -> None:
            for i in range(100):
                await var1.write(i, [self])
                await asyncio.sleep(0.005)

        async def consumer1() -> None:
            await asyncio.sleep(0.15)
            # Reset view1's result to current state, as returned by var1 (as if we are a client that connected just now)
            view1.result = await var1.retrieve_log_sync(
                datetime.datetime.now().astimezone() - datetime.timedelta(seconds=20),
                datetime.datetime.now().astimezone())

        async def consumer2() -> None:
            await asyncio.sleep(0.3)
            # Reset view2's result to current state, as returned by var1 (as if we are a client that connected just now)
            view2.result = await var1.retrieve_log_sync(
                datetime.datetime.now().astimezone() - datetime.timedelta(seconds=20),
                datetime.datetime.now().astimezone())

        await asyncio.gather(producer(), consumer1(), consumer2())

        self.assertListEqual([v for _t, v in view1.result], list(range(100)))
        self.assertListEqual([v for _t, v in view2.result], list(range(100)))


class SimpleInMemoryWritableLogVariable(shc.data_logging.WritableDataLogVariable[T], Readable[T], Generic[T]):
    """A simplified version of InMemoryDataLogVariable, based on WritableDataLogVariable to test its subscribe
    mechanism"""
    type: Type[T]

    def __init__(self, type_: Type[T]):
        self.type = type_
        super().__init__()
        self.data: List[Tuple[datetime.datetime, T]] = []

    async def _write_to_data_log(self, values: List[Tuple[datetime.datetime, T]]) -> None:
        self.data.extend(values)

    async def read(self) -> T:
        if not self.data:
            raise UninitializedError("No value has been persisted yet")
        return self.data[-1][1]

    async def retrieve_log(self, start_time: datetime.datetime, end_time: datetime.datetime,
                           include_previous: bool = False) -> List[Tuple[datetime.datetime, T]]:
        iterator = iter(enumerate(self.data))
        try:
            start_index = next(i for i, (ts, _v) in iterator if ts >= start_time)
        except StopIteration:
            if include_previous and self.data:
                return self.data[-1:]
            else:
                return []
        if self.data[start_index][0] >= end_time:
            if include_previous and self.data:
                return self.data[start_index:start_index+1]
            else:
                return []
        if include_previous and start_index > 0:
            start_index -= 1
        try:
            end_index = next(i for i, (ts, _v) in iterator if ts >= end_time)
        except StopIteration:
            return self.data[start_index:]
        return self.data[start_index:end_index]


class WritableDataLogVariableTest(AbstractLoggingTest):
    do_write_tests = True
    do_subscribe_tests = True

    async def _create_log_variable_with_data(self, type_: Type[T], data: Iterable[Tuple[datetime.datetime, T]]) \
            -> shc.data_logging.DataLogVariable[T]:
        var = SimpleInMemoryWritableLogVariable(type_)
        var.data = list(data)
        return var
