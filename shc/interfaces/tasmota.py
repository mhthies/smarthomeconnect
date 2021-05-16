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
import json
import logging
from typing import List, Any, Dict, Deque, Generic, Union

from paho.mqtt.client import MQTTMessage  # type: ignore

from ..base import Writable, Subscribable, T
from .mqtt import MQTTClientInterface
from ..datatypes import RangeInt0To100

logger = logging.getLogger(__name__)


class TasmotaInterface:
    def __init__(self, mqtt_interface: MQTTClientInterface, device_topic: str,
                 topic_template: str = "{prefix}/{topic}/"):
        self.mqtt_interface = mqtt_interface
        self.device_topic = device_topic
        self.topic_template = topic_template
        self.connectors: Dict[str, AbstractTasmotaConnector] = {}
        mqtt_interface.register_filtered_receiver(topic_template.format(prefix='stat', topic=device_topic) + 'RESULT',
                                                  self._dispatch_result, 1)
        mqtt_interface.register_filtered_receiver(topic_template.format(prefix='tele', topic=device_topic) + 'STATE',
                                                  self._dispatch_telemetry, 1)

    async def _dispatch_result(self, msg: MQTTMessage) -> None:
        try:
            data = json.loads(msg.payload.decode('utf-8'))
            assert isinstance(data, dict)
        except (json.JSONDecodeError, UnicodeDecodeError, AssertionError) as e:
            logger.error("Could not decode Tasmota result as JSON object: %s")
            return
        for key, value in data.items():
            if key in self.connectors:
                await self.connectors[key]._new_value_from_device(value)

    async def _dispatch_telemetry(self, msg: MQTTMessage) -> None:
        # TODO
        pass

    def power(self) -> "TasmotaPowerConnector":
        if 'Power' not in self.connectors:
            self.connectors["Power"] = TasmotaPowerConnector(self)
        return self.connectors["Power"]  # type: ignore

    def dimmer(self) -> "TasmotaDimmerConnector":
        if 'Dimmer' not in self.connectors:
            self.connectors["Dimmer"] = TasmotaDimmerConnector(self)
        return self.connectors["Power"]  # type: ignore

    async def _send_command(self, command: str, value: str):
        await self.mqtt_interface.publish_message(
            self.topic_template.format(prefix='cmnd', topic=self.device_topic) + 'command',
            value.encode())


class AbstractTasmotaConnector(Writable[T], Subscribable[T], Generic[T], metaclass=abc.ABCMeta):
    def __init__(self, interface: TasmotaInterface, command: str):
        super().__init__()
        self.command = command
        self.interface = interface
        self._pending_commands: Dict[str, Deque[asyncio.Event]] = {}

    async def _write(self, value: T, origin: List[Any]) -> None:
        # TODO return early if device is disconnected
        encoded_value = self._encode(value)
        queue = self._pending_commands.get(encoded_value)
        if queue is None:
            queue = collections.deque()
            self._pending_commands[encoded_value] = queue
        event = asyncio.Event()
        queue.append(event)

        await self.interface._send_command(self.command, encoded_value)

        try:
            await asyncio.wait_for(event.wait(), 5)
        except asyncio.TimeoutError:
            logger.warning("No Result from Tasmota device %s to %s command within 5s.", self.interface.device_topic,
                           self.command)
        finally:
            await self._publish(value, origin)
            assert queue is not None
            queue.remove(event)
            if not queue:
                del self._pending_commands[encoded_value]

    @abc.abstractmethod
    def _encode(self, value: T) -> str:
        pass

    @abc.abstractmethod
    def _decode(self, value: Union[str, float]) -> T:
        pass

    async def _new_value_from_device(self, value: str) -> None:
        queue = self._pending_commands.get(value)
        if queue is not None:
            queue[0].set()
        else:
            await self._publish(self._decode(value), [])


class TasmotaPowerConnector(AbstractTasmotaConnector[bool]):
    type = bool

    def __init__(self, interface: TasmotaInterface):
        super().__init__(interface, "Power")

    def _encode(self, value: bool) -> str:
        return 'ON' if value else 'OFF'

    def _decode(self, value: str) -> bool:
        return value.lower() in ('on', '1', 'true')


class TasmotaDimmerConnector(AbstractTasmotaConnector[RangeInt0To100]):
    type = RangeInt0To100

    def __init__(self, interface: TasmotaInterface):
        super().__init__(interface, "Dimmer")

    def _encode(self, value: RangeInt0To100) -> str:
        return str(value)

    def _decode(self, value: int) -> RangeInt0To100:
        return RangeInt0To100(value)
