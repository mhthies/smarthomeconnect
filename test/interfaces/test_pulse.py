import unittest
import ctypes
import ctypes.util

from shc.datatypes import RangeFloat1, Balance

libpulse_available = False
try:
    ctypes.CDLL(ctypes.util.find_library('libpulse') or 'libpulse.so.0')
    libpulse_available = True
except OSError:
    pass

if libpulse_available:
    import shc.interfaces.pulse


@unittest.skipUnless(libpulse_available, "libpulse is not availabe on this system")
class PulseVolumeTests(unittest.TestCase):
    def test_stereo_volume_conversion(self) -> None:
        vol = shc.interfaces.pulse.PulseVolumeRaw([1.0, 0.5], [1, 2])
        vol_split = shc.interfaces.pulse.PulseVolumeBalance.from_channels(vol)
        self.assertEqual(vol.map, vol_split.map)
        self.assertAlmostEqual(-0.5, vol_split.balance)
        self.assertEqual(1.0, vol_split.volume)
        self.assertEqual(0.0, vol_split.fade)
        self.assertEqual(0.0, vol_split.lfe_balance)
        vol2 = vol_split.as_channels()
        self.assertEqual(vol.map, vol2.map)
        for v1, v2 in zip(vol.values, vol2.values):
            self.assertAlmostEqual(v1, v2)

        vol_split2 = vol_split._replace(volume=RangeFloat1(0.3333), balance=Balance(0.25), fade=Balance(0.5))
        vol3 = vol_split2.as_channels()
        self.assertAlmostEqual(0.25, vol3.values[0], places=4)
        self.assertAlmostEqual(0.3333, vol3.values[1], places=4)

    def test_5_1_volume_conversion(self) -> None:
        vol = shc.interfaces.pulse.PulseVolumeRaw([0.1, 0.2, 0.3, 0.4, 0.5, 0.6], [1, 2, 5, 6, 3, 7])
        vol_split = shc.interfaces.pulse.PulseVolumeBalance.from_channels(vol)
        self.assertEqual(vol.map, vol_split.map)
        self.assertAlmostEqual(1-0.2/0.3, vol_split.balance, places=4)
        self.assertAlmostEqual(0.6, vol_split.volume, places=4)

        vol2 = vol_split.as_channels()
        self.assertEqual(vol.map, vol2.map)
        for v1, v2 in zip(vol.values, vol2.values):
            self.assertAlmostEqual(v1, v2, places=4)

        vol_split2 = vol_split._replace(volume=RangeFloat1(0.9))
        vol3 = vol_split2.as_channels()
        self.assertEqual(vol.map, vol2.map)
        for v1, v2 in zip(vol.values, vol3.values):
            self.assertAlmostEqual(v1 * 1.5, v2, places=4)
