import asyncio
import datetime
import enum
import json
import logging
import math
from typing import Optional, Type, Generic, List, Tuple, Any, Dict, Callable

import aiomysql
import pymysql

from shc.base import T, Readable, UninitializedError, Writable
from shc.conversion import SHCJsonEncoder, from_json
from shc.data_logging import WritableDataLogVariable
from shc.interfaces._helper import ReadableStatusInterface
from shc.supervisor import InterfaceStatus, ServiceStatus

logger = logging.getLogger(__name__)


class MySQLConnector(ReadableStatusInterface):
    """
    Interface for using a MySQL (or MariaDB or Percona) server for logging and/or persistence

    A database with the following schema needs to be created manually on the database server:

    .. code-block:: mysql

        CREATE TABLE log (
            name VARCHAR(256) NOT NULL,
            ts DATETIME(6) NOT NULL,
            value_int INTEGER,
            value_float FLOAT,
            value_str LONGTEXT,
            KEY name_ts(name, ts)
        );

        CREATE TABLE `persistence` (
            name VARCHAR(256) NOT NULL,
            ts DATETIME(6) NOT NULL,
            value LONGTEXT,
            UNIQUE KEY name(name)
        );

    For data logging of all value types that are derived from `int` (incl. `bool`), `float` or `str`, the respective
    `value\\_` column is used. This includes Enum types with a value base type in any of those. Otherwise, the value is
    JSON-encoded, using SHC's generic JSON encoding/decoding system from the :mod:`shc.conversion`, and stored in the
    `value_str` column.

    Values of persistence variables are always JSON-encoded for storage.

    All timestamps are stored in UTC.

    The given constructor keyword arguments are passed to
    `aiomysql.connect() <https://aiomysql.readthedocs.io/en/latest/connection.html#connection>`_ for configuring the
    connection to the database server:

    * ``host: str`` (default: ``"localhost"``)
    * ``port: int`` (default: ``3306``)
    * (optional) ``unix_socket: str``
    * (optional) ``user: str``
    * ``password: str`` (default: ``""``)
    * ``db: str`` – name ot the database
    * (optional) ``read_default_file`` – path to my.cnf file to read all these options from
    """
    def __init__(self, **kwargs):
        super().__init__()
        # see https://aiomysql.readthedocs.io/en/latest/connection.html#connection for valid parameters
        self.connect_args = kwargs
        self.pool: Optional[aiomysql.Pool] = None
        self.pool_ready = asyncio.Event()
        self.variables: Dict[str, MySQLLogVariable] = {}
        self.persistence_variables: Dict[str, MySQLPersistenceVariable] = {}

    async def start(self) -> None:
        logger.info("Creating MySQL connection pool ...")
        self.pool = await aiomysql.create_pool(**self.connect_args)
        self.pool_ready.set()

    async def stop(self) -> None:
        if self.pool is not None:
            logger.info("Closing all MySQL connections ...")
            self.pool.close()
            await self.pool.wait_closed()

    async def _get_status(self) -> "InterfaceStatus":
        if not self.pool_ready.is_set():
            return InterfaceStatus(ServiceStatus.CRITICAL, "Interface not started yet")
        assert isinstance(self.pool, aiomysql.Pool)
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cur:
                    await cur.execute("SELECT * from `log` WHERE FALSE")
        except pymysql.err.MySQLError as e:
            return InterfaceStatus(ServiceStatus.CRITICAL, str(e))
        return InterfaceStatus(ServiceStatus.OK, "")

    def variable(self, type_: Type[T], name: str) -> "MySQLLogVariable[T]":
        """
        Creates a `connectable` object with the given value type for logging a time series of the given name in the
        MySQL database

        The returned object is :class:`writable <shc.base.Writable>`, :class:`readable <shc.base.Readable>` and a
        (subscribable) :class:`DataLogVariable <shc.data_logging.DataLogVariable>`.

        :param type_: The value type of the returned connectable variable object. It must provide a
                      :ref:`default JSON serialization <datatypes.json>`.
        :param name: The name of the time series in the database. Its length must not exceed the declared maximum length
                     of the log.name column in the database schema (256 by default). If the same name is requested
                     twice, the *same* connectable object instance will be returned.
        """
        if name in self.variables:
            variable = self.variables[name]
            if variable.type is not type_:
                raise ValueError("MySQL log variable with name {} has already been defined with type {}"
                                 .format(name, variable.type.__name__))
            return variable
        else:
            variable = MySQLLogVariable(self, type_, name)
            self.variables[name] = variable
            return variable

    def persistence_variable(self, type_: Type[T], name: str) -> "MySQLPersistenceVariable[T]":
        """
        Creates a `connectable` object with the given value type for persisting (only) the current value of a connected
        object under the given name in the MySQL database

        The returned object is :class:`writable <shc.base.Writable>`, :class:`readable <shc.base.Readable>`.

        :param type_: The value type of the returned connectable object. It must provide a
                      :ref:`default JSON serialization <datatypes.json>`.
        :param name: The *name* for identifying the value in the database. Its length must not exceed the declared
                     maximum length of the log.persistence column in the database schema (256 by default). If the same
                     name is requested twice, the *same* connectable object instance will be returned.
        """
        if name in self.persistence_variables:
            variable = self.persistence_variables[name]
            if variable.type is not type_:
                raise ValueError("MySQL persistence variable with name {} has already been defined with type {}"
                                 .format(name, variable.type.__name__))
            return variable
        else:
            variable = MySQLPersistenceVariable(self, type_, name)
            self.persistence_variables[name] = variable
            return variable

    def __repr__(self) -> str:
        return "{}({})".format(self.__class__.__name__, {k: v for k, v in self.connect_args.items()
                                                         if k in ('host', 'db', 'port', 'unix_socket')})


class MySQLPersistenceVariable(Writable[T], Readable[T], Generic[T]):
    type: Type[T]

    def __init__(self, interface: MySQLConnector, type_: Type[T], name: str, table: str = "persistence"):
        self.type = type_
        super().__init__()
        self.interface = interface
        self.name = name
        self.table = table
        self._write_query = self._get_write_query()
        self._read_query = self._get_read_query()
        self._to_mysql_converter: Callable[[T], Any] = self._get_to_mysql_converter(type_)
        self._from_mysql_converter: Callable[[Any], T] = self._get_from_mysql_converter(type_)

    async def read(self) -> T:
        await self.interface.pool_ready.wait()
        assert self.interface.pool is not None
        async with self.interface.pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(self._read_query, {'name': self.name})
                value = await cur.fetchone()
        if value is None:
            raise UninitializedError("No value has been persisted in MySQL database yet")
        logger.debug("Retrieved value %s for %s from %s", value, self, self.interface)
        return self._from_mysql_converter(value[0])

    async def _write(self, value: T, origin: List[Any]) -> None:
        await self.interface.pool_ready.wait()
        assert self.interface.pool is not None
        async with self.interface.pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(self._write_query,
                                  {'ts': datetime.datetime.now().astimezone(datetime.timezone.utc),
                                   'value': self._to_mysql_converter(value),
                                   'name': self.name})
            await conn.commit()

    def _get_write_query(self) -> str:
        return f"INSERT INTO `{self.table}` (`name`, `ts`, `value`) " \
               f"VALUES (%(name)s, %(ts)s, %(value)s)" \
               f"ON DUPLICATE KEY UPDATE " \
               f"`value`=%(value)s, `ts`=%(ts)s"

    def _get_read_query(self) -> str:
        return f"SELECT `value` " \
               f"FROM `{self.table}` " \
               f"WHERE `name` = %(name)s " \
               f"ORDER BY `ts` DESC LIMIT 1"

    @staticmethod
    def _get_to_mysql_converter(type_: Type[T]) -> Callable[[T], Any]:
        return lambda value: json.dumps(value, cls=SHCJsonEncoder)

    @staticmethod
    def _get_from_mysql_converter(type_: Type[T]) -> Callable[[Any], T]:
        return lambda value: from_json(type_, json.loads(value))

    def __repr__(self):
        return "<{} '{}'>".format(self.__class__.__name__, self.name)


class MySQLLogVariable(WritableDataLogVariable[T], Readable[T], Generic[T]):
    type: Type[T]

    def __init__(self, interface: MySQLConnector, type_: Type[T], name: str, table: str = "log"):
        self.type = type_
        super().__init__()
        self.interface = interface
        self.name = name
        self.table = table
        self._insert_query = self._get_insert_query()
        self._retrieve_query = self._get_retrieve_query(include_previous=False)
        self._retrieve_with_prev_query = self._get_retrieve_query(include_previous=True)
        self._read_query = self._get_read_query()
        self._to_mysql_converter: Callable[[T], Any] = self._get_to_mysql_converter(type_)
        self._from_mysql_converter: Callable[[Any], T] = self._get_from_mysql_converter(type_)

    async def read(self) -> T:
        await self.interface.pool_ready.wait()
        assert self.interface.pool is not None
        async with self.interface.pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(self._read_query, {'name': self.name})
                value = await cur.fetchone()
        if value is None:
            raise UninitializedError("No value has been persisted in MySQL database yet")
        logger.debug("Retrieved value %s for %s from %s", value, self, self.interface)
        return self._from_mysql_converter(value[0])

    async def _write_to_data_log(self, values: List[Tuple[datetime.datetime, T]]) -> None:
        await self.interface.pool_ready.wait()
        assert self.interface.pool is not None
        async with self.interface.pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.executemany(self._insert_query,
                                      [{'ts': ts.astimezone(datetime.timezone.utc),
                                        'value': self._to_mysql_converter(value),
                                        'name': self.name}
                                       for ts, value in values])
            await conn.commit()

    async def retrieve_log(self, start_time: datetime.datetime, end_time: datetime.datetime,
                           include_previous: bool = True) -> List[Tuple[datetime.datetime, T]]:
        await self.interface.pool_ready.wait()
        assert self.interface.pool is not None
        async with self.interface.pool.acquire() as conn:
            async with conn.cursor() as cur:
                if include_previous:
                    await cur.execute(
                        self._retrieve_with_prev_query,
                        {'name': self.name,
                         'start': start_time.astimezone(datetime.timezone.utc),
                         'end': end_time.astimezone(datetime.timezone.utc)})
                else:
                    await cur.execute(self._retrieve_query,
                                      {'name': self.name,
                                       'start': start_time.astimezone(datetime.timezone.utc),
                                       'end': end_time.astimezone(datetime.timezone.utc)})

                return [(row[0].replace(tzinfo=datetime.timezone.utc), self._from_mysql_converter(row[1]))
                        for row in await cur.fetchall()]

    def _get_insert_query(self) -> str:
        return f"INSERT INTO `{self.table}` (`name`, `ts`, `{self._type_to_column(self.type)}`) " \
               f"VALUES (%(name)s, %(ts)s, %(value)s)"

    def _get_retrieve_query(self, include_previous: bool) -> str:
        if include_previous:
            return f"(SELECT `ts`, `{self._type_to_column(self.type)}` " \
                   f" FROM `{self.table}` " \
                   f" WHERE `name` = %(name)s AND `ts` < %(start)s " \
                   f" ORDER BY `ts` DESC LIMIT 1) " \
                   f"UNION (SELECT `ts`, `{self._type_to_column(self.type)}` " \
                   f"       FROM `{self.table}` " \
                   f"       WHERE `name` = %(name)s AND `ts` >= %(start)s AND `ts` < %(end)s " \
                   f"       ORDER BY `ts` ASC)"
        else:
            return f"SELECT `ts`, `{self._type_to_column(self.type)}` " \
                   f"FROM `{self.table}` " \
                   f"WHERE `name` = %(name)s AND `ts` >= %(start)s AND `ts` < %(end)s " \
                   f"ORDER BY `ts` ASC"

    def _get_read_query(self) -> str:
        return f"SELECT `{self._type_to_column(self.type)}` " \
               f"FROM `{self.table}` " \
               f"WHERE `name` = %(name)s " \
               f"ORDER BY `ts` DESC LIMIT 1"

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

    @staticmethod
    def _get_to_mysql_converter(type_: Type[T]) -> Callable[[T], Any]:
        if type_ in (bool, int, float, str) or issubclass(type_, bool):
            return lambda x: x
        elif issubclass(type_, int):
            return lambda value: int(value)  # type: ignore  # type_ is equivalent to T -> int(a: int) is valid
        elif issubclass(type_, float):
            # type_ is equivalent to T -> float(a: float) is valid
            return lambda value: None if math.isnan(value) else float(value)  # type: ignore
        elif issubclass(type_, str):
            return lambda value: str(value)
        elif issubclass(type_, enum.Enum):
            return lambda value: value.value  # type: ignore  # type_ is equivalent to T -> T is subclass of enum
        else:
            return lambda value: json.dumps(value, cls=SHCJsonEncoder)

    @staticmethod
    def _get_from_mysql_converter(type_: Type[T]) -> Callable[[Any], T]:
        if type_ is bool:
            return lambda x: bool(x)  # type: ignore  # type_ is equivalent to T -> type_ is bool here
        elif type_ in (int, str):
            return lambda x: x
        elif type_ is float:
            return lambda x: x if x is not None else float("nan")
        elif issubclass(type_, (bool, int, str, enum.Enum)):
            return lambda value: type_(value)  # type: ignore  # type_ is equivalent to T -> type_() is an instance of T
        elif issubclass(type_, float):
            # type_ is equivalent to T -> type_() is an instance of T
            return lambda value: type_(value) if value is not None else type_(float("nan"))  # type: ignore
        else:
            return lambda value: from_json(type_, json.loads(value))

    def __repr__(self):
        return "<{} '{}'>".format(self.__class__.__name__, self.name)
