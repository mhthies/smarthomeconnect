import asyncio
import datetime
import os
import shutil
import subprocess
import tempfile
import time
import unittest
import unittest.mock

import knxdclient
from shc import conversion
from shc.datatypes import FadeStep
from shc.interfaces import knx
from test._helper import async_test, InterfaceThreadRunner, ExampleWritable, ExampleReadable


class KNXDataTypesTest(unittest.TestCase):
    def test_knx_control_dimming_conversion(self) -> None:
        converter1 = conversion.get_converter(knx.KNXControlDimming, FadeStep)
        converter2 = conversion.get_converter(FadeStep, knx.KNXControlDimming)

        result = converter1(knx.KNXControlDimming(True, 2))  # +0.5
        self.assertIsInstance(result, FadeStep)
        self.assertAlmostEqual(0.5, result)

        result = converter1(knx.KNXControlDimming(False, 3))  # -0.25
        self.assertIsInstance(result, FadeStep)
        self.assertAlmostEqual(-0.25, result)

        result2 = converter2(FadeStep(0.25))
        self.assertIsInstance(result2, knx.KNXControlDimming)
        self.assertEqual(knx.KNXControlDimming(True, 3), result2)

        result2 = converter2(FadeStep(-0.10))  # Should be rounded to -0.125
        self.assertIsInstance(result2, knx.KNXControlDimming)
        self.assertEqual(knx.KNXControlDimming(False, 4), result2)


@unittest.skipIf(shutil.which("knxd") is None, "knxd is not available in PATH")
@unittest.skipIf(shutil.which("knxtool") is None, "knxtool is not available in PATH")
class KNXDConnectorTest(unittest.TestCase):
    def setUp(self) -> None:
        self.knxd_socket = tempfile.mktemp(suffix=".sock", prefix="knxdclient-test-knxd-")
        self.knxd_process = subprocess.Popen(["knxd", f"--listen-local={self.knxd_socket}", "-e", "0.5.1", "-E",
                                              "0.5.2:10", "dummy"])
        time.sleep(0.25)
        self.interface_runner = InterfaceThreadRunner(knx.KNXConnector, sock=self.knxd_socket)
        self.interface: knx.KNXConnector = self.interface_runner.interface

    def tearDown(self) -> None:
        self.interface_runner.stop()
        self.knxd_process.terminate()
        self.knxd_process.wait()

    @async_test
    async def test_receive(self) -> None:
        group_connector1 = self.interface.group(knx.KNXGAD(1, 2, 3), "1")
        target1 = ExampleWritable(bool).connect(group_connector1)
        group_connector2 = self.interface.group(knx.KNXGAD(17, 5, 127), "10")
        target2 = ExampleWritable(knxdclient.KNXTime).connect(group_connector2)

        self.interface_runner.start()

        proc = await asyncio.create_subprocess_exec('knxtool', 'on', f'local://{self.knxd_socket}', '1/2/3',
                                                    env=dict(PATH=os.environ['PATH']))
        await proc.communicate()
        if proc.returncode:
            raise RuntimeError(f"knxtool failed with exit code {proc.returncode}")
        proc = await asyncio.create_subprocess_exec('knxtool', 'groupwrite', f'local://{self.knxd_socket}',
                                                    '17/5/127', 'c6', '00', '0b',
                                                    env=dict(PATH=os.environ['PATH']))
        await proc.communicate()
        if proc.returncode:
            raise RuntimeError(f"knxtool failed with exit code {proc.returncode}")

        await asyncio.sleep(0.05)

        target1._write.assert_called_once_with(True, unittest.mock.ANY)
        target2._write.assert_called_once_with(knxdclient.KNXTime(datetime.time(6, 0, 11), 5),
                                               unittest.mock.ANY)

    @async_test
    async def test_send(self) -> None:
        group_connector1 = self.interface.group(knx.KNXGAD(1, 2, 3), "1")
        target1 = ExampleWritable(bool).connect(group_connector1)
        group_connector2 = self.interface.group(knx.KNXGAD(17, 5, 127), "10")
        target2 = ExampleWritable(knxdclient.KNXTime).connect(group_connector2)

        self.interface_runner.start()

        # Start busmonitor
        proc = await asyncio.create_subprocess_exec(
            'knxtool',
            'vbusmonitor1',
            f'local://{self.knxd_socket}',
            stdout=asyncio.subprocess.PIPE,
            env=dict(PATH=os.environ['PATH'])
        )
        await asyncio.sleep(0.1)

        try:
            # Send value
            await self.interface_runner.run_coro_async(group_connector1.write(False, [self]))
            await self.interface_runner.run_coro_async(
                group_connector2.write(knxdclient.KNXTime(datetime.time(6, 0, 11), 5), [self]))

        except Exception:
            proc.terminate()
            raise

        # Stop busmonitor and gather output
        await asyncio.sleep(0.1)
        proc.terminate()
        stdout, _stderr = await proc.communicate()
        if proc.returncode != -15:
            raise RuntimeError(f"knxtool vbusmonitor1 failed with unexpected exit code {proc.returncode}")

        # Analyze output
        lines = stdout.strip().split(b'\n')
        # self.assertEqual(2, len(lines))  # exactly two line of Busmonitor output (=2 telegrams) are expected
        self.assertRegex(lines[0], rb"to 1/2/3 hops: \d+ (T_Data_Group|T_DATA_XXX_REQ) "
                                   rb"A_GroupValue_Write \(small\) 00")
        self.assertRegex(lines[1], rb"to 17/5/127 hops: \d+ (T_Data_Group|T_DATA_XXX_REQ) "
                                   rb"A_GroupValue_Write C6 00 0B")

        target1._write.assert_called_once_with(False, [self, group_connector1])
        target2._write.assert_called_once_with(knxdclient.KNXTime(datetime.time(6, 0, 11), 5),
                                               [self, group_connector2])

    @async_test
    async def test_respond(self) -> None:
        _group_connector1 = self.interface.group(knx.KNXGAD(1, 2, 3), "1")\
            .connect(ExampleReadable(bool, True), read=True)  # noqa: F841
        _group_connector2 = self.interface.group(knx.KNXGAD(17, 5, 127), "10")\
            .connect(ExampleReadable(knxdclient.KNXTime, knxdclient.KNXTime(datetime.time(6, 0, 11), 5)),  # noqa: F841
                     read=True)

        self.interface_runner.start()

        # Start busmonitor
        proc = await asyncio.create_subprocess_exec(
            'knxtool',
            'vbusmonitor1',
            f'local://{self.knxd_socket}',
            stdout=asyncio.subprocess.PIPE,
            env=dict(PATH=os.environ['PATH'])
        )
        await asyncio.sleep(0.1)

        try:
            # Send GroupRead requests
            proc2 = await asyncio.create_subprocess_exec('knxtool', 'groupread', f'local://{self.knxd_socket}', '1/2/3',
                                                         env=dict(PATH=os.environ['PATH']))
            await proc2.communicate()
            if proc2.returncode:
                raise RuntimeError(f"knxtool groupread failed with exit code {proc.returncode}")
            await asyncio.sleep(0.1)
            proc2 = await asyncio.create_subprocess_exec('knxtool', 'groupread', f'local://{self.knxd_socket}',
                                                         '17/5/127',
                                                         env=dict(PATH=os.environ['PATH']))
            await proc2.communicate()
            if proc2.returncode:
                raise RuntimeError(f"knxtool groupread failed with exit code {proc.returncode}")
            await asyncio.sleep(0.1)

        except Exception:
            proc.terminate()
            raise

        # Stop busmonitor and gather output
        await asyncio.sleep(0.1)
        proc.terminate()
        stdout, _stderr = await proc.communicate()
        if proc.returncode != -15:
            raise RuntimeError(f"knxtool vbusmonitor1 failed with unexpected exit code {proc.returncode}")

        # Analyze output
        lines = stdout.strip().split(b'\n')
        # lines 0 and 2 should be the GroupRead reqest telegrams
        self.assertRegex(lines[1], rb"to 1/2/3 hops: \d+ (T_Data_Group|T_DATA_XXX_REQ) "
                                   rb"A_GroupValue_Response \(small\) 01")
        self.assertRegex(lines[3], rb"to 17/5/127 hops: \d+ (T_Data_Group|T_DATA_XXX_REQ) "
                                   rb"A_GroupValue_Response C6 00 0B")
