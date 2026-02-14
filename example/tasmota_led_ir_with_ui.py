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

import datetime
import logging

import shc.interfaces.in_memory_data_logging
from shc.datatypes import RangeFloat1, RGBUInt8
from shc.interfaces.mqtt import MQTTClientInterface
from shc.interfaces.tasmota import TasmotaInterface
import shc.web
from shc.web.log_widgets import LogListDataSpec
from shc.web.widgets import Switch, Slider, DisplayButton, ButtonGroup, icon

mqtt = MQTTClientInterface()
# a tasmota RGB (or RGBW) lamp/LED strip with IR receiver
tasmota_led = TasmotaInterface(mqtt, 'my_tasmota_device_topic')

# Create a Web server with a single index page
web_server = shc.web.WebServer('', 8081, index_name='index')
index_page = web_server.page('index', 'Home', menu_entry=True, menu_icon='home')

# Create an in-memory log for the IR commands received in the last 10 minutes
ir_log = shc.interfaces.in_memory_data_logging.InMemoryDataLogVariable(str, keep=datetime.timedelta(minutes=10))
# Show the logged IR commands in a list view on the web page
index_page.add_item(shc.web.log_widgets.LogListWidget(datetime.timedelta(minutes=5), [
    LogListDataSpec(ir_log)
]))
# Send the IR commands received by the Tasmota device to the in-memory log
tasmota_led.ir_receiver().connect(ir_log, convert=(lambda v: v.hex(), lambda x: x.encode()))

# State variables for on/off, dimmer and RGB color of the Tasmota device
power = shc.Variable(bool)\
    .connect(tasmota_led.power())
dimmer = shc.Variable(RangeFloat1)\
    .connect(tasmota_led.dimmer(), convert=True)
color = shc.Variable(RGBUInt8)\
    .connect(tasmota_led.color_rgb())

# Show an indicator for the MQTT connection state of the Tasmota device on the web page
index_page.add_item(ButtonGroup("Online?", [
    DisplayButton(label=icon('plug'), color="teal").connect(tasmota_led.online()),
]))
# Add UI controls for the on/off state and the dimmer value
index_page.add_item(Switch("Power").connect(power))
index_page.add_item(Slider("Dimmer").connect(dimmer))

# Add UI controls for the the RGB color components
index_page.new_segment()
index_page.add_item(Slider("Rot", color='red').connect(color.field('red'), convert=True))
index_page.add_item(Slider("Grün", color='green').connect(color.field('green'), convert=True))
index_page.add_item(Slider("Blau", color='blue').connect(color.field('blue'), convert=True))


if __name__ == '__main__':
    logging.basicConfig(level=logging.DEBUG)
    shc.main()
