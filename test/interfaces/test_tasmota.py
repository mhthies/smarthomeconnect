import asyncio
import datetime
import json
import math
import shutil
import subprocess
import time
import unittest
import unittest.mock
from contextlib import suppress
from pathlib import Path
from typing import Any, Dict

import aiomqtt

import shc.interfaces.mqtt
import shc.interfaces.tasmota
from shc.datatypes import RangeInt0To100, RangeUInt8, RGBUInt8, RGBWUInt8
from shc.supervisor import InterfaceStatus, ServiceStatus
from test._helper import ExampleWritable, InterfaceThreadRunner


@unittest.skipIf(shutil.which("mosquitto") is None, "mosquitto MQTT broker is not available in PATH")
class TasmotaInterfaceTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        async def _construct(*args):
            return shc.interfaces.tasmota.TasmotaInterface(*args)

        self.client_runner = InterfaceThreadRunner(shc.interfaces.mqtt.MQTTClientInterface, "localhost", 42883)
        self.client = self.client_runner.interface
        self.interface: shc.interfaces.tasmota.TasmotaInterface = self.client_runner.run_coro(
            _construct(self.client, "test-device")
        )
        broker_config_file = Path(__file__).parent.parent / "assets" / "mosquitto.conf"
        self.broker_process = subprocess.Popen(["mosquitto", "-p", "42883", "-c", str(broker_config_file)])
        time.sleep(0.25)

    def tearDown(self) -> None:
        self.client_runner.run_coro(self.interface.stop())
        self.client_runner.stop()
        self.broker_process.terminate()
        self.broker_process.wait()

    async def test_offline_state(self) -> None:
        offline_connector = self.interface.online()
        target_offline = ExampleWritable(bool).connect(offline_connector)
        status_connector = self.interface.monitoring_connector()
        target_status = ExampleWritable(InterfaceStatus).connect(status_connector)
        self.client_runner.start()
        self.client_runner.run_coro(self.interface.start())
        await asyncio.sleep(0.25)
        self.assertEqual(False, self.client_runner.run_coro(offline_connector.read()))
        self.assertEqual(
            InterfaceStatus(ServiceStatus.CRITICAL, "No Last Will or telemetry received from Tasmota device by now"),
            self.client_runner.run_coro(status_connector.read()),
        )

        task = asyncio.create_task(tasmota_device_mock("test-device"))
        await asyncio.sleep(0.1)

        try:
            target_offline._write.assert_called_once_with(True, unittest.mock.ANY)
            target_status._write.assert_called_with(InterfaceStatus(ServiceStatus.OK, ""), unittest.mock.ANY)
            self.assertEqual(True, self.client_runner.run_coro(offline_connector.read()))
            self.assertEqual(
                InterfaceStatus(ServiceStatus.OK, ""), self.client_runner.run_coro(status_connector.read())
            )

            task.cancel()
            with suppress(asyncio.CancelledError):
                await task

            await asyncio.sleep(0.1)
            target_offline._write.assert_called_with(False, unittest.mock.ANY)
            target_status._write.assert_called_with(
                InterfaceStatus(ServiceStatus.CRITICAL, "Tasmota device is offline"), unittest.mock.ANY
            )

        except Exception:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
            raise

    async def test_telemetry(self) -> None:
        target_telemetry = ExampleWritable(shc.interfaces.tasmota.TasmotaTelemetry).connect(self.interface.telemetry())

        task = asyncio.create_task(tasmota_device_mock("test-device"))
        await asyncio.sleep(0.1)
        self.client_runner.start()
        self.client_runner.run_coro(self.interface.start())

        try:
            await asyncio.sleep(0.1)

            target_telemetry._write.assert_called_once()
            telemetry = target_telemetry._write.call_args[0][0]
            self.assertIsInstance(telemetry, shc.interfaces.tasmota.TasmotaTelemetry)
            self.assertEqual(26, telemetry.heap)
            self.assertEqual(datetime.timedelta(days=7, hours=4, minutes=46, seconds=38), telemetry.uptime)
            self.assertEqual("00:11:22:33:44:55", telemetry.wifi_bssid)
            self.assertEqual(-62, telemetry.wifi_signal)
            self.assertEqual(datetime.timedelta(seconds=3), telemetry.wifi_downtime)
        finally:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task

    async def test_telemetry_warning_state(self) -> None:
        # Recreate Tasmota interface with really short telemetry timeout
        async def _construct(*args):
            return shc.interfaces.tasmota.TasmotaInterface(self.client, "test-device", telemetry_interval=0.03)

        self.interface = self.client_runner.run_coro(_construct())

        status_connector = self.interface.monitoring_connector()
        target_status = ExampleWritable(InterfaceStatus).connect(status_connector)

        self.client_runner.start()
        self.client_runner.run_coro(self.interface.start())

        task = asyncio.create_task(tasmota_device_mock("test-device"))
        await asyncio.sleep(0.04)

        try:
            target_status._write.assert_called_with(InterfaceStatus(ServiceStatus.OK, ""), unittest.mock.ANY)

            await asyncio.sleep(0.02)  # more than 1,5x 0,01s; so we should get a warning
            target_status._write.assert_called_with(
                InterfaceStatus(ServiceStatus.WARNING, unittest.mock.ANY), unittest.mock.ANY
            )

            await asyncio.sleep(0.3)  # more than 10x 0,01s; so we should get an error
            target_status._write.assert_called_with(
                InterfaceStatus(ServiceStatus.CRITICAL, unittest.mock.ANY), unittest.mock.ANY
            )

        finally:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task

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
            self.client_runner.run_coro(self.interface.start())

            await asyncio.sleep(0.25)
            target_color._write.assert_called_once_with(construct_color(0, 0, 0, 0), unittest.mock.ANY)
            target_power._write.assert_called_once_with(False, unittest.mock.ANY)

            async with aiomqtt.Client("localhost", 42883, identifier="some-other-client") as c:
                await c.publish("cmnd/test-device/color", b"#aabbcc", retain=True)

            await asyncio.sleep(0.1)
            target_color._write.assert_called_with(construct_color(170, 187, 204, 0), [conn_color])  # rounding error
            target_power._write.assert_called_with(True, [conn_power])

        finally:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task

    async def test_color_internal(self) -> None:
        def construct_color(r, g, b, w):
            return RGBWUInt8(RGBUInt8(RangeUInt8(r), RangeUInt8(g), RangeUInt8(b)), RangeUInt8(w))

        conn_color = self.interface.color_rgbw()
        target_color = ExampleWritable(RGBWUInt8).connect(conn_color)
        conn_power = self.interface.power()
        target_power = ExampleWritable(bool).connect(conn_power)
        conn_dimmer = self.interface.dimmer()
        target_dimmer = ExampleWritable(RangeInt0To100).connect(conn_dimmer)

        task = asyncio.create_task(tasmota_device_mock("test-device"))
        await asyncio.sleep(0.25)

        try:
            self.client_runner.start()
            self.client_runner.run_coro(self.interface.start())

            await asyncio.sleep(0.25)
            target_color._write.assert_called_once_with(construct_color(0, 0, 0, 0), unittest.mock.ANY)
            target_power._write.assert_called_once_with(False, unittest.mock.ANY)

            future = asyncio.wrap_future(
                asyncio.run_coroutine_threadsafe(
                    conn_color.write(construct_color(175, 117, 48, 66), [self]), loop=self.client_runner.loop
                )
            )
            # Should only return when the message returns from the broker
            await asyncio.sleep(0.0005)
            self.assertFalse(future.done())
            await future

            target_color._write.assert_called_with(construct_color(175, 117, 48, 66), [self, conn_color])
            target_power._write.assert_called_with(True, [self, conn_power])
            target_dimmer._write.assert_called_with(RangeInt0To100(68), [self, conn_dimmer])

        finally:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task

    async def test_sensor_ir(self) -> None:
        conn_ir = self.interface.ir_receiver()
        target_ir = ExampleWritable(bytes).connect(conn_ir)

        self.client_runner.start()
        self.client_runner.run_coro(self.interface.start())
        await asyncio.sleep(0.25)

        target_ir._write.assert_not_called()

        async with aiomqtt.Client("localhost", 42883, identifier="some-other-client") as c:
            await c.publish(
                "tele/test-device/RESULT",
                json.dumps(
                    {"Time": "1970-01-10T03:12:43", "IrReceived": {"Protocol": "NEC", "Bits": 32, "Data": "0x00F7609F"}}
                ).encode("ascii"),
            )

        await asyncio.sleep(0.25)
        target_ir._write.assert_called_once_with(b"\x00\xf7\x60\x9f", [conn_ir])

    async def test_sensor_power(self) -> None:
        conn_energy = self.interface.energy()
        target_energy = ExampleWritable(shc.interfaces.tasmota.TasmotaEnergyMeasurement).connect(conn_energy)

        self.client_runner.start()
        self.client_runner.run_coro(self.interface.start())
        await asyncio.sleep(0.25)

        target_energy._write.assert_not_called()

        async with aiomqtt.Client("localhost", 42883, identifier="some-other-client") as c:
            await c.publish(
                "tele/test-device/SENSOR",
                json.dumps(
                    {
                        "Time": "1970-01-01T00:49:50",
                        "ENERGY": {
                            "TotalStartTime": "1970-01-01T00:00:00",
                            "Total": 0.012,
                            "Yesterday": 0.000,
                            "Today": 0.012,
                            "Period": 2,
                            "Power": 15,
                            "ApparentPower": 26,
                            "ReactivePower": 22,
                            "Factor": 0.56,
                            "Voltage": 227,
                            "Current": 0.114,
                        },
                    }
                ).encode("ascii"),
            )

        await asyncio.sleep(0.25)
        expected = shc.interfaces.tasmota.TasmotaEnergyMeasurement(
            power=15.0,
            voltage=227.0,
            current=0.114,
            power_factor=0.56,
            apparent_power=26.0,
            reactive_power=22.0,
            total_energy=0.012,
            frequency=float("NaN"),
            total_energy_today=0.012,
            total_energy_yesterday=0.0,
        )
        target_energy._write.assert_called_once_with(unittest.mock.ANY, [conn_energy])
        self.assertIsInstance(target_energy._write.call_args[0][0], shc.interfaces.tasmota.TasmotaEnergyMeasurement)
        for a, (name, e) in zip(target_energy._write.call_args[0][0], expected._asdict().items()):
            if math.isnan(a) and math.isnan(e):
                continue
            self.assertAlmostEqual(e, a, msg=f"Field {name} is not equal")


BASE_STATUS11: Dict[str, Dict[str, Any]] = {
    "StatusSTS": {
        "Time": "1970-01-08T04:46:42",
        "Uptime": "7T04:46:38",
        "UptimeSec": 621998,
        "Heap": 26,
        "SleepMode": "Dynamic",
        "Sleep": 50,
        "LoadAvg": 19,
        "MqttCount": 1,
        "POWER": "OFF",
        "Dimmer": 100,
        "Color": "00CCFFEE",
        "HSBColor": "192,100,100",
        "White": 93,
        "Channel": [0, 80, 100, 93],
        "Scheme": 0,
        "Fade": "OFF",
        "Speed": 1,
        "LedTable": "ON",
        "Wifi": {
            "AP": 1,
            "SSId": "some-network",
            "BSSId": "00:11:22:33:44:55",
            "Channel": 11,
            "RSSI": 76,
            "Signal": -62,
            "LinkCount": 1,
            "Downtime": "0T00:00:03",
        },
    }
}


async def tasmota_device_mock(deviceid: str) -> None:
    # state variables:
    channel = [0, 0, 0, 0]
    power = False

    async with aiomqtt.Client("localhost", 42883, identifier="FakeTasmotaDevice") as c:
        await c.subscribe(f"cmnd/{deviceid}/+")
        await c.publish(f"tele/{deviceid}/LWT", b"Online", retain=True)

        try:
            async for msg in c.messages:
                topic = str(msg.topic)
                payload = msg.payload
                if topic == f"cmnd/{deviceid}/status":
                    if payload.strip() == b"11":
                        status = BASE_STATUS11.copy()
                        status["StatusSTS"]["POWER"] = "ON" if power else "OFF"
                        status["StatusSTS"]["Dimmer"] = int(max(channel) / 255 * 100)
                        status["StatusSTS"]["Channel"] = [int(v / 255 * 100) for v in channel]
                        status["StatusSTS"]["Color"] = "{:0>2X}{:0>2X}{:0>2X}{:0>2X}".format(*channel)
                        status["StatusSTS"]["White"] = int(channel[3] / 255 * 100)
                        # TODO insert current HSBColor
                        # Running the publish() call in a separated Task is required to workaround a reoccuring hangup
                        # of the unit tests on Python 3.9, probably caused by a CPython bug, which results in this
                        # Task ignoring to be cancelled: https://github.com/python/cpython/issues/86296
                        asyncio.create_task(c.publish(f"stat/{deviceid}/STATUS11", json.dumps(status).encode("ascii")))
                    else:
                        pass
                        # not implemented

                elif topic == f"cmnd/{deviceid}/power":
                    power = payload.lower() not in (b"0", "off", "false")
                    asyncio.create_task(
                        c.publish(f"stat/{deviceid}/RESULT", b'{"POWER":"' + (b"ON" if power else b"OFF") + b'"}')
                    )
                    asyncio.create_task(c.publish(f"stat/{deviceid}/POWER", b"ON" if power else b"OFF"))

                elif topic == f"cmnd/{deviceid}/color":
                    if payload[0] == ord("#"):
                        data = bytes.fromhex(payload.decode("ascii")[1:])
                        data += bytes([0] * (4 - len(data)))
                        channel = list(data[0:4])
                    else:
                        # not implemented
                        continue
                    power = max(channel) != 0
                    asyncio.create_task(
                        c.publish(
                            f"stat/{deviceid}/RESULT",
                            json.dumps(
                                {
                                    "POWER": "ON" if power else "OFF",
                                    "Dimmer": int(max(channel) / 255 * 100),
                                    "Color": "{:0>2X}{:0>2X}{:0>2X}{:0>2X}".format(*channel),
                                    "HSBColor": "48,100,100",  # TODO
                                    "White": int(channel[3] / 255 * 100),
                                    "Channel": [int(v / 255 * 100) for v in channel],
                                }
                            ).encode("ascii"),
                        )
                    )

        except asyncio.CancelledError:
            try:
                await asyncio.wait_for(c.publish(f"tele/{deviceid}/LWT", b"Offline", retain=True), timeout=1)
            except asyncio.TimeoutError:
                pass
            raise
