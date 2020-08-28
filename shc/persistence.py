# Copyright 2020 Michael Thies <mail@mhthies.de>
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may not use this file except in compliance with
# the License. You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software distributed under the License is distributed on an
# "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the License for the
# specific language governing permissions and limitations under the License.

import abc
import enum
import json
import datetime
import logging
from typing import Type, Generic, List, Any, Optional, AsyncIterable

import aiomysql  # TODO make feature-dependent dependency

from .base import T, Readable, Writable, UninitializedError
from .conversion import from_json, SHCJsonEncoder
from .supervisor import register_interface

logger = logging.getLogger(__name__)


class AbstractPersistenceInterface(metaclass=abc.ABCMeta):
    @abc.abstractmethod
    async def start(self) -> None:
        pass

    @abc.abstractmethod
    async def wait(self) -> None:
        pass

    @abc.abstractmethod
    async def stop(self) -> None:
        pass

    @abc.abstractmethod
    async def _write(self, name: str, value: Any, log: bool):
        pass

    @abc.abstractmethod
    async def _read(self, name: str, type_: Type) -> Optional[Any]:
        pass

    @abc.abstractmethod
    async def _retrieve_log(self, name: str, type_: Type, start_time: datetime.datetime, end_time: datetime.datetime
                            ) -> AsyncIterable[str]:
        # TODO add aggregation spec
        pass

    def variable(self, type_: Type, name: str, log: bool = True) -> "PersistenceVariable":
        return PersistenceVariable(self, type_, name, log)


class PersistenceVariable(Readable[T], Writable[T], Generic[T]):
    def __init__(self, interface: AbstractPersistenceInterface, type_: Type[T], name: str, log: bool):
        self.type = type_
        super().__init__()
        self.name = name
        self.log = log
        self.interface = interface

    async def read(self) -> T:
        value = await self.interface._read(self.name, self.type)
        if value is None:
            raise UninitializedError("No value for has been persistet for variable '{}' yet.".format(self.name))
        logger.debug("Retrieved value %s for %s from %s", value, self, self.interface)
        return value

    async def _write(self, value: T, origin: List[Any]):
        logger.debug("%s value %s for %s to persistence backend", "logging" if self.log else "updating", value, self)
        await self.interface._write(self.name, value, log=self.log)

    def __repr__(self):
        return "<PersistenceVariable '{}'>".format(self.name)


class MySQLPersistence(AbstractPersistenceInterface):
    def __init__(self, **kwargs):
        # see https://aiomysql.readthedocs.io/en/latest/connection.html#connection for valid parameters
        self.connect_args = kwargs
        self.pool: Optional[aiomysql.Pool] = None
        self.pool_ready = asyncio.Event()
        register_interface(self)

    async def start(self) -> None:
        logger.info("Creating MySQL connection pool ...")
        self.pool = await aiomysql.create_pool(**self.connect_args)
        self.pool_ready.set()

    async def wait(self) -> None:
        pass

    async def stop(self) -> None:
        logger.info("Clossing all MySQL connections ...")
        self.pool.close()
        await self.pool.wait_closed()

    async def _write(self, name: str, value: T, log: bool):
        column_name = self._type_to_column(type(value))
        value = self._into_mysql_type(value)
        await self.pool_ready.wait()
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cur:
                if log:
                    await cur.execute("INSERT INTO `log` (`name`, `ts`, `{}`) VALUES (%s, %s, %s)".format(column_name),
                                      (name, datetime.datetime.now().astimezone(), value))
                else:
                    await cur.execute("UPDATE `log` SET `ts` = %s, `{}` = %s WHERE `name` = %s".format(column_name),
                                      (datetime.datetime.now().astimezone(), value, name))
            await conn.commit()

    async def _read(self, name: str, type_: Type[T]) -> Optional[T]:
        column_name = self._type_to_column(type_)
        await self.pool_ready.wait()
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("SELECT `{}` from `log` WHERE `name` = %s ORDER BY `ts` DESC LIMIT 1"
                                  .format(column_name),
                                  (name,))
                value = await cur.fetchone()
        if value is None:
            return None
        return self._from_mysql_type(type_, value[0])

    async def _retrieve_log(self, name: str, type_: Type, start_time: datetime.datetime, end_time: datetime.datetime
                            ) -> AsyncIterable[str]:
        # TODO
        pass

    @classmethod
    def _type_to_column(cls, type_: type) -> str:
        if issubclass(type_, (int, bool)):
            return 'value_int'
        elif issubclass(type_, float):
            return 'value_float'
        elif issubclass(type_, str):
            return 'value_str'
        elif issubclass(type_, enum.Enum):
            return cls._type_to_column(type(next(iter(type_.__members__.values())).value))
        else:
            return 'value_str'

    @classmethod
    def _into_mysql_type(cls, value: Any) -> Any:
        if isinstance(value, bool):
            return value
        elif isinstance(value, int):
            return int(value)
        elif isinstance(value, float):
            return float(value)
        elif isinstance(value, str):
            return str(value)
        elif isinstance(value, enum.Enum):
            return cls._into_mysql_type(value.value)
        else:
            return json.dumps(value, cls=SHCJsonEncoder)

    @classmethod
    def _from_mysql_type(cls, type_: type, value: Any) -> Any:
        if issubclass(type_, (bool, int, float, str, enum.Enum)):
            return type_(value)
        else:
            return from_json(type_, json.loads(value))
