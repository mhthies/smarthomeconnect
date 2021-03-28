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
import itertools
import logging
from typing import Generic, List, Any, Tuple, Callable, Optional, Type, TypeVar, Awaitable, Union, Set, Iterable

from . import conversion

S = TypeVar('S')
T = TypeVar('T')
LogicHandler = Callable[[T, List[Any]], Awaitable[None]]

logger = logging.getLogger(__name__)

magicOriginVar: contextvars.ContextVar[List[Any]] = contextvars.ContextVar('shc_origin')

C = TypeVar('C', bound="Connectable")


class HasSharedLock:
    """
    Mutex mechanism for serializing value updates of *connected* stateful objects.

    Each `Writable` object which requires a mutex for serializing value updates, should inherit from this mixin class,
    providing an inner Lock, which is *shared* with other `HasSharedLock` objects it is subscribed to. The sharing of
    of the locks is typically ensured by :meth:`Subscribable.subscribe`, which uses :meth:`share_lock_with` to share the
    locks. Sharing means, that the `HasSharedLock` objects use the same :class:`_SharedLockInner` instance, i.e. they
    interlock against each other by acquiring the same internal Lock/mutex.

    To avoid deadlocks, the shared `_SharedLockInner` object stores a reference to the `HasSharedLock` object currently
    locking the mutex. When acquiring the lock, a list of objects to ignore as lockers can be passed. If the object
    which currently hodls the lock is in this list, the :meth:`acquire_lock` method returns without actually acquiring the
    lock. Typically, the `origin` list should be passed.
    """

    class _SharedLockInner:
        def __init__(self) -> None:
            self.lock = asyncio.Lock()
            self.shared_with: Set["HasSharedLock"] = set()
            self.locked_by: object = None

    def __init__(self):
        super().__init__()
        self._shared_lock = self._SharedLockInner()
        self._shared_lock.shared_with.add(self)

    async def acquire_lock(self, exclusion: Iterable[object] = ()) -> bool:
        """
        Acquires the lock, if the lock is not locked by an object contained in `exclusion`.

        If the lock is currently locked by an object, other than those in the `exclusion` list, this method awaits the
        release of the lock by the other Task. If the Lock is locked/acquired by an object contained in `exclusion`, the
        method returns immediately.

        :param exclusion: A list of objects
        :return: True, if the lock has acutally been required, False if it has been ignored, esp. if currently locked
            by one of the objects in `exclusion`
        """
        if self._shared_lock.lock.locked() and self._shared_lock.locked_by in exclusion:
            return False
        res = await self._shared_lock.lock.acquire()
        self._shared_lock.locked_by = self
        return res

    def release_lock(self) -> None:
        """
        Release the lock if it is acquired by the current task.
        """
        try:
            if self._shared_lock.locked_by is self:
                self._shared_lock.lock.release()
        except RuntimeError:
            pass

    def _share_lock_with(self, other: "HasSharedLock") -> None:
        """
        Share the inner lock with another HasSharedLock object.

        This method shares the :class:`_SharedLockInner` instance of this object, including the actual mutex, with
        `other`. The inner mutex of `other` is dropped. If `other` has already
        been shared with more `SharedLock` instances, the reference to the `_SharedLockInner` object is also copied to
        all of these instances, such that all of them share the same mutex, independent from the order and direction of
        `_share_lock_with` calls.

        :param other: The other `SharedLock` instance to share the internal mutex with.
        """
        old_set = other._shared_lock.shared_with
        self._shared_lock.shared_with.update(old_set)
        for s in old_set:
            s._shared_lock = self._shared_lock


class Connectable(Generic[T], metaclass=abc.ABCMeta):
    """
    :cvar type: The type of the values, this object is supposed to handle
    """
    type: Type[T]

    def connect(self: C, other: "Connectable",
                send: Optional[bool] = None,
                receive: Optional[bool] = None,
                read: Optional[bool] = None,
                provide: Optional[bool] = None,
                convert: Union[bool, Tuple[Callable[[T], Any], Callable[[Any], T]]] = False,
                send_sync: bool = True,
                receive_sync: bool = True) -> C:
        if isinstance(other, ConnectableWrapper):
            # If other object is not connectable itself but wraps one or more connectable objects (like, for example, a
            # `web.widgets.ValueButtonGroup`), let it use its special implementation of `connect()`.
            other.connect(self, send=receive, receive=send, read=provide, provide=read,
                          convert=((convert[1], convert[0]) if isinstance(convert, tuple) else convert))
        else:
            self._connect_with(self, other, send, provide, convert[0] if isinstance(convert, tuple) else convert,
                               send_sync)
            self._connect_with(other, self, receive, read, convert[1] if isinstance(convert, tuple) else convert,
                               receive_sync)
        return self

    @staticmethod
    def _connect_with(source: "Connectable", target: "Connectable", send: Optional[bool], provide: Optional[bool],
                      convert: Union[bool, Callable], send_sync: bool):
        if isinstance(source, Subscribable) and isinstance(target, Writable) and (send or send is None):
            source.subscribe(target, convert=convert, sync=send_sync)
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


class Writable(Connectable[T], Generic[T], metaclass=abc.ABCMeta):
    def __init__(self):
        super().__init__()

    async def write(self, value: T, origin: Optional[List[Any]] = None) -> None:
        """
        Asynchronous coroutine to update the object with a new value

        This method calls :meth:`_write` internally for the actual implementation-specific update logic. Inheriting
        classes should override *_write* instead of this method to keep profiting from the value type checking and
        magic context-based origin passing features.

        This method typically awaits the complete transmission of the new value to all targets. Depending in the
        internal functionality of the `Writable` this might include awaiting the `write` coroutine of multiple other
        (synchronously subscribed)
        `Writable` objects, which, in turn, might even await a successful network transmission of the value, and so on.

        This way, you can be sure that the value has been delivered to the target system (as far as SHC can track it)
        when the `write` coroutine returns, as long as all relevant subscriptions are synchronous (see
        :ref:`base.synchronous_subscriptions`). On the other hand, to keep your control flow independent from (probably
        lagging) transmission of values, you should call `write` in a new :class:`asyncio.Task`. For `writing` a value
        to multiple objects in parallel, you might consider :func:`asyncio.gather`.

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
    async def _write(self, value: T, origin: List[Any]) -> None:
        """
        Abstract internal method containing the actual implementation-specific write-logic.

        It must be overridden by classes inheriting from :class:`Writable` to be updated with new values. The *_write*
        implementation does not need to check the new value's type.

        :param value: The new value to update this object with
        :param origin: The origin / trace of the value update event. Should be passed to :meth:`Subscribable._publish`
            if the implementing class is *Subscribable* and re-publishes new values.
        """
        pass


class Readable(Connectable[T], Generic[T], metaclass=abc.ABCMeta):
    @abc.abstractmethod
    async def read(self) -> T:
        pass


class UninitializedError(RuntimeError):
    pass


class PublishError(RuntimeError):
    """
    Exception which is raised by :meth:`Subscribable._publish` when one or more Exceptions occurred while publishing the
    value update to synchronous subscribers and logic handlers.

    The original exceptions are collected in the ``errors`` attribute. This includes Exceptions from subsequent
    recursive synchronous publishing calls (e.g. when *writing* to a variable, which in turn publishes to an external
    interface, which raises an Exception). To determine the original source of the Exception(s), the source and target
    object where they occured is stored in the ``errors`` attribute along with the Exception.

    :ivar errors: A list of all Exceptions that occurred during the publishing. Each entry is a tuple
        (exception, source, target), where `source` is the *Subscribable* object which published to the `target`
        (*Writable* object or logic Handler function), when the Exception occured.
    """
    def __init__(self, message: str = '',
                 errors: List[Tuple[Exception, "Subscribable", Union["Writable", "LogicHandler"]]] = None):
        super().__init__(message)
        self.errors = errors or []

    def __str__(self) -> str:
        return super().__str__() + ', '.join(f"({source} -> {target}: {str(e)})"
                                             for e, source, target in self.errors)


class Subscribable(Connectable[T], Generic[T], metaclass=abc.ABCMeta):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._subscribers: List[Tuple[Writable[S], Optional[Callable[[T], S]], bool]] = []
        self._triggers: List[Tuple[LogicHandler, bool]] = []

    async def __publish_write(self, subscriber: Writable[S], converter: Optional[Callable[[T], S]], value: T,
                              origin: List[Any], raise_exc: bool):
        try:
            await subscriber.write(converter(value) if converter else value, origin)  # type: ignore
        except PublishError as e:
            if raise_exc:
                raise
            else:
                # We expect the error to be logged already (see below)
                logger.info("Publishing error is being dropped while publishing from %s to %s", subscriber, self,
                            exc_info=e)
        except Exception as e:
            logger.error("Error while writing new value %s from %s to %s:", value, self, subscriber, exc_info=e)
            if raise_exc:
                raise PublishError(errors=[(e, self, subscriber)]) from e

    async def __publish_trigger(self, target: LogicHandler, value: T, origin: List[Any], raise_exc: bool):
        try:
            await target(value, origin)
        except PublishError as e:
            if raise_exc:
                raise
            else:
                # We expect the error to be logged already (see below)
                logger.info("Publishing error is being dropped while triggering from %s to %s", target, self,
                            exc_info=e)
        except Exception as e:
            logger.error("Error while triggering %s from %s:", target, self, exc_info=e)
            if raise_exc:
                raise PublishError(errors=[(e, self, target)]) from e

    async def _publish(self, value: T, origin: List[Any]):
        """
        Coroutine to publish a new value to all subscribers and trigger all registered logic handlers.

        All logic handlers and :meth:`Writable.write` methods are called in parallel asyncio tasks. However, this
        method awaits the return of all *synchronous* subscribers/triggers (see :ref:`base.synchronous_subscriptions`).
        Thus, when implementing an external interface, which should be capable
        of processing multiple incoming values in parallel, you should `_publish()` each incoming new value in a
        separate asyncio Task. See also :meth:`Writable.write`.

        :param value: The new value to be published by this object. Must be an instance of this object's `type`.
        :param origin: The origin list of the new value, **excluding** this object. See :ref:`base.event-origin` for
            more details.`self` is appended automatically before calling the registered subscribers and logic handlers.
        :raises PublishError: If an Exception occurred while publishing the value to any of the synchronous subscribers
            or triggering any of the synchronously triggered logic handlers.
        """
        if not self._subscribers and not self._triggers:
            return
        coro_sync = []
        coro_async = []
        new_origin = origin + [self]
        for subscriber, converter, sync in self._subscribers:
            if not any(subscriber is s for s in origin):
                if sync:
                    coro_sync.append(self.__publish_write(subscriber, converter, value, new_origin, True))
                else:
                    coro_async.append(self.__publish_write(subscriber, converter, value, new_origin, False))
        for target, sync in self._triggers:
            if sync:
                coro_sync.append(self.__publish_trigger(target, value, new_origin, True))
            else:
                coro_async.append(self.__publish_trigger(target, value, new_origin, False))

        for coro in coro_async:
            asyncio.create_task(coro)

        if len(coro_sync) == 1:
            await coro_sync[0]
        else:
            results = await asyncio.gather(*coro_sync, return_exceptions=True)
            exceptions: List[PublishError] = [res for res in results if isinstance(res, PublishError)]
            if exceptions:
                raise PublishError(errors=list(itertools.chain.from_iterable((e.errors for e in exceptions))))

    def share_lock_with_subscriber(self, subscriber: HasSharedLock) -> None:
        """
        Connect/Share the shared locking mechanism of this Subscribable object (if it has one) with the one of the given
        subscriber (which is required to have one).

        This is mandatory for all synchronous subscriptions to ensure that each "network" of synchronously connected
        are locked mutually, such that race conditions and deadlocks are avoided. Thus, this method is automatically
        called by :meth:`subscribe` for synchronous subscriptions of subscribers, which have a shared lock, i.e. inherit
        from :class:`HasSharedLock`. When using :meth:`trigger` to synchronously call a locking method of a
        `HasSharedLock` object, you **must** call `share_lock_with_subscriber()` manually for this object.

        Subscribable objects that synchronously republish value updates from other Subscribable objects need to make
        sure that all subscribers (also) share their locks with those objects. This can be achieved by either

          * inheriting from :class:`HasSharedLock` and subscribing to those objects (or calling
            ``share_lock_with_subscriber(self)`` on them) or
          * overriding `share_lock_with_subscriber()` such that it calls ``share_lock_with_subscriber(subscriber)`` on
            all of those objects.

        :param subscriber: The subscriber which shall share its lock with this object. Must be inheriting from
            `HasSharedLock`.
        """
        if isinstance(self, HasSharedLock):
            self._share_lock_with(subscriber)

    def subscribe(self, subscriber: Writable[S], convert: Union[Callable[[T], S], bool] = False, sync=True) -> None:
        """
        Subscribe a writable object to this object to be updated, when this object publishes a new value.

        The subscriber's :meth:`Writable.write` method will be called for any new value published by this object, as
        long as the subscriber did not lead to the relevant update of this object (i.e. is not included in the
        `origin` list). The origin list passed to the subscriber's `write` method will contain this object as the last
        entry.

        :param subscriber: The object to subscribe for updates
        :param convert: A callable to convert this object's new value to the data ``type`` of the subscriber or ``True``
            to choose the appropriate conversion function automatically.
        :param sync: If True (default), when publishing a value update, this *Subscribable* object will wait for the
            the subscriber's `write()` method to complete. See :ref:`base.synchronous_subscriptions` for more
            information.
        :raises TypeError: If the `type` of the subscriber does not match this object's type and ``convert`` is False
            *or* if ``convert`` is True but no type conversion is known to convert this object's type into the
            subscriber's type.
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
        self._subscribers.append((subscriber, converter, sync))
        if sync and isinstance(subscriber, HasSharedLock):
            self.share_lock_with_subscriber(subscriber)

    def trigger(self, target: LogicHandler, sync=False) -> LogicHandler:
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
        :param sync: If True, when publishing a value update, this *Subscribable* object will wait for the
            the ``target`` coroutine to return. See :ref:`base.synchronous_subscriptions` for more
            information. Defaults to False.
        :return: The ``target`` function (unchanged)
        """
        self._triggers.append((target, sync))
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
