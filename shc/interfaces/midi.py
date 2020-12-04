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

import mido  # type: ignore

from ..base import Subscribable, Writable, T
from ..datatypes import RangeUInt8
from ..supervisor import register_interface

logger = logging.getLogger(__name__)


class MidiInterface:
    def __init__(self, input_port_name: Optional[str] = None,
                 output_port_name: Optional[str] = None,
                 send_channel: int = 0,
                 receive_channel: Union[None, int, Iterable[int]] = None) -> None:
        if not input_port_name and not output_port_name:
            raise ValueError("Either MIDI input port name or output port name must be specified.")

        self.input_port_name = input_port_name
        self.output_port_name = output_port_name
        self.send_channel = send_channel
        self.receive_channel = receive_channel

        self.output_queue: asyncio.Queue[Optional[mido.Message]]
        self._input_queue: asyncio.Queue[mido.Message]

        self._variable_map: Dict[Tuple[str, int], AbstractMidiVariable] = {}

        register_interface(self)

    async def start(self) -> None:
        loop = asyncio.get_event_loop()
        self.output_queue = asyncio.Queue()
        self._input_queue = asyncio.Queue()
        self._send_thread_stopped = asyncio.Event()
        self._send_thread_stopped.set()

        if self.output_port_name:
            send_thread = threading.Thread(target=self._send_thread, name="shc.midi.send_thread", args=(loop,))
            send_thread.start()
            self._send_thread_stopped.clear()

        def incoming_message_callback(message):
            loop.call_soon_threadsafe(self._input_queue.put_nowait, message)

        if self.input_port_name:
            self.receive_task = loop.create_task(self._receive_task())
            self.input_port = mido.open_input(self.input_port_name, callback=incoming_message_callback)

    async def wait(self) -> None:
        if self.input_port_name:
            await self.receive_task
        if self.output_port_name:
            await self._send_thread_stopped.wait()

    async def stop(self) -> None:
        logger.info('Stopping MIDI interface.')

        if self.input_port_name:
            logger.debug('First, closing down mido input_port ...')
            await asyncio.get_event_loop().run_in_executor(None, self.input_port.close)
            logger.debug('Cancelling receive_task ...')
            self.receive_task.cancel()
            await self.receive_task

        if self.output_port_name:
            logger.debug('Sending None value to _send_thread() to shut it down ...')
            await self.output_queue.put(None)
            await self._send_thread_stopped.wait()
        logger.debug('MIDI interface shutdown finished.')

    async def _receive_task(self) -> None:
        while True:
            try:
                message = await self._input_queue.get()
            except asyncio.CancelledError:
                logger.debug("_receive_task() cancelled while waiting for messages. Shutting down.")
                break

            logger.debug('Received MIDI message: %s', message)
            msg_type = message.type
            channel = message.channel
            if msg_type not in ('note_on', 'note_off', 'control_change'):
                logger.debug('Unsupported MIDI message type %s', msg_type)
                continue
            if isinstance(self.receive_channel, int):
                if channel != self.receive_channel:
                    logger.debug('Ignoring message from wrong input channel %s', channel)
                    continue
            elif self.receive_channel is not None and channel not in self.receive_channel:
                logger.debug('Ignoring message from wrong input channel %s', channel)
                continue

            key = message.control if msg_type == 'control_change' else message.note
            variable = self._variable_map.get((msg_type, key))
            if variable is None:
                logger.debug('MIDI message is not assigned to any variable')
                continue
            asyncio.create_task(variable._incoming_message(message))

    def _send_thread(self, loop: asyncio.AbstractEventLoop) -> None:
        try:
            logger.debug("Starting _send_thread(). Opening output_port for %s", self.output_port_name)
            output_port = mido.open_output(self.output_port_name)
            logger.debug("Output port to %s opened.", self.output_port_name)
            while True:
                message: mido.Message = asyncio.run_coroutine_threadsafe(self.output_queue.get(), loop).result()
                if message is None:
                    logger.debug("_send_thread got None value. Exiting send loop.")
                    break
                logger.debug('Sending MIDI message: %s', message)
                output_port.send(message)

            logger.info('Closing mido output_port ...')
            output_port.close()
            logger.debug('_send_thread() done.')
        finally:
            loop.call_soon_threadsafe(self._send_thread_stopped.set)

    def note_on_off(self, note: int, emulate_toggle: bool = False,
                    off_output_velocity: int = 0, on_output_velocity: int = 127) -> "NoteOnOffVariable":
        existing_variable = self._variable_map[('note_on', note)]
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
        existing_variable = self._variable_map[('control_change', control_channel)]
        if existing_variable:
            assert isinstance(existing_variable, ControlChangeVariable)
            return existing_variable
        variable = ControlChangeVariable(self, control_channel=control_channel)
        self._variable_map[('control_change', control_channel)] = variable
        return variable

    def note_velocity(self, note: int) -> "NoteVelocityVariable":
        existing_variable = self._variable_map[('note_on', note)]
        if existing_variable and isinstance(existing_variable, NoteVelocityVariable):
            return existing_variable
        elif existing_variable:
            raise ValueError("A variable for MIDI note {} is already existing but with a different variable type."
                             .format(note))
        variable = NoteVelocityVariable(self, note=note)
        self._variable_map[('note_on', note)] = variable
        self._variable_map[('note_off', note)] = variable
        return variable


class AbstractMidiVariable(metaclass=abc.ABCMeta):
    @abc.abstractmethod
    async def _incoming_message(self, message: mido.Message) -> None:
        pass


class NoteVelocityVariable(Subscribable[RangeUInt8], Writable[RangeUInt8], AbstractMidiVariable):
    type = RangeUInt8

    def __init__(self, interface: MidiInterface, note: int):
        super().__init__()
        self.interface = interface
        self.note = note

    async def _write(self, value: RangeUInt8, origin: List[Any]) -> None:
        midi_value = value//2
        await self.interface.output_queue.put(mido.Message('note_off' if midi_value == 0 else 'note_on',
                                                           channel=self.interface.send_channel, note=self.note,
                                                           velocity=midi_value))

    async def _incoming_message(self, message: mido.Message) -> None:
        value = message.velocity
        value = value * 2 + (1 if value > 63 else 0)
        await self._publish(RangeUInt8(value), [])


class ControlChangeVariable(Subscribable[RangeUInt8], Writable[RangeUInt8], AbstractMidiVariable):
    type = RangeUInt8

    def __init__(self, interface: MidiInterface, control_channel: int):
        super().__init__()
        self.interface = interface
        self.control_channel = control_channel

    async def _write(self, value: RangeUInt8, origin: List[Any]) -> None:
        await self.interface.output_queue.put(mido.Message('control_change', channel=self.interface.send_channel,
                                                           control=self.control_channel, value=value//2))

    async def _incoming_message(self, message: mido.Message) -> None:
        value = message.value
        value = value * 2 + (1 if value > 63 else 0)
        await self._publish(RangeUInt8(value), [])


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
        await self._to_midi(value)

    async def _to_midi(self, value) -> None:
        await self.interface.output_queue.put(mido.Message('note_on' if value else 'note_off',
                                                           channel=self.interface.send_channel, note=self.note,
                                                           velocity=self.on_velocity if value else self.off_velocity))

    async def _incoming_message(self, message: mido.Message) -> None:
        on = message.type == 'note_on' and message.velocity > 0
        if self.emulate_toggle:
            if on:
                self.value = not self.value
            await self._to_midi(self.value)
        else:
            self.value = on
        await self._publish(self.value, [])
