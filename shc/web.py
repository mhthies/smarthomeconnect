import abc
import asyncio
import json
import logging
import os
from typing import List, Dict, Any, Type, Set

import aiohttp.web

from .base import Subscribable, Writable, Reading, T
from .supervisor import register_interface

logger = logging.getLogger(__name__)


class WebServer:
    def __init__(self, host: str, port: int, index_name: str):
        self.host = host
        self.port = port
        self.index_name = index_name
        self._pages: Dict[str, WebPage] = {}
        self.widgets: Dict[int, WebWidget] = {}
        self._app = aiohttp.web.Application()
        self._app.add_routes([
            aiohttp.web.get("/", self._index_handler),
            aiohttp.web.get("/page/{name}/", self._page_handler),
            aiohttp.web.get("/ws", self._websocket_handler),
            aiohttp.web.static('/static', os.path.join(os.path.dirname(__file__), 'web_static')),
        ])
        register_interface(self)

    async def run(self) -> None:
        logger.info("Starting up web server on %s:%s ...", self.host, self.port)
        self._runner = aiohttp.web.AppRunner(self._app)
        await self._runner.setup()
        site = aiohttp.web.TCPSite(self._runner, self.host, self.port)
        await site.start()

    async def stop(self) -> None:
        logger.info("Cleaning up AppRunner ...")
        await self._runner.cleanup()

    def page(self, name: str) -> "WebPage":
        if name in self._pages:
            return self._pages[name]
        else:
            page = WebPage(self, name)
            self._pages[name] = page
            return page

    async def _index_handler(self, request: aiohttp.web.Request) -> aiohttp.web.Response:
        raise aiohttp.web.HTTPFound("/page/{}/".format(self.index_name))

    async def _page_handler(self, request: aiohttp.web.Request) -> aiohttp.web.Response:
        try:
            page = self._pages[request.match_info['name']]
        except KeyError:
            raise aiohttp.web.HTTPNotFound()
        return await page.generate(request)

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
        for widget in self.widgets.values():
            widget.ws_unsubscribe(ws)
        return ws

    async def _websocket_dispatch(self, ws: aiohttp.web.WebSocketResponse, msg: aiohttp.WSMessage) -> None:
        data = msg.json()
        # TODO error handling
        action = data["action"]
        if action == 'subscribe':
            await self.widgets[data["id"]].ws_subscribe(ws)
        elif action == 'write':
            await self.widgets[data["id"]].write(data["value"], [ws])


class WebPage:
    def __init__(self, server: WebServer, name: str):
        self.server = server
        self.name = name
        self.items: List[WebItem] = []

    def add_item(self, item: "WebItem"):
        self.items.append(item)
        self.server.widgets.update({id(widget): widget for widget in item.widgets})

    async def generate(self, request: aiohttp.web.Request) -> aiohttp.web.Response:
        # TODO use Jinja2 template
        body = "<!DOCTYPE html><html><head><script src=\"/static/main.js\"></script></head><body>\n"\
               + "\n".join(item.render() for item in self.items)\
               + "\n</body></html>"
        return aiohttp.web.Response(body=body, content_type="text/html", charset='utf-8')


class WebItem(metaclass=abc.ABCMeta):
    widgets: List["WebWidget"] = []

    @abc.abstractmethod
    def render(self) -> str:
        pass


class WebWidget(Reading[T], Writable[T], Subscribable[T], metaclass=abc.ABCMeta):
    def __init__(self, type_: Type[T]):
        self.type = type_
        super().__init__()
        self.subscribed_websockets: Set[aiohttp.web.WebSocketResponse] = set()

    async def write(self, value: T, source: List[Any]):
        data = json.dumps({'id': id(self),
                           'value': value})
        logger.debug("New value %s for widget id %s from %s. Publishing to %s subscribed websockets ...",
                     value, id(self), source, len(self.subscribed_websockets))
        await self._publish(value, source)
        await asyncio.gather(*(ws.send_str(data) for ws in self.subscribed_websockets))

    async def ws_subscribe(self, ws):
        logger.debug("New websocket subscription for widget id %s.", id(self))
        self.subscribed_websockets.add(ws)
        data = json.dumps({'id': id(self),
                           'value': await self._from_provider()})
        await ws.send_str(data)

    def ws_unsubscribe(self, ws):
        logger.debug("Unsubscribing websocket from widget id %s.", id(self))
        self.subscribed_websockets.discard(ws)

    # TODO add connect() method


class Switch(WebWidget, WebItem):
    def __init__(self, label: str):
        super().__init__(bool)
        self.label = label
        self.widgets = [self]

    def render(self) -> str:
        # TODO use Jinja2 templates
        return "<div><input type=\"checkbox\" data-widget=\"switch\" data-id=\"{id}\" /> {label}</div>"\
            .format(label=self.label, id=id(self))
