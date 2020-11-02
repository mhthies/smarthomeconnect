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
import json
import datetime
import logging
from typing import Type, Generic, List, Any, Optional, Set

import aiohttp.web

from ..base import T, Readable, Writable, UninitializedError
from ..conversion import SHCJsonEncoder
from ..web import WebUIConnector

logger = logging.getLogger(__name__)


class PersistenceVariable(Readable[T], Writable[T], Generic[T], metaclass=abc.ABCMeta):
    def __init__(self, type_: Type[T], log: bool):
        self.type = type_
        super().__init__()
        self.log = log
        self.subscribed_web_ui_views: List[LoggingWebUIView] = []

    @abc.abstractmethod
    async def _read_from_log(self) -> Optional[T]:
        pass

    @abc.abstractmethod
    async def _write_to_log(self, value: T) -> None:
        pass

    @abc.abstractmethod
    async def retrieve_log(self, start_time: datetime.datetime, end_time: datetime.datetime, num: Optional[int] = None,
                           offset: int = 0) -> List[T]:
        pass

    async def read(self) -> T:
        value = await self._read_from_log()
        if value is None:
            raise UninitializedError("No value for has been persisted for variable '{}' yet.".format(self))
        return value

    async def _write(self, value: T, origin: List[Any]):
        logger.debug("%s value %s for %s to log backend", "logging" if self.log else "updating", value, self)
        await self._write_to_log(value)
        for web_ui_view in self.subscribed_web_ui_views:
            await web_ui_view.new_value(datetime.datetime.now(), value)


class LoggingWebUIView(WebUIConnector):
    """
    A WebUIConnector which is used to retrieve a log/timeseries of a certain log variable for a certain time
    interval via the Webinterface UI websocket and subscribe to updates of that log variable.
    """
    def __init__(self, variable: PersistenceVariable, interval: datetime.timedelta):
        # TODO extend with value conversion
        # TODO extend for past interval
        # TODO extend for aggregation
        if not variable.log:
            raise ValueError("Cannot use a PersistenceVariable with log=False for a web logging web ui widget")
        super().__init__()
        self.variable = variable
        variable.subscribed_web_ui_views.append(self)
        self.interval = interval
        self.subscribed_websockets: Set[aiohttp.web.WebSocketResponse] = set()

    async def new_value(self, timestamp: datetime.datetime, value: Any) -> None:
        """
        Coroutine to be called by the class:`PersistenceVariable` this view belongs to, when it receives and logs a new
        value, so the value can instantly be plotted by all subscribed web clients.

        :param timestamp: Exact timestamp of the new value
        :param value: The new value
        """
        await self._websocket_publish([timestamp, value])

    async def _websocket_before_subscribe(self, ws: aiohttp.web.WebSocketResponse) -> None:
        # TODO use pagination
        # TODO somehow handle reconnects properly
        data = await self.variable.retrieve_log(datetime.datetime.now() - self.interval,
                                                datetime.datetime.now() + datetime.timedelta(seconds=5))
        await ws.send_str(json.dumps({'id': id(self),
                                      'v': data},
                                     cls=SHCJsonEncoder))
