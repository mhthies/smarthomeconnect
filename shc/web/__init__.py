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
import itertools
import json
import logging
import os
from typing import Dict, Iterable, Union, List, Set, Any, Optional, Tuple

import aiohttp.web
import jinja2
import markupsafe

from ..base import Reading, T, Writable, Subscribable
from ..conversion import SHCJsonEncoder, from_json
from ..supervisor import register_interface

logger = logging.getLogger(__name__)

jinja_env = jinja2.Environment(
    loader=jinja2.PackageLoader('shc.web', 'templates'),
    autoescape=jinja2.select_autoescape(['html', 'xml']),
    enable_async=True,
    trim_blocks=True,
    lstrip_blocks=True,
)
jinja_env.filters['id'] = id


class WebServer:
    def __init__(self, host: str, port: int, index_name: str):
        self.host = host
        self.port = port
        self.index_name = index_name
        self._pages: Dict[str, WebPage] = {}
        self.connectors: Dict[int, WebDisplayDatapoint] = {}
        self.ui_menu_entries: List[Tuple[Union[str, markupsafe.Markup], Union[str, Tuple]]] = []
        self._app = aiohttp.web.Application()
        self._app.add_routes([
            aiohttp.web.get("/", self._index_handler),
            aiohttp.web.get("/page/{name}/", self._page_handler, name='show_page'),
            aiohttp.web.get("/ws", self._websocket_handler),
            aiohttp.web.static('/static', os.path.join(os.path.dirname(__file__), 'static')),
        ])
        # aiohttp's Runner or Site do not provide a good method to await the stopping of the server. Thus we use our own
        # Event for that purpose.
        self._stopped = asyncio.Event()
        register_interface(self)
        # TODO add datapoint API

        # TODO allow registering HTTP APIs
        # TODO allow registering websocket APIs
        # TODO allow collecting page elements of certain type

    async def start(self) -> None:
        logger.info("Starting up web server on %s:%s ...", self.host, self.port)
        for connector in itertools.chain.from_iterable(page.get_connectors() for page in self._pages.values()):
            self.connectors[id(connector)] = connector
        self._runner = aiohttp.web.AppRunner(self._app)
        await self._runner.setup()
        site = aiohttp.web.TCPSite(self._runner, self.host, self.port)
        await site.start()

    async def wait(self) -> None:
        await self._stopped.wait()

    async def stop(self) -> None:
        logger.info("Cleaning up AppRunner ...")
        await self._runner.cleanup()
        self._stopped.set()

    def page(self, name: str) -> "WebPage":
        if name in self._pages:
            return self._pages[name]
        else:
            page = WebPage(self, name)
            self._pages[name] = page
            return page

    async def _index_handler(self, request: aiohttp.web.Request) -> aiohttp.web.Response:
        raise aiohttp.web.HTTPFound(self._app.router['show_page'].url_for(name=self.index_name))

    async def _page_handler(self, request: aiohttp.web.Request) -> aiohttp.web.Response:
        try:
            page = self._pages[request.match_info['name']]
        except KeyError:
            raise aiohttp.web.HTTPNotFound()
        return await page.generate(request, self.ui_menu_entries)

    async def _websocket_handler(self, request: aiohttp.web.Request) -> aiohttp.web.WebSocketResponse:
        ws = aiohttp.web.WebSocketResponse()
        await ws.prepare(request)

        msg: aiohttp.WSMessage
        async for msg in ws:
            if msg.type == aiohttp.WSMsgType.TEXT:
                await self._websocket_dispatch(ws, msg)
            elif msg.type == aiohttp.WSMsgType.ERROR:
                logger.info('ws connection closed with exception %s', ws.exception())
        logger.debug('websocket connection closed')
        # Make sure the websocket is removed as a subscriber from all WebDisplayDatapoints
        for connector in self.connectors.values():
            if isinstance(connector, WebDisplayDatapoint):
                await connector.websocket_close(ws)
        return ws

    async def _websocket_dispatch(self, ws: aiohttp.web.WebSocketResponse, msg: aiohttp.WSMessage) -> None:
        message = msg.json()
        try:
            connector = self.connectors[message["id"]]
        except KeyError:
            logger.error("Could not route message from websocket to connector, since no connector with this id is "
                         "known.")
            return
        if 'v' in message:
            await connector.from_websocket(message['v'], ws)
        elif 'sub' in message:
            await connector.websocket_subscribe(ws)
        else:
            logger.warning("Don't know how to handle websocket message: %s", message)


class WebConnectorContainer(metaclass=abc.ABCMeta):
    @abc.abstractmethod
    def get_connectors(self) -> Iterable["WebConnector"]:
        pass


class WebPage(WebConnectorContainer):
    def __init__(self, server: WebServer, name: str):
        self.server = server
        self.name = name
        self.segments: List["_WebPageSegment"] = []

    def add_item(self, item: "WebPageItem"):
        if not self.segments:
            self.new_segment()
        self.segments[-1].items.append(item)

    def get_connectors(self) -> Iterable[Union["WebDisplayDatapoint", "WebActionDatapoint"]]:
        return itertools.chain.from_iterable(item.get_connectors() for item in self.segments)

    def new_segment(self, title: Optional[str] = None, same_column: bool = False, full_width: bool = False):
        self.segments.append(_WebPageSegment(title, same_column, full_width))

    async def generate(self, request: aiohttp.web.Request, menu_data) -> aiohttp.web.Response:
        template = jinja_env.get_template('page.htm')
        body = await template.render_async(title=self.name, segments=self.segments, menu=menu_data)
        return aiohttp.web.Response(body=body, content_type="text/html", charset='utf-8')


class _WebPageSegment(WebConnectorContainer):
    def __init__(self, title: Optional[str], same_column: bool, full_width: bool):
        self.title = title
        self.same_column = same_column
        self.full_width = full_width
        self.items: List[WebPageItem] = []

    def get_connectors(self) -> Iterable[Union["WebConnector"]]:
        return itertools.chain.from_iterable(item.get_connectors() for item in self.items)


class WebPageItem(WebConnectorContainer, metaclass=abc.ABCMeta):
    @abc.abstractmethod
    async def render(self) -> str:
        pass


class WebConnector(WebConnectorContainer, metaclass=abc.ABCMeta):
    """
    An abstract base class for all objects that want to exchange messages with JavaScript UI Widgets via the websocket
    connection.

    For every Message received from a client websocket, the :meth:`from_websocket` method of the appropriate
    `WebConnector` is called. For this purpose, the :class:`WebServer` creates a dict of all WebConnectors in any
    registered :class:`WebPage` by their Python object id at startup. The message from the websocket is expected to have
    an `id` field which is used for the lookup.
    """
    @abc.abstractmethod
    async def from_websocket(self, value: Any, ws: aiohttp.web.WebSocketResponse) -> None:
        """
        This method is called for incoming "value" messages from a client to this specific `WebConnector` object.

        :param value: The JSON-decoded 'value' field from the message from the websocket
        :param ws: The concrete websocket, the message has been received from.
        """
        pass

    async def websocket_subscribe(self, ws: aiohttp.web.WebSocketResponse) -> None:
        """
        This method is called for incoming "subscribe" messages from a client to this specific `WebConnector` object.
        """
        pass

    async def websocket_close(self, ws: aiohttp.web.WebSocketResponse) -> None:
        """
        Called on every `WebConnector` of the :class:`WebServer`, when a websocket disconnects.

        Warning: This method is not only called on `WebConnectors` being subscribed by the closing websocket. So make
        sure to silently ignore the closing of unknown websockets when overriding this method.

        :param ws: The websocket that disconnected
        """
        pass

    def get_connectors(self) -> Iterable["WebConnector"]:
        return (self,)

    def __repr__(self):
        return "{}<id={}>".format(self.__class__.__name__, id(self))


class WebDisplayDatapoint(Reading[T], Writable[T], WebConnector, metaclass=abc.ABCMeta):
    is_reading_optional = False

    def __init__(self):
        super().__init__()
        self.subscribed_websockets: Set[aiohttp.web.WebSocketResponse] = set()

    async def _write(self, value: T, origin: List[Any]):
        await self._publish_to_ws(self.convert_to_ws_value(value))

    # TODO: refactor int WebConnector?
    async def _publish_to_ws(self, value):
        logger.debug("Publishing value %s for %s for %s subscribed websockets ...",
                     value, id(self), len(self.subscribed_websockets))
        data = json.dumps({'id': id(self), 'value': value}, cls=SHCJsonEncoder)
        await asyncio.gather(*(ws.send_str(data) for ws in self.subscribed_websockets))

    def convert_to_ws_value(self, value: T) -> Any:
        return value

    async def websocket_subscribe(self, ws: aiohttp.web.WebSocketResponse) -> None:
        if self._default_provider is None:
            logger.error("Cannot handle websocket subscription for %s, since not read provider is registered.",
                         self)
            return
        logger.debug("New websocket subscription for widget id %s.", id(self))
        self.subscribed_websockets.add(ws)
        current_value = await self._from_provider()
        if current_value is not None:
            data = json.dumps({'id': id(self),
                               'value': self.convert_to_ws_value(current_value)},
                              cls=SHCJsonEncoder)
            await ws.send_str(data)

    async def websocket_close(self, ws: aiohttp.web.WebSocketResponse) -> None:
        logger.debug("Unsubscribing websocket from %s.", self)
        self.subscribed_websockets.discard(ws)


class WebActionDatapoint(Subscribable[T], WebConnector, metaclass=abc.ABCMeta):
    def convert_from_ws_value(self, value: Any) -> T:
        return from_json(self.type, value)

    async def from_websocket(self, value: Any, ws: aiohttp.web.WebSocketResponse) -> None:
        await self._publish(self.convert_from_ws_value(value), [ws])
        if isinstance(self, WebDisplayDatapoint):
            await self._publish_to_ws(value)


from . import widgets
