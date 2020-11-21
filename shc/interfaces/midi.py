import abc
import asyncio
import logging
import threading
from typing import List, Any, Tuple, Dict

import mido

from ..base import Subscribable, Writable, T
from ..datatypes import RangeUInt8
from ..supervisor import register_interface

logger = logging.getLogger(__name__)


class MidiInterface:
    def __init__(self, input_port_name: str, output_port_name: str, send_channel: int = 0) -> None:
        # TODO make ports optional to allow oneway interface
        self.input_port_name = input_port_name
        self.output_port_name = output_port_name
        self.send_channel = send_channel

        self.output_queue = asyncio.Queue()
        self._input_queue = asyncio.Queue()
        self._send_thread_stopped = asyncio.Event()
        self._send_thread_stopped.set()

        self._variable_map: Dict[Tuple[str, int], AbstractMidiVariable] = {}

        register_interface(self)

    async def start(self) -> None:
        loop = asyncio.get_event_loop()

        send_thread = threading.Thread(target=self._send_thread, name="shc.midi.send_thread", args=(loop,))
        send_thread.start()
        self._send_thread_stopped.clear()
        self.receive_task = loop.create_task(self._receive_task())

        def incoming_message_callback(message):
            loop.call_soon_threadsafe(self._input_queue.put_nowait, message)

        self.input_port = mido.open_input(self.input_port_name, callback=incoming_message_callback)

    async def wait(self) -> None:
        await self.receive_task
        await self._send_thread_stopped.wait()

    async def stop(self) -> None:
        logger.debug('Stopping MIDI interface. First, closing down mido input_port ...')
        self.input_port.close()  # FIXME closing ports can be blocking (mutex and blocking IO)
        logger.debug('Cancelling receive_task ...')
        self.receive_task.cancel()
        await self.receive_task

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
            if msg_type not in ('note_on', 'note_off', 'control_change'):
                logger.debug('Unsupported MIDI message type %s', msg_type)
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
        # TODO detect/allow duplicate variables
        variable = NoteOnOffVariable(self, note, emulate_toggle, off_output_velocity, on_output_velocity)
        self._variable_map[('note_on', note)] = variable
        self._variable_map[('note_off', note)] = variable
        return variable

    def control_change(self, control_channel: int) -> "ControlChangeVariable":
        # TODO detect/allow duplicate variables
        variable = ControlChangeVariable(self, control_channel=control_channel)
        self._variable_map[('control_change', control_channel)] = variable
        return variable

    def note_velocity(self, note: int) -> "NoteVelocityVariable":
        # TODO detect/allow duplicate variables
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
        value = value//2
        await self.interface.output_queue.put(mido.Message('note_off' if value == 0 else 'note_on',
                                                           channel=self.interface.send_channel, note=self.note,
                                                           velocity=value))

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
