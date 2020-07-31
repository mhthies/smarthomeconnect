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


class Writable(Generic[T], metaclass=abc.ABCMeta):
    type: Type[T] = None

    @abc.abstractmethod
    async def write(self, value: T, source: List[Any]):
        pass


class Readable(Generic[T], metaclass=abc.ABCMeta):
    type: Type[T] = None

    @abc.abstractmethod
    async def read(self) -> T:
        pass


class Subscribable(Generic[T]):
    type: Type[T] = None

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._subscribers: List[Tuple[Writable[S], bool, Optional[Callable[[T], S]]]] = []
        self._triggers: List[Tuple[LogicHandler, bool]] = []

    async def _publish(self, value: T, source: List[Any], changed: bool = True):
        await asyncio.gather(
            *(subscriber.write(convert(value) if convert else value, source + [self])
              for subscriber, force, convert in self._subscribers
              if force or changed),
            *(target(value, source + [self])
              for target, force in self._triggers
              if force or changed)
        )

    def subscribe(self, subscriber: Writable[S], force_publish: bool = False,
                  convert: Union[Callable[[T], S], bool] = False):
        if convert is True:
            convert = conversion.get_converter(self.type, subscriber.type)
        elif convert is False:
            convert = None
            if subscriber.type is not self.type:
                raise TypeError("Type mismatch of subscriber {}: {} vs {}. You may want to use the `convert` parameter."
                                .format(subscriber, self.type.__name__, subscriber.type.__name__))
        self._subscribers.append((subscriber, force_publish, convert))

    def trigger(self, target: LogicHandler, force_trigger: bool = False) -> LogicHandler:
        self._triggers.append((target, force_trigger))
        return target


class Reading(Generic[T]):
    type: Type[T] = None

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._default_provider = Optional[Tuple[Readable[S], Optional[Callable[[S], T]]]]

    def set_provider(self, provider: Readable[S], convert: Union[Callable[[S], T], bool] = False):
        if convert is True:
            convert = conversion.get_converter(self.type, provider.type)
        elif convert is False:
            convert = None
            if provider.type is not self.type:
                raise TypeError("Type mismatch of Readable {}: {} vs {}. You may want to use the `convert` parameter."
                                .format(provider, self.type.__name__, provider.type.__name__))
        self._default_provider = (provider, convert)

    async def _from_provider(self) -> Optional[T]:
        if self._default_provider is not None:
            provider, convert = self._default_provider
            val = await provider.read()
            return convert(val) if convert else val
        return None


class Variable(Writable[T], Readable[T], Subscribable[T], Generic[T], metaclass=abc.ABCMeta):
    def __init__(self, type_: Type[T], initial_value: Optional[T] = None):
        self.type = type_
        super().__init__()
        self._value = initial_value if initial_value is not None else self.type()

    async def write(self, value: T, source: Optional[List[Any]] = None) -> None:
        if source is None:
            try:
                source = magicSourceVar.get()
            except LookupError as e:
                raise ValueError("No source attribute provided or set via execution context") from e
        logger.debug("New Variable value %s from %s", value, source)
        if self in source:
            logger.warning("Skipping update_from_bus of Variable %s to %s due to recursive event propagation: %s",
                           self, value, source)
            return
        changed = value != self._value
        self._value = value
        await self._publish(value, source, changed)

    async def read(self) -> T:
        return self._value

    def connect(self, other, send: bool = True, force_send: bool = False, receive: bool = True,
                force_receive: bool = False, init: bool = False, provide: bool = False,
                convert: bool = False) -> "Variable":
        if isinstance(other, Writable) and send:
            self.subscribe(other, force_send, convert=convert)
        if isinstance(other, Subscribable) and receive:
            other.subscribe(self, force_receive, convert=convert)
        if isinstance(other, Reading) and provide:
            other.set_provider(self, convert=convert)
        return self


def handler(f: LogicHandler) -> LogicHandler:
    @functools.wraps(f)
    async def wrapper(value, source) -> None:
        logger.debug("Triggering logic handler %s() from %s", f.__name__, source)
        try:
            token = magicSourceVar.set(source + [f])
            await f(value, source)
            magicSourceVar.reset(token)
        except Exception as e:
            logger.error("Error while executing handler %s():", f.__name__, exc_info=e)
    return wrapper
