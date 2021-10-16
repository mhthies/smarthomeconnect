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
"""
This module provides SHC interface implementations to control DMX lighting equipment from SHC.

Simple usage example::

    import shc
    import shc.interfaces.dmx
    from shc.datatypes import RangeUInt8, RGBFloat1

    dmx_interface = shc.interfaces.dmx.EnttecDMXUSBProConnector(serial_url="/dev/ttyUSB3",
                                                                universe_size=10)  # improves transmission speed

    dimmer_1 = shc.Variable(RangeUInt8, "dimmer 1").connect(dmx_interface.address(1))
    dimmer_2 = shc.Variable(RangeUInt8, "dimmer 2").connect(dmx_interface.address(2))
    # ...

    rgb_par = shc.Variable(RGBUInt8, "LED PAR")
    rgb_par.field('red').connect(dmx_interface.address(7))
    rgb_par.field('green').connect(dmx_interface.address(8))
    rgb_par.field('blue').connect(dmx_interface.address(9))

(see :ref:`variables.tuple_field_access` for an explanation why accessing the RGB colors works this way.)
"""

import abc
import enum
import logging
from typing import List, Any, NamedTuple, Optional

import serial_asyncio
import asyncio

from ..base import Writable
from ..datatypes import RangeUInt8
from ..supervisor import AbstractInterface

logger = logging.getLogger(__name__)


class AbstractDMXConnector(AbstractInterface, metaclass=abc.ABCMeta):
    """
    Abstract base class for DMX output interfaces.

    Concrete implementations, included with SHC, for specific protocols are:

    * :class:`EnttecDMXUSBProConnector`

    Instances of these classes provide a method :meth:`address` to create a `writable` object for a given DMX channel.
    """
    def __init__(self, universe_size: int = 512):
        super().__init__()
        self.universe = [0] * universe_size

    def address(self, dmx_address: int) -> "DMXAddress":
        """
        Get a *Writable* object for a specific DMX channel

        The expected value type is :class:`shc.datatypes.RangeUInt8`.

        :param dmx_address: The DMX channel address from 1 to 512
        :return: A *Writable* object for that DMX channel
        """
        return DMXAddress(self, dmx_address)

    @abc.abstractmethod
    async def transmit(self) -> None:
        """
        Abstract coroutine to trigger the transmission of the cached DMX universe to the DMX interface.

        This method is automatically called by :meth:`DMXAddress.write`.

        Concrete implementations of this method should make sure to await the successful transmission of the current
        universe state to the hardware interface. This might include waiting for the flushing of the serial buffer.
        """
        pass


class DMXAddress(Writable[RangeUInt8]):
    """
    `Writable` object of type :class:`RangeUInt8`, representing a single DMX channel of a :class:`AbstractDMXConnector`.

    Writing a value to a `DMXAddress` object sets the corresponding channel in the cached DMX universe to that value and
    triggers transmission of the universe to the hardware DMX interface.
    """
    type = RangeUInt8

    def __init__(self, connector: AbstractDMXConnector, address: int) -> None:
        self.address = address  # DMX channel address from 1 to 512
        self.connector = connector

    async def _write(self, value: RangeUInt8, origin: List[Any]) -> None:
        logger.debug("New value for DMX address %s: %s", self.address, value)
        self.connector.universe[self.address - 1] = value
        await self.connector.transmit()


class EnttecDMXUSBProConnector(AbstractDMXConnector):
    """
    A DMX Interface for the Enttec DMX USB PRO and compatible devices (with the same serial protocol).
    """
    # Build according to this spec:
    # https://web.archive.org/web/20200822142042/https://dol2kh495zr52.cloudfront.net/pdf/misc/dmx_usb_pro_api_spec.pdf

    def __init__(self, serial_url: str, universe_size: int = 512) -> None:
        super().__init__(universe_size)
        self.serial_url = serial_url
        self.running_transmit: Optional[asyncio.Future] = None
        self.next_transmit: Optional[asyncio.Future] = None

    async def start(self):
        logger.info("Starting Enttec DMX USB Pro interface on serial port %s ...", self.serial_url)
        self._reader, self._writer = await serial_asyncio.open_serial_connection(url=self.serial_url)
        await self._transmit()

    async def stop(self):
        logger.info("Closing serial port %s ...", self.serial_url)
        self._writer.close()
        await self._writer.wait_closed()

    @staticmethod
    def _universe_to_enttec(universe: List[int]) -> "EnttecMessage":
        """ Helper method to serialize a DMX universe (as List[int]) into an EnttacMessage to be sent to the DMX
        interface """
        DMX_LIGHTNING_DATA_START_CODE = 0
        data = bytes([DMX_LIGHTNING_DATA_START_CODE] + universe + [0] * (24 - len(universe)))
        return EnttecMessage(EntTecMessageLabel.OUTPUT_ONLY_SEND_DMX_PACKET, data)

    async def transmit(self) -> None:
        # In case, there is no running _transmit call, create a new one
        if not self.running_transmit or self.running_transmit.done():
            logger.debug("Immediately transmitting DMX data to interface ...")
            self.running_transmit = asyncio.create_task(self._transmit())
            await self.running_transmit
            logger.debug("DMX transmit finished ...")

        # In case there is already a running _transmit call, create a Future for the next _transmit call, await the
        # completion of the current _transmit, create a new _transmit call, and finally update the Future with its
        # result.
        elif not self.next_transmit:
            logger.debug("DMX transmit is already running. Queuing next transmit ...")
            self.next_transmit = asyncio.Future()
            await self.running_transmit
            logger.debug("Starting queued DMX transmit ...")
            self.running_transmit = self.next_transmit
            self.next_transmit = None
            try:
                await self._transmit()
                self.running_transmit.set_result(None)
                logger.debug("Queued DMX transmit finished ...")
            except Exception as e:
                self.running_transmit.set_exception(e)
                raise

        # In case there is a running _transmit and a Future for the next, simply await that future.
        else:
            logger.debug("DMX transmit is already running. Queued next transmit already exists. Wating for queued "
                         "transmit to finish ...")
            await self.next_transmit

    async def _transmit(self) -> None:
        """
        Internal helper coroutine to perform the actual transmission of the DMX universe to the DMX interface.

        This method converts the current state of the DMX universe to an EnttecMessage, writes it to the serial buffer
        and awaits the flush of the serial buffer to the interface."""
        # TODO catch connection errors
        self._writer.write(self._universe_to_enttec(self.universe).encode())
        await self._writer.drain()

    def __repr__(self) -> str:
        return "{}(serial_url={})".format(self.__class__.__name__, self.serial_url)


class EntTecMessageLabel(enum.Enum):
    REPROGRAM_FIRMWARE = 1
    PROGRAM_FLASH_PAGE = 2
    GET_WIDGET_PARAMETERS = 3
    SET_WIDGET_PARAMETERS = 4
    RECEIVED_DMX_PACKET = 5
    OUTPUT_ONLY_SEND_DMX_PACKET = 6
    SEND_RDM_PACKET = 7
    RECEIVE_DMX_ON_CHANGE = 8
    RECEIVED_DMX_CHANGE_OF_STATE_PACKET = 9
    GET_WIDGET_SERIAL_NUMBER = 10
    SEND_RDM_DISCOVERY = 11


class EnttecMessage(NamedTuple):
    label: EntTecMessageLabel
    data: bytes

    def encode(self) -> bytes:
        length = len(self.data)
        return bytes((0x7e, self.label.value, length & 0xff, (length >> 8) & 0xff)) + self.data + bytes((0xe7,))
