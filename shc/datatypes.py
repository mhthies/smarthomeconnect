# Copyright 2020-2021 Michael Thies <mail@mhthies.de>
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may not use this file except in compliance with
# the License. You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software distributed under the License is distributed on an
# "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the License for the
# specific language governing permissions and limitations under the License.
import abc
import logging
import math
from typing import NamedTuple, Union, overload, Generic

from shc.base import T
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

    @overload
    def __mul__(self, other: "RangeFloat1") -> "RangeFloat1": ...
    @overload
    def __mul__(self, other: Union[int, float]) -> float: ...

    def __mul__(self, other):
        if isinstance(other, RangeFloat1):
            return RangeFloat1(super().__mul__(float(other)))
        else:
            return super().__mul__(other)

    @overload
    def __rmul__(self, other: "RangeFloat1") -> "RangeFloat1": ...
    @overload
    def __rmul__(self, other: Union[int, float]) -> float: ...

    def __rmul__(self, other):
        return self.__mul__(other)


class RangeUInt8(int):
    """
    A range / percentage value, represented as an 8bit integer number from 0 (0%) to 255 (100%).
    """
    @classmethod
    def from_float(cls, value: float) -> "RangeUInt8":
        if not isinstance(value, RangeFloat1):
            value = RangeFloat1(value)
        return RangeUInt8(round(value * 255))

    def as_float(self) -> RangeFloat1:
        return RangeFloat1(int(self) / 255)


class RangeInt0To100(int):
    """
    A range / percentage value, represented as an 8bit integer percent number from 0 (0%) to 100 (100%).
    """
    @classmethod
    def from_float(cls, value: float) -> "RangeInt0To100":
        if not isinstance(value, RangeFloat1):
            value = RangeFloat1(value)
        return RangeInt0To100(round(value * 100))

    def as_float(self) -> RangeFloat1:
        return RangeFloat1(int(self) / 100)


register_converter(RangeFloat1, RangeInt0To100, RangeInt0To100.from_float)
register_converter(RangeUInt8, RangeInt0To100, lambda v: RangeInt0To100.from_float(v.as_float()))
register_converter(RangeUInt8, RangeFloat1, lambda v: v.as_float())
register_converter(RangeInt0To100, RangeFloat1, lambda v: v.as_float())
register_converter(RangeInt0To100, RangeUInt8, lambda v: RangeUInt8.from_float(v.as_float()))
register_converter(RangeFloat1, RangeUInt8, RangeUInt8.from_float)

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


class Balance(float):
    """
    A balance between to extreme positions, e.g. left-right, front-rear, channel 1-channel 2, etc., represented as a
    floating point number between -1.0 and 1.0. Thus, 0.0 represents the "center"/"balanced"/"normal" value.

    -1.0 typically means:
    - left (audio balance)
    - front (surround audio balance)
    - no LFE (surround audio balance)
    """
    pass


register_converter(RangeFloat1, Balance, lambda v: Balance(v * 2 - 1))
register_converter(Balance, RangeFloat1, lambda v: RangeFloat1(v / 2 + 0.5))


class AbstractStep(Generic[T], metaclass=abc.ABCMeta):
    """
    Abstract base class for all difference/step types, that represent a step within an associated range type
    """
    @abc.abstractmethod
    def apply_to(self, value: T) -> T:
        """
        Apply this step to a given value of the associated range type

        :param value: The old value
        :return: The new value, when this step is applied to the old value
        """
        pass


class FadeStep(float, AbstractStep[RangeFloat1]):
    """
    A dimmer or fader change step in the range -1.0 to 1.0. It can be applied to a :class:`RangeFloat1` adding it to the
    step to the current value and clipping the result to the range 0..1.0.

    See :class:`shc.misc.FadeStepAdapter` to do this to SHC.
    """
    pass

    def apply_to(self, value: RangeFloat1) -> RangeFloat1:
        return RangeFloat1(min(1.0, max(0.0, value + self)))


register_converter(float, FadeStep, lambda v: FadeStep(min(1.0, max(-1.0, v))))


class RGBUInt8(NamedTuple):
    """
    A 24bit color in RGB colorspace, composed of three :class:`RangeUInt8` values `red`, `green` and `blue`
    """
    red: RangeUInt8
    green: RangeUInt8
    blue: RangeUInt8

    def dimmed(self, other: Union[RangeUInt8, RangeFloat1, RangeInt0To100]) -> "RGBUInt8":
        if not isinstance(other, RangeFloat1):
            other = get_converter(type(other), RangeFloat1)(other)

        return RGBUInt8(RangeUInt8.from_float(self.red.as_float() * other),
                        RangeUInt8.from_float(self.green.as_float() * other),
                        RangeUInt8.from_float(self.blue.as_float() * other))

    @classmethod
    def from_float(cls, value: "RGBFloat1") -> "RGBUInt8":
        return RGBUInt8(RangeUInt8.from_float(value.red),
                        RangeUInt8.from_float(value.green),
                        RangeUInt8.from_float(value.blue))

    def as_float(self) -> "RGBFloat1":
        return RGBFloat1(self.red.as_float(),
                         self.green.as_float(),
                         self.blue.as_float())


class RGBFloat1(NamedTuple):
    """
    A floating point RGB color, composed of three :class:`RangeFloat1` values `red`, `green` and `blue`
    """
    red: RangeFloat1
    green: RangeFloat1
    blue: RangeFloat1

    def dimmed(self, other: Union[RangeUInt8, RangeFloat1, RangeInt0To100]) -> "RGBFloat1":
        if not isinstance(other, RangeFloat1):
            other = get_converter(type(other), RangeFloat1)(other)

        return RGBFloat1(self.red * other,
                         self.green * other,
                         self.blue * other)


register_converter(RGBUInt8, RGBFloat1, lambda v: v.as_float())
register_converter(RGBFloat1, RGBUInt8, RGBUInt8.from_float)


class HSVFloat1(NamedTuple):
    """
    A floating point color in HSV colorspace, composed of three :class:`RangeFloat1` values `hue`, `saturation` and
    `value`.
    """
    hue: RangeFloat1
    saturation: RangeFloat1
    value: RangeFloat1

    def dimmed(self, other: Union[RangeUInt8, RangeFloat1, RangeInt0To100]) -> "HSVFloat1":
        if not isinstance(other, RangeFloat1):
            other = get_converter(type(other), RangeFloat1)(other)
        return HSVFloat1(self.hue, self.saturation, RangeFloat1(self.value * other))

    @classmethod
    def from_rgb(cls, value: RGBFloat1) -> "HSVFloat1":
        # Taken from Wikipedia: https://de.wikipedia.org/wiki/HSV-Farbraum#Umrechnung_RGB_in_HSV/HSL
        r = value.red
        g = value.green
        b = value.blue
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

    def as_rgb(self) -> "RGBFloat1":
        # Taken from Wikipedia: https://de.wikipedia.org/wiki/HSV-Farbraum#Umrechnung_HSV_in_RGB
        h = self.hue
        s = self.saturation
        v = self.value
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


register_converter(HSVFloat1, RGBFloat1, lambda v: v.as_rgb())
register_converter(RGBFloat1, HSVFloat1, HSVFloat1.from_rgb)
register_converter(HSVFloat1, RGBUInt8, lambda v: RGBUInt8.from_float(v.as_rgb()))
register_converter(RGBUInt8, HSVFloat1, lambda v: HSVFloat1.from_rgb(v.as_float()))


class RGBWUInt8(NamedTuple):
    """
    4-channel RGBW LED color value, composed of a :class:`RGBUInt8` for `rgb` and a :class:`RangeUInt8` for `white`.
    """
    rgb: RGBUInt8
    white: RangeUInt8

    def dimmed(self, other: Union[RangeUInt8, RangeFloat1, RangeInt0To100]) -> "RGBWUInt8":
        if not isinstance(other, RangeFloat1):
            other = get_converter(type(other), RangeFloat1)(other)

        return RGBWUInt8(self.rgb.dimmed(other),
                         RangeUInt8.from_float(self.white.as_float() * other))


register_converter(RGBWUInt8, RGBUInt8, lambda x: x.rgb)
register_converter(RGBUInt8, RGBWUInt8, lambda x: RGBWUInt8(x, RangeUInt8(0)))


class CCTUInt8(NamedTuple):
    """
    A CCT LED brightness value, composed of two :class:`RangeUInt8` values `cold` and `warm`
    """
    cold: RangeUInt8
    warm: RangeUInt8

    def dimmed(self, other: Union[RangeUInt8, RangeFloat1, RangeInt0To100]) -> "CCTUInt8":
        if not isinstance(other, RangeFloat1):
            other = get_converter(type(other), RangeFloat1)(other)

        return CCTUInt8(RangeUInt8.from_float(self.cold.as_float() * other),
                        RangeUInt8.from_float(self.warm.as_float() * other))


class RGBCCTUInt8(NamedTuple):
    """
    5 channel LED color value, composed of a :class:`RGBUInt8` for `rgb` and a :class:`CCTUInt8` for `white`.
    """
    rgb: RGBUInt8
    white: CCTUInt8

    def dimmed(self, other: Union[RangeUInt8, RangeFloat1, RangeInt0To100]) -> "RGBCCTUInt8":
        if not isinstance(other, RangeFloat1):
            other = get_converter(type(other), RangeFloat1)(other)

        return RGBCCTUInt8(self.rgb.dimmed(other), self.white.dimmed(other))


register_converter(CCTUInt8, RangeUInt8, lambda x: RangeUInt8((x.cold + x.warm)/2))
register_converter(RangeUInt8, CCTUInt8, lambda x: CCTUInt8(x, x))
register_converter(RGBCCTUInt8, RGBUInt8, lambda x: x.rgb)
register_converter(RGBUInt8, RGBCCTUInt8, lambda x: RGBCCTUInt8(x, CCTUInt8(RangeUInt8(0), RangeUInt8(0))))
register_converter(RGBCCTUInt8, CCTUInt8, lambda x: x.white)
register_converter(CCTUInt8, RGBCCTUInt8, lambda x: RGBCCTUInt8(RGBUInt8(RangeUInt8(0), RangeUInt8(0), RangeUInt8(0)),
                                                                x))
register_converter(RGBCCTUInt8, RGBWUInt8, lambda x: RGBWUInt8(x.rgb, RangeUInt8((x.white.cold + x.white.warm)/2)))
register_converter(RGBWUInt8, RGBCCTUInt8, lambda x: RGBCCTUInt8(x.rgb, CCTUInt8(x.white, x.white)))
