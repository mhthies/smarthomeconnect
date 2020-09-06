import asyncio
import shutil
import time
import unittest
import unittest.mock

from selenium import webdriver
import selenium.webdriver.firefox.options

from shc import web
from ._helper import InterfaceThreadRunner, ExampleReadable


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

    def tearDown(self) -> None:
        self.server_runner.stop()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.driver.close()


class SimpleWebTest(AbstractWebTest):
    def test_basic(self) -> None:
        self.server_runner.start()
        self.driver.get("http://localhost:42080")

    def test_page(self) -> None:
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


class WebWidgetsTest(AbstractWebTest):
    def test_buttons(self) -> None:
        b1 = web.widgets.ToggleButton(label="B1", color='yellow')
        b2 = web.widgets.DisplayButton(label="B2", color='blue')
        b3 = web.widgets.StatelessButton(42, "B3")
        b4 = web.widgets.ValueButton(42, "B4", color="red")
        ExampleReadable(bool, True).connect(b1)
        ExampleReadable(bool, True).connect(b2)
        ExampleReadable(int, 42).connect(b4)

        page = self.server.page('index')
        page.add_item(web.widgets.ButtonGroup("My button group", [b1, b2, b3, b4]))

        with unittest.mock.patch.object(b1, '_publish') as b1_publish,\
                unittest.mock.patch.object(b3, '_publish') as b3_publish,\
                unittest.mock.patch.object(b4, '_publish') as b4_publish:
            self.server_runner.start()
            self.driver.get("http://localhost:42080")

            b1_element = self.driver.find_element_by_xpath('//button[normalize-space(text()) = "B1"]')
            b2_element = self.driver.find_element_by_xpath('//button[normalize-space(text()) = "B2"]')
            b3_element = self.driver.find_element_by_xpath('//button[normalize-space(text()) = "B3"]')
            b4_element = self.driver.find_element_by_xpath('//button[normalize-space(text()) = "B4"]')

            # Check initial states
            self.assertIn('yellow', b1_element.get_attribute('class'))
            self.assertIn('blue', b2_element.get_attribute('class'))
            self.assertIn('red', b4_element.get_attribute('class'))

            # Check state updates
            asyncio.run_coroutine_threadsafe(b1.write(False, [self]), loop=self.server_runner.loop).result()
            time.sleep(0.05)
            self.assertNotIn('yellow', b1_element.get_attribute('class'))
            self.assertIn('blue', b2_element.get_attribute('class'))
            self.assertIn('red', b4_element.get_attribute('class'))

            asyncio.run_coroutine_threadsafe(b2.write(False, [self]), loop=self.server_runner.loop).result()
            asyncio.run_coroutine_threadsafe(b4.write(56, [self]), loop=self.server_runner.loop).result()
            time.sleep(0.05)
            self.assertNotIn('blue', b2_element.get_attribute('class'))
            self.assertNotIn('red', b4_element.get_attribute('class'))

            # Check clicks
            b1_element.click()
            time.sleep(0.05)
            b1_publish.assert_called_once_with(True, unittest.mock.ANY)
            b3_publish.assert_not_called()
            b4_publish.assert_not_called()

            b3_element.click()
            time.sleep(0.05)
            b1_publish.assert_called_once()
            b3_publish.assert_called_once_with(42, unittest.mock.ANY)
            b4_publish.assert_not_called()

            b4_element.click()
            time.sleep(0.05)
            b1_publish.assert_called_once()
            b3_publish.assert_called_once()
            b4_publish.assert_called_once_with(42, unittest.mock.ANY)
