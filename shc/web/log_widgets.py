# Copyright 2020-2023 Michael Thies <mail@mhthies.de>
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may not use this file except in compliance with
# the License. You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software distributed under the License is distributed on an
# "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the License for the
# specific language governing permissions and limitations under the License.

"""
This module contains additional predefined user interface widget (:class:`WebPageItems <shc.web.interface.WebPageItem>`)
classes for displaying data logs (i.e. time series of dynamic variables) in the web UI, either as a textual list or as a
plotted chart.
The time series data, incl. live updates, is fetched from interfaces, which implement the
:class:`shc.data_logging.DataLogVariable` interface.
See :ref:`data_logging`.
"""
from dataclasses import dataclass
import datetime
from typing import Iterable, Optional, Generic, Union, Callable, Tuple, List

from markupsafe import Markup

from ..data_logging import DataLogVariable, LoggingWebUIView, AggregationMethod
from ..base import T
from .interface import WebPageItem, WebUIConnector, jinja_env


@dataclass
class LogListDataSpec(Generic[T]):
    """Specification of one data log source and the formatting of its datapoints within a :class:`LogListWidget`"""
    #: The `DataLogVariable` (i.e. logging database connector) to retrieve the recent datapoints and updates from
    variable: DataLogVariable[T]
    #: Formatter function or format string to format the values
    format: Union[str, Markup, Callable[[Union[T, float]], Union[str, Markup]]] = "{}"
    #: A color name to highlight all rows belonging to this data log in the `LogListWidget`. Must be one of
    #: Fomantic-UIs's color names.
    color: str = ''
    #: Aggregation method of this datalog or None to disable aggregation
    aggregation: Optional[AggregationMethod] = None
    #: If `aggregation` is not None: The time span/period of the single aggregation intervals and aggregated datapoints
    aggregation_interval: Optional[datetime.timedelta] = None


class LogListWidget(WebPageItem):
    """
    A `WebPageItem` showing a dynamically updated list of recent value changes from one or more `DataLogVariables`.

    The different data logs are combined, such that all datapoints (value changes) are shown in a unified list, ordered
    by their timestamp.

    Note: The aggregation method, interval and value formatting can be defined individually for each data log variable.
    Thus, these settings are defined via a list of :class:`LogListDataSpec` tuples, each of them defining one data log
    source with its settings. The overall display interval of the widget (i.e. how far into the past log entries are
    displayed), is set for all data log variables together.

    Usage example::

        import datetime
        from shc.web.data_logging import AggregationMethod
        from shc.web.log_widgets import LogListWidget, LogListDataSpec
        from shc.interfaces.in_memory_data_logging import InMemoryDataLogVariable

        # create WebServer and WebPage
        web_page = ...

        # Example in-memory log variables for keeping timeseries for 2h
        # They need to be connected to some subscribable objects for providing the values
        room_temperature_log = InMemoryDataLogVariable(float, datetime.timedelta(hours=2))
        heater_power_log = InMemoryDataLogVariable(bool, datetime.timedelta(hours=2))

        # LogListWidget, showing interleaved average temperature every 5 minutes and all heater
        # on/off events within last hour
        web_page.add_item(
            LogListWidget(
                datetime.timedelta(hours=1),
                [
                    LogListDataSpec(room_temperature_log,
                                    format="{}°C",
                                    aggregation=AggregationMethod.AVERAGE,
                                    aggregation_interval=datetime.timedelta(minutes=5)),
                    LogListDataSpec(heater_power_log, lambda v: "on" if v else "off"),
                ])
        )


    :param interval: The time interval boundary of the widget: All entries of the data logs from `interval` ago up to
        now are displayed.
    :param data_spec: The list of data log sources and their individual display settings. See :class:`LogListDataSpec`'s
        documentation for available fields.
    """
    def __init__(self, interval: datetime.timedelta, data_spec: List[LogListDataSpec]):
        self.interval = interval

        self.specs = []
        self.connectors = []

        for spec in data_spec:
            formatter: Callable[[T], Union[str, Markup]] = (
                (lambda x: spec.format.format(x))  # type: ignore
                if isinstance(spec.format, (str, Markup))
                else spec.format)
            aggregation_interval = spec.aggregation_interval if spec.aggregation_interval is not None else interval / 10
            connector = LoggingWebUIView(spec.variable, interval, spec.aggregation, aggregation_interval,
                                         converter=formatter, include_previous=False)
            color = "" if not spec.color else spec.color + " colored"
            self.connectors.append(connector)
            self.specs.append({'id': id(connector),
                               'color': color})

    async def render(self) -> str:
        return await jinja_env.get_template('log/loglist.htm').render_async(
            spec=self.specs, interval=round(self.interval.total_seconds() * 1000))

    def get_connectors(self) -> Iterable[WebUIConnector]:
        return self.connectors


@dataclass
class ChartDataSpec:
    """Specification of one data log source and the formatting of its datapoints within a :class:`ChartWidget`"""
    #: The `DataLogVariable` (i.e. logging database connector) to retrieve the recent datapoints and updates from
    variable: DataLogVariable
    label: str
    #: An RGB color value for the plot line. If None, one of the five pre-defined colors will be used for each line
    color: Optional[Tuple[int, int, int]] = None
    #: Aggregation method of this datalog or None to disable aggregation
    aggregation: Optional[AggregationMethod] = None
    #: If `aggregation` is not None: The time span/period of the single aggregation intervals and aggregated datapoints
    aggregation_interval: Optional[datetime.timedelta] = None
    #: Multiply all logged values by this factor before showing in the chart (e.g. for unit conversion purposes)
    scale_factor: float = 1.0
    #: Unit symbol to be shown after the value in the Chart tooltip
    unit_symbol: str = ""


class ChartWidget(WebPageItem):
    """
    A `WebPageItem` showing a dynamically line plot from one or more `DataLogVariables`, using Chart.js

    For each data log a single line is plotted, using a common x axis (time) and y axis (value). It is possible to
    combine different value types (float, int, bool – boolean values are converted to 0 and 1), as well as different
    aggregation methods and intervals. For example, you can show minimum, maximum and average aggregation of the same
    logging variable.

    Note: The aggregation method, interval and value formatting can be defined individually for each plot line.
    Thus, these settings are defined via a list of :class:`ChartDataSpec` tuples, each of them defining one data log
    source with its settings. The overall display interval of the widget (i.e. scaling of the x axis), is set for all
    data log variables together.

    Usage example::

        import datetime
        from shc.web.data_logging import AggregationMethod
        from shc.web.log_widgets import ChartWidget, ChartDataSpec
        from shc.interfaces.in_memory_data_logging import InMemoryDataLogVariable

        # create WebServer and WebPage
        web_page = ...

        # Example in-memory log variable for keeping timeseries for 2h
        # Needs to be connected to some subscribable object for providing the values
        room_temperature_log = InMemoryDataLogVariable(float, datetime.timedelta(hours=2))

        # ChartWidget, showing a plot of the 15-minutes minimum, maximum and average of the room
        # temperature within the last two hours.
        web_page.add_item(
            ChartWidget(
                datetime.timedelta(hours=1),
                [
                    ChartDataSpec(room_temperature_log,
                                  label="Min",
                                  aggregation=AggregationMethod.MINIMUM,
                                  aggregation_interval=datetime.timedelta(minutes=15)),
                    ChartDataSpec(room_temperature_log,
                                  label="Max",
                                  aggregation=AggregationMethod.MAXIMUM,
                                  aggregation_interval=datetime.timedelta(minutes=15)),
                    ChartDataSpec(room_temperature_log,
                                  label="AVG",
                                  aggregation=AggregationMethod.AVERAGE,
                                  aggregation_interval=datetime.timedelta(minutes=15)),
                ])
        )

    :param interval: The time interval / x axis range of the widget. The x axis will cover this time interval and end
        at the current time ("now").
    :param data_spec: The list of data log sources and their individual display settings. See :class:`ChartDataSpec`'s
        documentation for available fields.
    """
    COLORS = [
        (0, 181, 173),
        (219, 40, 40),
        (33, 186, 69),
        (163, 51, 200),
        (251, 189, 8),
    ]

    def __init__(self, interval: datetime.timedelta,  data_spec: List[ChartDataSpec]):
        self.interval = interval
        self.align_ticks_to = datetime.datetime(2020, 1, 1, 0, 0, 0)
        self.row_specs = []
        self.connectors = []

        for i, spec in enumerate(data_spec):
            aggregation_interval = spec.aggregation_interval
            if aggregation_interval is None:
                aggregation_interval = interval / 10
            is_aggregated = spec.aggregation is not None
            connector = LoggingWebUIView(spec.variable, interval, spec.aggregation,
                                         aggregation_interval, align_to=self.align_ticks_to,
                                         converter=None if spec.scale_factor == 1.0 else lambda x: x*spec.scale_factor,
                                         include_previous=True)
            self.connectors.append(connector)
            self.row_specs.append({'id': id(connector),
                                   'stepped_graph': is_aggregated,
                                   'show_points': is_aggregated,
                                   'color': spec.color if spec.color is not None else self.COLORS[i % len(self.COLORS)],
                                   'label': spec.label,
                                   'unit_symbol': spec.unit_symbol,
                                   'extend_graph_to_now': not is_aggregated})

    async def render(self) -> str:
        return await jinja_env.get_template('log/chart.htm').render_async(
            spec=self.row_specs, interval=round(self.interval.total_seconds() * 1000),
            align_ticks_to=self.align_ticks_to.timestamp() * 1000)

    def get_connectors(self) -> Iterable[WebUIConnector]:
        return self.connectors
