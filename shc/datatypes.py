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
import math
from typing import NamedTuple, Union

from shc.conversion import register_converter, get_converter

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

register_converter(float, RangeFloat1, lambda v: RangeFloat1(v))
register_converter(int, RangeUInt8, lambda v: RangeUInt8(v))
register_converter(int, RangeInt0To100, lambda v: RangeInt0To100(v))
register_converter(RangeFloat1, float, lambda v: float(v))
register_converter(RangeUInt8, int, lambda v: int(v))
register_converter(RangeInt0To100, int, lambda v: int(v))

register_converter(RangeUInt8, bool, lambda v: bool(v))
register_converter(RangeFloat1, bool, lambda v: bool(v))
register_converter(RangeInt0To100, bool, lambda v: bool(v))
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

    def __mul__(self, other: Union[RangeUInt8, RangeFloat1, RangeInt0To100, float]) -> "RGBUInt8":
        if isinstance(other, float):
            return RGBUInt8(RangeUInt8(round(self.red * other)),
                            RangeUInt8(round(self.green * other)),
                            RangeUInt8(round(self.blue * other)))
        elif isinstance(other, RangeUInt8):
            return RGBUInt8(RangeUInt8(round(self.red * other / 255)),
                            RangeUInt8(round(self.green * other / 255)),
                            RangeUInt8(round(self.blue * other / 255)))
        elif isinstance(other, RangeInt0To100):
            return RGBUInt8(RangeUInt8(round(self.red * other / 100)),
                            RangeUInt8(round(self.green * other / 100)),
                            RangeUInt8(round(self.blue * other / 100)))
        return NotImplemented

    def __rmul__(self, other: Union[RangeUInt8, RangeFloat1, RangeInt0To100, float]) -> "RGBUInt8":
        return self.__mul__(other)


class RGBFloat1(NamedTuple):
    """
    A floating point RGB color, composed of three :class:`RangeFloat1` values `red`, `green` and `blue`
    """
    red: RangeFloat1
    green: RangeFloat1
    blue: RangeFloat1

    def __mul__(self, other: Union[RangeUInt8, RangeFloat1, RangeInt0To100, float]) -> "RGBFloat1":
        if not isinstance(other, float):
            try:
                other = get_converter(type(other), RangeFloat1)
            except TypeError:
                return NotImplemented
        return RGBFloat1(RangeFloat1(self.red * other),
                         RangeFloat1(self.green * other),
                         RangeFloat1(self.blue * other))

    def __rmul__(self, other: Union[RangeUInt8, RangeFloat1, RangeInt0To100, float]) -> "RGBFloat1":
        return self.__mul__(other)


register_converter(RGBUInt8, RGBFloat1, lambda v: RGBFloat1(RangeFloat1(v.red / 255),
                                                            RangeFloat1(v.green / 255),
                                                            RangeFloat1(v.blue / 255)))
register_converter(RGBFloat1, RGBUInt8, lambda v: RGBUInt8(RangeUInt8(round(v.red * 255)),
                                                           RangeUInt8(round(v.green * 255)),
                                                           RangeUInt8(round(v.blue * 255))))


class HSVFloat1(NamedTuple):
    """
    A floating point color in HSV colorspace, composed of three :class:`RangeFloat1` values `hue`, `saturation` and
    `value`.
    """
    hue: RangeFloat1
    saturation: RangeFloat1
    value: RangeFloat1

    def __mul__(self, other: Union[RangeUInt8, RangeFloat1, RangeInt0To100, float]) -> "HSVFloat1":
        # Multiplication with a scalar (range) only effects the value
        if not isinstance(other, float):
            try:
                other = get_converter(type(other), RangeFloat1)
            except TypeError:
                return NotImplemented
        return HSVFloat1(self.hue, self.saturation, RangeFloat1(self.value * other))

    def __rmul__(self, other: Union[RangeUInt8, RangeFloat1, RangeInt0To100, float]) -> "HSVFloat1":
        return self.__mul__(other)

    @classmethod
    def from_rgb(cls, value: RGBFloat1) -> "HSVFloat1":
        # Taken from Wikipedia: https://de.wikipedia.org/wiki/HSV-Farbraum#Umrechnung_RGB_in_HSV/HSL
        r = value.red; g = value.green; b = value.blue
        max_v = max(r, g, b)
        min_v = min(r, g, b)
        h = (0 if max_v == min_v
             else 1/6 * (g - b) / (max_v - min_v) if max_v == r
             else 2/6 + 1/6 * (b - r) / (max_v - min_v) if max_v == g
             else 4/6 + 1/6 * (r - g) / (max_v - min_v))
        s = 0 if max_v == 0 else (max_v - min_v) / max_v
        v = max_v
        if h < 0:
            h += 1
        return cls(RangeFloat1(h), RangeFloat1(s), RangeFloat1(v))

    def to_rgb(self) -> "RGBFloat1":
        # Taken from Wikipedia: https://de.wikipedia.org/wiki/HSV-Farbraum#Umrechnung_HSV_in_RGB
        h = self.hue; s = self.saturation; v = self.value
        hi = math.floor(h * 6)
        f = h * 6 - hi
        p = v * (1 - s)
        q = v * (1 - s * f)
        t = v * (1 - s * (1 - f))

        r, g, b = ((v, t, p) if hi in (0, 6)
                   else (q, v, p) if hi == 1
                   else (p, v, t) if hi == 2
                   else (p, q, v) if hi == 3
                   else (t, p, v) if hi == 4
                   else (v, p, q))  # if hi == 5
        return RGBFloat1(RangeFloat1(r), RangeFloat1(g), RangeFloat1(b))


register_converter(HSVFloat1, RGBFloat1, lambda v: v.to_rgb())
register_converter(RGBFloat1, HSVFloat1, lambda v: HSVFloat1.from_rgb(v))


def hsv_to_rgbuint8(v: HSVFloat1) -> RGBUInt8:
    rgb = v.to_rgb()
    return RGBUInt8(RangeUInt8(round(rgb.red * 255)),
                    RangeUInt8(round(rgb.green * 255)),
                    RangeUInt8(round(rgb.blue * 255)))


register_converter(HSVFloat1, RGBUInt8, hsv_to_rgbuint8)
register_converter(RGBUInt8, HSVFloat1, lambda v: HSVFloat1.from_rgb(RGBFloat1(RangeFloat1(v.red / 255),
                                                                               RangeFloat1(v.green / 255),
                                                                               RangeFloat1(v.blue / 255))))

