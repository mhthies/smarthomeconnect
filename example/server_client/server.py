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

import enum

import shc
from shc.datatypes import RangeFloat1
import shc.web
from shc.web.widgets import *


# An enum of special values
class Fruits(enum.Enum):
    APPLES = 0
    LEMONS = 1
    BANANAS = 2


# Some State variables to interact with
foo = shc.Variable(bool, 'foo', initial_value=False)
yaks_favorite_fruit = shc.Variable(Fruits, 'yaks_favorite_fruit', initial_value=Fruits.APPLES)
yak_wool = shc.Variable(RangeFloat1, 'yak_wool', initial_value=0.0)


# The web server
web_server = shc.web.WebServer('localhost', 8080, index_name='index')

web_server.api(bool, 'foo').connect(foo)
web_server.api(Fruits, 'fruit').connect(yaks_favorite_fruit)
web_server.api(RangeFloat1, 'wool').connect(yak_wool)


index_page = web_server.page('index', 'Home', menu_entry=True, menu_icon='home')

# A simple ButtonGroup with ToggleButtons for foobar
index_page.add_item(ButtonGroup("State of the foobar", [
    ToggleButton("Foo").connect(foo)
]))

# … or use the ValueListButtonGroup as a shortcut, especially useful for enums
index_page.add_item(ValueListButtonGroup([(Fruits.APPLES, '🍏'),
                                          (Fruits.LEMONS, '🍋'),
                                          (Fruits.BANANAS, '🍌')], "Which fruit?").connect(yaks_favorite_fruit))

index_page.add_item(Slider("Yak wool", color='black').connect(yak_wool, convert=True))


if __name__ == '__main__':
    shc.main()
