import asyncio
import datetime
import json
import random
import unittest
import unittest.mock
from typing import Any, Union, Dict, List, Tuple

import aiohttp.web
from aiogram.bot.api import TelegramAPIServer

import shc.interfaces.telegram
from test._helper import async_test, InterfaceThreadRunner, ExampleSubscribable, ExampleReadable, ExampleWritable

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
            .connect(self.client.on_off_connector("Foo", set(), send_users={'max'}))

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

    @async_test
    async def test_write(self) -> None:
        foo = self.client.on_off_connector("Foo", {'max', 'tim'})
        foo_target = ExampleWritable(bool)\
            .connect(foo)
        foobar = self.client.generic_connector(int, "Foobar", lambda x: str(x), lambda x: int(x), {'max', 'alice'})
        foobar_target = ExampleWritable(int)\
            .connect(foobar)

        await self.api_mock.start()
        self.client_runner.start()
        await asyncio.sleep(0.05)
        self.api_mock.reset_mock()

        # Search for 'Foo'
        self.api_mock.add_update_for_bot({'message': {'message_id': 12345789,
                                                      'from': {'id': 987654123, 'is_bot': False, 'first_name:': "Max"},
                                                      'chat': {'id': 987654123, 'type': 'private', 'first_name': "Max"},
                                                      'date': datetime.datetime(2021, 1, 25, 17, 30).timestamp(),
                                                      'text': "Foo"}})
        await asyncio.sleep(0.3)
        self.api_mock.assert_one_method_called_with("sendMessage", chat_id="987654123")
        self.assertListEqual([[{'text': "/s Foo"}], [{'text': "/s Foobar"}]],
                             json.loads(self.api_mock.method_calls[-1][1]['reply_markup'])['keyboard'])
        self.api_mock.reset_mock()

        # Select 'Foobar'
        self.api_mock.add_update_for_bot({'message': {'message_id': 12345790,
                                                      'from': {'id': 987654123, 'is_bot': False, 'first_name:': "Max"},
                                                      'chat': {'id': 987654123, 'type': 'private', 'first_name': "Max"},
                                                      'date': datetime.datetime(2021, 1, 25, 17, 35).timestamp(),
                                                      'text': "/s Foobar"}})

        await asyncio.sleep(0.3)
        self.api_mock.assert_one_method_called_with("sendMessage", chat_id="987654123")
        self.assertNotIn("current", self.api_mock.method_calls[-1][1]['text'])
        reply_markup = json.loads(self.api_mock.method_calls[-1][1]['reply_markup'])
        self.assertListEqual([[{'text': "cancel", 'callback_data': 'cancel'}]], reply_markup['inline_keyboard'])
        self.api_mock.reset_mock()

        # Test invalid value
        self.api_mock.add_update_for_bot({'message': {'message_id': 12345791,
                                                      'from': {'id': 987654123, 'is_bot': False, 'first_name:': "Max"},
                                                      'chat': {'id': 987654123, 'type': 'private', 'first_name': "Max"},
                                                      'date': datetime.datetime(2021, 1, 25, 17, 40).timestamp(),
                                                      'text': "Foo"}})

        await asyncio.sleep(0.3)
        self.api_mock.assert_one_method_called_with("sendMessage", chat_id="987654123")
        self.assertIn("invalid literal", self.api_mock.method_calls[-1][1]['text'])
        self.assertNotIn("reply_markup", self.api_mock.method_calls[-1][1])
        self.api_mock.reset_mock()

        # Concurrent search by Tim
        self.api_mock.add_update_for_bot({'message': {'message_id': 12345792,
                                                      'from': {'id': 987654789, 'is_bot': False, 'first_name:': "Tim"},
                                                      'chat': {'id': 987654789, 'type': 'private', 'first_name': "Tim"},
                                                      'date': datetime.datetime(2021, 1, 25, 17, 40, 20).timestamp(),
                                                      'text': "Foo"}})
        await asyncio.sleep(0.3)
        self.api_mock.assert_one_method_called_with("sendMessage", chat_id="987654789")
        self.assertListEqual([[{'text': "/s Foo"}]],
                             json.loads(self.api_mock.method_calls[-1][1]['reply_markup'])['keyboard'])
        self.api_mock.reset_mock()

        # Max writes value 25
        self.api_mock.add_update_for_bot({'message': {'message_id': 12345793,
                                                      'from': {'id': 987654123, 'is_bot': False, 'first_name:': "Max"},
                                                      'chat': {'id': 987654123, 'type': 'private', 'first_name': "Max"},
                                                      'date': datetime.datetime(2021, 1, 25, 17, 41).timestamp(),
                                                      'text': "25"}})

        await asyncio.sleep(0.3)
        foobar_target._write.assert_called_once_with(25, [foobar])
        self.api_mock.reset_mock()

        # Search again for Foo
        self.api_mock.add_update_for_bot({'message': {'message_id': 12345789,
                                                      'from': {'id': 987654123, 'is_bot': False, 'first_name:': "Max"},
                                                      'chat': {'id': 987654123, 'type': 'private', 'first_name': "Max"},
                                                      'date': datetime.datetime(2021, 1, 25, 17, 42).timestamp(),
                                                      'text': "Foo"}})

        await asyncio.sleep(0.3)
        self.api_mock.assert_one_method_called_with("sendMessage", chat_id="987654123")
        self.assertListEqual([[{'text': "/s Foo"}], [{'text': "/s Foobar"}]],
                             json.loads(self.api_mock.method_calls[-1][1]['reply_markup'])['keyboard'])
        self.api_mock.reset_mock()

        # Two authentication error: Tim is not allowed to select Foobar at all
        self.api_mock.add_update_for_bot({'message': {'message_id': 12345792,
                                                      'from': {'id': 987654789, 'is_bot': False, 'first_name:': "Tim"},
                                                      'chat': {'id': 987654789, 'type': 'private', 'first_name': "Tim"},
                                                      'date': datetime.datetime(2021, 1, 25, 17, 44).timestamp(),
                                                      'text': "/s Foobar"}})
        await asyncio.sleep(0.3)
        self.api_mock.assert_one_method_called_with("sendMessage", chat_id="987654789")
        self.assertIn("authorized", self.api_mock.method_calls[-1][1]['text'])
        self.api_mock.reset_mock()

    @async_test
    async def test_inline_cancel(self) -> None:
        foo = self.client.on_off_connector("Foo", {'max', 'tim'})\
            .connect(ExampleReadable(bool, False))
        foobar = self.client.generic_connector(int, "Foobar", lambda x: str(x), lambda x: int(x), {'max', 'alice'})\
            .connect(ExampleReadable(int, 42))\
            .connect(ExampleWritable(int))

        await self.api_mock.start()
        self.client_runner.start()
        await asyncio.sleep(0.05)
        self.api_mock.reset_mock()

        # Select 'Foobar'
        self.api_mock.add_update_for_bot({'message': {'message_id': 12345790,
                                                      'from': {'id': 987654123, 'is_bot': False, 'first_name:': "Max"},
                                                      'chat': {'id': 987654123, 'type': 'private', 'first_name': "Max"},
                                                      'date': datetime.datetime(2021, 1, 25, 17, 35).timestamp(),
                                                      'text': "/s Foobar"}})

        await asyncio.sleep(0.3)
        self.api_mock.assert_method_called_with("sendMessage", chat_id="987654123")
        reply_markup = json.loads(self.api_mock.method_calls[-1][1]['reply_markup'])
        self.assertListEqual([[{'text': "cancel", 'callback_data': 'cancel'}]], reply_markup['inline_keyboard'])
        message_data = self.api_mock.method_calls[-1][2]
        self.api_mock.reset_mock()

        # Cancel using callback button
        self.api_mock.add_update_for_bot({'callback_query': {
            'id': 12345790,
            'from': {'id': 987654123, 'is_bot': False, 'first_name:': "Max"},
            'message': message_data,
            'chat_instance': "xyz",
            'data': 'cancel',
        }})

        await asyncio.sleep(0.3)
        # We expect to API method calls: Removing the inline keyboard and sending a "Action cancelled" message
        self.api_mock.assert_method_call_count(2)
        self.assertEqual("editMessageReplyMarkup", self.api_mock.method_calls[0][0])
        self.assertEqual(str(message_data['message_id']), self.api_mock.method_calls[0][1]['message_id'])
        self.assertNotIn('reply_markup', self.api_mock.method_calls[0][1])
        self.api_mock.assert_method_called_with("sendMessage", chat_id="987654123")
        self.assertIn("cancelled", self.api_mock.method_calls[1][1]['text'])
        self.api_mock.reset_mock()

        # Search again for Foo
        self.api_mock.add_update_for_bot({'message': {'message_id': 12345789,
                                                      'from': {'id': 987654123, 'is_bot': False, 'first_name:': "Max"},
                                                      'chat': {'id': 987654123, 'type': 'private', 'first_name': "Max"},
                                                      'date': datetime.datetime(2021, 1, 25, 17, 42).timestamp(),
                                                      'text': "Foo"}})

        await asyncio.sleep(0.3)
        self.api_mock.assert_one_method_called_with("sendMessage", chat_id="987654123")
        self.assertNotIn("invalid", self.api_mock.method_calls[-1][1]['text'])
        self.assertListEqual([[{'text': "/s Foo"}], [{'text': "/s Foobar"}]],
                             json.loads(self.api_mock.method_calls[-1][1]['reply_markup'])['keyboard'])

    @async_test
    async def test_auth_errors(self) -> None:
        foo = self.client.on_off_connector("Foo", {'max', 'tim'})

        await self.api_mock.start()
        self.client_runner.start()
        await asyncio.sleep(0.05)
        self.api_mock.reset_mock()

        # Eve is not allowed to select Foo
        self.api_mock.add_update_for_bot({'message': {'message_id': 12345790,
                                                      'from': {'id': 987654125, 'is_bot': False, 'first_name:': "Eve"},
                                                      'chat': {'id': 987654125, 'type': 'private', 'first_name': "Eve"},
                                                      'date': datetime.datetime(2021, 1, 25, 17, 43).timestamp(),
                                                      'text': "/s Foo"}})
        await asyncio.sleep(0.3)
        self.api_mock.assert_method_called_with("sendMessage", chat_id="987654125")
        foo_error_message = self.api_mock.method_calls[-1][1]['text']
        self.assertIn("authorized", foo_error_message)
        self.api_mock.reset_mock()

        # Eve is not allowed to select a non-existent object.
        # The message should be the same as for the existant object, so we don't leak information about existant objects
        self.api_mock.add_update_for_bot({'message': {'message_id': 12345791,
                                                      'from': {'id': 987654125, 'is_bot': False, 'first_name:': "Eve"},
                                                      'chat': {'id': 987654125, 'type': 'private', 'first_name': "Eve"},
                                                      'date': datetime.datetime(2021, 1, 25, 17, 43, 1).timestamp(),
                                                      'text': "/s Bar"}})
        await asyncio.sleep(0.3)
        self.api_mock.assert_method_called_with("sendMessage", chat_id="987654125")
        self.assertEqual(foo_error_message, self.api_mock.method_calls[-1][1]['text'])
        self.api_mock.reset_mock()

        # Eve is not allowed to search anything
        self.api_mock.add_update_for_bot({'message': {'message_id': 12345791,
                                                      'from': {'id': 987654125, 'is_bot': False, 'first_name:': "Eve"},
                                                      'chat': {'id': 987654125, 'type': 'private', 'first_name': "Eve"},
                                                      'date': datetime.datetime(2021, 1, 25, 17, 43, 1).timestamp(),
                                                      'text': "Fo"}})
        await asyncio.sleep(0.3)
        self.api_mock.assert_method_called_with("sendMessage", chat_id="987654125")
        self.assertIn("authorized", self.api_mock.method_calls[-1][1]['text'])
        self.assertNotIn("Foo", self.api_mock.method_calls[-1][1]['text'])
        self.api_mock.reset_mock()

    @async_test
    async def test_write_on_off(self) -> None:
        foo = self.client.on_off_connector("Foo", {'max', 'tim'})
        foo_target = ExampleWritable(bool)\
            .connect(foo)

        await self.api_mock.start()
        self.client_runner.start()
        await asyncio.sleep(0.05)
        self.api_mock.reset_mock()

        # Select 'Foo'
        self.api_mock.add_update_for_bot({'message': {'message_id': 12345790,
                                                      'from': {'id': 987654123, 'is_bot': False, 'first_name:': "Max"},
                                                      'chat': {'id': 987654123, 'type': 'private', 'first_name': "Max"},
                                                      'date': datetime.datetime(2021, 1, 25, 17, 35).timestamp(),
                                                      'text': "/s Foo"}})

        await asyncio.sleep(0.3)
        self.api_mock.assert_one_method_called_with("sendMessage", chat_id="987654123")
        reply_markup = json.loads(self.api_mock.method_calls[-1][1]['reply_markup'])
        self.assertListEqual([[{'text': "off"}, {'text': "on"}], [{'text': "/cancel"}]], reply_markup['keyboard'])
        self.api_mock.reset_mock()

        # Write invalid value
        self.api_mock.add_update_for_bot({'message': {'message_id': 12345790,
                                                      'from': {'id': 987654123, 'is_bot': False, 'first_name:': "Max"},
                                                      'chat': {'id': 987654123, 'type': 'private', 'first_name': "Max"},
                                                      'date': datetime.datetime(2021, 1, 25, 17, 36).timestamp(),
                                                      'text': "bla"}})

        await asyncio.sleep(0.3)
        self.api_mock.assert_one_method_called_with("sendMessage", chat_id="987654123")
        self.assertIn('Invalid', self.api_mock.method_calls[-1][1]['text'])
        self.assertNotIn('reply_markup', self.api_mock.method_calls[-1][1])  # No change to responseKeyboard expected
        self.api_mock.reset_mock()

        # Write valid 'on' value
        self.api_mock.add_update_for_bot({'message': {'message_id': 12345790,
                                                      'from': {'id': 987654123, 'is_bot': False, 'first_name:': "Max"},
                                                      'chat': {'id': 987654123, 'type': 'private', 'first_name': "Max"},
                                                      'date': datetime.datetime(2021, 1, 25, 17, 36).timestamp(),
                                                      'text': "on"}})

        await asyncio.sleep(0.3)
        foo_target._write.assert_called_once_with(True, unittest.mock.ANY)

    @async_test
    async def test_read(self) -> None:
        foo = self.client.str_connector("Foo", {'max'}, {'max', 'tim'})\
            .connect(ExampleWritable(str))\
            .connect(ExampleReadable(str, "hello, world!"))
        foobar = self.client.generic_connector(int, "Foobar", lambda x: str(x), lambda x: int(x), {'max', 'alice'},
                                               options=["0", "5", "15"])\
            .connect(ExampleWritable(int))\
            .connect(ExampleReadable(int, 42))
        bar = self.client.generic_connector(str, "Bar", lambda x: x, lambda x: x, {'alice', 'max'}, {'alice'})\
            .connect(ExampleWritable(str))

        await self.api_mock.start()
        self.client_runner.start()
        await asyncio.sleep(0.05)
        self.api_mock.reset_mock()

        # Search for 'Foo'
        self.api_mock.add_update_for_bot({'message': {'message_id': 12345789,
                                                      'from': {'id': 987654123, 'is_bot': False, 'first_name:': "Max"},
                                                      'chat': {'id': 987654123, 'type': 'private', 'first_name': "Max"},
                                                      'date': datetime.datetime(2021, 1, 25, 17, 30).timestamp(),
                                                      'text': "Foo"}})
        await asyncio.sleep(0.3)
        self.api_mock.assert_one_method_called_with("sendMessage", chat_id="987654123")
        self.assertListEqual([[{'text': "/s Foo"}], [{'text': "/s Foobar"}]],
                             json.loads(self.api_mock.method_calls[-1][1]['reply_markup'])['keyboard'])
        self.api_mock.reset_mock()

        # Select 'Foobar'
        self.api_mock.add_update_for_bot({'message': {'message_id': 12345790,
                                                      'from': {'id': 987654123, 'is_bot': False, 'first_name:': "Max"},
                                                      'chat': {'id': 987654123, 'type': 'private', 'first_name': "Max"},
                                                      'date': datetime.datetime(2021, 1, 25, 17, 35).timestamp(),
                                                      'text': "/s Foobar"}})

        await asyncio.sleep(0.3)
        self.api_mock.assert_method_called_with("sendMessage", chat_id="987654123")
        self.assertIn("42", self.api_mock.method_calls[-2][1]['text'])
        reply_markup = json.loads(self.api_mock.method_calls[-1][1]['reply_markup'])
        self.assertListEqual([[{'text': "0"}, {'text': "5"}], [{'text': "15"}], [{'text': "/cancel"}]],
                             reply_markup['keyboard'])
        self.api_mock.reset_mock()

        # Cancel and select 'Foo'
        self.api_mock.add_update_for_bot({'message': {'message_id': 12345789,
                                                      'from': {'id': 987654123, 'is_bot': False, 'first_name:': "Max"},
                                                      'chat': {'id': 987654123, 'type': 'private', 'first_name': "Max"},
                                                      'date': datetime.datetime(2021, 1, 25, 17, 42).timestamp(),
                                                      'text': "/cancel"}})

        self.api_mock.add_update_for_bot({'message': {'message_id': 12345790,
                                                      'from': {'id': 987654123, 'is_bot': False, 'first_name:': "Max"},
                                                      'chat': {'id': 987654123, 'type': 'private', 'first_name': "Max"},
                                                      'date': datetime.datetime(2021, 1, 25, 17, 42, 30).timestamp(),
                                                      'text': "/s Foo"}})

        await asyncio.sleep(0.3)
        self.api_mock.assert_method_called_with("sendMessage", chat_id="987654123")
        self.assertIn("hello, world", self.api_mock.method_calls[-2][1]['text'])
        reply_markup = json.loads(self.api_mock.method_calls[-1][1]['reply_markup'])
        self.assertListEqual([[{'text': "cancel", 'callback_data': 'cancel'}]], reply_markup['inline_keyboard'])
        inline_keyboard_message_id = self.api_mock.method_calls[-1][2]['message_id']
        self.api_mock.reset_mock()

        # Directly (without cancel) select Foobar
        self.api_mock.add_update_for_bot({'message': {'message_id': 12345791,
                                                      'from': {'id': 987654123, 'is_bot': False, 'first_name:': "Max"},
                                                      'chat': {'id': 987654123, 'type': 'private', 'first_name': "Max"},
                                                      'date': datetime.datetime(2021, 1, 25, 17, 43).timestamp(),
                                                      'text': "/s Foobar"}})

        await asyncio.sleep(0.3)
        self.assertEqual("editMessageReplyMarkup", self.api_mock.method_calls[0][0])
        self.assertEqual(str(inline_keyboard_message_id), self.api_mock.method_calls[0][1]['message_id'])

        self.assertEqual("987654123", self.api_mock.method_calls[1][1]['chat_id'])
        self.assertIn("cancelled", self.api_mock.method_calls[1][1]['text'])

        self.assertEqual("987654123", self.api_mock.method_calls[2][1]['chat_id'])
        self.assertIn("42", self.api_mock.method_calls[2][1]['text'])
        self.api_mock.reset_mock()

        # Tim can select (and write) but not read
        self.api_mock.add_update_for_bot({'message': {'message_id': 12345792,
                                                      'from': {'id': 987654789, 'is_bot': False, 'first_name:': "Tim"},
                                                      'chat': {'id': 987654789, 'type': 'private', 'first_name': "Tim"},
                                                      'date': datetime.datetime(2021, 1, 25, 17, 44).timestamp(),
                                                      'text': "/s Foobar"}})
        await asyncio.sleep(0.3)
        self.api_mock.assert_one_method_called_with("sendMessage", chat_id="987654789")
        self.assertNotIn("42", self.api_mock.method_calls[-1][1]['text'])
        self.api_mock.reset_mock()

        # Max should not see 'Bar', because its not readable, but he es not allowed to write
        self.api_mock.add_update_for_bot({'message': {'message_id': 12345793,
                                                      'from': {'id': 987654123, 'is_bot': False, 'first_name:': "Max"},
                                                      'chat': {'id': 987654123, 'type': 'private', 'first_name': "Max"},
                                                      'date': datetime.datetime(2021, 1, 25, 17, 45).timestamp(),
                                                      'text': "/cancel"}})
        await asyncio.sleep(0.15)
        self.api_mock.add_update_for_bot({'message': {'message_id': 12345794,
                                                      'from': {'id': 987654123, 'is_bot': False, 'first_name:': "Max"},
                                                      'chat': {'id': 987654123, 'type': 'private', 'first_name': "Max"},
                                                      'date': datetime.datetime(2021, 1, 25, 17, 45, 20).timestamp(),
                                                      'text': "Bar"}})
        await asyncio.sleep(0.3)
        self.api_mock.assert_method_called_with("sendMessage", chat_id="987654123")
        self.assertListEqual([[{'text': "/s Foobar"}]],
                             json.loads(self.api_mock.method_calls[-1][1]['reply_markup'])['keyboard'])
        self.api_mock.reset_mock()

        self.api_mock.add_update_for_bot({'message': {'message_id': 12345795,
                                                      'from': {'id': 987654123, 'is_bot': False, 'first_name:': "Max"},
                                                      'chat': {'id': 987654123, 'type': 'private', 'first_name': "Max"},
                                                      'date': datetime.datetime(2021, 1, 25, 17, 45).timestamp(),
                                                      'text': "/s Bar"}})
        await asyncio.sleep(0.3)
        self.api_mock.assert_one_method_called_with("sendMessage", chat_id="987654123")
        self.assertIn("authorized", self.api_mock.method_calls[-1][1]['text'])
        self.api_mock.reset_mock()


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
        self.method_calls: List[Tuple[str, Dict[str, Any], Any]] = []   # let's keep the types simple here
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
                f"Wrong value '{self.method_calls[-1][1][arg]}' for Parameter {arg}, expected '{val}'"

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
        timeout = int(data.get('timeout', 0))  # type:  ignore
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
        if method == "sendMessage":
            result = self._create_send_message_response(data)
            self.method_calls.append((method, data, result))
            return aiohttp.web.json_response({'ok': True, 'result': result})
        if method == "editMessageReplyMarkup":
            # We can't create a correct response, b/c we didn't store the message
            self.method_calls.append((method, data, True))
            return aiohttp.web.json_response({'ok': True, 'result': True})
        if method == "deleteWebhook":
            self.method_calls.append((method, data, True))
            return aiohttp.web.json_response({'ok': True, 'result': True})
        else:
            self.method_calls.append((method, data, None))
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
