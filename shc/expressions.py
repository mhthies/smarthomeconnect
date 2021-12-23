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
import functools
import math
import operator
import typing
from typing import Type, Generic, Any, Iterable, Callable, Union, Dict, Tuple, List, Optional

from . import conversion
from .base import Readable, Subscribable, T, Connectable, Writable, S, LogicHandler, UninitializedError
from .datatypes import RangeFloat1, RangeUInt8, HSVFloat1, RGBFloat1, RGBUInt8


class ExpressionBuilder(Connectable[T], metaclass=abc.ABCMeta):
    """
    An abstract base class for any object that may be used in SHC expressions.

    This class defines all the overloaded operators, to create *Connectable* :class:`ExpressionHandler` objects when
    being used in a Python expression. For using this class's features with any *Readable* + *Subscribable* object, use
    the :class:`ExpressionWrapper` subclass. Additionally, each :class:`ExpressionHandler` is also an
    `ExpressionBuilder`, allowing to combine Expressions to even larger Expressions.

    Currently, the following operators and builtin functions are supported:

    * ``+`` (add)
    * ``-`` (sub)
    * ``*`` (mul)
    * ``/`` (truediv)
    * ``//`` (floordiv)
    * ``%`` (mod)
    * ``abs()``
    * ``-()`` (neg)
    * ``ceil()``
    * ``floor()``
    * ``round()``
    * ``==`` (eq)
    * ``!=`` (ne)
    * ``<`` (lt)
    * ``<=`` (le)
    * ``>`` (gt)
    * ``>=`` (ge)

    Additionally, the following methods are provided:
    """
    @staticmethod
    def __get_other_type(other: object) -> type:
        if isinstance(other, Readable) and isinstance(other, Subscribable):
            return other.type
        else:
            return type(other)

    def __add__(self, other) -> "BinaryExpressionHandler":
        other_type = self.__get_other_type(other)
        if (self.type, other_type) in TYPES_ADD:
            return BinaryExpressionHandler(TYPES_ADD[(self.type, other_type)], self, other, operator.add)
        else:
            return NotImplemented

    def __radd__(self, other) -> "BinaryExpressionHandler":
        other_type = self.__get_other_type(other)
        if (other_type, self.type) in TYPES_ADD:
            return BinaryExpressionHandler(TYPES_ADD[(other_type, self.type)], other, self, operator.add)
        else:
            return NotImplemented

    def __sub__(self, other) -> "BinaryExpressionHandler":
        other_type = self.__get_other_type(other)
        if (self.type, other_type) in TYPES_SUB:
            return BinaryExpressionHandler(TYPES_SUB[(self.type, other_type)], self, other, operator.sub)
        else:
            return NotImplemented

    def __rsub__(self, other) -> "BinaryExpressionHandler":
        other_type = self.__get_other_type(other)
        if (other_type, self.type) in TYPES_SUB:
            return BinaryExpressionHandler(TYPES_SUB[(other_type, self.type)], other, self, operator.sub)
        else:
            return NotImplemented

    def __mul__(self, other) -> "BinaryExpressionHandler":
        other_type = self.__get_other_type(other)
        if (self.type, other_type) in TYPES_MUL:
            return BinaryExpressionHandler(TYPES_MUL[(self.type, other_type)], self, other, operator.mul)
        else:
            return NotImplemented

    def __rmul__(self, other) -> "BinaryExpressionHandler":
        other_type = self.__get_other_type(other)
        if (other_type, self.type) in TYPES_MUL:
            return BinaryExpressionHandler(TYPES_MUL[(other_type, self.type)], other, self, operator.mul)
        else:
            return NotImplemented

    def __truediv__(self, other) -> "BinaryExpressionHandler":
        other_type = self.__get_other_type(other)
        if (self.type, other_type) in TYPES_TRUEDIV:
            return BinaryExpressionHandler(TYPES_TRUEDIV[(self.type, other_type)], self, other, operator.truediv)
        else:
            return NotImplemented

    def __rtruediv__(self, other) -> "BinaryExpressionHandler":
        other_type = self.__get_other_type(other)
        if (other_type, self.type) in TYPES_TRUEDIV:
            return BinaryExpressionHandler(TYPES_TRUEDIV[(other_type, self.type)], other, self, operator.truediv)
        else:
            return NotImplemented

    def __floordiv__(self, other) -> "BinaryExpressionHandler":
        other_type = self.__get_other_type(other)
        if (self.type, other_type) in TYPES_FLOORDIV:
            return BinaryExpressionHandler(TYPES_FLOORDIV[(self.type, other_type)], self, other, operator.floordiv)
        else:
            return NotImplemented

    def __rfloordiv__(self, other) -> "BinaryExpressionHandler":
        other_type = self.__get_other_type(other)
        if (other_type, self.type) in TYPES_FLOORDIV:
            return BinaryExpressionHandler(TYPES_FLOORDIV[(other_type, self.type)], other, self, operator.floordiv)
        else:
            return NotImplemented

    def __mod__(self, other) -> "BinaryExpressionHandler":
        other_type = self.__get_other_type(other)
        if (self.type, other_type) in TYPES_MOD:
            return BinaryExpressionHandler(TYPES_MOD[(self.type, other_type)], self, other, operator.floordiv)
        else:
            return NotImplemented

    def __rmod__(self, other) -> "BinaryExpressionHandler":
        other_type = self.__get_other_type(other)
        if (other_type, self.type) in TYPES_MOD:
            return BinaryExpressionHandler(TYPES_MOD[(other_type, self.type)], other, self, operator.mod)
        else:
            return NotImplemented

    def __abs__(self) -> "UnaryExpressionHandler":
        if self.type in TYPES_ABS_NEG:
            return UnaryExpressionHandler(TYPES_ABS_NEG[self.type], self, operator.abs)
        else:
            raise TypeError("{} cannot be used with abs()".format(self))

    def __neg__(self) -> "UnaryExpressionHandler":
        if self.type in TYPES_ABS_NEG:
            return UnaryExpressionHandler(TYPES_ABS_NEG[self.type], self, operator.neg)
        else:
            raise TypeError("{} cannot be negated".format(self))

    def __ceil__(self) -> "UnaryExpressionHandler":
        if self.type in TYPES_CEIL_FLOOR_ROUND:
            return UnaryExpressionHandler(TYPES_CEIL_FLOOR_ROUND[self.type], self, math.ceil)
        else:
            raise TypeError("{} cannot be rounded".format(self))

    def __floor__(self) -> "UnaryExpressionHandler":
        if self.type in TYPES_CEIL_FLOOR_ROUND:
            return UnaryExpressionHandler(TYPES_CEIL_FLOOR_ROUND[self.type], self, math.floor)
        else:
            raise TypeError("{} cannot be rounded".format(self))

    def __round__(self) -> "UnaryExpressionHandler":
        if self.type in TYPES_CEIL_FLOOR_ROUND:
            return UnaryExpressionHandler(TYPES_CEIL_FLOOR_ROUND[self.type], self, round)
        else:
            raise TypeError("{} cannot be rounded".format(self))

    def __eq__(self, other) -> "BinaryExpressionHandler[bool]":  # type: ignore
        return BinaryExpressionHandler(bool, self, other, operator.eq)

    def __ne__(self, other) -> "BinaryExpressionHandler[bool]":  # type: ignore
        return BinaryExpressionHandler(bool, self, other, operator.eq)

    def __lt__(self, other) -> "BinaryExpressionHandler[bool]":
        other_type = self.__get_other_type(other)
        if (self.type, other_type) in TYPES_LT_LE_GT_GE:
            return BinaryExpressionHandler(TYPES_LT_LE_GT_GE[(self.type, other_type)], self, other, operator.lt)
        else:
            return NotImplemented

    def __le__(self, other) -> "BinaryExpressionHandler[bool]":
        other_type = self.__get_other_type(other)
        if (self.type, other_type) in TYPES_LT_LE_GT_GE:
            return BinaryExpressionHandler(TYPES_LT_LE_GT_GE[(self.type, other_type)], self, other, operator.le)
        else:
            return NotImplemented

    def __gt__(self, other) -> "BinaryExpressionHandler[bool]":
        other_type = self.__get_other_type(other)
        if (self.type, other_type) in TYPES_LT_LE_GT_GE:
            return BinaryExpressionHandler(TYPES_LT_LE_GT_GE[(self.type, other_type)], self, other, operator.gt)
        else:
            return NotImplemented

    def __ge__(self, other) -> "BinaryExpressionHandler[bool]":
        other_type = self.__get_other_type(other)
        if (self.type, other_type) in TYPES_LT_LE_GT_GE:
            return BinaryExpressionHandler(TYPES_LT_LE_GT_GE[(self.type, other_type)], self, other, operator.ge)
        else:
            return NotImplemented

    def and_(self, other) -> "BinaryCastExpressionHandler":
        return BinaryCastExpressionHandler(bool, self, other, operator.and_)

    def or_(self, other) -> "BinaryCastExpressionHandler":
        return BinaryCastExpressionHandler(bool, self, other, operator.or_)

    def not_(self) -> "UnaryExpressionHandler[bool]":
        return UnaryCastExpressionHandler(bool, self, operator.not_)

    def convert(self, type_: Type[S], converter: Optional[Callable[[T], S]] = None) -> "UnaryExpressionHandler[S]":
        """
        Returns an ExpressionHandler that wraps this object to convert values to another type using a given converter
        function or the :ref:`default converter <datatypes.default_converters>` for those two types.

        Example::

            value = shc.Variable(float)
            which_one = shc.Variable(bool)
            # display_string shall be a str-typed expression object
            display_string = expression.IfThenElse(which_one, value.EX.convert(str), "static string")

        :param type_: The target type to convert new values to. This will also by the `type` attribute of the returned
            ExpressionHandler object, such that it will be used for further
        :param converter: An optional converter function to use instead of the default conversion from this object's
            type to the given target type.
        """
        converter = converter or conversion.get_converter(self.type, type_)
        return UnaryExpressionHandler(type_, self, converter)


class ExpressionWrapper(Readable[T], Subscribable[T], ExpressionBuilder, Generic[T]):
    """
    Wrapper for any *Readable* + *Subscribable* object to equip it with expression-building capabilities, inherited from
    :class:`ExpressionBuilder`
    """
    def __init__(self, wrapped: Subscribable[T]):
        super().__init__()
        self.wrapped = wrapped
        self.type = wrapped.type

    async def read(self) -> T:
        return await self.wrapped.read()  # type: ignore

    def subscribe(self, subscriber: Writable[S], convert: Union[Callable[[T], S], bool] = False):
        return self.wrapped.subscribe(subscriber, convert)

    def trigger(self, target: LogicHandler, synchronous: bool = False) -> LogicHandler:
        return self.wrapped.trigger(target, synchronous=synchronous)


class ExpressionHandler(Readable[T], Subscribable[T], ExpressionBuilder, Generic[T], metaclass=abc.ABCMeta):
    """
    Base class for expression objects, i.e. the result object of an expression built with :class:`ExpressionBuilder`'s
    overloaded operators

    The ExpressionHandler object stores the operator (as a callable) and a reference to each operand. Thereby, it can
    *read* there current values and evaluate the operation/expression at any time with these values. *ExpressionHandler*
    objects are *Readable* (to evaluate the expression's current value on demand) and *Subscribable* (to evaluate and
    publish the expression's new value, when any of the operands is updated).
    """
    def __init__(self, type_: Type[T], operands: Iterable[object]):
        super().__init__()
        self.type = type_
        for operand in operands:
            if isinstance(operand, Subscribable):
                operand.trigger(self.on_change, synchronous=True)

    @abc.abstractmethod
    async def evaluate(self, received_value: Optional[Any], received_from: Optional[Any]) -> T:
        pass

    async def on_change(self, value, origin):
        try:
            await self._publish_and_wait(await self.evaluate(value, origin[-1]), origin)
        except UninitializedError:
            pass

    async def read(self) -> T:
        return await self.evaluate(None, None)

    @staticmethod
    def _wrap_static_value(val: Union[S, Readable[S]]) -> Readable[S]:
        class Wrapper(Readable[S]):
            def __init__(self, v: S):
                self.v = v
                self.type = type(v)

            async def read(self) -> S:
                return self.v

        if isinstance(val, Readable):
            return val
        else:
            return Wrapper(val)


# ################################# #
# Operator-based ExpressionHandlers #
# ################################# #

class BinaryExpressionHandler(ExpressionHandler[T], Generic[T]):
    def __init__(self, type_: Type[T], a, b, operator_: Callable[[Any, Any], T]):
        self.a = self._wrap_static_value(a)
        self.b = self._wrap_static_value(b)
        self.operator = operator_
        super().__init__(type_, (a, b))

    async def evaluate(self, received_value: Optional[Any], received_from: Optional[Any]) -> T:
        return self.operator(received_value if received_from is self.a else await self.a.read(),
                             received_value if received_from is self.b else await self.b.read())

    def __repr__(self) -> str:
        return "{}[{}({}, {})]".format(self.__class__.__name__, self.operator.__name__, repr(self.a), repr(self.b))


class BinaryCastExpressionHandler(BinaryExpressionHandler[T]):
    async def evaluate(self, received_value: Optional[Any], received_from: Optional[Any]) -> T:
        return self.type(await super().evaluate(received_value, received_from))  # type: ignore


class UnaryExpressionHandler(ExpressionHandler[T], Generic[T]):
    def __init__(self, type_: Type[T], a, operator_: Callable[[Any], T]):
        self.a = self._wrap_static_value(a)
        self.operator = operator_
        super().__init__(type_, (a,))

    async def evaluate(self, received_value: Optional[Any], received_from: Optional[Any]) -> T:
        return self.operator(received_value if received_from is self.a else await self.a.read())

    def __repr__(self) -> str:
        return "{}[{}({})]".format(self.__class__.__name__, self.operator.__name__, repr(self.a))


class UnaryCastExpressionHandler(UnaryExpressionHandler[T]):
    async def evaluate(self, received_value: Optional[Any], received_from: Optional[Any]) -> T:
        return self.type(await super().evaluate(received_value, received_from))  # type: ignore


# ############################# #
# Functional ExpressionHandlers #
# ############################# #

class IfThenElse(ExpressionHandler, Generic[T]):
    """
    A :class:`ExpressionHandler` version of the ``x if condition else y`` python syntax

    This class takes three connectable objects or static values: `condition`, `then` and `otherwise`. `condition` must
    be ``bool`` (or a *Connectable* with value type ``bool``), `then` and `otherwise` must be of the same type (reps.
    have the same value type). If the `condition` evaluates to True, this object evaluates to the value of `then`,
    otherwise it evaluates to the value of `otherwise`.

    See also :class:`Multiplexer` for switching between more than two values using an integer control value.
    If you only want enable and disable a single subscription dynamically (e.g. enable/disable the influence of a
    :class:`TimerSwitch <shc.timer.TimerSwitch>` on a :class:`Variable <shc.variables.Variable>`), take a look at
    :class:`shc.misc.BreakableSubscription` instead.
    """
    def __init__(self, condition: Union[bool, Readable[bool]], then: Union[T, Readable[T]],
                 otherwise: Union[T, Readable[T]]):
        super().__init__(then.type if isinstance(then, Connectable) else type(then), (condition, then, otherwise))
        self.condition: Readable[bool] = self._wrap_static_value(condition)
        self.then = self._wrap_static_value(then)
        self.otherwise = self._wrap_static_value(otherwise)

    async def evaluate(self, received_value: Optional[Any], received_from: Optional[Any]) -> T:
        return ((received_value if received_from is self.then else await self.then.read())  # type: ignore
                if (received_value if received_from is self.condition else await self.condition.read())
                else (received_value if received_from is self.otherwise else await self.otherwise.read()))


class Multiplexer(Readable[T], Subscribable[T], ExpressionBuilder[T], Generic[T]):
    """
    A :class:`ExpressionHandler` that behaves as a multiplexer block with an integer control value and any number of
    inputs from that the output value is chosen

    The control object, the first argument of this class, needs to be a Readable (and optionally Subscribable)
    object of int type. All other parameters are considered to be inputs. They must either be static values or
    Readable (and optionally Subscribable) objects. All of them must be of the same value type (resp. be instances of
    exactly that type). This type will also be the type of the Multiplexer itself.

    The control signal selects which of the inputs is passed through and is the provided value of the Multiplexer. E.g.,
    when the control object has the value 0, *reading* from the Multiplexer returns the first input's current value
    (i.e. the value of the object given as the second argument); when the control object has the value 1, the second
    input's value is returned, and so on. If the control value is out of range of the available inputs, *reading*
    returns an :class:`UninitializedError`.

    The Multiplexer publishes a value update whenever an update from the control object or the currently selected
    input is received – as long as they are Subscribable.

    See also :class:`IfThenElse` for simple cases with only two values and a boolean control value.
    If you only want enable and disable a single subscription dynamically (e.g. enable/disable the influence of a
    :class:`TimerSwitch <shc.timer.TimerSwitch>` on a :class:`Variable <shc.variables.Variable>`), take a look at
    :class:`shc.misc.BreakableSubscription` instead.
    """
    _synchronous_publishing = True

    def __init__(self, control: Readable[int], *inputs: Union[T, Readable[T]]):
        super().__init__()
        if not inputs:
            raise ValueError("Multiplexer must have at least one input")
        self.inputs: List[Readable[T]] = [input_ if isinstance(input_, Readable)
                                          else ExpressionHandler._wrap_static_value(input_)
                                          for input_ in inputs]
        self.type: Type[T] = self.inputs[0].type
        for i, input_ in enumerate(self.inputs):
            if input_.type != self.type:
                raise ValueError("Type of input {} ({}) does not match: {} instead of {}"
                                 .format(i, input, input_.type, self.type))
            if isinstance(input_, Subscribable):
                input_.trigger(self._new_value, synchronous=True)

        self.control = control
        if isinstance(control, Subscribable):
            control.trigger(self._index_change, synchronous=True)

    async def read(self) -> T:
        try:
            current_index = await self.control.read()
            current_input = self.inputs[current_index]
        except IndexError:
            # We "ignore" index errors here. They may have been logged by _index_change() before
            raise UninitializedError()
        return await current_input.read()

    async def _new_value(self, value: T, origin: List[Any]) -> None:
        try:
            current_index = await self.control.read()
            current_input = self.inputs[current_index]
        except UninitializedError:
            # We default to False, if the control variable is not initialized yet
            return
        except IndexError:
            # We ignore index errors here. They may have been logged by _index_change() before
            return
        if current_input is origin[-1]:
            await self._publish_and_wait(value, origin)

    async def _index_change(self, current_index: int, origin: List[Any]) -> None:
        try:
            current_input = self.inputs[current_index]
        except IndexError:
            raise ValueError("Index {} is out of range of available inputs of {}".format(current_index, self))
        try:
            await self._publish_and_wait(await current_input.read(), origin)
        except UninitializedError:
            pass


def not_(a) -> Union[bool, UnaryCastExpressionHandler[bool]]:
    """
    Create a :class:`ExpressionHandler` that wraps a *Connectable* or static value and evaluates to ``not x`` for the
    value `x`.

    This is the workaround for Python's limitations on overriding the ``not`` operator.
    """
    if isinstance(a, Readable) and isinstance(a, Subscribable):
        return UnaryCastExpressionHandler(bool, a, operator.not_)
    return not a


def and_(a, b) -> Union[bool, BinaryCastExpressionHandler[bool]]:
    """
    Create a :class:`ExpressionHandler` that wraps two *Connectables* or static values a,b and evaluates to
    ``a and b``.

    This is the workaround for Python's limitations on overriding the ``and`` operator.
    """
    if (not (isinstance(a, Readable) and isinstance(a, Subscribable))
            and not (isinstance(b, Readable) and isinstance(b, Subscribable))):
        return bool(a and b)
    return BinaryCastExpressionHandler(bool, a, b, operator.and_)


def or_(a, b) -> Union[bool, BinaryCastExpressionHandler[bool]]:
    """
    Create a :class:`ExpressionHandler` that wraps two *Connectables* or static values a,b and evaluates to
    ``a or b``.

    This is the workaround for Python's limitations on overriding the ``or`` operator.
    """
    if (not (isinstance(a, Readable) and isinstance(a, Subscribable))
            and not (isinstance(b, Readable) and isinstance(b, Subscribable))):
        return bool(a or b)
    return BinaryCastExpressionHandler(bool, a, b, operator.or_)


# This is just a hack to make type checkers happy with the signature of the __init__ method of return types by
# expression
class ExpressionFunctionHandler(ExpressionHandler[T], Generic[T]):
    def __init__(self, *args: Any) -> None: ...


def expression(func: Callable[..., T]) -> Type[ExpressionFunctionHandler[T]]:
    """
    A decorator to turn any simple function into an :class:`ExpressionHandler` class to be used in SHC expressions

    This way, custom functions can be used in SHC expression in an intuitive way::

        @expression
        def invert(a: float) -> float:
            return 1 / a

        var1 = Variable(float)
        var2 = Variable(float).connect( invert(var1) )

    The decorator turns the function into a class, such that calling it will return an instance of that class instead of
    evaluating the function. The resulting object is a *Readable* and *Subscribable* object, that evaluates the
    original function with the current values of the given arguments on every *read()* and every value update. The
    arguments passed to each instance must either be *Readable* (and optionally *Subscribable*) objects, providing
    values of the expected argument type, or simply static objects of the expected type.

    The wrapped function must be synchronous (not async) and have a type annotation for its return type. The type
    annotation must refer to a runtime type, which can be used for dynamic type checking (i.e. no subscripted generic
    type; use `list` instead of `List[int]` and similar). This return type annotation is also the type of the resulting
    ExpressionHandler objects.

    Currently only positional arguments (no keyword arguments) are supported for the functions.
    """
    class WrapHandler(ExpressionHandler[T]):
        def __init__(self, *args):
            self.args = [self._wrap_static_value(a) for a in args]
            type_ = typing.get_type_hints(func).get('return')
            if not type_:
                raise TypeError("@expression requires the wrapped function to have a return type annotation")
            # Check if the type annotation is valid for runtime type checking
            try:
                isinstance(None, type_)
            except TypeError as e:
                raise TypeError("@expression requires the wrapped function to have a return type annotation") from e

            super().__init__(type_, args)

        async def _get_arg_value(self, arg, received_value, received_from):
            return received_value if received_from is arg else await arg.read()

        async def evaluate(self, received_value: Optional[Any], received_from: Optional[Any]) -> T:
            return func(
                *(await asyncio.gather(
                    *(self._get_arg_value(a, received_value, received_from)
                      for a in self.args))))

        def __repr__(self) -> str:
            return "@expression[{}({})]".format(func.__name__, repr(self.args))

    functools.update_wrapper(WrapHandler, func, updated=())
    return WrapHandler  # type: ignore


# #################### #
# Type Inference Rules #
# #################### #

TYPES_ADD: Dict[Tuple[Type, Type], Type] = {
    (int, int): int,
    (int, float): float,
    (float, int): float,
    (float, float): float,
    (bool, int): int,
    (int, bool): int,
    (bool, float): float,
    (float, bool): float,
    (str, str): str,
    (bytes, bytes): bytes,
    (datetime.date, datetime.timedelta): datetime.date,
    (datetime.datetime, datetime.timedelta): datetime.datetime,
    (datetime.timedelta, datetime.date): datetime.date,
    (datetime.timedelta, datetime.datetime): datetime.datetime,
    (datetime.timedelta, datetime.timedelta): datetime.timedelta,
}
TYPES_SUB: Dict[Tuple[Type, Type], Type] = {
    (int, int): int,
    (int, float): float,
    (float, int): float,
    (float, float): float,
    (bool, int): int,
    (int, bool): int,
    (bool, float): float,
    (float, bool): float,
    (datetime.date, datetime.date): datetime.timedelta,
    (datetime.datetime, datetime.datetime): datetime.timedelta,
    (datetime.date, datetime.timedelta): datetime.date,
    (datetime.datetime, datetime.timedelta): datetime.datetime,
    (datetime.timedelta, datetime.timedelta): datetime.timedelta,
}
TYPES_MUL: Dict[Tuple[Type, Type], Type] = {
    (int, int): int,
    (int, float): float,
    (float, int): float,
    (float, float): float,
    (bool, int): int,
    (int, bool): int,
    (bool, float): float,
    (float, bool): float,
    (str, int): str,
    (int, str): str,
    (bytes, int): bytes,
    (int, bytes): bytes,
    (datetime.timedelta, float): datetime.timedelta,
    (float, datetime.timedelta): datetime.timedelta,
    (datetime.timedelta, int): datetime.timedelta,
    (int, datetime.timedelta): datetime.timedelta,
    (RangeFloat1, float): float,
    (float, RangeFloat1): float,
    (RangeFloat1, int): int,
    (int, RangeFloat1): int,
    (RangeFloat1, RangeFloat1): RangeFloat1
}
TYPES_FLOORDIV: Dict[Tuple[Type, Type], Type] = {
    (int, int): int,
    (float, int): float,
    (int, float): float,
    (float, float): float,
    (bool, int): int,
    (int, bool): int,
    (bool, float): float,
    (float, bool): float,
    (datetime.timedelta, datetime.timedelta): int,
    (datetime.timedelta, int): int,
}
TYPES_TRUEDIV: Dict[Tuple[Type, Type], Type] = {
    (int, int): float,
    (float, int): float,
    (int, float): float,
    (float, float): float,
    (bool, int): int,
    (int, bool): int,
    (bool, float): float,
    (float, bool): float,
    (datetime.timedelta, datetime.timedelta): float,
    (datetime.timedelta, int): datetime.timedelta,
    (datetime.timedelta, float): datetime.timedelta,
}
TYPES_MOD = {
    (int, int): int,
    (float, int): float,
    (int, float): float,
    (float, float): float,
    (datetime.timedelta, datetime.timedelta): datetime.timedelta,
}
TYPES_ABS_NEG: Dict[Type, Type] = {
    int: int,
    float: float,
    datetime.timedelta: datetime.timedelta,
}
TYPES_CEIL_FLOOR_ROUND: Dict[Type, Type] = {
    int: int,
    float: int,
}
TYPES_LT_LE_GT_GE: Dict[Tuple[Type, Type], Type] = {
    (int, int): bool,
    (int, float): bool,
    (float, int): bool,
    (float, float): bool,
    (datetime.datetime, datetime.datetime): bool,
    (datetime.date, datetime.date): bool,
    (datetime.time, datetime.time): bool,
}
