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
An example SHC application that demonstrates the implementation of a custom interface for communication with an
external web service via a websocket connection. The interface is based on the `SupervisedClientInterface` helper class.

We imagine a very simple smart home gateway with a websocket API. It allows us to control an arbitrary number of
attached dimmable lights, addressed by simple integer bus adresses, with the following protocol:

* Subscription: At startup, we connect to the websocket and send a command "<seq>:subscribe:<addr>" for every lamp
  address <addr> we are interested in. <seq> is a command sequence number to correlate the gateway's replies with the
  commands (e.g. "7:subscribe:42").
  * The gateway responds with either "<seq>:ok" or "<seq>:error:<error message>", e.g. "7:error:No such dimmer"
  * In addition, the gatway will send us a ":value:<addr>:<value>" message with the current dimmer value (0-100), e.g.
    ":value:42:0"
  * This message will also be sent by the gateway whenever a dimmer value is changed for one of these lights externally
    (at the light's control dial, from another websocket client, etc.). Such a message will *not* be sent when *we*
    requested a value change (-> we don't have to filter out these messages to recover the SHC `origin` value).
* We can change a dimmer by sending a command message "<seq>:set:<addr>:<value>". Again, <seq> is a command sequence
  number for correlation of the reply (e.g. "9:set:42:99").
  * The gateway responds with either "<seq>:ok" or "<seq>:error:<error message>"

Please refer to SHC's documentation for more information on implementing custom interfaces:
https://smarthomeconnect.readthedocs.io/en/latest/interfaces_custom.html
"""

import asyncio
import logging
import weakref
from typing import Any, Dict, List, Optional

import aiohttp

import shc.web
from shc.base import Subscribable, Writable
from shc.datatypes import RangeFloat1
from shc.interfaces._helper import SupervisedClientInterface
from shc.web.widgets import Slider

logger = logging.getLogger(__name__)


class ExampleDimmerGatewayInterface(SupervisedClientInterface):
    def __init__(self, gateway_address: str):
        super().__init__()
        self.gateway_address = gateway_address
        # A dict to cache the created Connector objects
        self._dimmer_connectors: Dict[int, ExampleDimmerConnector] = {}

        # We cannot create the aiohttp ClientSession in the __init__ method, because it calls
        # `asyncio.get_running_loop()` in its init method, but this whole object may be constructed before there is an
        # asyncio event loop running. Thus, we only declare the _session attribute here for the type checking and fill
        # it later in the `start()` coroutine, which is guaranteed to be the first method called from within the asyncio
        # event loop.
        self._session: aiohttp.ClientSession
        # Same for the websocket, which whill be constructed in the `_connect` method. Note, that -- other than the
        # ClientSession -- it is explicitly set to None, unless the connection is established.
        self._ws: Optional[aiohttp.ClientWebSocketResponse] = None
        # A dict of futures for pending commands ('subscribe' or 'set'), sent to the gateway. The futures are used to
        # await the response from the gatway. They are resolved by the _run task, either with a `None` value (in case of
        # an 'ok' response) or with an ExampleDimmerAPIError exception in case of an 'error' response.
        # We use a `WeakValueDictionary` here to allow destruction of the interface and the futures even when there are
        # pending & awaited futures left at destruction time.
        self._waiting_futures: weakref.WeakValueDictionary[int, asyncio.Future] = weakref.WeakValueDictionary()
        self._next_sequence_number = 0

    def dimmer_connector(self, dimmer_address: int) -> "ExampleDimmerConnector":
        """
        Get a connector object for the given dimmer channel.

        :param dimmer_address: The dimmer address to get connector for.
        """
        if dimmer_address not in self._dimmer_connectors:
            self._dimmer_connectors[dimmer_address] = ExampleDimmerConnector(self, dimmer_address)
        return self._dimmer_connectors[dimmer_address]

    async def start(self) -> None:
        # Usually, we do not need to implement the `start()` coroutine ourselves, when deriving from
        # `SupervisedClientInterface`. However, we override this coroutine to defer construction of the aiohttp
        # ClientSession to this method (to guarantee that an asyncio event loop is available). Then, we let
        # `SupervisedClientInterface.start()` orchestrate the interface startup as usual.
        timeout = aiohttp.ClientTimeout(total=60)
        self._session = aiohttp.ClientSession(timeout=timeout)
        await super().start()

    async def _connect(self) -> None:
        self._ws = await self._session.ws_connect(self.gateway_address + "/api/v1/ws")

    async def _subscribe(self) -> None:
        # subscribe for updates from the server, but only for those dimmer addresses that have Connector object that has
        # local subscribers
        await asyncio.gather(
            *(
                self._subscribe_and_wait(dimmer_address)
                for dimmer_address, obj in self._dimmer_connectors.items()
                if obj._subscribers or obj._triggers
            )
        )

    async def _disconnect(self) -> None:
        logger.info("Closing client websocket to %s ...", self.gateway_address)
        if self._ws is not None:
            await self._ws.close()

    async def stop(self) -> None:
        # Similar to the `start()` method, we let `SupervisedClientInterface.stop()` orchestrate the shutdown (i.e.
        # calling _disconnect() and waiting of the _run task to exit) and afterwards perform our custom deinitialization
        # (gracefully closing the aiohttp ClientSession)
        await super().stop()
        await self._session.close()

    async def _run(self) -> None:
        """
        Entrypoint to the _run task. We use it for receiving and dispatching the incoming websocket messages.
        """
        assert self._ws is not None
        assert self._running is not None, (
            "_running Event should have been constructed in SupervisedClientInterface.start()"
        )
        self._running.set()

        # Receive websocket messages until websocket is closed
        msg: aiohttp.WSMessage
        async for msg in self._ws:
            if msg.type == aiohttp.WSMsgType.TEXT:
                self._websocket_dispatch(msg)
            elif msg.type == aiohttp.WSMsgType.ERROR:
                logger.error("Dimmer gateway websocket failed with %s", self._ws.exception())  #
            # ignore other websocket message types

        logger.debug("Dimmer gateway websocket connection closed")

    def _websocket_dispatch(self, msg: aiohttp.WSMessage) -> None:
        """
        Dispatch a received websocket message. This is a helper method for  the _run task.

        Depending on the type of the message, it is used to resolve a pending future in `_waiting_futures` or it is
        forwarded as a value update to the respective Connector.
        """
        message: str = msg.data
        logger.debug("Incoming message from websocket: %s", message)

        message_parts = message.split(":")
        if len(message_parts) < 2:
            logger.error("Invalid message from gateway %s: Too few parts: '%s'", self.gateway_address, message)
            return
        message_type = message_parts[1]

        if message_type == "value":
            if len(message_parts) < 4:
                logger.error(
                    "Invalid value message from gateway %s: Too few parts: '%s'", self.gateway_address, message
                )
                return
            dimmer_address = int(message_parts[2])
            value = int(message_parts[3])
            if dimmer_address not in self._dimmer_connectors:
                logger.warning(
                    "Got unexpected value update for dimmer %s from gateway %s", dimmer_address, self.gateway_address
                )
                return
            self._dimmer_connectors[dimmer_address]._new_value_from_gateway(value)

        elif message_type == "ok":
            sequence_number = int(message_parts[0])
            if sequence_number not in self._waiting_futures:
                logger.warning(
                    "Got unexpected ok response for seq %s from gateway %s", sequence_number, self.gateway_address
                )
                return
            self._waiting_futures[sequence_number].set_result(None)

        elif message_type == "error":
            sequence_number = int(message_parts[0])
            if sequence_number not in self._waiting_futures:
                logger.warning(
                    "Got unexpected ok response for seq %s from gateway %s", sequence_number, self.gateway_address
                )
                return
            error = message_parts[2]
            self._waiting_futures[sequence_number].set_exception(ExampleDimmerAPIError(error))

        else:
            logger.error("Got unknown message type from gateway %s: '%s'", self.gateway_address, message)

    async def _subscribe_and_wait(self, dimmer_address: int) -> None:
        """
        Internal coroutine for subscribing for a specified dimmer on the dimmer gateway.

        This method sends the 'subscribe' message to the gateway and awaits the response (via an asyncio Future). To
        receive the response, it must only be used *after* starting the :meth:`run` coroutine in a parallel task. The
        coroutine raises an exception when an error response is received from the server or no response is received at
        all within 5 seconds.

        :param dimmer_address: The address/index of the dimmer to subscribe
        :raises ExampleDimmerAPIError: when the gateway responds with an error
        :raises asyncio.TimeoutError: when no response is received from the gateway within TIMEOUT seconds
        """
        # Create a future for getting the result and add the future to the _waiting_futures dict, such that the _run
        # task can resolve it when receiving the response.
        future = asyncio.get_running_loop().create_future()
        sequence_number = self._next_sequence_number
        self._next_sequence_number += 1
        self._waiting_futures[sequence_number] = future

        # Send subscribe request and wait for result future
        assert self._ws is not None
        await self._ws.send_str("{}:subscribe:{}".format(sequence_number, dimmer_address))
        timeout_sec = 5.0
        await asyncio.wait_for(future, timeout_sec)

    async def _send_value(self, dimmer_address: int, value: int) -> None:
        """
        Coroutine called by ExampleDimmerConnector's _write() method to send a new value to the dimmer gateway.

        The method awaits the receipt of the server's answer or a timeout of TIMEOUT seconds. In case of a server side
        error or a response timeout, an exception is raised.

        :param dimmer_address: The address/index of the dimmer to update
        :param value: The new dimmer value to be sent to the gateway.
        :raises ExampleDimmerAPIError: when sending the new value fails on the gateway side (i.e. the gateway returns
            an 'error' response).
        :raises asyncio.TimeoutError: when no response is received from the gateway within 5 seconds
        """
        if self._ws is None:
            raise RuntimeError(
                "Websocket of dimmer gateway at {} has not been connected yet".format(self.gateway_address)
            )

        # Create a future for getting the result and add the future to the _waiting_futures dict, such that the _run
        # task can resolve it when receiving the response.
        future = asyncio.get_running_loop().create_future()
        sequence_number = self._next_sequence_number
        self._next_sequence_number += 1
        self._waiting_futures[sequence_number] = future

        # Send subscribe request and wait for result future
        logger.debug("Writing dimmer %s value to ExampleDimmerGateway ...", dimmer_address)
        await self._ws.send_str("{}:set:{}:{}".format(sequence_number, dimmer_address, value))
        timeout_sec = 5.0
        await asyncio.wait_for(future, timeout_sec)
        logger.debug("Writing dimmer %s value to ExampleDimmerGateway succeeded", dimmer_address)


class ExampleDimmerConnector(Writable[RangeFloat1], Subscribable[RangeFloat1]):
    """
    Connector class for a single dimmer channel.

    It is Subscribable to receive value updates and Writable to send a new dimmer value to the gateway.
    """

    type = RangeFloat1
    _stateful_publishing = True

    def __init__(self, interface: ExampleDimmerGatewayInterface, dimmer_address: int) -> None:
        super().__init__()
        self._interface = interface
        self.dimmer_address = dimmer_address

    async def _write(self, value: RangeFloat1, origin: List[Any]) -> None:
        # The _send_value coroutine awaits the successful transmission of the value to the gateway (including response)
        # or raises an exception. Thus, this _write() coroutine correctly awaits the processing of the value update.
        await self._interface._send_value(self.dimmer_address, int(value * 100))
        self._publish(value, origin)

    def _new_value_from_gateway(self, value: int) -> None:
        # Since our imagined smart home gateway does only send us value updates for external value changes, we do not
        # need to check for pending updates from SHC here (to add the correct `origin` for publishing the value).
        # See the `custom_mqtt_interface.py` example for an example interface that needs to deal with
        self._publish(RangeFloat1(value / 100), [])


class ExampleDimmerAPIError(RuntimeError):
    """
    Custom Exception class to be raised when the interaction with the Dimmer gateway fails.
    """

    pass


# ######################################################################################################################
# SHC application setup with an instance of the interface and a Web UI with sliders for the first 10 dimmers

dimmer_gateway_interface = ExampleDimmerGatewayInterface("http://dimmer-gateway.lan")

web_server = shc.web.WebServer("localhost", 8080, index_name="index")

index_page = web_server.page("index", "Home", menu_entry=True, menu_icon="home")

for i in range(10):
    var = shc.Variable(RangeFloat1, "dimmer_{}".format(i), RangeFloat1(0.0)).connect(
        dimmer_gateway_interface.dimmer_connector(i)
    )
    index_page.add_item(Slider("Dimmer {}".format(i + 1), color="yellow").connect(var))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    shc.main()
