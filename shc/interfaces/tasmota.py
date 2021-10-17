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
from typing import List, Any, Dict, Deque, Generic, Union, Type, TypeVar, Tuple, cast, Optional

from paho.mqtt.client import MQTTMessage

from ..base import Writable, Subscribable, T, Readable
from .mqtt import MQTTClientInterface
from ..datatypes import RangeInt0To100, RGBUInt8, RangeUInt8, RGBWUInt8, RGBCCTUInt8, CCTUInt8
from ..supervisor import AbstractInterface, InterfaceStatus, ServiceStatus

logger = logging.getLogger(__name__)

ConnType = TypeVar("ConnType", bound="AbstractTasmotaConnector")
JSONType = Union[str, float, int, None, Dict[str, Any], List[Any]]


class TasmotaInterface(AbstractInterface):
    """
    SHC interface to connect with ESP8266-based IoT devices, running the
    `Tasmota firmware <https://tasmota.github.io/>`_, via MQTT.

    Requires a :class:`MQTTClientInterface` which is connected to the MQTT broker to which your Tasmota device(s)
    connect. Each instance of `TasmotaInterface` connects with a single Tasmota device. It identifies the individual
    Tasmota device via its MQTT "Topic" (by default something like "tasmota_A0B1C2").

    The `TasmotaInterface` provides *subscribable* and (mostly) *writable* connector objects to receive state updates
    from the Tasmota device and send commands. Currently, only PWM-dimmed lights and IR receivers are fully supported.
    Please file a GitHub issue if you are interested in other Tasmota functionality.

    :param mqtt_interface: The `MQTTClientInterface` to use for MQTT communication
    :param device_topic: The Tasmota devices individual "Topic", used to address the device, as it is configured on the
        Tasmota web UI at Configuration → MQTT or using Tasmota's `Topic` command. By default it should look like
        "tasmota_A0B1C2".
    :param topic_template: The Tasmota "Full Topic", used build MQTT topics from the individual device's topic.
        Only required if you don't use the default Full Topic "%prefix%/%topic%/". In contrast to the Tasmota web UI
        or "FullTopic" command, the parameter uses Python's modern formatting syntax: If your Tasmota "Full Topic" is
        "devices/%topic%/%prefix%/", you must specify "devices/{topic}/{prefix}/" as `topic_tempalate`.
    :param telemetry_interval: The expected interval of periodic telemetry messages from the Tasmota device in seconds.
        This is used by the status monitoring to detect device failures. Use `0` to disable telemetry monitoring.
    """
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

        self._latest_telemetry_time: Optional[float] = None
        self._latest_telemetry: Optional[Dict[str, JSONType]] = None

        # Subscribe relevant MQTT topics and register message handlers
        mqtt_interface.register_filtered_receiver(topic_template.format(prefix='tele', topic=device_topic) + 'RESULT',
                                                  self._handle_result_or_status, 1)
        mqtt_interface.register_filtered_receiver(topic_template.format(prefix='stat', topic=device_topic) + 'RESULT',
                                                  functools.partial(self._handle_result_or_status, result=True), 1)
        mqtt_interface.register_filtered_receiver(topic_template.format(prefix='tele', topic=device_topic) + 'STATE',
                                                  self._handle_result_or_status, 1)
        mqtt_interface.register_filtered_receiver(topic_template.format(prefix='tele', topic=device_topic) + 'SENSOR',
                                                  self._handle_result_or_status, 1)
        # TODO allow listening to STATUS8 responses for sensors
        mqtt_interface.register_filtered_receiver(topic_template.format(prefix='stat', topic=device_topic) + 'STATUS11',
                                                  self._handle_status11, 1)
        mqtt_interface.register_filtered_receiver(topic_template.format(prefix='tele', topic=device_topic) + 'LWT',
                                                  self._online_connector._update_from_mqtt, 1)

    async def start(self) -> None:
        # Send status request (for telemetry data and state) as soon as the MQTT interface is up
        await self.mqtt_interface.wait_running(5)
        await self._send_command("status", "11")
        # TODO send STATUS8 cmnd?

    async def stop(self) -> None:
        pass

    async def get_status(self) -> InterfaceStatus:
        # Check Tasmota online state (via Last Will message)
        if not self._online_connector.value:
            return InterfaceStatus(ServiceStatus.CRITICAL, "Tasmota device is not online")

        # Check telemetry data
        if not self._latest_telemetry:
            if not self.telemetry_interval:
                return InterfaceStatus()
            return InterfaceStatus(ServiceStatus.CRITICAL, "No telemetry data received from Tasmota device by now")
        assert self._latest_telemetry_time
        last_telemetry_age = time.monotonic() - self._latest_telemetry_time
        if last_telemetry_age > 10 * self.telemetry_interval:
            return InterfaceStatus(ServiceStatus.CRITICAL, "No telemetry data received from Tasmota device by now")
        indicators = {
            'telemetry_age': last_telemetry_age,
            'tasmota.UptimeSec': self._latest_telemetry.get('UptimeSec'),
            'tasmota.Heap': self._latest_telemetry.get('Heap'),
            'tasmota.LoadAvg': self._latest_telemetry.get('LoadAvg'),
            'tasmota.Wifi.RSSI': self._latest_telemetry.get('Wifi', {}).get('RSSI'),  # type: ignore
            'tasmota.Wifi.Signal': self._latest_telemetry.get('Wifi', {}).get('Signal'),   # type: ignore
            'tasmota.Wifi.Downtime': self._latest_telemetry.get('Wifi', {}).get('Downtime'),  # type: ignore
        }
        if last_telemetry_age > 10 * self.telemetry_interval:
            return InterfaceStatus(status=ServiceStatus.CRITICAL,
                                   message="Latest telemetry data from Tasmota device is {:.2f}s old (more than 10x the"
                                           " expected telemetry interval)".format(last_telemetry_age),
                                   indicators=indicators)  # type: ignore
        if last_telemetry_age > 1.5 * self.telemetry_interval:
            return InterfaceStatus(status=ServiceStatus.WARNING,
                                   message="Latest telemetry data from Tasmota device is {:.2f}s old (more than 1.5x "
                                           "the expected telemetry interval)".format(last_telemetry_age),
                                   indicators=indicators)  # type: ignore
        return InterfaceStatus(indicators=indicators)  # type: ignore

    def _handle_result_or_status(self, msg: MQTTMessage, result: bool = False) -> None:
        """
        Callback function to handle incoming MQTTMessages on the Tasmota device's RESULT, STATUS and STATE topics

        :param msg: The MQTTMessage to be parsed and handled.
        :param result: Shall be True if the handled message has been published on the Tasmota RESULT topic (i.e. it is
            probably a result to a Tasmota command we issued recently)
        """
        try:
            data = json.loads(msg.payload.decode('utf-8'))
            assert isinstance(data, dict)
        except (json.JSONDecodeError, UnicodeDecodeError, AssertionError) as e:
            logger.error("Could not decode Tasmota result as JSON object: %s", msg.payload, exc_info=e)
            return
        self._dispatch_status(data, result)

    def _handle_status11(self, msg: MQTTMessage) -> None:
        """
        Callback function to handle incoming MQTTMessages on the STATUS11 topic (as a result to of the 'status 11')
        command.
        """
        try:
            data = json.loads(msg.payload.decode('utf-8'))
            assert isinstance(data, dict)
            assert 'StatusSTS' in data
            assert isinstance(data['StatusSTS'], dict)
        except (json.JSONDecodeError, UnicodeDecodeError, AssertionError) as e:
            logger.error("Could not decode Tasmota telemetry status as JSON object: %s", msg.payload, exc_info=e)
            return
        self._dispatch_status(data['StatusSTS'], False)

    def _dispatch_status(self, data: Dict[str, JSONType], result: bool) -> None:
        """
        Internal helper method to dispatch results/telemetry updates and sensor readings from Tasmota device, received
        via :meth:`_handle_result_or_status` or :meth:`_handle_status11` for publishing by all affected connectors.

        :param data: The parsed JSON payload of the tasmota result/telemetry message
        :param result: Shall be True if the handled message has been published on the Tasmota RESULT topic (i.e. it is
            probably a result to a Tasmota command we issued recently)
        """
        logger.debug("Dispatching Tasmota result/status from %s: %s", self.device_topic, data)

        origin = []
        event = None

        # If the message has been received as a Tasmota "result", check if is the response to a recent command, in order
        # to publish the value updates with the correct 'origin' and let the sending Connector's `write()` method return
        # (by set()ing the associated Event).
        #
        # Notice, that we only check the field names to match received results with pending commands. I.e., we assume
        # that the first received result which contains the Tasmota field affected by an given command (and not matching
        # a previous command) belongs to that command. This may be wrong when a concurrent update of the same field (or
        # an internally linked field in Tasmota) from somewhere else happens. However, the worst outcome in that case
        # should be the unintended re-publishing of the result to our command to its origin within SHC. This should not
        # be an issue, since it will correctly represent the latest state of the Tasmota device and only happen once
        # (and thus not result in a feedback loop).
        if result:
            for field, origin_, event_ in self._pending_commands:
                if field in data:
                    origin = origin_
                    event = event_
                    logger.debug("The result/status is considered a result to our recent command for '%s' field, "
                                 "originating from %s", field, origin_)
                    break

        for key, value in data.items():
            for connector in self._connectors_by_result_field.get(key, []):
                try:
                    connector._publish(connector._decode(value), origin)
                except Exception as e:
                    logger.error("Error while processing Tasmota result/status field %s=%s from %s in Tasmota "
                                 "connector %s", key, value, self.device_topic, connector, exc_info=e)
        if event:
            event.set()

        # If it seems to be (periodic) telemetry update, store it for usage by our `get_status()` method
        if not result and "Uptime" in data:
            self._latest_telemetry = data
            self._latest_telemetry_time = time.monotonic()

    def online(self) -> "TasmotaOnlineConnector":
        """
        Returns a *readable* and *subscribable* :class:`bool`-typed Connector that will indicate the online-state of the
        Tasmota device, using its MQTT "Last Will Topic".
        """
        return self._online_connector

    def power(self) -> "TasmotaPowerConnector":
        """
        Returns a *subscribable* and *writable* :class:`bool`-typed Connector to monitor and control the POWER state of
        the Tasmota device.
        """
        return self._get_or_create_connector(TasmotaPowerConnector)

    def dimmer(self) -> "TasmotaDimmerConnector":
        """
        Returns a *subscribable* and *writable* Connector to monitor and control the Dimmer state of the Tasmota device.

        The dimmer value is an integer between 0 and 100, represented as :class:`shc.datatypes.RangeInt0To100` in SHC.
        """
        return self._get_or_create_connector(TasmotaDimmerConnector)

    def color_cct(self) -> "TasmotaColorCCTConnector":
        """
        Returns a *subscribable* and *writable* Connector to monitor and control two channel (cold-white, white-white)
        dimmable lamps attached to the Tasmota device. The value is represented as :class:`shc.datatypes.CCTUInt8`
        (composed of two 8-bit :class:`shc.datatypes.RangeUInt8` integer values).

        Note, that this connector is only sensible if the Tasmota device has two PWM pins for cold white and warm white
        configured. It will also work with different numbers of PWM channels configured, but the channel mapping will
        not be sensible.

        See https://tasmota.github.io/docs/Lights/ for more information on Tasmota light controls.
        """
        return self._get_or_create_connector(TasmotaColorCCTConnector)

    def color_rgb(self) -> "TasmotaColorRGBConnector":
        """
        Returns a *subscribable* and *writable* Connector to monitor and control three channel (red, green, blue)
        dimmable lamps attached to the Tasmota device. The value is represented as :class:`shc.datatypes.RGBUInt8`
        (composed of three 8-bit :class:`shc.datatypes.RangeUInt8` integer values).

        Note, that this connector is only sensible if the Tasmota device has at least three PWM pins for red, green and
        blue configured. It will also work with less PWM channels configured, but the channel mapping will not be
        sensible.

        See https://tasmota.github.io/docs/Lights/ for more information on Tasmota light controls.
        """
        return self._get_or_create_connector(TasmotaColorRGBConnector)

    def color_rgbw(self) -> "TasmotaColorRGBWConnector":
        """
        Returns a *subscribable* and *writable* Connector to monitor and control four channel (red, green, blue, white)
        dimmable lamps attached to the Tasmota device. The value is represented as :class:`shc.datatypes.RGBWUInt8`
        (composed of three 8-bit :class:`shc.datatypes.RangeUInt8` integer values for RGB in an
        `shc.datatypes.RGBUInt8` and an additional :class:`shc.datatypes.RangeUInt8` value for the white channel).

        Note, that this connector is only sensible if the Tasmota device has four PWM pins for red, green, blue and
        white configured. It will also work with a different number PWM channels configured, but the channel mapping
        will not always be sensible.

        See https://tasmota.github.io/docs/Lights/ for more information on Tasmota light controls.
        """
        return self._get_or_create_connector(TasmotaColorRGBWConnector)

    def color_rgbcct(self) -> "TasmotaColorRGBCCTConnector":
        """
        Returns a *subscribable* and *writable* Connector to monitor and control five channel (red, green, blue, cold
        white, warm white) dimmable lamps attached to the Tasmota device. The value is represented as
        :class:`shc.datatypes.RGBCCTUInt8`
        (composed of three 8-bit :class:`shc.datatypes.RangeUInt8` integer values for RGB in an
        `shc.datatypes.RGBUInt8` and two additional :class:`shc.datatypes.RangeUInt8` values in an
        class:`shc.datatypes.CCTUInt8`).

        Note, that this connector is only sensible if the Tasmota device has five PWM pins configured. It will also work
        less PWM channels configured, but the channel mapping will not always be sensible.

        See https://tasmota.github.io/docs/Lights/ for more information on Tasmota light controls.
        """
        return self._get_or_create_connector(TasmotaColorRGBCCTConnector)

    def ir_receiver(self) -> "TasmotaIRReceiverConnector":
        """
        Returns a *subscribable* :class:`bytes`-typed Connector that publishes the data/hash of each IR command received
        by the Tasmota device (via an IR receiver, attatched to a pin configured as `IRrecv`).

        See https://tasmota.github.io/docs/Tasmota-IR/#receiving-ir-commands for more information about receiving IR
        commands.
        """
        return self._get_or_create_connector(TasmotaIRReceiverConnector)

    def energy_power(self) -> "TasmotaEnergyPowerConnector":
        """
        Returns a *subscribable* :class:`float`-typed Connector, publishing the currently measured power consumption in
        watts from the Tasmota device, if available.
        """
        return self._get_or_create_connector(TasmotaEnergyPowerConnector)

    def energy_voltage(self) -> "TasmotaEnergyVoltageConnector":
        """
        Returns a *subscribable* :class:`float`-typed Connector, publishing the currently measured mains voltage in
        volts from the Tasmota device, if available.
        """
        return self._get_or_create_connector(TasmotaEnergyVoltageConnector)

    def energy_current(self) -> "TasmotaEnergyCurrentConnector":
        """
        Returns a *subscribable* :class:`float`-typed Connector, publishing the currently measured current flow in
        amperes from the Tasmota device, if available.
        """
        return self._get_or_create_connector(TasmotaEnergyCurrentConnector)

    def energy_total(self) -> "TasmotaEnergyTotalConnector":
        """
        Returns a *subscribable* :class:`float`-typed Connector, publishing the total energy consumption measured by the
        Tasmota device since its last reboot in kWh.
        """
        return self._get_or_create_connector(TasmotaEnergyTotalConnector)

    def energy_power_factor(self) -> "TasmotaEnergyFactorConnector":
        """
        Returns a *subscribable* :class:`float`-typed Connector, publishing the currently measured power factor from the
        Tasmota device.
        """
        return self._get_or_create_connector(TasmotaEnergyFactorConnector)

    def energy_apparent_power(self) -> "TasmotaEnergyApparentPowerConnector":
        """
        Returns a *subscribable* :class:`float`-typed Connector, publishing the currently measured apparent power in VA
        from the Tasmota device.
        """
        return self._get_or_create_connector(TasmotaEnergyApparentPowerConnector)

    def energy_reactive_power(self) -> "TasmotaEnergyReactivePowerConnector":
        """
        Returns a *subscribable* :class:`float`-typed Connector, publishing the currently measured reactive power in VAr
        from the Tasmota device.
        """
        return self._get_or_create_connector(TasmotaEnergyReactivePowerConnector)

    def _get_or_create_connector(self, type_: Type[ConnType]) -> ConnType:
        """
        Helper method to create or get the connector object of a given type, while making sure that there is only one
        of each type in each TasmotaInterface.

        :param type_: The connector type (class) to be created
        :return: The existing (or newly created) connector of the specified type
        """
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
        """
        Internal helper method to send a Tasmota command to the device via MQTT.

        See https://tasmota.github.io/docs/Commands/ for a reference of available commands.

        :param command: The Tasmota command (used as part of the MQTT topic)
        :param value: The parameters of the Tasmota command (used as MQTT payload)
        """
        # TODO raise exception if device is disconnected
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
        encoded_value = self._encode(value)
        event = asyncio.Event()

        self.interface._pending_commands.append((self.result_field, origin, event))

        try:
            await self.interface._send_command(self.command, encoded_value)
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
        # TODO this is hacky. We should probably add the detected protocol
        data = value['Data'] if 'Data' in value else value['Hash']
        return bytes.fromhex(data[2:])


class TasmotaEnergyPowerConnector(AbstractTasmotaConnector[float]):
    type = float

    def __init__(self, _interface: TasmotaInterface):
        super().__init__("ENERGY")

    def _decode(self, value: JSONType) -> float:
        assert isinstance(value, dict)
        return float(value['Power'])


class TasmotaEnergyVoltageConnector(AbstractTasmotaConnector[float]):
    type = float

    def __init__(self, _interface: TasmotaInterface):
        super().__init__("ENERGY")

    def _decode(self, value: JSONType) -> float:
        assert isinstance(value, dict)
        return float(value['Voltage'])


class TasmotaEnergyCurrentConnector(AbstractTasmotaConnector[float]):
    type = float

    def __init__(self, _interface: TasmotaInterface):
        super().__init__("ENERGY")

    def _decode(self, value: JSONType) -> float:
        assert isinstance(value, dict)
        return float(value['Current'])


class TasmotaEnergyTotalConnector(AbstractTasmotaConnector[float]):
    type = float

    def __init__(self, _interface: TasmotaInterface):
        super().__init__("ENERGY")

    def _decode(self, value: JSONType) -> float:
        assert isinstance(value, dict)
        return float(value['Total'])


class TasmotaEnergyApparentPowerConnector(AbstractTasmotaConnector[float]):
    type = float

    def __init__(self, _interface: TasmotaInterface):
        super().__init__("ENERGY")

    def _decode(self, value: JSONType) -> float:
        assert isinstance(value, dict)
        return float(value['ApparentPower'])


class TasmotaEnergyReactivePowerConnector(AbstractTasmotaConnector[float]):
    type = float

    def __init__(self, _interface: TasmotaInterface):
        super().__init__("ENERGY")

    def _decode(self, value: JSONType) -> float:
        assert isinstance(value, dict)
        return float(value['ReactivePower'])


class TasmotaEnergyFactorConnector(AbstractTasmotaConnector[float]):
    type = float

    def __init__(self, _interface: TasmotaInterface):
        super().__init__("ENERGY")

    def _decode(self, value: JSONType) -> float:
        assert isinstance(value, dict)
        return float(value['Factor'])


class TasmotaOnlineConnector(Readable[bool], Subscribable[bool]):
    type = bool

    def __init__(self):
        super().__init__()
        self.value = False

    def _update_from_mqtt(self, msg: MQTTMessage) -> None:
        self.value = msg.payload == b'Online'
        self._publish(self.value, [])

    async def read(self) -> bool:
        return self.value
