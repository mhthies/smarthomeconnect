import shutil
import unittest

from selenium import webdriver

from shc import web
from ._helper import InterfaceThreadRunner


@unittest.skipIf(shutil.which("geckodriver") is not None, "Selenium's geckodriver is not available in PATH")
class SimpleWebTest(unittest.TestCase):
    def setUp(self) -> None:
        self.server = web.WebServer("localhost", 42080, 'index')
        self.server_runner = InterfaceThreadRunner(self.server)
        self.driver = webdriver.Firefox()

    def tearDown(self):
        self.driver.close()
        self.server_runner.stop()

    def test_basic(self):
        self.server_runner.start()
        self.driver.get("http://localhost:42080")
