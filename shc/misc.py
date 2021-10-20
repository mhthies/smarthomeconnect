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

import datetime
import logging
from typing import Generic, Type, List, Any, Optional, Callable

from shc import conversion
from shc.base import Readable, Subscribable, Writable, handler, T, ConnectableWrapper, UninitializedError, Reading, S
from shc.datatypes import RangeFloat1, FadeStep
from shc.expressions import ExpressionWrapper
from shc.timer import Every

logger = logging.getLogger(__name__)

"""
This module contains some helper/adapter classes to support special patterns of interconnection of :class:`Connectable`
objects.
"""


class PeriodicReader(Readable[T], Subscribable[T], Generic[T]):
    """
    Wraps a :class:`Readable` object to turn it into :class:`Subscribable` object by periodically reading and publishing
    its value.

    :param wrapped: The *Readable* object, which shall be wrapped and read periodically
    :param interval: The interval in which the object's `.read()` coroutine is called and the result is published, e.g.
        ``datetime.timedelta(seconds=15)``.
    """
    def __init__(self, wrapped: Readable[T], interval: datetime.timedelta):
        self.type = wrapped.type
        super().__init__()
        self.wrapped = wrapped
        self.timer = Every(interval)
        self.timer.trigger(self.do_read, synchronous=True)

    async def read(self) -> T:
        return await self.wrapped.read()

    async def do_read(self, _value, origin) -> None:
        # We add the wrapped Readable object to the `origin` list to avoid publishing back its own value, in case it is
        # subscribed to one of our subscribers (e.g. a variable).
        self._publish(await self.wrapped.read(), origin + [self.wrapped])


class TwoWayPipe(ConnectableWrapper[T], Generic[T]):
    """
    A helper to connect two sets of Writable+Subscribable objects, without connecting the objects within each set. This
    object can be thought of as a bidirectional pipe: All write-events send to the left end of the pipe are forwarded to
    all objects on the right side and vice versa. This can be especially useful to connect a variable to multiple
    addresses of a home automation bus (like a KNX bus) without all mirroring incoming values on one address (e.g. a
    central or feedback datapoint) to the other addresses.

    To connect objects to one side of the pipe, use :meth:`connect_left` resp. :meth:`connect_right`. The additional
    method :meth:`connect` is an alias for `connect_left` to allow using a `TwoWayPipe` object as an argument for
    :meth:`Connectable.connect` itself with the result of connecting the pipe's left end to the object.

    The following example demonstrates, how to connect two interface connectors to a Variable, such that the Variable
    will interact with both of them, without forwarding events/values from one connector to the other::

        shc.Variable(bool)\\
            .connect(TwoWayPipe(bool)
                .connect_right(some_interface.connector(1))
                .connect_right(some_interface.connector(2)))

    :param type_: The `type` of the values to be forwarded. This is used as the `type` of the two pipe-end *connectable*
        objects.
    """
    def __init__(self, type_: Type[T]):
        self.type = type_
        self.left = _PipeEnd(type_)
        self.right = _PipeEnd(type_)
        self.left.other_end = self.right
        self.right.other_end = self.left

    def connect_right(self, *args, **kwargs) -> "TwoWayPipe":
        self.right.connect(*args, **kwargs)
        return self

    def connect_left(self, *args, **kwargs) -> "TwoWayPipe":
        self.left.connect(*args, **kwargs)
        return self

    def connect(self, *args, **kwargs) -> "TwoWayPipe":
        self.left.connect(*args, **kwargs)
        return self


class _PipeEnd(Subscribable[T], Writable[T], Generic[T]):
    def __init__(self, type_: Type[T]):
        self.type = type_
        super().__init__()
        self.other_end: "_PipeEnd" = None  # type: ignore

    async def _write(self, value: T, origin: List[Any]):
        await self.other_end._publish_and_wait(value, origin)


class BreakableSubscription(Subscribable[T], Generic[T]):
    """
    A transparent wrapper for `Subscribable` objects, that allows to dynamically switch forwarding of new values on and
    off.

    A `BreakableSubscription` object can wrap any `Subscribable` object and is `Subscribable` itself to transparently
    re-publish all published values of the wrapped object. However, the re-publishing can be switched on and off through
    a `Readable` boolean control object.

    This can be used to dynamically disable automatic control rules, e.g. control of variables through expressions.
    In the following example, the `fan` is automatically controlled via an expression, based on `room_temperature`, but
    only as long as the `automatic_fan_control` is on. Otherwise, it will not get value updates from that comparison
    expression and thus keep its current value::

        fan = shc.Variable(bool)
        room_temperature = shc.Variable(float)
        automatic_fan_control = shc.Variable(bool)

        fan.connect(shc.misc.BreakableSubscription(room_temperature.EX > 25.0,
                                                   automatic_fan_control))

    If the wrapped object is also `Readable` and the control object is also `Subscribable`, the current value of the
    wrapped object is read and published when the subscription is enabled (the control object changes to `True`).

    If you want to select a value from two or more `Readable` and `Subscribable` objects dynamically, take a look at
    :class:`shc.expressions.IfThenElse` or :class:`shc.expressions.Multiplexer`.

    :param wrapped: The Subscribable object to be wrapped
    :param control: The Readable control object
    """
    _synchronous_publishing = True

    def __init__(self, wrapped: Subscribable[T], control: Readable[bool]):
        self.type = wrapped.type
        super().__init__()
        self.wrapped = wrapped
        self.control = control
        wrapped.trigger(self._new_value, synchronous=True)
        if isinstance(control, Subscribable) and isinstance(wrapped, Readable):
            control.trigger(self._connection_change, synchronous=True)

    async def _new_value(self, value: T, origin: List[Any]) -> None:
        try:
            connected = await self.control.read()
        except UninitializedError:
            # We default to False, if the control variable is not initialized yet
            return
        if connected:
            await self._publish_and_wait(value, origin)

    async def _connection_change(self, connected: bool, origin: List[Any]) -> None:
        if not connected:
            return
        try:
            await self._publish_and_wait(await self.wrapped.read(), origin)  # type: ignore
        except UninitializedError:
            pass


class Hysteresis(Subscribable[bool], Readable[bool]):
    """
    A Hysteresis function wrapper for Subscribable objects of any comparable type.

    The `Hysteresis` object is a `Subscribable` and `Readable` object of boolean type, which wraps any `Subscribable`
    object of a `type` which is comparable with `<`. On any value update of the wrapped object, its current value is
    compared to two fixed bounds. When the value exceeds the upper bound, the `Hysteresis` publishes a `True` value;
    when it falls below the lower bound, the `Hysteresis` publishes a `False` value. As long as the value stays between
    the two bounds, the `Hysteresis` keeps its previous value (and does not publish anything). The output boolean
    value of the `Hysteresis` may be inverted via the `inverted` parameter.

    :param wrapped: The `Subscribable` object to apply the hysteresis on
    :param lower: The lower bound of the hysteresis
    :param upper: The lower bound of the hysteresis
    :param inverted: If True, the boolean output is inverted (False when value is above upper bound, True when value is
        below lower bound)
    :param initial_value: The initial value of the `Hysteresis` object, which is returned on `read()` requests, until
        the first value outside of the bounds is received. Attention: If `inverted` is True, the initial value is
        inverted, too.
    """
    type = bool

    def __init__(self, wrapped: Subscribable[T], lower: T, upper: T, inverted: bool = False,
                 initial_value: bool = False):
        super().__init__()
        wrapped.trigger(self._new_value, synchronous=True)
        self._value = initial_value  #: Current output value (uninverted)
        if not isinstance(lower, wrapped.type) or not isinstance(upper, wrapped.type):
            raise TypeError("'lower' and 'upper' must be instances of the wrapped Subscribable's type, which is {}"
                            .format(wrapped.type.__name__))
        self.lower = lower
        self.upper = upper
        if lower > upper:  # type: ignore  # To defined that T is comparable, we need to use Protocols from Python 3.8
            raise ValueError('Lower bound of hysteresis must be lower than upper bound.')
        self.inverted = inverted

    async def _new_value(self, value: T, origin: List[Any]) -> None:
        old_value = self._value
        if value < self.lower:  # type: ignore
            self._value = False
        elif value > self.upper:  # type: ignore
            self._value = True
        if self._value != old_value:
            await self._publish_and_wait(self._value != self.inverted, origin)

    async def read(self) -> bool:
        return self._value != self.inverted

    @property
    def EX(self) -> ExpressionWrapper[bool]:
        return ExpressionWrapper(self)


class FadeStepAdapter(Subscribable[RangeFloat1], Reading[RangeFloat1]):
    """
    An adapter to connect a Subscribable object which publishes :class:`shc.datatypes.FadeStep` values to a
    :class:`shc.datatypes.RangeFloat1` Variable (or another Readable + Wrtiable object of type `RangeFloat1`), such that
    the FadeSteps are applied to the current value of that object.

    Example usage::

        dim_up_button = shc.web.widgets.StatelessButton(FadeStep(0.1), "up")
        dim_down_button = shc.web.widgets.StatelessButton(FadeStep(-0.1), "down")

        dimmer_value = shc.Variable(RangeFloat1)\
            .connect(FadeStepAdapter(dim_up_button))\
            .connect(FadeStepAdapter(dim_down_button))

    To apply FadeSteps as dynamic ramps of a fixed duration instead of a sudden jump, take a look at
    :class:`shc.timer.FadeStepRamp` (see description in the documentation of :class:`shc.timer.AbstractRamp`).

    :param wrapped: The Subscribable object which shall be wrapped to apply its published FadeStep values to connected
        objects
    """
    type = RangeFloat1
    is_reading_optional = False

    def __init__(self, wrapped: Subscribable[FadeStep]):
        super().__init__()
        if not issubclass(wrapped.type, FadeStep):
            raise TypeError("First Parameter to `FadeStepAdapter` must be a Subscribable object with value type "
                            "`FadeStep`")
        wrapped.trigger(self._update, synchronous=True)

    async def _update(self, value: FadeStep, origin: List[Any]) -> None:
        current_value = await self._from_provider()
        if current_value is None:
            logger.warning("Cannot apply FadeStep, since current value is not available.")
            return
        await self._publish_and_wait(value.apply_to(current_value), origin)


class ConvertSubscription(Subscribable[T], Generic[T]):
    """
    An adapter, wrapping a subscribable object of value type S and converting it to a subscribable object of value type
    T, using the default converter or a given converter function.

    Typically, the following methods should be used instead of this class:

    - Use :meth:`.subscribe() <shc.base.Subscribable.subscribe>`'s ``convert`` parameter
    - Use an :ref:`SHC Expression <expressions>` and its :meth:`.convert() <shc.expressions.ExpressionBuilder.convert>`
      method

    However, they may be situations, where neither of these methods is applicable, e.g. when the subscribable object is
    not readable (so it should not used in an expression) and it is not used with `.subscribe()` or `.connect()`
    directly (e.g. it is passed to another object's constructor).
    """

    def __init__(self, wrapped: Subscribable[S], type_: Type[T], convert: Optional[Callable[[S], T]] = None):
        self.type = type_
        super().__init__()
        if convert is None:
            self.converter = conversion.get_converter(wrapped.type, type_)
        else:
            self.converter = convert
        wrapped.trigger(self.__update, synchronous=True)

    async def __update(self, value: S, origin: List[Any]):
        await self._publish_and_wait(self.converter(value), origin)
