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
    type: Type[T] = None

    def connect(self, other: "Connectable",
                send: Optional[bool] = None,
                force_send: bool = False,
                receive: Optional[bool] = None,
                force_receive: bool = False,
                read: Optional[bool] = None,
                provide: Optional[bool] = None,
                convert: bool = False) -> "Connectable":
        self._connect_with(self, other, send, force_send, provide, convert)
        self._connect_with(other, self, receive, force_receive, read, convert)
        return self

    @staticmethod
    def _connect_with(source: "Connectable", target: "Connectable", send: Optional[bool], force_send: bool,
                      provide: Optional[bool], convert: bool):
        if isinstance(source, Subscribable) and isinstance(target, Writable) and (send or send is None):
            source.subscribe(target, force_send, convert=convert)
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


class Writable(Connectable[T], Generic[T], metaclass=abc.ABCMeta):
    async def write(self, value: T, source: Optional[List[Any]] = None):
        if source is None:
            try:
                source = magicSourceVar.get()
            except LookupError as e:
                raise ValueError("No source attribute provided or set via execution context") from e
        if not isinstance(value, self.type):
            raise TypeError("Invalid type for {}: {} is not a {}".format(self, value, self.type.__name__))
        logger.debug("New value %s for %s from %s", value, self, source)
        await self._write(value, source)

    @abc.abstractmethod
    async def _write(self, value: T, source: List[Any]):
        pass


class Readable(Connectable[T], Generic[T], metaclass=abc.ABCMeta):
    @abc.abstractmethod
    async def read(self) -> T:
        pass


class Subscribable(Connectable[T], Generic[T], metaclass=abc.ABCMeta):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._subscribers: List[Tuple[Writable[S], bool, Optional[Callable[[T], S]]]] = []
        self._triggers: List[Tuple[LogicHandler, bool]] = []

    async def __publish_write(self, subscriber: Writable[S], converter: Callable[[T], S], value: T, source: List[Any]):
        try:
            await subscriber.write(converter(value) if converter else value, source + [self])
        except Exception as e:
            logger.error("Error while writing new value %s from %s to %s:", value, self, subscriber, exc_info=e)

    async def __publish_trigger(self, target: LogicHandler, value: T, source: List[Any]):
        try:
            await target(value, source + [self])
        except Exception as e:
            logger.error("Error writing triggering %s from %s:", target, self, exc_info=e)

    async def _publish(self, value: T, source: List[Any], changed: bool = True):
        await asyncio.gather(
            *(self.__publish_write(subscriber, converter, value, source)
              for subscriber, force, converter in self._subscribers
              if (force or changed) and subscriber not in source),
            *(self.__publish_trigger(target, value, source)
              for target, force in self._triggers
              if force or changed)
        )

    def subscribe(self, subscriber: Writable[S], force_publish: bool = False,
                  convert: Union[Callable[[T], S], bool] = False):
        converter: Optional[Callable[[T], S]]
        if convert is True:
            converter = conversion.get_converter(self.type, subscriber.type)
        elif convert is False:
            converter = None
            if subscriber.type is not self.type:
                raise TypeError("Type mismatch of subscriber {}: {} vs {}. You may want to use the `convert` parameter."
                                .format(subscriber, self.type.__name__, subscriber.type.__name__))
        else:
            assert(callable(convert))
            converter = convert
        self._subscribers.append((subscriber, force_publish, converter))

    def trigger(self, target: LogicHandler, force_trigger: bool = False) -> LogicHandler:
        self._triggers.append((target, force_trigger))
        return target


class Reading(Connectable[T], Generic[T], metaclass=abc.ABCMeta):
    is_reading_optional: bool = True

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._default_provider: Optional[Tuple[Readable[S], Optional[Callable[[S], T]]]] = None

    def set_provider(self, provider: Readable[S], convert: Union[Callable[[S], T], bool] = False):
        converter: Optional[Callable[[S], T]]
        if convert is True:
            converter = conversion.get_converter(provider.type, self.type)
        elif convert is False:
            converter = None
            if provider.type is not self.type:
                raise TypeError("Type mismatch of Readable {}: {} vs {}. You may want to use the `convert` parameter."
                                .format(provider, self.type.__name__, provider.type.__name__))
        else:
            assert(callable(convert))
            converter = convert
        self._default_provider = (provider, converter)

    async def _from_provider(self) -> Optional[T]:
        if self._default_provider is not None:
            provider, convert = self._default_provider
            val = await provider.read()
            return convert(val) if convert else val
        return None


def handler(allow_recursion=False) -> Callable[[LogicHandler], LogicHandler]:
    def decorator(f: LogicHandler) -> LogicHandler:
        @functools.wraps(f)
        async def wrapper(value, source) -> None:
            if f in source and not allow_recursion:
                logger.warning("Skipping recursive execution of logic handler %s() via %s", f.__name__, source)
                return
            logger.info("Triggering logic handler %s() from %s", f.__name__, source)
            try:
                token = magicSourceVar.set(source + [f])
                await f(value, source)
                magicSourceVar.reset(token)
            except Exception as e:
                logger.error("Error while executing handler %s():", f.__name__, exc_info=e)
        return wrapper
    return decorator
