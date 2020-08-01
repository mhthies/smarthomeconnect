from typing import TypeVar, Dict, Tuple, Type, Callable

from . import datatypes

S = TypeVar('S')
T = TypeVar('T')

_TYPE_CONVERSIONS: Dict[Tuple[Type[S], Type[T]], Callable[[S], T]] = {}


def register_converter(from_type: Type[S], to_type: Type[T], converter: Callable[[S], T]) -> None:
    _TYPE_CONVERSIONS[(from_type, to_type)] = converter


def get_converter(from_type: Type[S], to_type: Type[T]) -> Callable[[S], T]:
    try:
        return _TYPE_CONVERSIONS[(from_type, to_type)]
    except KeyError as e:
        raise TypeError("No converter available to convert {} into {}"
                        .format(from_type.__name__, to_type.__name__)) from e


register_converter(int, float, lambda v: float(v))
register_converter(float, int, lambda v: round(v))
register_converter(int, str, lambda v: str(v))
register_converter(float, str, lambda v: str(v))
register_converter(str, int, lambda v: int(v))
register_converter(str, int, lambda v: int(v))
register_converter(int, bool, lambda v: bool(v))
register_converter(float, bool, lambda v: bool(v))
register_converter(str, bool, lambda v: bool(v))
register_converter(datatypes.RangeFloat1, datatypes.RangeInt0To100, lambda v: datatypes.RangeInt0To100(round(v * 100)))
register_converter(datatypes.RangeUInt8, datatypes.RangeInt0To100,
                   lambda v: datatypes.RangeInt0To100(round(v * 100 / 255)))
register_converter(datatypes.RangeUInt8, datatypes.RangeFloat1, lambda v: datatypes.RangeFloat1(v / 255))
register_converter(datatypes.RangeInt0To100, datatypes.RangeFloat1, lambda v: datatypes.RangeFloat1(v / 100))
register_converter(datatypes.RangeUInt8, bool, lambda v: bool(v))
register_converter(datatypes.RangeFloat1, bool, lambda v: bool(v))
register_converter(datatypes.RangeInt0To100, bool, lambda v: bool(v))
register_converter(bool, datatypes.RangeUInt8, lambda v: datatypes.RangeUInt8(255 if v else 0))
register_converter(bool, datatypes.RangeFloat1, lambda v: datatypes.RangeFloat1(1.0 if v else 0.0))
register_converter(bool, datatypes.RangeInt0To100, lambda v: datatypes.RangeInt0To100(100 if v else 0))
