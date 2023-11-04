import asyncio
import datetime
from typing import Tuple, Type, Iterable

import shc.data_logging
import shc.interfaces.in_memory_data_logging
from shc.base import T
from .._helper import ClockMock, async_test
from ..test_data_logging import AbstractLoggingTest


class InMemoryTest(AbstractLoggingTest):
    do_write_tests = True
    do_subscribe_tests = True

    async def _create_log_variable_with_data(self, type_: Type[T], data: Iterable[Tuple[datetime.datetime, T]]) \
            -> shc.data_logging.DataLogVariable[T]:
        var = shc.interfaces.in_memory_data_logging.InMemoryDataLogVariable(type_, datetime.timedelta(days=1000*365))
        var.data = list(data)
        return var

    @async_test
    async def test_clean_up(self) -> None:
        var1 = shc.interfaces.in_memory_data_logging.InMemoryDataLogVariable(int, datetime.timedelta(seconds=10))
        with ClockMock(datetime.datetime(2020, 1, 1, 0, 0, 0)):
            await var1.write(1, [self])
            await asyncio.sleep(1)
            await var1.write(2, [self])
            await asyncio.sleep(1)
            await var1.write(3, [self])
            await asyncio.sleep(7.5)
            await var1.write(4, [self])

            self.assertEqual(4, len(var1.data))

            await asyncio.sleep(3)
            await var1.write(5, [self])

        # Check that old data has been deleted
        self.assertEqual(2, len(var1.data))
