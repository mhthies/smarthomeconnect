import shutil
import unittest

from selenium import webdriver
import selenium.webdriver.firefox.options

from shc import web
from ._helper import InterfaceThreadRunner


@unittest.skipIf(shutil.which("geckodriver") is None, "Selenium's geckodriver is not available in PATH")
class AbstractWebTest(unittest.TestCase):
    def setUp(self) -> None:
        self.server = web.WebServer("localhost", 42080, 'index')
        self.server_runner = InterfaceThreadRunner(self.server)

    @classmethod
    def setUpClass(cls) -> None:
        opts = selenium.webdriver.firefox.options.Options()
        opts.add_argument("-headless")
        cls.driver = webdriver.Firefox(options=opts)

    def tearDown(self):
        self.server_runner.stop()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.driver.close()


class SimpleWebTest(AbstractWebTest):
    def test_basic(self):
        self.server_runner.start()
        self.driver.get("http://localhost:42080")

    def test_page(self):
        page = self.server.page('index')
        page.add_item(web.widgets.ButtonGroup("My button group", [
            web.widgets.StatelessButton(42, "Foobar")
        ]))
        page.new_segment("Another segment", full_width=True)
        page.add_item(web.widgets.ButtonGroup("Another button group", [
            web.widgets.StatelessButton(42, "Bar")
        ]))

        self.server_runner.start()
        self.driver.get("http://localhost:42080")

        self.assertIn('index', self.driver.page_source)
        self.assertIn('Another segment', self.driver.page_source)
        button = self.driver.find_element_by_xpath('//button[normalize-space(text()) = "Foobar"]')
        self.assertIn("My button group", button.find_element_by_xpath('../..').text)
        button = self.driver.find_element_by_xpath('//button[normalize-space(text()) = "Bar"]')
        self.assertIn("Another button group", button.find_element_by_xpath('../..').text)
