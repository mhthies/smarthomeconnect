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
import itertools
import json
import logging
from typing import List, Any, Generic, Type, Callable, Awaitable, Optional, Union, Dict, Deque

from paho.mqtt.client import MQTTMessage
from asyncio_mqtt import Client, MqttError, ProtocolVersion
from paho.mqtt.matcher import MQTTMatcher

from ._helper import SupervisedClientInterface
from ..base import Writable, Subscribable, T, S, LogicHandler
from ..conversion import SHCJsonEncoder, from_json

logger = logging.getLogger(__name__)


class MQTTClientInterface(SupervisedClientInterface):
    """
    SHC interface for connecting to MQTT brokers.

    The interface allows to create *subscribable* and *writable* connector objects for subscribing and publishing to
    individual MQTT topics. Additionally it provides generic MQTT client functionality, that can be used by other
    interfaces/adapters for implementing special protocols over MQTT (e.g. :class:`TasmotaInterface` for IoT devices
    running the Tasmota firmware).

    Internally, the interface uses a :class:`asyncio_mqtt.Client` object, which itself uses a
    :class:`paho.mqtt.client.Client`. The connection options (`hostname`, `port`, `username`, `password`, `client_id`
    and `protocol` are passed to that client implementation. TLS encrypted connections are currently not supported.

    By default, the interface features automatic reconnect on MQTT connection loss, but only if the initial connection
    attempt is successful. This behaviour can be customized using the `auto_reconnect` and `failsafe_start` parameters.

    For interacting with "raw" MQTT topics, use one of the following methods for creating connector objects:

      * :meth:`topic_raw` – for publishing and receiving raw :class:`bytes` payloads
      * :meth:`topic_string` – for publishing and receiving UTF-8-encoded strings
      * :meth:`topic_json` – for publishing and receiving arbitrary value types, using SHC's default JSON serialization
        (through :class:`shc.conversion.SHCJsonEncoder` resp. :func:`shc.conversion.from_json`)

    :param hostname: MQTT broker hostname or IP address
    :param port: MQTT broker port
    :param username: MQTT broker login username (no login is performed if None)
    :param password: MQTT broker login password (no login is performed if None)
    :param client_id: MQTT client name (if None, it is auto-generated by the Paho MQTT client)
    :param protocol: MQTT protocol version (from asyncio_mqtt library), defaults to MQTT 3.11
    :param auto_reconnect: If True (default), the client tries to reconnect automatically on connection errors with
        exponential backoff (1 * 1.25^n seconds sleep). Otherwise, the complete SHC system is shut down, when a
        connection error occurs.
    :param failsafe_start: If True and auto_reconnect is True, the API client allows SHC to start up, even if the MQTT
        connection can not be established in the first try. The connection is retried in background with exponential
        backoff (see `auto_reconnect` option). Otherwise (default), the first connection attempt on startup is not
        retried and will shutdown the SHC application on failure, even if `auto_reconnect` is True.
    """
    def __init__(self, hostname: str = 'localhost', port: int = 1883, username: Optional[str] = None,
                 password: Optional[str] = None, client_id: Optional[str] = None,
                 protocol: Union[ProtocolVersion, int] = ProtocolVersion.V311,
                 auto_reconnect: bool = True, failsafe_start: bool = False) -> None:
        super().__init__(auto_reconnect, failsafe_start)
        self.client = Client(hostname, port, username=username, password=password, client_id=client_id,
                             protocol=ProtocolVersion(protocol))
        self.matcher = MQTTMatcher()
        self.subscribe_topics: Dict[str, int] = {}  #: dict {topic: qos} for subscribing
        self.run_task: Optional[asyncio.Task] = None

    async def _connect(self) -> None:
        logger.info("Connecting MQTT client interface ...")
        # TODO this is a dirty hack to work around asyncio-mqtt's reconnect issues
        if self.client._disconnected.done():
            exc = self.client._disconnected.exception()
            if exc:
                logger.warning("MQTT client has been disconnected with exception:", exc_info=exc)
            self.client._connected = asyncio.Future()
            self.client._disconnected = asyncio.Future()
        await self.client.connect()

    async def _subscribe(self) -> None:
        if self.subscribe_topics:
            logger.info("Subscribing to MQTT topics ...")
            logger.debug("Topics: %s", self.subscribe_topics)
            await self.client.subscribe(list(self.subscribe_topics.items()))
        else:
            logger.info("No MQTT topics need to be subscribed")

    async def _disconnect(self) -> None:
        logger.info("Disconnecting MQTT client interface ...")
        try:
            await self.client.disconnect()
        except MqttError as e:
            if e.args[0] == 'Operation timed out':
                await self.client.force_disconnect()

    def topic_raw(self, topic: str, subscribe_topics: Optional[str] = None, qos: int = 0, retain: bool = False,
                  force_mqtt_subscription: bool = False) -> "RawMQTTTopicVariable":
        """
        Create a connector for publishing and receiving MQTT messages to/form a single topic as raw `bytes`

        :param topic: The MQTT topic to publish messages to
        :param subscribe_topics: The topic filter to subscribe to. If None (default) it will be equal to `topic`. This
            can be used to subscribe to a wildcard topic filter instead of only the single publishing topic.
            Attention: `subscribe_topics` must always include the `topic`!
        :param qos: The MQTT QoS for publishing messages to that topic (subscription QoS is currently always 0)
        :param retain: The MQTT *retain* bit for publishing messages to that topic
        :param force_mqtt_subscription: Force subscription to the MQTT topic(s) even if there are no SHC-internal
            *Subscribers* or logic handlers registered to this object. This is required for the `write` method to await
            the successful publishing of a published message to all clients. If there are local *Subscribers* or
            triggered logic handlers and `force_mqtt_subscription` is False, the client will not subscribe to the MQTT
            broker for this topic, so `write()` of this connector object will return immediately.
        """
        if subscribe_topics is None:
            subscribe_topics = topic
        return RawMQTTTopicVariable(self, topic, subscribe_topics, qos, retain, force_mqtt_subscription)

    def topic_string(self, topic: str, subscribe_topics: Optional[str] = None, qos: int = 0, retain: bool = False,
                     force_mqtt_subscription: bool = False) -> "StringMQTTTopicVariable":
        """
        Create a connector for publishing and receiving MQTT messages to/form a single topic as UTF-8 encoded strings

        :param topic: The MQTT topic to publish messages to
        :param subscribe_topics: The topic filter to subscribe to. If None (default) it will be equal to `topic`. This
            can be used to subscribe to a wildcard topic filter instead of only the single publishing topic.
            Attention: `subscribe_topics` must always include the `topic`!
        :param qos: The MQTT QoS for publishing messages to that topic (subscription QoS is currently always 0)
        :param retain: The MQTT *retain* bit for publishing messages to that topic
        :param force_mqtt_subscription: Force subscription to the MQTT topic(s) even if there are no SHC-internal
            *Subscribers* or logic handlers registered to this object. This is required for the `write` method to await
            the successful publishing of a published message to all clients. If there are local *Subscribers* or
            triggered logic handlers and `force_mqtt_subscription` is False, the client will not subscribe to the MQTT
            broker for this topic, so `write()` of this connector object will return immediately.
        """
        if subscribe_topics is None:
            subscribe_topics = topic
        return StringMQTTTopicVariable(self, topic, subscribe_topics, qos, retain, force_mqtt_subscription)

    def topic_json(self, type_: Type[T], topic: str, subscribe_topics: Optional[str] = None, qos: int = 0,
                   retain: bool = False, force_mqtt_subscription: bool = False) -> "JSONMQTTTopicVariable[T]":
        """
        Create a connector for publishing and receiving arbitrary values as JSON-encoded MQTT messages

        The connector uses SHC's generic JSON encoding/decoding system from the :mod:`shc.conversion` module. It has
        built-in support for basic datatypes, :class:`typing.NamedTuple`-based types and :class:`enum.Enum`-based types.
        For handling a custom JSON message format, you should create a custom Python type and specify JSON encoder and
        decoder functions for it, using :func:`shc.conversion.register_json_conversion`. Additionally, you'll want to
        add default type conversion functions from/to default types, using :func:`register_converter`, so that type
        conversion can happen on-the-fly between *connected* objects.

        :param type_: The connector's value type (used for its ``.type`` attribute and for chosing the correct JSON
            decoding function)
        :param topic: The MQTT topic to publish messages to
        :param subscribe_topics: The topic filter to subscribe to. If None (default) it will be equal to `topic`. This
            can be used to subscribe to a wildcard topic filter instead of only the single publishing topic.
            Attention: `subscribe_topics` must always include the `topic`!
        :param qos: The MQTT QoS for publishing messages to that topic (subscription QoS is currently always 0)
        :param retain: The MQTT *retain* bit for publishing messages to that topic
        :param force_mqtt_subscription: Force subscription to the MQTT topic(s) even if there are no SHC-internal
            *Subscribers* or logic handlers registered to this object. This is required for the `write` method to await
            the successful publishing of a published message to all clients. If there are local *Subscribers* or
            triggered logic handlers and `force_mqtt_subscription` is False, the client will not subscribe to the MQTT
            broker for this topic, so `write()` of this connector object will return immediately.
        """
        if subscribe_topics is None:
            subscribe_topics = topic
        return JSONMQTTTopicVariable(type_, self, topic, subscribe_topics, qos, retain, force_mqtt_subscription)

    async def publish_message(self, topic: str, payload: bytes, qos: int = 0, retain: bool = False) -> None:
        """
        Generic coroutine for publishing an MQTT message to be used by higher-level interfaces

        :param topic: The MQTT topic to send the message to
        :param payload: The raw MQTT message payload
        :param qos: The MQTT QoS value of the published message
        :param retain: The MQTT retain bit for publishing
        """
        logger.debug("Sending MQTT message t: %s p: %s q: %s r: %s", topic, payload, qos, retain)
        await self.client.publish(topic, payload, qos, retain)

    def register_filtered_receiver(self, topic_filter: str, receiver: Callable[[MQTTMessage], None],
                                   subscription_qos: int = 0) -> None:
        """
        Subscribe to an MQTT topic filter and register a callback function to be called when a message matching this
        filter is received.

        Warning: If multiple receivers with intersecting topic filters are registered, the receiver behaviour for MQTT
        messages seems to be undefined. Each receiver will still only receive the correct messages, but QoS guarantees
        will probably not be hold. Esp., messages might be received multiple times.

        :param topic_filter: An MQTT topic filter, possible containing wildcard characters. It is used for subscribing
            to these topics and for filtering the received messages.
        :param receiver: The callback function to be called when a matching MQTT message is received. The function
            must have a single free positional argument for taking the MQTTMessage object.
        :param subscription_qos: The subscription QoS
        """
        # If the topic is already subscribed (e.g. by another connector), merge the QOS values (in doubt, promote
        # it to 2)
        if topic_filter in self.subscribe_topics:
            self.subscribe_topics[topic_filter] = \
                2 if self.subscribe_topics[topic_filter] != subscription_qos else subscription_qos
        else:
            self.subscribe_topics[topic_filter] = subscription_qos
        try:
            receiver_list = self.matcher[topic_filter]
            receiver_list.append(receiver)
        except KeyError:
            self.matcher[topic_filter] = [receiver]

    async def _run(self) -> None:
        async with self.client.unfiltered_messages() as messages:
            self._running.set()
            async for message in messages:
                logger.debug("Incoming MQTT message: %s", message)
                receivers: List[List[Callable[[MQTTMessage], Awaitable[None]]]] \
                    = self.matcher.iter_match(message.topic)
                for receiver in itertools.chain.from_iterable(receivers):
                    receiver(message)

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}({self.client._hostname})"


class AbstractMQTTTopicVariable(Writable[T], Subscribable[T], Generic[T], metaclass=abc.ABCMeta):
    def __init__(self, interface: MQTTClientInterface, publish_topic: str, subscribe_topics: str, qos: int,
                 retain: bool, force_mqtt_subscription: bool) -> None:
        super().__init__()
        self.interface = interface
        self.publish_topic = publish_topic
        self.subscribe_topics = subscribe_topics
        if not check_topic_matches_filter(publish_topic, subscribe_topics):
            raise ValueError("The publishing topic must match the subscribe topics filter! (Use an additional connector"
                             "otherwise.)")
        self.qos = qos
        self.retain = retain
        self._receiver_registered = False
        if force_mqtt_subscription:
            self.__subscribe_mqtt()
        self._pending_mqtt_pubs: Dict[bytes, Deque[asyncio.Event]] = {}

    def subscribe(self, subscriber: Writable[S], convert: Union[Callable[[T], S], bool] = False) -> None:
        self.__subscribe_mqtt()
        super().subscribe(subscriber, convert)

    def trigger(self, target: LogicHandler, synchronous: bool = False) -> LogicHandler:
        self.__subscribe_mqtt()
        return super().trigger(target, synchronous)

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
                logger.warning("Sent MQTT message was not received back from the broker within 5s.")
            finally:
                self._publish(value, origin)
                assert queue is not None
                queue.remove(event)
                if not queue:
                    del self._pending_mqtt_pubs[encoded_value]

    def _new_value_from_mqtt(self, message: MQTTMessage) -> None:
        if message.topic != self.publish_topic:
            self._publish(self._decode(message.payload), [])
            return

        queue = self._pending_mqtt_pubs.get(message.payload)
        if queue is not None:
            queue[0].set()
        else:
            self._publish(self._decode(message.payload), [])


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


def check_topic_matches_filter(topic: str, topic_filter: str) -> bool:
    """Returns true if the topic matches the topic_filter (which may contain wildcards).
    It can also be used to check if one topic_filter represents a subset of topics of another filter"""
    for a, b in itertools.zip_longest(topic.split('/'), topic_filter.split('/'), fillvalue=None):
        if b == '#':
            return True
        if b == '+' and a is not None:
            continue
        if a != b:
            return False
    return True
