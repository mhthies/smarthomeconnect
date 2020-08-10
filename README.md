
# Smart Home Connect

*Smart Home Connect* (SHC) is yet another Python home automation framework—in line with [Home Assistant](https://www.home-assistant.io/), [SmartHome.py](https://mknx.github.io/smarthome/), [SmartHomeNG](https://www.smarthomeng.de/) and probably many more.
Its purpose is to connect "smart home" devices via different communication protocols, provide means for creating automation rules/scripts and a web interface for controling the devices via browser.

In contrast to most other home automation frameworks, SHC is completely based on Python's asynchronous coroutines (asyncio) and configured via pure Python scripts instead of YAML files or a fancy web engineering tool.
Its configuration is based on instantiating *Connectable* objects (like state variables, User Interface Buttons, KNX Group Addresses, etc.) and interconnecting them with simple Read/Subscribe patterns.
Thus, it is quite simple but really powerful, allowing on-the-fly type conversion, expressions for calculating derived values, handling stateless events, ….


## Features

* configuration and definition of automation rules in plain Python
* interfaces
    * KNX bus via KNXD
* websocket-based web user interface (using *aiohttp*, *Jinja2* and *Semantic UI*)
    * widgets: buttons, text display, text/number inputs, dropdowns, … 
* chronological and periodic timers for triggering rules
* Logging/Persistence
    * to MySQL (using *aiomysql*)

### Roadmap

* JSON-over-MQTT interface
* DMX interface
* Extensibility of web interface (additional services via HTTP and websocket)
* HTTP API (GET, POST, websocket-subscribe) + Client
* More web widgets


## Simple Usage Example

```python
import datetime
import shc

# Configure interfaces
knx_connection = shc.knx.KNXConnector()
web_interface = shc.web.WebServer("localhost", 8080, "index")

web_index_page = web_interface.page('index')


# Simple On/Off Variable, connected to KNX Group Address (initialized per Group Read telegram),
# with a switch widget in the web user interface
ceiling_lights = shc.Variable(bool, "ceiling lights")\
    .connect(knx_connection.group(shc.knx.KNXGAD(1, 2, 3), dpt="1", init=True))

web_index_page.add_item(shc.web.widgets.Switch("Ceiling Lights")
                        .connect(ceiling_lights))


# Store timestamp of last change of the ceiling lights in a Variable (via logic handler) and show
# it in the web user interface
ceiling_lights_last_change = shc.Variable(
    datetime.datetime, "ceiling lights last change",
    initial_value=datetime.datetime.fromtimestamp(0))

@ceiling_lights.trigger
@shc.handler()
async def update_lastchange(_new_value, _source):
    await ceiling_lights_last_change.write(datetime.datetime.now())

web_index_page.add_item(
    shc.web.widgets.TextDisplay(datetime.datetime, "{:%c}", "Last Change of Ceiling Lights")
    .connect(ceiling_lights_last_change))


# close shutters via button in the web user interface (stateless event, so no Variable required) 
web_index_page.add_item(shc.web.widgets.ButtonGroup("Shutters", [
    shc.web.widgets.StatelessButton(shc.knx.KNXUpDown.DOWN,
                                    shc.web.widgets.icon("arrow down"))
    .connect(knx_connection.group(shc.knx.KNXGAD(3, 2, 1), dpt="1.008"))
]))

# use expression syntax to switch on fan when temperature is over 25 degrees 
temperature = shc.Variable(float, "temperature")\
    .connect(knx_connection.group(shc.knx.KNXGAD(0, 0, 1), dpt="9", init=True))
fan = shc.Variable(bool, "fan")\
    .connect(knx_connection.group(shc.knx.KNXGAD(0, 0, 2), dpt="1"))\
    .connect(temperature.EX > 25.0)

# Start up SHC
shc.main()
```
