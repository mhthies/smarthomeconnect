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
@shc.base.handler
async def update_lastchange(new_value, source) -> None:
    await michael_li_lastchange.write(datetime.datetime.now())


web_interface = shc.web.WebServer("localhost", 8080, "index")
index_page = web_interface.page("index")

sw_item = shc.web.Switch("Licht Michael")
sw_item.subscribe(michael_li)
sw_item.set_provider(michael_li)
michael_li.subscribe(sw_item)
index_page.add_item(sw_item)


@shc.timer.every(datetime.timedelta(seconds=10), align=False)
@shc.base.handler
async def toggle_light(value, source):
    #await michael_li.write(not await michael_li.read())
    pass


if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    shc.supervisor.main()
