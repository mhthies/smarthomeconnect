#!/usr/bin/env python3
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
An example SHC application, showing some specific features of SHC for interacting with KNX bus systems.

Particularly, we show

- using `TwoWayPipe` for listening to multiple KNX group addresses without echoing incoming telegrams
- using stateless interaction, e.g. for shutter up/down commands
- using `FadeStepAdapter` or `FadeStepRamp` to emulate dimming actuators in SHC

Please refer to SHC's documentation for more information on the used concepts and Python classes:

- https://smarthomeconnect.readthedocs.io/en/latest/interfaces/knx.html
- https://smarthomeconnect.readthedocs.io/en/latest/misc.html
"""

import datetime

import shc
import shc.web
import shc.misc
import shc.timer
from shc.datatypes import RangeUInt8, RangeFloat1, FadeStep
from shc.interfaces.knx import KNXConnector, KNXGAD, KNXUpDown
from shc.web.widgets import ButtonGroup, icon, StatelessButton, Switch

# Let's create a KNX interface and a web interface
knx_interface = KNXConnector()
web_interface = shc.web.WebServer('localhost', 8080, 'index')
web_page = web_interface.page('index', "Home")


# Central switching
# -----------------
#
# Let's assume:
# - 1/0/0 is a central switching function, that all light switching actuators in our home listen to
# - 2/3/7 is the individual group address auf our living room lights
#
# We want SHC to behave like a wall switch: Listen to both group addresses for changes, but send internal value updates
# only to the individual GAD. We will use a `TwoWayPipe` and the `.connect` method's `send` parameter for this. We also
# want to initialize the current state at SHC's startup via a group read telegram to the individual address (thus the
# `init` parameter):

house_central_group = knx_interface.group(KNXGAD(1, 0, 0), "1")
living_room_lights_group = knx_interface.group(KNXGAD(2, 3, 7), "1", init=True)

living_room_lights = shc.Variable(bool, "Living Room Lights")\
    .connect(shc.misc.TwoWayPipe(bool)
                .connect_right(living_room_lights_group)
                .connect_right(house_central_group, send=False))

# Now, we can connect other *connectable* objects to the Variable object, e.g. a switch widget in the UI

web_page.add_item(Switch("Living Room lights", color='yellow')
                  .connect(living_room_lights))

# Value feedback group addresses
# ------------------------------
#
# Similarly, we can listen to feedback group addresses. Let's say:
# - 2/4/1 is programmed a dimming actuator's target percentage datapoint,
# - 2/5/1 is programmed to its percentage value feedback datapoint


kitchen_lights_target_value = knx_interface.group(KNXGAD(2, 4, 1), "5.001")
kitchen_lights_value_feedback = knx_interface.group(KNXGAD(2, 5, 1), "5.001", init=True)

kitchen_lights = shc.Variable(RangeUInt8, "Kitchen Lights")\
    .connect(shc.misc.TwoWayPipe(RangeUInt8)
                .connect_right(kitchen_lights_target_value)
                .connect_right(kitchen_lights_value_feedback, send=False))


# Stateless interaction
# ---------------------
#
# up/down commands for shutters or blinds are stateless. So, we don't use shc Variable objects, but simply connect the
# relevant *connectable* objects directly, e.g. a stateless UI button with the KNX group address ...

living_room_blinds = knx_interface.group(KNXGAD(3, 3, 7), "1.008")

web_page.add_item(ButtonGroup("Living Room Blinds", [
    StatelessButton(KNXUpDown.UP, icon('angle double up')).connect(living_room_blinds),
    StatelessButton(KNXUpDown.DOWN, icon('angle double down')).connect(living_room_blinds),
]))


# ... or a KNX group address with a logic handler function.

@living_room_blinds.trigger
@shc.handler()
def on_living_room_blinds_move(value, _o):
    if value != KNXUpDown.UP:
        return

    print("Living room blinds are moving down ...")
    # TODO do something more interesting


# Emulating a dimming actuator
# ----------------------------
#
# Let's say, we have an LED strip which can be adjusted in brightness by our SHC application via some protocol. It will
# be connected to the following `led_strip_brightness` variable.
# We have a KNX wall switch with dimming function, which sends a single "control dimming" telegram with +100% or -100%
# when pressed and a "control dimming" stop telegram when released. We want to gradually dim our LED strip while the
# button is pressed.

led_strip_brightness = shc.Variable(RangeFloat1, "LED strip brightness")
led_strip_dimming_group = knx_interface.group(KNXGAD(4, 2, 9), "3")

led_strip_brightness\
    .connect(shc.timer.FadeStepRamp(
        shc.misc.ConvertSubscription(led_strip_dimming_group, FadeStep),
        ramp_duration=datetime.timedelta(seconds=5), max_frequency=5.0))
#           ↑ Full range dimming duration: 5 sec           ↑ max value update rate: 5 Hz    (⇒ 25 dimming steps)


if __name__ == '__main__':
    shc.main()
