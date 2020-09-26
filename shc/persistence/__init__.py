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
import asyncio
import enum
import json
import datetime
import logging
from typing import Type, Generic, List, Any, Optional, Tuple, Set

import aiohttp.web
import aiomysql  # type: ignore  # TODO make feature-dependent dependency

from ..base import T, Readable, Writable, UninitializedError
from ..conversion import from_json, SHCJsonEncoder
from ..supervisor import register_interface
from ..web import WebUIConnector

logger = logging.getLogger(__name__)


class PersistenceVariable(Readable[T], Writable[T], Generic[T], metaclass=abc.ABCMeta):
    def __init__(self, type_: Type[T], log: bool):
        self.type = type_
        super().__init__()
        self.log = log
        self.subscribed_web_ui_views: List[LoggingWebUIView] = []

    @abc.abstractmethod
    async def _read_from_log(self) -> Optional[T]:
        pass

    @abc.abstractmethod
    async def _write_to_log(self, value: T) -> None:
        pass

    @abc.abstractmethod
    async def retrieve_log(self, start_time: datetime.datetime, end_time: datetime.datetime, num: Optional[int] = None,
                           offset: int = 0) -> List[T]:
        pass

    async def read(self) -> T:
        value = await self._read_from_log()
        if value is None:
            raise UninitializedError("No value for has been persisted for variable '{}' yet.".format(self))
        return value

    async def _write(self, value: T, origin: List[Any]):
        logger.debug("%s value %s for %s to persistence backend", "logging" if self.log else "updating", value, self)
        await self._write_to_log(value)
        for web_ui_view in self.subscribed_web_ui_views:
            await web_ui_view.new_value(datetime.datetime.now(), value)


class LoggingWebUIView(WebUIConnector):
    """
    A WebUIConnector which is used to retrieve a log/timeseries of a certain persistence variable for a certain time
    interval via the Webinterface UI websocket and subscribe to updates of that persistence variable.
    """
    def __init__(self, variable: PersistenceVariable, interval: datetime.timedelta):
        # TODO extend with value conversion
        # TODO extend for past interval
        # TODO extend for aggregation
        if not variable.log:
            raise ValueError("Cannot use a PersistenceVariable with log=False for a web logging web ui widget")
        super().__init__()
        self.variable = variable
        variable.subscribed_web_ui_views.append(self)
        self.interval = interval
        self.subscribed_websockets: Set[aiohttp.web.WebSocketResponse] = set()

    async def new_value(self, timestamp: datetime.datetime, value: Any) -> None:
        """
        Coroutine to be called by the class:`PersistenceVariable` this view belongs to, when it receives and logs a new
        value, so the value can instantly be plotted by all subscribed web clients.

        :param timestamp: Exact timestamp of the new value
        :param value: The new value
        """
        await self._websocket_publish([timestamp, value])

    async def _websocket_before_subscribe(self, ws: aiohttp.web.WebSocketResponse) -> None:
        # TODO use pagination
        # TODO somehow handle reconnects properly
        data = await self.variable.retrieve_log(datetime.datetime.now() - self.interval,
                                                datetime.datetime.now() + datetime.timedelta(seconds=5))
        await ws.send_str(json.dumps({'id': id(self),
                                      'v': data},
                                     cls=SHCJsonEncoder))


class MySQLPersistence:
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
        if self.pool is not None:
            logger.info("Closing all MySQL connections ...")
            self.pool.close()
            await self.pool.wait_closed()

    def variable(self, type_: Type, name: str, log: bool = True) -> "MySQLPersistenceVariable":
        return MySQLPersistenceVariable(self, type_, name, log)


class MySQLPersistenceVariable(PersistenceVariable, Generic[T]):
    def __init__(self, interface: MySQLPersistence, type_: Type[T], name: str, log: bool):
        super().__init__(type_, log)
        self.interface = interface
        self.name = name
        self.log = log

    async def _write_to_log(self, value: Type[T]):
        column_name = self._type_to_column(type(value))
        value = self._into_mysql_type(value)
        await self.interface.pool_ready.wait()
        assert(self.interface.pool is not None)
        async with self.interface.pool.acquire() as conn:
            async with conn.cursor() as cur:
                if self.log:
                    await cur.execute("INSERT INTO `log` (`name`, `ts`, `{}`) VALUES (%s, %s, %s)".format(column_name),
                                      (self.name, datetime.datetime.now().astimezone(), value))
                else:
                    await cur.execute("UPDATE `log` SET `ts` = %s, `{}` = %s WHERE `name` = %s".format(column_name),
                                      (datetime.datetime.now().astimezone(), value, self.name))
            await conn.commit()

    async def _read_from_log(self) -> Optional[T]:
        column_name = self._type_to_column(self.type)
        await self.interface.pool_ready.wait()
        assert(self.interface.pool is not None)
        async with self.interface.pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("SELECT `{}` from `log` WHERE `name` = %s ORDER BY `ts` DESC LIMIT 1"
                                  .format(column_name),
                                  (self.name,))
                value = await cur.fetchone()
        if value is None:
            return None
        logger.debug("Retrieved value %s for %s from %s", value, self, self.interface)
        return self._from_mysql_type(value[0])

    async def retrieve_log(self, start_time: datetime.datetime, end_time: datetime.datetime,
                            num: Optional[int] = None, offset: int = 0) -> List[Tuple[datetime.datetime, T]]:
        column_name = self._type_to_column(self.type)
        await self.interface.pool_ready.wait()
        assert(self.interface.pool is not None)
        async with self.interface.pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("SELECT `ts`, `{}` from `log` WHERE `name` = %s AND `ts` >= %s and `ts` < %s "
                                  "ORDER BY `ts` ASC{}".format(column_name, " LIMIT %s, %s" if num is not None else ""),
                                  (self.name, start_time, end_time) + ((offset, num) if num is not None else ()))
                return [(row[0], self._from_mysql_type(row[1]))
                        for row in await cur.fetchall()]

    @classmethod
    def _type_to_column(cls, type_: Type) -> str:
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

    def _from_mysql_type(self, value: Any) -> Any:
        if issubclass(self.type, (bool, int, float, str, enum.Enum)):
            return self.type(value)
        else:
            return from_json(self.type, json.loads(value))

    def __repr__(self):
        return "<{} '{}'>".format(self.__class__.__name__, self.name)
