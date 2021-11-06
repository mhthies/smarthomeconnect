#!/usr/bin/env python3
# Copyright 2021 Michael Thies <mail@mhthies.de>
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
This SHC example application demonstrates, how a custom web UI widget can be built, including the Python widget class
(for rendering the HTML widget and providing a SHC connectable object for websocket communication with the widget), the
Javascript widget class (see `./web_assets/main.js`) and styling.
"""

from pathlib import Path
from typing import Iterable, NamedTuple

import shc.web.interface
import shc.web.widgets
import shc.datatypes


# A custom datatype to send two-dimensional data to our widget
class CrossHairPoint(NamedTuple):
    x: shc.datatypes.Balance
    y: shc.datatypes.Balance


# Our custom widget type.
#
# It inherits from WebPageItem to be render-able widget, that can be added to web pages via .add_item(), and it inherits
# from WebDisplayDatapoint (which is a WebUIConnector) to serve as an endpoint for the widget's websocket communication
# at the server-side. WebDisplayDatapoint already implements everything that is needed, to make up a `Writable` object,
# that transmits all value updates JSON-encoded to all connected web browsers.
class CrossHairWidget(shc.web.interface.WebPageItem,
                      shc.web.interface.WebDisplayDatapoint[CrossHairPoint]):
    type = CrossHairPoint

    # We do the HTML rendering for our widget quite simple here. Instead of using a full-blown template engine like
    # Jinja2, a simple Python format string does the job here.
    # However, we need to fill in the Python object-id of self as an HTML attribute, so the JavaScript-side of the
    # widget can read it and use it as the WebUIConnector object id to subscribe to for receiving value updates.
    async def render(self) -> str:
        return f"""
        <div class="crosshairs-widget" data-widget="crosshair" data-id="{id(self)}"><div class="indicator"></div></div>
        """

    # We need to the webserver all WebUIConnector objects contained in this widget, so that it can route subscriptions
    # and value updates from the web clients to these objects. Our widget type is a WebUIConnector by itself and does
    # not contain further WebUIConnectors. So we only need to return a single object in the list: self.
    def get_connectors(self) -> Iterable[shc.web.interface.WebUIConnector]:
        return [self]


# ################################################################################################
# The actual SHC application configuration
# (see the `ui_showcase.py` example for a more commented version)


# The web server
web_server = shc.web.interface.WebServer('localhost', 8080, index_name='index')
web_server.add_static_directory(Path(__file__).parent / 'web_assets', ['main.js'], ['main.css'])

# A variable to store the current crosshair indicator position
position = shc.Variable(CrossHairPoint, initial_value=CrossHairPoint(shc.datatypes.Balance(0),
                                                                     shc.datatypes.Balance(0)))

# A web page with our custom widget and two sliders to control the position
index_page = web_server.page('index', 'Crosshair example', menu_entry=True, menu_icon='home')

index_page.add_item(CrossHairWidget().connect(position))
index_page.add_item(shc.web.widgets.Slider("X").connect(position.field('x'), convert=True))
index_page.add_item(shc.web.widgets.Slider("Y").connect(position.field('y'), convert=True))

index_page.add_item(shc.web.widgets.ImageMap(Path(__file__).parent / 'web_assets' / 'bg.svg', []))
index_page.add_item(shc.web.widgets.ImageMap(Path(__file__).parent / 'web_assets' / 'bg.svg', []))

if __name__ == "__main__":
    shc.main()
