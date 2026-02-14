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
import random
import enum

import markupsafe

import shc
import shc.web
from shc.datatypes import RangeUInt8, RangeFloat1, RGBUInt8
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
yaks_favorite_fruit = shc.Variable(Fruits, 'yaks_favorite_fruit', initial_value=Fruits.APPLES)
number_of_yaks = shc.Variable(int, 'number_of_yaks', initial_value=0)
yak_wool = shc.Variable(RangeFloat1, 'yak_wool', initial_value=0.0)
yak_color = shc.Variable(RGBUInt8, 'yak_color', initial_value=RGBUInt8(RangeUInt8(0), RangeUInt8(0), RangeUInt8(0)))


# The web server
web_server = shc.web.WebServer('localhost', 8080, index_name='index')

#############################################################################################
# Page index (Home)                                                                         #
# Here we show all the buttons, the dropdowns, the Switch and the TextInput and TextDisplay #
#############################################################################################
index_page = web_server.page('index', 'Home', menu_entry=True, menu_icon='home')

# A simple ButtonGroup with ToggleButtons for foobar
index_page.add_item(ButtonGroup("State of the foobar", [
    ToggleButton("Foo").connect(foo),
    ToggleButton("Bar", color='red').connect(bar),
    # Foobar requires confirmation when switched on.
    ToggleButton("Foobar", color='black',
                 confirm_message="Do you want the foobar?", confirm_values=[True]).connect(foobar),
]))

# We can also use ValueButtons to represent individual states (here in the 'outline' version)
index_page.add_item(ButtonGroup("The Foo", [
    ValueButton(False, "Off", outline=True, color="black").connect(foo),
    ValueButton(True, "On", outline=True).connect(foo),
]))

# … or use the ValueListButtonGroup as a shortcut, especially useful for enums
index_page.add_item(ValueListButtonGroup([(Fruits.APPLES, '🍏'),
                                          (Fruits.LEMONS, '🍋'),
                                          (Fruits.BANANAS, '🍌')], "Which fruit?").connect(yaks_favorite_fruit))

# … there's even a shortcut for the shortcut (if you don't mind seeing the enum raw entry names)
index_page.add_item(EnumButtonGroup(Fruits, "Which fruit, again?").connect(yaks_favorite_fruit))

# … or, let's simply take a dropdown
index_page.add_item(Select([(Fruits.APPLES, '🍏'),
                            (Fruits.LEMONS, '🍋'),
                            (Fruits.BANANAS, '🍌')], "Now really, which fruit?").connect(yaks_favorite_fruit))
# … again, with shortcut
index_page.add_item(EnumSelect(Fruits, "Which fruit, again?").connect(yaks_favorite_fruit))


# Let's change to the right column
index_page.new_segment("The right column")

# We also have buttons, that are only readable (disabled) …
index_page.add_item(ButtonGroup("State of the bar", [
    DisplayButton(label=icon('hat wizard'), color="teal").connect(bar),
]))
# … or only clickable (stateless)
magic_button = StatelessButton(None, label=icon('magic'), color="yellow")
index_page.add_item(ButtonGroup("Magic", [magic_button]))


@magic_button.trigger
@shc.handler()
async def do_magic(_v, _o) -> None:
    await number_of_yaks.write(random.randint(0, 100))


# The Switch is a nice alternative to the ToggleButton
index_page.add_item(Switch("The foobar", color="black",
                           confirm_message="Sure about the foobar?", confirm_values=[True]).connect(foobar))


# Another segment in the right column
index_page.new_segment(same_column=True)

# For entering numbers or strings, use the TextInput widget
index_page.add_item(TextInput(int, "Number of yaks", min=0, max=100, step=1, input_suffix="pc.")
                    .connect(number_of_yaks))
# … and for displaying them the TextDisplay widget
index_page.add_item(TextDisplay(int, "{} Yaks", "The herd").connect(number_of_yaks))
# it even allows to HTML-format the value (or use a custom function for formatting):
index_page.add_item(TextDisplay(int, markupsafe.Markup("<b>{}</b> Yaks"), "The herd (nice)").connect(number_of_yaks))
index_page.add_item(TextDisplay(int, icon('paw', "{} Yaks"), "The herd (even nicer)").connect(number_of_yaks))


#############################################################################################
# Color page                                                                                #
# Here we show the color chooser and sliders                                                #
#############################################################################################

color_page = web_server.page('color', "Colors", menu_entry=True, menu_icon="palette")

color_page.new_segment("The color chooser")
color_page.add_item(ColorChoser().connect(yak_color))

color_page.new_segment("Other things")
color_page.add_item(MinMaxButtonSlider("Yak wool", color='black').connect(yak_wool, convert=True))
color_page.add_item(Slider("Red", color='red')
                    .connect(yak_color.field('red'), convert=True))
color_page.add_item(Slider("Green", color='green')
                    .connect(yak_color.field('green'), convert=True))
color_page.add_item(Slider("Blue", color='blue')
                    .connect(yak_color.field('blue'), convert=True))


#############################################################################################
# Overview page                                                                             #
# Here we show the ImageMap and HideRows                                                    #
#############################################################################################

overview_page = web_server.page('overview', "Overview", menu_entry='Some Submenu', menu_icon='tachometer alternate',
                                menu_sub_label="Overview")

# ImageMap supports all the different Buttons as items, as well as the special ImageMapLabel
# The optional fourth entry of each item is a list of WebPageItems (everything we have shown so far – even an ImageMap))
# to be placed in a popup shown when the item is clicked.
overview_page.add_item(ImageMap(
    "https://upload.wikimedia.org/wikipedia/commons/thumb/6/6d/Newburn_Flats_Floor_Plan.pdf"
    "/page1-543px-Newburn_Flats_Floor_Plan.pdf.jpg",
    [
        (0.20, 0.30, ToggleButton("Foo", outline=True).connect(foo)),
        (0.33, 0.30, ToggleButton("Bar", color='red', outline=True).connect(bar)),
        # Foobar requires confirmation when switched on.
        (0.67, 0.30, ToggleButton("Foobar", color='black', outline=True,
                                  confirm_message="Do you want the foobar?", confirm_values=[True]).connect(foobar)),

        (0.26, 0.42, DisplayButton(label=icon('hat wizard'), color="red").connect(bar)),

        # We use the RangeFloat1 → bool conversion here to highlight the button with the popup, whenever the yak_wool
        # value is > 0. To use another condition, you can pass a (lambda) function to the `convert` parameter
        (0.42, 0.52, DisplayButton(label=icon('dragon'), color="black").connect(yak_wool, convert=True), [
            Slider("Yak Wool").connect(yak_wool)
        ]),
    ]
))

overview_page.new_segment()
overview_page.add_item(HideRowBox([
    HideRow("Foo", color='blue').connect(foo),
    HideRow("Bar", color='red').connect(bar),
    # The optional button in the HideRow is completely independent from the row itself. Thus, we must connect the foobar
    # variable individually to the button and to the HideRow
    HideRow("Foobar", color='black', button=StatelessButton(False, icon('power off'), color='red').connect(foobar))
    .connect(foobar),
]))

if __name__ == '__main__':
    shc.main()
