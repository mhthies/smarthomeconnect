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
import weakref
from typing import Dict, Iterable, Union, List, Set, Any, Optional, Tuple

import aiohttp.web
import jinja2
import markupsafe
from aiohttp import WSCloseCode

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
    """
    A SHC interface to provide the web user interface.
    """
    def __init__(self, host: str, port: int, index_name: Optional[str] = None, root_url: str = "/"):
        """
        :param host: The listening host. Use "" to listen on all interfaces or "localhost" to listen only on the
            loopback interface.
        :param port: The port to listen on
        :param index_name: Name of the `WebPage`, the root URL redirects to. If None, the root URL returns an HTTP 404.
        :param root_url: The base URL, at witch the user will reach this server. Used to construct internal links. May
            be an absolute URI (like "https://myhost:8080/shc/") or an absolute-path reference (like "/shc/"). Defaults
            to "/". Note: This does not affect the routes of this HTTP server. It is only relevant, if you use an HTTP
            reverse proxy in front of this application, which serves the application in a sub path.
        """
        self.host = host
        self.port = port
        self.index_name = index_name
        self.root_url = root_url

        # a dict of all `WebPages` by their `name` for rendering them in the `_page_handler`
        self._pages: Dict[str, WebPage] = {}
        # a dict of all `WebConnectors` by their Python object id for routing incoming websocket mesages
        self.connectors: Dict[int, WebConnector] = {}
        # a set of all open websockets to close on graceful shutdown
        self._websockets = weakref.WeakSet()
        # data structure of the user interface's main menu
        # The structure looks as follows:
        # [('Label', 'page_name'),
        #  ('Submenu label', [
        #     ('Label 2', 'page_name2'), ...
        #   ]),
        #  ...]
        # TODO provide interface for easier setting of this structure
        self.ui_menu_entries: List[Tuple[Union[str, markupsafe.Markup], Union[str, Tuple]]] = []
        # List of all static js URLs to be included in the user interface pages
        self._js_files = [
            "static/jquery-3.min.js",
            "static/semantic-ui/components/checkbox.min.js",
            "static/semantic-ui/components/dropdown.min.js",
            "static/semantic-ui/components/slider.min.js",
            "static/semantic-ui/components/sidebar.min.js",
            "static/semantic-ui/components/transition.min.js",
            "static/iro.min.js",
            "static/main.js",
        ]
        # List of all static css URLs to be included in the user interface pages
        self._css_files = [
            "static/semantic-ui/semantic.min.css",
            "static/main.css",
        ]

        # The actual aiohttp web app
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
        logger.info("Closing open websockets ...")
        for ws in set(self._websockets):
            await ws.close(code=WSCloseCode.GOING_AWAY, message='Server shutdown')
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
        if not self.index_name:
            return aiohttp.web.HTTPNotFound()
        return aiohttp.web.HTTPFound(self._app.router['show_page'].url_for(name=self.index_name))

    async def _page_handler(self, request: aiohttp.web.Request) -> aiohttp.web.Response:
        try:
            page = self._pages[request.match_info['name']]
        except KeyError:
            raise aiohttp.web.HTTPNotFound()

        template = jinja_env.get_template('page.htm')
        body = await template.render_async(title=page.name, segments=page.segments, menu=self.ui_menu_entries,
                                           root_url=self.root_url, js_files=self._js_files, css_files=self._css_files)
        return aiohttp.web.Response(body=body, content_type="text/html", charset='utf-8')

    async def _websocket_handler(self, request: aiohttp.web.Request) -> aiohttp.web.WebSocketResponse:
        ws = aiohttp.web.WebSocketResponse()
        await ws.prepare(request)
        self._websockets.add(ws)

        msg: aiohttp.WSMessage
        try:
            async for msg in ws:
                if msg.type == aiohttp.WSMsgType.TEXT:
                    await self._websocket_dispatch(ws, msg)
                elif msg.type == aiohttp.WSMsgType.ERROR:
                    logger.info('ws connection closed with exception %s', ws.exception())
        finally:
            logger.debug('websocket connection closed')
            # Make sure the websocket is removed as a subscriber from all WebDisplayDatapoints
            self._websockets.discard(ws)
            for connector in self.connectors.values():
                if isinstance(connector, WebDisplayDatapoint):
                    await connector.websocket_close(ws)
            return ws

    async def _websocket_dispatch(self, ws: aiohttp.web.WebSocketResponse, msg: aiohttp.WSMessage) -> None:
        message = msg.json()
        try:
            connector = self.connectors[message["id"]]
        except KeyError:
            logger.error("Could not route message from websocket to connector, since no connector with id %s is "
                         "known.", message['id'])
            return
        if 'v' in message:
            await connector.from_websocket(message['v'], ws)
        elif 'sub' in message:
            await connector.websocket_subscribe(ws)
        else:
            logger.warning("Don't know how to handle websocket message: %s", message)

    def serve_static_file(self, path: os.PathLike) -> str:
        # TODO
        pass

    def add_js_file(self, path: os.PathLike) -> None:
        # TODO file is added only once
        self._js_files.append(self.serve_static_file(path))

    def add_css_file(self, path: os.PathLike) -> None:
        # TODO file is added only once
        self._css_files.append(self.serve_static_file(path))


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
