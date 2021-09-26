import asyncio
import json
import shutil
import subprocess
import time
import unittest
import unittest.mock
from contextlib import suppress
from typing import Dict, Any

import asyncio_mqtt  # type: ignore

import shc.interfaces.mqtt
import shc.interfaces.tasmota
from shc.datatypes import RGBWUInt8, RGBUInt8, RangeUInt8, RangeInt0To100
from test._helper import InterfaceThreadRunner, ExampleWritable, async_test


@unittest.skipIf(shutil.which("mosquitto") is None, "mosquitto MQTT broker is not available in PATH")
class TasmotaInterfaceTest(unittest.TestCase):
    def setUp(self) -> None:
        async def _construct(*args):
            return shc.interfaces.tasmota.TasmotaInterface(*args)

        self.client_runner = InterfaceThreadRunner(shc.interfaces.mqtt.MQTTClientInterface, "localhost", 42883)
        self.client = self.client_runner.interface
        self.interface: shc.interfaces.tasmota.TasmotaInterface = \
            asyncio.run_coroutine_threadsafe(_construct(self.client, 'test-device'), loop=self.client_runner.loop)\
            .result()
        self.broker_process = subprocess.Popen(["mosquitto", "-p", "42883"])
        time.sleep(0.25)

    def tearDown(self) -> None:
        asyncio.run_coroutine_threadsafe(self.interface.stop(), loop=self.client_runner.loop).result()
        self.client_runner.stop()
        self.broker_process.terminate()
        self.broker_process.wait()

    @async_test
    async def test_offline_state(self) -> None:
        task = asyncio.create_task(tasmota_device_mock("test-device"))
        await asyncio.sleep(0.25)

        try:
            target_offline = ExampleWritable(bool).connect(self.interface.online())
            self.client_runner.start()
            asyncio.run_coroutine_threadsafe(self.interface.start(), loop=self.client_runner.loop).result()
            await asyncio.sleep(0.25)

            target_offline._write.assert_called_once_with(True, unittest.mock.ANY)

            task.cancel()
            with suppress(asyncio.CancelledError):
                await task

            await asyncio.sleep(0.25)
            target_offline._write.assert_called_with(False, unittest.mock.ANY)

        except Exception:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
            raise

    @async_test
    async def test_color_external(self) -> None:
        def construct_color(r, g, b, w):
            return RGBWUInt8(RGBUInt8(RangeUInt8(r), RangeUInt8(g), RangeUInt8(b)), RangeUInt8(w))

        task = asyncio.create_task(tasmota_device_mock("test-device"))
        conn_color = self.interface.color_rgbw()
        target_color = ExampleWritable(RGBWUInt8).connect(conn_color)
        conn_power = self.interface.power()
        target_power = ExampleWritable(bool).connect(conn_power)
        await asyncio.sleep(0.25)

        try:
            self.client_runner.start()
            asyncio.run_coroutine_threadsafe(self.interface.start(), loop=self.client_runner.loop).result()

            await asyncio.sleep(0.25)
            target_color._write.assert_called_once_with(construct_color(0, 0, 0, 0), unittest.mock.ANY)
            target_power._write.assert_called_once_with(False, unittest.mock.ANY)

            async with asyncio_mqtt.Client("localhost", 42883, client_id="some-other-client") as c:
                await c.publish(f"cmnd/test-device/color", b'#aabbcc', retain=True)

            await asyncio.sleep(0.1)
            target_color._write.assert_called_with(construct_color(170, 187, 204, 0), [conn_color])  # rounding error
            target_power._write.assert_called_with(True, [conn_power])

        finally:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task

    @async_test
    async def test_color_internal(self) -> None:
        def construct_color(r, g, b, w):
            return RGBWUInt8(RGBUInt8(RangeUInt8(r), RangeUInt8(g), RangeUInt8(b)), RangeUInt8(w))

        task = asyncio.create_task(tasmota_device_mock("test-device"))
        conn_color = self.interface.color_rgbw()
        target_color = ExampleWritable(RGBWUInt8).connect(conn_color)
        conn_power = self.interface.power()
        target_power = ExampleWritable(bool).connect(conn_power)
        conn_dimmer = self.interface.dimmer()
        target_dimmer = ExampleWritable(RangeInt0To100).connect(conn_dimmer)
        await asyncio.sleep(0.25)

        try:
            self.client_runner.start()
            asyncio.run_coroutine_threadsafe(self.interface.start(), loop=self.client_runner.loop).result()

            await asyncio.sleep(0.25)
            target_color._write.assert_called_once_with(construct_color(0, 0, 0, 0), unittest.mock.ANY)
            target_power._write.assert_called_once_with(False, unittest.mock.ANY)

            future = asyncio.wrap_future(asyncio.run_coroutine_threadsafe(
                conn_color.write(construct_color(175, 117, 48, 66), [self]), loop=self.client_runner.loop))
            # Should only return when the message returns from the broker
            await asyncio.sleep(0.001)
            self.assertFalse(future.done())
            await future

            target_color._write.assert_called_with(construct_color(175, 117, 48, 66), [self, conn_color])
            target_power._write.assert_called_with(True, [self, conn_power])
            target_dimmer._write.assert_called_with(RangeInt0To100(68), [self, conn_dimmer])

        finally:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task

    @async_test
    async def test_sensor_ir(self) -> None:
        conn_ir = self.interface.ir_receiver()
        target_ir = ExampleWritable(bytes).connect(conn_ir)

        self.client_runner.start()
        asyncio.run_coroutine_threadsafe(self.interface.start(), loop=self.client_runner.loop).result()
        await asyncio.sleep(0.25)

        target_ir._write.assert_not_called()

        async with asyncio_mqtt.Client("localhost", 42883, client_id="some-other-client") as c:
            await c.publish(f"tele/test-device/RESULT",
                            json.dumps({"Time": "1970-01-10T03:12:43",
                                        "IrReceived": {"Protocol": "NEC", "Bits": 32, "Data": "0x00F7609F"}})
                            .encode('ascii'))

        await asyncio.sleep(0.25)
        target_ir._write.assert_called_once_with(b'\x00\xF7\x60\x9F', [conn_ir])

    @async_test
    async def test_sensor_power(self) -> None:
        conn_power = self.interface.energy_power()
        target_power = ExampleWritable(float).connect(conn_power)
        conn_voltage = self.interface.energy_voltage()
        target_voltage = ExampleWritable(float).connect(conn_voltage)
        conn_current = self.interface.energy_current()
        target_current = ExampleWritable(float).connect(conn_current)
        conn_factor = self.interface.energy_power_factor()
        target_factor = ExampleWritable(float).connect(conn_factor)
        conn_apparent_power = self.interface.energy_apparent_power()
        target_apparent_power = ExampleWritable(float).connect(conn_apparent_power)
        conn_reactive_power = self.interface.energy_reactive_power()
        target_reactive_power = ExampleWritable(float).connect(conn_reactive_power)
        conn_total = self.interface.energy_total()
        target_total = ExampleWritable(float).connect(conn_total)

        self.client_runner.start()
        asyncio.run_coroutine_threadsafe(self.interface.start(), loop=self.client_runner.loop).result()
        await asyncio.sleep(0.25)

        target_power._write.assert_not_called()
        target_voltage._write.assert_not_called()
        target_current._write.assert_not_called()
        target_factor._write.assert_not_called()
        target_apparent_power._write.assert_not_called()
        target_reactive_power._write.assert_not_called()
        target_total._write.assert_not_called()

        async with asyncio_mqtt.Client("localhost", 42883, client_id="some-other-client") as c:
            await c.publish(f"tele/test-device/SENSOR",
                            json.dumps({"Time": "1970-01-01T00:49:50",
                                        "ENERGY": {"TotalStartTime": "1970-01-01T00:00:00", "Total": 0.012,
                                                   "Yesterday": 0.000, "Today": 0.012, "Period": 2, "Power": 15,
                                                   "ApparentPower": 26, "ReactivePower": 22, "Factor": 0.56,
                                                   "Voltage": 227, "Current": 0.114}})
                            .encode('ascii'))

        await asyncio.sleep(0.25)
        target_power._write.assert_called_once_with(15.0, [conn_power])
        target_voltage._write.assert_called_once_with(227.0, [conn_voltage])
        target_current._write.assert_called_once_with(0.114, [conn_current])
        target_factor._write.assert_called_once_with(0.56, [conn_factor])
        target_apparent_power._write.assert_called_once_with(26.0, [conn_apparent_power])
        target_reactive_power._write.assert_called_once_with(22.0, [conn_reactive_power])
        target_total._write.assert_called_once_with(0.012, [conn_total])


BASE_STATUS11: Dict[str, Dict[str, Any]] = {
    "StatusSTS":
        {"Time": "1970-01-08T04:46:42", "Uptime": "7T04:46:38", "UptimeSec": 621998, "Heap": 26,
         "SleepMode": "Dynamic", "Sleep": 50, "LoadAvg": 19, "MqttCount": 1, "POWER": "OFF", "Dimmer": 100,
         "Color": "00CCFFEE", "HSBColor": "192,100,100", "White": 93, "Channel": [0, 80, 100, 93],
         "Scheme": 0, "Fade": "OFF", "Speed": 1, "LedTable": "ON",
         "Wifi": {
             "AP": 1, "SSId": "some-network", "BSSId": "00:11:22:33:44:55", "Channel": 11, "RSSI": 76,
             "Signal": -62, "LinkCount": 1, "Downtime": "0T00:00:03"}}}


async def tasmota_device_mock(deviceid: str) -> None:
    # state variables:
    channel = [0, 0, 0, 0]
    power = False

    async with asyncio_mqtt.Client("localhost", 42883, client_id="FakeTasmotaDevice") as c:
        await c.subscribe(f'cmnd/{deviceid}/+')
        await c.publish(f"tele/{deviceid}/LWT", b'Online', retain=True)

        try:
            async with c.unfiltered_messages() as messages:
                async for msg in messages:
                    if msg.topic == f'cmnd/{deviceid}/status':
                        if msg.payload.strip() == b'11':
                            status = BASE_STATUS11.copy()
                            status['StatusSTS']['POWER'] = 'ON' if power else 'OFF'
                            status['StatusSTS']['Dimmer'] = int(max(channel)/255*100)
                            status['StatusSTS']['Channel'] = [int(v/255*100) for v in channel]
                            status['StatusSTS']['Color'] = \
                                '{:0>2X}{:0>2X}{:0>2X}{:0>2X}'.format(*channel)
                            status['StatusSTS']['White'] = int(channel[3]/255*100)
                            # TODO insert current HSBColor
                            await c.publish(f"stat/{deviceid}/STATUS11", json.dumps(status).encode('ascii'))
                        else:
                            pass
                            # not implemented

                    elif msg.topic == f'cmnd/{deviceid}/power':
                        power = msg.payload.lower() not in (b'0', 'off', 'false')
                        await c.publish(f'stat/{deviceid}/RESULT', b'{"POWER":"' + (b'ON' if power else b'OFF') + b'"}')
                        await c.publish(f'stat/{deviceid}/POWER', b'ON' if power else b'OFF')

                    elif msg.topic == f'cmnd/{deviceid}/color':
                        if msg.payload[0] == ord('#'):
                            data = bytes.fromhex(msg.payload.decode('ascii')[1:])
                            data += bytes([0] * (4 - len(data)))
                            channel = list(data[0:4])
                        else:
                            # not implemented
                            continue
                        power = max(channel) != 0
                        await c.publish(f'stat/{deviceid}/RESULT',
                                        json.dumps({"POWER": 'ON' if power else 'OFF',
                                                    "Dimmer": int(max(channel)/255*100),
                                                    "Color": '{:0>2X}{:0>2X}{:0>2X}{:0>2X}'
                                                             .format(*channel),
                                                    "HSBColor": "48,100,100",  # TODO
                                                    "White": int(channel[3]/255*100),
                                                    "Channel": [int(v/255*100) for v in channel]}).encode('ascii'))

        except asyncio.CancelledError:
            await c.publish(f"tele/{deviceid}/LWT", b'Offline', retain=True)
            raise
