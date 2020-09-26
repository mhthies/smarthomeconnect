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

import asyncio
import logging
from typing import Generic, Type, Optional, List, Any, Union

from .base import Writable, T, Readable, Subscribable, UninitializedError, Reading
from .expressions import ExpressionWrapper

logger = logging.getLogger(__name__)

_ALL_VARIABLES: List["Variable"] = []


async def read_initialize_variables() -> None:
    await asyncio.gather(*(variable._init_from_provider() for variable in _ALL_VARIABLES))


class Variable(Writable[T], Readable[T], Subscribable[T], Reading[T], Generic[T]):
    def __init__(self, type_: Type[T], name: Optional[str] = None, initial_value: Optional[T] = None):
        """
        Create/initialize a new Variable object

        :param type_: The Variable's value type (used for its ``.type`` attribute, i.e. for the *Connectable* type
            checking mechanism)
        :param name: An optional name of the variable. Used for logging and future displaying purposes.
        :param initial_value: An optional initial value for the Variable. If not provided and no default provider is
            set via :meth:`set_provider`, the Variable is initialized with a None value and any :meth:`read` request
            will raise an :exc:`shc.base.UninitializedError` until the first value update is received.
        """
        self.type = type_
        super().__init__()
        self.name = name
        self._value: Optional[T] = initial_value
        self._variable_fields: List["VariableField"] = []

        # Create VariableFields for each typeannotated field of the type if it is typing.NamedTuple-based.
        if issubclass(type_, tuple) and type_.__annotations__:
            for name, field_type in type_.__annotations__.items():
                variable_field = VariableField(self, name, field_type)
                self._variable_fields.append(variable_field)
                setattr(self, name, variable_field)

        _ALL_VARIABLES.append(self)

    async def _write(self, value: T, origin: List[Any]) -> None:
        old_value = self._value
        self._value = value
        if old_value != value:  # if a single field is different, the full value will also be different
            tasks = []
            logger.info("New value %s for Variable %s from %s", value, self, origin[:1])
            tasks.append(self._publish(value, origin))
            tasks.extend(field._recursive_publish(getattr(value, field.field),
                                                  None if old_value is None else getattr(old_value, field.field),
                                                  origin)
                         for field in self._variable_fields)
            if tasks:
                await asyncio.gather(*tasks)

    async def read(self) -> T:
        if self._value is None:
            raise UninitializedError("Variable {} is not initialized yet.", repr(self))
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
    def __init__(self, parent: Union[Variable, "VariableField"], field: str, type_: Type[T]):
        self.type = type_
        super().__init__()
        self.parent = parent
        self.variable: Variable = parent.variable if hasattr(parent, 'variable') else parent  # type: ignore
        self.field: str = field
        self._variable_fields: List["VariableField"] = []

        # Create VariableFields for each typeannotated field of the type if it is typing.NamedTuple-based.
        if issubclass(type_, tuple) and type_.__annotations__:
            for name, field_type in type_.__annotations__.items():
                variable_field = VariableField(self, name, field_type)
                self._variable_fields.append(variable_field)
                setattr(self, name, variable_field)

    async def _recursive_publish(self, new_value: T, old_value: T, origin: List[Any]):
        tasks = []
        if old_value != new_value:
            tasks.append(self._publish(new_value, origin))
        tasks.extend(field._recursive_publish(getattr(new_value, field.field),
                                              None if old_value is None else getattr(old_value, field.field), origin)
                     for field in self._variable_fields)
        await asyncio.gather(*tasks)

    @property
    def _value(self):
        return None if self.parent._value is None else getattr(self.parent._value, self.field)

    async def _write(self, value: T, origin: List[Any]) -> None:
        if self.parent._value is None:
            raise UninitializedError("Cannot set field {} within Variable {}, since it is uninitialized"
                                     .format(self.field, self.variable))
        await self.parent._write(self.parent._value._replace(**{self.field: value}), origin + [self])

    async def read(self) -> T:
        if self.parent._value is None:
            raise UninitializedError("Variable {} is not initialized yet.", repr(self.variable))
        return getattr(self.parent._value, self.field)

    @property
    def EX(self) -> ExpressionWrapper:
        return ExpressionWrapper(self)
