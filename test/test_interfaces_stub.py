import unittest


class InterfaceImportTest(unittest.TestCase):
    def test_knx(self):
        import shc.interfaces.knx

    def test_dmx(self):
        import shc.interfaces.dmx

    def test_midi(self):
        import shc.interfaces.midi
