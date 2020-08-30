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

import logging
from typing import NamedTuple

from shc.conversion import register_converter

logger = logging.getLogger(__name__)


class RangeFloat1(float):
    """
    A range / percentage value, represented as a floating point number from 0.0 (0%) to 1.0 (100%).
    """
    def __new__(cls, *args, **kwargs):
        # noinspection PyArgumentList
        res = float.__new__(cls, *args, **kwargs)
        if not 0.0 <= res <= 1.0:
            raise ValueError("{} is out of the allowed range for type {}".format(res, cls.__name__))
        return res


class RangeUInt8(int):
    """
    A range / percentage value, represented as an 8bit integer number from 0 (0%) to 255 (100%).
    """
    pass


class RangeInt0To100(int):
    """
    A range / percentage value, represented as an 8bit integer percent number from 0 (0%) to 100 (100%).
    """
    pass


register_converter(RangeFloat1, RangeInt0To100, lambda v: RangeInt0To100(round(v * 100)))
register_converter(RangeUInt8, RangeInt0To100,
                   lambda v: RangeInt0To100(round(v * 100 / 255)))
register_converter(RangeUInt8, RangeFloat1, lambda v: RangeFloat1(v / 255))
register_converter(RangeInt0To100, RangeFloat1, lambda v: RangeFloat1(v / 100))
register_converter(RangeInt0To100, RangeUInt8, lambda v: RangeUInt8(round(v / 100 * 255)))
register_converter(RangeFloat1, RangeUInt8, lambda v: RangeUInt8(round(v * 255)))
register_converter(RangeUInt8, bool, lambda v: bool(v))
register_converter(int, RangeUInt8, lambda v: RangeUInt8(v))
register_converter(RangeFloat1, bool, lambda v: bool(v))
register_converter(int, RangeFloat1, lambda v: RangeFloat1(v))
register_converter(RangeInt0To100, bool, lambda v: bool(v))
register_converter(int, RangeInt0To100, lambda v: RangeInt0To100(v))
register_converter(bool, RangeUInt8, lambda v: RangeUInt8(255 if v else 0))
register_converter(bool, RangeFloat1, lambda v: RangeFloat1(1.0 if v else 0.0))
register_converter(bool, RangeInt0To100, lambda v: RangeInt0To100(100 if v else 0))


class AngleUInt8(int):
    """
    An angle, encoded as a 8-bit integer, from 0 (0°) to 255 (360°).
    """
    pass


class RGBUInt8(NamedTuple):
    """
    A 24bit color in RGB colorspace, composed of three :class:`RangeUInt8` values `red`, `green` and `blue`
    """
    red: RangeUInt8
    green: RangeUInt8
    blue: RangeUInt8
