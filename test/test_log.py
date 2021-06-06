import asyncio
import datetime
import unittest
from typing import List, Tuple, Optional, Generic

import shc.log.generic
import shc.log.in_memory
from shc.base import T
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


class ExampleLogVariable(shc.log.generic.PersistenceVariable[T], Generic[T]):
    async def _read_from_log(self) -> Optional[T]:
        raise NotImplementedError

    async def _write_to_log(self, value: T) -> None:
        raise NotImplementedError

    def __init__(self, time_series: List[Tuple[datetime.datetime, T]]):
        super().__init__(type(time_series[0][1]), True)
        self.data = time_series

    async def retrieve_log(self, start_time: datetime.datetime, end_time: datetime.datetime,
                           include_previous: bool = True) -> List[Tuple[datetime.datetime, T]]:
        return self.data


class AbstractLoggingTest(unittest.TestCase):
    @async_test
    async def test_maxmin_aggregation(self) -> None:
        variable = ExampleLogVariable(time_series_1)
        result = await variable.retrieve_aggregated_log(start_time=datetime.datetime(2020, 1, 1, 0, 0, 10),
                                                        end_time=datetime.datetime(2020, 1, 1, 0, 0, 30),
                                                        aggregation_method=shc.log.AggregationMethod.MAXIMUM,
                                                        aggregation_interval=datetime.timedelta(seconds=10))
        self.assertEqual(2, len(result))
        self.assertAlmostEqual(40.0, result[0][1])
        self.assertAlmostEqual(40.0, result[1][1])
        self.assertAlmostEqual(datetime.datetime(2020, 1, 1, 0, 0, 10), result[0][0])
        self.assertAlmostEqual(datetime.datetime(2020, 1, 1, 0, 0, 20), result[1][0])

        result = await variable.retrieve_aggregated_log(start_time=datetime.datetime(2020, 1, 1, 0, 0, 30),
                                                        end_time=datetime.datetime(2020, 1, 1, 0, 0, 50),
                                                        aggregation_method=shc.log.AggregationMethod.MINIMUM,
                                                        aggregation_interval=datetime.timedelta(seconds=10))
        self.assertEqual(2, len(result))
        self.assertAlmostEqual(20.0, result[0][1])

        result = await variable.retrieve_aggregated_log(start_time=datetime.datetime(2020, 1, 1, 0, 0, 0),
                                                        end_time=datetime.datetime(2020, 1, 1, 0, 0, 10),
                                                        aggregation_method=shc.log.AggregationMethod.MINIMUM,
                                                        aggregation_interval=datetime.timedelta(seconds=10))
        self.assertEqual(1, len(result))
        self.assertAlmostEqual(20.0, result[0][1])

    @async_test
    async def test_average_aggregation(self) -> None:
        variable = ExampleLogVariable(time_series_1)
        result = await variable.retrieve_aggregated_log(start_time=datetime.datetime(2020, 1, 1, 0, 0, 10),
                                                        end_time=datetime.datetime(2020, 1, 1, 0, 0, 30),
                                                        aggregation_method=shc.log.AggregationMethod.AVERAGE,
                                                        aggregation_interval=datetime.timedelta(seconds=10))
        self.assertEqual(2, len(result))
        self.assertAlmostEqual(30.0, result[0][1])
        self.assertAlmostEqual(28.0, result[1][1])
        self.assertAlmostEqual(datetime.datetime(2020, 1, 1, 0, 0, 10), result[0][0])
        self.assertAlmostEqual(datetime.datetime(2020, 1, 1, 0, 0, 20), result[1][0])

        result = await variable.retrieve_aggregated_log(start_time=datetime.datetime(2020, 1, 1, 0, 0, 25),
                                                        end_time=datetime.datetime(2020, 1, 1, 0, 0, 50),
                                                        aggregation_method=shc.log.AggregationMethod.AVERAGE,
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
                                                        aggregation_method=shc.log.AggregationMethod.AVERAGE,
                                                        aggregation_interval=datetime.timedelta(seconds=10))
        self.assertEqual(1, len(result))
        self.assertAlmostEqual(30.0, result[0][1])

        result = await variable.retrieve_aggregated_log(start_time=datetime.datetime(2020, 1, 1, 0, 0, 10),
                                                        end_time=datetime.datetime(2020, 1, 1, 0, 0, 20),
                                                        aggregation_method=shc.log.AggregationMethod.AVERAGE,
                                                        aggregation_interval=datetime.timedelta(seconds=2.5))
        self.assertEqual(4, len(result))
        self.assertAlmostEqual(40.0, result[0][1])
        self.assertAlmostEqual(40.0, result[1][1])
        self.assertAlmostEqual(20.0, result[2][1])
        self.assertAlmostEqual(20.0, result[3][1])

    @async_test
    async def test_ontime_aggregation(self) -> None:
        variable = ExampleLogVariable(time_series_2)
        result = await variable.retrieve_aggregated_log(start_time=datetime.datetime(2020, 1, 1, 0, 0, 10),
                                                        end_time=datetime.datetime(2020, 1, 1, 0, 0, 30),
                                                        aggregation_method=shc.log.AggregationMethod.ON_TIME,
                                                        aggregation_interval=datetime.timedelta(seconds=10))
        self.assertEqual(2, len(result))
        self.assertAlmostEqual(5.0, result[0][1])
        self.assertAlmostEqual(4.0, result[1][1])
        self.assertAlmostEqual(datetime.datetime(2020, 1, 1, 0, 0, 10), result[0][0])
        self.assertAlmostEqual(datetime.datetime(2020, 1, 1, 0, 0, 20), result[1][0])

        result = await variable.retrieve_aggregated_log(start_time=datetime.datetime(2020, 1, 1, 0, 0, 25),
                                                        end_time=datetime.datetime(2020, 1, 1, 0, 0, 50),
                                                        aggregation_method=shc.log.AggregationMethod.ON_TIME,
                                                        aggregation_interval=datetime.timedelta(seconds=2.5))
        self.assertEqual(10, len(result))
        self.assertAlmostEqual(1.5, result[0][1])
        self.assertAlmostEqual(2.5, result[1][1])
        self.assertAlmostEqual(2.5, result[2][1])
        self.assertAlmostEqual(2.5, result[3][1])
        self.assertAlmostEqual(0.0, result[4][1])
        self.assertAlmostEqual(0.0, result[4][1])

        result = await variable.retrieve_aggregated_log(start_time=datetime.datetime(2020, 1, 1, 0, 0, 0),
                                                        end_time=datetime.datetime(2020, 1, 1, 0, 0, 10),
                                                        aggregation_method=shc.log.AggregationMethod.ON_TIME_RATIO,
                                                        aggregation_interval=datetime.timedelta(seconds=10))
        self.assertEqual(1, len(result))
        self.assertAlmostEqual(0.5, result[0][1])

        result = await variable.retrieve_aggregated_log(start_time=datetime.datetime(2020, 1, 1, 0, 0, 10),
                                                        end_time=datetime.datetime(2020, 1, 1, 0, 0, 20),
                                                        aggregation_method=shc.log.AggregationMethod.ON_TIME_RATIO,
                                                        aggregation_interval=datetime.timedelta(seconds=2.5))
        self.assertEqual(4, len(result))
        self.assertAlmostEqual(1.0, result[0][1])
        self.assertAlmostEqual(1.0, result[1][1])
        self.assertAlmostEqual(0.0, result[2][1])
        self.assertAlmostEqual(0.0, result[3][1])

    @async_test
    async def test_empty_aggregation(self) -> None:
        variable = ExampleLogVariable(time_series_1)
        result = await variable.retrieve_aggregated_log(start_time=datetime.datetime(2020, 1, 1, 0, 0, 40),
                                                        end_time=datetime.datetime(2020, 1, 1, 0, 0, 50),
                                                        aggregation_method=shc.log.AggregationMethod.MINIMUM,
                                                        aggregation_interval=datetime.timedelta(seconds=2.5))
        self.assertEqual(4, len(result))
        self.assertEqual(20.0, result[0][1])

        result = await variable.retrieve_aggregated_log(start_time=datetime.datetime(2020, 1, 1, 0, 0, 40),
                                                        end_time=datetime.datetime(2020, 1, 1, 0, 0, 50),
                                                        aggregation_method=shc.log.AggregationMethod.AVERAGE,
                                                        aggregation_interval=datetime.timedelta(seconds=2.5))
        self.assertEqual(4, len(result))
        self.assertEqual(20.0, result[0][1])

        result = await variable.retrieve_aggregated_log(start_time=datetime.datetime(2020, 1, 1, 0, 0, 40),
                                                        end_time=datetime.datetime(2020, 1, 1, 0, 0, 50),
                                                        aggregation_method=shc.log.AggregationMethod.ON_TIME_RATIO,
                                                        aggregation_interval=datetime.timedelta(seconds=2.5))
        self.assertEqual(4, len(result))
        self.assertEqual(1.0, result[0][1])

        result = await variable.retrieve_aggregated_log(start_time=datetime.datetime(2019, 1, 1, 0, 0, 40),
                                                        end_time=datetime.datetime(2019, 1, 1, 0, 0, 50),
                                                        aggregation_method=shc.log.AggregationMethod.MAXIMUM,
                                                        aggregation_interval=datetime.timedelta(seconds=2.5))
        self.assertEqual(0, len(result))

        result = await variable.retrieve_aggregated_log(start_time=datetime.datetime(2019, 1, 1, 0, 0, 40),
                                                        end_time=datetime.datetime(2019, 1, 1, 0, 0, 50),
                                                        aggregation_method=shc.log.AggregationMethod.AVERAGE,
                                                        aggregation_interval=datetime.timedelta(seconds=2.5))
        self.assertEqual(0, len(result))

        result = await variable.retrieve_aggregated_log(start_time=datetime.datetime(2019, 1, 1, 0, 0, 40),
                                                        end_time=datetime.datetime(2019, 1, 1, 0, 0, 50),
                                                        aggregation_method=shc.log.AggregationMethod.ON_TIME,
                                                        aggregation_interval=datetime.timedelta(seconds=2.5))
        self.assertEqual(0, len(result))

    @async_test
    async def test_aggregation_type_error(self) -> None:
        variable = ExampleLogVariable([(datetime.datetime(2020, 1, 1, 0, 0, 0), "foo")])
        with self.assertRaises(TypeError):
            await variable.retrieve_aggregated_log(start_time=datetime.datetime(2020, 1, 1, 0, 0, 40),
                                                   end_time=datetime.datetime(2020, 1, 1, 0, 0, 50),
                                                   aggregation_method=shc.log.AggregationMethod.MINIMUM,
                                                   aggregation_interval=datetime.timedelta(seconds=2.5))


class InMemoryTest(unittest.TestCase):
    @async_test
    async def test_simple(self) -> None:
        var1 = shc.log.in_memory.InMemoryPersistenceVariable(int, datetime.timedelta(seconds=10))
        with ClockMock(datetime.datetime(2020, 1, 1, 0, 0, 0)):
            await var1.write(1, [self])
            await asyncio.sleep(1)
            await var1.write(2, [self])
            await asyncio.sleep(1)
            await var1.write(3, [self])
            await asyncio.sleep(8)
            await var1.write(4, [self])
            await asyncio.sleep(0.5)
            await var1.write(5, [self])

        # Check data retrieval
        data = await var1.retrieve_log(datetime.datetime(2020, 1, 1, 0, 0, 0, microsecond=500000).astimezone(),
                                       datetime.datetime(2020, 11, 20, 0, 0, 0).astimezone())
        self.assertEqual(4, len(data))
        self.assertListEqual([2, 3, 4, 5], [v for _ts, v in data])
        self.assertAlmostEqual(data[0][0], datetime.datetime(2020, 1, 1, 0, 0, 1).astimezone(),
                               delta=datetime.timedelta(milliseconds=50))
        self.assertAlmostEqual(data[-1][0], datetime.datetime(2020, 1, 1, 0, 0, 10, microsecond=500000).astimezone(),
                               delta=datetime.timedelta(milliseconds=50))

        # Check reading
        self.assertEqual(5, await var1.read())

        # Check that old data has been deleted
        self.assertEqual(4, len(var1.data))
