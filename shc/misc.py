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

import datetime
from typing import Generic, Type, List, Any

from shc.base import Readable, Subscribable, Writable, handler, T, ConnectableWrapper
from shc.timer import Every

"""
This module contains some helper/adapter classes to support special patterns of interconnection of :class:`Connectable`
objects.   
"""


class PeriodicReader(Readable[T], Subscribable[T], Generic[T]):
    """
    Wraps a :class:`Readable` object to turn it into :class:`Subscribable` object by periodically reading and publishing
    its value.
    """
    def __init__(self, wrapped: Readable[T], interval: datetime.timedelta):
        self.type = wrapped.type
        super().__init__()
        self.wrapped = wrapped
        self.timer = Every(interval)
        self.timer.trigger(self.do_read)

    async def read(self) -> T:
        return await self.wrapped.read()

    async def do_read(self, _value, origin) -> None:
        # We add the wrapped Readable object to the `origin` list to avoid publishing back its own value, in case it is
        # subscribed to one of our subscribers (e.g. a variable).
        await self._publish(await self.wrapped.read(), origin + [self.wrapped])


class TwoWayPipe(ConnectableWrapper[T], Generic[T]):
    """
    A helper to connect two sets of Writable+Subscribable objects, without connecting the objects within each set. This
    object can be thought of as a bidirectional pipe: All write-events send to the left end of the pipe are forwarded to
    all objects on the right side and vice versa. This can be especially useful to connect a variable to multiple
    addresses of a home automation bus (like a KNX bus) without all mirroring incoming values on one address (e.g. a
    central or feedback datapoint) to the other addresses.

    To connect objects to one side of the pipe, use :meth:`connect_left` resp. :meth:`connect_right`. The additional
    method :meth:`connect` is an alias for `connect_left` to allow using a `TwoWayPipe` object as an argument for
    :meth:`Connectable.connect` itself with the result of connecting the pipe's left end to the object.

    The following example demonstrates, how to connect two interface connectors to a Variable, such that the Variable
    will interact with both of them, without forwarding events/values from one connector to the other::

        shc.Variable(bool)\
            .connect(TwoWayPipe(bool)
                .connect_right(some_interface.connector(1))
                .connect_right(some_interface.connector(2)))
    """
    def __init__(self, type_: Type[T]):
        self.type = type_
        self.left = _PipeEnd(type_)
        self.right = _PipeEnd(type_)
        self.left.other_end = self.right
        self.right.other_end = self.left

    def connect_right(self, *args, **kwargs) -> "TwoWayPipe":
        self.right.connect(*args, **kwargs)
        return self

    def connect_left(self, *args, **kwargs) -> "TwoWayPipe":
        self.left.connect(*args, **kwargs)
        return self

    def connect(self, *args, **kwargs) -> "TwoWayPipe":
        self.left.connect(*args, **kwargs)
        return self


class _PipeEnd(Subscribable[T], Writable[T], Generic[T]):
    def __init__(self, type_: Type[T]):
        self.type = type_
        super().__init__()
        self.other_end: "_PipeEnd" = None  # type: ignore

    async def _write(self, value: T, origin: List[Any]):
        await self.other_end._publish(value, origin)
