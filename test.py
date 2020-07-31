import asyncio
import logging
import datetime

import shc.base
import shc.knx
import shc.web
import shc.datatypes


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


web_interface = shc.web.WebServer("index")
index_page = web_interface.page("index")

sw_item = shc.web.Switch("Licht Michael")
sw_item.subscribe(michael_li)
sw_item.set_provider(michael_li)
michael_li.subscribe(sw_item)
index_page.add_item(sw_item)


async def main():
    knx_task = asyncio.create_task(knx_connection.run())
    web_task = asyncio.create_task(web_interface.run())
    await asyncio.sleep(5)
    #await michael_li.write(True, ["main"])
    await asyncio.sleep(5)
    #await michael_li.write(False, ["main"])
    await asyncio.sleep(5)
    await knx_connection.stop()
    await web_interface.stop()
    await knx_task
    await web_task

if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    asyncio.run(main(), debug=True)
