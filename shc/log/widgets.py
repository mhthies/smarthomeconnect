import datetime
from pathlib import Path
from typing import Iterable, Optional

from . import PersistenceVariable, LoggingRawWebUIView, AggregationMethod, LoggingAggregatedWebUIView
from ..web import WebServer, WebPage, WebPageItem, WebUIConnector


class LogListWidget(WebPageItem):
    def __init__(self, variable: PersistenceVariable, interval: datetime.timedelta,
                 aggregation: Optional[AggregationMethod] = None,
                 aggregation_interval: Optional[datetime.timedelta] = None):
        # TODO add formatting
        # TODO allow multiple variables
        self.interval = interval
        if aggregation_interval is None:
            aggregation_interval = interval / 10
        self.connector = (LoggingRawWebUIView(variable, interval, include_previous=False) if aggregation is None
                          else LoggingAggregatedWebUIView(variable, interval, aggregation, aggregation_interval))

    def register_with_server(self, page: WebPage, server: WebServer) -> None:
        server.add_js_file(Path(__file__).parent / 'log.js')

    async def render(self) -> str:
        return '<div class="ui secondary segment" style="max-height: 300px; overflow-y: auto;">' \
               '    <div data-widget="log.log_list" data-id="{}" data-interval="{}" class="ui divided list"></div>' \
               '</div>'\
            .format(id(self.connector), round(self.interval.total_seconds() * 1000))

    def get_connectors(self) -> Iterable[WebUIConnector]:
        return [self.connector]


class ChartWidget(WebPageItem):
    def __init__(self, variable: PersistenceVariable, interval: datetime.timedelta,
                 aggregation: Optional[AggregationMethod] = None,
                 aggregation_interval: Optional[datetime.timedelta] = None):
        # TODO add label,
        # TODO allow multiple variables
        self.interval = interval
        self.align_ticks_to = datetime.datetime(2020, 1, 1, 0, 0, 0)
        if aggregation_interval is None:
            aggregation_interval = interval / 10
        self.is_aggregated = aggregation is not None
        self.connector = (LoggingRawWebUIView(variable, interval, include_previous=True)
                          if aggregation is None
                          else LoggingAggregatedWebUIView(variable, interval, aggregation, aggregation_interval,
                                                          align_to=self.align_ticks_to))

    def register_with_server(self, page: WebPage, server: WebServer) -> None:
        server.add_js_file(Path(__file__).parent / 'moment.min.js')
        server.add_js_file(Path(__file__).parent / 'Chart.min.js')
        server.add_js_file(Path(__file__).parent / 'log.js')

    async def render(self) -> str:
        return '<canvas data-widget="log.line_chart" data-id="{}" data-interval="{}" data-align-ticks-to="{}" ' \
               'data-aggregated="{}"></canvas>'\
            .format(id(self.connector), round(self.interval.total_seconds() * 1000),
                    self.align_ticks_to.timestamp() * 1000, self.is_aggregated)

    def get_connectors(self) -> Iterable[WebUIConnector]:
        return [self.connector]
