import datetime
from typing import Optional, Type, Generic, List, Tuple

from ..base import T
from .generic import PersistenceVariable


class InMemoryPersistenceVariable(PersistenceVariable, Generic[T]):
    def __init__(self, type_: Type[T], keep: datetime.timedelta):
        super().__init__(type_, log=True)
        self.data: List[Tuple[datetime.datetime, T]] = []
        self.keep = keep

    async def _write_to_log(self, value: T):
        self.clean_up()
        self.data.append((datetime.datetime.now(datetime.timezone.utc), value))

    def clean_up(self) -> None:
        begin = datetime.datetime.now(datetime.timezone.utc) - self.keep
        keep_from: Optional[int] = None
        for i, (ts, _v) in enumerate(self.data):
            if ts > begin:
                keep_from = i
                break
        self.data = self.data[keep_from:]

    async def _read_from_log(self) -> Optional[T]:
        if not self.data:
            return None
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
