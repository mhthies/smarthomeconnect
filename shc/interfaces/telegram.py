import abc
import asyncio
import logging
import re
from typing import Generic, TypeVar, Set, Type, Optional, List, Pattern, Tuple, Dict, Any, Callable

import aiogram
from aiogram.bot.api import TelegramAPIServer, TELEGRAM_PRODUCTION

from ..base import Writable, Subscribable, Reading, T
from ..supervisor import AbstractInterface

RoleT = TypeVar('RoleT')
UserT = TypeVar('UserT')

logger = logging.getLogger(__name__)


class TelegramBot(AbstractInterface, Generic[UserT, RoleT]):
    """
    TODO
    """

    def __init__(self, api_token: str, auth_provider: "TelegramAuthProvider[UserT, RoleT]",
                 telegram_server: TelegramAPIServer = TELEGRAM_PRODUCTION):
        super().__init__()
        self.auth_provider = auth_provider

        self.bot = aiogram.Bot(token=api_token, server=telegram_server)
        self.dp = aiogram.Dispatcher(self.bot)
        self.dp.register_message_handler(self._handle_start, commands=["start"])
        self.dp.register_message_handler(self._handle_cancel, commands=["cancel"])
        self.dp.register_message_handler(self._handle_select, commands=["s"])
        self.dp.register_callback_query_handler(self._handle_callback_query)
        self.dp.register_message_handler(self._handle_other)
    
        self.connectors: Dict[str, "TelegramConnector"] = {}
        self.poll_task: Optional[asyncio.Task] = None
        #: Current state/context of each chat. Either None (init state selected) or
        self.chat_state: Dict[int, TelegramConnector] = {}
        #: Maps chat ids to a message id of a messages with an active inline keyboard in that chat, if any.
        #: Used to clean up inline keyboards, when cancelled.
        self.message_with_inline_keyboard: Dict[int, int] = {}

    async def start(self) -> None:
        self.poll_task = asyncio.create_task(self._run())

    async def _run(self) -> None:
        await self.dp.start_polling()

    async def stop(self) -> None:
        self.dp.stop_polling()
        if self.poll_task:
            await self.poll_task
        await self.dp.storage.close()
        await self.dp.storage.wait_closed()
        session = await self.dp.bot.get_session()
        await session.close()

    async def _handle_start(self, message: aiogram.types.Message):
        """
        Handler function for /start command messages
        """
        # TODO logging
        await message.reply("Hi!\nI'm an SHC bot!", reply=False)
        chat_id = message.chat.id
        user = self.auth_provider.get_telegram_user(chat_id)
        if user is None:
            await message.reply(f"Unauthorized! Please make sure that this Telegram chat's ID ({chat_id}) is "
                                f"authorized to interact with this bot.", reply=False)

    async def _handle_select(self, message: aiogram.types.Message) -> None:
        """
        Handler function for /s command messages for selecting (and reading) a connector
        """
        # TODO logging
        chat_id = message.chat.id
        user = self.auth_provider.get_telegram_user(chat_id)
        if user is None:
            await message.reply("Not authorized!")
            return

        # Cancel ongoing value setting (if any)
        if chat_id in self.chat_state:
            await self._do_cancel(chat_id, silent=True)

        connector_id = message.text[3:]  # strip the '/select ' prefix
        if connector_id not in self.connectors:
            await message.reply("Unknown connector/object")
            return
        connector = self.connectors[connector_id]
        not_authorized = True

        # Read value
        if connector.is_readable() and self.auth_provider.has_user_role(user, connector.read_roles):
            not_authorized = False
            read_message = await connector.read_message()
            if read_message:
                await message.reply(read_message, reply=False)

        # Prepare setting value
        if connector.is_settable() and self.auth_provider.has_user_role(user, connector.set_roles):
            not_authorized = False
            # Create custom keyboard/inline keyboard markup
            keyboard = connector.get_setting_keyboard()
            # If no options/custom keyboard is provided, we create an inline keyboard of cancelling the value setting.
            # Otherwise, we add a `/cancel` button to the bottom of the keyboard.
            if keyboard is None:
                keyboard = aiogram.types.InlineKeyboardMarkup(
                    row_width=1,
                    inline_keyboard=[[aiogram.types.InlineKeyboardButton("cancel", callback_data="cancel")]])
                inline_keyboard = True
            else:
                keyboard.keyboard.append([aiogram.types.KeyboardButton("/cancel")])
                inline_keyboard = False

            reply_message = await message.reply(connector.get_set_message(), reply=False, reply_markup=keyboard)
            self.chat_state[message.chat.id] = connector
            if inline_keyboard:
                self.message_with_inline_keyboard[chat_id] = reply_message.message_id

        if not_authorized:
            await message.reply("Not authorized!")

    async def _handle_cancel(self, message: aiogram.types.Message) -> None:
        """
        Handler function for /cancel command messages for cancelling the current chat context
        """
        logger.debug("Received /cancel format for Telegram chat %s", message.chat.id)
        await self._do_cancel(message.chat.id)

    async def _handle_other(self, message: aiogram.types.Message) -> None:
        """
        Handler function for all incoming Telegram messages that are not recognized as a command.

        The message is interpreted as a connector search or a new value for the selected connector, depending on the
        current chat state.
        """
        chat_id = message.chat.id
        user = self.auth_provider.get_telegram_user(chat_id)
        if user is None:
            await message.reply("Not authorized!")
            logger.warning("Received non-command message '%s' from unauthorized Telegram user (chat id %s)",
                           message.text, chat_id)
            return
        logger.debug("Received non-command message '%s' from Telegram user %s", message.text, user)
        if chat_id in self.chat_state:
            await self._do_set(message, user)
        else:
            await self._do_connector_search(message, user)

    async def _do_set(self, message: aiogram.types.Message, user: UserT) -> None:
        """
        Use the given Telegram message as a new value for the currently selected connector in the message's chat

        This method must should only be called, if the message's chat is known to have a selected connector/context
        (chat_state) and the chat is known to belong to an authenticated user. The user's authorization for the
        connector is checked by this method.

        :param message: The Telegram message to be handled as a new value
        :param user: The identified user, related to the chat
        """
        chat_id = message.chat.id
        context = self.chat_state.get(chat_id)
        assert(context is not None)  # _do_set() should only be called if a context is present
        if not self.auth_provider.has_user_role(user, context.set_roles):
            logger.warning("User %s is not authorized for setting Telegram connector %s", user, context.name)
            await message.reply("Not authorized!")
            return
        value = message.text
        try:
            logger.info("Received value '%s' for Telegram connector %s", value, context.name)
            context.from_telegram(value)
            await message.reply("🆗", reply=False, reply_markup=aiogram.types.ReplyKeyboardRemove())
            del self.chat_state[chat_id]
        except (TypeError, ValueError) as e:
            logger.warning("Invalid value '%s' received for Telegram connector %s: %s", value, context.name, e)
            await message.reply(f"Invalid value for connector/object {context.name}: {e}")
        except Exception as e:
            logger.error("Error while sending value '%s' to Telegram connector/object %s:", value, context.name,
                         exc_info=e)
            await message.reply(f"Internal error while setting value for connector/object {context.name}")

    async def _do_connector_search(self, message: aiogram.types.Message, user: UserT) -> None:
        """
        TODO

        :param message:
        :param user:
        """
        connectors = self._find_matching_connectors(message.text, user)
        if connectors:
            await message.reply("Please chose", reply_markup=aiogram.types.ReplyKeyboardMarkup(
                [[aiogram.types.KeyboardButton(f"/s {var.name}")]
                 for var in connectors],
                one_time_keyboard=True,
                resize_keyboard=True), reply=False)
        else:
            await message.reply("No matching connector/object found")

    def _find_matching_connectors(self, search_term: str, user: UserT) -> List["TelegramConnector"]:
        """
        Search for connectors of this bot, matching a given search term, entered by the user, and being accessible for
        the given user.

        This method is used to present a connector selection list to the user, when they enter a search term.
        """
        regex = re.compile(re.escape(search_term), re.IGNORECASE)
        return [var
                for name, var in self.connectors.items()
                if regex.search(name) and (
                    self.auth_provider.has_user_role(user, var.read_roles) and var.is_readable()
                    or self.auth_provider.has_user_role(user, var.set_roles) and var.is_settable())]

    async def _handle_callback_query(self, query: aiogram.types.CallbackQuery) -> None:
        """
        Handler function to be called when an inline button callback query is received from Telegram.

        This is currently only used for "cancel" inline keyboard buttons.
        """
        logger.debug("Received CallbackQuery")
        if query.message is None:
            logger.warning("Received CallbackQuery without message, so the originating chat cannot be identified.")
            return
        if query.data == 'cancel':
            # Remove inline keyboard. Just to be sure. (Should also be done by _do_cancel(), when chat state is tracked
            # correctly)
            chat_id = query.message.chat.id
            message_id = query.message.message_id
            await self.bot.edit_message_reply_markup(chat_id, message_id, reply_markup=None)
            if self.message_with_inline_keyboard.get(chat_id) == message_id:
                del self.message_with_inline_keyboard[chat_id]
            # Now, the actual action cancelling
            await self._do_cancel(query.message.chat.id)

    async def _do_cancel(self, chat_id: int, silent: bool = False) -> None:
        """
        Cancel the connector setting in progress in the given chat

        This means:

        * reset the chat_state/unselect the selected context/connector (so following input is not interpreted as a value
          for this connector)
        * remove the custom keyboard (if any)
        * remove the inline keyboard (if any)

        :param chat_id: The Telegram chat id of the chat to be resetted
        :param silent: If True, a message is only sent to the chat if a connector is actually selected in this chat. If
            **there is** a connector selected, a message is sent nonetheless. As a side effect, if no message is sent,
            we cannot reset the custom keyboard either. However, this *should* not be required in this case, if we
            tracked the state correctly.
        """
        if chat_id in self.message_with_inline_keyboard:
            message_id = self.message_with_inline_keyboard[chat_id]
            await self.bot.edit_message_reply_markup(chat_id, message_id, reply_markup=None)
            del self.message_with_inline_keyboard[chat_id]
        if chat_id in self.chat_state:
            del self.chat_state[chat_id]
            await self.bot.send_message(chat_id, "Action cancelled", reply_markup=aiogram.types.ReplyKeyboardRemove())
        elif not silent:
            await self.bot.send_message(chat_id, "No action in progress.",
                                        reply_markup=aiogram.types.ReplyKeyboardRemove())

    def generic_connector(self, type_: Type[T], name: str,
                          to_message: Callable[[T], str], parse_value: Callable[[str], T],
                          read_roles: Set[RoleT], set_roles: Optional[Set[RoleT]] = None,
                          send_users: Set[UserT] = set(), options: Optional[List[str]] = None
                          ) -> "TelegramConnector[T, RoleT]":
        """
        TODO

        :param type_:
        :param name:
        :param to_message:
        :param parse_value:
        :param read_roles:
        :param set_roles:
        :param send_users:
        :param options:
        :return:
        """
        if name in self.connectors:
            raise ValueError(f"Connector with name {name} already exists in this Telegram bot.")
        var = TelegramConnector(
            self, type_, name, read_roles, send_users,
            set_roles if set_roles is not None else read_roles,
            "Change to?", parse_value,
            lambda x: f"{name} is currently {to_message(x)}", lambda x: f"{name} is now {to_message(x)}",
            options)
        self.connectors[name] = var
        return var

    def str_connector(self, name: str, read_roles: Set[RoleT], set_roles: Optional[Set[RoleT]] = None,
                      send_users: Set[UserT] = set()) -> "TelegramConnector[str, RoleT]":
        """
        TODO

        :param name:
        :param read_roles:
        :param set_roles:
        :param send_users:
        :return:
        """
        if name in self.connectors:
            raise ValueError(f"Connector with name {name} already exists in this Telegram bot.")
        var = TelegramConnector(
            self, str, name, read_roles, send_users,
            set_roles if set_roles is not None else read_roles,
            "Change to?", lambda x: x,
            lambda x: f"{name} is currently {x}", lambda x: f"{name} is now {x}",
            None)
        self.connectors[name] = var
        return var

    def on_off_connector(self, name: str, read_roles: Set[RoleT], set_roles: Optional[Set[RoleT]] = None,
                         send_users: Set[UserT] = set()) -> "TelegramConnector[bool, RoleT]":
        """
        TODO

        :param name:
        :param read_roles:
        :param set_roles:
        :param send_users:
        :return:
        """
        if name in self.connectors:
            raise ValueError(f"Connector with name {name} already exists in this Telegram bot.")

        def parse_value(x: str) -> bool:
            if x == "on":
                return True
            elif x == "off":
                return False
            else:
                raise ValueError("Invalid on/off value.")

        var = TelegramConnector(
            self, bool, name, read_roles, send_users,
            set_roles if set_roles is not None else read_roles,
            "Switch?",
            parse_value,
            lambda x: f"{name} is currently {'on' if x else 'off'}.",
            lambda x: f"{name} is now {'on' if x else 'off'}",
            ['off', 'on'])
        self.connectors[name] = var
        return var

    def trigger_connector(self, name: str, read_roles: Set[RoleT], set_roles: Optional[Set[RoleT]] = None,
                          send_users: Set[UserT] = set()) -> "TelegramConnector[None, RoleT]":
        """
        TODO

        :param name:
        :param read_roles:
        :param set_roles:
        :param send_users:
        :return:
        """
        if name in self.connectors:
            raise ValueError(f"Connector with name {name} already exists in this Telegram bot.")

        def parse_value(x: str) -> None:
            if x == "do":
                return None
            else:
                raise ValueError("Invalid value. Must be 'do'. Otherwise, use /cancel to cancel triggering.")

        var = TelegramConnector(
            self, type(None), name, read_roles, send_users,
            set_roles if set_roles is not None else read_roles,
            "Trigger?",
            parse_value,
            lambda x: "",
            lambda x: f"{name} has been triggered",
            ['do'])
        self.connectors[name] = var
        return var

    async def send_message(self, text: str, users: Set[UserT], chat_ids: Set[int] = set()) -> None:
        """
        Send a message to one or more Telegram chats, identified by either the Telegram chat id or a user of the given
        auth_provider

        Currently, only unformatted text messages are supported.

        :param text: The message text
        :param users: A set of users of this bot's auth_provider to send the message to
        :param chat_ids: A set of (additional) telegram chat ids to send the message to. If a specific chat is part of
            both sets, the message is still only sent once.
        """
        user_chats = set()
        for user in users:
            chat = self.auth_provider.get_telegram_chat_of_user(user)
            if chat is None:
                logger.warning("Could not resolve user %s to Telegram chat_id for sending message to them", user)
            else:
                user_chats.add(chat)
        await asyncio.gather(*(self.bot.send_message(chat_id, text)
                               for chat_id in chat_ids | user_chats))


class TelegramConnector(Generic[T, RoleT], Reading[T], Subscribable[T], Writable[T],
                        metaclass=abc.ABCMeta):
    is_reading_optional = False

    def __init__(self, interface: TelegramBot, type_: Type[T], name: str, read_roles: Set[RoleT],
                 send_users: Set[UserT], set_roles: Set[RoleT], set_message: str, parse_value: Callable[[str], T],
                 format_value_read: Callable[[T], str], format_value_send: Callable[[T], str],
                 options: Optional[List[str]]):
        self.type = type_
        super().__init__()
        self.interface = interface
        self.name = name
        self.read_roles = read_roles
        self.send_users = send_users
        self.set_roles = set_roles

        self.set_message = set_message
        self.parse_value_fn = parse_value
        self.format_value_read_fn = format_value_read
        self.format_value_send_fn = format_value_send
        if options:
            self.keyboard = aiogram.types.ReplyKeyboardMarkup(
                [[aiogram.types.KeyboardButton(o)
                  for o in options[i:i+2]]
                 for i in range(0, len(options), 2)])
        else:
            self.keyboard = None
    
    def is_settable(self) -> bool:
        """ Returns True, if the connector has subscribers, i.e. it is meaningfully readable from Telegram """
        return bool(self._subscribers or self._triggers)

    def is_readable(self) -> bool:
        """ Returns True, if the connector has a default_provider, i.e. it is meaningfully writable from Telegram """
        return self._default_provider is not None

    async def _write(self, value: T, _origin: List[Any]) -> None:
        await self.interface.send_message(text=self.format_value_send_fn(value), users=self.send_users)
    
    async def read_message(self) -> Optional[str]:
        """ Create a response to a read-request from Telegram.

        :return: A message with the current value from the default_provider, using the :attr:`format_value_read_fn` or
        """
        value = await self._from_provider()
        if value is not None:
            return self.format_value_read_fn(value)
        return None

    def from_telegram(self, value: str) -> None:
        self._publish(self.parse_value_fn(value), [])
    
    def get_setting_keyboard(self) -> aiogram.types.ReplyKeyboardMarkup:
        return self.keyboard

    def get_set_message(self) -> str:
        return self.set_message


class TelegramAuthProvider(Generic[UserT, RoleT], metaclass=abc.ABCMeta):
    """
    Abstract base class for authentication & authorization providers for the SHC TelegramBot interface

    A `TelegramAuthProvider` allows to authenticate Telegram users by their chat id and check their authorization for
    specific functions of the TelegramBot interface based on a custom 'Role' type. The AuthProvider's Role type is used
    to define the set of authorized roles for each individual function of the TelegramBot interface. The set of roles is
    treated as a black box by the bot and only passed to the AuthProvider to check authorization.
    
    When a user interacts with the bot, the bot authenticates them by their chat id using :meth:`get_telegram_user`. If
    the method returns `None`, the user is rejected. Otherwise, the authenticated user is returned, represented as an
    (arbitrary) unique user id string. For each interaction with a Bot functionality, the AuthProvider's
    :meth:`has_user_role` method is used to check if the specific user (user id string) is allowed to use the
    functionality based on the given set of role objects.

    Provided implementations by SHC:
    * :class:`SimpleTelegramAuth`
    """
    @abc.abstractmethod
    def get_telegram_user(self, chat_id: int) -> Optional[UserT]:
        pass

    @abc.abstractmethod
    def has_user_role(self, user: UserT, roles: Set[RoleT]) -> Optional[bool]:
        pass

    def get_telegram_chat_of_user(self, user: UserT) -> Optional[int]:
        return None


class SimpleTelegramAuth(TelegramAuthProvider[str, str]):
    """
    A simple implementation of a :class:`TelegramAuthProvider`.

    It uses a fixed dict for mapping user id strings and telegram chat ids and uses the user id strings themselves as
    role definitions. Thus, it does not have a concept of user groups; you always need to specify the set of all
    authorized user ids for each TelegramBot connector. (Of course, you can put the set in a variable to reuse it.)

    :param users: Dict of users in the form {user_id: telegram_chat_id}
    """
    def __init__(self, users: Dict[str, int]):
        self.users = users
        self.user_by_id = {v: k for k, v in users.items()}
    
    def get_telegram_user(self, chat_id: int) -> Optional[str]:
        try:
            return self.user_by_id[chat_id]
        except KeyError:
            return None

    def has_user_role(self, user: str, roles: Set[RoleT]) -> Optional[bool]:
        return user in roles

    def get_telegram_chat_of_user(self, user: str) -> Optional[int]:
        try:
            return self.users[user]
        except KeyError:
            return None
