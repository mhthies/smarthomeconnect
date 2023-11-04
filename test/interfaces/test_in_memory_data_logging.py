import asyncio
import datetime
import unittest
from typing import List, Tuple, Any

import shc.interfaces.in_memory_data_logging
from test._helper import async_test, ClockMock


class LiveDataLogViewMock:
    def __init__(self):
        self.result = []

    async def _new_log_values_written(self, values: List[Tuple[datetime.datetime, Any]]) -> None:
        self.result.extend(values)


class InMemoryTest(unittest.TestCase):
    @async_test
    async def test_simple(self) -> None:
        var1 = shc.interfaces.in_memory_data_logging.InMemoryDataLogVariable(int, datetime.timedelta(seconds=10))
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

    @async_test
    async def test_subscribe_log(self) -> None:
        var1 = shc.interfaces.in_memory_data_logging.InMemoryDataLogVariable(int, datetime.timedelta(seconds=10))
        view1 = LiveDataLogViewMock()
        view2 = LiveDataLogViewMock()
        var1.subscribe_data_log(view1)  # type: ignore
        var1.subscribe_data_log(view2)  # type: ignore

        start_ts = datetime.datetime(2020, 1, 1, 0, 0, 0).astimezone()

        with ClockMock(start_ts):
            await var1.write(1, [self])
            await asyncio.sleep(1)
            await var1.write(2, [self])
            await asyncio.sleep(1)
            await var1.write(3, [self])

            view1.result = await var1.retrieve_log(start_ts,
                                                   datetime.datetime(2020, 1, 1, 0, 0, 2, 50000).astimezone())

            await asyncio.sleep(7)
            await var1.write(4, [self])

            view2.result = await var1.retrieve_log(start_ts,
                                                   datetime.datetime(2020, 1, 1, 0, 0, 10, 50000).astimezone())

            await asyncio.sleep(1.5)
            await var1.write(5, [self])

        self.assertListEqual([v for _t, v in view1.result], [1, 2, 3, 4, 5])
        self.assertListEqual([v for _t, v in view2.result], [1, 2, 3, 4, 5])
        # TODO check timestamps

    @async_test
    async def test_subscribe_log_sync(self) -> None:
        var1 = shc.interfaces.in_memory_data_logging.InMemoryDataLogVariable(int, datetime.timedelta(seconds=10))
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
