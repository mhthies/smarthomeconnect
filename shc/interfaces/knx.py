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
import math
from typing import List, Any, Dict, Tuple, Optional, Set, Generic, NamedTuple

import knxdclient
from ._helper import SupervisedClientInterface

from .. import datatypes
from ..base import Writable, Subscribable, Reading, T
from ..conversion import register_converter
from ..datatypes import FadeStep

KNXGAD = knxdclient.GroupAddress

logger = logging.getLogger(__name__)


class KNXHVACMode(enum.Enum):
    """
    Python enum representation of the KNX datapoint type 20.102 "DPT_HVACMode", a 8-bit enum of heating/ventilation/AC
    operating modes.

    The value mapping corresponds to KNX' native value encoding of this datatype.
    """
    AUTO = 0
    COMFORT = 1
    STANDBY = 2
    ECONOMY = 3
    BUILDING_PROTECTION = 4


class KNXUpDown(enum.Enum):
    """
    Python enum representation of the KNX datapoint type 1.008 "DPT_UpDown", a 1-bit value for controlling blinds etc.

    Values of this type can also be used as bool values, using the native KNX value mapping (to datapoint type 1.001).
    """
    UP = False
    DOWN = True

    def __bool__(self):
        return self.value


class KNXControlDimming(NamedTuple):
    """
    Python NamedTuple representation of the KNX datapoint type 3.007 "DPT_Control_Dimming" or 3.008
    "DPT_Control_Blinds".

    :param increase: True: Increase dimmer brightness / lower blinds; False: Decrese dimmer brightness / raise blinds
    :param step_exponent: 0: Break dimmming action; 1-7 define step size = 2^(1-stepcode)
    """
    increase: bool
    step_exponent: int

    @property
    def step(self) -> FadeStep:
        if not self.step_exponent:
            return FadeStep(0.0)
        return FadeStep((1 if self.increase else -1) * 2.0 ** (1 - self.step_exponent))

    @classmethod
    def from_step(cls, value: FadeStep) -> "KNXControlDimming":
        increase = True
        val: float = value
        if val < 0:
            increase = False
            val = -val
        # Rounding the logarithm doesn't give us the nearest exponent of two of the original value, but it should be
        # okay in practice.
        return cls(increase, 0 if val == 0.0 else min(7, 1 - round(math.log2(val))))


register_converter(KNXHVACMode, int, lambda v: v.value)
register_converter(int, KNXHVACMode, lambda v: KNXHVACMode(v))
register_converter(KNXUpDown, bool, lambda v: v.value)
register_converter(bool, KNXUpDown, lambda v: KNXUpDown(v))
register_converter(KNXControlDimming, FadeStep, lambda v: v.step)
register_converter(KNXControlDimming, float, lambda v: v.step)
register_converter(FadeStep, KNXControlDimming, lambda v: KNXControlDimming.from_step(v))
register_converter(float, KNXControlDimming, lambda v: KNXControlDimming.from_step(FadeStep(min(1.0, max(-1.0, v)))))
register_converter(datetime.datetime, knxdclient.KNXTime, knxdclient.KNXTime.from_datetime)


KNXDPTs: Dict[str, Tuple[type, knxdclient.KNXDPT]] = {
    '1': (bool, knxdclient.KNXDPT.BOOLEAN),
    '1.008': (KNXUpDown, knxdclient.KNXDPT.BOOLEAN),
    '3': (KNXControlDimming, knxdclient.KNXDPT.BOOLEAN_UINT3),
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


class KNXConnector(SupervisedClientInterface):
    """
    SHC interface for connecting with a KNX home automation bus via KNX deamon (KNXD).

    The interface allows to interact bidirectional with KNX group addresses (i.e. send and receive KNX *group write*
    telegrams). For this purpose a *Connectable* object can be created for each group address, using the :meth:`group`
    method.

    The connection to the KNX bus is established by using KNXDs native client protocol (not via KNX over UDP protocol),
    either via TCP port or via UNIX domain socket. Thus, KNXD must be started with either the `-i` or `-u` option
    (or be run by systemd with an appropriate config for taking care of this). By default, the `KNXConnector` tries to
    connect to KNXDs default TCP port 6720 at localhost. The parameters ``host``, ``port``, and ``sock`` can be used to
    specify another host/port or connect via a local UNIX domain socket instead.

    :param host: Hostname for connecting to KNXD via TCP. Defaults to 'localhost'
    :param port: TCP port where KNXD is listening for client connections at the specified `host`. Defaults to 6720.
    :param sock: Path to the KNXD UNIX domain socket. If given, it is used instead of the TCP connection to host/port.
    :param auto_reconnect: If True (default), the interface tries to reconnect automatically with exponential backoff
        (5 * 1.25^n seconds sleep), when connection to KNXD is lost. Otherwise, the complete SHC system is shut down
        on connection errors.
    :param read_init_after_reconnect: If True (default), the *group read* telegrams for initialization (according to the
        `init` parameter of :meth:`group`) are resent when reconnecting after a connection loss to compensate for
        possibly missed value updates on the KNX bus.
    :param failsafe_start: If True, the KNXD client allows SHC to start up, even if the connection to KNXD can not be
        established in the first try. The connection is retried in background with exponential backoff (see
        `auto_reconnect` option). Otherwise (default), the first connection attempt on startup is not retried and will
        shutdown the SHC application on failure, even if `auto_reconnect` is True.
    """
    def __init__(self, host: str = 'localhost', port: int = 6720, sock: Optional[str] = None,
                 auto_reconnect: bool = True, read_init_after_reconnect: bool = True, failsafe_start: bool = False):
        super().__init__(auto_reconnect, failsafe_start)
        self.backoff_base = 5
        self.host = host
        self.port = port
        self.sock = sock
        self.read_init_after_reconnect = read_init_after_reconnect
        self.groups: Dict[KNXGAD, KNXGroupVar] = {}
        self.knx = knxdclient.KNXDConnection()
        self.knx.set_group_apdu_handler(self._dispatch_telegram)
        self.init_request_groups: Set[KNXGAD] = set()
        self._first_connect = True

    async def _connect(self) -> None:
        await self.knx.connect(self.host, self.port, self.sock)

    async def _subscribe(self) -> None:
        await self.knx.open_group_socket()
        if self._first_connect or self.read_init_after_reconnect:
            await self._send_init_requests()
        self._first_connect = False

    async def _run(self):
        self._running.set()
        await self.knx.run()

    async def _disconnect(self) -> None:
        await self.knx.stop()

    def group(self, addr: KNXGAD, dpt: str, init: bool = False) -> "KNXGroupVar":
        """
        Create a *Connectable* object for sending and receiving KNX telegrams for a given group address.

        The returned object is *Subscribable* for receiving updates (group write and group response telegrams) from the
        KNX system and *Writable* to send a new value to the KNX system. It is also optionally *Reading*. If a
        `default_provider` is set (e.g. via the read/provide parameter of
        :meth:`connect <shc.base.Connectable.connect>`), this `KNXConnector` actively responds to *group read* telegrams
        from the KNX system by sending a *group response* with the read value.

        To ensure correct data encoding, the KNX datapoint type of the group address must be specified. It **must** be
        equal to the datapoint type of other KNX devices' datapoints which are connected to this group address. The
        returned *Connectable's* `type` is derived from the KNX datapoint type. The following KNX datapoint types (DPT)
        are supported:

        +----------+---------------------------------------+
        | KNX DPT  | Python `type`                         |
        +==========+=======================================+
        | '1'      | :class:`bool`                         |
        +----------+---------------------------------------+
        | '1.008'  | :class:`KNXUpDown`                    |
        +----------+---------------------------------------+
        | '3'      | :class:`KNXControlDimming`            |
        +----------+---------------------------------------+
        | '4'      | :class:`str`                          |
        +----------+---------------------------------------+
        | '5'      | :class:`int`                          |
        +----------+---------------------------------------+
        | '5.001'  | :class:`shc.datatypes.RangeUInt8`     |
        +----------+---------------------------------------+
        | '5.003'  | :class:`shc.datatypes.AngleUInt8`     |
        +----------+---------------------------------------+
        | '5.004'  | :class:`shc.datatypes.RangeInt0To100` |
        +----------+---------------------------------------+
        | '6'      | :class:`int`                          |
        +----------+---------------------------------------+
        | '7'      | :class:`int`                          |
        +----------+---------------------------------------+
        | '8'      | :class:`int`                          |
        +----------+---------------------------------------+
        | '9'      | :class:`float`                        |
        +----------+---------------------------------------+
        | '10'     | :class:`knxdclient.KNXTime`           |
        +----------+---------------------------------------+
        | '11'     | :class:`datetime.date`                |
        +----------+---------------------------------------+
        | '12'     | :class:`int`                          |
        +----------+---------------------------------------+
        | '13'     | :class:`int`                          |
        +----------+---------------------------------------+
        | '14'     | :class:`float`                        |
        +----------+---------------------------------------+
        | '16'     | :class:`str`                          |
        +----------+---------------------------------------+
        | '17'     | :class:`int`                          |
        +----------+---------------------------------------+
        | '19'     | :class:`datetime.datetime`            |
        +----------+---------------------------------------+
        | '20.102' | :class:`KNXHVACMode`                  |
        +----------+---------------------------------------+

        When `group` is called multiple times with the same group address, a reference to the **same** *Connectable*
        object is returned. This ensures, that dispatching of incoming messages and local feedback (see below) always
        work correctly and checks on the `origin` of a new value don't behave unexpectedly. However, the datapoint type
        given in all calls for the same group address must match. Otherwise, a `ValueError` is raised.

        The *Connectable* object for each group address features an internal local feedback. This means, that every
        new value *written* to the object is being published to all other local subscribers, **after** being transmitted
        to the KNX system. Thus, the KNX group address behaves "bus-like", for the connected objects within SHC: When
        one connected object sends a new value to the KNX bus, its received by all KNX devices and all other connected
        objects as well, which is important for central functions etc.

        :param addr: The KNX group address to connect to, represented as a :class:`KNXGAD` object
        :param dpt: The KNX datapoint type (DPT) number as string according to the table above
        :param init: If True, the interface will send a *group read* telegram to this group address after SHC's startup.
            This can be used to initialize subscribed SHC variables with the current value from the KNX system, if
            there's a KNX device responding to read requests for this group address (i.e. which has the *read* flag set
            on the relevant datapoint).
        :return: The *Connectable* object representing the group address
        :raise ValueError: If `group` has been called before with the same group address but a different datapoint type
        """
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

    def _dispatch_telegram(self, packet: knxdclient.ReceivedGroupAPDU) -> None:
        if packet.payload.type is knxdclient.KNXDAPDUType.READ:
            if packet.dst in self.groups:
                asyncio.create_task(self._respond_read_request(self.groups[packet.dst]))
        else:
            try:
                group_var = self.groups[packet.dst]
            except KeyError:
                logging.debug("No KNX Group Variable for Addr %s registered", packet.dst)
                return
            group_var.update_from_bus(packet.payload.value, [packet.src])

    async def _respond_read_request(self, group_var: "KNXGroupVar") -> None:
        try:
            encoded_data = await group_var.read_from_bus()
            if encoded_data is not None:
                await self.knx.group_write(group_var.addr, knxdclient.KNXDAPDUType.RESPONSE, encoded_data)
        except Exception as e:
            logger.warning("Error while responding to KNX group read request for %s:", group_var.addr, exc_info=e)

    async def send(self, addr: knxdclient.GroupAddress, encoded_data: knxdclient.EncodedData):
        await self.knx.group_write(addr, knxdclient.KNXDAPDUType.WRITE, encoded_data)
        await asyncio.sleep(0.15)  # wait a bit longer to be sure, that the telegram has been sent to the bus

    def __repr__(self) -> str:
        return "{}(host={}, port={}, sock={})".format(self.__class__.__name__, self.host, self.port, self.sock)


class KNXGroupVar(Subscribable[T], Writable[T], Reading[T], Generic[T]):
    _stateful_publishing = True

    def __init__(self, connector: KNXConnector, addr: KNXGAD, dpt: str):
        if dpt not in KNXDPTs:
            raise ValueError("KNX Datapoint Type {} is not supported".format(dpt))
        self.type = KNXDPTs[dpt][0]
        super().__init__()
        self.dpt = dpt
        self.knx_major_dpt = KNXDPTs[dpt][1]
        self.connector = connector
        self.addr = addr

    def update_from_bus(self, data: knxdclient.EncodedData, origin: List[Any]) -> None:
        value: T = knxdclient.decode_value(data, self.knx_major_dpt)
        if type(value) is not self.type:
            value = self.type(*value) if issubclass(self.type, tuple) else self.type(value)  # type: ignore
        logger.debug("Got new value %s for KNX Group variable %s from bus", value, self.addr)
        self._publish(value, origin)

    async def read_from_bus(self) -> Optional[knxdclient.EncodedData]:
        value = await self._from_provider()
        if value is not None:
            return knxdclient.encode_value(value, self.knx_major_dpt)
        return None

    async def _write(self, value: T, origin: List[Any]) -> None:
        self._publish(value, origin)
        encoded_data = knxdclient.encode_value(value, self.knx_major_dpt)
        await self.connector.send(self.addr, encoded_data)

    def __repr__(self) -> str:
        return "{}(GAD={})".format(self.__class__.__name__, self.addr)
