import unittest

from shc import conversion
from shc.datatypes import FadeStep
from shc.interfaces import knx


class KNXDataTypesTest(unittest.TestCase):
    def test_knx_control_dimming_conversion(self) -> None:
        converter1 = conversion.get_converter(knx.KNXControlDimming, FadeStep)
        converter2 = conversion.get_converter(FadeStep, knx.KNXControlDimming)

        result = converter1(knx.KNXControlDimming(True, 2))  # +0.5
        self.assertIsInstance(result, FadeStep)
        self.assertAlmostEqual(0.5, result)

        result = converter1(knx.KNXControlDimming(False, 3))  # -0.25
        self.assertIsInstance(result, FadeStep)
        self.assertAlmostEqual(-0.25, result)

        result2 = converter2(FadeStep(0.25))
        self.assertIsInstance(result2, knx.KNXControlDimming)
        self.assertEqual(knx.KNXControlDimming(True, 3), result2)

        result2 = converter2(FadeStep(-0.10))  # Should be rounded to -0.125
        self.assertIsInstance(result2, knx.KNXControlDimming)
        self.assertEqual(knx.KNXControlDimming(False, 4), result2)
