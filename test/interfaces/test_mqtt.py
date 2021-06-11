import asyncio
import logging
import shutil
import subprocess
import tracemalloc
import unittest
import unittest.mock

import asyncio_mqtt

import shc.interfaces.mqtt

from .._helper import InterfaceThreadRunner, async_test, ExampleWritable


@unittest.skipIf(shutil.which("mosquitto") is None, "mosquitto MQTT broker is not available in PATH")
class MQTTClientTest(unittest.TestCase):
    def setUp(self) -> None:
        tracemalloc.start()
        self.client = shc.interfaces.mqtt.MQTTClientInterface("localhost", 42883)
        self.broker_process = subprocess.Popen(["mosquitto", "-p", "42883"])

    def tearDown(self) -> None:
        asyncio.get_event_loop().run_until_complete(self.client.stop())
        self.broker_process.terminate()

    @async_test
    async def test_subscribe(self) -> None:
        logging.basicConfig(level=logging.DEBUG)

        async with asyncio_mqtt.Client("localhost", 42883, client_id="TestClient") as c:
            await c.publish("test/topic", b"42", 0, True)

        target_raw = ExampleWritable(bytes).connect(self.client.topic_raw('test/topic'))
        target_raw2 = ExampleWritable(bytes).connect(self.client.topic_raw('test/another/topic'))
        target_str = ExampleWritable(str).connect(self.client.topic_string('test/topic'))
        target_int = ExampleWritable(int).connect(self.client.topic_json(int, 'test/topic'))

        await self.client.start()

        await asyncio.sleep(0.50)

        target_raw._write.assert_called_once_with(b'42', unittest.mock.ANY)
        target_str._write.assert_called_once_with('42', unittest.mock.ANY)
        target_int._write.assert_called_once_with(42, unittest.mock.ANY)
        target_raw2._write.assert_not_called()
        target_raw._write.reset_mock()
        target_str._write.reset_mock()
        target_int._write.reset_mock()

        async with asyncio_mqtt.Client("localhost", 42883, client_id="TestClient") as c:
            await c.publish("test/topic", b"56", 0, False)

        await asyncio.sleep(0.05)

        target_raw._write.assert_called_once_with(b'56', unittest.mock.ANY)
        target_str._write.assert_called_once_with('56', unittest.mock.ANY)
        target_int._write.assert_called_once_with(56, unittest.mock.ANY)

    # TODO test_publish

    # TODO test_publish_message
    # TODO test_register_filtered_receiver

    # TODO test reconnect
