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
import abc
import asyncio
import collections
import json
import logging
from typing import List, Any, Generic, Type, Callable, Awaitable, Optional, Tuple, Union, Dict, Deque

from paho.mqtt.client import MQTTMessage, MQTTv311  # type: ignore
from asyncio_mqtt import Client, MqttError  # type: ignore
from paho.mqtt.matcher import MQTTMatcher  # type: ignore

from ._helper import SupervisedClientInterface
from ..base import Writable, Subscribable, T, S, LogicHandler
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

    def topic_raw(self, topic: str, subscribe_topics: Optional[str] = None, qos: int = 0, retain: bool = False,
                  force_mqtt_subscription: bool = False) -> "RawMQTTTopicVariable":
        if subscribe_topics is None:
            subscribe_topics = topic
        return RawMQTTTopicVariable(self, topic, subscribe_topics, qos, retain, force_mqtt_subscription)

    def topic_string(self, topic: str, subscribe_topics: Optional[str] = None, qos: int = 0, retain: bool = False,
                     force_mqtt_subscription: bool = False) -> "StringMQTTTopicVariable":
        if subscribe_topics is None:
            subscribe_topics = topic
        return StringMQTTTopicVariable(self, topic, subscribe_topics, qos, retain, force_mqtt_subscription)

    def topic_json(self, type_: Type[T], topic: str, subscribe_topics: Optional[str] = None, qos: int = 0,
                   retain: bool = False, force_mqtt_subscription: bool = False) -> "JSONMQTTTopicVariable[T]":
        if subscribe_topics is None:
            subscribe_topics = topic
        return JSONMQTTTopicVariable(type_, self, topic, subscribe_topics, qos, retain, force_mqtt_subscription)

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


class AbstractMQTTTopicVariable(Writable[T], Subscribable[T], Generic[T], metaclass=abc.ABCMeta):
    def __init__(self, interface: MQTTClientInterface, publish_topic: str, subscribe_topics: str, qos: int,
                 retain: bool, force_mqtt_subscription: bool) -> None:
        super().__init__()
        self.interface = interface
        self.publish_topic = publish_topic
        self.subscribe_topics = subscribe_topics
        self.qos = qos
        self.retain = retain
        self._receiver_registered = False
        if force_mqtt_subscription:
            self.__subscribe_mqtt()
        self._pending_mqtt_pubs: Dict[bytes, Deque[asyncio.Event]] = {}

    def subscribe(self, subscriber: Writable[S], convert: Union[Callable[[T], S], bool] = False) -> None:
        self.__subscribe_mqtt()
        super().subscribe(subscriber, convert)

    def trigger(self, target: LogicHandler) -> LogicHandler:
        self.__subscribe_mqtt()
        return super().trigger(target)

    def __subscribe_mqtt(self):
        if not self._receiver_registered:
            self.interface.register_filtered_receiver(self.subscribe_topics, self._new_value_from_mqtt)
            self._receiver_registered = True

    @abc.abstractmethod
    def _encode(self, value: T) -> bytes:
        pass

    @abc.abstractmethod
    def _decode(self, value: bytes) -> T:
        pass

    async def _write(self, value: T, origin: List[Any]) -> None:
        encoded_value = self._encode(value)
        if self._receiver_registered:
            queue = self._pending_mqtt_pubs.get(encoded_value)
            if queue is None:
                queue = collections.deque()
                self._pending_mqtt_pubs[encoded_value] = queue
            event = asyncio.Event()
            queue.append(event)

        await self.interface.publish_message(self.publish_topic, encoded_value, self.qos, self.retain)

        if self._receiver_registered:
            try:
                await asyncio.wait_for(event.wait(), 5)
            except asyncio.TimeoutError:
                pass
            finally:
                await self._publish(value, origin)
                assert queue is not None
                queue.remove(event)
                if not queue:
                    del self._pending_mqtt_pubs[encoded_value]

    async def _new_value_from_mqtt(self, message: MQTTMessage) -> None:
        queue = self._pending_mqtt_pubs.get(message.payload)
        if queue is not None:
            queue[0].set()
        else:
            await self._publish(self._decode(message.payload), [])


class RawMQTTTopicVariable(AbstractMQTTTopicVariable[bytes]):
    type = bytes

    def _encode(self, value: bytes) -> bytes:
        return value

    def _decode(self, value: bytes) -> bytes:
        return value


class StringMQTTTopicVariable(AbstractMQTTTopicVariable[str]):
    type = str

    def _encode(self, value: str) -> bytes:
        return value.encode('utf-8')

    def _decode(self, value: bytes) -> str:
        return value.decode('utf-8-sig')


class JSONMQTTTopicVariable(AbstractMQTTTopicVariable[T], Generic[T]):
    def __init__(self, type_: Type[T], interface: MQTTClientInterface, publish_topic: str, subscribe_topics: str,
                 qos: int, retain: bool, force_mqtt_subscription: bool) -> None:
        self.type = type_
        super().__init__(interface, publish_topic, subscribe_topics, qos, retain, force_mqtt_subscription)

    def _encode(self, value: T) -> bytes:
        return json.dumps(value, cls=SHCJsonEncoder).encode('utf-8')

    def _decode(self, value: bytes) -> T:
        return from_json(self.type, json.loads(value.decode('utf-8-sig')))
