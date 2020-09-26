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
import datetime
import logging
import math
import random
import weakref
from typing import List, Optional, Callable, Any, Type, Union, Tuple, Iterable, Generic

from .base import Subscribable, LogicHandler, Readable, Writable, T, UninitializedError

logger = logging.getLogger(__name__)

HIGH_YEAR = 2200


class _TimerSupervisor:
    """
    Interface-like class to supervise all timer instances, i.e. start them on startup of SHC and let them gracefully
    shutdown.

    Should be used as a singleton instance.
    """
    def __init__(self):
        self.supervised_timers: List[_AbstractScheduleTimer] = []
        self.timer_tasks: List[asyncio.Task] = []
        self.temporary_tasks: weakref.WeakSet[asyncio.Task] = weakref.WeakSet()

    async def start(self) -> None:
        logger.info("Starting TimerSupervisor with %s timers ...", len(self.supervised_timers))
        self.timer_tasks = list(map(lambda timer: asyncio.create_task(timer.run()), self.supervised_timers))

    async def wait(self) -> None:
        await asyncio.gather(*self.timer_tasks, return_exceptions=True)

    async def stop(self) -> None:
        logger.info("Cancelling supervised timers ...")
        for task in self.timer_tasks:
            task.cancel()
        for task in self.temporary_tasks:
            task.cancel()

    def register_timer(self, timer: "_AbstractScheduleTimer") -> None:
        self.supervised_timers.append(timer)

    def add_temporary_task(self, task: asyncio.Task) -> None:
        self.temporary_tasks.add(task)


timer_supervisor = _TimerSupervisor()


async def _logarithmic_sleep(target: datetime.datetime):
    while True:
        diff = (target - datetime.datetime.now().astimezone()).total_seconds()
        if diff < 0.2:
            if diff > 0:
                await asyncio.sleep(diff)
            return
        else:
            await asyncio.sleep(diff / 2)


def _random_time(maximum_offset: Optional[datetime.timedelta], random_function: str = 'uniform') -> datetime.timedelta:
    """
    Generate a random timedelta within a given range.

    :param maximum_offset: The maximum absolute value of the random timedelta. Depending on the random function, this
        might not be interpreted strictly (e.g. for the 'gauss' function, the value does only hit the interval by 96%
        chance). If None, return value is 0 seconds.
    :param random_function: The random function / random distribution to use. Currently supported are 'uniform' and
        'gauss'.
    :return: A timedelta roughly between -maximum_offset and +maximum_offset.
    """
    if not maximum_offset:
        return datetime.timedelta()
    if random_function == 'uniform':
        random_value = random.uniform(-1, 1)
    elif random_function == 'gauss':
        random_value = random.gauss(0, 0.5)
    else:
        raise ValueError("Unsupported random function '{}'".format(random_function))
    return maximum_offset * random_value


class _AbstractScheduleTimer(Subscribable[None], metaclass=abc.ABCMeta):
    """
    Abstract base class for all schedule Timer objects.

    These objects are started upon startup of SHC by the :class:`_TimerSupervisor` and enter into a loop where they
    calculate the next trigger time according to some schedule (dependent on the specific subclass) and await that
    point in time via an asyncio sleep.

    Since the Timer's main loop works the same for every schedule Timer implementation, it is implemented in this
    abstract class. Only the :meth:`_next_execution` method has to be overriden by each subclass to calculate the next
    trigger time (or return None if the Timer object finished its task).

    :ivar:`last_execution`: Timestamp of the last execution. May be used by the *_next_execution* method.
    """
    type = type(None)

    def __init__(self):
        super().__init__()
        timer_supervisor.register_timer(self)
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
    def _next_execution(self) -> Optional[datetime.datetime]:
        pass


class Every(_AbstractScheduleTimer):
    """
    A schedule timer that periodically triggers with a given interval, optionally extended/shortened by a random time.

    It may either be triggered once on startup of SHC and then enter its periodical loop *or* be aligned with the wall
    clock, i.e. be triggered when the current time in the UNIX era is multiple of the interval. This alignment is
    enabled by default. It has the advantage of keeping the length of the interval, even when the SHC application
    is restarted—als long as application's downtime does not fall together with the application's downtime or in the gap
    between calculated time and (random) offset. In this case the trigger execution will be skipped once.

    Thus, if it is important that the trigger being executed with *at least* the given interval, the *align*
    functionality should be turned off. Otherwise it will cause a more stable interval.
    """
    def __init__(self, delta: datetime.timedelta, align: bool = True,
                 offset: datetime.timedelta = datetime.timedelta(), random: Optional[datetime.timedelta] = None,
                 random_function: str = 'uniform'):
        """
        :param delta: The interval between trigger events
        :param align: If True, the interval is kept even after restarts. If False, the timer triggers once upon
            application start up and keeps the interval from that point on.
        :param offset: An offset to add to the trigger times. May be negative. This can be used for explicitly
            offsetting multiple `Every` timers with the same `delta`.
        :param random: A maximum offset to add to or substract from each trigger time. A random timedelta (roughly)
            between -`random` and +`random` will be added to each individual trigger time.
        :param random_function: Identifier of a random distribution function to be used for calculating the `random`
            offset. See :func:`_random_time`'s documentation for supported values.
        """
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
    """
    Decorator for logic handlers to instantiate a :class:`Every` timer and let it trigger the decorated logic handler.

    All positional and keyword arguments are passed to :meth:`Every.__init__`.
    """
    return Every(*args, **kwargs).trigger


class Once(_AbstractScheduleTimer):
    """
    A schedule timer which only triggers only once at startup of the SHC application, optionally delayed by some static
    offset and an additional random offset.
    """
    def __init__(self, offset: datetime.timedelta = datetime.timedelta(), random: Optional[datetime.timedelta] = None,
                 random_function: str = 'uniform'):
        """
        :param offset: The single trigger event is delayed by this timedelta after SHC application startup
        :param random: A maximum offset to add to or substract from each trigger time. A random timedelta (roughly)
            between -`random` and +`random` will be added to the trigger time. If the resulting trigger time lies in the
            past, the trigger will executed directly upon application startup.
        :param random_function: Identifier of a random distribution function to be used for calculating the `random`
            offset. See :func:`_random_time`'s documentation for supported values.
        """
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
    """
    Decorator for logic handlers to instantiate a :class:`Once` timer and let it trigger the decorated logic handler.

    All positional and keyword arguments are passed to :meth:`Once.__init__`.
    """
    return Once(*args, **kwargs).trigger


class EveryNth(int):
    """
    A special integer class to be used as an argument for :meth:`At.__init__` to specify that every nth number of the as
    a valid number of the specific field for triggering the timer.

    E.g. ``month=EveryNth(2)`` equals ``month=[1,3,5,7,9,11]``, ``hour=EveryNth(6) equals hour=[0,6,12,18]``
    """
    pass


ValSpec = Union[int, Iterable[int], EveryNth, None]


class At(_AbstractScheduleTimer):
    """
    Periodic timer which triggers on specific datetime values according to spec based on the Gregorian calendar and wall
    clock times. For each field in (year, month, day, hour, minute, second, millisecond) or (year, week, weekday, hour,
    minute, second, millisecond), a pattern may be specified, which may be

    * `None` (all values allowed for that field)
    * a single `int` value
    * a sorted `list` of valid int values
    * an :class:`EveryNth` object (which is a wrapper around integers): It specifies that every nth value is valid
      (e.g. month=EveryNth(2) equals month=[1,3,5,7,9,11], hour=EveryNth(6) equals hour=[0,6,12,18])

    The timer is scheduled for the next datetime matching the specified pattern of each field.
    """
    def __init__(self,
                 year: ValSpec = None,
                 month: ValSpec = None,
                 day: ValSpec = None,
                 weeknum: ValSpec = None,
                 weekday: ValSpec = None,
                 hour: ValSpec = 0,
                 minute: ValSpec = 0,
                 second: ValSpec = 0,
                 millis: ValSpec = 0,
                 random: Optional[datetime.timedelta] = None,
                 random_function: str = 'uniform'):
        """
        :param year: A pattern for the `year` value of the next trigger date/time (range: 0–2200)
        :param month: A pattern for the `month` value of the next trigger date/time (range: 1–12). Must not be used
            together with `weeknum` or `weekday`.
        :param day: A pattern for the `day of month` value of the next trigger date/time (range: 1–31). Must not be used
            together with `weeknum` or `weekday`.
        :param weeknum: A pattern for the `week of year` value of the next trigger date/time according to the ISO
            weeknumber (range: 1-53).  Must not be used together with `month` or `day`.
        :param weekday: A pattern for the `weekday` value of the next trigger date/time (range: 1(monday) - 7(sunday)).
            Must not be used together with `month` or `day`.
        :param hour: A pattern for the `hour` value of the next trigger time (range: 0–23).
        :param minute: A pattern for the `minute` value of the next trigger time (range: 0–59).
        :param second: A pattern for the `second` value of the next trigger time (range: 0–59).
        :param millis: A pattern for the `millisecond` value of the next trigger time (range: 0–999).
        :param random: A maximum offset to add to or substract from each trigger time. A random timedelta (roughly)
            between -`random` and +`random` will be added to each individual trigger time.
        :param random_function: Identifier of a random distribution function to be used for calculating the `random`
            offset. See :func:`_random_time`'s documentation for supported values.
        """
        super().__init__()
        if weekday is None and weeknum is None:
            self.spec = (year, month, day, hour, minute, second, millis)
            self.week_mode = False
        elif month is None and day is None:
            self.spec = (year, weeknum, weekday, hour, minute, second, millis)
            self.week_mode = True
        else:
            raise ValueError("At-Timer cannot constrain month/day and week/weekday at the same time. Either month and "
                             "day or weeknum and weekday must be None.")
        self.random = random
        self.random_function = random_function

    def _next_execution(self) -> Optional[datetime.datetime]:
        now = datetime.datetime.now()
        # This method iteratively approaches the next execution timestamp according to the self.spec. For this purpose,
        # timestamps are represented as tuples/lists of seven elements:
        # In week-mode: (year, week, weekday, hour, minute, second, millisencond),
        # in month-mode: (year, month, day, hour, minute, second, millisecond)
        # The algorithm uses some kind of simple backtracking: Starting with the current time, it checks each tuple
        # entry's value for compliance with the spec, beginning at the first entry (year). If it does not match, the

        # The lowest value of each entry
        origin = (1, 1, 1, 0, 0, 0, 0)

        def limit(i: int, val: List[int]) -> int:
            """
            Calculate the highest possible value for the entry with index `i` of a tuple/list-timestamp. This may depend
            on the year, month and week of the current value `val`.
            """
            if i > 2:
                return (23, 59, 59, 999)[i - 3]
            if i == 0:
                return HIGH_YEAR
            elif i == 1 and self.week_mode:
                return datetime.date(val[0], 12, 28).isocalendar()[1]  # 52 or 53 depending on the year
                # 29.12., 30.12. and 31.12. may be in week 1 of the next year.
            elif i == 1:
                return 12
            elif i == 2 and self.week_mode:
                return 7
            else:
                return (datetime.date(val[0] + (1 if val[1] == 12 else 0), 1 if val[1] == 12 else val[1] + 1, 1)
                        - datetime.timedelta(days=1)).day

        if self.week_mode:
            val = [now.year, now.isocalendar()[1], now.isocalendar()[2], now.hour, now.minute, now.second,
                   round(now.microsecond / 1000)]
        else:
            val = [now.year, now.month, now.day, now.hour, now.minute, now.second, round(now.microsecond / 1000)]

        # Start with the first entry (year)
        i = 0
        must_increase = False
        # Iterate through entries until all 7 are matching the spec
        while i < 7:
            # In case the entry's current value matches the spec and we didn't flag it to be increased, move on to the
            # next entry
            if not must_increase and self._matches(val[i], self.spec[i], origin[i]):
                i += 1
                continue
            must_increase = False
            # Otherwise calculate the next higher value according to the spec
            new_val = self._next(val[i], self.spec[i], origin[i])
            # If the next higher value is valid, reset all following entries to their minimum values (origin) and
            # proceed with checking the next entry.
            if new_val is not None and new_val <= limit(i, val):
                val[i] = new_val
                i += 1
                for j in range(i, 7):
                    val[j] = origin[j]
            # If there is no valid higher entry, step back one entry: Reset this and all
            # following entries to their minimum values (origin) and proceed with the previous entry, while ensuring it
            # will be increased.
            else:
                i -= 1
                # If we hit the year limit and thus cannot step back any further, return None to indicate that there
                # is no next execution time
                if i < 0:
                    logger.warning("Could not find a next execution time for %s.", self)
                    return None
                for j in range(i + 1, 7):
                    val[j] = origin[j]
                must_increase = True

        if self.week_mode:
            # Unfortunately, the fromisocalendar() function has only been added in Python 3.8:
            # val_date = datetime.date.fromisocalendar(val[0], val[1], val[2])
            val_date = datetime.datetime.strptime("{}-W{}-1".format(val[0], val[1]), '%G-W%V-%u') \
                       + datetime.timedelta(days=val[2]-1)
            result = datetime.datetime(val_date.year, val_date.month, val_date.day, val[3], val[4], val[5],
                                       val[6] * 1000).astimezone()
        else:
            result = datetime.datetime(val[0], val[1], val[2], val[3], val[4], val[5], val[6] * 1000).astimezone()
        return result + _random_time(self.random, self.random_function)

    @staticmethod
    def _matches(val: int, spec: ValSpec, origin) -> bool:
        """
        Check if an entry of a tuple/list-represented timestamp matches the spec value for that entry.
        :param val: The value of the tuple-timestamp entry
        :param spec: The spec for that entry
        :param origin: The minimum value of that entry. It is used to align EveryNth specs.
        :return: True if the current value matches the spec
        """
        if spec is None:
            return True
        if isinstance(spec, Iterable):
            return val in spec
        if isinstance(spec, EveryNth):
            return (val - origin) % spec == 0
        return val == spec

    @staticmethod
    def _next(val: int, spec: ValSpec, origin) -> Optional[int]:
        """
        Calculate the next higher valuer of a tuple/list-represented timestamp entry that matches the spec for that
        entry.
        :param val: The current value of the tuple-timestamp entry
        :param spec: The spec for that entry
        :param origin: The minimum value of that entry. It is used to align EveryNth specs.
        :return: The next higher matching value or None if there is none.
        """
        if spec is None:
            return val + 1
        if isinstance(spec, Iterable):
            try:
                return next(v for v in spec if v > val)
            except StopIteration:
                return None
        if isinstance(spec, EveryNth):
            return val + spec - (val - origin) % spec
        return spec if spec > val else None


def at(*args, **kwargs) -> Callable[[LogicHandler], LogicHandler]:
    """
    Decorator for logic handlers to instantiate a :class:`At` timer and let it trigger the decorated logic handler.

    All positional and keyword arguments are passed to :meth:`At.__init__`.
    """
    return At(*args, **kwargs).trigger


class _DelayedBool(Subscribable[bool], Readable[bool], metaclass=abc.ABCMeta):
    """
    Abstract base class for boolean-based delay timers.

    All derived classes work in a similar way: They wrap a *Subscribable* object of boolean type and re-publish its
    updates according to different rules:

    * :class:`TOn`: Changes from False → True are delayed, while True → False changes are published directly and cancel
        any pending False → True change
    * :class:`TOff`: Changes from True → False are delayed, while False → True changes are published directly and cancel
        any pending True → False change
    * :class:`TOnOff`: Same behaviour as combining a TOn with a TOff, i.e. all changes are delayed and may be
        superseded by a contrary change (in contrast to a simple :class:`Delay` object).
    * :class:`TPulse`: Each True value triggers a True pulse of exactly ``delay`` length, but only if no pulse is
        currently active (i.e. the current value is False; a pulse is not re-triggerable).
    """
    def __init__(self, wrapped: Subscribable[bool], delay: datetime.timedelta):
        self.type = bool
        super().__init__()
        self.delay = delay
        self._value = False
        self._change_task: Optional[asyncio.Task] = None
        wrapped.trigger(self._update)

    @abc.abstractmethod
    async def _update(self, value: bool, origin: List[Any]): ...

    async def read(self) -> bool:
        return self._value

    async def _set_delayed(self, value: bool, origin: List[Any]):
        # Make sure this task is cancelled on shutdown
        current_task = asyncio.current_task()
        assert(current_task is not None)
        timer_supervisor.add_temporary_task(current_task)
        try:
            await _logarithmic_sleep(datetime.datetime.now().astimezone() + self.delay)
        except asyncio.CancelledError:
            return
        self._value = value
        await self._publish(value, origin)
        self._change_task = None


class TOn(_DelayedBool):
    async def _update(self, value: bool, origin: List[Any]):
        if value and self._change_task is None:
            self._change_task = asyncio.create_task(self._set_delayed(True, origin))
        elif not value:
            if self._change_task is not None:
                self._change_task.cancel()
                self._change_task = None
            if self._value:
                self._value = False
                await self._publish(False, origin)


class TOff(_DelayedBool):
    async def _update(self, value: bool, origin: List[Any]):
        if not value and self._change_task is None:
            self._change_task = asyncio.create_task(self._set_delayed(False, origin))
        elif value:
            if self._change_task is not None:
                self._change_task.cancel()
                self._change_task = None
            if not self._value:
                self._value = True
                await self._publish(True, origin)


class TOnOff(_DelayedBool):
    async def _update(self, value: bool, origin: List[Any]):
        if value == self._value and self._change_task is None:
            return
        if self._change_task is not None:
            self._change_task.cancel()
        self._change_task = asyncio.create_task(self._set_delayed(value, origin))


class TPulse(_DelayedBool):
    async def _update(self, value: bool, origin: List[Any]):
        if value and not self._value:
            self._change_task = asyncio.create_task(self._set_delayed(False, origin))
            self._value = True
            await self._publish(True, origin)


class Delay(Subscribable[T], Readable[T], Generic[T]):
    """
    A *Readable* and *Subscribable* object which wraps another Subscribable object and re-publishes its updates after
    the time interval specified by ``delay``. It also *provides* its state/value from ``delay`` time ago.
    """
    def __init__(self, wrapped: Subscribable[T], delay: datetime.timedelta, initial_value: Optional[T] = None):
        self.type = wrapped.type
        super().__init__()
        self.delay = delay
        self._value: Optional[T] = initial_value
        wrapped.trigger(self._update)

    async def _update(self, value: T, origin: List[Any]) -> None:
        asyncio.create_task(self.__set_delayed(value, origin))

    async def __set_delayed(self, value: T, origin: List[Any]):
        # Make sure this task is cancelled on shutdown
        current_task = asyncio.current_task()
        assert(current_task is not None)
        timer_supervisor.add_temporary_task(current_task)
        try:
            await _logarithmic_sleep(datetime.datetime.now() + self.delay)
        except asyncio.CancelledError:
            return
        changed = value != self._value
        logger.debug("Value %s for Delay %s is now active and published", value, self)
        self._value = value
        await self._publish(value, origin)

    async def read(self) -> T:
        if self._value is None:
            raise UninitializedError("{} is not initialized yet.", repr(self))
        return self._value
