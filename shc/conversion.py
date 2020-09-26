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
import enum
import json
from typing import TypeVar, Dict, Tuple, Type, Callable, Any

S = TypeVar('S')
T = TypeVar('T')

_TYPE_CONVERSIONS: Dict[Tuple[Type, Type], Callable[[Any], Any]] = {}
_JSON_CONVERSIONS: Dict[Type, Tuple[Callable[[Any], Any], Callable[[Any], Any]]] = {}


def register_converter(from_type: Type[S], to_type: Type[T], converter: Callable[[S], T]) -> None:
    _TYPE_CONVERSIONS[(from_type, to_type)] = converter


def register_json_conversion(type_: Type[T], to_json: Callable[[T], Any], from_json: Callable[[Any], T]) -> None:
    _JSON_CONVERSIONS[type_] = (to_json, from_json)


def get_converter(from_type: Type[S], to_type: Type[T]) -> Callable[[S], T]:
    """
    Get the default conversion function for converting values from ``from_type`` to ``to_type``.

    :param from_type: The source type
    :param to_type: The target type
    :return: A function, which converts a value of type ``from_type`` to ``to_type``.
    :raises TypeError: If no converter is known for this particular type conversion
    """
    try:
        return _TYPE_CONVERSIONS[(from_type, to_type)]
    except KeyError as e:
        raise TypeError("No converter available to convert {} into {}"
                        .format(from_type.__name__, to_type.__name__)) from e


class SHCJsonEncoder(json.JSONEncoder):
    def default(self, o: Any) -> Any:
        if isinstance(o, enum.Enum):
            return o.value
        if type(o) in _JSON_CONVERSIONS:
            return _JSON_CONVERSIONS[type(o)][0](o)
        return super().default(o)


def from_json(type_: Type[T], value: Any) -> T:
    if issubclass(type_, (bool, int, float, str)):
        return type_(value)  # type: ignore
    if issubclass(type_, enum.Enum):
        return type_(value)  # type: ignore
    if issubclass(type_, tuple) and type_.__annotations__:
        return type_(*(from_json(t, v) for v, (_n, t) in zip(value, type_.__annotations__.items())))  # type: ignore
    try:
        return _JSON_CONVERSIONS[type_][1](value)
    except KeyError as e:
        raise TypeError("No JSON converter available for {}".format(type_.__name__)) from e


register_converter(int, float, lambda v: float(v))
register_converter(float, int, lambda v: round(v))
register_converter(int, str, lambda v: str(v))
register_converter(float, str, lambda v: str(v))
register_converter(str, int, lambda v: int(v))
register_converter(str, int, lambda v: int(v))
register_converter(int, bool, lambda v: bool(v))
register_converter(float, bool, lambda v: bool(v))
register_converter(str, bool, lambda v: bool(v))
register_json_conversion(datetime.date, lambda o: o.isoformat(), lambda v: datetime.date.fromisoformat(v))
register_json_conversion(datetime.datetime, lambda o: o.isoformat(), lambda v: datetime.datetime.fromisoformat(v))
register_json_conversion(datetime.timedelta, lambda o: o.total_seconds(), lambda v: datetime.timedelta(seconds=v))
