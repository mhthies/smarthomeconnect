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
import json
import logging
from typing import List, Any, Generic, Type, Callable, Awaitable, Optional, Tuple

from paho.mqtt.client import MQTTMessage, MQTTv311  # type: ignore
from asyncio_mqtt import Client, MqttError  # type: ignore
from paho.mqtt.matcher import MQTTMatcher  # type: ignore

from ..base import Writable, Subscribable, T
from ..conversion import SHCJsonEncoder, from_json
from ..supervisor import register_interface

logger = logging.getLogger(__name__)


class MQTTClientInterface:
    """
    TODO
    """
    def __init__(self, hostname: str = 'localhost', port: int = 1883, username: Optional[str] = None,
                 password: Optional[str] = None, client_id: Optional[str] = None, protocol: int = MQTTv311) -> None:
        register_interface(self)
        self.client = Client(hostname, port, username=username, password=password, client_id=client_id,
                             protocol=protocol)
        self.matcher = MQTTMatcher()
        self.subscribe_topics: List[Tuple[str, int]] = []  #: List of (topic, qos) tuples for subscribing
        self.run_task: Optional[asyncio.Task] = None

    async def start(self) -> None:
        logger.info("Connecting MQTT client interface ...")
        await self.client.connect()
        self.run_task = asyncio.create_task(self.run())
        logger.info("Subscribing to MQTT topics ...")
        logger.debug("Topics: %s", self.subscribe_topics)
        await self.client.subscribe(self.subscribe_topics)
        # TODO error handling: MqttError on connection error or subscription failure

    async def stop(self) -> None:
        logger.info("Stopping MQTT client interface ...")
        await self.client.disconnect()
        if self.run_task:
            self.run_task.cancel()
            try:
                await self.run_task
            except asyncio.CancelledError:
                pass
        logger.info("MQTT client interface stopped")

    def topic_raw(self, topic: str, subscribe_topics: Optional[str] = None, qos: int = 0, retain: bool = False) \
            -> "RawMQTTTopicVariable":
        var = RawMQTTTopicVariable(self, topic, qos, retain)
        if subscribe_topics is None:
            subscribe_topics = topic
        self.subscribe_topics.append((subscribe_topics, qos))
        self.register_filtered_receiver(subscribe_topics, var._new_value_from_mqtt)
        return var

    def topic_string(self, topic: str, subscribe_topics: Optional[str] = None, qos: int = 0, retain: bool = False) \
            -> "StringMQTTTopicVariable":
        var = StringMQTTTopicVariable(self, topic, qos, retain)
        if subscribe_topics is None:
            subscribe_topics = topic
        self.subscribe_topics.append((subscribe_topics, qos))
        self.register_filtered_receiver(subscribe_topics, var._new_value_from_mqtt)
        return var

    def topic_json(self, type_: Type[T], topic: str, subscribe_topics: Optional[str] = None, qos: int = 0,
                   retain: bool = False) -> "JSONMQTTTopicVariable[T]":
        var = JSONMQTTTopicVariable(type_, self, topic, qos, retain)
        if subscribe_topics is None:
            subscribe_topics = topic
        self.subscribe_topics.append((subscribe_topics, qos))
        self.register_filtered_receiver(subscribe_topics, var._new_value_from_mqtt)
        return var

    async def publish_message(self, topic: str, payload: bytes, qos: int = 0, retain: bool = False) -> None:
        logger.debug("Sending MQTT message t: %s p: %s q: %s r: %s", topic, payload, qos, retain)
        await self.client.publish(topic, payload, qos, retain)

    def register_filtered_receiver(self, topic_filter: str, receiver: Callable[[MQTTMessage], Awaitable[None]],
                                   subscription_qos: int = 0) -> None:
        self.subscribe_topics.append((topic_filter, subscription_qos))
        self.matcher[topic_filter] = receiver

    async def run(self) -> None:
        async with self.client.unfiltered_messages() as messages:
            async for message in messages:
                logger.debug("Incoming MQTT message: %s", message)
                try:
                    receiver: Callable[[MQTTMessage], Awaitable[None]] = self.matcher[message.topic]
                except KeyError:
                    logger.info("Topic %s of incoming message does not match any receiver filter")
                    continue
                asyncio.create_task(receiver(message))

        # TODO error handling: MqttError when disconnected


class RawMQTTTopicVariable(Writable[bytes], Subscribable[bytes]):
    type = bytes

    def __init__(self, interface: MQTTClientInterface, topic: str, qos: int, retain: bool) -> None:
        super().__init__()
        self.interface = interface
        self.topic = topic
        self.qos = qos
        self.retain = retain

    async def _write(self, value: bytes, origin: List[Any]) -> None:
        await self.interface.publish_message(self.topic, value, self.qos, self.retain)

    async def _new_value_from_mqtt(self, message: MQTTMessage) -> None:
        await self._publish(message.payload, [])


class StringMQTTTopicVariable(Writable[str], Subscribable[str]):
    type = str

    def __init__(self, interface: MQTTClientInterface, topic: str, qos: int, retain: bool) -> None:
        super().__init__()
        self.interface = interface
        self.topic = topic
        self.qos = qos
        self.retain = retain

    async def _write(self, value: str, origin: List[Any]) -> None:
        await self.interface.publish_message(self.topic, value.encode('utf-8'), self.qos, self.retain)

    async def _new_value_from_mqtt(self, message: MQTTMessage) -> None:
        await self._publish(message.payload.decode('utf-8-sig'), [])


class JSONMQTTTopicVariable(Writable[T], Subscribable[T], Generic[T]):
    def __init__(self, type_: Type[T], interface: MQTTClientInterface, topic: str, qos: int, retain: bool) -> None:
        self.type = type_
        super().__init__()
        self.interface = interface
        self.topic = topic
        self.qos = qos
        self.retain = retain

    async def _write(self, value: T, origin: List[Any]) -> None:
        await self.interface.publish_message(self.topic, json.dumps(value, cls=SHCJsonEncoder).encode('utf-8'),
                                             self.qos, self.retain)

    async def _new_value_from_mqtt(self, message: MQTTMessage) -> None:
        await self._publish(from_json(self.type, message.payload.decode('utf-8-sig')), [])
