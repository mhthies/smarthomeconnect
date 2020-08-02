import asyncio
import logging
import datetime

import shc.base
import shc.knx
import shc.web
import shc.datatypes
import shc.timer
import shc.supervisor


knx_connection = shc.knx.KNXConnector()

michael_li = shc.base.Variable(bool)\
    .connect(knx_connection.group(shc.knx.KNXGAD(1, 0, 2), "1", init=True))\
    .connect(knx_connection.group(shc.knx.KNXGAD(0, 0, 1), "1"), send=False)\
    .connect(knx_connection.group(shc.knx.KNXGAD(0, 0, 4), "1"), send=False)

michael_li_lastchange = shc.base.Variable(datetime.datetime, datetime.datetime.fromtimestamp(0))

michael_li_value = shc.base.Variable(shc.datatypes.RangeUInt8)\
    .connect(michael_li, convert=True)


@michael_li.trigger
@shc.base.handler()
async def update_lastchange(new_value, source) -> None:
    await michael_li_lastchange.write(datetime.datetime.now())


web_interface = shc.web.WebServer("localhost", 8080, "index")
index_page = web_interface.page("index")

index_page.add_item(shc.web.Switch("Licht Michael")
                    .connect(michael_li))


michael_heating_mode = shc.base.Variable(shc.knx.KNXHVACMode, shc.knx.KNXHVACMode.AUTO)\
    .connect(knx_connection.group(shc.knx.KNXGAD(3, 3, 0), "20.102", init=True))
index_page.add_item(shc.web.EnumSelect(shc.knx.KNXHVACMode)
                    .connect(michael_heating_mode))

michael_blind_start = knx_connection.group(shc.knx.KNXGAD(2, 2, 9), "1.008")
index_page.add_item(shc.web.StatelessButton(shc.knx.KNXUpDown.UP, "↑")
                    .connect(michael_blind_start))
index_page.add_item(shc.web.StatelessButton(shc.knx.KNXUpDown.DOWN, "↓")
                    .connect(michael_blind_start))

michael_temp = shc.base.Variable(float)\
    .connect(knx_connection.group(shc.knx.KNXGAD(3, 3, 2), "9", init=True))
index_page.add_item(shc.web.TextDisplay(float, "{:.1f}°C", "Temperatur")
                    .connect(michael_temp))


@shc.timer.every(datetime.timedelta(seconds=10), align=False)
@shc.base.handler()
async def toggle_light(value, source):
    #await michael_li.write(not await michael_li.read())
    pass


if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    shc.supervisor.main()
