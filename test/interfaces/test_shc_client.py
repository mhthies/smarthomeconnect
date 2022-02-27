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
import asyncio
import datetime
import logging
import unittest
import unittest.mock
import time
from typing import NamedTuple

import aiohttp

import shc.web
import shc.interfaces.shc_client
from test._helper import ExampleReadable, InterfaceThreadRunner, ExampleWritable, ExampleSubscribable, async_test, \
    ClockMock, AsyncMock


class ExampleType(NamedTuple):
    the_value: float
    is_it_real: bool


class SHCWebsocketClientTest(unittest.TestCase):
    def setUp(self) -> None:
        self.server_runner = InterfaceThreadRunner(shc.web.WebServer, "localhost", 42080)
        self.client_runner = InterfaceThreadRunner(shc.interfaces.shc_client.SHCWebClient, 'http://localhost:42080')
        self.server = self.server_runner.interface
        self.client = self.client_runner.interface

    def tearDown(self) -> None:
        self.client_runner.stop()
        self.server_runner.stop()

    def test_subscribe(self) -> None:
        self.server.api(int, "foo")
        bar_object = self.server.api(ExampleType, "bar")\
            .connect(ExampleReadable(ExampleType, ExampleType(42, True)))
        bar_source = ExampleSubscribable(ExampleType).connect(bar_object)

        client_foo = self.client.object(int, 'foo')
        client_bar = self.client.object(ExampleType, 'bar')
        foo_target = ExampleWritable(int).connect(client_foo)
        bar_target = ExampleWritable(ExampleType).connect(client_bar)

        self.server_runner.start()
        self.client_runner.start()

        time.sleep(0.05)
        foo_target._write.assert_not_called()
        bar_target._write.assert_called_once_with(ExampleType(42, True), [client_bar])
        self.assertIsInstance(bar_target._write.call_args[0][0], ExampleType)
        bar_target._write.reset_mock()

        self.server_runner.run_coro(bar_source.publish(ExampleType(56, False), [self]))
        time.sleep(0.05)
        bar_target._write.assert_called_once_with(ExampleType(56, False), [client_bar])

    @async_test
    async def test_subscribe_error(self) -> None:
        self.server.api(int, "foo")
        self.server.api(ExampleType, "bar")

        bar_client = self.client.object(int, 'bar')

        # Creating an option with equal name should return the same object again or raise a type error
        self.assertIs(self.client.object(int, 'bar'), bar_client)
        with self.assertRaises(TypeError):
            self.client.object(str, 'bar')

        # Test raising of connection errors on startup (server is not started yet)
        with self.assertRaises(aiohttp.ClientConnectionError):
            self.client_runner.start()

        self.server_runner.start()

        # Test raising of subscription errors on startup (inexistent api object name)
        # This requires that the object has a local subscriber (otherwise, subscription is skipped)
        another_client = shc.interfaces.shc_client.SHCWebClient('http://localhost:42080')
        foobar = another_client.object(int, 'foobar')
        foobar.subscribe(ExampleWritable(int))
        try:
            with self.assertRaises(shc.interfaces.shc_client.WebSocketAPIError):
                await another_client.start()
        finally:
            await another_client.stop()

    def test_read(self) -> None:
        self.server.api(int, "foo")
        self.server.api(ExampleType, "bar")\
            .connect(ExampleReadable(ExampleType, ExampleType(42, True)))

        client_foo = self.client.object(int, 'foo')
        client_bar = self.client.object(ExampleType, 'bar')

        self.server_runner.start()
        self.client_runner.start()

        with self.assertRaises(shc.base.UninitializedError):
            self.client_runner.run_coro(client_foo.read())

        result = self.client_runner.run_coro(client_bar.read())
        self.assertIsInstance(result, ExampleType)
        self.assertEqual(ExampleType(42, True), result)

    def test_write(self) -> None:
        server_bar = self.server.api(ExampleType, "bar")
        target = ExampleWritable(ExampleType).connect(server_bar)

        client_bar = self.client.object(ExampleType, 'bar')

        self.server_runner.start()
        self.client_runner.start()

        self.client_runner.run_coro(client_bar.write(ExampleType(42, True), [self]))
        time.sleep(0.05)
        target._write.assert_called_once_with(ExampleType(42, True), unittest.mock.ANY)
        self.assertIsInstance(target._write.call_args[0][0], ExampleType)

    def test_client_online_object(self) -> None:
        server_bar = self.server.api(bool, "bar")
        target = ExampleWritable(bool).connect(server_bar)

        # a bit hacky, but IMHO, it's okay to not test the constructor propertly ;)
        self.client.client_online_object = "bar"

        self.server_runner.start()
        self.client_runner.start()

        time.sleep(0.05)
        target._write.assert_called_once_with(True, unittest.mock.ANY)

        self.client_runner.stop()
        time.sleep(0.05)
        target._write.assert_called_with(False, unittest.mock.ANY)

        # Test raising of an error on startup if the object does not exist at the server
        another_client = shc.interfaces.shc_client.SHCWebClient('http://localhost:42080', client_online_object="foobar")
        try:
            with self.assertRaises(shc.interfaces.shc_client.WebSocketAPIError):
                asyncio.get_event_loop().run_until_complete(another_client.start())
        finally:
            asyncio.get_event_loop().run_until_complete(another_client.stop())

    def test_reconnect(self) -> None:
        self.server.api(ExampleType, "bar")\
            .connect(ExampleReadable(ExampleType, ExampleType(42, True)))
        foo_server_target = ExampleWritable(int).connect(self.server.api(int, "foo"))

        client_bar = self.client.object(ExampleType, 'bar')
        bar_target = ExampleWritable(ExampleType).connect(client_bar)
        client_foo = self.client.object(int, 'foo')\
            .connect(ExampleReadable(int, 56), read=True)

        self.server_runner.start()
        self.client_runner.start()

        bar_target._write.assert_called_once_with(ExampleType(42, True), [client_bar])
        bar_target._write.reset_mock()
        foo_server_target._write.assert_called_once_with(56, unittest.mock.ANY)
        # We cannot use ClockMock here, since it does not support asyncio.wait()

        with self.assertLogs("shc.interfaces._helper", logging.ERROR) as ctx:
            self.server_runner.stop()
        self.assertIn("Unexpected shutdown", ctx.output[0])  # type: ignore
        self.assertIn("SHCWebClient", ctx.output[0])  # type: ignore

        # Re-setup server
        self.server_runner = InterfaceThreadRunner(shc.web.WebServer, "localhost", 42080)
        self.server = self.server_runner.interface
        self.server.api(ExampleType, "bar")\
            .connect(ExampleReadable(ExampleType, ExampleType(42, True)))
        foo_server_target = ExampleWritable(int).connect(self.server.api(int, "foo"))

        # Wait for first reconnect attempt
        with self.assertLogs("shc.interfaces._helper", logging.ERROR) as ctx:
            time.sleep(1.1)
        self.assertIn("Error in interface SHCWebClient", ctx.output[0])  # type: ignore
        self.assertIn("Cannot connect to host", ctx.output[0])  # type: ignore

        # Start server
        self.server_runner.start()

        # Wait for second reconnect attempt
        with unittest.mock.patch.object(self.client._session, 'ws_connect', new=AsyncMock()) as connect_mock:
            time.sleep(1)
            connect_mock.assert_not_called()
        time.sleep(0.3)

        bar_target._write.assert_called_once_with(ExampleType(42, True), [client_bar])
        foo_server_target._write.assert_called_once_with(56, unittest.mock.ANY)

    def test_initial_reconnect(self) -> None:
        self.client.failsafe_start = True
        client_bar = self.client.object(ExampleType, 'bar')
        bar_target = ExampleWritable(ExampleType).connect(client_bar)

        # We cannot use ClockMock here, since the server seems to be too slow then

        with self.assertLogs("shc.interfaces._helper", logging.ERROR) as ctx:
            self.client_runner.start()
            time.sleep(0.5)
        self.assertIn("Error in interface SHCWebClient", ctx.output[0])  # type: ignore
        self.assertIn("Cannot connect to host", ctx.output[0])  # type: ignore

        # Start server
        self.server_runner.start()

        # Client should still fail due to missing API object
        with self.assertLogs("shc.interfaces._helper", logging.ERROR) as ctx:
            time.sleep(0.6)
        self.assertIn("Error in interface SHCWebClient", ctx.output[0])  # type: ignore
        self.assertIn("Failed to subscribe SHC API object 'bar'", ctx.output[0])  # type: ignore

        # Re-setup server
        self.server_runner.stop()
        self.server_runner = InterfaceThreadRunner(shc.web.WebServer, "localhost", 42080)
        self.server = self.server_runner.interface
        self.server.api(ExampleType, "bar") \
            .connect(ExampleReadable(ExampleType, ExampleType(42, True)))
        self.server_runner.start()

        # wait for second reconnect attempt
        with unittest.mock.patch.object(self.client._session, 'ws_connect', new=AsyncMock()) as connect_mock:
            time.sleep(1)
            connect_mock.assert_not_called()
        time.sleep(0.3)

        bar_target._write.assert_called_once_with(ExampleType(42, True), [client_bar])


class SHCWebsocketClientConcurrentUpdateTest(unittest.TestCase):
    def setUp(self) -> None:
        self.server = shc.web.WebServer("localhost", 42080)
        self.client = shc.interfaces.shc_client.SHCWebClient('http://localhost:42080')

    def tearDown(self) -> None:
        loop = asyncio.get_event_loop()
        loop.run_until_complete(self.client.stop())
        loop.run_until_complete(self.server.stop())

    @async_test
    async def test_concurrent_update(self) -> None:
        foo_api = self.server.api(int, 'foo')
        server_var = shc.Variable(int, initial_value=0).connect(foo_api)
        foo_client = self.client.object(int, 'foo')
        client_var = shc.Variable(int).connect(foo_client)

        await self.server.start()
        await self.client.start()
        await asyncio.sleep(0.1)

        self.assertEqual(0, await client_var.read())

        await asyncio.gather(foo_api.write(42, [self]),
                             foo_client.write(56, [self]))
        await asyncio.sleep(0.1)
        self.assertEqual(await client_var.read(),
                         await server_var.read())
