# Copyright 2020 Michael Thies <mail@mhthies.de>
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may not use this file except in compliance with
# the License. You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software distributed under the License is distributed on an
# "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the License for the
# specific language governing permissions and limitations under the License.

import abc
import asyncio
import contextvars
import functools
import logging
from typing import Generic, List, Any, Tuple, Callable, Optional, Type, TypeVar, Awaitable, Union

from . import conversion

S = TypeVar('S')
T = TypeVar('T')
LogicHandler = Callable[[T, List[Any]], Awaitable[None]]

logger = logging.getLogger(__name__)

magicSourceVar: contextvars.ContextVar[List[Any]] = contextvars.ContextVar('shc_source')


class Connectable(Generic[T], metaclass=abc.ABCMeta):
    type: Type[T]

    def connect(self, other: "Connectable",
                send: Optional[bool] = None,
                receive: Optional[bool] = None,
                read: Optional[bool] = None,
                provide: Optional[bool] = None,
                convert: bool = False) -> "Connectable":
        if isinstance(other, ConnectableWrapper):
            # If other object is not connectable itself but wraps one or more connectable objects (like, for example, a
            # `web.widgets.ValueButtonGroup`), let it use its special implementation of `connect()`.
            other.connect(self, send=receive, force_send=force_receive, receive=send, force_receive=force_send,
                          read=provide, provide=read, convert=convert)
        else:
            self._connect_with(self, other, send, provide, convert)
            self._connect_with(other, self, receive, read, convert)
        return self

    @staticmethod
    def _connect_with(source: "Connectable", target: "Connectable", send: Optional[bool], provide: Optional[bool],
                      convert: bool):
        if isinstance(source, Subscribable) and isinstance(target, Writable) and (send or send is None):
            source.subscribe(target, convert=convert)
        elif send and not isinstance(source, Subscribable):
            raise TypeError("Cannot subscribe {} to {}, since the latter is not Subscribable".format(target, source))
        elif send and not isinstance(target, Writable):
            raise TypeError("Cannot subscribe {} to {}, since the former is not Writable".format(target, source))
        if isinstance(source, Readable) and isinstance(target, Reading) \
                and (provide or (provide is None and not target.is_reading_optional)):
            target.set_provider(source, convert=convert)
        elif provide and not isinstance(source, Readable):
            raise TypeError("Cannot use {} as read provider for {}, since the former is not Readable"
                            .format(source, target))
        elif provide and not isinstance(target, Reading):
            raise TypeError("Cannot use {} as read provider for {}, since the latter is not Reading"
                            .format(source, target))


class ConnectableWrapper(Connectable[T], Generic[T], metaclass=abc.ABCMeta):
    type: Type[T]

    @abc.abstractmethod
    def connect(self, other: "Connectable",
                send: Optional[bool] = None,
                receive: Optional[bool] = None,
                read: Optional[bool] = None,
                provide: Optional[bool] = None,
                convert: bool = False) -> "Connectable":
        pass


class Writable(Connectable[T], Generic[T], metaclass=abc.ABCMeta):
    async def write(self, value: T, source: Optional[List[Any]] = None):
        if source is None:
            try:
                source = magicSourceVar.get()
            except LookupError as e:
                raise ValueError("No source attribute provided or set via execution context") from e
        if not isinstance(value, self.type):
            raise TypeError("Invalid type for {}: {} is not a {}".format(self, value, self.type.__name__))
        logger.debug("New value %s for %s via %s", value, self, source)
        await self._write(value, source)

    @abc.abstractmethod
    async def _write(self, value: T, source: List[Any]):
        pass


class Readable(Connectable[T], Generic[T], metaclass=abc.ABCMeta):
    @abc.abstractmethod
    async def read(self) -> T:
        pass


class UninitializedError(RuntimeError):
    pass


class Subscribable(Connectable[T], Generic[T], metaclass=abc.ABCMeta):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._subscribers: List[Tuple[Writable[S], Optional[Callable[[T], S]]]] = []
        self._triggers: List[LogicHandler] = []

    async def __publish_write(self, subscriber: Writable[S], converter: Optional[Callable[[T], S]], value: T,
                              source: List[Any]):
        try:
            await subscriber.write(converter(value) if converter else value, source + [self])  # type: ignore
        except Exception as e:
            logger.error("Error while writing new value %s from %s to %s:", value, self, subscriber, exc_info=e)

    async def __publish_trigger(self, target: LogicHandler, value: T, source: List[Any]):
        try:
            await target(value, source + [self])
        except Exception as e:
            logger.error("Error while triggering %s from %s:", target, self, exc_info=e)

    async def _publish(self, value: T, source: List[Any], changed: bool = True):
        await asyncio.gather(
            *(self.__publish_write(subscriber, converter, value, source)
              for subscriber, converter in self._subscribers
              if not any(subscriber is s for s in source)),
            *(self.__publish_trigger(target, value, source)
              for target in self._triggers)
        )

    def subscribe(self, subscriber: Writable[S], convert: Union[Callable[[T], S], bool] = False):
        converter: Optional[Callable[[T], S]]
        if callable(convert):
            converter = convert
        elif issubclass(self.type, subscriber.type):
            converter = None
        elif convert:
            converter = conversion.get_converter(self.type, subscriber.type)
        else:
            raise TypeError("Type mismatch of subscriber {} ({}) for {} ({})"
                            .format(repr(subscriber), subscriber.type.__name__, repr(self), self.type.__name__))
        self._subscribers.append((subscriber, converter))

    def trigger(self, target: LogicHandler) -> LogicHandler:
        self._triggers.append(target)
        return target


class Reading(Connectable[T], Generic[T], metaclass=abc.ABCMeta):
    is_reading_optional: bool = True

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._default_provider: Optional[Tuple[Readable[S], Optional[Callable[[S], T]]]] = None

    def set_provider(self, provider: Readable[S], convert: Union[Callable[[S], T], bool] = False):
        converter: Optional[Callable[[S], T]]
        if callable(convert):
            converter = convert
        elif issubclass(provider.type, self.type):
            converter = None
        elif convert:
            converter = conversion.get_converter(provider.type, self.type)
        else:
            raise TypeError("Type mismatch of Readable {} ({}) as provider for {} ({})"
                            .format(repr(provider), provider.type.__name__, repr(self), self.type.__name__))
        self._default_provider = (provider, converter)

    async def _from_provider(self) -> Optional[T]:
        if self._default_provider is None:
            return None
        provider, convert = self._default_provider
        try:
            val = await provider.read()
        except UninitializedError:
            return None
        return convert(val) if convert else val


def handler(reset_source=False, allow_recursion=False) -> Callable[[LogicHandler], LogicHandler]:
    def decorator(f: LogicHandler) -> LogicHandler:
        @functools.wraps(f)
        async def wrapper(value, source: Optional[List[Any]] = None) -> None:
            if source is None:
                try:
                    source = magicSourceVar.get()
                except LookupError as e:
                    raise ValueError("No source attribute provided or set via execution context") from e
            if any(wrapper is s for s in source) and not allow_recursion:
                logger.warning("Skipping recursive execution of logic handler %s() via %s", f.__name__, source)
                return
            logger.info("Triggering logic handler %s() from %s", f.__name__, source)
            try:
                token = magicSourceVar.set([wrapper] if reset_source else (source + [wrapper]))
                await f(value, source)
                magicSourceVar.reset(token)
            except Exception as e:
                logger.error("Error while executing handler %s():", f.__name__, exc_info=e)
        return wrapper
    return decorator
