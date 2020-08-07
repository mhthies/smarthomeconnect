import asyncio
import logging
import datetime
import random

import shc.base
import shc.knx
import shc.variables
import shc.web
import shc.web.widgets
import shc.datatypes
import shc.timer
import shc.supervisor
import shc.persistence

import example_config

knx_connection = shc.knx.KNXConnector()
log_interface = shc.persistence.MySQLPersistence(host="localhost", db="shc", user="shc",
                                                 password=example_config.MYSQL_PASSWORD)

michael_li = shc.variables.Variable(bool, "Licht Michael")\
    .connect(knx_connection.group(shc.knx.KNXGAD(1, 0, 2), "1", init=True))\
    .connect(knx_connection.group(shc.knx.KNXGAD(0, 0, 1), "1"), send=False)\
    .connect(knx_connection.group(shc.knx.KNXGAD(0, 0, 4), "1"), send=False)\
    .connect(log_interface.variable(bool, "og_michael_light"), read=True)

michael_li_lastchange = shc.variables.Variable(datetime.datetime, datetime.datetime.fromtimestamp(0))

michael_li_value = shc.variables.Variable(shc.datatypes.RangeUInt8)\
    .connect(michael_li, convert=True)


@michael_li.trigger
@shc.base.handler()
async def update_lastchange(new_value, source) -> None:
    await michael_li_lastchange.write(datetime.datetime.now())


web_interface = shc.web.WebServer("localhost", 8080, "index")
index_page = web_interface.page("index")

index_page.add_item(shc.web.widgets.Switch(shc.web.widgets.icon("lightbulb outline", "Licht Michael"))
                    .connect(michael_li))
index_page.add_item(shc.web.widgets.ButtonGroup(shc.web.widgets.icon("lightbulb outline", "Licht Michael"), [
    shc.web.widgets.ToggleButton("I", color="yellow").connect(michael_li)]))
index_page.add_item(shc.web.widgets.ButtonGroup(shc.web.widgets.icon("lightbulb outline", "Licht Michael"), [
    shc.web.widgets.DisplayButton(label=shc.web.widgets.icon("power off")).connect(michael_li)]))


michael_heating_mode = shc.variables.Variable(shc.knx.KNXHVACMode, "Heating mode Michael", shc.knx.KNXHVACMode.AUTO)\
    .connect(knx_connection.group(shc.knx.KNXGAD(3, 3, 0), "20.102", init=True))\
    .connect(log_interface.variable(shc.knx.KNXHVACMode, "og_michael_heating_mode"), read=True)
index_page.add_item(shc.web.widgets.EnumSelect(shc.knx.KNXHVACMode)
                    .connect(michael_heating_mode))
index_page.add_item(shc.web.widgets.EnumButtonGroup(shc.knx.KNXHVACMode, "Heating mode", 'red')
                    .connect(michael_heating_mode))
index_page.add_item(shc.web.widgets.ValueListButtonGroup([(shc.knx.KNXHVACMode.COMFORT, "C"),
                                                          (shc.knx.KNXHVACMode.STANDBY, "S"),
                                                          (shc.knx.KNXHVACMode.ECONOMY, "N"),
                                                          (shc.knx.KNXHVACMode.BUILDING_PROTECTION, "F"),],
                                                         "Heating mode", 'red')
                    .connect(michael_heating_mode))

michael_blind_start = knx_connection.group(shc.knx.KNXGAD(2, 2, 9), "1.008")
index_page.add_item(shc.web.widgets.ButtonGroup("Blinds", [
    shc.web.widgets.StatelessButton(shc.knx.KNXUpDown.UP, shc.web.widgets.icon("arrow up"))
    .connect(michael_blind_start),
    shc.web.widgets.StatelessButton(shc.knx.KNXUpDown.DOWN, shc.web.widgets.icon("arrow down"))
    .connect(michael_blind_start),
]))

michael_temp = shc.variables.Variable(float, "Temperature Michael")\
    .connect(knx_connection.group(shc.knx.KNXGAD(3, 3, 2), "9", init=True))\
    .connect(log_interface.variable(float, "og_michael_temperature"))
index_page.add_item(shc.web.widgets.TextDisplay(float, "{:.1f} °C", "Temperatur")
                    .connect(michael_temp))

index_page.add_item(shc.web.widgets.TextDisplay(float, "{:.1f} °C", "Temperatur +5")
                    .connect(michael_temp.EX + 5))

temp_thresh = shc.variables.Variable(bool, "Temperature Threshold").connect((michael_temp.EX + 10) > 35)
index_page.add_item(shc.web.widgets.TextDisplay(bool, "{}", "Temperatur > 25°C?")
                    .connect(temp_thresh))

index_page.add_item(shc.web.widgets.ButtonGroup("Temp > 25", [
    shc.web.widgets.DisplayButton(label=">25°").connect(michael_temp.EX > 25)]))

michael_setpoint_offset = shc.variables.Variable(float, "Setpoint offset Michael")\
    .connect(knx_connection.group(shc.knx.KNXGAD(3, 3, 4), "9", init=True))
index_page.add_item(shc.web.widgets.TextInput(float, "Setpoint offset", min=-5.0, max=5.0, step=0.5, input_suffix="°C")
                    .connect(michael_setpoint_offset))


michael_rl = shc.variables.Variable(shc.datatypes.RangeUInt8, "Blinds Michael")\
    .connect(knx_connection.group(shc.knx.KNXGAD(2, 2, 20), "5.001"))\
    .connect(knx_connection.group(shc.knx.KNXGAD(8, 2, 7), "5.001", init=True), send=False)
index_page.add_item(shc.web.widgets.Slider("RL", color="blue")
                    .connect(michael_rl, convert=True))


@shc.timer.every(datetime.timedelta(seconds=10), align=False)
@shc.base.handler()
async def toggle_light(value, source):
    #await michael_li.write(not await michael_li.read())
    pass

some_color = shc.variables.Variable(shc.datatypes.RGBUInt8, "An RGB Color", shc.datatypes.RGBUInt8(0, 0, 0))
index_page.add_item(shc.web.widgets.TextDisplay(shc.datatypes.RGBUInt8, "{}", "Farbe: ").connect(some_color))


@shc.timer.at(hour=None, minute=shc.timer.EveryNth(2))
@shc.base.handler()
async def change_color(_value, _source):
    await some_color.red.write(shc.datatypes.RangeUInt8(random.randrange(0, 256)))


if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    shc.supervisor.event_loop.set_debug(True)
    shc.supervisor.main()
