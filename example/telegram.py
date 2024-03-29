# Copyright 2022 Michael Thies <mail@mhthies.de>
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
A simple SHC example project that demonstrates the TelegramBot interface.

To visualize and modify the state Variables, that can be accessed via the Telegram bot, an additional web UI is started
at localhost:8080. To try this example, you need to create Telegram bot (using the "BotFather") and modify lines
58-59 of this example script to match your bot credentials and personal Telegram chat id.
"""
import logging
import random
import enum

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

telegram_bot.on_off_connector("Foo", {'michael'}).connect(foo)
telegram_bot.on_off_connector("Bar", {'michael'}).connect(bar)
telegram_bot.on_off_connector("Foobar", {'michael'}).connect(foobar)
telegram_bot.str_connector("Yak Name", {'michael'}).connect(yak_name)
telegram_bot.generic_connector(int, "Yak Number", lambda x: str(x), lambda x: int(x), {'michael'})\
    .connect(number_of_yaks)

# For Python 3.7 compatibility, we store the trigger in a variable first, before applying it as a decorator to the logic
#   handler function. From Python 3.8 on, you can simply write the full expression as a decorator.
random_yaks_trigger = telegram_bot.trigger_connector("Random Yaks", {'michael'}).trigger


@random_yaks_trigger
@shc.handler()
async def random_yaks(_v, _o):
    await number_of_yaks.write(random.randint(0, 255))


if __name__ == '__main__':
    logging.basicConfig(level=logging.DEBUG)
    shc.main()
