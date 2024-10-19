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
A simple SHC example, providing a web interface to control and supervise the default sink of the local Pulseaudio
server.
"""
from typing import cast, Iterable

import shc
import shc.web
import shc.interfaces.pulse
from shc.web.widgets import AbstractButton, Slider, ButtonGroup, ToggleButton, icon, DisplayButton

interface = shc.interfaces.pulse.PulseAudioInterface()
sink_name = None

volume = shc.Variable(shc.interfaces.pulse.PulseVolumeComponents, "volume")\
    .connect(interface.default_sink_volume(), convert=True)
active = shc.Variable(bool, "active")\
    .connect(interface.default_sink_running())
mute = shc.Variable(bool, "mute")\
    .connect(interface.default_sink_muted())


web_interface = shc.web.WebServer('localhost', 8080, 'index')
page = web_interface.page('index', "Home")
page.add_item(Slider("Volume").connect(volume.field('volume')))
page.add_item(Slider("Balance").connect(volume.field('balance'), convert=True))
page.add_item(Slider("Fade").connect(volume.field('fade'), convert=True))
page.add_item(ButtonGroup("", cast(Iterable[AbstractButton], [
    ToggleButton(icon('volume mute')).connect(mute),
    DisplayButton(label=icon('power off')).connect(active),
])))

if __name__ == '__main__':
    shc.main()
