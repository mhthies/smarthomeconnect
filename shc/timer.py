import abc
import asyncio
import datetime
import logging
import math
import random
from typing import List, Optional, Callable

from .base import Subscribable
from .supervisor import register_interface

logger = logging.getLogger(__name__)


class _TimerSupervisor:
    def __init__(self):
        self.supervised_timers: List[AbstractTimer] = []
        self.timer_tasks: List[asyncio.Task] = []

    async def run(self) -> None:
        logger.info("Starting TimerSupervisor with %s timers ...", len(self.supervised_timers))
        self.timer_tasks = list(map(lambda timer: asyncio.create_task(timer.run()), self.supervised_timers))
        await asyncio.gather(*self.timer_tasks, return_exceptions=True)

    async def stop(self) -> None:
        logger.info("Cancelling supervised timers ...")
        for task in self.timer_tasks:
            task.cancel()

    def register_timer(self, timer):
        self.supervised_timers.append(timer)


_timer_supervisor = _TimerSupervisor()
register_interface(_timer_supervisor)


class AbstractTimer(metaclass=abc.ABCMeta):
    def __init__(self):
        super().__init__()
        _timer_supervisor.register_timer(self)

    @abc.abstractmethod
    async def run(self):
        pass

    @staticmethod
    async def _logarithmic_sleep(target: datetime.datetime):
        while True:
            diff = (target - datetime.datetime.now().astimezone()).total_seconds()
            if diff < 0.2:
                await asyncio.sleep(diff)
                return
            else:
                await asyncio.sleep(diff / 2)


class Every(AbstractTimer, Subscribable[None]):
    def __init__(self, delta: datetime.timedelta, align: bool = True,
                 offset: datetime.timedelta = datetime.timedelta(), random: Optional[datetime.timedelta] = None,
                 random_function: str = 'uniform'):
        super().__init__()
        self.delta = delta
        self.align = align
        self.offset = offset
        self.random = random
        self.random_function = random_function
        self.last_execution: Optional[datetime.datetime] = None

    async def run(self):
        while True:
            next_execution = self._next_execution()
            await self._logarithmic_sleep(next_execution)
            self.last_execution = next_execution
            asyncio.create_task(self._publish(None, []))

    def _next_execution(self) -> datetime.datetime:
        if self.align:
            delta_seconds = self.delta.total_seconds()
            now_timestamp = datetime.datetime.now().timestamp()
            next_execution = datetime.datetime.fromtimestamp(
                (math.floor(now_timestamp / delta_seconds) + 1) * delta_seconds)\
                .astimezone()
        else:
            if self.last_execution is None:
                next_execution = datetime.datetime.now().astimezone()
            else:
                next_execution = self.last_execution + self.delta
        return next_execution + self.offset + self._random_time()

    def _random_time(self) -> datetime.timedelta:
        if not self.random:
            return datetime.timedelta()
        if self.random_function == 'uniform':
            random_value = random.uniform(-1, 1)
        elif self.random_function == 'gauss':
            random_value = random.gauss(0, 0.5)
        else:
            raise ValueError("Unsupported random function '{}'".format(self.random_function))
        return self.random * random_value


def every(*args, **kwargs) -> Callable[[Callable], Callable]:
    return Every(*args, **kwargs).trigger
