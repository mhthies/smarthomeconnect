import enum
import json
from typing import Any, Type, Union, Iterable

from . import WebPageItem, WebDisplayDatapoint, WebActionDatapoint, jinja_env
from ..base import T


class Switch(WebDisplayDatapoint[bool], WebActionDatapoint[bool], WebPageItem):
    def __init__(self, label: str):
        self.type = bool
        super().__init__()
        self.label = label
        self.widgets = [self]

    def get_datapoints(self) -> Iterable[Union["WebDisplayDatapoint", "WebActionDatapoint"]]:
        return (self,)

    async def render(self) -> str:
        return await jinja_env.get_template('widgets/switch.htm').render_async(id=id(self), label=self.label)


class EnumSelect(WebDisplayDatapoint[enum.Enum], WebActionDatapoint[enum.Enum], WebPageItem):
    def __init__(self, type_: Type[enum.Enum]):
        self.type = type_
        super().__init__()
        self.widgets = [self]

    def get_datapoints(self) -> Iterable[Union["WebDisplayDatapoint", "WebActionDatapoint"]]:
        return (self,)

    def convert_to_ws_value(self, value: enum.Enum) -> Any:
        return value.value

    def convert_from_ws_value(self, value: Any) -> enum.Enum:
        return self.type(value)

    async def render(self) -> str:
        return await jinja_env.get_template('widgets/select.htm').render_async(
            id=id(self), label="TODO", options=[(e.value, e.name) for e in self.type])


class StatelessButton(WebActionDatapoint[T], WebPageItem):
    def __init__(self, value: T, label: str):
        self.type = type(value)
        super().__init__()
        self.value = value
        self.label = label
        self.widgets = [self]

    def get_datapoints(self) -> Iterable[Union["WebDisplayDatapoint", "WebActionDatapoint"]]:
        return (self,)

    def convert_from_ws_value(self, value: Any) -> T:
        return self.value

    async def render(self) -> str:
        return await jinja_env.get_template('widgets/button.htm').render_async(id=id(self), label=self.label)


class TextDisplay(WebDisplayDatapoint[T], WebPageItem):
    def __init__(self, type_: Type[T], format_string: str, label: str):
        self.type = type_
        super().__init__()
        self.format_string = format_string
        self.label = label
        self.widgets = [self]

    def get_datapoints(self) -> Iterable[Union["WebDisplayDatapoint", "WebActionDatapoint"]]:
        return (self,)

    def convert_to_ws_value(self, value: T) -> Any:
        return self.format_string.format(value)

    async def render(self) -> str:
        return await jinja_env.get_template('widgets/textdisplay.htm').render_async(id=id(self), label=self.label)

