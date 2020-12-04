import asyncio
import time
import unittest
import unittest.mock
import logging

import mido  # type: ignore
import shc.interfaces.midi
from shc.datatypes import RangeUInt8

from .._helper import async_test, InterfaceThreadRunner, AsyncMock


class MIDITest(unittest.TestCase):
    def test_errors(self) -> None:
        with self.assertRaises(ValueError):
            interface = shc.interfaces.midi.MidiInterface()

        interface = shc.interfaces.midi.MidiInterface("foo")
        var1 = interface.note_on_off(42)
        var2 = interface.note_on_off(42)
        self.assertIs(var1, var2)
        with self.assertRaises(ValueError):
            interface.note_velocity(42)


class MIDIInputTest(unittest.TestCase):
    def setUp(self) -> None:
        self.dummy_port = mido.open_output('TestPort1234', virtual=True)

        self.interface = shc.interfaces.midi.MidiInterface("TestPort1234", None)
        self.interface_runner = InterfaceThreadRunner(self.interface)

    def tearDown(self) -> None:
        self.interface_runner.stop()
        self.dummy_port.close()

    def test_input(self) -> None:
        var1 = self.interface.note_on_off(5)
        var2 = self.interface.note_velocity(7)
        var3 = self.interface.control_change(1)

        with unittest.mock.patch.object(var1, '_publish', new_callable=AsyncMock) as publish_mock1,\
             unittest.mock.patch.object(var2, '_publish', new_callable=AsyncMock) as publish_mock2,\
             unittest.mock.patch.object(var3, '_publish', new_callable=AsyncMock) as publish_mock3:

            self.interface_runner.start()
            time.sleep(0.05)

            # Things to be ignored
            self.dummy_port.send(mido.Message('note_on', channel=0, note=42, velocity=20))
            self.dummy_port.send(mido.Message('control_change', channel=0, control=42, value=0))
            self.dummy_port.send(mido.Message('aftertouch', channel=0, value=18))
            time.sleep(0.05)

            publish_mock1.assert_not_called()
            publish_mock2.assert_not_called()
            publish_mock3.assert_not_called()

            # Note on
            self.dummy_port.send(mido.Message('note_on', channel=0, note=5, velocity=20))
            self.dummy_port.send(mido.Message('note_on', channel=0, note=7, velocity=20))
            time.sleep(0.05)

            publish_mock1.assert_called_once_with(True, unittest.mock.ANY)
            publish_mock2.assert_called_once_with(RangeUInt8(40), unittest.mock.ANY)
            publish_mock3.assert_not_called()

            # Note off
            publish_mock1.reset_mock()
            publish_mock2.reset_mock()
            self.dummy_port.send(mido.Message('note_off', channel=0, note=5, velocity=40))
            self.dummy_port.send(mido.Message('note_off', channel=0, note=7, velocity=40))
            time.sleep(0.05)

            publish_mock1.assert_called_once_with(False, unittest.mock.ANY)
            publish_mock2.assert_called_once_with(RangeUInt8(80), unittest.mock.ANY)
            publish_mock3.assert_not_called()

            # Control change
            publish_mock1.reset_mock()
            publish_mock2.reset_mock()
            self.dummy_port.send(mido.Message('control_change', channel=0, control=1, value=42))
            time.sleep(0.05)

            publish_mock1.assert_not_called()
            publish_mock2.assert_not_called()
            publish_mock3.assert_called_once_with(RangeUInt8(84), unittest.mock.ANY)

    # TODO add test for emulated toggle


class MIDIOutputTest(unittest.TestCase):
    def setUp(self) -> None:
        self.callback = unittest.mock.Mock()
        self.dummy_port = mido.open_input('TestPort456', virtual=True, callback=self.callback)

        self.interface = shc.interfaces.midi.MidiInterface(None, "TestPort456", send_channel=9)
        self.interface_runner = InterfaceThreadRunner(self.interface)

    def tearDown(self) -> None:
        self.interface_runner.stop()
        self.dummy_port.close()

    def test_output(self) -> None:
        var1 = self.interface.note_on_off(5)
        var2 = self.interface.note_velocity(7)
        var3 = self.interface.control_change(1)

        self.interface_runner.start()
        time.sleep(0.05)

        # Note on
        asyncio.run_coroutine_threadsafe(var1.write(True, [self]), self.interface_runner.loop)
        time.sleep(0.05)
        self.callback.assert_called_once()
        message = self.callback.call_args[0][0]
        assert isinstance(message, mido.Message)
        self.assertEqual(message.channel, 9)
        self.assertEqual(message.type, "note_on")
        self.assertEqual(message.note, 5)
        self.assertNotEqual(message.velocity, 0)

        # Note off
        self.callback.reset_mock()
        asyncio.run_coroutine_threadsafe(var1.write(False, [self]), self.interface_runner.loop)
        time.sleep(0.05)
        self.callback.assert_called_once()
        message = self.callback.call_args[0][0]
        assert isinstance(message, mido.Message)
        self.assertEqual(message.channel, 9)
        self.assertEqual(message.type, "note_off")
        self.assertEqual(message.note, 5)
        self.assertEqual(message.velocity, 0)

        # Note on (velocity)
        self.callback.reset_mock()
        asyncio.run_coroutine_threadsafe(var2.write(RangeUInt8(42), [self]), self.interface_runner.loop)
        time.sleep(0.05)
        self.callback.assert_called_once()
        message = self.callback.call_args[0][0]
        assert isinstance(message, mido.Message)
        self.assertEqual(message.channel, 9)
        self.assertEqual(message.type, "note_on")
        self.assertEqual(message.note, 7)
        self.assertEqual(message.velocity, 21)

        # Note off (velocity)
        self.callback.reset_mock()
        asyncio.run_coroutine_threadsafe(var2.write(RangeUInt8(0), [self]), self.interface_runner.loop)
        time.sleep(0.05)
        self.callback.assert_called_once()
        message = self.callback.call_args[0][0]
        assert isinstance(message, mido.Message)
        self.assertEqual(message.channel, 9)
        self.assertEqual(message.type, "note_off")
        self.assertEqual(message.note, 7)
        self.assertEqual(message.velocity, 0)

        # Control change
        self.callback.reset_mock()
        asyncio.run_coroutine_threadsafe(var3.write(RangeUInt8(56), [self]), self.interface_runner.loop)
        time.sleep(0.05)
        self.callback.assert_called_once()
        message = self.callback.call_args[0][0]
        assert isinstance(message, mido.Message)
        self.assertEqual(message.channel, 9)
        self.assertEqual(message.type, "control_change")
        self.assertEqual(message.control, 1)
        self.assertEqual(message.value, 28)
