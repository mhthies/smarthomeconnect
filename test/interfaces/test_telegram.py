import asyncio
import datetime
import random
import unittest
from typing import Any, Union, Dict, List, Tuple

import aiohttp.web
from aiogram.bot.api import TelegramAPIServer

import shc.interfaces.telegram
from test._helper import async_test, InterfaceThreadRunner, ExampleSubscribable, ExampleReadable

JSON_TYPE_1 = Union[None, bool, int, float, str, Dict[str, Any], List[Any]]
JSON_TYPE = Union[None, bool, int, float, str, Dict[str, JSON_TYPE_1], List[JSON_TYPE_1]]


class TelegramBotTest(unittest.TestCase):
    def setUp(self) -> None:
        self.api_mock = TelegramAPIMock(port=42180,
                                        user_object={'id': 12345689, 'is_bot': True, 'first_name': "The Bot"})
        self.auth_provider = shc.interfaces.telegram.SimpleTelegramAuth({'max': 987654123, 'tim': 987654789})
        self.client_runner = InterfaceThreadRunner(shc.interfaces.telegram.TelegramBot, "123456789:exampleTokenXXX",
                                                   self.auth_provider,
                                                   TelegramAPIServer("http://localhost:42180/{token}/{method}", ""))
        self.client: shc.interfaces.telegram.TelegramBot = self.client_runner.interface

    def tearDown(self) -> None:
        asyncio.get_event_loop().run_until_complete(self.api_mock.stop())
        self.client_runner.stop()

    @async_test
    async def test_subscribe(self) -> None:
        foo_source = ExampleSubscribable(bool)\
            .connect(self.client.on_off_connector("Foo", set(), send_users={'user1'}))

        await self.api_mock.start()
        self.client_runner.start()
        await asyncio.sleep(0.05)
        self.api_mock.reset_mock()

        await self.client_runner.run_coro_async(foo_source.publish(True, [self]))
        await asyncio.sleep(0.05)
        self.api_mock.assert_one_method_called_with("sendMessage", text="Foo is now on")

    @async_test
    async def test_start(self) -> None:
        await self.api_mock.start()
        self.client_runner.start()
        await asyncio.sleep(0.05)
        self.api_mock.reset_mock()

        self.api_mock.add_update_for_bot({'message': {'message_id': 12345789,
                                                      'from': {'id': 987654123, 'is_bot': False, 'first_name:': "Max"},
                                                      'chat': {'id': 987654123, 'type': 'private', 'first_name': "Max"},
                                                      'date': datetime.datetime(2021, 1, 25, 17, 30).timestamp(),
                                                      'text': "/start"}})
        await asyncio.sleep(0.3)
        self.api_mock.assert_one_method_called_with("sendMessage", text="Hi!\nI'm an SHC bot!", chat_id="987654123")

        self.api_mock.add_update_for_bot({'message': {'message_id': 12345790,
                                                      'from': {'id': 987654125, 'is_bot': False, 'first_name:': "Eve"},
                                                      'chat': {'id': 987654125, 'type': 'private', 'first_name': "Eve"},
                                                      'date': datetime.datetime(2021, 1, 25, 17, 35).timestamp(),
                                                      'text': "/start"}})
        await asyncio.sleep(0.3)
        self.api_mock.assert_method_call_count(3)
        self.api_mock.assert_method_called_with("sendMessage", chat_id="987654125")
        self.assertIn("Unauthorized", self.api_mock.method_calls[-1][1]['text'])


class TelegramAPIMock:
    def __init__(self, port: int, user_object: Dict[str, JSON_TYPE]):
        self.port = port
        self.user_object = user_object

        self._app = aiohttp.web.Application()
        self._app.add_routes([
            aiohttp.web.get("/{token}/getUpdates", self._get_updates),
            aiohttp.web.post("/{token}/getUpdates", self._get_updates),
            aiohttp.web.get("/{token}/{method}", self._any_method),
            aiohttp.web.post("/{token}/{method}", self._any_method),
        ])

        self._pending_updates: List[Dict[str, JSON_TYPE]] = []
        self._updates_pending = asyncio.Event()
        self._runner = aiohttp.web.AppRunner(self._app)
        self.method_calls: List[Tuple[str, Dict[str, JSON_TYPE]]] = []
        self._next_update_id = 1

    async def start(self) -> None:
        await self._runner.setup()
        site = aiohttp.web.TCPSite(self._runner, "localhost", self.port)
        await site.start()

    async def stop(self) -> None:
        await self._runner.cleanup()

    def add_update_for_bot(self, update: Dict[str, JSON_TYPE]) -> None:
        update['update_id'] = self._next_update_id
        self._pending_updates.append(update)
        self._next_update_id += 1
        self._updates_pending.set()

    def assert_method_called_with(self, method: str, **kwargs) -> None:
        assert len(self.method_calls) > 0, "No Telegram API method has been called"
        assert method == self.method_calls[-1][0], \
            f"Wrong Telegram API method {self.method_calls[-1][0]} called, expected {method}"
        for arg, val in kwargs.items():
            assert arg in self.method_calls[-1][1], f"Expected {arg} in Telegram API method call parameters"
            assert val == self.method_calls[-1][1][arg],\
                f"Wrong value {self.method_calls[-1][1][arg]} for Parameter {arg}, expected {val}"

    def assert_method_call_count(self, count: int) -> None:
        actual_count = len(self.method_calls)
        assert count == actual_count, f"{actual_count} Telegram API methods called " \
                                      f"({[call[0] for call in self.method_calls]}), expected {count}"

    def assert_one_method_called_with(self, method: str, **kwargs):
        self.assert_method_call_count(1)
        self.assert_method_called_with(method, **kwargs)

    def reset_mock(self) -> None:
        self.method_calls = []

    @staticmethod
    async def __get_args(request: aiohttp.web.Request) -> Dict[str, JSON_TYPE]:
        if request.content_type == "application/json":
            return await request.json()
        elif request.content_type == "application/x-www-form-urlencoded":
            return dict(await request.post())  # type: ignore
        else:
            return dict(request.query)

    async def _get_updates(self, request: aiohttp.web.Request) -> aiohttp.web.Response:
        data = await self.__get_args(request)
        offset = data.get('offset')
        if offset is not None:
            self._pending_updates = [update for update in self._pending_updates
                                     if update['update_id'] > int(offset)]  # type: ignore
        timeout = int(data.get('timeout', 0))
        timeout = min(timeout, 1)  # cap timeout to 1 second for faster stopping of tests
        if not self._pending_updates:
            self._updates_pending.clear()
            try:
                await asyncio.wait_for(self._updates_pending.wait(), timeout)
            except asyncio.TimeoutError:
                pass
        updates = self._pending_updates[:data.get('limit', 100)]  # type: ignore
        return aiohttp.web.json_response({'ok': True, 'result': updates})

    async def _any_method(self, request: aiohttp.web.Request) -> aiohttp.web.Response:
        method = request.match_info['method']
        data = await self.__get_args(request)
        self.method_calls.append((method, data))
        if method == "sendMessage":
            return aiohttp.web.json_response({'ok': True, 'result': self._create_send_message_response(data)})
        if method == "editMessageReplyMarkup":
            return aiohttp.web.json_response({})  # We can't create a correct response, b/c we didn't store the message
        if method == "deleteWebhook":
            return aiohttp.web.json_response({'ok': True, 'result': True})
        else:
            raise aiohttp.web.HTTPNotImplemented(text=f"Method {method} not implemented.")

    def _create_send_message_response(self, data: Dict[str, JSON_TYPE]) -> Dict[str, JSON_TYPE]:
        if 'text' not in data:
            raise aiohttp.web.HTTPNotImplemented(text=f"Only text messages are implemented in the Mock")
        return {
            'message_id': random.randint(0, 2**32),
            'from': self.user_object,
            'date': round(datetime.datetime.now().timestamp()),
            'chat': {'id': data['chat_id'], 'type': "private"},  # TODO: more chat info?
            'text': data['text'],  # We ignore formatting here
            # We also ignore reply to messages (we would need a database of messages to add the relevant info here)
        }
