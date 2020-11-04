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
import enum
import json
import datetime
import logging
from typing import Type, Generic, List, Any, Optional, Set, Tuple, Union, cast

import aiohttp.web

from ..base import T, Readable, Writable, UninitializedError
from ..conversion import SHCJsonEncoder
from ..web import WebUIConnector

logger = logging.getLogger(__name__)


class AggregationMethod(enum.Enum):
    AVERAGE = 0
    MINIMUM = 1
    MAXIMUM = 2
    ON_TIME = 3
    ON_TIME_RATIO = 4


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
    async def retrieve_log(self, start_time: datetime.datetime, end_time: datetime.datetime,
                           include_previous: bool = True) -> List[Tuple[datetime.datetime, T]]:
        """
        Retrieve all log entries for this log variable in the specified time range from the log backend/database

        The method shall return a list of all log entries with a timestamp greater or equal to the `start_time` and
        less than the `end_time`. If `include_previous` is True (shall be the default value), the last entry *before*
        the start shall also be included, if there is no entry exactly at the start_time.

        :param start_time: Begin of the time range (inclusive)
        :param end_time: End of the time range (exclusive)
        :param include_previous: If True (the default), the last value *before* `start_time`
        """
        pass

    async def retrieve_aggregated_log(self, start_time: datetime.datetime, end_time: datetime.datetime,
                                      aggregation_method: AggregationMethod, aggregation_interval: datetime.timedelta
                                      ) -> List[Tuple[datetime.datetime, float]]:
        data_raw = await self.retrieve_log(start_time, end_time, include_previous=True)
        aggregation_timestamps = [start_time + i * aggregation_interval
                                  for i in range((end_time - start_time) // aggregation_interval)]

        # The last aggregation_timestamps is not added to the results, but only used to delimit the last aggregation
        # interval.
        if aggregation_timestamps[-1] < end_time:
            aggregation_timestamps.append(end_time)

        result: List[Tuple[datetime.datetime, float]] = []

        if aggregation_method in (AggregationMethod.MINIMUM, AggregationMethod.MAXIMUM):
            if not issubclass(self.type, (int, float)):
                raise TypeError("MINIMUM and MAXIMUM aggregation is only applicable to int and float type log "
                                "variables.")
            fn = {
                AggregationMethod.MINIMUM: min,
                AggregationMethod.MAXIMUM: max
            }[aggregation_method]

            next_aggr_ts_index = 0

            # Get first entry and its timestamp for skipping of empty aggregation intervals and initialization of the
            # first relevant interval
            data = cast(List[Tuple[datetime.datetime, Union[int, float]]], data_raw)
            iterator = iter(data)
            try:
                last_ts, last_value = next(iterator)
            except StopIteration:
                return []

            # Ignore aggregation intervals before the first entry
            while last_ts >= aggregation_timestamps[next_aggr_ts_index]:
                next_aggr_ts_index += 1
                if next_aggr_ts_index >= len(aggregation_timestamps):
                    return []

            aggregated_value = last_value  # type: ignore
            for ts, value in iterator:
                # The timestamp is after the next aggregation interval begin, finalize the current aggregation interval
                # value
                if ts >= aggregation_timestamps[next_aggr_ts_index]:
                    if next_aggr_ts_index > 0:
                        result.append((aggregation_timestamps[next_aggr_ts_index-1], aggregated_value))
                    next_aggr_ts_index += 1
                    if next_aggr_ts_index >= len(aggregation_timestamps):
                        return result

                    aggregated_value = last_value

                    # Fill up aggregation intervals without entries
                    while ts >= aggregation_timestamps[next_aggr_ts_index]:
                        result.append((aggregation_timestamps[next_aggr_ts_index-1], last_value))
                        next_aggr_ts_index += 1
                        if next_aggr_ts_index >= len(aggregation_timestamps):
                            return result

                last_value = value
                aggregated_value = fn(aggregated_value, value)

            if next_aggr_ts_index > 0:
                result.append((aggregation_timestamps[next_aggr_ts_index - 1], aggregated_value))
            return result

        elif aggregation_method == AggregationMethod.AVERAGE:
            if not issubclass(self.type, (int, float)):
                raise TypeError("AVERAGE aggregation is only applicable to int and float type log variables.")
            next_aggr_ts_index = 0
            # Get first entry and its timestamp for skipping of empty aggregation intervals and initialization of the
            # first relevant interval
            data = cast(List[Tuple[datetime.datetime, Union[int, float]]], data_raw)
            iterator = iter(data)
            try:
                last_ts, last_value = next(iterator)
            except StopIteration:
                return []

            # Ignore aggregation intervals before the first entry
            while last_ts >= aggregation_timestamps[next_aggr_ts_index]:
                next_aggr_ts_index += 1
                if next_aggr_ts_index >= len(aggregation_timestamps):
                    return []

            value_sum = 0.0
            time_sum = 0.0

            for ts, value in iterator:
                # The timestamp is after the next aggregation timestamp, finalize the current aggregation timestamp
                # value
                if ts >= aggregation_timestamps[next_aggr_ts_index]:
                    if next_aggr_ts_index > 0:
                        # Add remaining part to the last aggregation interval
                        remaining_delta_seconds = (aggregation_timestamps[next_aggr_ts_index] - last_ts).total_seconds()
                        value_sum += last_value * remaining_delta_seconds
                        time_sum += remaining_delta_seconds

                        # Add average result entry from accumulated values
                        result.append((aggregation_timestamps[next_aggr_ts_index-1], value_sum / time_sum))

                    next_aggr_ts_index += 1
                    if next_aggr_ts_index >= len(aggregation_timestamps):
                        return result

                    # Fill up aggregation intervals without entries
                    while ts >= aggregation_timestamps[next_aggr_ts_index]:
                        result.append((aggregation_timestamps[next_aggr_ts_index-1], last_value))
                        next_aggr_ts_index += 1
                        if next_aggr_ts_index >= len(aggregation_timestamps):
                            return result

                    value_sum = 0
                    time_sum = 0

                # Accumulate the weighted value and time interval to the `*_sum` variables
                if next_aggr_ts_index > 0:
                    interval_start = aggregation_timestamps[next_aggr_ts_index-1]
                    value_start = max(last_ts, interval_start)
                    time_delta_seconds = (ts - value_start).total_seconds()
                    value_sum += last_value * time_delta_seconds
                    time_sum += time_delta_seconds

                last_value = value
                last_ts = ts

            if next_aggr_ts_index > 0:
                # Add remaining part to the last aggregation interval
                remaining_delta_seconds = (aggregation_timestamps[next_aggr_ts_index] - last_ts).total_seconds()
                value_sum += last_value * remaining_delta_seconds
                time_sum += remaining_delta_seconds

                # Add average result entry from accumulated values
                result.append((aggregation_timestamps[next_aggr_ts_index - 1], value_sum / time_sum))
            return result

        else:
            raise ValueError("Unsupported aggregation method {}".format(aggregation_method))

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
