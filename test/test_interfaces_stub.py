import unittest


class InterfaceImportTest(unittest.TestCase):
    def test_knx(self):
        import shc.interfaces.knx  # noqa: F401

    def test_dmx(self):
        import shc.interfaces.dmx  # noqa: F401

    def test_midi(self):
        import shc.interfaces.midi  # noqa: F401
