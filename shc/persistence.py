import abc
import json
import datetime
import logging
from typing import Type, Generic, List, Any, Optional

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
    async def _write(self, name: str, value: str, log: bool):
        pass

    @abc.abstractmethod
    async def _read(self, name: str) -> Optional[str]:
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
        value = await self.interface._read(self.name)
        if value is None:
            raise UninitializedError("No value for has been persistet for variable '{}' yet.".format(self.name))
        logger.debug("Retrieved value %s for %s from %s", value[0], self, self.interface)
        return from_json(self.type, json.loads(value[0]))

    async def _write(self, value: T, source: List[Any]):
        data = json.dumps(value, cls=SHCJsonEncoder)
        logger.debug("%s value %s for %s to persistence backend", "logging" if self.log else "updating", data, self)
        await self.interface._write(self.name, data, log=self.log)

    def __repr__(self):
        return "<PersistenceVariable '{}'>".format(self.name)


class MySQLPersistence(AbstractPersistenceInterface):
    def __init__(self, **kwargs):
        # see https://aiomysql.readthedocs.io/en/latest/connection.html#connection for valid parameters
        self.connect_args = kwargs
        self.pool: aiomysql.Pool
        register_interface(self)

    async def start(self) -> None:
        logger.info("Creating MySQL connection pool ...")
        self.pool = await aiomysql.create_pool(**self.connect_args)

    async def wait(self) -> None:
        pass

    async def stop(self) -> None:
        logger.info("Clossing all MySQL connections ...")
        self.pool.close()
        await self.pool.wait_closed()

    async def _write(self, name: str, value: str, log: bool):
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cur:
                if log:
                    await cur.execute("INSERT INTO `log` (`name`, `ts`, `value`) VALUES (%s, %s, %s)",
                                      (name, datetime.datetime.now().astimezone(), value))
                else:
                    await cur.execute("UPDATE `log` SET `ts` = %s, `value` = %s WHERE `name` = %s",
                                      (datetime.datetime.now().astimezone(), value, name))
            await conn.commit()

    async def _read(self, name: str) -> Optional[str]:
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("SELECT `value` from `log` WHERE `name` = %s ORDER BY `ts` DESC LIMIT 1", (name,))
                return await cur.fetchone()
