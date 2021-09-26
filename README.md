
# Smart Home Connect

[![GitHub Actions CI Status](https://github.com/mhthies/smarthomeconnect/workflows/build/badge.svg)](https://github.com/mhthies/smarthomeconnect/actions?query=workflow%3Abuild)
[![codecov](https://codecov.io/gh/mhthies/smarthomeconnect/branch/master/graph/badge.svg)](https://codecov.io/gh/mhthies/smarthomeconnect)
[![Documentation Status at readthedocs.io](https://readthedocs.org/projects/smarthomeconnect/badge/?version=latest)](https://smarthomeconnect.readthedocs.io/en/latest/?badge=latest)
[![Latest PyPI version](https://badge.fury.io/py/smarthomeconnect.svg)](https://pypi.org/project/smarthomeconnect/)


*Smart Home Connect* (SHC) is yet another Python home automation framework—in line with [Home Assistant](https://www.home-assistant.io/), [SmartHome.py](https://mknx.github.io/smarthome/), [SmartHomeNG](https://www.smarthomeng.de/) and probably many more.
Its purpose is to connect "smart home" devices via different communication protocols, provide means for creating automation rules/scripts and a web interface for controling the devices via browser.

In contrast to most other home automation frameworks, SHC is completely based on Python's asynchronous coroutines (asyncio) and configured via pure Python scripts instead of YAML files or a fancy web engineering tool.
Its configuration is based on instantiating *Connectable* objects (like state variables, User Interface Buttons, KNX Group Addresses, etc.) and interconnecting them with simple Read/Subscribe patterns.
Thus, it is quite simple but really powerful, allowing on-the-fly type conversion, expressions for calculating derived values, handling stateless events, ….
Read more about SHC's base concepts [in the documentation](https://smarthomeconnect.readthedocs.io/en/latest/base.html).


## Features

* interfaces
    * KNX bus via KNXD
    * DMX (via Enttec DMX USB Pro and compatible interfaces)
    * HTTP/REST API + websocket API
    * SHC client (connecting to another SHC instance via websocket API)
    * MIDI
    * MQTT
    * [Tasmota](https://github.com/arendst/tasmota/) (currently: relais, RGB+CCW lights, IR receiver, power sensors; more features will be added on demand)
* websocket-based web user interface (using *aiohttp*, *Jinja2* and *Semantic UI*)
    * widgets: buttons, text display, text/number inputs, dropdowns, images with placeable buttons, charts, etc., … 
* configuration of data points/variables and automation rules in plain Python
    * full power of Python + intuitive representation and interconnection of different interfaces 
    * type checking and extensible type conversion system
    * connecting objects via Python expressions
* chronological and periodic timers for triggering rules 
* Logging/Persistence (no really stable in API yet)
    * to MySQL

### Roadmap

* Stabilize logging API
* Logging to Influx-DB
* More web widgets
    * Gauges
    * timeline/"stripe" charts


## Getting started

0. (Optional) Create a virtual environment to keep your Python package repositories clean:
   ```bash
   python3 -m virtualenv -p python3 venv
   . venv/bin/activate
   ```
   Read more about virtual environments [in the offical Python docs](https://docs.python.org/3/tutorial/venv.html).
  
1. Install the `smarthomeconnect` Python distribution from PyPI:
   ```bash
   pip3 install smarthomeconnect
   ```
   It will be only install smarthomeconnect and the dependencies of its core features.
   Additional depdencies are required for certain interface modules and can be installed via pip's/setuptool's 'extras' feature.
   See [Depdencies section](#Dependencies) of this readme for a complete list.
   If you install SHC from a source distribution (in contrast to a "binary" package, such as a "wheel" package from PyPI), you'll need NodeJS and npm installed on your machine, which are used to download the web UI assets during the Python package building process. 

2. Create a Python script (let's call it `my_home_automation.py`) which imports and starts Smart Home Connect:
   ```python
   #!/usr/bin/env python3
   import shc

   # TODO add interfaces and Variables
  
   shc.main()
   ```
   When running this script (`python3 my_home_authomation.py`), SHC should start and exit (successfully) immediately, since no interfaces are defined.
   See the code below for an example with the Web UI and the KNX interface.

3. Read about the basic concepts of SHC and available interfaces in the [SHC documentation](https://smarthomeconnect.readthedocs.io/en/latest/).
   Extend your script to create interfaces and Variables, *connect* connectable objects, define logic handlers and let them be triggered.


## Simple Usage Example

```python
import datetime
import shc
import shc.web
import shc.interfaces.knx

# Configure interfaces
knx_connection = shc.interfaces.knx.KNXConnector()
web_interface = shc.web.WebServer("localhost", 8080, "index")

web_index_page = web_interface.page('index')


# Simple On/Off Variable, connected to KNX Group Address (initialized per Group Read telegram),
# with a switch widget in the web user interface
ceiling_lights = shc.Variable(bool, "ceiling lights")\
    .connect(knx_connection.group(shc.interfaces.knx.KNXGAD(1, 2, 3), dpt="1", init=True))

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
    shc.web.widgets.StatelessButton(shc.interfaces.knx.KNXUpDown.DOWN,
                                    shc.web.widgets.icon("arrow down"))
    .connect(knx_connection.group(shc.interfaces.knx.KNXGAD(3, 2, 1), dpt="1.008"))
]))

# use expression syntax to switch on fan when temperature is over 25 degrees 
temperature = shc.Variable(float, "temperature")\
    .connect(knx_connection.group(shc.interfaces.knx.KNXGAD(0, 0, 1), dpt="9", init=True))
fan = shc.Variable(bool, "fan")\
    .connect(knx_connection.group(shc.interfaces.knx.KNXGAD(0, 0, 2), dpt="1"))\
    .connect(temperature.EX > 25.0)

# Start up SHC
shc.main()
```


## License

Smart Home Connect is published under the terms of the Apache License 2.0.

It's bundled with multiple third party works:

* [“Prism”](https://www.toptal.com/designers/subtlepatterns/prism/) – Subtle Patterns by Toptal Designers (Creative Commons BY-SA 3.0)

See `LICENSE` and `NOTICE` file for further information.


## Dependencies

SHC depends on the following Python packages:

* `aiohttp` and its dependencies (Apache License 2.0, MIT License, Python Software Foundation License, LGPL 2.1, 3-Clause BSD License)
* `jinja2` and `MarkupSafe` (BSD-3-Clause License)

Additional dependencies are required for some of SHC's interfaces.
They can be installed automatically via pip, by specifying the relevant 'extras' flag, e.g. `pip install smarthomeconnect[mysql]` for mysql logging support. 
 
* Logging via MySQL `[mysql]`:
    * `aiomysql` and `PyMySQL` (MIT License)
* KNX interface `[knx]`:
    * `knxdclient` (Apache License 2.0)
* DMX interface `[dmx]`:
    * `pyserial-asyncio` & `pySerial` (BSD-3-Clause License)
* MIDI interface `[midi]`:
    * `mido` (MIT License)
    * `python-rtmidi` (MIT License) incl. RTMidi (modified MIT License)
* MQTT interface `[mqtt]`:
    * `paho-mqtt` (Eclipse Public License v1.0 *or* Eclipse Distribution License v1.0)
    * `asyncio-mqtt` (BSD-3-Clause License)

In addition, the following Javascript libraries from NPM are required for the web UI frontend.
They are not included in this repository or in source distribution packages of SHC.
Instead they are downloaded and packed during Python package build and bundled in the "binary" Python packages (including "wheel" packages) of SHC:

* [Fomantic UI CSS framework](https://fomantic-ui.com/) (MIT License)
* [jQuery](https://jquery.com/) (MIT License)
* [iro.js](https://iro.js.org/) (Mozilla Public License 2.0)
* [Chart.js](https://www.chartjs.org//) (MIT License)


## Development

Feel free to open an issue on GitHub if you miss a feature or find an unexpected behaviour or bug. 
Please, consult the [documentation](https://smarthomeconnect.readthedocs.io/en/latest/) on the relevant topic and search the GitHub issues for existing reports of the issue first.

If you want to help with the development of *Smart Home Connect*, your Pull Requests are always appreciated.

Setting up a dev environment for SHC is simple:
Clone the git repository and install the development dependencies, listed in `requirements.txt` (+ the `python-rtmidi` module if you want to run the MIDI tests).
These include all dependencies of smarthomeconnect with all extras:
```bash
git clone https://github.com/mhthies/smarthomeconnect
cd smarthomeconnect
pip3 install -r requirements.txt
pip3 install python-rtmidi
```
You may want to use a virtual environment to avoid messing up your Python packages.

Additionally, you'll need NodeJS and NPM on your machine for downloading and packing the web UI frontend asset  files.
Use the following commands to download all frontend dependencies from NPM and package them into `/shc/web/static` (using Parcel.js):
```bash
npm install
npm run build
```
When working on the web UI source files themselves (which are located in `web_ui_src`), you'll probably want to run Parcel.js in monitor mode, providing automatic re-packing and reload on every change:
```bash
npx parcel web_ui_src/main.js --out-dir shc/web/static/pack --public-url ./
```

Please make sure that all the unittests are passing, when submitting a Pull Request:
```bash
python3 -m unittest
```
The web tests require Firefox and `geckodriver` to be installed on your system and the frontend assets. 

Additionally, I'd like to keep the test coverage on a high level.
To check it, you may want to determine it locally, using the `coverage` tool:
```bash
coverage run -m unittest
coverage html
``` 
