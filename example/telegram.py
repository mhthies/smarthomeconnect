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
"""
A simple SHC example project with only a web interface to show all the nice ui elements on multiple pages.

Some things to note:
* The `shc.web.widgets.icon()` function is used to create icon labels for items, buttons, etc. It takes an icon name
  (see https://fomantic-ui.com/elements/icon.html for reference) and an optional label text to be placed along with the
  icon.
* The `color` parameter typically takes one of the colors of Semantic UI. See
  https://fomantic-ui.com/elements/button.html#colored for reference.
"""
import logging
import random
import enum
from pathlib import Path

import markupsafe

import shc
from shc.interfaces.telegram import SimpleTelegramAuth, TelegramBot
from shc.web.widgets import *


# An enum of special values
class Fruits(enum.Enum):
    APPLES = 0
    LEMONS = 1
    BANANAS = 2


# Some State variables to interact with
foo = shc.Variable(bool, 'foo', initial_value=False)
bar = shc.Variable(bool, 'bar', initial_value=False)
foobar = shc.Variable(bool, 'foobar', initial_value=False)
number_of_yaks = shc.Variable(int, 'number_of_yaks', initial_value=0)
yak_name = shc.Variable(str, 'yak_name')


# A web server
web_server = shc.web.WebServer('localhost', 8080, index_name='index')

index_page = web_server.page('index', 'Home', menu_entry=True, menu_icon='home')

index_page.add_item(ButtonGroup("State of the foobar", [
    ToggleButton("Foo").connect(foo),
    ToggleButton("Bar", color='red').connect(bar),
    ToggleButton("Foobar", color='black').connect(foobar),
]))
index_page.add_item(TextInput(int, "Number of yaks", min=0, max=100, step=1, input_suffix="pc.")
                    .connect(number_of_yaks))
index_page.add_item(TextInput(str, "Yak's name")
                    .connect(yak_name))

# The Telegram bot
telegram_auth = SimpleTelegramAuth({'michael': 123})
telegram_bot = TelegramBot("123456789:exampleTokenXXX", telegram_auth)

telegram_bot.on_off_connector("Foo", {'michael'}).connect(foo, read=True)
telegram_bot.on_off_connector("Bar", {'michael'}).connect(bar, read=True)
telegram_bot.on_off_connector("Foobar", {'michael'}).connect(foobar, read=True)
telegram_bot.str_connector("Yak Name", {'michael'}).connect(yak_name, read=True)
telegram_bot.str_connector("Yak Number", {'michael'}).connect(number_of_yaks, convert=(int, str), read=True)


@telegram_bot.trigger_connector("Random Yaks", {'michael'}).trigger
@shc.handler()
async def random_yaks(_v, _o):
    await number_of_yaks.write(random.randint(0, 255))


if __name__ == '__main__':
    logging.basicConfig(level=logging.DEBUG)
    shc.main()
