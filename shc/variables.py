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

import asyncio
import datetime
import logging
import warnings
from typing import Generic, Type, Optional, List, Any, Union, Dict

from . import timer
from .base import Writable, T, Readable, Subscribable, UninitializedError, Reading
from .expressions import ExpressionWrapper

logger = logging.getLogger(__name__)

_ALL_VARIABLES: List["Variable"] = []


async def read_initialize_variables() -> None:
    await asyncio.gather(*(variable._init_from_provider() for variable in _ALL_VARIABLES))


class Variable(Writable[T], Readable[T], Subscribable[T], Reading[T], Generic[T]):
    """
    A Variable object for caching and distributing values of a certain type.

    :param type_: The Variable's value type (used for its ``.type`` attribute, i.e. for the *Connectable* type
        checking mechanism)
    :param name: An optional name of the variable. Used for logging and future displaying purposes.
    :param initial_value: An optional initial value for the Variable. If not provided and no default provider is
        set via :meth:`set_provider`, the Variable is initialized with a None value and any :meth:`read` request
        will raise an :exc:`shc.base.UninitializedError` until the first value update is received.
    """
    _stateful_publishing = True

    def __init__(self, type_: Type[T], name: Optional[str] = None, initial_value: Optional[T] = None):
        self.type = type_
        super().__init__()
        self.name = name
        self._value: Optional[T] = initial_value
        self._variable_fields: Dict[str, "VariableField"] = {}

        # Create VariableFields for each type-annotated field of the type if it is typing.NamedTuple-based.
        if issubclass(type_, tuple) and type_.__annotations__:
            for name, field_type in type_.__annotations__.items():
                variable_field = VariableField(self, name, field_type)
                self._variable_fields[name] = variable_field

        _ALL_VARIABLES.append(self)

    def field(self, name: str) -> "VariableField":
        if not issubclass(self.type, tuple) or not self.type.__annotations__:
            raise TypeError(f"{self.type.__name__} is not a NamedTuple, but Variable.field() only works with "
                            f"NamedTuple-typed Variables.")
        return self._variable_fields[name]

    def __getattr__(self, item: str):
        if item in self._variable_fields:
            warnings.warn("Retrieving VariableFields via dynamic attribute names is deprecated. Use .field() instead.",
                          DeprecationWarning, 2)
            return self._variable_fields[item]
        else:
            raise AttributeError()

    async def _write(self, value: T, origin: List[Any]) -> None:
        old_value = self._value
        self._value = value
        if old_value != value:  # if a single field is different, the full value will also be different
            logger.info("New value %s for Variable %s from %s", value, self, origin[:1])
            self._do_all_publish(old_value, origin)

    def _do_all_publish(self, old_value: Optional[T], origin: List[Any]) -> None:
        logger.debug("Publishing value %s for Variable %s", self._value, self)
        assert self._value is not None
        self._publish(self._value, origin)
        for name, field in self._variable_fields.items():
            field._recursive_publish(getattr(self._value, name),
                                     None if old_value is None else getattr(old_value, name),
                                     origin)

    async def read(self) -> T:
        if self._value is None:
            raise UninitializedError("Variable {} is not initialized yet.".format(repr(self)))
        return self._value

    async def _init_from_provider(self) -> None:
        value = await self._from_provider()
        if value is not None:
            assert self._default_provider is not None
            await self._write(value, [self._default_provider[0]])

    @property
    def EX(self) -> ExpressionWrapper:
        return ExpressionWrapper(self)

    def __repr__(self) -> str:
        if self.name:
            return "<{} \"{}\">".format(self.__class__.__name__, self.name)
        else:
            return super().__repr__()


class VariableField(Writable[T], Readable[T], Subscribable[T], Generic[T]):
    _stateful_publishing = True

    def __init__(self, parent: Union[Variable, "VariableField"], field_name: str, type_: Type[T]):
        self.type = type_
        super().__init__()
        self.parent = parent
        self.variable: Variable = parent.variable if hasattr(parent, 'variable') else parent  # type: ignore
        self.field_name: str = field_name
        self._variable_fields: Dict[str, "VariableField"] = {}

        # Create VariableFields for each type-annotated field of the type if it is typing.NamedTuple-based.
        if issubclass(type_, tuple) and type_.__annotations__:
            for name, field_type in type_.__annotations__.items():
                variable_field = VariableField(self, name, field_type)
                self._variable_fields[name] = variable_field

    def field(self, name: str) -> "VariableField":
        if not issubclass(self.type, tuple) or not self.type.__annotations__:
            raise TypeError(f"{self.type.__name__} is not a NamedTuple, but VariableField.field() only works with "
                            f"NamedTuple-typed VariableFields.")
        return self._variable_fields[name]

    def __getattr__(self, item: str):
        if item in self._variable_fields:
            warnings.warn("Retrieving VariableFields via dynamic attribute names is deprecated. Use .field() instead.",
                          DeprecationWarning, 2)
            return self._variable_fields[item]
        else:
            raise AttributeError()

    def _recursive_publish(self, new_value: T, old_value: T, origin: List[Any]):
        if old_value != new_value:
            self._publish(new_value, origin)
            for name, field in self._variable_fields.items():
                field._recursive_publish(getattr(new_value, name),
                                         None if old_value is None else getattr(old_value, name),
                                         origin)

    @property
    def _value(self):
        return None if self.parent._value is None else getattr(self.parent._value, self.field_name)

    async def _write(self, value: T, origin: List[Any]) -> None:
        if self.parent._value is None:
            raise UninitializedError("Cannot set field {} within Variable {}, since it is uninitialized"
                                     .format(self.field_name, self.variable))
        await self.parent._write(self.parent._value._replace(**{self.field_name: value}), origin + [self])

    async def read(self) -> T:
        if self.parent._value is None:
            raise UninitializedError("Variable {} is not initialized yet.", repr(self.variable))
        return getattr(self.parent._value, self.field_name)

    @property
    def EX(self) -> ExpressionWrapper:
        return ExpressionWrapper(self)


class DelayedVariable(Variable[T], Generic[T]):
    """
    A Variable object, which delays the updates to avoid publishing half-updated values

    This is achieved by delaying the publishing of a newly received value by a configurable amount of time
    (`publish_delay`). If more value updates are received while a previous update publishing is still pending, the
    latest value will be published at the originally scheduled publishing time. There will be no publishing of the
    intermediate values. The next value update received after the publishing will be delayed by the configured delay
    time again, resulting in a maximum update interval of the specified delay time.

    This is similar (but slightly different) to the behaviour of :class:`shc.misc.RateLimitedSubscription`.

    :param type_: The Variable's value type (used for its ``.type`` attribute, i.e. for the *Connectable* type
        checking mechanism)
    :param name: An optional name of the variable. Used for logging and future displaying purposes.
    :param initial_value: An optional initial value for the Variable. If not provided and no default provider is
        set via :meth:`set_provider`, the Variable is initialized with a None value and any :meth:`read` request
        will raise an :exc:`shc.base.UninitializedError` until the first value update is received.
    :param publish_delay: Amount of time to delay the publishing of a new value.
    """
    def __init__(self, type_: Type[T], name: Optional[str] = None, initial_value: Optional[T] = None,
                 publish_delay: datetime.timedelta = datetime.timedelta(seconds=0.25)):
        super().__init__(type_, name, initial_value)
        self._publish_delay = publish_delay
        self._pending_publish_task: Optional[asyncio.Task] = None
        self._latest_origin: List[Any] = []

    async def _write(self, value: T, origin: List[Any]) -> None:
        old_value = self._value
        self._value = value
        self._latest_origin = origin
        if old_value != value:  # if a single field is different, the full value will also be different
            logger.info("New value %s for Variable %s from %s", value, self, origin[:1])
            if not self._pending_publish_task:
                self._pending_publish_task = asyncio.create_task(self._wait_and_publish(old_value))
                timer.timer_supervisor.add_temporary_task(self._pending_publish_task)

    async def _wait_and_publish(self, old_value: Optional[T]) -> None:
        try:
            await asyncio.sleep(self._publish_delay.total_seconds())
        except asyncio.CancelledError:
            pass
        self._do_all_publish(old_value, self._latest_origin)
        self._pending_publish_task = None
