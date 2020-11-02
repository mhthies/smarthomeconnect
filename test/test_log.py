import asyncio
import datetime
import unittest

import shc.log.in_memory
from ._helper import async_test, ClockMock


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
