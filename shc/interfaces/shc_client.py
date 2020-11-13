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
                await asyncio.gather(*(self._subscribe_and_wait(name) for name in self._api_objects))
                # TODO gather results and give a better error description
            except Exception:
                await self._ws.close()
                raise
        except Exception:
            await self._session.close()
            raise

    async def _subscribe_and_wait(self, name: str) -> None:
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
        if 'value' in message and (not 'action' in message or message['action'] == 'subscribe'):
            asyncio.create_task(self._api_objects[name].new_value(message['value']))

        elif 'handle' not in message:
            logger.warning("Received unexpected message from SHC websocket API: %s", msg)

    async def _send_value(self, name: str, value: Any) -> None:
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
        try:
            await self._publish(from_json(self.type, value), [])
            logger.debug("Received new value %s for SHC API object %s", value, self.name)
        except Exception as e:
            logger.error("Error while processing new value %s for API object %s", value, self.name, exc_info=e)


class WebSocketAPIError(RuntimeError):
    pass
