# Copyright 2020-2021 Michael Thies <mail@mhthies.de>
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
import pathlib
import weakref
from json import JSONDecodeError
from typing import Dict, Iterable, Union, List, Set, Any, Optional, Tuple, Generic, Type, Callable

import aiohttp.web
import jinja2
from aiohttp import WSCloseCode

from ..base import Reading, T, Writable, Subscribable
from ..conversion import SHCJsonEncoder, from_json
from ..supervisor import get_interfaces, AbstractInterface, ServiceStatus

logger = logging.getLogger(__name__)

jinja_env = jinja2.Environment(
    loader=jinja2.PackageLoader('shc.web', 'templates'),
    autoescape=jinja2.select_autoescape(['html', 'xml']),
    enable_async=True,
    trim_blocks=True,
    lstrip_blocks=True,
)
jinja_env.filters['id'] = id

LastWillT = Tuple["WebApiObject[T]", T]


class WebServer(AbstractInterface):
    """
    A SHC interface to provide the web user interface and a REST+websocket API for interacting with Connectable objects.

    :param host: The listening host. Use "" to listen on all interfaces or "localhost" to listen only on the
        loopback interface.
    :param port: The port to listen on
    :param index_name: Name of the `WebPage`, the root URL redirects to. If None, the root URL returns an HTTP 404.
    :param root_url: The base URL, at witch the user will reach this server. Used to construct internal links. May
        be an absolute URI (like "https://myhost:8080/shc") or an absolute-path reference (like "/shc"). Defaults
        to "". Note: This does not affect the routes of this HTTP server. It is only relevant, if you use an HTTP
        reverse proxy in front of this application, which serves the application in a sub path.
    :param title_formatter: A format string or format function to create the full HTML title, typically shown as browser
        tab title, from a web page's title. If it is a string, it should have one positional format placeholder
        (``{}``)
    :param enable_monitoring: If True (default), the monitoring endpoint at `/monitoring` is enabled to allow monitoring
        the interfaces' status in the UI or from a monitoring system
    """
    def __init__(self, host: str, port: int, index_name: Optional[str] = None, root_url: str = "",
                 title_formatter: Union[str, Callable[[str], str]] = "{} | SHC", enable_monitoring: bool = True):
        super().__init__()
        self.host = host
        self.port = port
        self.index_name = index_name
        self.root_url = root_url
        self.title_formatter = (title_formatter
                                if callable(title_formatter)
                                else lambda x: title_formatter.format(x))  # type: ignore

        # a dict of all `WebPage`s by their `name` for rendering them in the `_page_handler`
        self._pages: Dict[str, WebPage] = {}
        # a dict of all `WebConnector`s by their Python object id for routing incoming websocket mesages
        self.connectors: Dict[int, WebUIConnector] = {}
        # a dict of all `WebApiObject`s by their name for handling incoming HTTP requests and subscribe messages
        self._api_objects: Dict[str, WebApiObject] = {}
        # a set of all open websockets to close on graceful shutdown
        self._websockets: weakref.WeakSet[aiohttp.web.WebSocketResponse] = weakref.WeakSet()
        # a set of all open tasks to close on graceful shutdown
        self._associated_tasks: weakref.WeakSet[asyncio.Task] = weakref.WeakSet()
        # last will (object, value) per API websocket client (if set)
        self._api_ws_last_will: Dict[aiohttp.web.WebSocketResponse, LastWillT] = {}
        # data structure of the user interface's main menu
        # The structure looks as follows:
        # [('Label', 'icon', 'page_name'),
        #  ('Submenu label', None, [
        #     ('Label 2', 'icon', 'page_name2'), ...
        #   ]),
        #  ...]
        self.ui_menu_entries: List[Tuple[str, Optional[str], Union[str, List[Tuple[str, Optional[str], str]]]]] = []
        # List of all static js URLs to be included in the user interface pages
        self._js_files = [
            "/static/pack/main.js",
        ]
        # List of all static css URLs to be included in the user interface pages
        self._css_files = [
            "/static/pack/main.css",
        ]
        # A dict of all static files served by the application. Used to make sure, any of those is only served at one
        # path, when added via `serve_static_file()` multiple times.
        self.static_files: Dict[pathlib.Path, str] = {}

        # The actual aiohttp web app
        self._app = aiohttp.web.Application()
        self._app.add_routes([
            aiohttp.web.get("/", self._index_handler),
            aiohttp.web.get("/page/{name}/", self._page_handler, name='show_page'),
            aiohttp.web.get("/ws", self._ui_websocket_handler),
            aiohttp.web.static('/static', os.path.join(os.path.dirname(__file__), 'static')),
            aiohttp.web.get("/api/v1/ws", self._api_websocket_handler),
            aiohttp.web.get("/api/v1/object/{name}", self._api_get_handler),
            aiohttp.web.post("/api/v1/object/{name}", self._api_post_handler),
        ])
        if enable_monitoring:
            self._app.add_routes([aiohttp.web.get("/monitoring", self._monitoring_handler)])

    async def start(self) -> None:
        logger.info("Starting up web server on %s:%s ...", self.host, self.port)
        for connector in itertools.chain.from_iterable(page.get_connectors() for page in self._pages.values()):
            self.connectors[id(connector)] = connector
        for api_object in self._api_objects.values():
            api_object.start()
        self._runner = aiohttp.web.AppRunner(self._app)
        await self._runner.setup()
        site = aiohttp.web.TCPSite(self._runner, self.host, self.port)
        await site.start()

    async def stop(self) -> None:
        logger.info("Closing open websockets ...")
        for ws in set(self._websockets):
            await ws.close(code=WSCloseCode.GOING_AWAY, message=b'Server shutdown')
        for task in set(self._associated_tasks):
            task.cancel()
        logger.info("Cleaning up AppRunner ...")
        await self._runner.cleanup()

    def page(self, name: str, title: Optional[str] = None, menu_entry: Union[bool, str] = False,
             menu_icon: Optional[str] = None, menu_sub_label: Optional[str] = None, menu_sub_icon: Optional[str] = None
             ) -> "WebPage":
        """
        Create a new WebPage with a given name.

        If there is already a page with that name existing, it will be returned.

        :param name: The `name` of the page, which is used in the page's URL to identify it.
        :param title: The title/heading of the page. If not given, the name is used.
        :param menu_entry: If True (or a none-empty string) and this is a new page, an entry in the main menu will be
            created for the page. If `menu_entry` is a string, it will be used as the label, otherwise, the title will
            be used as a label.
        :param menu_icon: If given, the menu entry is prepended with the named icon
        :param menu_sub_label: If given, the menu entry is labeled with `menu_sub_label` and added to a submenu, labeled
            with `menu_entry` (and `menu_icon`, if given).
        :param menu_sub_icon: If given and `menu_sub_label` is given, the named icon is prepended to the submenu entry.
        :return: The new WebPage object or the existing WebPage object with that name
        :raises ValueError: If `menu_entry` is not False and there is already a menu entry with the same label (or a
            submenu entry with the same two labels)
        """
        if name in self._pages:
            return self._pages[name]
        else:
            if not title:
                title = name
            page = WebPage(self, name, title)
            self._pages[name] = page
            if menu_entry:
                self.add_menu_entry(name,
                                    menu_entry if isinstance(menu_entry, str) else title,
                                    menu_icon, menu_sub_label, menu_sub_icon)
            return page

    def add_menu_entry(self, page_name: str, label: str, icon: Optional[str] = None, sub_label: Optional[str] = None,
                       sub_icon: Optional[str] = None) -> None:
        """
        Create an entry for a named web UI page in the web UI's main navigation menu.

        The existence of the page is not checked, so menu entries can be created before the page has been created.

        :param page_name: The name of the page (link target)
        :param label: The label of the entry (or the submenu to place the entry in) in the main menu
        :param icon: If given, the menu entry is prepended with the named icon
        :param sub_label: If given, the menu entry is labeled with `sub_label` and added to a submenu, labeled with
            `label` (and `icon`, if given).
        :param sub_icon: If given and `menu_sub_label` is given, the named icon is prepended to the submenu entry.
        :raises ValueError: If there is already a menu entry with the same label (or a submenu entry with the same two
            labels)
        """
        existing_entry = next((e for e in self.ui_menu_entries if e[0] == label), None)
        if not sub_label:
            if existing_entry:
                raise ValueError("UI main menu entry with label {} exists already. Contents: {}"
                                 .format(label, existing_entry[2]))
            self.ui_menu_entries.append((label, icon, page_name))

        elif existing_entry:
            if not isinstance(existing_entry[2], list):
                raise ValueError("Existing UI main menu entry with label {} is not a submenu but a link to page {}"
                                 .format(label, existing_entry[2]))
            existing_entry[2].append((sub_label, sub_icon, page_name))

        else:
            self.ui_menu_entries.append((label, icon, [(sub_label, sub_icon, page_name)]))

    def api(self, type_: Type, name: str) -> "WebApiObject":
        """
        Create a new API endpoint with a given name and type.

        :param type_: The value type of the API endpoint object. Used as the *Connectable* object's `type` attribute and
            for JSON-decoding/encoding the values transmitted via the API.
        :param name: The name of the API object, which is the distinguishing part of the REST-API endpoint URL and used
            to identify the object in the websocket API.
        :return: A *Connectable* object that represents the API endpoint.
        """
        if name in self._api_objects:
            existing = self._api_objects[name]
            if existing.type is not type_:
                raise TypeError("Type {} does not match type {} of existing API object with same name"
                                .format(type_, existing.type))
            return existing
        else:
            api_object = WebApiObject(type_, name)
            self._api_objects[name] = api_object
            return api_object

    async def _index_handler(self, _request: aiohttp.web.Request) -> aiohttp.web.Response:
        if not self.index_name:
            raise aiohttp.web.HTTPNotFound()
        raise aiohttp.web.HTTPFound(self.root_url + str(self._app.router['show_page'].url_for(name=self.index_name)))

    async def _page_handler(self, request: aiohttp.web.Request) -> aiohttp.web.Response:
        try:
            page = self._pages[request.match_info['name']]
        except KeyError:
            raise aiohttp.web.HTTPNotFound()

        html_title = self.title_formatter(page.title)
        template = jinja_env.get_template('page.htm')
        body = await template.render_async(title=page.title, segments=page.segments, menu=self.ui_menu_entries,
                                           root_url=self.root_url, js_files=self._js_files, css_files=self._css_files,
                                           server_token=id(self), html_title=html_title)
        return aiohttp.web.Response(body=body, content_type="text/html", charset='utf-8')

    async def _ui_websocket_handler(self, request: aiohttp.web.Request) -> aiohttp.web.WebSocketResponse:
        ws = aiohttp.web.WebSocketResponse()
        await ws.prepare(request)
        self._websockets.add(ws)

        msg: aiohttp.WSMessage
        try:
            async for msg in ws:
                if msg.type == aiohttp.WSMsgType.TEXT:
                    await self._ui_websocket_dispatch(ws, msg)
                elif msg.type == aiohttp.WSMsgType.ERROR:
                    logger.info('UI websocket connection closed with exception %s', ws.exception())
        finally:
            logger.debug('UI websocket connection closed')
            # Make sure the websocket is removed as a subscriber from all WebDisplayDatapoints
            self._websockets.discard(ws)
            for connector in self.connectors.values():
                connector.websocket_close(ws)
            return ws

    async def _ui_websocket_dispatch(self, ws: aiohttp.web.WebSocketResponse, msg: aiohttp.WSMessage) -> None:
        message = msg.json()
        if 'serverToken' in message:
            # Detect server restarts (if serverToken of client's page is different from our current server id) and
            # ask client to reload page.
            if message['serverToken'] != id(self):
                logger.debug("Client's serverToken %s does not match our id. Asking for reload.",
                             message['serverToken'])
                asyncio.create_task(ws.send_json({'reload': True}))
            return

        try:
            connector = self.connectors[message["id"]]
        except KeyError:
            logger.error("Could not route message from websocket to connector, since no connector with id %s is "
                         "known.", message['id'])
            return
        if 'v' in message:
            # We don't need to do this in an asynchronous task, since the from_websocket method uses asynchronous
            # publishing
            connector.from_websocket(message['v'], ws)
        elif 'sub' in message:
            asyncio.create_task(connector.websocket_subscribe(ws))
        else:
            logger.warning("Don't know how to handle websocket message: %s", message)

    async def _api_websocket_handler(self, request: aiohttp.web.Request) -> aiohttp.web.WebSocketResponse:
        ws = aiohttp.web.WebSocketResponse()
        await ws.prepare(request)
        self._websockets.add(ws)

        msg: aiohttp.WSMessage
        try:
            async for msg in ws:
                if msg.type == aiohttp.WSMsgType.TEXT:
                    # It does not make sense to avoid the task creation here, since we would have to create a task in
                    # any branch of the _api_websocket_dispatch() to asynchronously do writing to websockets then.
                    asyncio.create_task(self._api_websocket_dispatch(request, ws, msg))
                elif msg.type == aiohttp.WSMsgType.ERROR:
                    logger.info('API websocket connection closed with exception %s', ws.exception())
        finally:
            logger.debug('API websocket connection closed')
            self._websockets.discard(ws)
            for api_object in self._api_objects.values():
                api_object.websocket_close(ws)
            if ws in self._api_ws_last_will:
                obj, value = self._api_ws_last_will.pop(ws)
                await obj.http_post(value, ws)
            return ws

    async def _api_websocket_dispatch(self, request: aiohttp.web.Request, ws: aiohttp.web.WebSocketResponse,
                                      msg: aiohttp.WSMessage) -> None:
        try:
            message = msg.json()
        except JSONDecodeError:
            logger.warning("Websocket API message from %s is not a valid JSON string: %s", request.remote, msg.data)
            await ws.send_json({'status': 400, 'error': "Could not parse message as JSON: {}".format(msg.data)})
            return

        try:
            name = message["name"]
            action = message["action"]
            handle = message.get("handle")
        except KeyError:
            logger.warning("Websocket API message from %s without 'name' or 'action' field: %s", request.remote,
                           message)
            await ws.send_json({'status': 422,
                                'error': "Message does not include a 'name' and an 'action' field"})
            return
        result = {'status': 204,
                  'name': name,
                  'action': action,
                  'handle': handle}
        try:
            obj = self._api_objects[name]
        except KeyError:
            logger.warning("Could not find API object %s, requested by %s", name, request.remote)
            result['status'] = 404
            result['error'] = "There is no API object with name '{}'".format(name)
            await ws.send_json(result)
            return

        try:
            # subscribe action
            if action == "subscribe":
                logger.debug("got websocket subscribe request for API object %s from %s", name, request.remote)
                await obj.websocket_subscribe(ws, handle)
                return

            # post action
            elif action == "post":
                value_exists = False
                try:
                    value = message["value"]
                    value_exists = True
                except KeyError:
                    result['status'] = 422
                    result['error'] = "message does not include a 'value' field"
                    logger.warning("Websocket API POST message from %s without 'value' field: %s", request.remote,
                                   message)
                if value_exists:
                    logger.debug("got post request for API object %s via websocket from %s with value %s",
                                 name, request.remote, value)
                    try:
                        await obj.http_post(value, ws)
                    except (ValueError, TypeError) as e:
                        logger.warning("Error while updating API object %s with value via websocket from %s (error was "
                                       "%s): %s", name, request.remote, e, value)
                        result['status'] = 422
                        result['error'] = "Could not use provided value to update API object: {}".format(e)

            # lastwill action
            elif action == "lastwill":
                value_exists = False
                try:
                    value = message["value"]
                    value_exists = True
                except KeyError:
                    result['status'] = 422
                    result['error'] = "message does not include a 'value' field"
                    logger.warning("Websocket API LASTWILL message from %s without 'value' field: %s", request.remote,
                                   message)
                if value_exists:
                    logger.debug("got LASTWILL request for API object %s via websocket from %s with value %s",
                                 name, request.remote, value)
                    try:
                        self._api_ws_last_will[ws] = (obj, obj._check_last_will(value))
                    except (ValueError, TypeError) as e:
                        logger.warning("Error while setting last will of websocket client %s for API object %s (error"
                                       "was %s): %s", name, request.remote, e, value)
                        result['status'] = 422
                        result['error'] = "Could not use provided value to set last will: {}".format(e)

            # get action
            elif action == "get":
                logger.debug("got get request for API object %s via websocket from %s", name, request.remote)
                value = (await obj.http_get())[1]
                result['status'] = 200 if value is not None else 409
                result['value'] = value

            else:
                logger.warning("Unknown websocket API action '%s', requested by %s", action, request.remote)
                result['status'] = 422
                result['error'] = "Not a valid action: '{}'".format(action)
        except Exception as e:
            logger.error("Error while processing API websocket message from %s: %s", request.remote, message,
                         exc_info=e)
            result['status'] = 500
            result['error'] = "Internal server error while processing message"

        # Finally, send a response
        logger.debug("Sending websocket response: %s", result)
        await ws.send_str(json.dumps(result, cls=SHCJsonEncoder))

    async def _api_get_handler(self, request: aiohttp.web.Request) -> aiohttp.web.Response:
        try:
            api_object = self._api_objects[request.match_info['name']]
        except KeyError:
            name_failsafe = request.match_info.get('name', '<undefined>')
            logger.warning("Could not find API object %s, requested by %s", name_failsafe, request.remote)
            raise aiohttp.web.HTTPNotFound(reason="Could not find API Object with name {}"
                                           .format(name_failsafe))
        # Parse `wait` and `timeout` from request query string
        wait = 'wait' in request.query
        timeout = 30.0
        if wait and request.query['wait']:
            try:
                timeout = float(request.query['wait'])
            except ValueError as e:
                raise aiohttp.web.HTTPBadRequest(reason="Could not parse 'wait' query parameter's value as float: {}"
                                                 .format(e))

        # if `wait`: Make this Request gracefully stoppable on shutdown by registering it for
        if wait:
            current_task = asyncio.current_task()
            assert(current_task is not None)
            self._associated_tasks.add(current_task)

        # Now, let's actually call http_get of the API object
        # If `wait`, this will await a new value or the `timeout`.
        changed, value, etag = await api_object.http_get(wait, timeout, request.headers.get('If-None-Match'))

        # If not changed (either when `wait` and timeout is reached) or if not `wait` and `If-None-Match` indicates
        # unchanged value, return HTTP 304 Not Modified
        if not changed:
            raise aiohttp.web.HTTPNotModified(headers={'ETag': etag})
        else:
            return aiohttp.web.Response(status=200 if value is not None else 409,
                                        headers={'ETag': etag},
                                        body=json.dumps(value, cls=SHCJsonEncoder),
                                        content_type="application/json",
                                        charset='utf-8')

    async def _api_post_handler(self, request: aiohttp.web.Request) -> aiohttp.web.Response:
        text = await request.text()
        try:
            data = json.loads(text)
        except JSONDecodeError as e:
            logger.warning("Invalid JSON body POSTed from %s to %s (error was: %s): %s",
                           request.remote, request.url, e, text)
            raise aiohttp.web.HTTPBadRequest(reason="Could not parse request body as json: {}".format(str(e)))

        try:
            name = request.match_info['name']
            api_object = self._api_objects[name]
        except KeyError:
            name_failsafe = request.match_info.get('name', '<undefined>')
            logger.warning("Could not find API object %s, requested by %s", name_failsafe, request.remote)
            raise aiohttp.web.HTTPNotFound(reason="Could not find API Object with name {}"
                                           .format(name_failsafe))
        try:
            await api_object.http_post(data, request)
        except (ValueError, TypeError) as e:
            logger.warning("Error while updating API object %s with value from %s (error was %s): %s", name,
                           request.remote, e, data)
            raise aiohttp.web.HTTPUnprocessableEntity(reason="Could not use provided value to update API object: {}"
                                                      .format(e))
        raise aiohttp.web.HTTPNoContent()

    async def _monitoring_handler(self, request: aiohttp.web.Request) -> aiohttp.web.Response:
        accept_map = {'text/*': 'text/plain',
                      'application/*': 'application/json',
                      '*/*': 'application/json',
                      'text/html': 'text/html',
                      'application/json': 'application/json',
                      }
        accept_list = request.headers.get("Accept", "application/json").split(",")
        content_type: Optional[str] = None
        for mime_type in accept_list:
            mime_type = mime_type.strip().split(";")[0]
            if mime_type in accept_map:
                content_type = accept_map[mime_type]
                break
        if content_type is None:
            raise aiohttp.web.HTTPNotAcceptable()

        # Fetch interface data
        interfaces_data = {}
        overall_status = 0
        for iface in get_interfaces():
            status = await iface.get_status()
            interfaces_data[repr(iface)] = {
                'status': status.status.value,
                'message': status.message,
                'indicators': status.indicators,
            }
            overall_status = max(overall_status, min(status.status.value, 2) - 2 + iface.criticality.value)

        # Calculate HTTP status code
        http_status = {0: 200,
                       1: 213,
                       2: 513}.get(overall_status, 500)

        if content_type == "application/json":
            data = {
                'status': overall_status,
                'interfaces': interfaces_data,
            }
            body = json.dumps(data)
        elif content_type == "text/html":
            template = jinja_env.get_template('status.htm')
            body = await template.render_async(overall_status=overall_status, interfaces_data=interfaces_data,
                                               ServiceStatus=ServiceStatus, menu=self.ui_menu_entries,
                                               root_url=self.root_url, js_files=self._js_files,
                                               css_files=self._css_files, server_token=id(self),
                                               html_title="Status Monitoring")
        return aiohttp.web.Response(status=http_status,
                                    body=body,
                                    content_type=content_type,
                                    charset='utf-8')

    def serve_static_file(self, path: pathlib.Path) -> str:
        """
        Register a static file to be served on this HTTP server.

        The URL is automatically chosen, based on the file's name and existing static files.
        If the same path has already been added as a static file, its existing static URL is returned instead of
        creating a new one.

        This method should primarily be used by WebPageItem implementations within their
        :meth:`WebPageItem.register_with_server` method. It is meant for serving configuration-specific images etc.

        :param path: The path of the local file to be served as a static file
        :return: The URL of the static file, including the server's root_url, such that it is represented an absolute
            URL or absolute-path reference (relative to the HTTP server root), which can be used in <img>, <link> tags,
            etc.
        """
        path = path.absolute()
        if path in self.static_files:
            return f"{self.root_url}/addon/{self.static_files[path]}"

        final_file_name = path.name
        i = 0
        while final_file_name in self.static_files.values():
            final_file_name = "{}_{:04d}.{}".format(path.stem, i, path.suffix)
        self.static_files[path] = final_file_name
        final_url = '/addon/{}'.format(final_file_name)

        # Unfortunately, aiohttp.web.static can only serve directories. We want to serve a single file here.
        async def send_file(_request):
            return aiohttp.web.FileResponse(path)
        self._app.add_routes([aiohttp.web.get(final_url, send_file)])

        return self.root_url + final_url

    def add_static_directory(self, path: pathlib.Path, js_files: Iterable[str] = (), css_files: Iterable[str] = ()
                             ) -> str:
        """
        Register an additional directory of static files served by this server, optionally with a list of JavaScript and
        CSS files to be loaded in each page's HTML head.

        This method adds the given path as a static directory to be served by this webserver. The root URL of the served
        directory is automatically determined, based on the file's name and existing static files. If the same path has
        already been added as a static file, its existing static URL is returned instead of creating a new one.

        The given `js_files` and `css_files` are interpreted as relative URL references of files within the directory,
        that will be served by the HTTP server at the directory's root URL + this path. Make sure to use '/' as path
        separator and URL-encode these strings if necessary.

        :param path: Local filesystem path of directory to be served
        :param js_files: list of relative URLs within the directory to be included as Javascript files into UI pages
        :param css_files: list of relative URLs within the directory to be included as CSS files into UI pages
        :return: The HTTP root URL where the directory is served, including the server's root_url, such that it is
            represented an absolute URL or absolute-path reference (relative to the HTTP server root)
        """
        path = path.absolute()
        if path in self.static_files:
            final_url = '/addon/{}'.format(self.static_files[path])
        else:
            final_file_name = path.name
            i = 0
            while final_file_name in self.static_files.values():
                final_file_name = "{}_{:04d}.{}".format(path.stem, i, path.suffix)

            self.static_files[path] = final_file_name
            final_url = '/addon/{}'.format(final_file_name)

            self._app.add_routes([aiohttp.web.static(final_url, path)])

        self._css_files.extend((f"{final_url}/{file}" for file in css_files))
        self._js_files.extend((f"{final_url}/{file}" for file in js_files))

        return f"{self.root_url}{final_url}/"

    def __repr__(self) -> str:
        return "{}(host={}, port={})".format(self.__class__.__name__, self.host, self.port)


class WebConnectorContainer(metaclass=abc.ABCMeta):
    @abc.abstractmethod
    def get_connectors(self) -> Iterable["WebUIConnector"]:
        pass


class WebPage(WebConnectorContainer):
    """
    Programmatic representation of a web UI page.

    To create a new page or get an existing page by name, use the :meth:`WebServer.page` method of the target web
    interface.
    """
    def __init__(self, server: WebServer, name: str, title: str):
        self.server = server
        self.name = name
        self.title = title
        self.segments: List["_WebPageSegment"] = []

    def add_item(self, item: "WebPageItem") -> None:
        """
        Add a new `WebPageItem` (widget) to the page.

        The item is appended to the current segment (see :meth:`new_segment`). If the page does not have any segments
        yet, a first segment is created with the default parameters (half-width, no heading) to contain the item.

        :param item: The `WebPageItem` to be added to this page
        """
        if not self.segments:
            self.new_segment()
        self.segments[-1].items.append(item)
        item.register_with_server(self, self.server)

    def get_connectors(self) -> Iterable["WebUIConnector"]:
        return itertools.chain.from_iterable(item.get_connectors() for item in self.segments)

    def new_segment(self, title: Optional[str] = None, same_column: bool = False, full_width: bool = False) -> None:
        """
        Create a new visual segment on the page, to contain further `WebPageItems`, optionally with a heading.

        :param title: A title for the segment, which is shown as a heading above the segment
        :param same_column: If True, the segment is added below the previous segment, in the same column (left or
            right). Otherwise, by default, the other column is used, which creates a new row, if the previous segment
            is in the right column. This option has no effect, when used for the first segment of a page.
        :param full_width: If True, the segment spans the full width of the page layout on large screens (1127px at
            maximum), instead of using only one of the two columns. In this case, the `same_column` parameter has no
            effect.
        """
        self.segments.append(_WebPageSegment(title, same_column, full_width))


class _WebPageSegment(WebConnectorContainer):
    def __init__(self, title: Optional[str], same_column: bool, full_width: bool):
        self.title = title
        self.same_column = same_column
        self.full_width = full_width
        self.items: List[WebPageItem] = []

    def get_connectors(self) -> Iterable[Union["WebUIConnector"]]:
        return itertools.chain.from_iterable(item.get_connectors() for item in self.items)


class WebPageItem(WebConnectorContainer, metaclass=abc.ABCMeta):
    """
    Abstract base class for all web UI widgets which can be added to a web UI page.
    """
    def register_with_server(self, page: WebPage, server: WebServer) -> None:
        """
        Called when the WebPageItem is added to a WebPage.

        It may be overidden by inheriting classes to get certain information about the WebPage or the WebServer or
        register required static files with the WebServer, using :meth:`WebServer.serve_static_file`,
        :meth:`WebServer.add_js_file`, :meth:`WebServer.serve_static_file`.

        :param page: The WebPage, this WebPageItem is added to.
        :param server: The WebServer, the WebPage (and thus, from now on, this WebPageItem) belongs to.
        """
        pass

    @abc.abstractmethod
    async def render(self) -> str:
        """
        Generate the HTML code of this `WebPageItem`.

        This coroutine is called as part of the rendering of the `WebPage`, the `WebPageItem` has been added to. It must
        be overriden by inheriting classes to return HTML code of the specific widget class to be inserted into the
        pages HTML code. To create interactive widgets, the HTML code should contain tags with `data-widget` and
        `data-id` attributes.

        :return: The HTML code of the specific `WebPageItem`
        """
        pass


class WebUIConnector(WebConnectorContainer, metaclass=abc.ABCMeta):
    """
    An abstract base class for all objects that want to exchange messages with JavaScript UI Widgets via the websocket
    connection.

    For every Message received from a client websocket, the :meth:`from_websocket` method of the appropriate
    `WebUIConnector` is called. For this purpose, the :class:`WebServer` creates a dict of all WebConnectors in any
    registered :class:`WebPage` by their Python object id at startup. The message from the websocket is expected to have
    an `id` field which is used for the lookup.
    """
    def __init__(self):
        self.subscribed_websockets: Set[aiohttp.web.WebSocketResponse] = set()

    def from_websocket(self, value: Any, ws: aiohttp.web.WebSocketResponse) -> None:
        """
        This method is called for incoming "value" messages from a client to this specific `WebUIConnector` object.

        It should be overridden by concrete `WebUIConnector` implementations to handle incoming values.

        :param value: The JSON-decoded 'value' field from the message from the websocket
        :param ws: The websocket connection, the message has been received from.
        """
        pass

    async def websocket_subscribe(self, ws: aiohttp.web.WebSocketResponse) -> None:
        await self._websocket_before_subscribe(ws)
        self.subscribed_websockets.add(ws)

    async def _websocket_before_subscribe(self, ws: aiohttp.web.WebSocketResponse) -> None:
        """
        This method is called by :meth:`websocket_subscribe`, when a new websocket subscribes to this specific
        `WebUIConnector`, *before* the client is added to the `subscribed_websockets` variable.

        It can be overridden to send an initial value or other initialization data to the client.
        """
        pass

    async def _websocket_publish(self, value: Any) -> None:
        """
        Send a value to the to all websocket clients subscribed to this `WebUIConnector` object

        This will trigger a call to the `update()` method of the subscribed JavaScript Widget objects.

        :param value: The value to send to the clients. Must be JSON-serializable using the `SHCJsonEncoder`, i.e. it
            should only include standard JSON types or types which have been registered for JSON conversion via
            :func:`shc.conversion.register_json_conversion`.
        """
        logger.debug("Publishing value %s for %s for %s subscribed websockets ...",
                     value, id(self), len(self.subscribed_websockets))
        data = json.dumps({'id': id(self), 'v': value}, cls=SHCJsonEncoder)
        await asyncio.gather(*(ws.send_str(data) for ws in self.subscribed_websockets))

    def websocket_close(self, ws: aiohttp.web.WebSocketResponse) -> None:
        self.subscribed_websockets.discard(ws)

    def get_connectors(self) -> Iterable["WebUIConnector"]:
        return (self,)

    def __repr__(self):
        return "{}<id={}>".format(self.__class__.__name__, id(self))


class WebDisplayDatapoint(Reading[T], Writable[T], WebUIConnector, metaclass=abc.ABCMeta):
    """
    Abstract base class for `WebUIConnectors` for state-displaying web UI widgets.

    This base class inherits from :class:`WebUIConnector` as well as the *Connectable* base classes :class:`Writable`
    and :class:`Reading`, which allows to *read* and *receive* values from another *Connectable* and forward them over
    the websocket to update a UI widget. This way, widgets reflecting the current value of a *Connectable* object can be
    built.

    This base class may be mixed with :class:`WebActionDatapoint`, creating a `Writable` + `Subscribable` class, to
    build interactive Widgets which display **and** update the connected objects' value.

    As this is a generic *Connectable* class, don't forget to define the :ref:`type attribute <base.typing>`, when
    inheriting from it—either as a class attribute or as an instance attribute, set in the constructor.
    """
    is_reading_optional = False

    async def _write(self, value: T, origin: List[Any]):
        if isinstance(self, WebActionDatapoint):
            self._publish(value, origin)
        await self._websocket_publish(self.convert_to_ws_value(value))

    def convert_to_ws_value(self, value: T) -> Any:
        """
        Callback method to convert new (*received* or *read*) values, before being JSON-encoded and published to the
        websocket clients

        This method may be overridden by inheriting classes to do any transformation of the new value, including type
        conversions. For example, a complex value of the object's *value type* may be used to evaluate a logic
        expression and only send the boolean result to the UI widget.

        Defaults to the identity function (simply returning the new value as is).

        :param value: The new value, as *read* or *received* from another *Connectable* object
        :return: The value to JSON-encoded and published to all subscribed websocket clients. Must be JSON-serializable
            using the `SHCJsonEncoder`, i.e. it should only include standard JSON types or types which have been
            registered for JSON conversion via :func:`shc.conversion.register_json_conversion`.
        """
        return value

    async def _websocket_before_subscribe(self, ws: aiohttp.web.WebSocketResponse) -> None:
        if self._default_provider is None:
            logger.error("Cannot handle websocket subscription for %s, since not read provider is registered.",
                         self)
            return
        logger.debug("New websocket subscription for widget id %s.", id(self))
        self.subscribed_websockets.add(ws)
        current_value = await self._from_provider()
        if current_value is not None:
            data = json.dumps({'id': id(self),
                               'v': self.convert_to_ws_value(current_value)},
                              cls=SHCJsonEncoder)
            await ws.send_str(data)


class WebActionDatapoint(Subscribable[T], WebUIConnector, metaclass=abc.ABCMeta):
    """
    Abstract base class for `WebUIConnectors` for interactive web UI widgets, publishing values to other objects.

    This base class inherits from :class:`WebUIConnector` as well as the *Connectable* base class :class:`Subscribable`,
    which allows it to *publish* values to other *Connectable* objects, when the UI widget sends a websocket message.
    This way, interactive widgets can be built, which publish values when the user interacts with them.

    This base class may be mixed with :class:`WebDisplayDatapoint`, creating a `Writable` + `Subscribable` class, to
    build interactive Widgets which display **and** update the connected objects' value.

    As this is a generic *Connectable* class, don't forget to define the :ref:`type attribute <base.typing>`, when
    inheriting from it—either as a class attribute or as an instance attribute, set in the constructor.
    """
    def __init__(self):
        super().__init__()
        self._stateful_publishing = isinstance(self, WebDisplayDatapoint)

    def convert_from_ws_value(self, value: Any) -> T:
        """
        Callback method to convert/transform values from a websocket client, before *publishing* them.

        This method may be overridden by inheriting classes to do any transformation of the new value, including type
        conversions. For example, a None-value may be transformed to a static value of the object's *value type*.

        Defaults to the identity function (simply returning the value as is).

        :param value: The JSON-decoded value, received from the websocket client
        :return: The value to be *published* to subscribed *Connectable* objects.
        """
        return from_json(self.type, value)

    def from_websocket(self, value: Any, ws: aiohttp.web.WebSocketResponse) -> None:
        value_converted = self.convert_from_ws_value(value)
        self._publish(value_converted, [ws])
        if isinstance(self, WebDisplayDatapoint):
            # from_websocket is awaited in the websocket message processing loop, so we should do all (asynchronously)
            # blocking things in separate tasks.
            asyncio.create_task(self._websocket_publish(self.convert_to_ws_value(value_converted)))


class WebApiObject(Reading[T], Writable[T], Subscribable[T], Generic[T]):
    """
    *Connectable* object that represents an endpoint of the REST/websocket API.

    :ivar name: The name of this object in the REST/websocket API
    """
    is_reading_optional = False
    _stateful_publishing = True

    def __init__(self, type_: Type[T], name: str):
        self.type = type_
        super().__init__()
        self.name = name
        self.subscribed_websockets: Set[aiohttp.web.WebSocketResponse] = set()
        self.future: asyncio.Future[T]

    def start(self) -> None:
        """
        Do some things at startup of the webserver.
        """
        # We do this upon server startup to ensure that the future is bound to the correct AsyncIO event loop.
        # This might not be the case if we create the future in the __init__ method, since the object creation might be
        # done in a different Thread than the SHC main event loop thread (as in our unittests).
        self.future = asyncio.get_event_loop().create_future()

    async def _write(self, value: T, origin: List[Any]) -> None:
        # Asynchronous local feedback publishing. This ensures that conflicting updates, which are currently waiting for
        # local processing by a subscriber can be corrected by resetting this update's origin.
        self._publish(value, origin)
        await self._publish_http(value)

    async def http_post(self, value: Any, origin: Any) -> None:
        self._publish(from_json(self.type, value), [origin])
        await self._publish_http(value, origin)

    def _check_last_will(self, value: Any) -> T:
        """
        Check and convert a value that has been send by an API client as a last will for this object.

        We do this synchronously when the client set its last will, so we can inform it if the value is invalid.

        :param value: The decoded json value from the client
        :return: The converted value to be stored for later use as a last will
        """
        return from_json(self.type, value)

    async def _post_last_will(self, value: T, ws: aiohttp.web.WebSocketResponse) -> None:
        """
        Post the stored last will of a client
        """
        self._publish(from_json(self.type, value), [ws])
        await self._publish_http(value, ws)

    async def _publish_http(self, value: T, skip_websocket: Optional[object] = None) -> None:
        """
        Publish a new value to all subscribed websockets and waiting long-running poll requests.

        :param skip_websocket: If given and a websocket object (:class:`aiohttp.web.WebSocketResponse`) which is
            subscribed to this WebApiObject, this websocket is skipped when publishing the new value. This should be
            used by :meth:`http_post` to prevent reflecting every value posted via the websocket API to its original
            sender.
        """
        self.future.set_result(value)
        self.future = asyncio.get_event_loop().create_future()
        data = json.dumps({'status': 200, 'name': self.name, 'value': value}, cls=SHCJsonEncoder)
        await asyncio.gather(*(ws.send_str(data) for ws in self.subscribed_websockets
                               if ws is not skip_websocket))

    async def websocket_subscribe(self, ws: aiohttp.web.WebSocketResponse, handle: Any) -> None:
        self.subscribed_websockets.add(ws)
        current_value = await self._from_provider()
        if current_value is not None:
            data = {'status': 200, 'action': 'subscribe', 'name': self.name, 'value': current_value, 'handle': handle}
        else:
            data = {'status': 204, 'action': 'subscribe', 'name': self.name, 'handle': handle}
        await ws.send_str(json.dumps(data, cls=SHCJsonEncoder))

    def websocket_close(self, ws: aiohttp.web.WebSocketResponse) -> None:
        self.subscribed_websockets.discard(ws)

    async def http_get(self, wait: bool = False, timeout: float = 30, etag_match: Optional[str] = None
                       ) -> Tuple[bool, Any, str]:
        """
        Get the current value or await a new value.

        This method is used for normal GET requests and long-running polls that only return when a new value is
        awailable.

        :param wait: If True, the method awaits the receiving of a new value or the expiration of the timeout. If False,
            it simply *reads* and returns the current value
        :param timeout: If `wait` is True and no value arrives within `timeout` seconds, this method returns, with the
            first element in the result tuple set to True to indicate the timeout.
        :param etag_match: The `If-None-Match` header value provided by the client. Should be the `etag` from the
            client's last call to this method.
            With `wait=True`: If given and not equal to the id of the current future, this method assumes that the
            client missed a value and falls back to *read* and return the current value immediately. This way, we make
            sure that the client does not miss an update while renewing its poll request.
            With `wait=False`: Normal HTTP behaviour: If the etag does match the current future's is, we return
            with `changed=False`, which should result in an
        :return: A tuple (changed, value, etag).
            `changed` is False, if this method returns due to a timeout or with `wait=False` and an etag indicating an
            unchanged value, or True, if due to a new value. Should be used for the HTTP status code: 200 vs. 304.
            `value` represents the new value (or None when `changed=False`).
            `etag` is the id of the new future. It can be used as the HTML `ETag` header, so the client can send it in
            the `If-None-Match` header of the next request, which is passed to this method's `etag_match` parameter.
        """
        # If not waiting for next value and etag indicates unchanged value: return with `changed=False`
        if not wait and etag_match == str(id(self.future)):
            return False, None, str(id(self.future))
        # If not waiting for next value *or* etag indicates changed value: return current value
        if not wait or (etag_match is not None and etag_match != str(id(self.future))):
            value = await self._from_provider()
            return True, value, str(id(self.future))

        # If waiting for next value: Await future using timeout
        try:
            value = await asyncio.wait_for(asyncio.shield(self.future), timeout=timeout)
            return True, value, str(id(self.future))
        except (asyncio.TimeoutError, asyncio.CancelledError):
            return False, None, str(id(self.future))
