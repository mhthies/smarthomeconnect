import abc
import asyncio
import itertools
import json
import logging
import os
from typing import Dict, Iterable, Union, List, Set, Any

import aiohttp.web

from ..base import Reading, T, Writable, Subscribable
from ..conversion import SHCJsonEncoder, from_json
from ..supervisor import register_interface

logger = logging.getLogger(__name__)


class WebServer:
    def __init__(self, host: str, port: int, index_name: str):
        self.host = host
        self.port = port
        self.index_name = index_name
        self._pages: Dict[str, WebPage] = {}
        self.display_datapoints: Dict[int, WebDisplayDatapoint] = {}
        self.action_datapoints: Dict[int, WebActionDatapoint] = {}
        self._app = aiohttp.web.Application()
        self._app.add_routes([
            aiohttp.web.get("/", self._index_handler),
            aiohttp.web.get("/page/{name}/", self._page_handler),
            aiohttp.web.get("/ws", self._websocket_handler),
            aiohttp.web.static('/static', os.path.join(os.path.dirname(__file__), 'static')),
        ])
        self.run_task: asyncio.Task
        register_interface(self)
        # TODO add datapoint API

        # TODO allow registering HTTP APIs
        # TODO allow registering websocket APIs
        # TODO allow collecting page elements of certain type

    async def start(self) -> None:
        logger.info("Starting up web server on %s:%s ...", self.host, self.port)
        for datapoint in itertools.chain.from_iterable(page.get_datapoints() for page in self._pages.values()):
            if isinstance(datapoint, WebDisplayDatapoint):
                self.display_datapoints[id(datapoint)] = datapoint
            if isinstance(datapoint, WebActionDatapoint):
                self.action_datapoints[id(datapoint)] = datapoint
        self._runner = aiohttp.web.AppRunner(self._app)
        await self._runner.setup()
        site = aiohttp.web.TCPSite(self._runner, self.host, self.port)
        self.run_task = asyncio.create_task(site.start())

    async def wait(self) -> None:
        await self.run_task

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
        # Make sure the websocket is removed as a subscriber from all WebDisplayDatapoints
        for datapoint in self.display_datapoints.values():
            if isinstance(datapoint, WebDisplayDatapoint):
                datapoint.ws_unsubscribe(ws)
        return ws

    async def _websocket_dispatch(self, ws: aiohttp.web.WebSocketResponse, msg: aiohttp.WSMessage) -> None:
        data = msg.json()
        # TODO error handling
        action = data["action"]
        if action == 'subscribe':
            await self.display_datapoints[data["id"]].ws_subscribe(ws)
        elif action == 'write':
            await self.action_datapoints[data["id"]].update_from_ws(data["value"], ws)


class WebDatapointContainer(metaclass=abc.ABCMeta):
    @abc.abstractmethod
    def get_datapoints(self) -> Iterable[Union["WebDisplayDatapoint", "WebActionDatapoint"]]:
        pass


class WebPage(WebDatapointContainer):
    def __init__(self, server: WebServer, name: str):
        self.server = server
        self.name = name
        self.items: List[WebPageItem] = []

    def add_item(self, item: "WebPageItem"):
        self.items.append(item)

    def get_datapoints(self) -> Iterable[Union["WebDisplayDatapoint", "WebActionDatapoint"]]:
        return itertools.chain.from_iterable(item.get_datapoints() for item in self.items)

    async def generate(self, request: aiohttp.web.Request) -> aiohttp.web.Response:
        # TODO use Jinja2 template
        body = "<!DOCTYPE html><html><head><script src=\"/static/main.js\"></script></head><body>\n"\
               + "\n".join(item.render() for item in self.items)\
               + "\n</body></html>"
        return aiohttp.web.Response(body=body, content_type="text/html", charset='utf-8')


class WebPageItem(WebDatapointContainer, metaclass=abc.ABCMeta):
    @abc.abstractmethod
    def render(self) -> str:
        pass


class WebDisplayDatapoint(Reading[T], Writable[T], metaclass=abc.ABCMeta):
    is_reading_optional = False

    def __init__(self):
        super().__init__()
        self.subscribed_websockets: Set[aiohttp.web.WebSocketResponse] = set()

    async def _write(self, value: T, source: List[Any]):
        await self._publish_to_ws(self.convert_to_ws_value(value))

    async def _publish_to_ws(self, value):
        logger.debug("Publishing value %s for %s for %s subscribed websockets ...",
                     value, id(self), len(self.subscribed_websockets))
        data = json.dumps({'id': id(self), 'value': value}, cls=SHCJsonEncoder)
        await asyncio.gather(*(ws.send_str(data) for ws in self.subscribed_websockets))

    def convert_to_ws_value(self, value: T) -> Any:
        return value

    async def ws_subscribe(self, ws):
        if self._default_provider is None:
            logger.error("Cannot handle websocket subscription for %s, since not read provider is registered.", self)
            return
        logger.debug("New websocket subscription for widget id %s.", id(self))
        self.subscribed_websockets.add(ws)
        current_value = await self._from_provider()
        if current_value is not None:
            data = json.dumps({'id': id(self),
                               'value': self.convert_to_ws_value(current_value)},
                              cls=SHCJsonEncoder)
            await ws.send_str(data)

    def ws_unsubscribe(self, ws):
        logger.debug("Unsubscribing websocket from %s.", self)
        self.subscribed_websockets.discard(ws)

    def __repr__(self):
        return "{}<id={}>".format(self.__class__.__name__, id(self))


class WebActionDatapoint(Subscribable[T], metaclass=abc.ABCMeta):
    def convert_from_ws_value(self, value: Any) -> T:
        return from_json(self.type, value)

    async def update_from_ws(self, value: Any, ws: aiohttp.web.WebSocketResponse) -> None:
        await self._publish(self.convert_from_ws_value(value), [ws])
        if isinstance(self, WebDisplayDatapoint):
            await self._publish_to_ws(value)