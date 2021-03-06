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
from typing import Type, Dict, Generic, List, Any

import aiohttp

from ..base import T, Subscribable, Writable, Readable, UninitializedError
from ..conversion import SHCJsonEncoder, from_json
from ..supervisor import register_interface

logger = logging.getLogger(__name__)


# Timeout for read, write and subscribe calls in seconds
TIMEOUT = 5.0


class SHCWebClient:
    """
    Client for connecting to remote SHC instances via the websocket API, provided by :class:`shc.web.WebServer`

    For each API object (:class:`shc.web.WebApiObject`) on the remote server, a local "proxy" object can be created by
    calling :meth:`object` with the server object's name and correct type. This object (:class:`WebApiClientObject`)
    forwards local `read` and `write` calls to the server and remote writes from the server to locally subscribed
    objects.

    :param server: Base URL of the remote SHC webserver instance without trailing slash, e.g. 'https://example.com/shc'.
        The path of the API websocket ('/api/v1/ws') is appended internally.
    """
    def __init__(self, server: str) -> None:
        self.server = server
        self._api_objects: Dict[str, WebApiClientObject] = {}
        register_interface(self)

        self._session: aiohttp.ClientSession
        self._ws: aiohttp.ClientWebSocketResponse
        self._run_task: asyncio.Task
        self._stopping = False
        self._waiting_futures: weakref.WeakValueDictionary[int, asyncio.Future] = weakref.WeakValueDictionary()

    async def start(self):
        logger.info("Connecting SHC web client interface to %s ...", self.server)
        self._session = aiohttp.ClientSession()
        try:
            self._ws = await self._session.ws_connect(self.server + '/api/v1/ws')
            try:
                self._run_task = asyncio.create_task(self.run())
                await asyncio.gather(*(self._subscribe_and_wait(name)
                                       for name, obj in self._api_objects.items()
                                       if obj._subscribers or obj._triggers))
                # TODO gather results and give a better error description
            except Exception:
                await self._ws.close()
                raise
        except Exception:
            await self._session.close()
            raise

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
        await self._ws.send_json({'action': 'subscribe', 'name': name, 'handle': id(future)})
        result = await asyncio.wait_for(future, TIMEOUT)
        if not 200 <= result['status'] < 300:
            raise WebSocketAPIError("Failed to subscribe SHC API object '{}' with status {}: {}"
                                    .format(name, result['status'], result.get('error')))

    async def wait(self):
        await self._run_task

    async def stop(self):
        logger.info("Closing SHC web client to %s ...", self.server)
        self._stopping = True
        await self._ws.close()
        await self._run_task
        await self._session.close()

    async def run(self) -> None:
        msg: aiohttp.WSMessage
        async for msg in self._ws:
            if msg.type == aiohttp.WSMsgType.TEXT:
                await self._websocket_dispatch(msg)
            elif msg.type == aiohttp.WSMsgType.ERROR:
                raise RuntimeError('SHC API websocket connection closed with exception {}'
                                   .format(self._ws.exception()))
        logger.debug('SHC API websocket connection closed')
        if not self._stopping:
            raise RuntimeError('SHC API websocket was unexpectedly closed')

    async def _websocket_dispatch(self, msg: aiohttp.WSMessage) -> None:
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
            asyncio.create_task(self._api_objects[name].new_value(message['value']))

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
        to the corresponding :class:`shc.web.WebApiObject`; new values, pushed from the server, are published to the
        object's subscribers.

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


class WebApiClientObject(Readable[T], Writable[T], Subscribable[T], Generic[T]):
    """
    A `Connectable` object to communicate with a single API object of a remote SHC websocket API.

    This object basically builds a transparent tunnel to the corresponding :class:`shc.web.WebApiObject` with the
    matching `name` on the server side, forwarding :meth:`read` and :meth:`write` calls to connected objects on the
    server and publishing received value updates (from `write` calls on the server) to locally connected objects.

    Thus, this class inherits from :class:`shc.base.Readable`, :class:`shc.base.Wrtiable` and
    :class:`shc.base.Subscribable`.
    """
    def __init__(self, client: SHCWebClient, type_: Type[T], name: str):
        self.type = type_
        super().__init__()
        self.client = client
        self.name = name

    async def read(self) -> T:
        return from_json(self.type, await self.client._read_value(self.name))

    async def _write(self, value: T, origin: List[Any]) -> None:
        await self.client._send_value(self.name, value)
        await self._publish(value, origin)

    async def new_value(self, value: Any) -> None:
        """
        Called by the associated :class:`SHCWebClient` when a new value for this object is received from the remote SHC
        server to be published to local subscribers.

        :param value: The received, json-decoded value. It will be processed using :meth:`shc.conversion.from_json`.
        """
        try:
            await self._publish(from_json(self.type, value), [])
            logger.debug("Received new value %s for SHC API object %s", value, self.name)
        except Exception as e:
            logger.error("Error while processing new value %s for API object %s", value, self.name, exc_info=e)


class WebSocketAPIError(RuntimeError):
    """
    Exception to be raised by :meth:`WebApiClientObject.read`, :meth:`WebApiClientObject.write` and on startup of the
    :class:`SHCWebClient`, when an SHC websocket API action fails with an non-200 status code.
    """
    pass
