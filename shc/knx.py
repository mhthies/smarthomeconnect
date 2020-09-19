# Copyright 2020 Michael Thies <mail@mhthies.de>
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may not use this file except in compliance with
# the License. You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software distributed under the License is distributed on an
# "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the License for the
# specific language governing permissions and limitations under the License.

import asyncio
import datetime
import enum
import logging
from typing import List, Any, Dict, Tuple, Optional, Set

import knxdclient
from . import datatypes
from .base import Writable, Subscribable, Reading, T
from .conversion import register_converter
from .supervisor import register_interface

KNXGAD = knxdclient.GroupAddress

logger = logging.getLogger(__name__)


class KNXHVACMode(enum.Enum):
    AUTO = 0
    COMFORT = 1
    STANDBY = 2
    ECONOMY = 3
    BUILDING_PROTECTION = 4


class KNXUpDown(enum.Enum):
    UP = False
    DOWN = True

    def __bool__(self):
        return self.value


register_converter(KNXHVACMode, int, lambda v: v.value)
register_converter(int, KNXHVACMode, lambda v: KNXHVACMode(v))
register_converter(KNXUpDown, bool, lambda v: v.value)
register_converter(bool, KNXUpDown, lambda v: KNXUpDown(v))
register_converter(datetime.datetime, knxdclient.KNXTime, knxdclient.KNXTime.from_datetime)


KNXDPTs: Dict[str, Tuple[type, knxdclient.KNXDPT]] = {
    '1': (bool, knxdclient.KNXDPT.BOOLEAN),
    '1.008': (KNXUpDown, knxdclient.KNXDPT.BOOLEAN),
    '4': (str, knxdclient.KNXDPT.CHAR),
    '5': (int, knxdclient.KNXDPT.UINT8),
    '5.001': (datatypes.RangeUInt8, knxdclient.KNXDPT.UINT8),
    '5.003': (datatypes.AngleUInt8, knxdclient.KNXDPT.UINT8),
    '5.004': (datatypes.RangeInt0To100, knxdclient.KNXDPT.UINT8),
    '6': (int, knxdclient.KNXDPT.INT8),
    '7': (int, knxdclient.KNXDPT.UINT16),
    '8': (int, knxdclient.KNXDPT.INT16),
    '9': (float, knxdclient.KNXDPT.FLOAT16),
    '10': (knxdclient.KNXTime, knxdclient.KNXDPT.TIME),
    '11': (datetime.date, knxdclient.KNXDPT.DATE),
    '12': (int, knxdclient.KNXDPT.UINT32),
    '13': (int, knxdclient.KNXDPT.INT32),
    '14': (float, knxdclient.KNXDPT.FLOAT32),
    '16': (str, knxdclient.KNXDPT.STRING),
    '17': (int, knxdclient.KNXDPT.SCENE_NUMBER),
    '19': (datetime.datetime, knxdclient.KNXDPT.DATE_TIME),
    '20.102': (KNXHVACMode, knxdclient.KNXDPT.ENUM8),
}


class KNXConnector:
    def __init__(self, host: str = 'localhost', port: int = 6720, sock: Optional[str] = None):
        self.host = host
        self.port = port
        self.sock = sock
        self.groups: Dict[KNXGAD, KNXGroupVar] = {}
        self.knx = knxdclient.KNXDConnection()
        self.knx.register_telegram_handler(self._dispatch_telegram)
        self.knx_run_task: asyncio.Task
        self.init_request_groups: Set[KNXGAD] = set()
        register_interface(self)

    async def start(self):
        await self.knx.connect(self.host, self.port, self.sock)
        self.knx_run_task = asyncio.create_task(self.knx.run())
        await self.knx.open_group_socket()
        await self._send_init_requests()

    async def wait(self):
        await self.knx_run_task

    async def stop(self):
        await self.knx.stop()

    def group(self, addr: KNXGAD, dpt: str, init: bool = False) -> "KNXGroupVar":
        if addr in self.groups:
            group_var = self.groups[addr]
            if group_var.dpt != dpt:
                raise ValueError("KNX Datapoint Type conflict: Group Variable {} has been created with type {} before"
                                 .format(group_var.addr, group_var.dpt))
        else:
            group_var = KNXGroupVar(self, addr, dpt)
            self.groups[addr] = group_var
        if init:
            self.init_request_groups.add(addr)
        return group_var

    async def _send_init_requests(self):
        await asyncio.gather(*(self.knx.group_write(addr, knxdclient.KNXDAPDUType.READ, 0)
                               for addr in self.init_request_groups))

    async def _dispatch_telegram(self, packet: knxdclient.ReceivedGroupAPDU) -> None:
        if packet.payload.type is knxdclient.KNXDAPDUType.READ:
            if packet.dst in self.groups:
                encoded_data = await self.groups[packet.dst].read_from_bus()
                if encoded_data is not None:
                    await self.knx.group_write(packet.dst, knxdclient.KNXDAPDUType.RESPONSE, encoded_data)
        else:
            try:
                group_var = self.groups[packet.dst]
            except KeyError:
                logging.debug("No KNX Group Variable for Addr %s registered", packet.dst)
                return
            await group_var.update_from_bus(packet.payload.value, [packet.src])

    async def send(self, addr: knxdclient.GroupAddress, encoded_data: knxdclient.EncodedData):
        await self.knx.group_write(addr, knxdclient.KNXDAPDUType.WRITE, encoded_data)


class KNXGroupVar(Subscribable, Writable, Reading):
    def __init__(self, connector: KNXConnector, addr: KNXGAD, dpt: str):
        if dpt not in KNXDPTs:
            raise ValueError("KNX Datapoint Type {} is not supported".format(dpt))
        self.type = KNXDPTs[dpt][0]
        super().__init__()
        self.dpt = dpt
        self.knx_major_dpt = KNXDPTs[dpt][1]
        self.connector = connector
        self.addr = addr

    async def update_from_bus(self, data: knxdclient.EncodedData, origin: List[Any]) -> None:
        value = self.type(knxdclient.decode_value(data, self.knx_major_dpt))
        logger.debug("Got new value %s for KNX Group variable %s from bus", value, self.addr)
        await self._publish(value, origin)

    async def read_from_bus(self) -> Optional[knxdclient.EncodedData]:
        value = await self._from_provider()
        if value is not None:
            return knxdclient.encode_value(value, self.knx_major_dpt)
        return None

    async def _write(self, value: T, origin: List[Any]) -> None:
        encoded_data = knxdclient.encode_value(value, self.knx_major_dpt)
        await self.connector.send(self.addr, encoded_data)
        await self._publish(value, origin)

    def __repr__(self) -> str:
        return "{}(GAD={})".format(self.__class__.__name__, self.addr)
