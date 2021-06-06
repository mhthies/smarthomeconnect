# Copyright 2021 Michael Thies <mail@mhthies.de>
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
import collections
import functools
import json
import logging
import time
from typing import List, Any, Dict, Deque, Generic, Union, Type, TypeVar, Tuple, cast

from paho.mqtt.client import MQTTMessage  # type: ignore

from ..base import Writable, Subscribable, T, Readable
from .mqtt import MQTTClientInterface
from ..datatypes import RangeInt0To100, RGBUInt8, RangeUInt8, RGBWUInt8, RGBCCTUInt8, CCTUInt8
from ..supervisor import AbstractInterface, InterfaceStatus, ServiceStatus

logger = logging.getLogger(__name__)

ConnType = TypeVar("ConnType", bound="AbstractTasmotaConnector")
JSONType = Union[str, float, int, None, Dict[str, Any], List[Any]]


class TasmotaInterface(AbstractInterface):
    def __init__(self, mqtt_interface: MQTTClientInterface, device_topic: str,
                 topic_template: str = "{prefix}/{topic}/", telemetry_interval: int = 300):
        super().__init__()
        self.mqtt_interface = mqtt_interface
        self.device_topic = device_topic
        self.topic_template = topic_template
        self.telemetry_interval = telemetry_interval
        self._connectors_by_result_field: Dict[str, List[AbstractTasmotaConnector]] = {}
        self._connectors_by_type: Dict[Type[AbstractTasmotaConnector], AbstractTasmotaConnector] = {}
        self._pending_commands: Deque[Tuple[str, List[Any], asyncio.Event]] = collections.deque()
        self._online_connector = TasmotaOnlineConnector()

        self._latest_telemetry_time = None
        self._latest_telemetry = None

        mqtt_interface.register_filtered_receiver(topic_template.format(prefix='tele', topic=device_topic) + 'RESULT',
                                                  self._handle_result_or_status, 1)
        mqtt_interface.register_filtered_receiver(topic_template.format(prefix='stat', topic=device_topic) + 'RESULT',
                                                  functools.partial(self._handle_result_or_status, result=True), 1)
        mqtt_interface.register_filtered_receiver(topic_template.format(prefix='tele', topic=device_topic) + 'STATE',
                                                  self._handle_result_or_status, 1)
        mqtt_interface.register_filtered_receiver(topic_template.format(prefix='stat', topic=device_topic) + 'STATUS11',
                                                  self._handle_status11, 1)
        mqtt_interface.register_filtered_receiver(topic_template.format(prefix='tele', topic=device_topic) + 'LWT',
                                                  self._online_connector._update_from_mqtt, 1)

    async def start(self) -> None:
        await asyncio.sleep(.1)
        await self.mqtt_interface.wait_running(5)
        await self._send_command("status", "11")

    async def stop(self) -> None:
        pass

    async def get_status(self) -> InterfaceStatus:
        if not self._online_connector.value:
            return InterfaceStatus(ServiceStatus.CRITICAL, "Tasmota device is not online")
        if not self._latest_telemetry and self.telemetry_interval:
            return InterfaceStatus(ServiceStatus.CRITICAL, "No telemetry data received from Tasmota device by now")
        last_telemetry_age = time.monotonic() - self._latest_telemetry_time
        if last_telemetry_age > 10 * self.telemetry_interval:
            return InterfaceStatus(ServiceStatus.CRITICAL, "No telemetry data received from Tasmota device by now")
        indicators = {
            'telemetry_age': last_telemetry_age,
            'tasmota.UptimeSec': self._latest_telemetry.get('UptimeSec'),
            'tasmota.Heap': self._latest_telemetry.get('Heap'),
            'tasmota.LoadAvg': self._latest_telemetry.get('LoadAvg'),
            'tasmota.Wifi.RSSI': self._latest_telemetry.get('Wifi', {}).get('RSSI'),
            'tasmota.Wifi.Signal': self._latest_telemetry.get('Wifi', {}).get('Signal'),
            'tasmota.Wifi.Downtime': self._latest_telemetry.get('Wifi', {}).get('Downtime'),
        }
        if last_telemetry_age > 10 * self.telemetry_interval:
            return InterfaceStatus(status=ServiceStatus.CRITICAL,
                                   message="Latest telemetry data from Tasmota device is {:.2f}s old (more than 10x the"
                                           " expected telemetry interval)".format(last_telemetry_age),
                                   indicators=indicators)
        if last_telemetry_age > 1.5 * self.telemetry_interval:
            return InterfaceStatus(status=ServiceStatus.WARNING,
                                   message="Latest telemetry data from Tasmota device is {:.2f}s old (more than 1.5x "
                                           "the expected telemetry interval)".format(last_telemetry_age),
                                   indicators=indicators)
        return InterfaceStatus(indicators=indicators)

    async def _handle_result_or_status(self, msg: MQTTMessage, result: bool = False) -> None:
        try:
            data = json.loads(msg.payload.decode('utf-8'))
            assert isinstance(data, dict)
        except (json.JSONDecodeError, UnicodeDecodeError, AssertionError) as e:
            logger.error("Could not decode Tasmota result as JSON object: %s", msg.payload, exc_info=e)
            return
        await self._dispatch_status(data, result)

    async def _handle_status11(self, msg: MQTTMessage) -> None:
        try:
            data = json.loads(msg.payload.decode('utf-8'))
            assert isinstance(data, dict)
            assert 'StatusSTS' in data
            assert isinstance(data['StatusSTS'], dict)
        except (json.JSONDecodeError, UnicodeDecodeError, AssertionError) as e:
            logger.error("Could not decode Tasmota telemetry status as JSON object: %s", msg.payload, exc_info=e)
            return
        await self._dispatch_status(data['StatusSTS'], False)

    async def _dispatch_status(self, data: JSONType, result: bool) -> None:
        logger.debug("Dispatching Tasmota result/status from %s: %s", self.device_topic, data)

        origin = []
        event = None
        if result:
            for field, origin_, event_ in self._pending_commands:
                if field in data:
                    origin = origin_
                    event = event_
                    break

        for key, value in data.items():
            for connector in self._connectors_by_result_field.get(key, []):
                # TODO handle errors
                await connector._publish(connector._decode(value), origin)
        if event:
            event.set()

        if not result and "Uptime" in data:
            self._latest_telemetry = data
            self._latest_telemetry_time = time.monotonic()

    def online(self) -> "TasmotaOnlineConnector":
        return self._online_connector

    def power(self) -> "TasmotaPowerConnector":
        return self._get_or_create_connector(TasmotaPowerConnector)

    def dimmer(self) -> "TasmotaDimmerConnector":
        return self._get_or_create_connector(TasmotaDimmerConnector)

    def color_cct(self) -> "TasmotaColorCCTConnector":
        return self._get_or_create_connector(TasmotaColorCCTConnector)

    def color_rgb(self) -> "TasmotaColorRGBConnector":
        return self._get_or_create_connector(TasmotaColorRGBConnector)

    def color_rgbw(self) -> "TasmotaColorRGBWConnector":
        return self._get_or_create_connector(TasmotaColorRGBWConnector)

    def color_rgbcct(self) -> "TasmotaColorRGBCCTConnector":
        return self._get_or_create_connector(TasmotaColorRGBCCTConnector)

    def ir_receiver(self) -> "TasmotaIRReceiverConnector":
        return self._get_or_create_connector(TasmotaIRReceiverConnector)

    def _get_or_create_connector(self, type_: Type[ConnType]) -> ConnType:
        if type_ in self._connectors_by_type:
            return cast(ConnType, self._connectors_by_type[type_])
        else:
            conn = type_(self)  # type: ignore
            self._connectors_by_type[type_] = conn
            if conn.result_field in self._connectors_by_result_field:
                self._connectors_by_result_field[conn.result_field].append(conn)
            else:
                self._connectors_by_result_field[conn.result_field] = [conn]
            return conn

    async def _send_command(self, command: str, value: str):
        await self.mqtt_interface.publish_message(
            self.topic_template.format(prefix='cmnd', topic=self.device_topic) + command,
            value.encode())

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}({self.device_topic})"


class AbstractTasmotaConnector(Subscribable[T], Generic[T], metaclass=abc.ABCMeta):
    def __init__(self, result_field: str):
        super().__init__()
        self.result_field = result_field

    @abc.abstractmethod
    def _decode(self, value: JSONType) -> T:
        pass


class AbstractTasmotaRWConnector(AbstractTasmotaConnector[T], Writable[T], Generic[T], metaclass=abc.ABCMeta):
    def __init__(self, interface: TasmotaInterface, command: str, result_field: str):
        super().__init__(result_field)
        self.command = command
        self.interface = interface

    async def _write(self, value: T, origin: List[Any]) -> None:
        # TODO return early if device is disconnected
        encoded_value = self._encode(value)
        event = asyncio.Event()

        self.interface._pending_commands.append((self.result_field, origin, event))
        await self.interface._send_command(self.command, encoded_value)

        try:
            await asyncio.wait_for(event.wait(), 5)
        except asyncio.TimeoutError:
            logger.warning("No Result from Tasmota device %s to %s command within 5s.", self.interface.device_topic,
                           self.command)
        finally:
            # Remove queue entry
            index = -1
            for pos, t in enumerate(self.interface._pending_commands):
                if t[2] is event:
                    index = pos
                    break
            assert index != -1
            del self.interface._pending_commands[index]

    @abc.abstractmethod
    def _encode(self, value: T) -> str:
        pass


class TasmotaPowerConnector(AbstractTasmotaRWConnector[bool]):
    type = bool

    def __init__(self, interface: TasmotaInterface):
        super().__init__(interface, "Power", "POWER")

    def _encode(self, value: bool) -> str:
        return 'ON' if value else 'OFF'

    def _decode(self, value: JSONType) -> bool:
        assert isinstance(value, str)
        return value.lower() in ('on', '1', 'true')


class TasmotaDimmerConnector(AbstractTasmotaRWConnector[RangeInt0To100]):
    type = RangeInt0To100

    def __init__(self, interface: TasmotaInterface):
        super().__init__(interface, "Dimmer", "Dimmer")

    def _encode(self, value: RangeInt0To100) -> str:
        return str(value)

    def _decode(self, value: JSONType) -> RangeInt0To100:
        assert isinstance(value, int)
        return RangeInt0To100(value)


class TasmotaColorCCTConnector(AbstractTasmotaRWConnector[CCTUInt8]):
    type = CCTUInt8

    def __init__(self, interface: TasmotaInterface):
        super().__init__(interface, "color", "Color")

    def _encode(self, value: CCTUInt8) -> str:
        return '#{:0>2X}{:0>2X}'.format(value.cold, value.warm)

    def _decode(self, value: JSONType) -> CCTUInt8:
        assert isinstance(value, str)
        data = bytes.fromhex(value)
        data += bytes([0] * (2 - len(data)))
        return CCTUInt8(RangeUInt8(data[0]), RangeUInt8(data[1]))


class TasmotaColorRGBConnector(AbstractTasmotaRWConnector[RGBUInt8]):
    type = RGBUInt8

    def __init__(self, interface: TasmotaInterface):
        super().__init__(interface, "color", "Color")

    def _encode(self, value: RGBUInt8) -> str:
        return '#{:0>2X}{:0>2X}{:0>2X}'.format(value.red, value.green, value.blue)

    def _decode(self, value: JSONType) -> RGBUInt8:
        assert isinstance(value, str)
        data = bytes.fromhex(value)
        data += bytes([0] * (3 - len(data)))
        return RGBUInt8(*(RangeUInt8(v) for v in data))


class TasmotaColorRGBWConnector(AbstractTasmotaRWConnector[RGBWUInt8]):
    type = RGBWUInt8

    def __init__(self, interface: TasmotaInterface):
        super().__init__(interface, "color", "Color")

    def _encode(self, value: RGBWUInt8) -> str:
        return '#{:0>2X}{:0>2X}{:0>2X}{:0>2X}'.format(value.rgb.red, value.rgb.green, value.rgb.blue, value.white)

    def _decode(self, value: JSONType) -> RGBWUInt8:
        assert isinstance(value, str)
        data = bytes.fromhex(value)
        data += bytes([0] * (4 - len(data)))
        return RGBWUInt8(RGBUInt8(*(RangeUInt8(v) for v in data[0:3])), RangeUInt8(data[3]))


class TasmotaColorRGBCCTConnector(AbstractTasmotaRWConnector[RGBCCTUInt8]):
    type = RGBCCTUInt8

    def __init__(self, interface: TasmotaInterface):
        super().__init__(interface, "color", "Color")

    def _encode(self, value: RGBCCTUInt8) -> str:
        return '#{:0>2X}{:0>2X}{:0>2X}{:0>2X}{:0>2X}'.format(value.rgb.red, value.rgb.green, value.rgb.blue,
                                                             value.white.cold, value.white.warm)

    def _decode(self, value: JSONType) -> RGBCCTUInt8:
        assert isinstance(value, str)
        data = bytes.fromhex(value)
        data += bytes([0] * (5 - len(data)))
        return RGBCCTUInt8(RGBUInt8(*(RangeUInt8(v) for v in data[0:3])),
                           CCTUInt8(RangeUInt8(data[3]), RangeUInt8(data[4])))


class TasmotaIRReceiverConnector(AbstractTasmotaConnector[bytes]):
    type = bytes

    def __init__(self, _interface: TasmotaInterface):
        super().__init__("IrReceived")

    def _decode(self, value: JSONType) -> bytes:
        assert isinstance(value, dict)
        data = value['Data'] if 'Data' in value else value['Hash']  # TODO this is hacky. We should probably add the detected protocol
        return bytes.fromhex(data[2:])


class TasmotaOnlineConnector(Readable[bool], Subscribable[bool]):
    type = bool

    def __init__(self):
        super().__init__()
        self.value = None

    async def _update_from_mqtt(self, msg: MQTTMessage) -> None:
        self.value = msg.payload == b'Online'
        await self._publish(self.value, [])

    async def read(self) -> bool:
        return self.value
