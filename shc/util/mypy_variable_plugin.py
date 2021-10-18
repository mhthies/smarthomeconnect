# Copyright 2021 Michael Thies <mail@mhthies.de>
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may not use this file except in compliance with
# the License. You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software distributed under the License is distributed on an
# "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the License for the
# specific language governing permissions and limitations under the License.
"""
A MyPy type checker plugin for some of the dynamic typing features of the SmartHomeConnect framework (SHC)

Currently, it allows to improve the typechecking for VariableField objects which are retrieved via the
:meth:`field() <shc.variables.Variable.field>` method of `Variables` and `VariableFields`.

To enable this plugin, set `plugins = shc.util.mypy_variable_plugin` in the global `[mypy]` section of your MyPy config
file (other Plugins can be added with comma-separation).
"""
from typing import Optional, Callable

from mypy import errorcodes
from mypy.nodes import StrExpr
from mypy.plugin import Plugin, MethodContext
from mypy.types import Instance, Type, TupleType


class SHCVariable(Plugin):
    def get_method_hook(self, fullname: str) -> Optional[Callable[[MethodContext], Type]]:
        if fullname in ("shc.variables.Variable.field", "shc.variables.VariableField.field"):
            return self._shc_variable_field_callback
        return None

    @staticmethod
    def _shc_variable_field_callback(context: MethodContext) -> Type:
        assert isinstance(context.type, Instance)
        assert isinstance(context.default_return_type, Instance)
        if not context.type.args:
            return context.default_return_type
        wrapped_type = context.type.args[0]
        if not isinstance(wrapped_type, TupleType) or not wrapped_type.partial_fallback.type.is_named_tuple:
            context.api.fail(".field() can only be used with NamedTuple-typed SHC Variables or VariableFields",
                             context.context, code=errorcodes.MISC)
            return context.default_return_type
        field_name_expression = context.args[0][0]
        if not isinstance(field_name_expression, StrExpr):
            # If the field name is not specified as a simple string expression, we cannot check the value
            return context.default_return_type
        field_name = field_name_expression.value
        tuple_field_names = wrapped_type.partial_fallback.type.metadata['namedtuple']['fields']
        assert isinstance(tuple_field_names, list)
        try:
            field_index = tuple_field_names.index(field_name)
        except ValueError:
            context.api.fail(f"NamedTuple \"{wrapped_type}\" has no field \"{field_name}\" to create a variable field "
                             f"for",
                             context.context, code=errorcodes.ATTR_DEFINED)
            return context.default_return_type
        field_type = wrapped_type.items[field_index]
        return Instance(context.default_return_type.type, [field_type])


def plugin(version: str):
    return SHCVariable
