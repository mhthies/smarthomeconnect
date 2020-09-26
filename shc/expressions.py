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
import datetime
import math
import operator
from typing import Type, Generic, Any, Iterable, Callable, Union, Dict, Tuple

from . import conversion
from .base import Readable, Subscribable, T, Connectable, Writable, S, LogicHandler


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
    * ``and``
    * ``or``

    Additionally, the following methods are provided:

    * :meth:`not`: To be used instead of the ``not`` operator (which cannot be overridden)
    * :meth:`convert`: Creates a "type cast" expression, which converts this object's value to the specified value type,
      using the default converter function from :mod:`shc.conversion`.
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

    def __eq__(self, other) -> "BinaryExpressionHandler":  # type: ignore
        return BinaryExpressionHandler(bool, self, other, operator.eq)

    def __ne__(self, other) -> "BinaryExpressionHandler":  # type: ignore
        return BinaryExpressionHandler(bool, self, other, operator.eq)

    def __lt__(self, other) -> "BinaryExpressionHandler":
        other_type = self.__get_other_type(other)
        if (self.type, other_type) in TYPES_LT_LE_GT_GE:
            return BinaryExpressionHandler(TYPES_LT_LE_GT_GE[(self.type, other_type)], self, other, operator.lt)
        else:
            return NotImplemented

    def __le__(self, other) -> "BinaryExpressionHandler":
        other_type = self.__get_other_type(other)
        if (self.type, other_type) in TYPES_LT_LE_GT_GE:
            return BinaryExpressionHandler(TYPES_LT_LE_GT_GE[(self.type, other_type)], self, other, operator.le)
        else:
            return NotImplemented

    def __gt__(self, other) -> "BinaryExpressionHandler":
        other_type = self.__get_other_type(other)
        if (self.type, other_type) in TYPES_LT_LE_GT_GE:
            return BinaryExpressionHandler(TYPES_LT_LE_GT_GE[(self.type, other_type)], self, other, operator.gt)
        else:
            return NotImplemented

    def __ge__(self, other) -> "BinaryExpressionHandler":
        other_type = self.__get_other_type(other)
        if (self.type, other_type) in TYPES_LT_LE_GT_GE:
            return BinaryExpressionHandler(TYPES_LT_LE_GT_GE[(self.type, other_type)], self, other, operator.ge)
        else:
            return NotImplemented

    def __and__(self, other) -> "BinaryCastExpressionHandler":
        return BinaryCastExpressionHandler(bool, self, other, operator.and_)

    def __rand__(self, other) -> "BinaryCastExpressionHandler":
        return BinaryCastExpressionHandler(bool, other, self, operator.and_)

    def __or__(self, other) -> "BinaryCastExpressionHandler":
        return BinaryCastExpressionHandler(bool, self, other, operator.or_)

    def __ror__(self, other) -> "BinaryCastExpressionHandler":
        return BinaryCastExpressionHandler(bool, other, self, operator.or_)

    def not_(self) -> "UnaryExpressionHandler":
        return UnaryCastExpressionHandler(bool, self, operator.not_)

    def convert(self, type_: Type[T]) -> "UnaryExpressionHandler":
        converter = conversion.get_converter(self.type, type_)
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

    def trigger(self, target: LogicHandler) -> LogicHandler:
        return self.wrapped.trigger(target)


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
                operand.trigger(self.on_change)

    @abc.abstractmethod
    async def evaluate(self) -> T:
        pass

    async def on_change(self, _value, origin):
        await self._publish(await self.evaluate(), origin)

    async def read(self) -> T:
        return await self.evaluate()

    @staticmethod
    def _wrap_static_value(val: Union[S, Readable[S]]) -> Readable[S]:
        class Wrapper(Readable[S]):
            def __init__(self, v: S):
                self.v = v

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

    async def evaluate(self) -> T:
        return self.operator(await self.a.read(), await self.b.read())

    def __repr__(self) -> str:
        return "{}[{}({}, {})]".format(self.__class__.__name__, self.operator.__name__, repr(self.a), repr(self.b))


class BinaryCastExpressionHandler(BinaryExpressionHandler[T]):
    async def evaluate(self) -> T:
        return self.type(await super().evaluate())  # type: ignore


class UnaryExpressionHandler(ExpressionHandler[T], Generic[T]):
    def __init__(self, type_: Type[T], a, operator_: Callable[[Any], T]):
        self.a = self._wrap_static_value(a)
        self.operator = operator_
        super().__init__(type_, (a,))

    async def evaluate(self) -> T:
        return self.operator(await self.a.read())

    def __repr__(self) -> str:
        return "{}[{}({})]".format(self.__class__.__name__, self.operator.__name__, repr(self.a))


class UnaryCastExpressionHandler(UnaryExpressionHandler[T]):
    async def evaluate(self) -> T:
        return self.type(await super().evaluate())  # type: ignore


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
    """
    def __init__(self, condition: Union[bool, Readable[bool]], then: Union[T, Readable[T]], otherwise: Union[T, Readable[T]]):
        super().__init__(then.type if isinstance(then, Connectable) else type(then), (condition, then, otherwise))
        self.condition: Readable[bool] = self._wrap_static_value(condition)
        self.then = self._wrap_static_value(then)
        self.otherwise = self._wrap_static_value(otherwise)

    async def evaluate(self) -> T:
        return (await self.then.read()) if (await self.condition.read()) else (await self.otherwise.read())


def not_(a):
    """
    Create a :class:`ExpressionHandler` that wraps a *Connectable* or static value and evaluates to ``not x`` for the
    value `x`.

    This is the workaround for Python's limitations on overriding the ``not`` operator.
    """
    if isinstance(a, Readable) and isinstance(a, Subscribable):
        return UnaryCastExpressionHandler(bool, a, operator.not_)
    return not a


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
    (datetime.timedelta, float): datetime.timedelta,
    (float, datetime.timedelta): datetime.timedelta,
    (datetime.timedelta, int): datetime.timedelta,
    (int, datetime.timedelta): datetime.timedelta,
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
