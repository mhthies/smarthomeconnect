#!/usr/bin/env python3
# Copyright 2026 Michael Thies <mail@mhthies.de>
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may not use this file except in compliance with
# the License. You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software distributed under the License is distributed on an
# "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the License for the
# specific language governing permissions and limitations under the License.
"""
An example SHC application that demonstrates the implementation of a custom interface for MQTT communication to a
custom external device.

We imagine a simple music player called `FooPlayer` that provides the following MQTT interface:

* the device publishes an "online"/"offline" message to the MQTT topic /<device>/online (using MQTT's last will
  feature).
* current playback state is published to MQTT topic /<device>/state. Either "play" or "pause".
* current volume (integer in range 0..100) is published to MQTT topic /<device>/volume.
* we can control volume by sending "volume=<value>" to MQTT topic /<device>/command.
* we can control playback state by sending "pause" or "play" to MQTT topic /<device>/command.
* we can trigger a voice announcement of the current state by sending "announce" to MQTT topic /<device>/command.

Please refer to SHC's documentation for more information on implementing custom interfaces:
https://smarthomeconnect.readthedocs.io/en/latest/interfaces_custom.html

"""

import abc
import asyncio
import collections
import enum
import logging
from typing import Any, Deque, Generic, List, Tuple

import aiomqtt

import shc
import shc.interfaces.mqtt
import shc.web
from shc.base import Subscribable, T, T_con, Writable
from shc.datatypes import RangeFloat1
from shc.interfaces._helper import SubscribableStatusInterface
from shc.supervisor import ServiceCriticality, ServiceStatus
from shc.web.widgets import ButtonGroup, Slider, StatelessButton, ValueListButtonGroup

logger = logging.getLogger(__name__)


# ######################################################################################################################
# Definition of the FooPlayerInterface and its connectors


# We derive from SubscribableStatusInterface to get the batteries-included SubscribableStatusConnector as the
# interface's monitoring_connector.
class FooPlayerInterface(SubscribableStatusInterface):
    def __init__(self, mqtt_interface: shc.interfaces.mqtt.MQTTClientInterface, device_id: str):
        super().__init__()
        self.mqtt_interface = mqtt_interface
        self.device_id = device_id
        self._status_connector.update_status(ServiceStatus.UNKNOWN)
        self.mqtt_interface.register_filtered_receiver(self.device_id + "/#", self._on_mqtt_message)
        # We need to make sure that every call to online_connector(), state_connector(), etc. returns the same connector
        # instance, such that the publishing of sent values to other SHC-internal subscribers works correctly.
        # In this simple scenario, we can achieve this by simply constructing all the connector objects upfront. If the
        # number of connectors is large or not known beforehand (due to parameterization of the connectors), you should
        # instead use a dict with a sensible key as a cache and let the interface's methods construct the connectors on
        # demand, if not already existing.
        self._online_connector = FooPlayerOnlineConnector()
        self._state_connector = FooPlayerStateConnector(self)
        self._volume_connector = FooPlayerVolumeConnector(self)

    async def start(self) -> None:
        pass

    async def stop(self) -> None:
        pass

    async def _send_command(self, command: str) -> None:
        await self.mqtt_interface.publish_message(self.device_id + "/command", command.encode(encoding="utf-8"))

    def _on_mqtt_message(self, message: aiomqtt.Message) -> None:
        # In this simple case, we can distinguish the different topics with an if-else-ladder. For larger interfaces,
        # the connectors should be stored in a dict by sub-topic.
        if message.topic.value.endswith("/online"):
            self._online_connector._on_mqtt_message(message.payload.decode())
            status = {"online": ServiceStatus.OK, "offline": ServiceStatus.CRITICAL}.get(
                message.payload.decode(), ServiceStatus.UNKNOWN
            )
            self._status_connector.update_status(status)
        elif message.topic.value.endswith("/volume"):
            self._volume_connector._on_mqtt_message(message.payload.decode())
        elif message.topic.value.endswith("/state"):
            self._state_connector._on_mqtt_message(message.payload.decode())
        elif message.topic.value.endswith("/command"):
            pass
        else:
            logger.warning("MQTT message on unknown topic %s received", message.topic)

    def online_connector(self) -> "FooPlayerOnlineConnector":
        return self._online_connector

    def state_connector(self) -> "FooPlayerStateConnector":
        return self._state_connector

    def volume_connector(self) -> "FooPlayerVolumeConnector":
        return self._volume_connector

    def voice_announcement(self) -> "FooPlayerVoiceAnnouncementConnector":
        return FooPlayerVoiceAnnouncementConnector(self)


class FooPlayerOnlineConnector(Subscribable[bool]):
    type = bool

    def _on_mqtt_message(self, message: str) -> None:
        self._publish(message == "online", [])


class _AbstractStatefulFooPlayerConnector(Subscribable[T], Writable[T], Generic[T], abc.ABC):
    """Abstract type for connector objects for the FooPlayerInterface that are Writable and Subscribable.

    This allows us to re-use the complicated logic for awaiting command replys via a pending command queue for the
    FooPlayerStateConnector and the FooPlayerVolumeConnector.

    All of these are "stateful" connectable objects (since they Subscribable + Writable and represent the state of the
    actual FooPlayer device). We need to set the `_stateful_publishing` class variable to enable the value update
    conflict detection. See Docstring of `Subscribable._publish()` for more information.
    """

    _stateful_publishing = True

    def __init__(self, interface: FooPlayerInterface):
        super().__init__()
        self._interface = interface
        self._pending_command_queue: Deque[Tuple[str, asyncio.Event]] = collections.deque()

    @abc.abstractmethod
    def _decode_message(self, message_payload: str) -> T:
        pass

    @abc.abstractmethod
    def _encode_command_and_expected_reply(self, value: T) -> Tuple[str, str]:
        pass

    def _on_mqtt_message(self, message: str) -> None:
        for expected_reply, event in self._pending_command_queue:
            if message == expected_reply:
                # if there is a pending command where we are waiting for exactly this value as the response, we set the
                # event and the _write() method will take care of publishing the new value with the correct origin.
                event.set()
                break
        else:
            # otherwise, the change of the value seems to have been triggered externally. Thus, we publish it.
            self._publish(self._decode_message(message), [])

    async def _write(self, value: T, origin: List[Any]) -> None:
        command, expected_reply = self._encode_command_and_expected_reply(value)

        # To ensure correct detection of update conflicts, we need to await the returned MQTT message from the
        # device. This is achieved by creating the asyncio.Event, which is pushed into the `_pending_command_queue`
        # and will be set by `_on_mqtt_message()` when we receive a matching MQTT message. For more accurate distinction
        # from external changes, we add the value to the
        event = asyncio.Event()
        self._pending_command_queue.append((expected_reply, event))

        try:
            await self._interface._send_command(command)
            await asyncio.wait_for(event.wait(), 5)
            # Only publish new value to local subscribers when it has been successfully transmitted to the device
            self._publish(value, origin)
        except asyncio.TimeoutError:
            logger.warning(
                "No Result from FooPlayer device %s to %s command within 5s.", self._interface.device_id, command
            )
        finally:
            # Remove queue entry
            self._pending_command_queue.remove((expected_reply, event))


class FooPlayerState(enum.Enum):
    PLAYING = "play"
    PAUSED = "pause"


class FooPlayerStateConnector(_AbstractStatefulFooPlayerConnector[FooPlayerState]):
    type = FooPlayerState

    def _decode_message(self, message_payload: str) -> FooPlayerState:
        return FooPlayerState(message_payload)

    def _encode_command_and_expected_reply(self, value: FooPlayerState) -> Tuple[str, str]:
        return value.value, value.value


class FooPlayerVolumeConnector(_AbstractStatefulFooPlayerConnector[RangeFloat1]):
    type = RangeFloat1

    def _decode_message(self, message_payload: str) -> RangeFloat1:
        return RangeFloat1(int(message_payload) / 100)

    def _encode_command_and_expected_reply(self, value: RangeFloat1) -> Tuple[str, str]:
        encoded_value = str(round(value * 100))
        return f"volume={encoded_value}", encoded_value


class FooPlayerVoiceAnnouncementConnector(Writable[None]):
    type = type(None)

    def __init__(self, interface: FooPlayerInterface):
        self._interface = interface

    async def _write(self, value: T_con, origin: List[Any]) -> None:
        await self._interface._send_command("announce")


# ######################################################################################################################
# SHC application setup with an instance of the interface and a Web UI

mqtt_interface = shc.interfaces.mqtt.MQTTClientInterface("localhost", 1883, failsafe_start=True)
foo_player_interface = FooPlayerInterface(mqtt_interface, "my_player_id")

web_server = shc.web.WebServer("localhost", 8080, index_name="index")
web_server.configure_monitoring([(foo_player_interface, "FooPlayer my_player_id", ServiceCriticality.WARNING)])

index_page = web_server.page("index", "Home", menu_entry=True, menu_icon="home")

index_page.add_item(
    ValueListButtonGroup([(FooPlayerState.PAUSED, "️⏸️"), (FooPlayerState.PLAYING, "▶️")], "Foo Player State").connect(
        foo_player_interface.state_connector()
    )
)
index_page.add_item(
    ButtonGroup("Foo Player Commands", [StatelessButton(None, "🗣️").connect(foo_player_interface.voice_announcement())])
)
index_page.add_item(Slider("Volume", color="blue").connect(foo_player_interface.volume_connector()))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    shc.main()
