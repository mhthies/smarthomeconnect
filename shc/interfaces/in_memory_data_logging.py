import asyncio
import datetime
from typing import Optional, Type, Generic, List, Tuple, Any

from shc.base import T, Readable, Writable, UninitializedError
from shc.data_logging import DataLogVariable, LiveDataLogView


class InMemoryDataLogVariable(Writable[T], DataLogVariable[T], Readable[T], Generic[T]):
    """
    A single in-memory :class:`DataLogVariable <shc.data_logging.DataLogVariable>`, based on a simple Python list,
    without any persistent storage.

    Data log entries that are older than the specified `keep` time are dropped automatically, to keep memory usage
    limited. This class is sufficient for logging a variable value for the purpose of displaying a chart over the last
    few minutes (or maybe hours) and calculate aggregated values, if you don't mind losing the historic data on every
    restart of the SHC application. It's also fine for demonstration purposes (see ui_logging_showcase.py in the
    examples/ directory).

    :param type\\_: Value type of this `connectable` object (and as a `DataLogVariable`)
    :param keep: timespan for which to keep the values. Older values will be deleted upon the next `write` to the
                 object.
    """
    type: Type[T]

    def __init__(self, type_: Type[T], keep: datetime.timedelta):
        self.type = type_
        super().__init__()
        self.data: List[Tuple[datetime.datetime, T]] = []
        self.keep = keep
        self._data_log_subscribers: List[LiveDataLogView] = []

    async def _write(self, value: T, origin: List[Any]) -> None:
        self.clean_up()
        entry = (datetime.datetime.now(datetime.timezone.utc), value)
        self.data.append(entry)
        # We do not need the complicated locking, queuing and flushing from WritableDataLogVariable here, since querying
        # and appending the in-memory log is "atomic" (in the sense of asyncio tasks), i.e. does not include an 'await'
        # statement.
        tasks = [subscriber._new_log_values_written([entry])
                 for subscriber in self._data_log_subscribers]
        if len(tasks) == 1:
            await tasks[0]
        else:
            await asyncio.gather(*tasks)

    def clean_up(self) -> None:
        begin = datetime.datetime.now(datetime.timezone.utc) - self.keep
        keep_from: Optional[int] = None
        for i, (ts, _v) in enumerate(self.data):
            if ts > begin:
                keep_from = i
                break
        self.data = self.data[keep_from:]

    async def read(self) -> T:
        if not self.data:
            raise UninitializedError("No value has been persisted yet")
        return self.data[-1][1]

    def subscribe_data_log(self, subscriber: LiveDataLogView) -> None:
        self._data_log_subscribers.append(subscriber)

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
