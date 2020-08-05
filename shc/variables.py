import asyncio
import logging
from typing import Generic, Type, Optional, get_type_hints, List, Any, Union

from shc.base import Writable, T, Readable, Subscribable, UninitializedError
from shc.expressions import ExpressionWrapper

logger = logging.getLogger(__name__)


class Variable(Writable[T], Readable[T], Subscribable[T], Generic[T]):
    def __init__(self, type_: Type[T], initial_value: Optional[T] = None):
        self.type = type_
        super().__init__()
        self._value: Optional[T] = initial_value
        self._variable_fields: List["VariableField"] = []

        # Create VariableFields for each typeannotated field of the type if it is typing.NamedTuple-based.
        type_hints = get_type_hints(type_)
        if issubclass(type_, tuple) and type_hints:
            for name, field_type in type_hints.items():
                variable_field = VariableField(self, name, field_type)
                self._variable_fields.append(variable_field)
                setattr(self, name, variable_field)

    async def _write(self, value: T, source: List[Any]) -> None:
        old_value = self._value
        logger.info("New value %s for Variable %s", value, self)
        self._value = value
        await asyncio.gather(self._publish(value, source, old_value != value),
                             *(field._recursive_publish(getattr(value, field.field),
                                                        getattr(old_value, field.field), source)
                               for field in self._variable_fields))
        # TODO make recursive

    async def read(self) -> T:
        if self._value is None:
            raise UninitializedError("Variable {} is not initialized yet.", repr(self))
        return self._value

    @property
    def EX(self) -> ExpressionWrapper:
        return ExpressionWrapper(self)


class VariableField(Writable[T], Readable[T], Subscribable[T], Generic[T]):
    def __init__(self, parent: Union[Variable, "VariableField"], field: str, type_: Type[T]):
        self.type = type_
        super().__init__()
        self.parent = parent
        self.variable = parent.variable if hasattr(parent, 'variable') else parent
        self.field = field
        self._variable_fields: List["VariableField"] = []

        # Create VariableFields for each typeannotated field of the type if it is typing.NamedTuple-based.
        type_hints = get_type_hints(type_)
        if issubclass(type_, tuple) and type_hints:
            for name, field_type in type_hints.items():
                variable_field = VariableField(self, name, field_type)
                self._variable_fields.append(variable_field)
                setattr(self, name, variable_field)

    async def _recursive_publish(self, new_value: T, old_value: T, source: List[Any]):
        await asyncio.gather(self._publish(new_value, source, new_value != old_value),
                             *(field._recursive_publish(getattr(new_value, field.field),
                                                        getattr(old_value, field.field), source)
                               for field in self._variable_fields))

    @property
    def _value(self):
        return None if self.parent._value is None else getattr(self.parent._value, self.field)

    async def _write(self, value: T, source: List[Any]) -> None:
        if self.parent._value is None:
            logger.warning("Cannot set field %s within Variable %s, since it is uninitialized", self.field,
                           self.variable)
            return
        await self.parent._write(self.parent._value._replace(**{self.field: value}), source + [self])

    async def read(self) -> T:
        if self.parent._value is None:
            raise UninitializedError("Variable {} is not initialized yet.", repr(self.variable))
        return getattr(self.parent._value, self.field)

    @property
    def EX(self) -> ExpressionWrapper:
        return ExpressionWrapper(self)
