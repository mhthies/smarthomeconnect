# Copyright 2020-2021 Michael Thies <mail@mhthies.de>
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
import time
import weakref
from typing import List, Optional, Callable, Any, Type, Union, Tuple, Iterable, Generic, TypeVar

from .base import Subscribable, LogicHandler, Readable, Writable, T, UninitializedError, Reading
from .datatypes import RangeFloat1, RangeUInt8, RangeInt0To100, HSVFloat1, RGBUInt8, RGBWUInt8, FadeStep, AbstractStep
from .expressions import ExpressionWrapper

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
            logger.debug("Scheduling next execution of timer %s for %s", self, next_execution)
            await _logarithmic_sleep(next_execution)
            self.last_execution = next_execution
            self._publish(None, [])  # we use asynchronous publishing, so no worries about timing

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
    """
    Decorator for logic handlers to instantiate a :class:`Every` timer and let it trigger the decorated logic handler.

    All positional and keyword arguments are passed to :meth:`Every.__init__`.
    """
    return Every(*args, **kwargs).trigger


class Once(_AbstractScheduleTimer):
    """
    A schedule timer which only triggers only once at startup of the SHC application, optionally delayed by some static
    offset and an additional random offset.

    :param offset: The single trigger event is delayed by this timedelta after SHC application startup
    :param random: A maximum offset to add to or substract from each trigger time. A random timedelta (roughly)
        between -`random` and +`random` will be added to the trigger time. If the resulting trigger time lies in the
        past, the trigger will executed directly upon application startup.
    :param random_function: Identifier of a random distribution function to be used for calculating the `random`
        offset. See :func:`_random_time`'s documentation for supported values.
    """
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
    type = bool

    def __init__(self, wrapped: Subscribable[bool], delay: datetime.timedelta):
        super().__init__()
        self.delay = delay
        self._value = False
        self._change_task: Optional[asyncio.Task] = None
        wrapped.trigger(self._update, synchronous=True)

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
        self._publish(value, origin)
        self._change_task = None

    @property
    def EX(self) -> ExpressionWrapper:
        return ExpressionWrapper(self)


class TOn(_DelayedBool):
    """
    Power-up delay for bool-type *Subscribable* objects

    This object wraps a *Subscribable* bool object and applies a power-up / turn-on delay to its value. I.e., a `False`
    value is re-published immediately, a `True` value is delayed for the configured time period. If a `False` is
    received during the turn-on delay period, the `True` value is superseded and the `TOn`'s value does not change to
    `True` at all.

    The `TOn` object is *Subscribable* and *Readable* for publishing and providing the delayed value. Thus, it can be
    used like an :ref:`SHC Expression <expressions>`. To actually use it in an Expression, you can use the :attr:`EX`
    property, which wraps the `TOn` object in a :class:`shc.expressions.ExpressionWrapper`.

    :param wrapped: The *Subscribable* object to be wrapped for delaying its value
    :param delay: The power-up delay time. E.g. `datetime.timedelta(seconds=5)`
    """
    async def _update(self, value: bool, origin: List[Any]):
        if value and self._change_task is None:
            self._change_task = asyncio.create_task(self._set_delayed(True, origin))
        elif not value:
            if self._change_task is not None:
                self._change_task.cancel()
                self._change_task = None
            if self._value:
                self._value = False
                self._publish(False, origin)


class TOff(_DelayedBool):
    """
    Turn-off delay for bool-type *Subscribable* objects

    This object wraps a *Subscribable* bool object and applies a turn-off delay to its value. I.e., a `True`
    value is re-published immediately, a `False` value is delayed for the configured time period. If a `True` is
    received during the turn-off delay period, the `False` value is superseded and the `TOff`'s value does stay `True`
    continuously.

    The `TOff` object is *Subscribable* and *Readable* for publishing and providing the delayed value. Thus, it can be
    used like an :ref:`SHC Expression <expressions>`. To actually use it in an Expression, you can use the :attr:`EX`
    property, which wraps the `TOff` object in a :class:`shc.expressions.ExpressionWrapper`.

    :param wrapped: The *Subscribable* object to be wrapped for delaying its value
    :param delay: The turn-off delay time. E.g. `datetime.timedelta(seconds=5)`
    """
    async def _update(self, value: bool, origin: List[Any]):
        if not value and self._change_task is None:
            self._change_task = asyncio.create_task(self._set_delayed(False, origin))
        elif value:
            if self._change_task is not None:
                self._change_task.cancel()
                self._change_task = None
            if not self._value:
                self._value = True
                self._publish(True, origin)


class TOnOff(_DelayedBool):
    """
    Resettable boolean-delay for *Subscribable* objects

    This object wraps a *Subscribable* bool object and applies a delay to its value. It behaves like a series of a
    :class:`TOn` and a :class:`TOff` timer with the same delay time: All value updates of the wrapped object will be
    delayed. Albeit, in contrast to a :class:`Delay` timer, a value update can be aborted by sending the
    contrary value during the delay period. Thus, short pulses in either direction (fast False→True→False or
    True→False→True toggling) is suppressed in the `TOnOff`'s value.

    Like all delay timers, the `TOnOff` object is *Subscribable* and *Readable* for publishing and providing the delayed
    value. Thus, it can be used like an :ref:`SHC Expression <expressions>`. To actually use it in an Expression, you
    can use the :attr:`EX` property, which wraps the `TOnOff` object in a :class:`shc.expressions.ExpressionWrapper`.

    :param wrapped: The *Subscribable* object to be wrapped for delaying its value
    :param delay: The delay time. E.g. `datetime.timedelta(seconds=5)`
    """
    async def _update(self, value: bool, origin: List[Any]):
        if value == self._value and self._change_task is None:
            return
        if self._change_task is not None:
            self._change_task.cancel()
        self._change_task = asyncio.create_task(self._set_delayed(value, origin))


class TPulse(_DelayedBool):
    """
    Non-retriggerable pulse generator for bool-typed *Subscribable* objects

    This object wraps a *Subscribable* bool object and creates a fixed length pulse (`True` period) on each rising edge
    (False→True) change of its value. The pulse is not retriggerable, i.e. it is not prolonged when a second raising
    edge occurs during the pulse.

    Like all delay timers, the `TPulse` object is *Subscribable* and *Readable* for publishing and providing the pulse
    signal. Thus, it can be used like an :ref:`SHC Expression <expressions>`. To actually use it in an Expression, you
    can use the :attr:`EX` property, which wraps the `TPulse` object in a :class:`shc.expressions.ExpressionWrapper`.

    :param wrapped: The *Subscribable* object to be wrapped for delaying its value
    :param delay: The pulse length. E.g. `datetime.timedelta(seconds=5)`
    """
    def __init__(self, wrapped: Subscribable[bool], delay: datetime.timedelta):
        super().__init__(wrapped, delay)
        self._prev_value = False

    async def _update(self, value: bool, origin: List[Any]):
        rising_edge = value and not self._prev_value
        self._prev_value = value
        if rising_edge and not self._value:
            self._change_task = asyncio.create_task(self._set_delayed(False, origin))
            self._value = True
            self._publish(True, origin)


class Delay(Subscribable[T], Readable[T], Generic[T]):
    """
    A *Readable* and *Subscribable* object which wraps another Subscribable object and re-publishes its updates after
    the time interval specified by ``delay``. It also *provides* the state/value from ``delay`` time ago via ``read()``
    calls.

    :param wrapped: The *Subscribable* object to be wrapped for delaying its value
    :param delay: The delay time. E.g. `datetime.timedelta(seconds=5)`
    :param initial_value: If given, the value which is returned by :meth:`read` before a value has been received from
        the `wrapped` object (and passed the delay period). If not given, :meth:`read` raises an
        :class:`shc.base.UninitializedError` in this case.
    """
    def __init__(self, wrapped: Subscribable[T], delay: datetime.timedelta, initial_value: Optional[T] = None):
        self.type = wrapped.type
        super().__init__()
        self.delay = delay
        self._value: Optional[T] = initial_value
        wrapped.trigger(self._update, synchronous=True)

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
        self._publish(value, origin)

    async def read(self) -> T:
        if self._value is None:
            raise UninitializedError("{} is not initialized yet.", repr(self))
        return self._value

    @property
    def EX(self) -> ExpressionWrapper:
        return ExpressionWrapper(self)


class TimerSwitch(Subscribable[bool], Readable[bool]):
    """
    A helper to program something similar to those old-fashioned digital timer switch adaptors

    A `TimerSwitch` is basically a bool Variable with a fancy constructor to let some timers set the variable to True or
    False. Additionally, a `duration` mode is built in, which allows to specify a duration after which the `TimerSwitch`
    switches off (is set to False) automatically – similar to the :class:`TPulse` timer (but with re-trigger-ability).

    A simple usage example for switching on at 8:00 and off at 13:37, but 9:00 and 15:00 on weekends may look like::

        timer_switch = TimerSwitch(on=[At(weekday=[1,2,3,4,5], hour=8),
                                       At(weekday=[6,7], hour=9),
                                   off=[At(weekday=[1,2,3,4,5], hour=13, minute=37),
                                        At(weekday=[6,7], hour=15)]
        my_ceiling_lights.connect(timer_switch)

    To enable or disable the `TimerSwitch`, you may want to take a look at the :class:`shc.misc.BreakableSubscription`.

    :param on: A list of timers which should trigger a 'switch on' action (i.e. set the `TimerSwitch`'s value to True
        when triggering)
    :param off: A list of timers which should trigger a 'switch off' action (i.e. set the `TimerSwitch`'s value to
        False when triggering). Either this parameter or the `duration` (but not both) must be specified.
    :param duration: Period of time, after which the `TimerSwitch` will be switched off automatically after each
        'switch on' event. Must be used as an alternative to the `off` parameter.
    :param duration_random: An optional (maximum) offset to add to or substract from the `duration` period. If
        `duration` is used, a random timedelta between ``-duration_random`` and ``+duration_random`` will be added to
        each individual 'on' period.
    """
    type = bool

    def __init__(self, on: Iterable[Subscribable], off: Optional[Iterable[Subscribable]] = None,
                 duration: Optional[datetime.timedelta] = None, duration_random: Optional[datetime.timedelta] = None):
        super().__init__()
        if not off and duration is None:
            raise ValueError("Either 'off' timer specs or a 'duration' must be specified")
        if off and duration is not None:
            raise ValueError("'off' timer specs and a 'duration' cannot be specified at the same time")
        if duration_random and duration is None:
            raise ValueError("A 'duration_random' value does not make sense without a duration")

        self.value = False
        self.duration = duration
        self.duration_random = duration_random
        self.delay_task: Optional[asyncio.Task] = None

        for on_timer in on:
            on_timer.trigger(self._on, synchronous=True)
        if off:
            for off_timer in off:
                off_timer.trigger(self._off, synchronous=True)

    async def _on(self, _v, origin) -> None:
        if not self.value:
            self.value = True
            self._publish(True, origin)
        if self.duration is not None:
            if self.delay_task is not None:
                self.delay_task.cancel()
            self.delay_task = asyncio.create_task(self._delayed_off(origin))
            timer_supervisor.add_temporary_task(self.delay_task)

    async def _off(self, _v, origin) -> None:
        if self.value:
            self.value = False
            self._publish(False, origin)

    async def _delayed_off(self, origin) -> None:
        assert(self.duration is not None)
        await _logarithmic_sleep(datetime.datetime.now().astimezone() + self.duration
                                 + _random_time(self.duration_random))
        await self._off(False, origin)

    async def read(self) -> bool:
        return self.value

    @property
    def EX(self) -> ExpressionWrapper:
        return ExpressionWrapper(self)


class RateLimitedSubscription(Subscribable[T], Generic[T]):
    """
    A transparent wrapper for `Subscribable` objects, that delays and drops values to make sure that a given maximum
    rate of new values is not exceeded.

    :param wrapped: The Subscribable object to be wrapped
    :param min_interval: The minimal allowed interval between published values in seconds
    """
    def __init__(self, wrapped: Subscribable[T], min_interval: float):
        self.type = wrapped.type
        super().__init__()
        wrapped.trigger(self._new_value, synchronous=True)
        self.min_interval = min_interval
        self._last_publish = 0.0
        self._delay_task: Optional[asyncio.Task] = None
        self._latest_value: T
        self._latest_origin: List[Any]

    async def _new_value(self, value: T, origin: List[Any]) -> None:
        next_allowed_publish = self._last_publish + self.min_interval
        now = time.time()
        if now >= next_allowed_publish:
            self._last_publish = now
            self._publish(value, origin)
        else:
            self._latest_value = value
            self._latest_origin = origin
            if not self._delay_task:
                self._delay_task = asyncio.create_task(self._delayed_publish(next_allowed_publish - now))
                timer_supervisor.add_temporary_task(self._delay_task)

    async def _delayed_publish(self, delay: float):
        await asyncio.sleep(delay)
        self._last_publish = time.time()
        self._delay_task = None
        self._publish(self._latest_value, self._latest_origin)


class AbstractRamp(Readable[T], Subscribable[T], Reading[T], Writable[T], Generic[T], metaclass=abc.ABCMeta):
    """
    Abstract base class for all ramp generators

    All ramp generators create smooth transitions from incoming value updates by splitting publishing multiple timed
    updates each doing a small step towards the target value. They are *Readable* and *Subscribable* to be used in
    :ref:`expressions`.

    In addition, the Ramp generators are *Writable* and *Reading* in order to connect them to a stateful object (like a
    :class:`Variable <shc.variables.Variable>`) which also receives value updates from other sources. For this to work
    flawlessly, the Ramp generator will stop the current ramp in progress, when it receives a value (via :meth:`write`)
    from the connected object and it will *read* the current value of the connected object and use it as the start value
    for a ramp instead of the last value received from the wrapped object. Both of these features are optional, so the
    Ramp generator can also be connected to non-readable and non-subscribable objects.

    Different derived ramp generator classes for different datatypes exist:

    - :class:`IntRamp` (for :class:`int`, :class:`shc.datatypes.RangeUInt8` and :class:`shc.datatypes.RangeInt0To100`)
    - :class:`FloatRamp` (for :class:`float` and :class:`shc.datatypes.RangeFloat1`)
    - :class:`HSVRamp` (for :class:`shc.datatypes.HSVFloat1`)
    - :class:`RGBHSVRamp` (doing a linear ramp in HSV color space for :class:`shc.datatypes.RGBUInt8`)
    - :class:`RGBWHSVRamp` (for :class:`shc.datatypes.RGBWUInt8`; doing a linear ramp in HSV color space plus simple
      linear ramp for the white channel)

    All of these ramp generator types allow to wrap a Subscribable object of one of their value types to subscribe to
    its value updates to turn them into ramps. Alternatively, they can be initialized with only the concrete value type
    only, so the :meth:`ramp_to` method can be triggered manually from logic handlers etc.

    As a special case, there's the :class:`FadeStepRamp`, which is a RangeFloat1-typed Connectable object, which wraps
    a Subscribable object of type :class:`shc.datatypes.FadeStep` and creates ramps from the received fade steps
    (similar to :class:`shc.misc.FadeStepAdapter`).

    In addition, all of them take the following init parameters:

    :param ramp_duration: The duration of the generated ramp/transition. Depending on `dynamic_duration` this is either
        the fixed duration of each ramp or it is the duration of a ramp across the full value range, which is
        dynamically lowered for smaller ramps.
    :param dynamic_duration: If `True` (default) the duration of each ramp is dynamically calculated, such that all
        ramps/transitions have the same "speed" (only works for Range- and Range-based types). In this case,
        `ramp_duration` defines the speed by specifying the maximum duration, resp. the duration of a range across the
        full value range. If `False`, all ramps/transitions are stretched to the fixed duration.
    :param max_frequency: The maximum frequency of value updates to be emitted by the ramp generator in updates per
        second (i.e. the "frame rate" of the ramp animation). The frequency is be dynamically reduced, if the resolution
        of the datatype cannot render the resulting number of steps/frames.
    :param enable_ramp: Optional bypass: If a bool-typed *readable* object is provided, it is read at the beginning of
        each received value update. If its value evaluates to `False`, the ramp is bypassed and the new target value is
        republished immediately. If the value is `True`, the ramp generator is enabled. If no object is given, the ramp
        generator is always on.
    """
    is_reading_optional = False

    def __init__(self, type_: Type[T], ramp_duration: datetime.timedelta, dynamic_duration: bool = True,
                 max_frequency: float = 25.0, enable_ramp: Optional[Readable[bool]] = None):
        self.type = type_
        super().__init__()
        self.ramp_duration = ramp_duration
        self.dynamic_duration = dynamic_duration
        self.max_frequency = max_frequency
        self.enable_ramp = enable_ramp
        self._current_value: Optional[T] = None
        self.__new_target_value: Optional[T] = None
        self.__task: Optional[asyncio.Task] = None

    async def read(self) -> T:
        if self._current_value is None:
            raise UninitializedError("RampGenerator has no value received yet.")
        return self._current_value

    async def _write(self, value: T, origin: List[Any]) -> None:
        if self.__task:
            self.__task.cancel()

    async def ramp_to(self, value: T, origin: List[Any]) -> None:
        """
        Start a new ramp to the the given value.

        This method is triggered automatically by the wrapped *Subscribable* object. It can also be triggered
        programmatically from logic handlers etc.
        """
        if self.enable_ramp is not None:
            enabled = await self.enable_ramp.read()
            if not enabled:
                if self.__task:
                    self.__task.cancel()
                self._current_value = value
                await self._publish_and_wait(value, origin)
                return
        begin = await self._from_provider()
        if begin is not None:
            self._current_value = begin
        if self._current_value is None:
            self._current_value = value
            await self._publish_and_wait(value, origin)
            return

        self.__new_target_value = value
        if not self.__task:
            task = asyncio.get_event_loop().create_task(self._ramp())
            self.__task = task
            timer_supervisor.add_temporary_task(task)

    async def ramp_by(self, step: AbstractStep[T], origin: List[Any]) -> None:
        """
        Start a new ramp of the given step size
        """
        begin = await self._from_provider()
        if begin is not None:
            self._current_value = begin
        if self._current_value is None:
            logger.warning("Cannot apply FadeStep, since current value is not available.")
            return

        if self.enable_ramp is not None:
            enabled = await self.enable_ramp.read()
            if not enabled:
                if self.__task:
                    self.__task.cancel()
                self._current_value = step.apply_to(self._current_value)
                await self._publish_and_wait(self._current_value, origin)
                return

        self.__new_target_value = step.apply_to(self._current_value)
        if not self.__task:
            task = asyncio.get_event_loop().create_task(self._ramp())
            self.__task = task
            timer_supervisor.add_temporary_task(task)

    async def _ramp(self) -> None:
        step = 0
        num_steps = 0
        try:
            assert self.__new_target_value is not None
            while step < num_steps or self.__new_target_value is not None:
                # New target => recalculate steps
                if self.__new_target_value is not None:
                    begin = self._current_value
                    assert begin is not None
                    target = self.__new_target_value
                    self.__new_target_value = None
                    height, max_steps = self._calculate_ramp(begin, target)
                    length = self.ramp_duration.total_seconds() * (height if self.dynamic_duration else 1.0)
                    num_steps = min(math.ceil(length * self.max_frequency), max_steps)
                    if num_steps == 0:
                        break
                    step_length = length / num_steps
                    self._init_ramp(begin, target, num_steps)
                    step = 0
                step += 1
                value = self._next_step(step)
                if value != self._current_value:
                    self._publish(value, [])
                    self._current_value = value
                await asyncio.sleep(step_length)

            # Mitigate deriving values from rounding errors etc.
            if target != self._current_value:
                self._publish(target, [])
                self._current_value = target
        except asyncio.CancelledError:
            pass
        finally:
            self.__task = None

    @abc.abstractmethod
    def _calculate_ramp(self, begin: T, target: T) -> Tuple[float, int]:
        """
        Calculate height and maximum reasonable number of steps of a ramp to be performed

        The maximum reasonable number of steps is typically constraint be the resolution of the datatype. In most cases,
        it is not reasonable to compute more steps than the datatype can represent values between begin and target.

        The height of the ramp must always be positive and in [0, 1].

        :param begin: The planned start value of the ramp
        :param target: The planned target value of the ramp
        :return: Tuple of (height of the ramp as part of the full range, maximum reasonable number of steps)
        """
        pass

    @abc.abstractmethod
    def _init_ramp(self, begin: T, target: T, num_steps: int) -> None:
        """
        Initialize a new ramp

        This method is called whenever a new ramp is started and can do any form of pre-calculation for the ramp steps.
        The calculated internal values, are supposed to be stored as attributes of `self` such that they can be used by
        :meth:`_next_step` afterwareds.

        Attention: An ongoing ramp may be interrupted by a new target value. In this case, :meth:`_init_ramp` is called
        again, before all steps of the ramp have been computed. Afterwards, the the `step` counter is reset to 1 and
        :meth:`_next_step` is called again for each step of the new ramp.

        :param begin: The start value of the ramp
        :param target: The target value of the ramp
        :param num_steps: The number of steps. This number is fixed in advanced; all steps will be performed (unless the
            ramp is interrupted)
        """
        pass

    @abc.abstractmethod
    def _next_step(self, step: int) -> T:
        """
        Calculate the next step of the ramp.

        This method can rely on any data generated by :meth:`_init_ramp`. For easier implementation, the step counter is
        passed to the method.

        Attention: An ongoing ramp may be interrupted by a new target value. In this case, :meth:`_init_ramp` is called
        again, before all steps of the ramp have been computed. Afterwards, the the `step` counter is reset to 1 and
        :meth:`_next_step` is called again for each step of the new ramp.

        :param step: Step counter, starting at 1 (!) and running up to (including!) num_steps.
        :return: The calculated value of this step, to be published
        """
        pass


IntRampT = TypeVar('IntRampT', int, RangeUInt8, RangeInt0To100)


class IntRamp(AbstractRamp[IntRampT], Generic[IntRampT]):
    def __init__(self, wrapped_or_type: Union[Subscribable[IntRampT], Type[IntRampT]], *args, **kwargs):
        if isinstance(wrapped_or_type, Subscribable):
            type_: Type[IntRampT] = wrapped_or_type.type
            wrapped_or_type.trigger(self.ramp_to, synchronous=True)
        else:
            type_ = wrapped_or_type
        super().__init__(type_, *args, **kwargs)  # type: ignore  # Mypy does not understand that type_ *is*  FloatRampT

    def _calculate_ramp(self, begin: IntRampT, target: IntRampT) -> Tuple[float, int]:
        diff = abs(target-begin)
        height = (diff/255 if issubclass(self.type, RangeUInt8) else
                  diff/100 if issubclass(self.type, RangeInt0To100) else
                  1.0)
        return height, diff

    def _init_ramp(self, begin: IntRampT, target: IntRampT, num_steps: int) -> None:
        self._begin: IntRampT = begin
        self._diff: float = (target - begin) / num_steps

    def _next_step(self, step: int) -> IntRampT:
        return self.type(round(self._begin + self._diff * step))


FloatRampT = TypeVar('FloatRampT', float, RangeFloat1)


class AbstractFloatRamp(AbstractRamp[FloatRampT], Generic[FloatRampT]):
    def _calculate_ramp(self, begin: FloatRampT, target: FloatRampT) -> Tuple[float, int]:
        diff = abs(target-begin)
        height = diff/1.0 if issubclass(self.type, RangeFloat1) else 1.0
        return height, 2**64-1

    def _init_ramp(self, begin: FloatRampT, target: FloatRampT, num_steps: int) -> None:
        self._begin: FloatRampT = begin
        self._diff: float = (target - begin) / num_steps

    def _next_step(self, step: int) -> FloatRampT:
        return self.type(self._begin + self._diff * step)


class FloatRamp(AbstractFloatRamp[FloatRampT], Generic[FloatRampT]):
    def __init__(self, wrapped_or_type: Union[Subscribable[FloatRampT], Type[FloatRampT]], *args, **kwargs):
        if isinstance(wrapped_or_type, Subscribable):
            type_: Type[FloatRampT] = wrapped_or_type.type
            wrapped_or_type.trigger(self.ramp_to, synchronous=True)
        else:
            type_ = wrapped_or_type
        super().__init__(type_, *args, **kwargs)  # type: ignore  # Mypy does not understand that type_ *is*  FloatRampT


class FadeStepRamp(AbstractFloatRamp[RangeFloat1]):
    def __init__(self, wrapped: Subscribable[FadeStep], *args, **kwargs):
        super().__init__(RangeFloat1, *args, **kwargs)
        wrapped.trigger(self.ramp_by, synchronous=True)


def _normalize_hsv_ramp(begin: HSVFloat1, target: HSVFloat1) -> Tuple[HSVFloat1, HSVFloat1]:
    return begin._replace(hue=begin.hue if begin.saturation != 0 else target.hue,
                          saturation=begin.saturation if begin.value != 0 else target.saturation),\
           target._replace(hue=target.hue if target.saturation != 0 else begin.hue,
                           saturation=target.saturation if target.value != 0 else begin.saturation)


def _hsv_diff(begin: HSVFloat1, target: HSVFloat1) -> Tuple[float, float, float]:
    return (
        ((target.hue - begin.hue) % 1
         if abs((target.hue - begin.hue) % 1) < 0.5
         else -((begin.hue - target.hue) % 1)
         ),
        (target.saturation - begin.saturation),
        (target.value - begin.value)
    )


def _hsv_step(begin: HSVFloat1, diff: Tuple[float, float, float], step: int) -> HSVFloat1:
    return HSVFloat1(RangeFloat1((begin.hue + diff[0] * step) % 1.0),
                     RangeFloat1(begin.saturation + diff[1] * step),
                     RangeFloat1(begin.value + diff[2] * step))


class HSVRamp(AbstractRamp[HSVFloat1]):
    def __init__(self, wrapped: Optional[Subscribable[HSVFloat1]], *args, **kwargs):
        super().__init__(HSVFloat1, *args, **kwargs)
        if wrapped is not None:
            wrapped.trigger(self.ramp_to, synchronous=True)

    def _calculate_ramp(self, begin: HSVFloat1, target: HSVFloat1) -> Tuple[float, int]:
        diff = _hsv_diff(begin, target)
        height = max(abs(diff[0] * 2), abs(diff[1]), abs(diff[2]))
        return height, 2**64-1

    def _init_ramp(self, begin: HSVFloat1, target: HSVFloat1, num_steps: int) -> None:
        self._begin = begin
        self._diff: Tuple[float, float, float] = tuple(v/num_steps for v in _hsv_diff(begin, target))  # type: ignore

    def _next_step(self, step: int) -> HSVFloat1:
        return _hsv_step(self._begin, self._diff, step)


class RGBHSVRamp(AbstractRamp[RGBUInt8]):
    def __init__(self, wrapped: Optional[Subscribable[RGBUInt8]], *args, **kwargs):
        super().__init__(RGBUInt8, *args, **kwargs)
        if wrapped is not None:
            wrapped.trigger(self.ramp_to, synchronous=True)

    def _calculate_ramp(self, begin: RGBUInt8, target: RGBUInt8) -> Tuple[float, int]:
        begin_hsv, target_hsv = _normalize_hsv_ramp(HSVFloat1.from_rgb(begin.as_float()),
                                                    HSVFloat1.from_rgb(target.as_float()))
        diff = _hsv_diff(begin_hsv, target_hsv)
        height = max(abs(diff[0] * 2), abs(diff[1]), abs(diff[2]))
        max_steps = max(2*abs(b-t) for b, t in zip(begin, target))  # rough estimation
        return height, max_steps

    def _init_ramp(self, begin: RGBUInt8, target: RGBUInt8, num_steps: int) -> None:
        begin_hsv, target_hsv = _normalize_hsv_ramp(HSVFloat1.from_rgb(begin.as_float()),
                                                    HSVFloat1.from_rgb(target.as_float()))
        self._hsv_begin = begin_hsv
        hsv_diff = _hsv_diff(begin_hsv, target_hsv)
        self._hsv_diff: Tuple[float, float, float] = tuple(v/num_steps for v in hsv_diff)  # type: ignore

    def _next_step(self, step: int) -> RGBUInt8:
        return RGBUInt8.from_float(_hsv_step(self._hsv_begin, self._hsv_diff, step).as_rgb())


class RGBWHSVRamp(AbstractRamp[RGBWUInt8]):
    def __init__(self, wrapped: Optional[Subscribable[RGBWUInt8]], *args, **kwargs):
        super().__init__(RGBWUInt8, *args, **kwargs)
        if wrapped is not None:
            wrapped.trigger(self.ramp_to, synchronous=True)

    def _calculate_ramp(self, begin: RGBWUInt8, target: RGBWUInt8) -> Tuple[float, int]:
        begin_hsv, target_hsv = _normalize_hsv_ramp(HSVFloat1.from_rgb(begin.rgb.as_float()),
                                                    HSVFloat1.from_rgb(target.rgb.as_float()))
        hsv_diff = _hsv_diff(begin_hsv, target_hsv)
        w_diff = abs(target.white - begin.white)
        height = max(abs(hsv_diff[0] * 2), abs(hsv_diff[1]), abs(hsv_diff[2]), w_diff / 255)
        max_steps = max(*(2*abs(b-t) for b, t in zip(begin.rgb, target.rgb)), w_diff)  # rough estimation
        return height, max_steps

    def _init_ramp(self, begin: RGBWUInt8, target: RGBWUInt8, num_steps: int) -> None:
        self._w_begin: int = begin.white
        self._w_diff: float = (target.white - begin.white) / num_steps
        begin_hsv, target_hsv = _normalize_hsv_ramp(HSVFloat1.from_rgb(begin.rgb.as_float()),
                                                    HSVFloat1.from_rgb(target.rgb.as_float()))
        self._hsv_begin = begin_hsv
        hsv_diff = _hsv_diff(begin_hsv, target_hsv)
        self._hsv_diff: Tuple[float, float, float] = tuple(v/num_steps for v in hsv_diff)  # type: ignore

    def _next_step(self, step: int) -> RGBWUInt8:
        return RGBWUInt8(RGBUInt8.from_float(_hsv_step(self._hsv_begin, self._hsv_diff, step).as_rgb()),
                         RangeUInt8(round(self._w_begin + self._w_diff * step)))
