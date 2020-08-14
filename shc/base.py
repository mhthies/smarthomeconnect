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

magicOriginVar: contextvars.ContextVar[List[Any]] = contextvars.ContextVar('shc_origin')


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
            other.connect(self, send=receive, receive=send, read=provide, provide=read, convert=convert)
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
    async def write(self, value: T, origin: Optional[List[Any]] = None):
        if origin is None:
            try:
                origin = magicOriginVar.get()
            except LookupError as e:
                raise ValueError("No origin attribute provided or set via execution context") from e
        if not isinstance(value, self.type):
            raise TypeError("Invalid type for {}: {} is not a {}".format(self, value, self.type.__name__))
        logger.debug("New value %s for %s via %s", value, self, origin)
        await self._write(value, origin)

    @abc.abstractmethod
    async def _write(self, value: T, origin: List[Any]):
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
                              origin: List[Any]):
        try:
            await subscriber.write(converter(value) if converter else value, origin + [self])  # type: ignore
        except Exception as e:
            logger.error("Error while writing new value %s from %s to %s:", value, self, subscriber, exc_info=e)

    async def __publish_trigger(self, target: LogicHandler, value: T, origin: List[Any]):
        try:
            await target(value, origin + [self])
        except Exception as e:
            logger.error("Error while triggering %s from %s:", target, self, exc_info=e)

    async def _publish(self, value: T, origin: List[Any], changed: bool = True):
        await asyncio.gather(
            *(self.__publish_write(subscriber, converter, value, origin)
              for subscriber, converter in self._subscribers
              if not any(subscriber is s for s in origin)),
            *(self.__publish_trigger(target, value, origin)
              for target in self._triggers)
        )

    def subscribe(self, subscriber: Writable[S], convert: Union[Callable[[T], S], bool] = False) -> None:
        """
        Subscribe a writable object to this object to be updated, when this object publishes a new value.

        The subscriber's :meth:`Writable.write` method will be called for any new value published by this object, as
        long as the subscriber did not lead to the relevant update of this object (i.e. is not included in the
        `origin` list). The origin list passed to the subscriber's `write` method will contain this object as the last
        entry.

        :param subscriber: The object to subscribe for updates
        :param convert: A callable to convert this object's new value to the data `type` of the subscriber or `True` to
            choose the appropriate conversion function automatically.
        :raises TypeError: If the `type` of the subscriber does not match this object's type and `convert` is False *or*
            if `convert` is True but no type conversion is known to convert this object's type into the subscriber's
            type.
        """
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
        """
        Register a logic handler function to be triggered when this object is updated.

        This method can be used as a decorator for custom logic handler functions. Alternatively, it can simply called
        with a function object: `some_subscribable.trigger(some_handler_function).

        The `target` function must be an async coroutine that takes two arguments: The new value of this object and the
        origin/trace of the event (a list of objects that led to the handler being tiggered). The handler function
        must make sure to prevent infinite recursive feedback loops: In contrast to subscribed objects, logic handler
        functions are also triggered, if they led to the object being updated (i.e. they are already conained in the
        `origin` list). Thus, they should skip execution if called recursively. It should also append itself to the
        `origin` list and pass the extended list to all :meth:`Writable.write` calls it does.

        To ensure all this for a custom handler function, use the :func:`handler` decorator::

            @some_subscribable.trigger
            @handler()
            async def some_handler_function(value, origin):
                ...
                some_writable.write(value + 1)
                ...

        You may even use multiple trigger decorators::

            @some_subscribable.trigger
            @another_subscribable.trigger
            @handler()
            async def some_handler_function(value, origin):
                if origin[-1] is some_subscribable:
                    ...
                else:
                    ...

        :param target: The handler function/coroutine to be triggered on updates. Must comply with the requirements
            mentioned above.
        :return: The `target` function (unchanged)
        """
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
        """
        :meth:`Readable.read`() the current value from the default provider and convert it to this object's type, if
        necessary, using the registered converter function.

        :return: The default provider's current value *or* `None` if no default provider is set or it's `read` method
            raises an UninitializedError.
        """
        if self._default_provider is None:
            return None
        provider, convert = self._default_provider
        try:
            val = await provider.read()
        except UninitializedError:
            return None
        return convert(val) if convert else val


def handler(reset_origin=False, allow_recursion=False) -> Callable[[LogicHandler], LogicHandler]:
    """
    Decorator for custom logic handler functions.

    Wraps a custom logic handler functions to make sure it is suited to be registered to be triggered by a subscribable
    object with :meth:`Subscribable.trigger`. It makes sure that
    * exceptions, occuring during execution, are logged,
    * the `origin` is extended with the logic handler itself and magically passed to all :meth:`Writable.write` calls
    * the `origin` can magically be passed when called directly by other logic handlers
    * the execution is skipped when called recursively (i.e. the logic handler is already contained in the `origin` list

    :param reset_origin: If True, the origin which is magically passed to all `write` calls, only contains the logic
        handler itself, not the previous `origin` list, which led to the handler's execution. This can be used to
        change an object's value, which triggers this logic handler. This may cause infinite recursive feedback loops,
        so use with care!
    :param allow_recursion: If True, recursive execution of the handler is not skipped. The handler must check the
        passed values and/or the `origin` list itself to prevent infinite feedback loops via `write` calls or calls to
        other logic handlers – especiaally when used together with `reset_origin`.
    """
    def decorator(f: LogicHandler) -> LogicHandler:
        @functools.wraps(f)
        async def wrapper(value, origin: Optional[List[Any]] = None) -> None:
            if origin is None:
                try:
                    origin = magicOriginVar.get()
                except LookupError as e:
                    raise ValueError("No origin attribute provided or set via execution context") from e
            if any(wrapper is s for s in origin) and not allow_recursion:
                logger.info("Skipping recursive execution of logic handler %s() via %s", f.__name__, origin)
                return
            logger.info("Triggering logic handler %s() from %s", f.__name__, origin)
            try:
                token = magicOriginVar.set([wrapper] if reset_origin else (origin + [wrapper]))
                await f(value, origin)
                magicOriginVar.reset(token)
            except Exception as e:
                logger.error("Error while executing handler %s():", f.__name__, exc_info=e)
        return wrapper
    return decorator
