import datetime
from pathlib import Path
from typing import Iterable, Optional, Generic, Union, Callable, NamedTuple, Tuple, List

import jinja2
from markupsafe import Markup

from . import PersistenceVariable, LoggingRawWebUIView, AggregationMethod, LoggingAggregatedWebUIView
from ..base import T
from ..web import WebServer, WebPage, WebPageItem, WebUIConnector, jinja_env


jinja_env = jinja_env.overlay(
    loader=jinja2.PackageLoader('shc.log', 'templates'),
)


class LogListWidget(WebPageItem, Generic[T]):
    def __init__(self, variable: PersistenceVariable[T], interval: datetime.timedelta,
                 format: Union[str, Markup, Callable[[Union[T, float]], Union[str, Markup]]] = "{}",
                 aggregation: Optional[AggregationMethod] = None,
                 aggregation_interval: Optional[datetime.timedelta] = None):
        # TODO allow multiple variables
        self.interval = interval
        formatter: Callable[[T], Union[str, Markup]] = (
            (lambda x: format.format(x))
            if isinstance(format, (str, Markup))
            else format)
        if aggregation_interval is None:
            aggregation_interval = interval / 10
        self.connector = (LoggingRawWebUIView(variable, interval, formatter, include_previous=False)
                          if aggregation is None
                          else LoggingAggregatedWebUIView(variable, interval, aggregation, aggregation_interval,
                                                          formatter))

    def register_with_server(self, page: WebPage, server: WebServer) -> None:
        # Chart.js is not required for this widget, but we need to load it before 'log.js', in case, it is required for
        # a ChartWidget.
        server.add_js_file(Path(__file__).parent / 'Chart.min.js')
        server.add_js_file(Path(__file__).parent / 'log.js')

    async def render(self) -> str:
        return await jinja_env.get_template('log/loglist.htm').render_async(
            id=id(self.connector), interval=round(self.interval.total_seconds() * 1000))

    def get_connectors(self) -> Iterable[WebUIConnector]:
        return [self.connector]


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

    def register_with_server(self, page: WebPage, server: WebServer) -> None:
        server.add_js_file(Path(__file__).parent / 'Chart.min.js')
        server.add_js_file(Path(__file__).parent / 'log.js')

    async def render(self) -> str:
        return await jinja_env.get_template('log/chart.htm').render_async(
            spec=self.row_specs, interval=round(self.interval.total_seconds() * 1000),
            align_ticks_to=self.align_ticks_to.timestamp() * 1000)

    def get_connectors(self) -> Iterable[WebUIConnector]:
        return self.connectors
