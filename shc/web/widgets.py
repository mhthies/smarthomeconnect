import enum
import json
from typing import Any, Type, Union, Iterable

from . import WebPageItem, WebDisplayDatapoint, WebActionDatapoint
from ..base import T


class Switch(WebDisplayDatapoint[bool], WebActionDatapoint[bool], WebPageItem):
    def __init__(self, label: str):
        self.type = bool
        super().__init__()
        self.label = label
        self.widgets = [self]

    def get_datapoints(self) -> Iterable[Union["WebDisplayDatapoint", "WebActionDatapoint"]]:
        return (self,)

    def render(self) -> str:
        # TODO use Jinja2 templates
        return "<div><input type=\"checkbox\" data-widget=\"switch\" data-id=\"{id}\" /> {label}</div>"\
            .format(label=self.label, id=id(self))


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

    def render(self) -> str:
        # TODO use Jinja2 templates
        return "<div><select data-widget=\"enum-select\" data-id=\"{id}\">{options}</select></div>"\
            .format(id=id(self),
                    options="".join("<option value=\"{value}\">{label}</option>"
                                    .format(value=json.dumps(e.value), label=e.name) for e in self.type))


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

    def render(self) -> str:
        # TODO use Jinja2 templates
        return "<div><button data-widget=\"stateless-button\" data-id=\"{id}\">{label}</button></div>"\
            .format(id=id(self), label=self.label)


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

    def render(self) -> str:
        # TODO use Jinja2 templates
        return "<div><strong>{label}</strong> <span data-id=\"{id}\" data-widget=\"text-display\"></span></div>"\
            .format(id=id(self), label=self.label)

