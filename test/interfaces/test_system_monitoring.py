import asyncio
import unittest
import unittest.mock

import shc.interfaces.system_monitoring
from shc.supervisor import InterfaceStatus, ServiceStatus
from .._helper import InterfaceThreadRunner, ExampleWritable, async_test


class EventLoopMonitorTest(unittest.TestCase):
    def setUp(self) -> None:
        self.interface_runner = InterfaceThreadRunner(shc.interfaces.system_monitoring.EventLoopMonitor, interval=0.03)
        self.interface = self.interface_runner.interface

    def tearDown(self) -> None:
        self.interface_runner.stop()

    @async_test
    async def test_ok(self) -> None:
        status_target = ExampleWritable(InterfaceStatus)
        connector = self.interface.monitoring_connector()
        connector.connect(status_target)

        self.interface_runner.start()
        await asyncio.sleep(0.1)

        status_target._write.assert_called_with(InterfaceStatus(ServiceStatus.OK, "", unittest.mock.ANY), [connector])
        status = await connector.read()
        self.assertIsInstance(status, InterfaceStatus)
        self.assertGreater(status[2]["tasks_max"], 0)
        self.assertLess(status[2]["tasks_max"], 100)
        self.assertGreater(status[2]["lag_max"], 0.0)
        self.assertLess(status[2]["lag_max"], 0.1)