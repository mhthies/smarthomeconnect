
# Smart Home Connect

*Smart Home Connect* (SHC) is yet another Python home automation framework—in line with [Home Assistant](https://www.home-assistant.io/), [SmartHome.py](https://mknx.github.io/smarthome/) and probably many more.
Its purpose is to connect "smart home" devices via different communication protocols, provide means for creating automation rules/scripts and a web interface for controling the devices via browser.

In contrast to most other home automation frameworks, SHC is completely based on Python's asynchronous coroutines (asyncio) and configured via Python scripts instead of YAML files or a fancy web engineering tool. 


## Features

* interfaces
    * KNX bus via KNXd 
* websocket-based web user interface (using aiohttp, Jinja2 and Semantic UI)
* interaction with logic rules in plain Python
* chronological and periodic timers for triggering rules
* Logging/Persistence
    * to MySQL (using aiomysql)

### Roadmap

* JSON-over-MQTT interface
* DMX interface
* HTTP API (GET, POST, websocket-subscribe) + Client
