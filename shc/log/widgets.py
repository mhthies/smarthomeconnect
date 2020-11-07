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
        self.connector = (LoggingRawWebUIView(variable, interval) if aggregation is None
                          else LoggingAggregatedWebUIView(variable, interval, aggregation, aggregation_interval))

    def register_with_server(self, page: WebPage, server: WebServer) -> None:
        server.add_js_file(Path(__file__).parent / 'log.js')

    async def render(self) -> str:
        return '<div data-widget="log.log_list" data-id="{}" data-interval="{}" ' \
               'style="max-height: 300px; overflow-y: auto;"></div>'\
            .format(id(self.connector), round(self.interval.total_seconds() * 1000))

    def get_connectors(self) -> Iterable[WebUIConnector]:
        return [self.connector]
