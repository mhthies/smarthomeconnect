import datetime
from pathlib import Path
from typing import Iterable, Optional, Generic, Union, Callable, NamedTuple, Tuple, List

import jinja2
from markupsafe import Markup

from ..log.generic import PersistenceVariable, LoggingRawWebUIView, AggregationMethod, LoggingAggregatedWebUIView
from ..base import T
from .interface import WebPageItem, WebUIConnector, jinja_env


class LogListDataSpec(NamedTuple):
    variable: PersistenceVariable
    format: Union[str, Markup, Callable[[Union[T, float]], Union[str, Markup]]] = "{}"
    color: str = ''
    aggregation: Optional[AggregationMethod] = None
    aggregation_interval: Optional[datetime.timedelta] = None


class LogListWidget(WebPageItem, Generic[T]):
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
            connector = (LoggingRawWebUIView(spec.variable, interval, formatter, include_previous=False)
                         if spec.aggregation is None
                         else LoggingAggregatedWebUIView(spec.variable, interval, spec.aggregation,
                                                         aggregation_interval, formatter))
            self.connectors.append(connector)
            self.specs.append({'id': id(connector),
                               'color': spec.color})

    async def render(self) -> str:
        return await jinja_env.get_template('log/loglist.htm').render_async(
            spec=self.specs, interval=round(self.interval.total_seconds() * 1000))

    def get_connectors(self) -> Iterable[WebUIConnector]:
        return self.connectors


class ChartDataSpec(NamedTuple):
    variable: PersistenceVariable
    label: str
    color: Optional[Tuple[int, int, int]] = None
    aggregation: Optional[AggregationMethod] = None
    aggregation_interval: Optional[datetime.timedelta] = None


class ChartWidget(WebPageItem):
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
            connector = (LoggingRawWebUIView(spec.variable, interval, include_previous=True)
                         if spec.aggregation is None
                         else LoggingAggregatedWebUIView(spec.variable, interval, spec.aggregation,
                                                         aggregation_interval, align_to=self.align_ticks_to))
            self.connectors.append(connector)
            self.row_specs.append({'id': id(connector),
                                   'is_aggregated': is_aggregated,
                                   'color': spec.color if spec.color is not None else self.COLORS[i % len(self.COLORS)],
                                   'label': spec.label})

    async def render(self) -> str:
        return await jinja_env.get_template('log/chart.htm').render_async(
            spec=self.row_specs, interval=round(self.interval.total_seconds() * 1000),
            align_ticks_to=self.align_ticks_to.timestamp() * 1000)

    def get_connectors(self) -> Iterable[WebUIConnector]:
        return self.connectors
