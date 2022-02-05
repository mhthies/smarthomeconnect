import abc
import asyncio
import logging
import re
from typing import Generic, TypeVar, Set, Type, Optional, List, Pattern, Tuple, Dict, Any

import aiogram

from ..base import Writable, Subscribable, Reading, T
from ..supervisor import AbstractInterface

RoleT = TypeVar('RoleT')
UserT = TypeVar('UserT')

logger = logging.getLogger(__name__)


class TelegramBot(AbstractInterface, Generic[UserT, RoleT]):
    """
    TODO
    """

    def __init__(self, api_token: str, auth_provider: "TelegramAuthProvider[UserT, RoleT]"):
        super().__init__()
        self.auth_provider = auth_provider

        self.bot = aiogram.Bot(token=api_token)
        self.dp = aiogram.Dispatcher(self.bot)
        self.dp.register_message_handler(self._handle_start, commands=["start"])
        self.dp.register_message_handler(self._handle_cancel, commands=["cancel"])
        self.dp.register_message_handler(self._handle_select, commands=["s"])
        self.dp.register_callback_query_handler(self._handle_callback_query)
        self.dp.register_message_handler(self._handle_other)
    
        self.variables: Dict[str, "TelegramVariableConnector"] = {}
        self.poll_task: Optional[asyncio.Task] = None
        #: Current state/context of each chat. Either None (init state selected) or
        self.chat_state: Dict[int, TelegramVariableConnector] = {}

    async def start(self) -> None:
        self.poll_task = asyncio.create_task(self._run())

    async def _run(self) -> None:
        await self.dp.start_polling()

    async def stop(self) -> None:
        self.dp.stop_polling()
        await self.poll_task
        await self.dp.storage.close()
        await self.dp.storage.wait_closed()
        session = await self.dp.bot.get_session()
        await session.close()

    async def _handle_start(self, message: aiogram.types.Message):
        """
        Handler function for /start command messages

        :param message: The aiogram Message object representing the incoming message
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
        Handler function for /s command messages for selecting (and reading) a variable

        :param message: The aiogram Message object representing the incoming message
        """
        # TODO logging
        chat_id = message.chat.id
        user = self.auth_provider.get_telegram_user(chat_id)
        if user is None:
            await message.reply("Not authorized!")
            return
        variable_id = message.text[3:]  # strip the '/select ' prefix
        if variable_id not in self.variables:
            await message.reply("Unknown variable/connector")
            return
        variable = self.variables[variable_id]
        # Read value
        if self.auth_provider.has_user_role(user, variable.read_roles):
            read_message = await variable.read_message()
            if read_message:
                await message.reply(read_message, reply=False)
        # Prepare setting value
        if variable.is_settable() and self.auth_provider.has_user_role(user, variable.set_roles):
            keyboard = variable.get_setting_keyboard()
            # TODO add inline keyboard for cancelling
            await message.reply(variable.get_set_message(), reply=False, reply_markup=keyboard)
            self.chat_state[message.chat.id] = variable

    async def _handle_cancel(self, message: aiogram.types.Message) -> None:
        """
        Handler function for /cancel command messages for cancelling the current chat context

        :param message: The aiogram Message object representing the incoming message
        """
        logger.debug("Received /cancel format for Telegram chat %s", message.chat.id)
        await self._do_cancel(message.chat.id)

    async def _handle_other(self, message: aiogram.types.Message) -> None:
        """
        Handler function for all incoming Telegram messages that are not recognized as a command.

        The message is

        :param message: The aiogram Message object representing the incoming message
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
            await self._do_variable_search(message, user)

    async def _do_set(self, message: aiogram.types.Message, user: UserT) -> None:
        """


        :param message:
        :param user:
        """
        chat_id = message.chat.id
        context = self.chat_state.get(chat_id)
        assert(context is not None)  # _do_set() should only be called if a context is present
        if not self.auth_provider.has_user_role(user, context.set_roles):
            logger.warning("User %s is not authorized for setting Telegram variable %s", user, context.name)
            await message.reply("Not authorized!")
            return
        value = message.text
        try:
            logger.info("Received value '%s' for Telegram variable %s", value, context.name)
            context.from_telegram(value)
            await message.reply("🆗", reply=False, reply_markup=aiogram.types.ReplyKeyboardRemove())
            del self.chat_state[chat_id]
        except (TypeError, ValueError) as e:
            logger.warning("Invalid value '%s' received for Telegram variable %s: %s", value, context.name, e)
            await message.reply(f"Invalid value for variable/object {context.name}: {e}")
        except Exception as e:
            logger.error("Error while sending value '%s' to Telegram variable/object %s:", value, context.name,
                         exc_info=e)
            await message.reply(f"Internal error while setting value for variable/object {context.name}")

    async def _do_variable_search(self, message: aiogram.types.Message, user: UserT) -> None:
        """
        TODO

        :param message:
        :param user:
        """
        variables = self._find_matching_variables(message.text, user)
        if variables:
            await message.reply("Please chose", reply_markup=aiogram.types.ReplyKeyboardMarkup(
                [[aiogram.types.KeyboardButton(f"/s {var.name}")]
                 for var in variables],
                one_time_keyboard=True,
                resize_keyboard=True), reply=False)
        else:
            await message.reply("No matching variable/control found")

    def _find_matching_variables(self, search_term: str, user: UserT) -> List["TelegramVariableConnector"]:
        """
        TODO

        :param search_term:
        :param user:
        :return:
        """
        regex = re.compile(re.escape(search_term), re.IGNORECASE)
        return [var
                for name, var in self.variables.items()
                if regex.search(name) and (
                    self.auth_provider.has_user_role(user, var.read_roles)
                    or self.auth_provider.has_user_role(user, var.set_roles))]

    async def _handle_callback_query(self, query: aiogram.types.CallbackQuery) -> None:
        """
        TODO
        :param query:
        """
        logger.debug("Received CallbackQuery")
        if query.message is None:
            logger.warning("Received CallbackQuery without message, so the originating chat cannot be identified.")
            return
        if query.data == 'cancel':
            await self._do_cancel(query.message.chat.id)

    async def _do_cancel(self, chat_id: int) -> None:
        """
        TODO
        :param chat_id:
        """
        if chat_id in self.chat_state:
            del self.chat_state[chat_id]
            await self.bot.send_message(chat_id, "Action cancelled", reply_markup=aiogram.types.ReplyKeyboardRemove())
        else:
            await self.bot.send_message(chat_id, "Nothing to do.", reply_markup=aiogram.types.ReplyKeyboardRemove())

    def generic_variable(self, name: str, read_roles: Set[RoleT], set_roles: Optional[Set[RoleT]] = None,
                         send_users: Set[UserT] = set(), alternative_names: Optional[Pattern] = None,
                         options: Optional[List[Tuple[str, str]]] = None) -> "TelegramVariableConnector[str]":
        """
        TODO

        :param name:
        :param read_roles:
        :param set_roles:
        :param send_roles:
        :param alternative_names:
        :param options:
        :return:
        """
        if name in self.variables:
            raise ValueError(f"Variable with name {name} already exists in this Telegram bot.")
        var = TelegramVariableConnector(self, str, name, read_roles, send_users,
                                        set_roles if set_roles is not None else read_roles)
        self.variables[name] = var
        return var

    def on_off_variable(self, name: str, read_roles: Set[RoleT], set_roles: Optional[Set[RoleT]] = None,
                         send_users: Set[UserT] = set(), alternative_names: Optional[Pattern] = None,
                         options: Optional[List[Tuple[str, str]]] = None) -> "TelegramVariableConnector[bool]":
        if name in self.variables:
            raise ValueError(f"Variable with name {name} already exists in this Telegram bot.")
        var = OnOffVariable(self, name, read_roles, send_users,
                            set_roles if set_roles is not None else read_roles)
        self.variables[name] = var
        return var

    async def send_message(self, message, users: Set[UserT], chat_ids: Set[int] = set()) -> None:
        """
        TODO

        :param message:
        :param users:
        :param chat_ids:
        :return:
        """
        user_chats = set()
        for user in users:
            chat = self.auth_provider.get_telegram_chat_of_user(user)
            if chat is None:
                logger.warning("Could not resolve user %s to Telegram chat_id for sending message to them", user)
            else:
                user_chats.add(chat)
        await asyncio.gather(*(self.bot.send_message(chat_id, message)
                               for chat_id in chat_ids | user_chats))


class TelegramVariableConnector(Generic[T, RoleT], Reading[T], Subscribable[T], Writable[T]):
    def __init__(self, interface: TelegramBot, type_: Type[T], name: str, read_roles: Set[RoleT],
                 send_users: Set[UserT], set_roles: Set[RoleT]):
        self.type = type_
        super().__init__()
        self.interface = interface
        self.name = name
        self.read_roles = read_roles
        self.send_users = send_users
        self.set_roles = set_roles
    
    def is_settable(self) -> bool:
        return bool(self._subscribers or self._triggers)

    async def _write(self, value: T, _origin: List[Any]) -> None:
        await self.interface.send_message(message=self._format_value_send(value), users=self.send_users)
    
    async def read_message(self) -> Optional[str]:
        value = await self._from_provider()
        res = []
        if value is not None:
            res.append(self._format_value_select(value))
        return None

    def from_telegram(self, value: str) -> None:
        self._publish(self._parse_value(value), [])
    
    def get_setting_keyboard(self) -> Optional[aiogram.types.ReplyKeyboardMarkup]:
        return None

    def _format_value_select(self, value) -> str:
        return f"{self.name} is currently {value}"

    def _format_value_send(self, value) -> str:
        return f"{self.name} is now {value}"

    def get_set_message(self) -> str:
        return "Set it to?"

    def _parse_value(self, value: str) -> T:
        return self.type(value)


class OnOffVariable(TelegramVariableConnector[bool, RoleT], Generic[RoleT]):
    def __init__(self, interface: TelegramBot, name: str, read_roles: Set[RoleT], send_users: Set[UserT],
                 set_roles: Set[RoleT]):
        super().__init__(interface, bool, name, read_roles, send_users, set_roles)

    def get_setting_keyboard(self) -> aiogram.types.ReplyKeyboardMarkup:
        return aiogram.types.ReplyKeyboardMarkup(
            [[aiogram.types.KeyboardButton("off"), aiogram.types.KeyboardButton("on")],
             [aiogram.types.KeyboardButton("/cancel")]])

    def get_set_message(self) -> str:
        return "Switch?"

    def _parse_value(self, value: str) -> bool:
        if value == "on":
            return True
        elif value == "off":
            return False
        else:
            raise ValueError("Invalid on/off value.")


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
    * :cls:`SimpleTelegramAuth`
    """
    @abc.abstractmethod
    def get_telegram_user(self, chat_id: int) -> Optional[UserT]:
        pass

    @abc.abstractmethod
    def has_user_role(self, user: UserT, roles: Set[RoleT]) -> Optional[bool]:
        pass

    def get_telegram_chat_of_user(self, user: UserT) -> Optional[UserT]:
        return None


class SimpleTelegramAuth(TelegramAuthProvider[str, str]):
    """
    A simple implementation of a :cls:`TelegramAuthProvider`.

    It uses a fixed dict for mapping user id strings and telegram chat ids and uses the user id strings themselves as
    role definitions. Thus, it does not have a concept of user groups; you always need to specify the set of all
    authorized user ids for each TelegramBot variable. (Of course, you can put the set in a variable to reuse it.)

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
