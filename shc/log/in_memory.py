import datetime
from typing import Optional, Type, Generic, List, Tuple

from ..base import T
from . import PersistenceVariable


class InMemoryPersistenceVariable(PersistenceVariable, Generic[T]):
    def __init__(self, type_: Type[T], keep: datetime.timedelta):
        super().__init__(type_, log=True)
        self.data: List[Tuple[datetime.datetime, T]] = []
        self.keep = keep

    async def _write_to_log(self, value: T):
        self.clean_up()
        self.data.append((datetime.datetime.now(), value))

    def clean_up(self) -> None:
        begin = datetime.datetime.now() - self.keep
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
                           include_previous_entry: bool = False) -> List[Tuple[datetime.datetime, T]]:
        return [v for v in self.data if start_time <= v[0] < end_time]
