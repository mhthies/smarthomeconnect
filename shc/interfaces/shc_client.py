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
import weakref
from json import JSONDecodeError
from typing import Type, Dict, Generic, List, Any, Optional

import aiohttp

from ._helper import SupervisedClientInterface
from ..base import T, Subscribable, Writable, Readable, UninitializedError, Reading
from ..conversion import SHCJsonEncoder, from_json
from ..supervisor import register_interface, stop

logger = logging.getLogger(__name__)


# Timeout for read, write and subscribe calls in seconds
TIMEOUT = 5.0


class SHCWebClient(SupervisedClientInterface):
    """
    Client for connecting to remote SHC instances via the websocket API, provided by :class:`shc.web.WebServer`

    For each API object (:class:`shc.web.WebApiObject`) on the remote server, a local "proxy" object can be created by
    calling :meth:`object` with the server object's name and correct type. This object (:class:`WebApiClientObject`)
    forwards local `read` and `write` calls to the server and remote writes from the server to locally subscribed
    objects.

    :param server: Base URL of the remote SHC webserver instance without trailing slash, e.g. 'https://example.com/shc'.
        The path of the API websocket ('/api/v1/ws') is appended internally.
    :param auto_reconnect: If True (default), the API client tries to reconnect automatically on connection errors with
        exponential backoff (1 * 1.25^n seconds sleep). Otherwise, the complete SHC system is shut down, when a
        connection error occurs.
    :param failsafe_start: If True and auto_reconnect is True, the API client allows SHC to start up, even if the API
        connection can not be established in the first try. The connection is retried in background with exponential
        backoff (see `auto_reconnect` option). Otherwise (default), the first connection attempt on startup is not
        retried and will shutdown the SHC application on failure, even if `auto_reconnect` is True.
    :param client_online_object: The (optional) name of an API object of the SHC API server to be used as a server-side
        online indicator for this client. The object must be of bool type. The client will automatically send a `True`
        value to this object when (re)connecting and use the server's ‘last will’ feature to let a `False` value be
        published when the websocket connection is lost.
    """
    def __init__(self, server: str, auto_reconnect: bool = True, failsafe_start: bool = False,
                 client_online_object: Optional[str] = None) -> None:
        super().__init__(auto_reconnect, failsafe_start)
        self.server = server
        self.client_online_object = client_online_object
        self._api_objects: Dict[str, WebApiClientObject] = {}

        self._session: aiohttp.ClientSession
        self._ws: Optional[aiohttp.ClientWebSocketResponse] = None
        self._waiting_futures: weakref.WeakValueDictionary[int, asyncio.Future] = weakref.WeakValueDictionary()

    async def _subscribe_and_wait(self, name: str) -> None:
        """
        Internal coroutine for subscribing for a specified API object on the remote SHC server.

        This method sends the 'subscribe' message to the server and awaits the response (via an asyncio Future). To
        receive the response, it must only be used *after* starting the :meth:`run` coroutine in a parallel task. The
        coroutine raises an exception when a negative response is reiceved from the server or no response is received at
        all within TIMEOUT seconds.

        :param name: Name (designator) of the server's API object to be subscribed
        :raises WebSocketAPIError: when the server responds with a non-200 status code
        :raises asyncio.TimeoutError: when no response is received within TIMEOUT seconds
        """
        future = asyncio.get_event_loop().create_future()
        self._waiting_futures[id(future)] = future
        assert self._ws is not None
        await self._ws.send_json({'action': 'subscribe', 'name': name, 'handle': id(future)})
        result = await asyncio.wait_for(future, TIMEOUT)
        if not 200 <= result['status'] < 300:
            raise WebSocketAPIError("Failed to subscribe SHC API object '{}' with status {}: {}"
                                    .format(name, result['status'], result.get('error')))

    async def start(self) -> None:
        self._session = aiohttp.ClientSession()
        await super().start()

    async def _connect(self) -> None:
        # TODO change timeout: https://docs.aiohttp.org/en/stable/client_quickstart.html#timeouts
        self._ws = await self._session.ws_connect(self.server + '/api/v1/ws')

    async def _subscribe(self) -> None:
        # First send the value all objects with a default_provider to the server
        await asyncio.gather(*(obj._read_and_send()
                               for obj in self._api_objects.values()))
        # then subscribe all objects with subscribers for updates from the server
        await asyncio.gather(*(self._subscribe_and_wait(name)
                               for name, obj in self._api_objects.items()
                               if obj._subscribers or obj._triggers))
        if self.client_online_object is not None:
            await self._set_last_will(self.client_online_object, False)
            await self._send_value(self.client_online_object, True)

    async def _disconnect(self) -> None:
        logger.info("Closing client websocket to %s ...", self.server)
        if self._ws is not None:
            await self._ws.close()

    async def stop(self) -> None:
        await super().stop()
        await self._session.close()

    async def _run(self) -> None:
        """
        Entrypoint for the async "run" Task for receiving Websocket messages
        """
        assert self._ws is not None
        self._running.set()

        # Receive websocket messages until websocket is closed
        msg: aiohttp.WSMessage
        async for msg in self._ws:
            if msg.type == aiohttp.WSMsgType.TEXT:
                self._websocket_dispatch(msg)
            elif msg.type == aiohttp.WSMsgType.ERROR:
                logger.error('SHC API websocket failed with %s', self._ws.exception())

        logger.debug('SHC API websocket connection closed')

    def _websocket_dispatch(self, msg: aiohttp.WSMessage) -> None:
        try:
            message = msg.json()
        except JSONDecodeError:
            logger.warning("Websocket message from SHC server is not a valid JSON string: %s", msg.data)
            return

        logger.debug("Incoming message from websocket API: %s", message)

        try:
            name = message["name"]
            status = message["status"]
        except KeyError:
            logger.warning("Websocket message from SHC server does not include 'name' and 'status' fields: %s",
                           msg.data)
            return

        # If the message has a handle and the handle is associated with a waiting future, set the message as result
        if 'handle' in message:
            future = self._waiting_futures.get(message['handle'])
            if future is None:
                logger.info("Received websocket API message with handle, which refers to non-existent future: %s", msg)
            else:
                future.set_result(message)
                del self._waiting_futures[id(future)]

        # New (or initial) value for subscribed object (not on read response)
        if 'value' in message and ('action' not in message or message['action'] == 'subscribe'):
            # We don't need to do this in an asynchronous task, since the new_value method uses asynchronous publishing
            self._api_objects[name].new_value(message['value'])

        elif 'handle' not in message:
            logger.warning("Received unexpected message from SHC websocket API: %s", msg)

    async def _send_value(self, name: str, value: Any) -> None:
        """
        Coroutine called by WebApiClientObject's _write() method to send a new value to the remote SHC server

        The method awaits the receipt of the server's answer or a timeout of TIMEOUT seconds. In case of a server side
        error or a response timeout, an exception is raised.

        :param name: Name of the API object
        :param value: The value to be sent to the server. The value's type must match the server-side API object's type
            and be encodable with the SHCJsonEncoder (i.e. have a json conversion registered in the
            :mod:`shc.conversion` module).
        :raises WebSocketAPIError: when sending the new value fails on the server side (i.e. the API's return code is
            not in the 200-range). This may be caused by a type or object name mismatch.
        :raises asyncio.TimeoutError: when no response is received from the server within TIMEOUT seconds
        """
        if self._ws is None:
            raise RuntimeError("Websocket of SHC client for API at {} has not been connected yet".format(self.server))
        future = asyncio.get_event_loop().create_future()
        self._waiting_futures[id(future)] = future
        logger.debug("Writing value from SHC API object %s ...", name)
        await self._ws.send_str(json.dumps({'action': 'post', 'name': name, 'value': value, 'handle': id(future)},
                                           cls=SHCJsonEncoder))

        result = await asyncio.wait_for(future, TIMEOUT)
        if 200 <= result['status'] < 300:
            logger.debug("Writing value to SHC API object %s succeeded", name)
        else:
            raise WebSocketAPIError("Writing value to SHC API failed with error {}: {}"
                                    .format(result['status'], result.get('error')))

    async def _set_last_will(self, name: str, value: Any) -> None:
        """
        Coroutine for setting a last will at the SHC server

        The method awaits the receipt of the server's answer or a timeout of TIMEOUT seconds. In case of a server side
        error or a response timeout, an exception is raised.

        The parameters are similar to :meth:`_send_value`:

        :param name: Name of the API object to set the last will for
        :param value: The last will value to be stored at the server. The value's type must match the server-side API
            object's type and be encodable with the SHCJsonEncoder
        :raises WebSocketAPIError: when setting the last will fails on the server side (i.e. the API's return code is
            not in the 200-range). This may be caused by a type or object name mismatch.
        :raises asyncio.TimeoutError: when no response is received from the server within TIMEOUT seconds
        """
        if self._ws is None:
            raise RuntimeError("Websocket of SHC client for API at {} has not been connected yet".format(self.server))
        future = asyncio.get_event_loop().create_future()
        self._waiting_futures[id(future)] = future
        logger.debug("Setting last will at SHC API for object name %s ...", name)
        await self._ws.send_str(json.dumps({'action': 'lastwill', 'name': name, 'value': value, 'handle': id(future)},
                                           cls=SHCJsonEncoder))

        result = await asyncio.wait_for(future, TIMEOUT)
        if 200 <= result['status'] < 300:
            logger.debug("Setting last will at SHC API for object %s succeeded", name)
        else:
            raise WebSocketAPIError("Setting last will at SHC API failed with error {}: {}"
                                    .format(result['status'], result.get('error')))

    async def _read_value(self, name: str) -> Any:
        """
        Coroutine called by WebApiClientObject's read() to fetch the current value of an API object from the remote SHC
        server

        The method awaits the server's answer and returns the raw json-decoded value. If no response is received after
        TIMEOUT seconds the coroutine aborts with an exception.

        :param name: Name of the API object to retrieve its value
        :returns: The json-decoded, but not yet converted value of the API object. It should be converted to the
            expected type, using :func:`shc.conversion.from_json`.
        :raises UninitializedError: when a status code 409 is received from the server, indicating that the API object
            (resp. the underlying readable object) has not yet been initialized.
        :raises WebSocketAPIError: when reading the current value fails on the server side (i.e. the API's return code
            is not in the 200-range). This may be caused object name mismatch or another server-side error.
        :raises asyncio.TimeoutError: when no response is received from the server within TIMEOUT seconds
        """
        if self._ws is None:
            raise RuntimeError("Websocket of SHC client for API at {} has not been connected yet".format(self.server))
        future = asyncio.get_event_loop().create_future()
        self._waiting_futures[id(future)] = future
        logger.debug("Reading value from SHC API object %s ...", name)
        await self._ws.send_str(json.dumps({'action': 'get', 'name': name, 'handle': id(future)}, cls=SHCJsonEncoder))
        result = await asyncio.wait_for(future, TIMEOUT)
        if 200 <= result['status'] < 300:
            logger.debug("Read value %s from SHC API for object %s", result['value'], name)
            return result['value']
        elif result['status'] == 409:
            logger.debug("'get' action of SHC API for object %s returned uninitialized (status 409)", name)
            raise UninitializedError
        else:
            raise WebSocketAPIError("Writing value to SHC API failed with error {}: {}"
                                    .format(result['status'], result.get('error')))

    def object(self, type_: Type, name: str) -> "WebApiClientObject":
        """
        Create a `Connectable` object for communicating with an API object on the remote SHC server.

        The returned object is `Subscribable`, `Readable` and `Writable`. Read and write calls are basically forwarded
        to the corresponding :class:`WebApiObject <shc.web.interface.WebApiObject>` of the server; new values, pushed
        from the server, are published to the object's subscribers.

        :param type_: The data type of the server's API object. This is also the `type` of the returned `Connectable`
            object.
        :param name: The name of the server's API object
        """
        if name in self._api_objects:
            existing = self._api_objects[name]
            if existing.type is not type_:
                raise TypeError("Type {} does not match type {} of existing API client object with same name"
                                .format(type_, existing.type))
            return existing
        else:
            api_object = WebApiClientObject(self, type_, name)
            self._api_objects[name] = api_object
            return api_object

    def __repr__(self) -> str:
        return "{}(server={})".format(self.__class__.__name__, self.server)


class WebApiClientObject(Readable[T], Writable[T], Subscribable[T], Reading[T], Generic[T]):
    """
    A `Connectable` object to communicate with a single API object of a remote SHC websocket API.

    This object basically builds a transparent tunnel to the corresponding :class:`shc.web.WebApiObject` with the
    matching `name` on the server side, forwarding :meth:`read` and :meth:`write` calls to connected objects on the
    server and publishing received value updates (from `write` calls on the server) to locally connected objects.

    Thus, this class inherits from :class:`shc.base.Readable`, :class:`shc.base.Wrtiable` and
    :class:`shc.base.Subscribable`.

    In addition, the class inherits from :class:`shc.base.Reading` (but with `is_reading_optional = True`). This is used
    to (optionally) read a local provider's value and send it to the server upon (re)connection. This is done **before**
    subscribing for updates from the server to ensure that the local value prevails over the server's value in case of
    diverged values in the unconnected time.
    """
    _stateful_publishing = True
    is_reading_optional = True

    def __init__(self, client: SHCWebClient, type_: Type[T], name: str):
        self.type = type_
        super().__init__()
        self.client = client
        self.name = name
        self.pending_sends = 0

    async def read(self) -> T:
        return from_json(self.type, await self.client._read_value(self.name))

    async def _write(self, value: T, origin: List[Any], _reflected_from_server: bool = False) -> None:
        # Asynchronous local feedback publishing. This ensures that conflicting updates, which are currently waiting for
        # local processing by a subscriber can be corrected by resetting this update's origin.
        self._publish(value, origin)
        if not _reflected_from_server:
            self.pending_sends += 1
        try:
            await self.client._send_value(self.name, value)
        finally:
            if not _reflected_from_server:
                self.pending_sends -= 1

    async def _read_and_send(self) -> None:
        """
        If a default_provider is set, read its current value and send it to the server.

        This is usually called by the :meth:`SHCWebClient._subscribe` to send the current local value to the server upon
        (re)connect.
        """
        value = await self._from_provider()
        if value is not None:
            await self._write(value, [])

    def new_value(self, value: Any) -> None:
        """
        Called by the associated :class:`SHCWebClient` when a new value for this object is received from the remote SHC
        server to be published to local subscribers.

        :param value: The received, json-decoded value. It will be processed using :meth:`shc.conversion.from_json`.
        """
        try:
            # Return value to server if we have sent a (conflicting) value recently (with the acknowledge still pending)
            # to prevent inconsistent state on server and client.
            if self.pending_sends:
                asyncio.create_task(self._write(value, [], _reflected_from_server=True))
            self._publish(from_json(self.type, value), [])
            logger.debug("Received new value %s for SHC API object %s", value, self.name)
        except Exception as e:
            logger.error("Error while processing new value %s for API object %s", value, self.name, exc_info=e)


class WebSocketAPIError(RuntimeError):
    """
    Exception to be raised by :meth:`WebApiClientObject.read`, :meth:`WebApiClientObject.write` and on startup of the
    :class:`SHCWebClient`, when an SHC websocket API action fails with an non-200 status code.
    """
    pass
