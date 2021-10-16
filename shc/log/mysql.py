import asyncio
import datetime
import enum
import json
import logging
from typing import Optional, Type, Generic, List, Tuple, Any, Dict

import aiomysql
import pymysql

from ..base import T
from ..conversion import SHCJsonEncoder, from_json
from .generic import PersistenceVariable
from ..supervisor import AbstractInterface, InterfaceStatus, ServiceStatus

logger = logging.getLogger(__name__)


class MySQLPersistence(AbstractInterface):
    def __init__(self, **kwargs):
        super().__init__()
        # see https://aiomysql.readthedocs.io/en/latest/connection.html#connection for valid parameters
        self.connect_args = kwargs
        self.pool: Optional[aiomysql.Pool] = None
        self.pool_ready = asyncio.Event()
        self.variables: Dict[str, MySQLPersistenceVariable] = {}

    async def start(self) -> None:
        logger.info("Creating MySQL connection pool ...")
        self.pool = await aiomysql.create_pool(**self.connect_args)
        self.pool_ready.set()

    async def stop(self) -> None:
        if self.pool is not None:
            logger.info("Closing all MySQL connections ...")
            self.pool.close()
            await self.pool.wait_closed()

    async def get_status(self) -> "InterfaceStatus":
        if not self.pool_ready.is_set():
            return InterfaceStatus(ServiceStatus.CRITICAL, "Interface not started yet")
        assert(isinstance(self.pool, aiomysql.Pool))
        free_connections = self.pool.freesize
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cur:
                    await cur.execute("SELECT * from `log` WHERE FALSE")
        except pymysql.err.MySQLError as e:
            return InterfaceStatus(ServiceStatus.CRITICAL, str(e), {'free_connections': free_connections})
        return InterfaceStatus(ServiceStatus.OK, "", {'free_connections': free_connections})

    def variable(self, type_: Type, name: str, log: bool = True) -> "MySQLPersistenceVariable":
        if name in self.variables:
            variable = self.variables[name]
            if variable.type is not type_:
                raise ValueError("MySQL persistence variable with name {} has already been defined with type {}"
                                 .format(name, variable.type.__name__))
            return variable
        return MySQLPersistenceVariable(self, type_, name, log)

    def __repr__(self) -> str:
        return "{}({})".format(self.__class__.__name__, {k: v for k, v in self.connect_args.items()
                                                         if k in ('host', 'db', 'port', 'unix_socket')})


class MySQLPersistenceVariable(PersistenceVariable, Generic[T]):
    def __init__(self, interface: MySQLPersistence, type_: Type[T], name: str, log: bool):
        super().__init__(type_, log)
        self.interface = interface
        self.name = name
        self.log = log

    async def _write_to_log(self, value: T):
        column_name = self._type_to_column(type(value))
        value = self._into_mysql_type(value)
        await self.interface.pool_ready.wait()
        assert(self.interface.pool is not None)
        async with self.interface.pool.acquire() as conn:
            async with conn.cursor() as cur:
                if self.log:
                    await cur.execute("INSERT INTO `log` (`name`, `ts`, `{}`) VALUES (%s, %s, %s)".format(column_name),
                                      (self.name, datetime.datetime.now(datetime.timezone.utc), value))
                else:
                    await cur.execute("UPDATE `log` SET `ts` = %s, `{}` = %s WHERE `name` = %s".format(column_name),
                                      (datetime.datetime.now(datetime.timezone.utc), value, self.name))
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
                           include_previous: bool = True) -> List[Tuple[datetime.datetime, T]]:
        column_name = self._type_to_column(self.type)
        await self.interface.pool_ready.wait()
        assert(self.interface.pool is not None)
        async with self.interface.pool.acquire() as conn:
            async with conn.cursor() as cur:
                if include_previous:
                    await cur.execute(
                        "(SELECT `ts`, `{0}` from `log` WHERE `name` = %s AND `ts` <= %s "
                        " ORDER BY `ts` DESC LIMIT 1) "
                        "UNION (SELECT `ts`, `{0}` from `log` WHERE `name` = %s AND `ts` > %s AND `ts` < %s "
                        " ORDER BY `ts` ASC)".format(column_name),
                        (self.name, start_time, self.name, start_time, end_time))
                else:
                    await cur.execute(
                        "SELECT `ts`, `{0}` from `log` WHERE `name` = %s AND `ts` >= %s AND `ts` < %s "
                        "ORDER BY `ts` ASC".format(column_name),
                        (self.name, start_time, end_time))

                return [(row[0].replace(tzinfo=datetime.timezone.utc), self._from_mysql_type(row[1]))
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
