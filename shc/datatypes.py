import logging

logger = logging.getLogger(__name__)


class RangeUInt8(int):
    def __new__(cls, *args, **kwargs):
        res = int.__new__(cls, *args, **kwargs)
        if not 0 <= res <= 2**8-1:
            raise ValueError("{} is out of the allowed range for type {}".format(res, cls.__name__))
        return res


class RangeInt0To100(int):
    def __new__(cls, *args, **kwargs):
        res = int.__new__(cls, *args, **kwargs)
        if not 0 <= res <= 2**8-1:
            raise ValueError("{} is out of the allowed range for type {}".format(res, cls.__name__))
        return res


class RangeFloat1(float):
    def __new__(cls, *args, **kwargs):
        res = int.__new__(cls, *args, **kwargs)
        if not 0.0 <= res <= 1.0:
            raise ValueError("{} is out of the allowed range for type {}".format(res, cls.__name__))
        return res
