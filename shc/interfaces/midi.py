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
import abc
import asyncio
import logging
import threading
from typing import List, Any, Tuple, Dict, Optional, Union, Iterable

import mido

from ..base import Subscribable, Writable, T
from ..datatypes import RangeUInt8
from ..supervisor import stop, AbstractInterface

logger = logging.getLogger(__name__)


class MidiInterface(AbstractInterface):
    """
    An SHC interface for connecting with MIDI devices.

    This interface is primarily designed to control SHC applications with MIDI DAW controllers such as the *Behringer
    X-Touch*, *Icon QCon*, *DJ Techtools Midi Fighter* or similar, which provide (motorized) faders, rotary encoders
    and/or push buttons. These interfaces typically send MIDI Note on/off and control change messages when the user
    uses the controls. In return, the controller's hardware feedback (motor faders, LEDs) can be updated by sending the
    corresponding MIDI events to the controller.

    Thus, the `MidiInterface` allows to create the following types of *Connectable* objects:

    * :meth:`note_on_off`: :class:`bool`-type for sending/receiving Note on/off events for a specific note number (for
      push buttons)
    * :meth:`note_velocity`: range-type (:class:`RangeUint8 <shc.datatypes.RangeUInt8>`) for sending/receiving Note
      on/off events with a value encoded in the velocity parameter of a specific note number
    * :meth:`control_change`: range-type (:class:`RangeUint8 <shc.datatypes.RangeUInt8>`) for sending/receiving Control
      Change events with a for a specific control.

    However, the Interface features might also be suited to control any MIDI gear, which reacts to these MIDI events.

    The outbound MIDI channel number can be set globally for all *Connectables* of the interface (``send_channel``).
    Inbound MIDI events can be filtered for a specific MIDI channel or a list of channels (``receive_channel``).

    The interface can be used in a bidirectional mode, input-only mode (no output port; values `written` to the
    *Connectable* objects are dropped) or output-only mode (no input port).

    :param input_port_name: Name of the inbound MIDI port. If not specified, the interface works in output-only mode.
        Use ``mido.get_input_names()`` to get a list of output port names.
    :param output_port_name: Name of the outbound MIDI port. If not specified, the interface works in input-only mode.
        Use ``mido.get_output_names()`` to get a list of output port names.
    :param send_channel: MIDI channel number [0-15] for all outbound MIDI messages. Defaults to 0.
    :param receive_channel: If specified, it allows to filter the incomming MIDI events by MIDI channel. Either a single
        channel number [0-15] or a list of channel numbers which should be processed. Other than the specified MIDI
        channel(s) are ignored.
    """
    def __init__(self, input_port_name: Optional[str] = None,
                 output_port_name: Optional[str] = None,
                 send_channel: int = 0,
                 receive_channel: Union[None, int, Iterable[int]] = None) -> None:
        if not input_port_name and not output_port_name:
            raise ValueError("Either MIDI input port name or output port name must be specified.")
        super().__init__()

        self.input_port_name = input_port_name
        self.output_port_name = output_port_name
        self.send_channel = send_channel
        self.receive_channel = receive_channel

        self._output_queue: asyncio.Queue[Optional[mido.Message]]
        self._input_queue: asyncio.Queue[mido.Message]

        self._variable_map: Dict[Tuple[str, int], AbstractMidiVariable] = {}

    async def start(self) -> None:
        loop = asyncio.get_event_loop()
        # We must initialize the Queues and Events here to make sure that they are assigned to the correct event loop
        self._output_queue = asyncio.Queue()
        self._input_queue = asyncio.Queue()
        self._send_thread_stopped = asyncio.Event()
        self._send_thread_stopped.set()

        if self.output_port_name:
            send_thread = threading.Thread(target=self._send_thread, name="shc.midi.send_thread", args=(loop,))
            send_thread.start()
            self._send_thread_stopped.clear()

        def incoming_message_callback(message):
            loop.call_soon_threadsafe(self._dispatch_message, message)

        if self.input_port_name:
            self.input_port = mido.open_input(self.input_port_name, callback=incoming_message_callback)

    async def stop(self) -> None:
        logger.info('Stopping MIDI interface.')

        if self.input_port_name:
            logger.debug('First, closing down mido input_port ...')
            await asyncio.get_event_loop().run_in_executor(None, self.input_port.close)

        if self.output_port_name:
            logger.debug('Sending None value to _send_thread() to shut it down ...')
            await self._output_queue.put(None)
            await self._send_thread_stopped.wait()
        logger.debug('MIDI interface shutdown finished.')

    def _dispatch_message(self, message) -> None:
        logger.debug('Received MIDI message: %s', message)
        msg_type = message.type
        channel = message.channel
        # Filter by MIDI event type
        if msg_type not in ('note_on', 'note_off', 'control_change'):
            logger.debug('Unsupported MIDI message type %s', msg_type)
            return
        # Filter by MIDI channel
        if isinstance(self.receive_channel, int):
            if channel != self.receive_channel:
                logger.debug('Ignoring message from wrong input channel %s', channel)
                return
        elif self.receive_channel is not None and channel not in self.receive_channel:
            logger.debug('Ignoring message from wrong input channel %s', channel)
            return

        # Check if a *Connectable* object is registered for this type/index combination
        key = message.control if msg_type == 'control_change' else message.note
        variable = self._variable_map.get((msg_type, key))
        if variable is None:
            logger.debug('MIDI message is not assigned to any variable')
            return

        # Dispatch new value in a new asyncio Task
        try:
            variable._incoming_message(message)
        except Exception as e:
            logger.error("Error while dispatching incoming MIDI message %s", message, exc_info=e)

    def _send_thread(self, loop: asyncio.AbstractEventLoop) -> None:
        """
        Entry point for the daemon thread for sending outgoing MIDI messages to the MIDI port.
        """
        try:
            logger.debug("Starting _send_thread(). Opening output_port for %s", self.output_port_name)
            output_port = mido.open_output(self.output_port_name)
            logger.debug("Output port to %s opened.", self.output_port_name)
            while True:
                message: mido.Message = asyncio.run_coroutine_threadsafe(self._output_queue.get(), loop).result()
                if message is None:
                    logger.debug("_send_thread got None value. Exiting send loop.")
                    break
                logger.debug('Sending MIDI message: %s', message)
                output_port.send(message)

            logger.info('Closing mido output_port ...')
            output_port.close()
            logger.debug('_send_thread() done.')
        except Exception as e:
            logger.critical("Exception in MIDI send thread. Shutting down SHC ...", exc_info=e)
            asyncio.run_coroutine_threadsafe(stop(), loop)
        finally:
            loop.call_soon_threadsafe(self._send_thread_stopped.set)

    def _send_message(self, message: mido.Message) -> None:
        """
        Internal method used by the Variable objects to send a MIDI message to the output port via the output queue.

        This method takes care of dropping the messages if this interface works in input-only mode.
        :param message: The MIDI message to send to the output port
        """
        if self.output_port_name:
            self._output_queue.put_nowait(message)

    def note_on_off(self, note: int, emulate_toggle: bool = False,
                    off_output_velocity: int = 0, on_output_velocity: int = 127) -> "NoteOnOffVariable":
        """
        Create a *Connectable* object for this MIDI interface which handles Note on/off events as boolean values.

        The returned object is *Writable* and *Subscribable*. It will publish a `True` value when a Note on event for
        the specified Note is received and a `False` for each Note off event. Note on events with velolicty=0 are
        handled like Note off events. The same mapping is applied for outgoing messages: `True` → Note on
        `False` → Note off. The velocity values for outgoing events can be configured via ``off_output_velocity`` and
        ``on_output_velocity``.

        The ``emulate_toggle`` parameter can be used to select a different operation mode, which is designed to turn a
        hardware controller's "flash" buttons (press sends Note on, release send note off) into toggle buttons. In this
        mode, an internal boolean state is maintained, which is toggled upon every incoming Note on events. Incoming
        Note off events are ignored. The state can be updated from within SHC by *writing* a bool value to the object.
        Outbound MIDI events are created, when the state is updated from within SHC (as in the normal operation mode)
        **and** as a response to incoming MIDI event, to make sure the hardware controller's button LEDs are always in
        the right state.

        The following table shows a comparison of the two operation modes:

        +------------------------------+--------------------------+-------------------------------------------+
        | incoming MIDI event sequence | ``emulate_toggle=False`` | ``emulate_toggle=True``                   |
        +==============================+==========================+===========================================+
        | *Note on*                    | ``True`` published       | ``True`` published, *Note on* sent back   |
        +------------------------------+--------------------------+-------------------------------------------+
        | *Note off*                   | ``False`` published      | ``True`` published, *Note on* sent back   |
        +------------------------------+--------------------------+-------------------------------------------+
        | *Note on*                    | ``True`` published       | ``False`` published, *Note off* sent back |
        +------------------------------+--------------------------+-------------------------------------------+
        | *Note off*                   | ``False`` published      | ``False`` published, *Note off* sent back |
        +------------------------------+--------------------------+-------------------------------------------+
        | …                            | …                        | …                                         |
        +------------------------------+--------------------------+-------------------------------------------+

        .. warning::

            For every note number, either :meth:`note_on_off` or :meth:`note_velocity` can be used, but not both.

        :param note: The MIDI note number to listen to/send events to [0 (C-2) - 127 (G9)].
        :param emulate_toggle: If True, emulate a toggle button (see above).
        :param off_output_velocity: The MIDI velocity of outbound *Note on* events. Defaults to 0.
        :param on_output_velocity: The MIDI velocity of outbound *Note on* events. Defaults to 127.
        :return: The *Connectible* object with the given specification
        """
        existing_variable = self._variable_map.get(('note_on', note))
        if existing_variable and isinstance(existing_variable, NoteOnOffVariable):
            return existing_variable
        elif existing_variable:
            raise ValueError("A variable for MIDI note {} is already existing but with a different variable type."
                             .format(note))
        variable = NoteOnOffVariable(self, note, emulate_toggle, off_output_velocity, on_output_velocity)
        self._variable_map[('note_on', note)] = variable
        self._variable_map[('note_off', note)] = variable
        return variable

    def control_change(self, control_channel: int) -> "ControlChangeVariable":
        """
        Create a *Connectable* object for this MIDI interface which handles *Control Change* events.

        The logics are pretty simple: The value of an incoming MIDI control change event for the given control number
        is published as a :class:`shc.datatypes.RangeUInt8` value. New values from SHC are sent out as control change
        MIDI events. The 7-bit MIDI values are converted to a RangeUInt8 by multiplying with 2 and adding 1 to all
        values >127. This way, the MIDI value 127 is mapped to ``RangeUInt8(255)``.

        :param control_channel: The MIDI control number (0-127)
        :return: The *Connectable* object with `RangeUInt8` type to interact with the specified MIDI control channel
        """
        existing_variable = self._variable_map.get(('control_change', control_channel))
        if existing_variable:
            assert isinstance(existing_variable, ControlChangeVariable)
            return existing_variable
        variable = ControlChangeVariable(self, control_channel=control_channel)
        self._variable_map[('control_change', control_channel)] = variable
        return variable

    def note_velocity(self, note: int) -> "NoteVelocityVariable":
        """
        Create a *Connectable* object for this MIDI interface which handles Note on/off events as range values using
        their velocity value.

        For each incoming Note on/off event for the specified note number the velocity value is published as a
        :class:`shc.datatypes.RangeUInt8`. The 7-bit MIDI values are converted to a RangeUInt8 by multiplying with 2 and
        adding 1 to all values >127. This way, the MIDI value 127 is mapped to ``RangeUInt8(255)``. When a new value
        is received from SHC (i.e. `written` to the object), an outbound Note on/off event is created, with a note
        velocity corresponding to the value. If the value is 0, a Note off event is created, otherwise a Note on event.

        .. warning::

            For every note number, either :meth:`note_on_off` or :meth:`note_velocity` can be used, but not both.

        :param note: The MIDI control number (0-127)
        :return: The *Connectable* object with `RangeUInt8` type to interact with the specified MIDI note.
        """
        existing_variable = self._variable_map.get(('note_on', note))
        if existing_variable and isinstance(existing_variable, NoteVelocityVariable):
            return existing_variable
        elif existing_variable:
            raise ValueError("A variable for MIDI note {} is already existing but with a different variable type."
                             .format(note))
        variable = NoteVelocityVariable(self, note=note)
        self._variable_map[('note_on', note)] = variable
        self._variable_map[('note_off', note)] = variable
        return variable

    def __repr__(self) -> str:
        return "{}(input_port_name={}, output_port_name={}, send_channel={}, receive_channel={})"\
            .format(self.__class__.__name__, self.input_port_name, self.output_port_name, self.send_channel,
                    self.receive_channel)


class AbstractMidiVariable(metaclass=abc.ABCMeta):
    @abc.abstractmethod
    def _incoming_message(self, message: mido.Message) -> None:
        pass


class NoteVelocityVariable(Subscribable[RangeUInt8], Writable[RangeUInt8], AbstractMidiVariable):
    type = RangeUInt8

    def __init__(self, interface: MidiInterface, note: int):
        super().__init__()
        self.interface = interface
        self.note = note

    async def _write(self, value: RangeUInt8, origin: List[Any]) -> None:
        midi_value = value//2
        self.interface._send_message(mido.Message('note_off' if midi_value == 0 else 'note_on',
                                                  channel=self.interface.send_channel, note=self.note,
                                                  velocity=midi_value))

    def _incoming_message(self, message: mido.Message) -> None:
        value = message.velocity
        value = value * 2 + (1 if value > 63 else 0)
        self._publish(RangeUInt8(value), [])


class ControlChangeVariable(Subscribable[RangeUInt8], Writable[RangeUInt8], AbstractMidiVariable):
    type = RangeUInt8

    def __init__(self, interface: MidiInterface, control_channel: int):
        super().__init__()
        self.interface = interface
        self.control_channel = control_channel

    async def _write(self, value: RangeUInt8, origin: List[Any]) -> None:
        self.interface._send_message(mido.Message('control_change', channel=self.interface.send_channel,
                                                  control=self.control_channel, value=value//2))

    def _incoming_message(self, message: mido.Message) -> None:
        value = message.value
        value = value * 2 + (1 if value > 63 else 0)
        self._publish(RangeUInt8(value), [])


class NoteOnOffVariable(Subscribable[bool], Writable[bool], AbstractMidiVariable):
    type = bool

    def __init__(self, interface: MidiInterface, note: int, emulate_toggle: bool,
                 off_output_velocity: int, on_output_velocity: int):
        super().__init__()
        self.interface = interface
        self.note = note
        self.emulate_toggle = emulate_toggle
        self.off_velocity = off_output_velocity
        self.on_velocity = on_output_velocity

        # Required for emulate_toggle
        self.value = False

    async def _write(self, value: bool, origin: List[Any]) -> None:
        self.value = value
        self._to_midi(value)

    def _to_midi(self, value) -> None:
        self.interface._send_message(mido.Message('note_on' if value else 'note_off',
                                                  channel=self.interface.send_channel, note=self.note,
                                                  velocity=self.on_velocity if value else self.off_velocity))

    def _incoming_message(self, message: mido.Message) -> None:
        on = message.type == 'note_on' and message.velocity > 0
        if self.emulate_toggle:
            if on:
                self.value = not self.value
            self._to_midi(self.value)
        else:
            self.value = on
        self._publish(self.value, [])
