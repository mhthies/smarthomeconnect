import datetime
from typing import Optional, Type, Generic, List, Tuple

from shc.base import T, Readable, UninitializedError
from shc.data_logging import WritableDataLogVariable


# TODO use custom subscribe_data_log() data log implementation instead of inheriting from WritableDataLogVariable
#  -> we don't need the complex locking, queuing and flushing mechanism, since querying and appending the in-memory log
#     is "atomic" (in the sense of asyncio tasks).
# TODO rename
class InMemoryPersistenceVariable(WritableDataLogVariable, Readable[T], Generic[T]):
    type: Type[T]

    def __init__(self, type_: Type[T], keep: datetime.timedelta):
        self.type = type_
        super().__init__()
        self.data: List[Tuple[datetime.datetime, T]] = []
        self.keep = keep

    async def _write_to_data_log(self, values: List[Tuple[datetime.datetime, T]]) -> None:
        self.clean_up()
        self.data.extend(values)

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
        if include_previous and start_index > 0:
            start_index -= 1
        try:
            end_index = next(i for i, (ts, _v) in iterator if ts > end_time)
        except StopIteration:
            return self.data[start_index:]
        return self.data[start_index:end_index]
