# Copyright 2022 Michael Thies <mail@mhthies.de>
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
This module provides pseudo SHC interfaces that allow to monitor fundamental system functionality, such as the Python
asyncio event loop.

These interfaces don't “interface” with anything, but they provide the usual
:meth:`monitoring_connector() <shc.supervisor.AbstractInterface.monitoring_connector>` method to be included in the
:ref:`SHC monitoring <monitoring>` framework and make use of the supervisor for startup and graceful shutdown.
"""

import asyncio
import collections
import functools
from typing import Deque, Tuple

from shc.interfaces._helper import SubscribableStatusInterface
from shc.supervisor import ServiceStatus


class EventLoopMonitor(SubscribableStatusInterface):
    """
    A special SHC interface class for monitoring the health of the asyncio Event Loop.

    This interface does not provide any connectors, but only implements the :meth:`get_status` method for allowing
    external monitoring systems to monitor the health of this application's event loop.

    For this purpose, when started, it regularly checks the current number of asyncio tasks and the delay of scheduled
    function calls in the event loop. These values are reported in the metrics dict of the interface status. The
    interface's service status is determined by comparing these metrics to fixed threshold values.

    :param interval: Interval for checking the function call delay and number of tasks in seconds
    :param num_aggr_samples: Number of intervals to aggregate the measurements. For both, delay and task number, the
        maximum from all samples is reported and compared to the threshold values. Thus, at each time, the monitoring
        status covers a timespan of the last `num_aggr_samples` * `interval` seconds.
    :param lag_warning: Threshold for the scheduled function call delay in seconds to report WARNING state
    :param lag_error: Threshold for the scheduled function call delay in seconds to report CRITICAL state
    :param tasks_warning: Threshold for the number of active/waiting asyncio Tasks to report WARNING state
    :param tasks_error: Threshold for the number of active/waiting asyncio Tasks to report CRITICAL state
    """
    def __init__(self, interval: float = 5.0, num_aggr_samples: int = 60,
                 lag_warning: float = 0.005, lag_error: float = 0.02,
                 tasks_warning: int = 1000, tasks_error: int = 10000):
        super().__init__()
        self.interval = interval
        self.num_aggr_samples = num_aggr_samples
        self.samples: Deque[Tuple[float, int]] = collections.deque()
        self.task: asyncio.Task
        self.tic = 0.0

        self.lag_warning = lag_warning
        self.lag_error = lag_error
        self.tasks_warning = tasks_warning
        self.tasks_error = tasks_error

    async def start(self) -> None:
        self.task = asyncio.create_task(self._monitor_loop())

    async def stop(self) -> None:
        self.task.cancel()
        await self.task

    async def _monitor_loop(self) -> None:
        loop = asyncio.get_running_loop()
        while True:
            self.tic = loop.time()
            loop.call_soon(self._measure_delay)
            try:
                await asyncio.sleep(self.interval)
            except asyncio.CancelledError:
                return

    def _measure_delay(self) -> None:
        lag = asyncio.get_running_loop().time() - self.tic
        queue_length = sum(1 for task in asyncio.all_tasks() if not task.done())
        self.samples.append((lag, queue_length))
        while len(self.samples) > self.num_aggr_samples:
            self.samples.popleft()

        self._update_status()

    def _update_status(self):
        lag_max, tasks_max = functools.reduce(lambda a, i: (max(a[0], i[0]), max(a[1], i[1])), self.samples, (0.0, 0))
        warning = lag_max >= self.lag_warning or tasks_max >= self.tasks_warning
        error = lag_max >= self.lag_error or tasks_max >= self.tasks_error
        self._status_connector.update_status(
            (ServiceStatus.UNKNOWN if len(self.samples) == 0
             else ServiceStatus.CRITICAL if error
             else ServiceStatus.WARNING if warning
             else ServiceStatus.OK),
            "",
            {
                'lag_max': lag_max,
                'tasks_max': tasks_max
            }
        )

    def __repr__(self) -> str:
        return "EventLoopMonitor"
