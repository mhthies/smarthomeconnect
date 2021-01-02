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
from typing import List, Any, Generic, Type, Callable, Awaitable, Optional, Tuple, Union

from paho.mqtt.client import MQTTMessage, MQTTv311  # type: ignore
from asyncio_mqtt import Client, MqttError  # type: ignore
from paho.mqtt.matcher import MQTTMatcher  # type: ignore

from ._helper import SupervisedClientInterface
from ..base import Writable, Subscribable, T, S
from ..conversion import SHCJsonEncoder, from_json

logger = logging.getLogger(__name__)


class MQTTClientInterface(SupervisedClientInterface):
    """
    TODO
    """
    def __init__(self, hostname: str = 'localhost', port: int = 1883, username: Optional[str] = None,
                 password: Optional[str] = None, client_id: Optional[str] = None, protocol: int = MQTTv311,
                 auto_reconnect: bool = True, failsafe_start: bool = False) -> None:
        super().__init__(auto_reconnect, failsafe_start)
        self.client = Client(hostname, port, username=username, password=password, client_id=client_id,
                             protocol=protocol)
        self.matcher = MQTTMatcher()
        self.subscribe_topics: List[Tuple[str, int]] = []  #: List of (topic, qos) tuples for subscribing
        self.run_task: Optional[asyncio.Task] = None

    async def _connect(self) -> None:
        logger.info("Connecting MQTT client interface ...")
        await self.client.connect()

    async def _subscribe(self) -> None:
        if self.subscribe_topics:
            logger.info("Subscribing to MQTT topics ...")
            logger.debug("Topics: %s", self.subscribe_topics)
            await self.client.subscribe(self.subscribe_topics)
        else:
            logger.info("No MQTT topics need to be subscribed")

    async def _disconnect(self) -> None:
        logger.info("Disconnecting MQTT client interface ...")
        await self.client.disconnect()

    def topic_raw(self, topic: str, subscribe_topics: Optional[str] = None, qos: int = 0, retain: bool = False) \
            -> "RawMQTTTopicVariable":
        if subscribe_topics is None:
            subscribe_topics = topic
        return RawMQTTTopicVariable(self, topic, subscribe_topics, qos, retain)

    def topic_string(self, topic: str, subscribe_topics: Optional[str] = None, qos: int = 0, retain: bool = False) \
            -> "StringMQTTTopicVariable":
        if subscribe_topics is None:
            subscribe_topics = topic
        return StringMQTTTopicVariable(self, topic, subscribe_topics, qos, retain)

    def topic_json(self, type_: Type[T], topic: str, subscribe_topics: Optional[str] = None, qos: int = 0,
                   retain: bool = False) -> "JSONMQTTTopicVariable[T]":
        if subscribe_topics is None:
            subscribe_topics = topic
        return JSONMQTTTopicVariable(type_, self, topic, subscribe_topics, qos, retain)

    async def publish_message(self, topic: str, payload: bytes, qos: int = 0, retain: bool = False) -> None:
        logger.debug("Sending MQTT message t: %s p: %s q: %s r: %s", topic, payload, qos, retain)
        await self.client.publish(topic, payload, qos, retain)

    def register_filtered_receiver(self, topic_filter: str, receiver: Callable[[MQTTMessage], Awaitable[None]],
                                   subscription_qos: int = 0) -> None:
        self.subscribe_topics.append((topic_filter, subscription_qos))
        self.matcher[topic_filter] = receiver

    async def _run(self) -> None:
        async with self.client.unfiltered_messages() as messages:
            self._running.set()
            async for message in messages:
                logger.debug("Incoming MQTT message: %s", message)
                try:
                    receiver: Callable[[MQTTMessage], Awaitable[None]] = self.matcher[message.topic]
                except KeyError:
                    logger.info("Topic %s of incoming message does not match any receiver filter")
                    continue
                asyncio.create_task(receiver(message))


class RawMQTTTopicVariable(Writable[bytes], Subscribable[bytes]):
    type = bytes

    def __init__(self, interface: MQTTClientInterface, publish_topic: str, subscribe_topics: str, qos: int,
                 retain: bool) -> None:
        super().__init__()
        self.interface = interface
        self.publish_topic = publish_topic
        self.subscribe_topics = subscribe_topics
        self.qos = qos
        self.retain = retain
        self._receiver_registered = False

    def subscribe(self, subscriber: Writable[S], convert: Union[Callable[[bytes], S], bool] = False) -> None:
        super().subscribe(subscriber, convert)
        if not self._receiver_registered:
            self.interface.register_filtered_receiver(self.subscribe_topics, self._new_value_from_mqtt)
            self._receiver_registered = True

    async def _write(self, value: bytes, origin: List[Any]) -> None:
        await self.interface.publish_message(self.publish_topic, value, self.qos, self.retain)

    async def _new_value_from_mqtt(self, message: MQTTMessage) -> None:
        await self._publish(message.payload, [])


class StringMQTTTopicVariable(Writable[str], Subscribable[str]):
    type = str

    def __init__(self, interface: MQTTClientInterface, publish_topic: str, subscribe_topics: str, qos: int,
                 retain: bool) -> None:
        super().__init__()
        self.interface = interface
        self.publish_topic = publish_topic
        self.subscribe_topics = subscribe_topics
        self.qos = qos
        self.retain = retain
        self._receiver_registered = False

    def subscribe(self, subscriber: Writable[S], convert: Union[Callable[[str], S], bool] = False) -> None:
        super().subscribe(subscriber, convert)
        if not self._receiver_registered:
            self.interface.register_filtered_receiver(self.subscribe_topics, self._new_value_from_mqtt)
            self._receiver_registered = True

    async def _write(self, value: str, origin: List[Any]) -> None:
        await self.interface.publish_message(self.publish_topic, value.encode('utf-8'), self.qos, self.retain)

    async def _new_value_from_mqtt(self, message: MQTTMessage) -> None:
        await self._publish(message.payload.decode('utf-8-sig'), [])


class JSONMQTTTopicVariable(Writable[T], Subscribable[T], Generic[T]):
    def __init__(self, type_: Type[T], interface: MQTTClientInterface, publish_topic: str, subscribe_topics: str,
                 qos: int, retain: bool) -> None:
        self.type = type_
        super().__init__()
        self.interface = interface
        self.publish_topic = publish_topic
        self.subscribe_topics = subscribe_topics
        self.qos = qos
        self.retain = retain
        self._receiver_registered = False

    def subscribe(self, subscriber: Writable[S], convert: Union[Callable[[str], S], bool] = False) -> None:
        super().subscribe(subscriber, convert)
        if not self._receiver_registered:
            self.interface.register_filtered_receiver(self.subscribe_topics, self._new_value_from_mqtt)
            self._receiver_registered = True

    async def _write(self, value: T, origin: List[Any]) -> None:
        await self.interface.publish_message(self.publish_topic, json.dumps(value, cls=SHCJsonEncoder).encode('utf-8'),
                                             self.qos, self.retain)

    async def _new_value_from_mqtt(self, message: MQTTMessage) -> None:
        await self._publish(from_json(self.type, json.loads(message.payload.decode('utf-8-sig'))), [])
