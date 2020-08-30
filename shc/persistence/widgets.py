import datetime
from pathlib import Path
from typing import Iterable

from . import PersistenceVariable, LoggingWebUIView
from ..web import WebServer, WebPage, WebPageItem, WebUIConnector


class LogListWidget(WebPageItem):
    def __init__(self, variable: PersistenceVariable, interval: datetime.timedelta):
        # TODO add formatting
        # TODO allow multiple variables
        self.connector = LoggingWebUIView(variable, interval)

    def register_with_server(self, page: WebPage, server: WebServer) -> None:
        server.add_js_file(Path(__file__).parent / 'persistence.js')

    async def render(self) -> str:
        return '<div data-widget="persistence.log_list" data-id="{}"></div>'.format(id(self.connector))

    def get_connectors(self) -> Iterable[WebUIConnector]:
        return [self.connector]
