
import unittest

from shc import datatypes, conversion


class ConversionTests(unittest.TestCase):
    def test_ranges_1(self) -> None:
        v0 = 0.5
        conv0 = conversion.get_converter(float, datatypes.RangeFloat1)
        r1 = conv0(v0)
        self.assertIsInstance(r1, datatypes.RangeFloat1)

        conv1 = conversion.get_converter(datatypes.RangeFloat1, float)
        v1 = conv1(r1)
        self.assertEqual(0.5, v1)

        conv2 = conversion.get_converter(datatypes.RangeFloat1, datatypes.RangeUInt8)
        r2 = conv2(r1)
        self.assertIsInstance(r2, datatypes.RangeUInt8)
        conv3 = conversion.get_converter(datatypes.RangeUInt8, int)
        v2 = conv3(r2)
        self.assertEqual(128, v2)

        conv4 = conversion.get_converter(datatypes.RangeUInt8, datatypes.RangeInt0To100)
        r3 = conv4(r2)
        self.assertIsInstance(r3, datatypes.RangeInt0To100)
        conv5 = conversion.get_converter(datatypes.RangeInt0To100, int)
        v3 = conv5(r3)
        self.assertEqual(50, v3)

        conv6 = conversion.get_converter(datatypes.RangeInt0To100, datatypes.RangeFloat1)
        r4 = conv6(r3)
        self.assertIsInstance(r4, datatypes.RangeFloat1)
        self.assertAlmostEqual(r1, r4)

    def test_ranges_2(self) -> None:
        # And the other way round!

        v0 = 25
        conv0 = conversion.get_converter(int, datatypes.RangeInt0To100)
        r1 = conv0(v0)
        self.assertIsInstance(r1, datatypes.RangeInt0To100)
        self.assertEqual(datatypes.RangeInt0To100(25), r1)

        conv1 = conversion.get_converter(datatypes.RangeInt0To100, datatypes.RangeUInt8)
        r2 = conv1(r1)
        self.assertIsInstance(r2, datatypes.RangeUInt8)
        self.assertEqual(datatypes.RangeUInt8(64), r2)

        conv2 = conversion.get_converter(datatypes.RangeUInt8, datatypes.RangeFloat1)
        r3 = conv2(r2)
        self.assertIsInstance(r3, datatypes.RangeFloat1)
        self.assertAlmostEqual(0.25, float(r3), delta=0.01)

        conv3 = conversion.get_converter(datatypes.RangeFloat1, datatypes.RangeInt0To100)
        r4 = conv3(r3)
        self.assertEqual(r1, r4)

    def test_ranges_and_bool(self) -> None:
        r1 = datatypes.RangeUInt8(0)
        r2 = datatypes.RangeInt0To100(0)
        r3 = datatypes.RangeFloat1(0)
        r4 = datatypes.RangeUInt8(75)
        r5 = datatypes.RangeInt0To100(17)
        r6 = datatypes.RangeFloat1(0.6)
        self.assertFalse(conversion.get_converter(datatypes.RangeUInt8, bool)(r1))
        self.assertFalse(conversion.get_converter(datatypes.RangeInt0To100, bool)(r2))
        self.assertFalse(conversion.get_converter(datatypes.RangeFloat1, bool)(r3))
        self.assertTrue(conversion.get_converter(datatypes.RangeUInt8, bool)(r4))
        self.assertTrue(conversion.get_converter(datatypes.RangeInt0To100, bool)(r5))
        self.assertTrue(conversion.get_converter(datatypes.RangeFloat1, bool)(r6))

        self.assertEqual(datatypes.RangeUInt8(0), conversion.get_converter(bool, datatypes.RangeUInt8)(False))
        self.assertEqual(datatypes.RangeInt0To100(0), conversion.get_converter(bool, datatypes.RangeInt0To100)(False))
        self.assertEqual(datatypes.RangeFloat1(0), conversion.get_converter(bool, datatypes.RangeFloat1)(False))
        self.assertEqual(datatypes.RangeUInt8(255), conversion.get_converter(bool, datatypes.RangeUInt8)(True))
        self.assertEqual(datatypes.RangeInt0To100(100), conversion.get_converter(bool, datatypes.RangeInt0To100)(True))
        self.assertEqual(datatypes.RangeFloat1(1.0), conversion.get_converter(bool, datatypes.RangeFloat1)(True))

    def test_rgb(self) -> None:
        some_blue = datatypes.RGBFloat1(datatypes.RangeFloat1(.25),
                                        datatypes.RangeFloat1(.5),
                                        datatypes.RangeFloat1(.75))
        some_blue_int = conversion.get_converter(datatypes.RGBFloat1, datatypes.RGBUInt8)(some_blue)
        self.assertEqual(datatypes.RGBUInt8(datatypes.RangeUInt8(64),
                                            datatypes.RangeUInt8(128),
                                            datatypes.RangeUInt8(191)),
                         some_blue_int)

        some_blue_hsv = conversion.get_converter(datatypes.RGBFloat1, datatypes.HSVFloat1)(some_blue)
        self.assertAlmostEqual(210/360, some_blue_hsv.hue, delta=0.01)
        self.assertAlmostEqual(0.6667, some_blue_hsv.saturation, delta=0.01)
        self.assertAlmostEqual(0.75, some_blue_hsv.value, delta=0.01)

        some_blue_hsv2 = conversion.get_converter(datatypes.RGBUInt8, datatypes.HSVFloat1)(some_blue_int)
        self.assertAlmostEqual(210/360, some_blue_hsv2.hue, delta=0.01)
        self.assertAlmostEqual(0.6667, some_blue_hsv2.saturation, delta=0.01)
        self.assertAlmostEqual(0.75, some_blue_hsv2.value, delta=0.01)

        some_yellow_hsv = some_blue_hsv._replace(hue=datatypes.RangeFloat1(45/360))

        some_yellow = conversion.get_converter(datatypes.HSVFloat1, datatypes.RGBFloat1)(some_yellow_hsv)
        self.assertAlmostEqual(0.75, some_yellow.red, delta=0.01)
        self.assertAlmostEqual(0.625, some_yellow.green, delta=0.01)
        self.assertAlmostEqual(0.25, some_yellow.blue, delta=0.01)

        some_yellow_int = conversion.get_converter(datatypes.HSVFloat1, datatypes.RGBUInt8)(some_yellow_hsv)
        self.assertEqual(datatypes.RGBUInt8(datatypes.RangeUInt8(191),
                                            datatypes.RangeUInt8(159),
                                            datatypes.RangeUInt8(64)),
                         some_yellow_int)

        some_yellow2 = conversion.get_converter(datatypes.RGBUInt8, datatypes.RGBFloat1)(some_yellow_int)
        self.assertAlmostEqual(0.75, some_yellow2.red, delta=0.01)
        self.assertAlmostEqual(0.625, some_yellow2.green, delta=0.01)
        self.assertAlmostEqual(0.25, some_yellow2.blue, delta=0.01)

    def test_cct_and_rgbw(self) -> None:
        some_blue_int = datatypes.RGBUInt8(datatypes.RangeUInt8(64),
                                           datatypes.RangeUInt8(128),
                                           datatypes.RangeUInt8(191))
        some_blue_rgbw = conversion.get_converter(datatypes.RGBUInt8, datatypes.RGBWUInt8)(some_blue_int)
        self.assertEqual(datatypes.RGBWUInt8(some_blue_int, datatypes.RangeUInt8(0)),
                         some_blue_rgbw)

        some_blue_with_white = some_blue_rgbw._replace(white=datatypes.RangeUInt8(133))
        self.assertEqual(some_blue_int,
                         conversion.get_converter(datatypes.RGBWUInt8, datatypes.RGBUInt8)(some_blue_with_white))

        some_blue_with_cct = \
            conversion.get_converter(datatypes.RGBWUInt8, datatypes.RGBCCTUInt8)(some_blue_with_white)
        self.assertEqual(datatypes.RGBCCTUInt8(some_blue_int, datatypes.CCTUInt8(datatypes.RangeUInt8(133),
                                                                                 datatypes.RangeUInt8(133))),
                         some_blue_with_cct)

        some_blue_with_white_other_cct = some_blue_with_cct._replace(
            white=datatypes.CCTUInt8(datatypes.RangeUInt8(113), datatypes.RangeUInt8(153)))
        self.assertEqual(some_blue_with_white,
                         conversion.get_converter(datatypes.RGBCCTUInt8, datatypes.RGBWUInt8)
                         (some_blue_with_white_other_cct))

        self.assertEqual(datatypes.CCTUInt8(datatypes.RangeUInt8(113), datatypes.RangeUInt8(153)),
                         conversion.get_converter(datatypes.RGBCCTUInt8, datatypes.CCTUInt8)
                         (some_blue_with_white_other_cct))

        self.assertEqual(some_blue_int,
                         conversion.get_converter(datatypes.RGBCCTUInt8, datatypes.RGBUInt8)
                         (some_blue_with_cct))

        self.assertEqual(datatypes.RangeUInt8(133),
                         conversion.get_converter(datatypes.CCTUInt8, datatypes.RangeUInt8)
                         (datatypes.CCTUInt8(datatypes.RangeUInt8(113), datatypes.RangeUInt8(153))))
        self.assertEqual(datatypes.CCTUInt8(datatypes.RangeUInt8(133), datatypes.RangeUInt8(133)),
                         conversion.get_converter(datatypes.RangeUInt8, datatypes.CCTUInt8)
                         (datatypes.RangeUInt8(133)))


class ColorTests(unittest.TestCase):
    def test_rgb_scaling(self) -> None:
        some_blue = datatypes.RGBFloat1(datatypes.RangeFloat1(.25),
                                        datatypes.RangeFloat1(.5),
                                        datatypes.RangeFloat1(.75))

        some_dim_blue = some_blue.dimmed(datatypes.RangeFloat1(0.5))
        self.assertAlmostEqual(some_dim_blue.red, .125)
        self.assertAlmostEqual(some_dim_blue.green, .25)
        self.assertAlmostEqual(some_dim_blue.blue, .375)

        some_dim_blue2 = some_blue.dimmed(datatypes.RangeInt0To100(50))
        self.assertAlmostEqual(some_dim_blue2.red, .125, delta=0.01)
        self.assertAlmostEqual(some_dim_blue2.green, .25, delta=0.01)
        self.assertAlmostEqual(some_dim_blue2.blue, .375, delta=0.01)

        some_dim_blue3 = some_blue.dimmed(datatypes.RangeUInt8(127))
        self.assertAlmostEqual(some_dim_blue3.red, .125, delta=0.01)
        self.assertAlmostEqual(some_dim_blue3.green, .25, delta=0.01)
        self.assertAlmostEqual(some_dim_blue3.blue, .375, delta=0.01)

        some_blue_hsv = datatypes.HSVFloat1(datatypes.RangeFloat1(210/360),
                                            datatypes.RangeFloat1(.6667),
                                            datatypes.RangeFloat1(.75))

        some_dim_hsv_blue = some_blue_hsv.dimmed(datatypes.RangeFloat1(0.5))
        self.assertAlmostEqual(some_dim_hsv_blue.hue, 210/360)
        self.assertAlmostEqual(some_dim_hsv_blue.saturation, .6667)
        self.assertAlmostEqual(some_dim_hsv_blue.value, .375)

        some_dim_hsv_blue2 = some_blue_hsv.dimmed(datatypes.RangeInt0To100(50))
        self.assertAlmostEqual(some_dim_hsv_blue2.value, .375, delta=0.01)

        some_dim_hsv_blue3 = some_blue_hsv.dimmed(datatypes.RangeUInt8(127))
        self.assertAlmostEqual(some_dim_hsv_blue3.value, .375, delta=0.01)

    def test_rgbw_scaling(self) -> None:
        some_blue_with_white = datatypes.RGBWUInt8(datatypes.RGBUInt8(datatypes.RangeUInt8(64),
                                                                      datatypes.RangeUInt8(128),
                                                                      datatypes.RangeUInt8(191)),
                                                   datatypes.RangeUInt8(133))
        self.assertEqual(datatypes.RGBWUInt8(datatypes.RGBUInt8(datatypes.RangeUInt8(32),
                                                                datatypes.RangeUInt8(64),
                                                                datatypes.RangeUInt8(96)),
                                             datatypes.RangeUInt8(66)),
                         some_blue_with_white.dimmed(datatypes.RangeFloat1(0.5)))

        some_blue_with_cct = datatypes.RGBCCTUInt8(datatypes.RGBUInt8(datatypes.RangeUInt8(64),
                                                                      datatypes.RangeUInt8(128),
                                                                      datatypes.RangeUInt8(191)),
                                                   datatypes.CCTUInt8(datatypes.RangeUInt8(133),
                                                                      datatypes.RangeUInt8(118)))
        self.assertEqual(datatypes.RGBCCTUInt8(datatypes.RGBUInt8(datatypes.RangeUInt8(32),
                                                                  datatypes.RangeUInt8(64),
                                                                  datatypes.RangeUInt8(96)),
                                               datatypes.CCTUInt8(datatypes.RangeUInt8(66),
                                                                  datatypes.RangeUInt8(59))),
                         some_blue_with_cct.dimmed(datatypes.RangeFloat1(0.5)))
