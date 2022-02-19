# Copyright 2020-2021 Michael Thies <mail@mhthies.de>
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
from typing import Generic, List, Any, Tuple, Callable, Optional, Type, TypeVar, Awaitable, Union, Dict, Set

from . import conversion

S = TypeVar('S')
T = TypeVar('T')
T_co = TypeVar('T_co')
T_con = TypeVar('T_con')
LogicHandler = Callable[[T, List[Any]], Awaitable[None]]

logger = logging.getLogger(__name__)

magicOriginVar: contextvars.ContextVar[List[Any]] = contextvars.ContextVar('shc_origin')

C = TypeVar('C', bound="Connectable")


class Connectable(Generic[T], metaclass=abc.ABCMeta):
    """
    :cvar type: The type of the values, this object is supposed to handle
    """
    type: Type[T]

    def connect(self: C, other: "Connectable[S]",
                send: Optional[bool] = None,
                receive: Optional[bool] = None,
                read: Optional[bool] = None,
                provide: Optional[bool] = None,
                convert: Union[bool, Tuple[Callable[[T], S], Callable[[S], T]]] = False) -> C:
        """
        Subscribe self to other and set as default_provider and vice versa (depending on the two object's capabilities,
        optionalities and given parameters).

        :param other: The other *Connectable* object to connect with
        :param send: Send value updates to `other` (i.e. subscribe `other` to `self`).
            Requires `self` to be :class:`Subscribable` and other to be :class:`Writable`. In this case, defaults to
            True if not specified.
        :param receive: Receive value updates from `other` (i.e. subscribe `self` to `other`).
            Requires `self` to be :class:`Writable` and other to be :class:`Subscribable`. In this case, defaults to
            True if not specified.
        :param read: Read values from `other` (i.e. set `other` as default provider for `self`).
            Requires `self` to be :class:`Reading` and `other` to be :class:`Readable`.
            If not specified, defaults to False unless `self.is_reading_optional` is set to False.
        :param provide: Provide values to `other` for reading (i.e. set `self` as default provider for `other`).
            Requires `self` to be :class:`Readable` and `other` to be :class:`Reading`.
            If not specified, defaults to False unless `other.is_reading_optional` is set to False.
        :param convert: Enable built-in type conversion for the created subscriptions/default_providers:
            Either a boolean or a tuple of two conversion functions. Defaults to ``False``, i.e. a type mismatch will
            result in a TypeError instead of implicit conversion. Set to ``True``, to choose the appropriate
            conversion function automatically. Raises a TypeError if no default conversion for one of the two directions
            is available and that direction is used.
            For custom conversion functions, pass a tuple ``(to_other, to_self)``, where ``to_other`` is a (non-async)
            callable for converting `self`'s value type into `other`'s value type and ``to_self`` does the conversion
            the other way round.
        :return: Returns self to allow functional-style chaining
        """
        if isinstance(other, ConnectableWrapper):
            # If other object is not connectable itself but wraps one or more connectable objects (like, for example, a
            # `web.widgets.ValueButtonGroup`), let it use its special implementation of `connect()`.
            other.connect(self, send=receive, receive=send, read=provide, provide=read,
                          convert=((convert[1], convert[0]) if isinstance(convert, tuple) else convert))
        else:
            self._connect_with(self, other, send, provide, convert[0] if isinstance(convert, tuple) else convert)
            self._connect_with(other, self, receive, read, convert[1] if isinstance(convert, tuple) else convert)
        return self

    @staticmethod
    def _connect_with(source: "Connectable", target: "Connectable", send: Optional[bool], provide: Optional[bool],
                      convert: Union[bool, Callable]):
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
    def connect(self: C, other: "Connectable",
                send: Optional[bool] = None,
                receive: Optional[bool] = None,
                read: Optional[bool] = None,
                provide: Optional[bool] = None,
                convert: Union[bool, Tuple[Callable[[T], Any], Callable[[Any], T]]] = False) -> C:
        pass


class Writable(Connectable[T_con], Generic[T_con], metaclass=abc.ABCMeta):
    async def write(self, value: T_con, origin: Optional[List[Any]] = None) -> None:
        """
        Asynchronous coroutine to update the object with a new value

        This method calls :meth:`_write` internally for the actual implementation-specific update logic. Inheriting
        classes should override *_write* instead of this method to keep profiting from the value type checking and
        magic context-based origin passing features.

        This method awaits the complete transmission and processing of the new value by the next stateful
        object/system, e.g. storing and re-publishing the value on a Variable, publishing the value from an MQTT
        broker on an MQTT client connector, forwarding the value to all subscribers on an Expression.

        :param value: The new value
        :param origin: The origin / trace of the value update event, i.e. the list of objects/functions which have been
            publishing to/calling one another to cause this value update. It is used to avoid recursive feedback loops
            and may be used for origin-specific handling of the value. The last entry of the list should be the
            object/function calling this method.
        :raises TypeError: If the value's type does not match the the object's ``type`` attribute.
        """
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
    async def _write(self, value: T_con, origin: List[Any]) -> None:
        """
        Abstract internal method containing the actual implementation-specific write-logic.

        It must be overridden by classes inheriting from :class:`Writable` to be updated with new values. The *_write*
        implementation does not need to check the new value's type.

        Please make sure that your `_write` implementation awaits the processing of the value update by the next
        stateful object/system before returning:

        - On a Variable and similar stateful re-publishing objects, which use `_stateful_publishing = True`, await the
          storing and `_publish()`-ing of the new value
        - On an Expression and similar stateless re-publishing objects, use `_publish_and_wait()` instead of
          `_publish()` and await its return
        - On external interface connectors (e.g. MQTT connector) await (at least) the successful processing of the value
          by the external system

        This is required to make the state inconsistency mitigation method of :class:`Subscribable` objects work.

        :param value: The new value to update this object with
        :param origin: The origin / trace of the value update event. Should be passed to :meth:`Subscribable._publish`
            if the implementing class is *Subscribable* and re-publishes new values.
        """
        pass


class Readable(Connectable[T_co], Generic[T_co], metaclass=abc.ABCMeta):
    @abc.abstractmethod
    async def read(self) -> T_co:
        """
        Get the current value of this Connectable object.

        :raises UninitializedError: If the value is not (yet) specified
        """
        pass


class UninitializedError(RuntimeError):
    pass


SubscriberListType = Tuple[Writable[S], Optional[Callable[[T_co], S]]]


class Subscribable(Connectable[T_co], Generic[T_co], metaclass=abc.ABCMeta):
    _stateful_publishing: bool = False

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._subscribers: List[SubscriberListType] = []
        self._triggers: List[Tuple[LogicHandler, bool]] = []
        self._pending_updates: Dict[int, Dict[asyncio.Task, Optional[int]]] = {}

    async def __publish_write(self, subscriber: Writable[S], converter: Optional[Callable[[T_co], S]], value: T_co,
                              origin: List[Any], use_pending: bool):
        try:
            await subscriber.write(converter(value) if converter else value, origin + [self])  # type: ignore
        except Exception as e:
            logger.error("Error while writing new value %s from %s to %s:", value, self, subscriber, exc_info=e)
        finally:
            if use_pending:
                del self._pending_updates[id(subscriber)][asyncio.current_task()]  # type: ignore

    async def __publish_trigger(self, target: LogicHandler, value: T_co,
                                origin: List[Any], use_pending: bool):
        try:
            await target(value, origin + [self])
        except Exception as e:
            logger.error("Error while triggering %s from %s:", target, self, exc_info=e)
        finally:
            if use_pending:
                del self._pending_updates[id(target)][asyncio.current_task()]  # type: ignore

    def _publish(self, value: T_co, origin: List[Any]):
        """
        Method to publish a new value to all subscribers and trigger all registered logic handlers.

        All logic handlers and :meth:`Writable.write` methods are called in parallel asyncio tasks, which are **not**
        awaited to return. If `_stateful_publishing` is True on this object (or class), it will keep track of the
        currently pending publishing tasks. This information is then used to mitigate state inconsistencies, caused by
        value updates crossing over each other, by resetting the `origin` of following value updates to the respected
        subscribers.

        `_stateful_publishing` should be enabled for all objects that are *Subscribable* and *Writable* (i.e. allows
        sending and receiving value updates) and have either internal state (like Variables) or represent an external,
        stateful (or quasi-stateful) system (like a Connector object for a KNX group address/an MQTT topic). On the
        other hand, objects, that are only *Subscribable*, should not use `_stateful_publishing`.

        If the object only forwards value updates without storing a state, it should await the successful publishing of
        the value by using the :meth:`_publish_and_wait` coroutine.

        :param value: The new value to be published by this object. Must be an instance of this object's `type`.
        :param origin: The origin list of the new value, **excluding** this object. See :ref:`base.event-origin` for
            more details.`self` is appended automatically before calling the registered subscribers and logic handlers.
        """
        if self._stateful_publishing:
            for subscriber, converter in self._subscribers:
                prev_step = id(origin[-1]) if origin else None
                reset_origin = any(o != prev_step for o in self._pending_updates[id(subscriber)].values())
                if reset_origin:
                    logger.info("Resetting origin from %s to %s; value=%s; origin=%s", self, subscriber, value, origin)
                if reset_origin or not any(s is subscriber for s in origin):
                    task = asyncio.create_task(self.__publish_write(subscriber, converter, value,
                                                                    [] if reset_origin else origin, True))
                    self._pending_updates[id(subscriber)][task] = prev_step
            for target, sync in self._triggers:
                reset_origin = False
                if sync:
                    prev_step = id(origin[-1]) if origin else None
                    reset_origin = any(o != prev_step for o in self._pending_updates[id(target)].values())
                task = asyncio.create_task(self.__publish_trigger(target, value, [] if reset_origin else origin, sync))
                if sync:
                    self._pending_updates[id(target)][task] = prev_step

        else:
            for target, sync in self._triggers:
                asyncio.create_task(self.__publish_trigger(target, value, origin, False))
            for subscriber, converter in self._subscribers:
                if not any(s is subscriber for s in origin):
                    asyncio.create_task(self.__publish_write(subscriber, converter, value, origin, False))

    async def _publish_and_wait(self, value: T_co, origin: List[Any]):
        """
        A coroutine to publish a new value to all subscribers and trigger all registered logic handlers and wait for
        this publishing to finish.

        All logic handlers and :meth:`Writable.write` methods are called in parallel asyncio tasks. However, this
        method awaits the return of *all* them. This should only be used for **stateless** objects that re-publish
        incoming value updates (like :ref:`Expressions <expressions>`, :class:`shc.misc.TwoWayPipe`, etc.). Other
        objects should use :meth:`_publish` instead.

        :param value: The new value to be published by this object. Must be an instance of this object's `type`.
        :param origin: The origin list of the new value, **excluding** this object. See :ref:`base.event-origin` for
            more details.`self` is appended automatically before calling the registered subscribers and logic handlers.
        """
        for target, sync in self._triggers:
            if not sync:
                asyncio.create_task(self.__publish_trigger(target, value, origin, False))
        sync_jobs = [self.__publish_write(subscriber, converter, value, origin, False)
                     for subscriber, converter in self._subscribers
                     if not any(s is subscriber for s in origin)]
        sync_jobs.extend(
            self.__publish_trigger(target, value, origin, False)
            for target, sync in self._triggers
            if sync)
        if len(sync_jobs) == 1:
            await sync_jobs[0]
        elif sync_jobs:
            await asyncio.gather(*sync_jobs)

    def subscribe(self, subscriber: Writable[S], convert: Union[Callable[[T_co], S], bool] = False) -> None:
        """
        Subscribe a writable object to this object to be updated, when this object publishes a new value.

        The subscriber's :meth:`Writable.write` method will be called for any new value published by this object, as
        long as the subscriber did not lead to the relevant update of this object (i.e. is not included in the
        `origin` list). The origin list passed to the subscriber's `write` method will contain this object as the last
        entry.

        :param subscriber: The object to subscribe for updates
        :param convert: A callable to convert this object's new value to the data ``type`` of the subscriber or ``True``
            to choose the appropriate conversion function automatically.
        :raises TypeError: If the `type` of the subscriber does not match this object's type and ``convert`` is False
            *or* if ``convert`` is True but no type conversion is known to convert this object's type into the
            subscriber's type.
        """
        converter: Optional[Callable[[T_co], S]]
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
        if self._stateful_publishing:
            self._pending_updates[id(subscriber)] = {}

    def trigger(self, target: LogicHandler, synchronous: bool = False) -> LogicHandler:
        """
        Register a logic handler function to be triggered when this object is updated.

        This method can be used as a decorator for custom logic handler functions. Alternatively, it can simply called
        with a function object: ``some_subscribable.trigger(some_handler_function)``.

        The `target` function must be an async coroutine that takes two arguments: The new value of this object and the
        origin/trace of the event (a list of objects that led to the handler being tiggered). The handler function
        must make sure to prevent infinite recursive feedback loops: In contrast to subscribed objects, logic handler
        functions are also triggered, if they led to the object being updated (i.e. they are already conained in the
        ``origin`` list). Thus, they should skip execution if called recursively. It should also append itself to the
        ``origin`` list and pass the extended list to all :meth:`Writable.write` calls it does.

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
        :param synchronous: If True, the target coroutine is triggered synchronously, i.e. :meth:`_publish_and_wait`
            will wait for it to return. This SHALL be used for internal triggering methods that re-publish the value
            updates of this Subscribable object. For logic handlers that might require substantial time to return, it
            SHALL not be used!
        :return: The ``target`` function (unchanged) – this allows decorator-style usage of this method
        """
        self._triggers.append((target, synchronous))
        if synchronous and self._stateful_publishing:
            self._pending_updates[id(target)] = {}
        return target


DefaultProviderType = Tuple[Readable[S], Optional[Callable[[S], T_con]]]


class Reading(Connectable[T_con], Generic[T_con], metaclass=abc.ABCMeta):
    is_reading_optional: bool = True

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._default_provider: Optional[DefaultProviderType] = None

    def set_provider(self, provider: Readable[S], convert: Union[Callable[[S], T_con], bool] = False):
        converter: Optional[Callable[[S], T_con]]
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

    async def _from_provider(self) -> Optional[T_con]:
        """
        Private method to be used by inheriting classes to read the current value from this object's default provider
        (via its :meth:`Readable.read` method) and convert it to this object's type, if necessary, using the registered
        converter function.

        :return: The default provider's current value *or* ``None`` if no default provider is set or it's *read* method
            raises an :class:`UninitializedError`.
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

    Wraps a custom logic handler functions to make sure it is suited to be registered for triggering by a subscribable
    object with :meth:`Subscribable.trigger`. It makes sure that

    * exceptions, occurring execution, are logged,
    * the `origin` is extended with the logic handler itself and magically passed to all :meth:`Writable.write` calls
    * the `origin` can magically be passed when called directly by other logic handlers
    * the execution is skipped when called recursively (i.e. the logic handler is already contained in the `origin` list

    :param reset_origin: If True, the origin which is magically passed to all `write` calls, only contains the logic
        handler itself, not the previous `origin` list, which led to the handler's execution. This can be used to
        change an object's value, which triggered this logic handler. This may cause infinite recursive feedback loops,
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
            if any(s is wrapper for s in origin) and not allow_recursion:
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


def blocking_handler() -> Callable[[Callable[[T, List[Any]], None]], LogicHandler]:
    """
    Decorator for custom blocking (non-async) logic handler functions.

    Wraps a function to transform it into an async logic handler function, which is suited to be registered for
    triggering by a subscribable object with :meth:`Subscribable.trigger`. The wrapped function is executed in a
    separate thread, using asyncio's `run_in_executor()`.

    Like :func:`handler`, this decorator catches and logs errors and ensures that the `origin` can magically be passed
    when called directly by other logic handlers. However, since the wrapped function is not an asynchronous coroutine,
    it is not able to call :meth:`Writable.write` or another logic handler directly. Thus, this decorator does not
    include special measures for preparing and passing the `origin` list or avoiding recursive execution.
    """
    def decorator(f: Callable[[T, List[Any]], None]) -> LogicHandler:
        @functools.wraps(f)
        async def wrapper(value, origin: Optional[List[Any]] = None) -> None:
            if origin is None:
                try:
                    origin = magicOriginVar.get()
                except LookupError as e:
                    raise ValueError("No origin attribute provided or set via execution context") from e
            logger.info("Triggering blocking logic handler %s() from %s", f.__name__, origin)
            try:
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(None, f, value, origin)
            except Exception as e:
                logger.error("Error while executing handler %s():", f.__name__, exc_info=e)
        return wrapper
    return decorator
