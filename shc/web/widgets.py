import abc
import enum
import itertools
import json
from typing import Any, Type, Union, Iterable, List, Generic, Tuple, TypeVar, Optional

import markupsafe

from . import WebPageItem, WebDisplayDatapoint, WebActionDatapoint, jinja_env, WebDatapointContainer
from ..base import T, ConnectableWrapper
from ..conversion import SHCJsonEncoder
from ..datatypes import RangeFloat1


def icon(icon_name: str, label: str = '') -> markupsafe.Markup:
    return markupsafe.Markup('<i class="ui {}{} icon"></i>'.format("" if label else "fitted ", icon_name)) + label


class Switch(WebDisplayDatapoint[bool], WebActionDatapoint[bool], WebPageItem):
    def __init__(self, label: Union[str, markupsafe.Markup]):
        self.type = bool
        super().__init__()
        self.label = label

    def get_datapoints(self) -> Iterable[Union["WebDisplayDatapoint", "WebActionDatapoint"]]:
        return (self,)

    async def render(self) -> str:
        return await jinja_env.get_template('widgets/switch.htm').render_async(id=id(self), label=self.label)


class Select(WebDisplayDatapoint[T], WebActionDatapoint[T], WebPageItem, Generic[T]):
    def __init__(self, values: List[Tuple[T, Union[str, markupsafe.Markup]]], label: str = ''):
        self.type = type(values[0][0])
        super().__init__()
        self.values = values
        self.label = label

    def get_datapoints(self) -> Iterable[Union["WebDisplayDatapoint", "WebActionDatapoint"]]:
        return (self,)

    async def render(self) -> str:
        return await jinja_env.get_template('widgets/select.htm').render_async(
            id=id(self), label=self.label, options=[(json.dumps(value, cls=SHCJsonEncoder), label)
                                                for value, label in self.values])


Ti = TypeVar('Ti', int, float, str)


class TextInput(WebDisplayDatapoint[Ti], WebActionDatapoint[Ti], WebPageItem, Generic[Ti]):
    def __init__(self, type_: Type[Ti], label: Union[str, markupsafe.Markup] = '', min: Optional[Ti] = None,
                 max: Optional[Ti] = None, step: Optional[Ti] = None, input_suffix: Union[str, markupsafe.Markup] = ''):
        self.type = type_
        super().__init__()
        self.label = label
        self.min = min
        self.max = max
        self.step = step
        if self.step is None and issubclass(self.type, int):
            self.step = 1
        self.input_type = "number" if issubclass(self.type, (int, float)) else "text"
        self.input_suffix = input_suffix

    def get_datapoints(self) -> Iterable[Union["WebDisplayDatapoint", "WebActionDatapoint"]]:
        return (self,)

    def convert_from_ws_value(self, value: Any) -> T:
        return self.type(value)

    async def render(self) -> str:
        return await jinja_env.get_template('widgets/textinput.htm').render_async(
            id=id(self), label=self.label, type=self.input_type, min=self.min, max=self.max, step=self.step,
            input_suffix=self.input_suffix)


class Slider(WebDisplayDatapoint[Ti], WebActionDatapoint[Ti], WebPageItem, Generic[Ti]):
    def __init__(self, label: Union[str, markupsafe.Markup] = '', color: str = ''):
        self.type = RangeFloat1
        super().__init__()
        self.label = label
        self.color = color

    def get_datapoints(self) -> Iterable[Union["WebDisplayDatapoint", "WebActionDatapoint"]]:
        return (self,)

    def convert_from_ws_value(self, value: Any) -> T:
        return float(value)

    async def render(self) -> str:
        return await jinja_env.get_template('widgets/slider.htm').render_async(
            id=id(self), label=self.label, color=self.color)


class EnumSelect(Select):
    def __init__(self, type_: Type[enum.Enum], label: Union[str, markupsafe.Markup] = ''):
        values = [(entry, entry.name) for entry in type_]
        super().__init__(values, label)


class ButtonGroup(WebPageItem):
    def __init__(self, label: Union[str, markupsafe.Markup], buttons: List["AbstractButton"]):
        super().__init__()
        self.label = label
        self.buttons = buttons

    def get_datapoints(self) -> Iterable[Union["WebDisplayDatapoint", "WebActionDatapoint"]]:
        return self.buttons

    async def render(self) -> str:
        return await jinja_env.get_template('widgets/buttongroup.htm')\
            .render_async(label=self.label, buttons=self.buttons)


class AbstractButton(metaclass=abc.ABCMeta):
    label: Union[str, markupsafe.Markup] = ''
    color: str = ''
    stateful: bool = True
    enabled: bool = True


class StatelessButton(WebActionDatapoint[T], AbstractButton, Generic[T]):
    stateful = False

    def __init__(self, value: T, label: Union[str, markupsafe.Markup] = ''):
        self.type = type(value)
        super().__init__()
        self.value = value
        self.label = label

    def convert_from_ws_value(self, value: Any) -> T:
        return self.value


class ValueButton(WebActionDatapoint[T], WebDisplayDatapoint[T], AbstractButton, Generic[T]):
    def __init__(self, value: T, label: Union[str, markupsafe.Markup] = '', color: str = 'blue'):
        self.type = type(value)
        super().__init__()
        self.value = value
        self.label = label
        self.color = color

    def convert_from_ws_value(self, value: Any) -> T:
        return self.value

    def convert_to_ws_value(self, value: T) -> Any:
        return value == self.value


class ToggleButton(WebActionDatapoint[bool], AbstractButton, WebDisplayDatapoint[bool]):
    def __init__(self, label: Union[str, markupsafe.Markup] = '', color: str = 'blue'):
        self.type = bool
        super().__init__()
        self.label = label
        self.color = color


class DisplayButton(WebDisplayDatapoint[T], AbstractButton, Generic[T]):
    enabled = False

    def __init__(self, value: T = True,  label: Union[str, markupsafe.Markup] = '', color: str = 'blue'):
        self.type = type(value)
        super().__init__()
        self.value = value
        self.label = label
        self.color = color

    def convert_to_ws_value(self, value: T) -> Any:
        return value == self.value


class TextDisplay(WebDisplayDatapoint[T], WebPageItem):
    def __init__(self, type_: Type[T], format_string: str, label: Union[str, markupsafe.Markup]):
        self.type = type_
        super().__init__()
        self.format_string = format_string
        self.label = label

    def get_datapoints(self) -> Iterable[Union["WebDisplayDatapoint", "WebActionDatapoint"]]:
        return (self,)

    def convert_to_ws_value(self, value: T) -> Any:
        return self.format_string.format(value)

    async def render(self) -> str:
        return await jinja_env.get_template('widgets/textdisplay.htm').render_async(id=id(self), label=self.label)


class ValueListButtonGroup(ButtonGroup, ConnectableWrapper[T], Generic[T]):
    def __init__(self, values: List[Tuple[T, Union[str, markupsafe.Markup]]], label: Union[str, markupsafe.Markup],
                 color: str = 'blue'):
        buttons = [ValueButton(value=v[0], label=v[1], color=color) for v in values]
        super().__init__(label, buttons)

    def connect(self, *args, **kwargs):
        for button in self.buttons:
            button.connect(*args, **kwargs)
        return self


class EnumButtonGroup(ValueListButtonGroup):
    def __init__(self, type_: Type[enum.Enum], label: Union[str, markupsafe.Markup], color: str = 'blue'):
        values = [(entry, entry.name) for entry in type_]
        super().__init__(values, label, color)


class HideRowBox(WebPageItem):
    def __init__(self, rows: List["HideRow"]):
        self.rows = rows

    def get_datapoints(self) -> Iterable[Union["WebDisplayDatapoint", "WebActionDatapoint"]]:
        return itertools.chain.from_iterable(row.get_datapoints() for row in self.rows)

    async def render(self) -> str:
        return await jinja_env.get_template('widgets/hiderowbox.htm').render_async(rows=self.rows)


class HideRow(WebDisplayDatapoint[bool], WebDatapointContainer):
    def __init__(self, label: Union[str, markupsafe.Markup], button: Optional[AbstractButton] = None,
                 color: str = 'blue',):
        self.type = bool
        super().__init__()
        self.label = label
        self.button = button
        self.color = color

    def get_datapoints(self) -> Iterable[Union["WebDisplayDatapoint", "WebActionDatapoint"]]:
        if self.button:
            yield self.button
        yield self
