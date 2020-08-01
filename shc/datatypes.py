import logging

from shc.conversion import register_converter

logger = logging.getLogger(__name__)


class RangeFloat1(float):
    def __new__(cls, *args, **kwargs):
        res = int.__new__(cls, *args, **kwargs)
        if not 0.0 <= res <= 1.0:
            raise ValueError("{} is out of the allowed range for type {}".format(res, cls.__name__))
        return res


class RangeUInt8(int):
    pass


class RangeInt0To100(int):
    pass


register_converter(RangeFloat1, RangeInt0To100, lambda v: RangeInt0To100(round(v * 100)))
register_converter(RangeUInt8, RangeInt0To100,
                   lambda v: RangeInt0To100(round(v * 100 / 255)))
register_converter(RangeUInt8, RangeFloat1, lambda v: RangeFloat1(v / 255))
register_converter(RangeInt0To100, RangeFloat1, lambda v: RangeFloat1(v / 100))
register_converter(RangeUInt8, bool, lambda v: bool(v))
register_converter(RangeFloat1, bool, lambda v: bool(v))
register_converter(RangeInt0To100, bool, lambda v: bool(v))
register_converter(bool, RangeUInt8, lambda v: RangeUInt8(255 if v else 0))
register_converter(bool, RangeFloat1, lambda v: RangeFloat1(1.0 if v else 0.0))
register_converter(bool, RangeInt0To100, lambda v: RangeInt0To100(100 if v else 0))


class AngleUInt8(int):
    pass

