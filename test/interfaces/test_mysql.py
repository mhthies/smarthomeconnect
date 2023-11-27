import datetime
import asyncio
import unittest
import urllib.parse
from typing import Tuple, Type, Iterable, Dict
import os

import aiomysql
import pymysql

import shc.data_logging
import shc.interfaces.mysql
from shc.base import T
from ..test_data_logging import AbstractLoggingTest


def parse_mysql_url(url: str) -> Dict[str, any]:
    try:
        parts = urllib.parse.urlparse(url)
    except ValueError as e:
        print(f"Could not parse MySQL connection URL: {e}")
    if parts.scheme != "mysql":
        print(f"Could not parse MySQL connection URL: Schema is not 'mysql'")
    result = {'user': parts.username, 'password': parts.password, 'db': parts.path.lstrip("/")}
    if parts.netloc.startswith("/"):
        result["unix_socket"] = parts.hostname
    else:
        result["host"] = parts.hostname
        if parts.port is not None:
            result["port"] = parts.port
    result.update(urllib.parse.parse_qsl(parts.query))
    return result


MYSQL_URL = os.getenv("SHC_TEST_MSQL_URL")
MYSQL_ARGS = parse_mysql_url(MYSQL_URL) if MYSQL_URL is not None else None
# pymysql uses slightly different args than aiomysql
PYMYSQL_ARGS = dict(MYSQL_ARGS, database= MYSQL_ARGS["db"])
del PYMYSQL_ARGS["db"]


@unittest.skipIf(MYSQL_ARGS is None, "No MySQL database connection given. Must be specified as URL "
                                     "mysql://user:pass@host/database in env variable SHC_TEST_MSQL_URL")
class MySQLTest(AbstractLoggingTest):
    do_write_tests = True
    do_subscribe_tests = True

    def setUp(self) -> None:
        self._run_mysql_sync("""
            CREATE TABLE `log` (
                name VARCHAR(256) NOT NULL,
                ts DATETIME(6) NOT NULL,
                value_int INTEGER,
                value_float FLOAT,
                value_str LONGTEXT,
                KEY name_ts(name, ts)
            );
            """)
        self.interface = shc.interfaces.mysql.MySQLConnector(**MYSQL_ARGS)
        loop = asyncio.get_event_loop()
        loop.run_until_complete(self.interface.start())

    def tearDown(self) -> None:
        loop = asyncio.get_event_loop()
        loop.run_until_complete(self.interface.stop())
        self._run_mysql_sync("""
            DROP TABLE `log`;
            """)

    def _run_mysql_sync(self, query: str) -> None:
        connection = pymysql.connect(**PYMYSQL_ARGS)
        cursor = connection.cursor()
        cursor.execute(query)
        cursor.close()
        connection.commit()
        connection.close()

    async def _create_log_variable_with_data(self, type_: Type[T], data: Iterable[Tuple[datetime.datetime, T]]) \
            -> shc.data_logging.DataLogVariable[T]:
        async with aiomysql.connect(**MYSQL_ARGS) as conn:
            async with conn.cursor() as cur:
                # All data in the tests is float, int or str, so we don't need to convert
                column = {
                    bool: "value_int",
                    int: "value_int",
                    float: "value_float",
                    str: "value_str",
                }[type_]
                await cur.executemany(
                    f"INSERT INTO `log` (`name`, `ts`, `{column}`) VALUES (%(name)s, %(ts)s, %(value)s)",
                    [{'ts': ts.astimezone(datetime.timezone.utc), 'value': value, 'name': "test_variable"}
                     for ts, value in data])
            await conn.commit()

        var = self.interface.variable(type_, "test_variable")
        return var
