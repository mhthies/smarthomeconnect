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
import math
from typing import Type, Generic, List, Any, Optional, Set, Tuple, Union, cast, TypeVar, Callable

import aiohttp.web

from .. import timer
from ..base import T, Readable, Writable, UninitializedError
from ..conversion import SHCJsonEncoder
from ..web.interface import WebUIConnector

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
        self.subscribed_web_ui_views: List[LoggingRawWebUIView] = []

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
        data = await self.retrieve_log(start_time, end_time, include_previous=True)
        aggregation_timestamps = [start_time + i * aggregation_interval
                                  for i in range(math.ceil((end_time - start_time) / aggregation_interval))]

        # The last aggregation_timestamps is not added to the results, but only used to delimit the last aggregation
        # interval.
        if aggregation_timestamps[-1] < end_time:
            aggregation_timestamps.append(end_time)

        if aggregation_method in (AggregationMethod.MINIMUM, AggregationMethod.MAXIMUM, AggregationMethod.AVERAGE):
            if not issubclass(self.type, (int, float)):
                raise TypeError("min/max/avg. aggregation is only applicable to int and float type log variables.")

        elif aggregation_method not in (AggregationMethod.ON_TIME, AggregationMethod.ON_TIME_RATIO):
            raise ValueError("Unsupported aggregation method {}".format(aggregation_method))

        aggregator_t = {
            AggregationMethod.MINIMUM: MinAggregator,
            AggregationMethod.MAXIMUM: MaxAggregator,
            AggregationMethod.AVERAGE: AverageAggregator,
            AggregationMethod.ON_TIME: OnTimeAggregator,
            AggregationMethod.ON_TIME_RATIO: OnTimeRatioAggregator,
        }[aggregation_method]()  # type: ignore
        aggregator = cast(AbstractAggregator[T, Any], aggregator_t)  # This is guaranteed by our type checks above

        next_aggr_ts_index = 0
        # Get first entry and its timestamp for skipping of empty aggregation intervals and initialization of the
        # first relevant interval
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

        result: List[Tuple[datetime.datetime, float]] = []
        aggregator.reset()

        for ts, value in iterator:
            # The timestamp is after the next aggregation timestamp, finalize the current aggregation timestamp
            # value
            if ts >= aggregation_timestamps[next_aggr_ts_index]:
                if next_aggr_ts_index > 0:
                    # Add remaining part to the last aggregation interval
                    aggregator.aggregate(last_ts, aggregation_timestamps[next_aggr_ts_index], last_value)

                    # Add average result entry from accumulated values
                    result.append((aggregation_timestamps[next_aggr_ts_index-1], aggregator.get()))

                next_aggr_ts_index += 1
                if next_aggr_ts_index >= len(aggregation_timestamps):
                    return result

                # Do the same for every following empty interval
                while ts >= aggregation_timestamps[next_aggr_ts_index]:
                    aggregator.reset()
                    aggregator.aggregate(aggregation_timestamps[next_aggr_ts_index-1],
                                         aggregation_timestamps[next_aggr_ts_index], last_value)
                    result.append((aggregation_timestamps[next_aggr_ts_index-1], aggregator.get()))

                    next_aggr_ts_index += 1
                    if next_aggr_ts_index >= len(aggregation_timestamps):
                        return result

                aggregator.reset()

            # Accumulate the weighted value and time interval to the `*_sum` variables
            if next_aggr_ts_index > 0:
                interval_start = aggregation_timestamps[next_aggr_ts_index-1]
                aggregator.aggregate(max(last_ts, interval_start), ts, last_value)

            last_value = value
            last_ts = ts

        if next_aggr_ts_index > 0:
            # Add remaining part to the last aggregation interval
            aggregator.aggregate(last_ts, aggregation_timestamps[next_aggr_ts_index], last_value)

            # Add average result entry from accumulated values
            result.append((aggregation_timestamps[next_aggr_ts_index-1], aggregator.get()))

        next_aggr_ts_index += 1

        # Fill remaining aggregation intervals
        while next_aggr_ts_index < len(aggregation_timestamps):
            aggregator.reset()
            aggregator.aggregate(aggregation_timestamps[next_aggr_ts_index - 1],
                                 aggregation_timestamps[next_aggr_ts_index], last_value)
            result.append((aggregation_timestamps[next_aggr_ts_index - 1], aggregator.get()))

            next_aggr_ts_index += 1
        return result

    async def read(self) -> T:
        value = await self._read_from_log()
        if value is None:
            raise UninitializedError("No value for has been persisted for variable '{}' yet.".format(self))
        return value

    async def _write(self, value: T, origin: List[Any]):
        logger.debug("%s value %s for %s to log backend", "logging" if self.log else "updating", value, self)
        await self._write_to_log(value)
        for web_ui_view in self.subscribed_web_ui_views:
            await web_ui_view.new_value(datetime.datetime.now(datetime.timezone.utc), value)


class LoggingRawWebUIView(WebUIConnector):
    """
    A WebUIConnector which is used to retrieve a log/timeseries of a certain log variable for a certain time
    interval via the Webinterface UI websocket and subscribe to updates of that log variable.
    """
    def __init__(self, variable: PersistenceVariable, interval: datetime.timedelta,
                 converter: Optional[Callable] = None, include_previous: bool = True):
        if not variable.log:
            raise ValueError("Cannot use a PersistenceVariable with log=False for a web logging web ui widget")
        super().__init__()
        self.variable = variable
        variable.subscribed_web_ui_views.append(self)
        self.interval = interval
        self.subscribed_websockets: Set[aiohttp.web.WebSocketResponse] = set()
        self.converter: Callable = converter or (lambda x: x)
        self.include_previous = include_previous

    async def new_value(self, timestamp: datetime.datetime, value: Any) -> None:
        """
        Coroutine to be called by the class:`PersistenceVariable` this view belongs to, when it receives and logs a new
        value, so the value can instantly be plotted by all subscribed web clients.

        :param timestamp: Exact timestamp of the new value
        :param value: The new value
        """
        await self._websocket_publish({
            'init': False,
            'data': [(timestamp, self.converter(value))]
        })

    async def _websocket_before_subscribe(self, ws: aiohttp.web.WebSocketResponse) -> None:
        data = await self.variable.retrieve_log(datetime.datetime.now(datetime.timezone.utc)
                                                - self.interval,
                                                datetime.datetime.now(datetime.timezone.utc)
                                                + datetime.timedelta(seconds=5), include_previous=self.include_previous)
        await ws.send_str(json.dumps({'id': id(self),
                                      'v': {
                                          'init': True,
                                          'data': [(ts, self.converter(v)) for ts, v in data]
                                      }},
                                     cls=SHCJsonEncoder))


class LoggingAggregatedWebUIView(WebUIConnector):
    """
    A WebUIConnector which is used to retrieve and periodically update aggregated log data of a certain log variable for
    a certain time interval via the Webinterface UI websocket.
    """
    def __init__(self, variable: PersistenceVariable, interval: datetime.timedelta, aggregation: AggregationMethod,
                 aggregation_interval: datetime.timedelta, converter: Optional[Callable] = None,
                 align_to: datetime.datetime = datetime.datetime(2020, 1, 1, 0, 0, 0),
                 update_interval: Optional[datetime.timedelta] = None):
        # TODO add pre_converter (e.g. for scaling or getting a single value out of Namespaces)
        # TODO add PersistenceVariable type check?
        if not variable.log:
            raise ValueError("Cannot use a PersistenceVariable with log=False for a web logging web ui widget")
        super().__init__()
        self.variable = variable
        self.interval = interval
        self.aggregation = aggregation
        self.aggregation_interval = aggregation_interval
        self.subscribed_websockets: Set[aiohttp.web.WebSocketResponse] = set()
        self.converter = converter or (lambda x: x)
        self.align_to = align_to
        update_interval = (update_interval if update_interval is not None
                           else min(aggregation_interval / 2, datetime.timedelta(minutes=1)))
        self.last_update = datetime.datetime.fromtimestamp(0).astimezone() + 2 * aggregation_interval

        self.timer = timer.Every(update_interval)
        self.timer.trigger(self._update, synchronous=True)

    async def _websocket_before_subscribe(self, ws: aiohttp.web.WebSocketResponse) -> None:
        begin, end = self.calculate_interval(False)
        data = await self.variable.retrieve_aggregated_log(begin, end, self.aggregation, self.aggregation_interval)
        # TODO use caching?
        await ws.send_str(json.dumps({'id': id(self),
                                      'v': {
                                          'init': True,
                                          'data': [(ts, self.converter(v)) for ts, v in data]
                                      }},
                                     cls=SHCJsonEncoder))

    def calculate_interval(self, only_latest: bool) -> Tuple[datetime.datetime, datetime.datetime]:
        """
        Calculate the begin and end timestamps to be passed to :meth:`PersistenceVariable.retrieve_aggregated_log` based
        on the configured interval, aggregation_interval, align timestamp.

        :param only_latest: If True, the begin timestamp is chosen in such a way, that only the new and (probably)
            changed aggregated values since the last update (see self.last_update) are returned.
        :return: (start_time, end_time) for `retrieve_aggregated_log()`
        """
        end = datetime.datetime.now().astimezone()
        preliminary_begin = end - self.interval
        if only_latest:
            preliminary_begin = max(preliminary_begin, self.last_update - self.aggregation_interval)
        align = self.align_to.astimezone()
        align_count = (preliminary_begin - align) // self.aggregation_interval
        begin = align + (align_count + 1) * self.aggregation_interval

        return begin, end

    async def _update(self, _v, _o) -> None:
        if not self.subscribed_websockets:
            return

        begin, end = self.calculate_interval(True)
        data = await self.variable.retrieve_aggregated_log(begin, end, self.aggregation, self.aggregation_interval)
        await self._websocket_publish({'init': False,
                                       'data': [(ts, self.converter(v)) for ts, v in data]})
        self.last_update = end


S = TypeVar('S')


class AbstractAggregator(Generic[T, S], metaclass=abc.ABCMeta):
    """
    Abstract base class for Aggregator classes, a special helper class, used to define the actual aggregation logic in
    :meth:`PersistenceVariable.retrieve_aggregated_log`. For each aggregation method (see :class:`AggregationMethods`),
    a specialized Aggregator class is available.

    The aggregator defines, how individual values, which lasted for a given time interval, are aggregated into a single
    value. It is controlled by the `retrieve_aggregated_log()` method via three interface methods:
    * :meth:`reset` is called at the begin of every aggregation interval to reset the aggregated value
    * :meth:`aggregate` is called for each value change with the value and the begin and end timestamps of the interval
        for which the value lasted. These time intervals can be used to calculate the value's weight in a weighted
        average or the on time of a bool aggregation
    * :meth:`get` is called at the end of every aggregation interval to retrieve the aggregated value

    """
    __slots__ = ()

    def reset(self) -> None:
        pass

    @abc.abstractmethod
    def get(self) -> S:
        pass

    @abc.abstractmethod
    def aggregate(self, start: datetime.datetime, end: datetime.datetime, value: T) -> None:
        pass


class AverageAggregator(AbstractAggregator[Union[float, int], float]):
    """
    Aggregator implementation for AggregationMethod.AVERAGE. It calculates an average of the values, weighted by their
    respective time intervals.
    """
    __slots__ = ('value_sum', 'time_sum')
    value_sum: float
    time_sum: float

    def reset(self) -> None:
        self.value_sum = 0.0
        self.time_sum = 0.0

    def get(self) -> float:
        return self.value_sum / self.time_sum

    def aggregate(self, start: datetime.datetime, end: datetime.datetime, value: Union[float, int]) -> None:
        delta_seconds = (end - start).total_seconds()
        self.time_sum += delta_seconds
        self.value_sum += value * delta_seconds


class MinAggregator(AbstractAggregator[Union[float, int], float]):
    """
    Aggregator implementation for AggregationMethod.MINIMUM. It calculates the minimum of all values in an aggregation
    interval. The value's begin..end interval is ignored. Thus, even values with 0 duration are taken into account.
    """
    __slots__ = ('value',)
    value: float

    def reset(self) -> None:
        self.value = float('inf')

    def get(self) -> float:
        return self.value

    def aggregate(self, start: datetime.datetime, end: datetime.datetime, value: Union[int, float]) -> None:
        self.value = min(self.value, value)


class MaxAggregator(AbstractAggregator[Union[float, int], float]):
    """
    Aggregator implementation for AggregationMethod.MAXIMUM. It calculates the maximum of all values in an aggregation
    interval. The value's begin..end interval is ignored. Thus, even values with 0 duration are taken into account.
    """
    __slots__ = ('value',)
    value: float

    def reset(self) -> None:
        self.value = float('-inf')

    def get(self) -> float:
        return self.value

    def aggregate(self, start: datetime.datetime, end: datetime.datetime, value: Union[int, float]) -> None:
        self.value = max(self.value, value)


class OnTimeAggregator(AbstractAggregator[Any, float]):
    """
    Aggregator implementation for AggregationMethod.ONTIME. It calculates the aggregated duration of all intervals where
    the value evaluates to True. The value is returned in seconds.
    """
    __slots__ = ('value',)
    value: datetime.timedelta

    def reset(self) -> None:
        self.value = datetime.timedelta(0)

    def get(self) -> float:
        return self.value.total_seconds()

    def aggregate(self, start: datetime.datetime, end: datetime.datetime, value: bool) -> None:
        if value:
            self.value += end - start


class OnTimeRatioAggregator(AbstractAggregator[Any, float]):
    """
    # Aggregator implementation for AggregationMethod.ONTIME. It calculates the ratio of all intervals where the value
    evaluates to True to the total duration of the aggregation interval.
    """
    __slots__ = ('value', 'total_time')
    value: datetime.timedelta
    total_time: datetime.timedelta

    def reset(self) -> None:
        self.value = datetime.timedelta(0)
        self.total_time = datetime.timedelta(0)

    def get(self) -> float:
        return self.value / self.total_time

    def aggregate(self, start: datetime.datetime, end: datetime.datetime, value: Any) -> None:
        delta = end - start
        self.total_time += delta
        if value:
            self.value += delta
