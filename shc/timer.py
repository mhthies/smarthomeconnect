import abc
import asyncio
import datetime
import logging
import math
import random
from typing import List, Optional, Callable, Any, Type

from .base import Subscribable, LogicHandler, Readable, Writable, T, UninitializedError
from .supervisor import register_interface

logger = logging.getLogger(__name__)


class _TimerSupervisor:
    def __init__(self):
        self.supervised_timers: List[_AbstractTimer] = []
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


async def _logarithmic_sleep(target: datetime.datetime):
    while True:
        diff = (target - datetime.datetime.now().astimezone()).total_seconds()
        if diff < 0.2:
            if diff > 0:
                await asyncio.sleep(diff)
            return
        else:
            await asyncio.sleep(diff / 2)


def _random_time(random_range: Optional[datetime.timedelta], random_function: str = 'uniform') -> datetime.timedelta:
    if not random_range:
        return datetime.timedelta()
    if random_function == 'uniform':
        random_value = random.uniform(-1, 1)
    elif random_function == 'gauss':
        random_value = random.gauss(0, 0.5)
    else:
        raise ValueError("Unsupported random function '{}'".format(random_function))
    return random_range * random_value


class _AbstractTimer(Subscribable[None], metaclass=abc.ABCMeta):
    def __init__(self):
        super().__init__()
        _timer_supervisor.register_timer(self)
        self.last_execution: Optional[datetime.datetime] = None

    async def run(self):
        while True:
            next_execution = self._next_execution()
            if next_execution is None:
                logger.info("Timer %s has fulfilled its job and is quitting now.", self)
                return
            logger.info("Scheduling next execution of timer %s for %s", self, next_execution)
            await _logarithmic_sleep(next_execution)
            self.last_execution = next_execution
            asyncio.create_task(self._publish(None, []))

    @abc.abstractmethod
    def _next_execution(self) -> datetime.datetime:
        pass


class Every(_AbstractTimer):
    def __init__(self, delta: datetime.timedelta, align: bool = True,
                 offset: datetime.timedelta = datetime.timedelta(), random: Optional[datetime.timedelta] = None,
                 random_function: str = 'uniform'):
        super().__init__()
        self.delta = delta
        self.align = align
        self.offset = offset
        self.random = random
        self.random_function = random_function

    def _next_execution(self) -> Optional[datetime.datetime]:
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
        return next_execution + self.offset + _random_time(self.random, self.random_function)


def every(*args, **kwargs) -> Callable[[LogicHandler], LogicHandler]:
    return Every(*args, **kwargs).trigger


class Once(_AbstractTimer):
    def __init__(self, offset: datetime.timedelta = datetime.timedelta(), random: Optional[datetime.timedelta] = None,
                 random_function: str = 'uniform'):
        super().__init__()
        self.offset = offset
        self.random = random
        self.random_function = random_function
        self.is_executed = False

    def _next_execution(self) -> Optional[datetime.datetime]:
        if self.is_executed:
            return None
        self.is_executed = True
        return datetime.datetime.now().astimezone() + self.offset + _random_time(self.random, self.random_function)


def once(*args, **kwargs) -> Callable[[LogicHandler], LogicHandler]:
    return Once(*args, **kwargs).trigger


# TODO At()


class _DelayedBool(Subscribable[bool], Readable[bool], Writable[bool], metaclass=abc.ABCMeta):
    def __init__(self, delay: datetime.timedelta):
        self.type = bool
        super().__init__()
        self.delay = delay
        self._value = False
        self._change_task = Optional[asyncio.Task]

    async def read(self) -> bool:
        return self._value

    async def __set_delayed(self, value: bool, source: List[Any]):
        try:
            await _logarithmic_sleep(datetime.datetime.now() + self.delay)
        except asyncio.CancelledError:
            return
        self._value = value
        await self._publish(value, source)
        self._change_task = None


class TOn(_DelayedBool):
    async def _write(self, value: bool, source: List[Any]):
        if value and self._change_task is None:
            self._change_task = asyncio.create_task(self.__set_delayed(True, source))
        elif not value:
            if self._change_task is not None:
                self._change_task.cancel()
                self._change_task = None
            self._value = False
            await self._publish(False, source)


class TOff(_DelayedBool):
    async def _write(self, value: bool, source: List[Any]):
        if not value and self._change_task is None:
            self._change_task = asyncio.create_task(self.__set_delayed(True, source))
        elif value:
            if self._change_task is not None:
                self._change_task.cancel()
                self._change_task = None
            self._value = False
            await self._publish(False, source)


class TOnOff(_DelayedBool):
    async def _write(self, value: bool, source: List[Any]):
        if value == self._value and self._change_task is None:
            return
        if self._change_task is not None:
            self._change_task.cancel()
        self._change_task = asyncio.create_task(self.__set_delayed(value, source))


class TPulse(_DelayedBool):
    async def _write(self, value: bool, source: List[Any]):
        if value and not self._value:
            self._change_task = asyncio.create_task(self.__set_delayed(False, source))
            self._value = True
            await self._publish(True, source)


class Delay(Subscribable[bool], Readable[bool], Writable[bool], metaclass=abc.ABCMeta):
    def __init__(self, type_: Type[T], delay: datetime.timedelta, initial_value: Optional[T] = None):
        self.type = type_
        super().__init__()
        self.delay = delay
        self._value: Optional[T] = initial_value

    async def _write(self, value: T, source: List[Any]) -> None:
        asyncio.create_task(self.__set_delayed(value, source))

    async def __set_delayed(self, value: T, source: List[Any]):
        try:
            await _logarithmic_sleep(datetime.datetime.now() + self.delay)
        except asyncio.CancelledError:
            return
        changed = value != self._value
        logger.debug("Value %s for Delay %s is now active and published", value, self)
        self._value = value
        await self._publish(value, source, changed)

    async def read(self) -> T:
        if self._value is None:
            raise UninitializedError("Variable {} is not initialized yet.", repr(self))
        return self._value
