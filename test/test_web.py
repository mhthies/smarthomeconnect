import asyncio
import enum
import json
import math
import shutil
import time
import unittest
import unittest.mock
import urllib.request
import urllib.error
import http.client

import aiohttp
from selenium import webdriver
import selenium.webdriver.firefox.options
from selenium.webdriver.common.keys import Keys
from selenium.webdriver import ActionChains

from shc import web
from shc.datatypes import RangeFloat1, RGBUInt8, RangeUInt8
from ._helper import InterfaceThreadRunner, ExampleReadable, AsyncMock, async_test


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
        page = self.server.page('index', 'Home Page')
        page.add_item(web.widgets.ButtonGroup("My button group", [
            web.widgets.StatelessButton(42, "Foobar")
        ]))
        page.new_segment("Another segment", full_width=True)
        page.add_item(web.widgets.ButtonGroup("Another button group", [
            web.widgets.StatelessButton(42, "Bar")
        ]))

        self.server_runner.start()
        self.driver.get("http://localhost:42080")

        self.assertIn('Home Page', self.driver.page_source)
        self.assertIn('Home Page', self.driver.title)
        self.assertIn('Another segment', self.driver.page_source)
        button = self.driver.find_element_by_xpath('//button[normalize-space(text()) = "Foobar"]')
        self.assertIn("My button group", button.find_element_by_xpath('../..').text)
        button = self.driver.find_element_by_xpath('//button[normalize-space(text()) = "Bar"]')
        self.assertIn("Another button group", button.find_element_by_xpath('../..').text)

    def test_main_menu(self) -> None:
        self.server.page('index', menu_entry="Home", menu_icon='home')
        self.server.add_menu_entry('another_page', label="Foo", sub_label="Bar", sub_icon="bars")

        self.server_runner.start()
        self.driver.get("http://localhost:42080")

        # Only search for the (visible) main navigation bar, instead of the hidden sidebare for mobile screens:
        container = self.driver.find_element_by_css_selector('.pusher')

        home_link = container.find_element_by_css_selector('i.home.icon').find_element_by_xpath('..')
        self.assertIn("Home", home_link.text)
        home_link.click()

        container = self.driver.find_element_by_css_selector('.pusher')
        submenu = container.find_element_by_xpath('.//div[contains(text(), "Foo")]')
        submenu_entry = submenu.find_element_by_xpath('.//a[contains(@class, "item")]')
        self.assertFalse(submenu_entry.is_displayed())
        submenu.click()
        self.assertIn("Bar", submenu_entry.text)
        self.assertTrue(submenu_entry.is_displayed())
        self.assertEqual(submenu_entry.get_attribute('href').strip(), "http://localhost:42080/page/another_page/")
        submenu_entry.find_element_by_css_selector('i.bars.icon')


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

        with unittest.mock.patch.object(b1, '_publish', new_callable=AsyncMock) as b1_publish,\
                unittest.mock.patch.object(b3, '_publish', new_callable=AsyncMock) as b3_publish,\
                unittest.mock.patch.object(b4, '_publish', new_callable=AsyncMock) as b4_publish:
            self.server_runner.start()
            self.driver.get("http://localhost:42080")
            time.sleep(0.05)

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

    def test_display(self) -> None:
        page = self.server.page('index')
        text_widget = web.widgets.TextDisplay(int, "{} lux", "Brightness").connect(ExampleReadable(int, 42))
        page.add_item(text_widget)

        self.server_runner.start()
        self.driver.get("http://localhost:42080")
        time.sleep(0.05)
        value_element = self.driver.find_element_by_xpath('//*[normalize-space(text()) = "Brightness"]/..//*[@data-id]')
        self.assertEqual("42 lux", value_element.text.strip())

        asyncio.run_coroutine_threadsafe(text_widget.write(56, [self]), loop=self.server_runner.loop).result()
        time.sleep(0.05)
        self.assertEqual("56 lux", value_element.text.strip())

    def test_input_int(self) -> None:
        page = self.server.page('index')
        input_widget = web.widgets.TextInput(int, "Brightness").connect(ExampleReadable(int, 42))
        page.add_item(input_widget)

        with unittest.mock.patch.object(input_widget, '_publish', new_callable=AsyncMock) as publish_mock:
            self.server_runner.start()
            self.driver.get("http://localhost:42080")
            time.sleep(0.05)
            input_element = self.driver.find_element_by_xpath('//*[normalize-space(text()) = "Brightness"]/..//input')
            self.assertEqual("42", input_element.get_attribute("value"))

            asyncio.run_coroutine_threadsafe(input_widget.write(56, [self]), loop=self.server_runner.loop).result()
            time.sleep(0.05)
            self.assertEqual("56", input_element.get_attribute("value"))

            input_element.send_keys(Keys.SHIFT + Keys.HOME, Keys.BACK_SPACE)
            input_element.send_keys("15", Keys.ENTER)
            time.sleep(0.05)
            self.assertEqual("15", input_element.get_attribute("value"))
            publish_mock.assert_called_once_with(15, unittest.mock.ANY)

            input_element.send_keys(Keys.SHIFT + Keys.HOME, Keys.BACK_SPACE)
            input_element.send_keys("18", Keys.ESCAPE)
            time.sleep(0.05)
            self.assertEqual("15", input_element.get_attribute("value"))
            publish_mock.assert_called_once()

            input_element.send_keys(Keys.SHIFT + Keys.HOME, Keys.BACK_SPACE)
            input_element.send_keys("42", Keys.TAB)
            time.sleep(0.05)
            self.assertEqual("42", input_element.get_attribute("value"))
            publish_mock.assert_called_with(42, unittest.mock.ANY)

    def test_input_string(self) -> None:
        page = self.server.page('index')
        input_widget = web.widgets.TextInput(str, "Message of the Day").connect(ExampleReadable(str, "Hello, World!"))
        page.add_item(input_widget)

        with unittest.mock.patch.object(input_widget, '_publish', new_callable=AsyncMock) as publish_mock:
            self.server_runner.start()
            self.driver.get("http://localhost:42080")
            time.sleep(0.05)
            input_element = self.driver.find_element_by_xpath(
                '//*[normalize-space(text()) = "Message of the Day"]/..//input')
            self.assertEqual("Hello, World!", input_element.get_attribute("value"))

            asyncio.run_coroutine_threadsafe(input_widget.write("Foobar", [self]), loop=self.server_runner.loop).result()
            time.sleep(0.05)
            self.assertEqual("Foobar", input_element.get_attribute("value"))

            input_element.send_keys(Keys.SHIFT + Keys.HOME, Keys.BACK_SPACE)
            input_element.send_keys("Hello, SHC!", Keys.ENTER)
            time.sleep(0.05)
            self.assertEqual("Hello, SHC!", input_element.get_attribute("value"))
            publish_mock.assert_called_once_with("Hello, SHC!", unittest.mock.ANY)

    def test_slider(self) -> None:
        page = self.server.page('index')
        input_widget = web.widgets.Slider("Amount of Foo").connect(ExampleReadable(RangeFloat1, RangeFloat1(0.3)))
        page.add_item(input_widget)

        with unittest.mock.patch.object(input_widget, '_publish', new_callable=AsyncMock) as publish_mock:
            self.server_runner.start()
            self.driver.get("http://localhost:42080")
            time.sleep(0.05)
            container_element = self.driver.find_element_by_xpath(
                '//*[normalize-space(text()) = "Amount of Foo"]/..')
            slider_element = container_element.find_element_by_css_selector('.slider')
            handle_element = slider_element.find_element_by_css_selector(".thumb")

            # Center of handle should be somewhere near 30% of width of
            slider_width = slider_element.rect['width']
            slider_start = slider_element.rect['x']
            handle_center = handle_element.rect['x'] + handle_element.rect['width']/2
            self.assertAlmostEqual(slider_start + 0.3 * slider_width, handle_center, delta=4)  # 4px off is okay

            # Let's move the handle to about 70%
            ActionChains(self.driver).drag_and_drop_by_offset(handle_element, 0.4 * slider_width, 0).perform()

            time.sleep(0.05)
            publish_mock.assert_called_once()
            self.assertAlmostEqual(0.7, publish_mock.call_args[0][0], delta=0.05)  # 5% off is okay

            # Let's move the handle to about 0%
            publish_mock.reset_mock()
            ActionChains(self.driver).drag_and_drop_by_offset(handle_element, -0.8 * slider_width, 0).perform()
            time.sleep(0.05)
            publish_mock.assert_called_once()
            self.assertEqual(0.0, publish_mock.call_args[0][0])

    def test_colorchoser(self) -> None:
        page = self.server.page('index')
        input_widget = web.widgets.ColorChoser()\
            .connect(ExampleReadable(RGBUInt8, RGBUInt8(RangeUInt8(127), RangeUInt8(127), RangeUInt8(127))))
        page.add_item(input_widget)

        with unittest.mock.patch.object(input_widget, '_publish', new_callable=AsyncMock) as publish_mock:
            self.server_runner.start()
            self.driver.get("http://localhost:42080")
            time.sleep(1)
            wheel_element = self.driver.find_element_by_css_selector('.IroWheel')
            wheel_handle_element = wheel_element.find_element_by_css_selector('.IroHandle>circle')
            slider_element = self.driver.find_element_by_css_selector('.IroSlider')
            slider_handle_element = slider_element.find_element_by_css_selector('.IroHandle>circle')

            # The wheel handle should be in the center of the wheel ...
            wheel_rect = wheel_element.rect
            wheel_center = (wheel_rect['x'] + wheel_rect['width']/2, wheel_rect['y'] + wheel_rect['height']/2)
            wheel_handle_rect = wheel_element.rect
            wheel_handle_center = (wheel_handle_rect['x'] + wheel_handle_rect['width']/2,
                                   wheel_handle_rect['y'] + wheel_handle_rect['height']/2)
            self.assertAlmostEqual(wheel_center[0], wheel_handle_center[0], delta=4)  # 4px off is okay
            self.assertAlmostEqual(wheel_center[1], wheel_handle_center[1], delta=4)  # 4px off is okay

            # The slider handle should be at 50%
            slider_rect = slider_element.rect
            slider_handle_rect = slider_handle_element.rect
            self.assertAlmostEqual(slider_rect['x'] + slider_rect['width']/2,
                                   slider_handle_rect['x'] + slider_handle_rect['width']/2, delta=4)  # 4px off is okay

            # Now, lets set a yellow color at 80% brightness
            # Yellow is in the right lower corner of the wheel, at 120° clockwise from the top or -60° (-pi/3 rad)
            # mathematically. (Attention: The y axis is inverted in contrast to the normal mathetmatical orientation)
            ActionChains(self.driver)\
                .move_to_element_with_offset(slider_element, 0.8 * slider_rect['width'], slider_rect['height']/2)\
                .click()\
                .move_to_element(wheel_handle_element)\
                .click_and_hold()\
                .move_to_element_with_offset(
                    wheel_element,
                    wheel_rect['width']/2 + 0.6 * math.cos(-math.pi/3) * wheel_rect['width'],
                    wheel_rect['height']/2 + -0.6 * math.sin(-math.pi/3) * wheel_rect['height'])\
                .release()\
                .perform()

            time.sleep(0.05)
            self.assertEqual(2, publish_mock.call_count)
            latest_color = publish_mock.call_args[0][0]
            self.assertAlmostEqual(204, latest_color.red, delta=13)  # 5% off is okay
            self.assertAlmostEqual(204, latest_color.green, delta=13)
            self.assertAlmostEqual(0, latest_color.blue, delta=6)

    def test_enum_select(self) -> None:
        class ExampleEnum(enum.Enum):
            SOME_VALUE = 0
            SOME_OTHER_VALUE = 1
            YET_ANOTHER_VALUE = 2

        page = self.server.page('index')
        input_widget = web.widgets.EnumSelect(ExampleEnum, "Select the Foo")\
            .connect(ExampleReadable(ExampleEnum, ExampleEnum.SOME_OTHER_VALUE))
        page.add_item(input_widget)

        with unittest.mock.patch.object(input_widget, '_publish', new_callable=AsyncMock) as publish_mock:
            self.server_runner.start()
            self.driver.get("http://localhost:42080")
            time.sleep(0.05)
            container_element = self.driver.find_element_by_xpath(
                '//*[normalize-space(text()) = "Select the Foo"]/..')
            menu_element = container_element.find_element_by_css_selector('.selection.dropdown')

            menu_element.click()
            second_option_element = menu_element\
                .find_element_by_xpath('.//*[normalize-space(text()) = "SOME_OTHER_VALUE"][contains(@class, "item")]')
            self.assertIn("selected", second_option_element.get_attribute('class'))

            # select the third option
            third_option_element = menu_element\
                .find_element_by_xpath('.//*[normalize-space(text()) = "YET_ANOTHER_VALUE"]')
            third_option_element.click()

            time.sleep(0.05)
            menu_element.click()
            self.assertNotIn("selected", second_option_element.get_attribute('class'))
            self.assertIn("selected", third_option_element.get_attribute('class'))
            publish_mock.assert_called_once_with(ExampleEnum.YET_ANOTHER_VALUE, unittest.mock.ANY)


class TestAPI(unittest.TestCase):
    # We use the Python built-in (synchronous) HTTP client (urllib.request / http.client) to test the compatibility with
    # another HTTP implementation and have a more realistic control flow/timing (with different threads instead of one
    # AsyncIO event loop)
    def setUp(self) -> None:
        self.server = web.WebServer("localhost", 42080, 'index')
        self.server_runner = InterfaceThreadRunner(self.server)

    def tearDown(self) -> None:
        self.server_runner.stop()

    def test_rest_get(self) -> None:
        api_object = self.server.api(int, "the_api_object").connect(ExampleReadable(int, 42))
        self.server_runner.start()

        with self.assertRaises(urllib.error.HTTPError) as cm:
            urllib.request.urlopen("http://localhost:42080/api/v1/object/a_non_existing_object")
        self.assertEqual(404, cm.exception.code)

        response: http.client.HTTPResponse = urllib.request.urlopen(
            "http://localhost:42080/api/v1/object/the_api_object")
        self.assertEqual(42, json.loads(response.read()))
        etag1 = response.headers["ETag"]

        # GET request with 'If-None-Match' header with the retrieved ETag should return HTTP 304 NotModified
        request = urllib.request.Request("http://localhost:42080/api/v1/object/the_api_object",
                                         headers={'If-None-Match': etag1})
        with self.assertRaises(urllib.error.HTTPError) as cm:
            urllib.request.urlopen(request)
        self.assertEqual(304, cm.exception.code)
        self.assertEqual(etag1, cm.exception.headers["ETag"])

    def test_rest_get_wait(self) -> None:
        api_object = self.server.api(int, "the_api_object").connect(ExampleReadable(int, 42))
        self.server_runner.start()

        async def scheduled_update(value):
            await asyncio.sleep(0.2)
            await api_object.write(value, self)

        tic = time.time()
        asyncio.run_coroutine_threadsafe(scheduled_update(56), self.server_runner.loop)

        response: http.client.HTTPResponse = urllib.request.urlopen(
            "http://localhost:42080/api/v1/object/the_api_object?wait=0.5")
        toc = time.time()
        self.assertEqual(56, json.loads(response.read()))
        self.assertAlmostEqual(0.2, toc-tic, delta=0.02)

        # When no update happens, we should retrieve a HTTP 304 NotModified after 0.5 s
        tic = time.time()
        with self.assertRaises(urllib.error.HTTPError) as cm:
            urllib.request.urlopen("http://localhost:42080/api/v1/object/the_api_object?wait=0.5")
        toc = time.time()
        self.assertEqual(304, cm.exception.getcode())
        self.assertAlmostEqual(0.5, toc-tic, delta=0.02)

    def test_rest_get_wait_etag(self) -> None:
        api_object = self.server.api(int, "the_api_object").connect(ExampleReadable(int, 42))
        self.server_runner.start()

        # A normal GET request to get the current ETag
        response: http.client.HTTPResponse = urllib.request.urlopen(
            "http://localhost:42080/api/v1/object/the_api_object")
        etag1 = response.headers["ETag"]

        async def scheduled_update(value):
            await asyncio.sleep(0.2)
            await api_object.write(value, self)

        # A GET request with matching ETag and wait parameter. It should wait for the next value
        tic = time.time()
        asyncio.run_coroutine_threadsafe(scheduled_update(56), self.server_runner.loop)

        request = urllib.request.Request("http://localhost:42080/api/v1/object/the_api_object?wait=0.5",
                                         headers={'If-None-Match': etag1})
        response: http.client.HTTPResponse = urllib.request.urlopen(request)
        toc = time.time()
        etag2 = response.headers['ETag']
        self.assertEqual(56, json.loads(response.read()))
        self.assertAlmostEqual(0.2, toc-tic, delta=0.02)
        self.assertNotEqual(etag1, etag2)

        # Now, simulate that we missed that update by sending the same ETag again. It should return immediately with a
        # freshly read value (which is still 42) but the new ETag
        tic = time.time()
        request = urllib.request.Request("http://localhost:42080/api/v1/object/the_api_object?wait=0.5",
                                         headers={'If-None-Match': etag1})
        response: http.client.HTTPResponse = urllib.request.urlopen(request)
        toc = time.time()
        self.assertEqual(42, json.loads(response.read()))
        self.assertEqual(etag2, response.headers['ETag'])
        self.assertAlmostEqual(0, toc-tic, delta=0.02)

    def test_rest_post(self) -> None:
        api_object = self.server.api(int, "the_api_object").connect(ExampleReadable(int, 42))
        self.server_runner.start()

        # POST to non-existing object
        with unittest.mock.patch.object(api_object, '_publish', new_callable=AsyncMock) as publish_mock:
            with self.assertRaises(urllib.error.HTTPError) as cm:
                request = urllib.request.Request("http://localhost:42080/api/v1/object/non_existing_object",
                                                 data=json.dumps(56).encode(), method="POST")
                urllib.request.urlopen(request)
        self.assertEqual(404, cm.exception.code)
        publish_mock.assert_not_called()

        # valid POST
        with unittest.mock.patch.object(api_object, '_publish', new_callable=AsyncMock) as publish_mock:
            request = urllib.request.Request("http://localhost:42080/api/v1/object/the_api_object",
                                             data=json.dumps(56).encode(), method="POST")
            urllib.request.urlopen(request)
        publish_mock.assert_called_once_with(56, unittest.mock.ANY)

        # POST with invalid JSON data → HTTP 400 InvalidRequest
        with self.assertRaises(urllib.error.HTTPError) as cm:
            request = urllib.request.Request("http://localhost:42080/api/v1/object/the_api_object",
                                             data="56,".encode(), method="POST")
            urllib.request.urlopen(request)
        self.assertEqual(400, cm.exception.code)

        # POST with invalid JSON data type → HTTP 422 InvalidRequest
        with self.assertRaises(urllib.error.HTTPError) as cm:
            request = urllib.request.Request("http://localhost:42080/api/v1/object/the_api_object",
                                             data=json.dumps("abc").encode(), method="POST")
            urllib.request.urlopen(request)
        self.assertEqual(422, cm.exception.code)


class WebSocketAPITest(unittest.TestCase):
    def setUp(self) -> None:
        self.server = web.WebServer("localhost", 42080, 'index')
        self.server_runner = InterfaceThreadRunner(self.server)

        self.closing = False
        self.ws_callback = unittest.mock.Mock()

    async def start_websocket(self) -> None:
        async def handle_websocket(ws):
            async for msg in ws:
                if msg.type in (aiohttp.WSMsgType.TEXT, aiohttp.WSMsgType.BINARY):
                    self.ws_callback(msg.data)
                elif msg.type == aiohttp.WSMsgType.CLOSED:
                    if self.closing:
                        break
                    else:
                        raise AssertionError("Websocket closed by server.")
                elif msg.type == aiohttp.WSMsgType.ERROR:
                    raise AssertionError("Websocket error: {}".format(msg.data))

        self.client_session = aiohttp.ClientSession()
        self.ws = await self.client_session.ws_connect('http://localhost:42080/api/v1/ws')
        self.ws_receiver_task = asyncio.create_task(handle_websocket(self.ws))

    def tearDown(self) -> None:
        # Close client
        # websocket
        self.closing = True
        loop = asyncio.get_event_loop()
        loop.create_task(self.ws.close())
        loop.create_task(self.client_session.close())
        pending = asyncio.all_tasks(loop)
        loop.run_until_complete(asyncio.gather(*pending))
        # Await ws receiver task to catch websocket errors
        loop.run_until_complete(self.ws_receiver_task)

        self.server_runner.stop()

    @async_test
    async def test_errors(self) -> None:
        api_object = self.server.api(int, "the_api_object").connect(ExampleReadable(int, 42))
        self.server_runner.start()
        await self.start_websocket()

        # Invalid JSON → 400
        await self.ws.send_str("42,")
        await asyncio.sleep(0.05)
        self.ws_callback.assert_called_once()
        data = json.loads(self.ws_callback.call_args[0][0])
        self.assertEqual(400, data['status'])
        self.assertIn('JSON', data['error'])

        # Missing action → 422
        self.ws_callback.reset_mock()
        await self.ws.send_json({'name': 'the_api_object'})
        await asyncio.sleep(0.05)
        self.ws_callback.assert_called_once()
        data = json.loads(self.ws_callback.call_args[0][0])
        self.assertEqual(422, data['status'])
        self.assertIn('action', data['error'])

        # Missing object name → 422
        self.ws_callback.reset_mock()
        await self.ws.send_json({'action': 'get'})
        await asyncio.sleep(0.05)
        self.ws_callback.assert_called_once()
        data = json.loads(self.ws_callback.call_args[0][0])
        self.assertEqual(422, data['status'])
        self.assertIn('name', data['error'])

        # Invalid action → 422
        self.ws_callback.reset_mock()
        await self.ws.send_json({'action': 'foobar', 'name': 'the_api_object'})
        await asyncio.sleep(0.05)
        self.ws_callback.assert_called_once()
        data = json.loads(self.ws_callback.call_args[0][0])
        self.assertEqual(422, data['status'])
        self.assertIn('action', data['error'])

        # Unknown object → 404
        self.ws_callback.reset_mock()
        await self.ws.send_json({'action': 'get', 'name': 'non_existing_object'})
        await asyncio.sleep(0.05)
        self.ws_callback.assert_called_once()
        data = json.loads(self.ws_callback.call_args[0][0])
        self.assertEqual(404, data['status'])
        self.assertIn('name', data['error'])

    @async_test
    async def test_get(self) -> None:
        api_object = self.server.api(int, "the_api_object").connect(ExampleReadable(int, 42))
        self.server_runner.start()
        await self.start_websocket()

        await self.ws.send_json({'action': 'get', 'name': 'the_api_object'})
        await asyncio.sleep(0.05)
        self.ws_callback.assert_called_once()
        data = json.loads(self.ws_callback.call_args[0][0])
        self.assertEqual('get', data['action'])
        self.assertEqual('the_api_object', data['name'])
        self.assertEqual(200, data['status'])
        self.assertEqual(42, data['value'])

    @async_test
    async def test_post(self) -> None:
        api_object = self.server.api(int, "the_api_object")
        self.server_runner.start()
        await self.start_websocket()

        with unittest.mock.patch.object(api_object, '_publish', new_callable=AsyncMock) as publish_mock:
            await self.ws.send_json({'action': 'post', 'name': 'the_api_object', 'value': 56})
            await asyncio.sleep(0.05)

        publish_mock.assert_called_once_with(56, unittest.mock.ANY)
        self.ws_callback.assert_called_once()
        data = json.loads(self.ws_callback.call_args[0][0])
        self.assertEqual('post', data['action'])
        self.assertEqual('the_api_object', data['name'])
        self.assertEqual(204, data['status'])

    @async_test
    async def test_subscribe(self) -> None:
        api_object = self.server.api(int, "the_api_object").connect(ExampleReadable(int, 42))
        self.server_runner.start()
        await self.start_websocket()

        await self.ws.send_json({'action': 'subscribe', 'name': 'the_api_object'})
        await asyncio.sleep(0.05)

        self.ws_callback.assert_called_once()
        data = json.loads(self.ws_callback.call_args[0][0])
        self.assertEqual('subscribe', data['action'])
        self.assertEqual('the_api_object', data['name'])
        self.assertEqual(42, data['value'])
        self.assertEqual(200, data['status'])

        self.ws_callback.reset_mock()
        asyncio.run_coroutine_threadsafe(api_object.write(56, [self]), self.server_runner.loop)
        await asyncio.sleep(0.05)

        self.ws_callback.assert_called_once()
        data = json.loads(self.ws_callback.call_args[0][0])
        self.assertEqual('the_api_object', data['name'])
        self.assertEqual(56, data['value'])
        self.assertEqual(200, data['status'])
