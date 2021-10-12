import asyncio
import os
import shutil
import subprocess
import tempfile
import time
import unittest
import unittest.mock
import ctypes
import ctypes.util
from pathlib import Path
from typing import Tuple

from shc.datatypes import RangeFloat1, Balance
from .._helper import async_test, InterfaceThreadRunner, ExampleWritable

libpulse_available = False
try:
    ctypes.CDLL(ctypes.util.find_library('libpulse') or 'libpulse.so.0')
    libpulse_available = True
except OSError:
    pass

if libpulse_available:
    import shc.interfaces.pulse


@unittest.skipUnless(libpulse_available, "libpulse is not availabe on this system")
class PulseVolumeTests(unittest.TestCase):
    def test_stereo_volume_conversion(self) -> None:
        vol = shc.interfaces.pulse.PulseVolumeRaw([1.0, 0.5], [1, 2])
        vol_split = shc.interfaces.pulse.PulseVolumeBalance.from_channels(vol)
        self.assertEqual(vol.map, vol_split.map)
        self.assertAlmostEqual(-0.5, vol_split.balance)
        self.assertEqual(1.0, vol_split.volume)
        self.assertEqual(0.0, vol_split.fade)
        self.assertEqual(0.0, vol_split.lfe_balance)
        vol2 = vol_split.as_channels()
        self.assertEqual(vol.map, vol2.map)
        for v1, v2 in zip(vol.values, vol2.values):
            self.assertAlmostEqual(v1, v2)

        vol_split2 = vol_split._replace(volume=RangeFloat1(0.3333), balance=Balance(0.25), fade=Balance(0.5))
        vol3 = vol_split2.as_channels()
        self.assertAlmostEqual(0.25, vol3.values[0], places=4)
        self.assertAlmostEqual(0.3333, vol3.values[1], places=4)

    def test_5_1_volume_conversion(self) -> None:
        vol = shc.interfaces.pulse.PulseVolumeRaw([0.1, 0.2, 0.3, 0.4, 0.5, 0.6], [1, 2, 5, 6, 3, 7])
        vol_split = shc.interfaces.pulse.PulseVolumeBalance.from_channels(vol)
        self.assertEqual(vol.map, vol_split.map)
        self.assertAlmostEqual(1-0.2/0.3, vol_split.balance, places=4)
        self.assertAlmostEqual(0.6, vol_split.volume, places=4)

        vol2 = vol_split.as_channels()
        self.assertEqual(vol.map, vol2.map)
        for v1, v2 in zip(vol.values, vol2.values):
            self.assertAlmostEqual(v1, v2, places=4)

        vol_split2 = vol_split._replace(volume=RangeFloat1(0.9))
        vol3 = vol_split2.as_channels()
        self.assertEqual(vol.map, vol2.map)
        for v1, v2 in zip(vol.values, vol3.values):
            self.assertAlmostEqual(v1 * 1.5, v2, places=4)


@unittest.skipUnless(libpulse_available, "libpulse is not availabe on this system")
@unittest.skipIf(shutil.which("pulseaudio") is None, "pulseaudio executable is not available in PATH")
@unittest.skipIf(shutil.which("pactl") is None, "pactl executable is not available in PATH")
class SinkConnectorTests(unittest.TestCase):
    def setUp(self) -> None:
        pulse_dir, self.pulse_process = create_dummy_instance()
        time.sleep(0.05)  # let Pulseaudio start
        self.pulse_url = f"unix:{pulse_dir / 'pulse' / 'native'}"
        self.interface_runner = InterfaceThreadRunner(shc.interfaces.pulse.PulseAudioInterface,
                                                      pulse_server_socket=self.pulse_url)
        self.interface = self.interface_runner.interface

    def tearDown(self) -> None:
            self.interface_runner.stop()
            self.pulse_process.terminate()
            self.pulse_process.wait()

    @async_test
    async def test_sink_volume(self) -> None:
        volume_connector1 = self.interface.sink_volume("testsink1")
        target1 = ExampleWritable(shc.interfaces.pulse.PulseVolumeRaw).connect(volume_connector1)
        volume_connector2 = self.interface.sink_volume("testsink2")
        target2 = ExampleWritable(shc.interfaces.pulse.PulseVolumeRaw).connect(volume_connector2)
        volume_connector3 = self.interface.sink_volume("testsink3")
        target3 = ExampleWritable(shc.interfaces.pulse.PulseVolumeRaw).connect(volume_connector3)

        # Initialize sink volumes
        await self._run_pactl('set-sink-volume', 'testsink1', '90%')
        await self._run_pactl('set-sink-volume', 'testsink2', '100%')

        self.interface_runner.start()

        # Read sink volumes
        value1 = await asyncio.wrap_future(asyncio.run_coroutine_threadsafe(volume_connector1.read(),
                                                                            loop=self.interface_runner.loop))
        self.assertAlmostEqual(0.9, value1.values[0], places=3)
        value2 = await asyncio.wrap_future(asyncio.run_coroutine_threadsafe(volume_connector2.read(),
                                                                            loop=self.interface_runner.loop))
        self.assertAlmostEqual(1.0, value2.values[0], places=3)
        with self.assertRaises(shc.base.UninitializedError):
            await asyncio.wrap_future(asyncio.run_coroutine_threadsafe(volume_connector3.read(),
                                                                       loop=self.interface_runner.loop))

        # External volume change to testsink2
        target1._write.reset_mock()
        target2._write.reset_mock()
        await self._run_pactl('set-sink-volume', 'testsink2', '90%', '80%', '80%', '70%', '90%', '90%')
        await asyncio.sleep(0.05)
        target2._write.assert_called_once()
        for v1, v2 in zip([0.9, 0.8, 0.8, 0.7, 0.9, 0.9], target2._write.call_args[0][0].values):
            self.assertAlmostEqual(v1, v2, places=4)
        target1._write.assert_not_called()
        target3._write.assert_not_called()

        # testsink3 added
        output = await self._run_pactl('load-module', 'module-null-sink', 'sink_name=testsink3')
        module_id = int(output)
        await asyncio.sleep(0.05)
        target3._write.assert_called_once()
        for v1, v2 in zip([1.0, 1.0], target3._write.call_args[0][0].values):
            self.assertAlmostEqual(v1, v2, places=4)

        # unload testsink3
        await self._run_pactl('unload-module', str(module_id))
        await asyncio.sleep(0.05)
        with self.assertRaises(shc.base.UninitializedError):
            await asyncio.wrap_future(asyncio.run_coroutine_threadsafe(volume_connector3.read(),
                                                                       loop=self.interface_runner.loop))

        # Write to testsink1's volume
        value1_new = value1._replace(values=[0.8, 0.7])
        await asyncio.wrap_future(asyncio.run_coroutine_threadsafe(volume_connector1.write(value1_new, [self]),
                                                                   loop=self.interface_runner.loop))
        await asyncio.sleep(0.05)
        target1._write.assert_called_once()
        self.assertEqual([self, volume_connector1], target1._write.call_args[0][1])
        for v1, v2 in zip(value1_new.values, target1._write.call_args[0][0].values):
            self.assertAlmostEqual(v1, v2, places=4)
        response = await self._run_pactl('get-sink-volume', 'testsink1')
        self.assertIn("front-left: 52429", response)
        self.assertIn("front-right: 45875", response)

    @async_test
    async def test_default_sink_mute(self) -> None:
        mute_connector = self.interface.default_sink_muted()
        target = ExampleWritable(bool).connect(mute_connector)

        await self._run_pactl('set-default-sink', 'testsink1')

        self.interface_runner.start()

        # Read sink volumes
        value = await asyncio.wrap_future(asyncio.run_coroutine_threadsafe(mute_connector.read(),
                                                                           loop=self.interface_runner.loop))
        self.assertIs(value, False)

        # External mute change to testsink1
        target._write.reset_mock()
        await self._run_pactl('set-sink-mute', 'testsink1', 'true')
        await asyncio.sleep(0.05)
        target._write.assert_called_once_with(True, unittest.mock.ANY)

        # Change default sink to testsink2
        target._write.reset_mock()
        await self._run_pactl('set-default-sink', 'testsink2')
        await asyncio.sleep(0.05)
        target._write.assert_called_once_with(False, unittest.mock.ANY)

        # External mute change to testsink1, which should not have an effect
        target._write.reset_mock()
        await self._run_pactl('set-sink-mute', 'testsink1', 'false')
        await asyncio.sleep(0.05)
        target._write.assert_not_called()

        # Write to default sink's (testsink2's) mute
        target._write.reset_mock()
        await asyncio.wrap_future(asyncio.run_coroutine_threadsafe(mute_connector.write(True, [self]),
                                                                   loop=self.interface_runner.loop))
        await asyncio.sleep(0.05)
        target._write.assert_called_once_with(True, [self, mute_connector])
        self.assertIn("yes", await self._run_pactl('get-sink-mute', 'testsink2'))
        self.assertIn("no", await self._run_pactl('get-sink-mute', 'testsink1'))

    async def _run_pactl(self, *args) -> str:
        proc = await asyncio.create_subprocess_exec(
            'pactl',
            '-s',
            self.pulse_url,
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=dict(LC_MESSAGES='C', PATH=os.environ['PATH'])
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode:
            raise RuntimeError(f"pactl failed with exit code {proc.returncode}. StdErr:\n{stderr.decode()}")
        return stdout.decode()


def create_dummy_instance() -> Tuple[Path, subprocess.Popen]:
    pulse_dir = tempfile.mkdtemp(prefix='shc-pulse-tests.')
    env = dict(PATH=os.environ['PATH'], XDG_RUNTIME_DIR=pulse_dir, PULSE_STATE_PATH=pulse_dir)
    proc = subprocess.Popen(
        ['pulseaudio', '--daemonize=no', '--fail',
         '-nF', '/dev/stdin', '--exit-idle-time=-1', '--log-level=error'],
        env=env, stdin=subprocess.PIPE)
    assert proc.stdin is not None
    proc.stdin.write("""
load-module module-suspend-on-idle
load-module module-filter-heuristics
load-module module-filter-apply
load-module module-switch-on-port-available
load-module module-native-protocol-unix
load-module module-null-sink sink_name=testsink1
load-module module-null-sink sink_name=testsink2 channels=6 channel_map=front-left,front-right,rear-left,rear-right,front-center,lfe
load-module module-null-source source_name=testsource1
load-module module-null-source source_name=testsource2
""".encode())
    proc.stdin.close()
    return Path(pulse_dir), proc
