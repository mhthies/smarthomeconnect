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
import logging
import warnings
from typing import Generic, Type, Optional, List, Any, Union, Dict, NamedTuple

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

        # Create VariableFields for each typeannotated field of the type if it is typing.NamedTuple-based.
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
            self._publish(value, origin)
            for name, field in self._variable_fields.items():
                field._recursive_publish(getattr(value, name),
                                         None if old_value is None else getattr(old_value, name),
                                         origin)

    async def read(self) -> T:
        if self._value is None:
            raise UninitializedError("Variable {} is not initialized yet.".format(repr(self)))
        return self._value

    async def _init_from_provider(self) -> None:
        value = await self._from_provider()
        if value is not None:
            assert(self._default_provider is not None)
            await self._write(value, [self._default_provider[0]])

    @property
    def EX(self) -> ExpressionWrapper:
        return ExpressionWrapper(self)

    def __repr__(self) -> str:
        if self.name:
            return "<Variable \"{}\">".format(self.name)
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
