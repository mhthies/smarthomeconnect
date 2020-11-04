import asyncio
import datetime
import unittest
from typing import List, Tuple, Optional

import shc.log.in_memory
import shc.log
from shc.base import T
from ._helper import async_test, ClockMock, AsyncMock


class ExampleLogVariable(shc.log.PersistenceVariable):
    async def _read_from_log(self) -> Optional[T]:
        raise NotImplementedError

    async def _write_to_log(self, value: T) -> None:
        raise NotImplementedError

    def __init__(self):
        super().__init__(float, True)

    async def retrieve_log(self, start_time: datetime.datetime, end_time: datetime.datetime,
                           include_previous: bool = True) -> List[Tuple[datetime.datetime, float]]:
        return [
            (datetime.datetime(2020, 1, 1, 0, 0, 0), 20.0),
            (datetime.datetime(2020, 1, 1, 0, 0, 5), 40.0),
            (datetime.datetime(2020, 1, 1, 0, 0, 15), 20.0),
            (datetime.datetime(2020, 1, 1, 0, 0, 25), 40.0),
            (datetime.datetime(2020, 1, 1, 0, 0, 27), 40.0),
            (datetime.datetime(2020, 1, 1, 0, 0, 35), 20.0),
        ]


class AbstractLoggingTest(unittest.TestCase):
    @async_test
    async def test_maxmin_aggregation(self) -> None:
        variable = ExampleLogVariable()
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
        self.assertEqual(1, len(result))
        self.assertAlmostEqual(20.0, result[0][1])

        result = await variable.retrieve_aggregated_log(start_time=datetime.datetime(2020, 1, 1, 0, 0, 0),
                                                        end_time=datetime.datetime(2020, 1, 1, 0, 0, 10),
                                                        aggregation_method=shc.log.AggregationMethod.MINIMUM,
                                                        aggregation_interval=datetime.timedelta(seconds=10))
        self.assertEqual(1, len(result))
        self.assertAlmostEqual(20.0, result[0][1])

    @async_test
    async def test_average_aggregation(self) -> None:
        variable = ExampleLogVariable()
        result = await variable.retrieve_aggregated_log(start_time=datetime.datetime(2020, 1, 1, 0, 0, 10),
                                                        end_time=datetime.datetime(2020, 1, 1, 0, 0, 30),
                                                        aggregation_method=shc.log.AggregationMethod.AVERAGE,
                                                        aggregation_interval=datetime.timedelta(seconds=10))
        self.assertEqual(2, len(result))
        self.assertAlmostEqual(30.0, result[0][1])
        self.assertAlmostEqual(30.0, result[1][1])
        self.assertAlmostEqual(datetime.datetime(2020, 1, 1, 0, 0, 10), result[0][0])
        self.assertAlmostEqual(datetime.datetime(2020, 1, 1, 0, 0, 20), result[1][0])

        result = await variable.retrieve_aggregated_log(start_time=datetime.datetime(2020, 1, 1, 0, 0, 25),
                                                        end_time=datetime.datetime(2020, 1, 1, 0, 0, 50),
                                                        aggregation_method=shc.log.AggregationMethod.AVERAGE,
                                                        aggregation_interval=datetime.timedelta(seconds=2.5))
        self.assertEqual(5, len(result))
        self.assertAlmostEqual(40.0, result[0][1])
        self.assertAlmostEqual(40.0, result[1][1])
        self.assertAlmostEqual(40.0, result[2][1])
        self.assertAlmostEqual(40.0, result[3][1])
        self.assertAlmostEqual(20.0, result[4][1])

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
    async def test_empty_aggregation(self) -> None:
        variable = ExampleLogVariable()
        result = await variable.retrieve_aggregated_log(start_time=datetime.datetime(2020, 1, 1, 0, 0, 40),
                                                        end_time=datetime.datetime(2020, 1, 1, 0, 0, 50),
                                                        aggregation_method=shc.log.AggregationMethod.MINIMUM,
                                                        aggregation_interval=datetime.timedelta(seconds=2.5))
        self.assertEqual(0, len(result))

        result = await variable.retrieve_aggregated_log(start_time=datetime.datetime(2020, 1, 1, 0, 0, 40),
                                                        end_time=datetime.datetime(2020, 1, 1, 0, 0, 50),
                                                        aggregation_method=shc.log.AggregationMethod.MAXIMUM,
                                                        aggregation_interval=datetime.timedelta(seconds=2.5))
        self.assertEqual(0, len(result))


class InMemoryTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        ClockMock.enable()

    @async_test
    async def test_simple(self) -> None:
        in_memory_log = shc.log.in_memory.InMemoryPersistence(keep=datetime.timedelta(seconds=10))

        var1 = in_memory_log.variable(int)
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
        data = await var1.retrieve_log(datetime.datetime(2020, 1, 1, 0, 0, 0, microsecond=500000),
                                       datetime.datetime(2020, 11, 20, 0, 0, 0))
        self.assertEqual(4, len(data))
        self.assertListEqual([2, 3, 4, 5], [v for _ts, v in data])
        self.assertAlmostEqual(data[0][0], datetime.datetime(2020, 1, 1, 0, 0, 1),
                               delta=datetime.timedelta(milliseconds=50))
        self.assertAlmostEqual(data[-1][0], datetime.datetime(2020, 1, 1, 0, 0, 10, microsecond=500000),
                               delta=datetime.timedelta(milliseconds=50))

        # Check reading
        self.assertEqual(5, await var1.read())

        # Check that old data has been deleted
        self.assertEqual(4, len(var1.data))
