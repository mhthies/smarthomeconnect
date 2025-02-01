import asyncio
import logging
import shutil
import subprocess
import time
import unittest
import unittest.mock
from contextlib import suppress
from pathlib import Path
from typing import List

import aiomqtt

import shc.interfaces.mqtt

from .._helper import AsyncMock, ExampleWritable, InterfaceThreadRunner, async_test


@unittest.skipIf(shutil.which("mosquitto") is None, "mosquitto MQTT broker is not available in PATH")
class MQTTClientTest(unittest.TestCase):
    def setUp(self) -> None:
        self.client_runner = InterfaceThreadRunner(shc.interfaces.mqtt.MQTTClientInterface, "localhost", 42883)
        self.client = self.client_runner.interface
        self.broker_config_file = Path(__file__).parent.parent / "assets" / "mosquitto.conf"
        self.broker_process = subprocess.Popen(["mosquitto", "-p", "42883", "-c", str(self.broker_config_file)])
        time.sleep(0.25)

    def tearDown(self) -> None:
        self.client_runner.stop()
        self.broker_process.terminate()
        self.broker_process.wait()

    @staticmethod
    async def _send_retained_test_message() -> None:
        async with aiomqtt.Client("localhost", 42883, identifier="TestClient") as c:
            await c.publish("test/topic", b"42", 0, True)

    @async_test
    async def test_subscribe(self) -> None:
        await self._send_retained_test_message()

        target_raw = ExampleWritable(bytes).connect(self.client.topic_raw("test/topic"))
        target_raw2 = ExampleWritable(bytes).connect(self.client.topic_raw("test/another/topic"))
        target_str = ExampleWritable(str).connect(self.client.topic_string("test/topic", "test/#"))
        target_int = ExampleWritable(int).connect(self.client.topic_json(int, "test/topic"))

        self.client_runner.start()

        await asyncio.sleep(0.50)

        # Due to the double-subscription to test/topic, they may be called multiple times
        target_raw._write.assert_called_with(b"42", unittest.mock.ANY)
        target_raw2._write.assert_not_called()
        target_str._write.assert_called_with("42", unittest.mock.ANY)
        target_int._write.assert_called_with(42, unittest.mock.ANY)
        target_raw._write.reset_mock()
        target_str._write.reset_mock()
        target_int._write.reset_mock()

        async with aiomqtt.Client("localhost", 42883, identifier="TestClient") as c:
            await c.publish("test/topic", b"56", 0, False)

        await asyncio.sleep(0.05)

        target_raw._write.assert_called_once_with(b"56", unittest.mock.ANY)
        target_str._write.assert_called_once_with("56", unittest.mock.ANY)
        target_int._write.assert_called_once_with(56, unittest.mock.ANY)
        target_raw._write.reset_mock()
        target_str._write.reset_mock()
        target_int._write.reset_mock()

        async with aiomqtt.Client("localhost", 42883, identifier="TestClient") as c:
            await c.publish("test/something", b"21", 0, False)

        await asyncio.sleep(0.05)

        target_raw._write.assert_not_called()
        target_str._write.assert_called_once_with("21", unittest.mock.ANY)
        target_raw._write.assert_not_called()

    @async_test
    async def test_publish(self) -> None:
        MESSAGES: List[aiomqtt.Message] = []

        async def _task() -> None:
            async with aiomqtt.Client("localhost", 42883, identifier="TestClient") as c:
                await c.subscribe("#")
                async for msg in c.messages:
                    MESSAGES.append(msg)

        task = asyncio.create_task(_task())
        await asyncio.sleep(0.1)

        try:
            conn_raw = self.client.topic_raw("test/topic", qos=2)
            conn_str = self.client.topic_string("test/another/topic", "test/another/#", retain=True)
            conn_json = self.client.topic_json(str, "test/topic", force_mqtt_subscription=True)
            target_str = ExampleWritable(str).connect(conn_str)

            self.client_runner.start()

            await self.client_runner.run_coro_async(conn_raw.write(b'"500"', [self]))
            # Write might not wait until the message is published
            await asyncio.sleep(0.1)
            self.assertEqual(1, len(MESSAGES))
            self.assertEqual(b'"500"', MESSAGES[-1].payload)
            self.assertEqual("test/topic", str(MESSAGES[-1].topic))

            await self.client_runner.run_coro_async(conn_str.write("a test with »«", [self]))
            # Due to the local subscriber, write() should wait until the message has been received
            target_str._write.assert_called_once_with("a test with »«", [self, conn_str])
            await asyncio.sleep(0.01)
            self.assertEqual(2, len(MESSAGES))
            self.assertEqual("a test with »«".encode("utf-8"), MESSAGES[-1].payload)
            self.assertEqual("test/another/topic", str(MESSAGES[-1].topic))

            await self.client_runner.run_coro_async(conn_json.write("text", [self]))
            # Du to the forced subscription, write() should wait until the message has been received
            await asyncio.sleep(0.01)
            self.assertEqual(3, len(MESSAGES))
            self.assertEqual(b'"text"', MESSAGES[-1].payload)
            self.assertEqual("test/topic", str(MESSAGES[-1].topic))

        finally:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task

    def test_reconnect(self) -> None:
        asyncio.get_event_loop().run_until_complete(self._send_retained_test_message())

        target_raw = ExampleWritable(bytes).connect(self.client.topic_raw("test/topic"))
        self.client_runner.start()
        # We cannot use ClockMock here, since it does not support asyncio.wait()
        time.sleep(0.05)
        target_raw._write.assert_called_once_with(b"42", unittest.mock.ANY)
        target_raw._write.reset_mock()

        with self.assertLogs("shc.interfaces._helper", logging.ERROR) as ctx:
            self.broker_process.terminate()
            self.broker_process.wait()
            time.sleep(0.2)
        self.assertIn("Disconnected", ctx.output[0])
        self.assertIn("MQTTClientInterface", ctx.output[0])

        # Wait for first reconnect attempt
        with self.assertLogs("shc.interfaces._helper", logging.ERROR) as ctx:
            time.sleep(1.1)
        self.assertIn("Error in interface MQTTClientInterface", ctx.output[0])
        # self.assertIn("Connection refused", ctx.output[0])

        # Restart server
        self.broker_process = subprocess.Popen(["mosquitto", "-p", "42883", "-c", str(self.broker_config_file)])

        # Wait for second reconnect attempt
        with unittest.mock.patch.object(self.client.client, "__aenter__", new=AsyncMock()) as connect_mock:
            time.sleep(0.8)
            connect_mock.assert_not_called()

        asyncio.get_event_loop().run_until_complete(self._send_retained_test_message())
        time.sleep(5)

        target_raw._write.assert_called_once_with(b"42", unittest.mock.ANY)

    def test_initial_reconnect(self) -> None:
        asyncio.get_event_loop().run_until_complete(self._send_retained_test_message())
        self.client.failsafe_start = True
        target_raw = ExampleWritable(bytes).connect(self.client.topic_raw("test/topic"))

        self.broker_process.terminate()
        self.broker_process.wait()

        # We cannot use ClockMock here, since the server seems to be too slow then

        with self.assertLogs("shc.interfaces._helper", logging.ERROR) as ctx:
            self.client_runner.start()
            time.sleep(0.5)
        self.assertIn("Error in interface MQTTClientInterface", ctx.output[0])
        self.assertIn("Connection refused", ctx.output[0])

        # Restart server
        self.broker_process = subprocess.Popen(["mosquitto", "-p", "42883", "-c", str(self.broker_config_file)])
        time.sleep(0.25)
        asyncio.get_event_loop().run_until_complete(self._send_retained_test_message())

        # wait for reconnect attempt
        with unittest.mock.patch.object(self.client.client, "__aenter__", new=AsyncMock()) as connect_mock:
            time.sleep(0.15)
            connect_mock.assert_not_called()
        time.sleep(0.4)

        target_raw._write.assert_called_once_with(b"42", unittest.mock.ANY)
