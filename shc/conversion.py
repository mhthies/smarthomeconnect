from typing import TypeVar, Dict, Tuple, Type, Callable

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
