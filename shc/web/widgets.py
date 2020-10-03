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
import enum
import itertools
import json
import pathlib
from os import PathLike
from typing import Any, Type, Union, Iterable, List, Generic, Tuple, TypeVar, Optional

import markupsafe

from . import WebPageItem, WebDisplayDatapoint, WebActionDatapoint, jinja_env, WebConnectorContainer, WebUIConnector, \
    WebPage, WebServer
from ..base import T, ConnectableWrapper
from ..conversion import SHCJsonEncoder
from ..datatypes import RangeFloat1, RGBUInt8


def icon(icon_name: str, label: str = '') -> markupsafe.Markup:
    return markupsafe.Markup('<i class="ui {}{} icon"></i>'.format("" if label else "fitted ", icon_name)) + label


class Switch(WebDisplayDatapoint[bool], WebActionDatapoint[bool], WebPageItem):
    def __init__(self, label: Union[str, markupsafe.Markup], color: str = '', confirm_message: str = '',
                 confirm_values: Iterable[bool] = (False, True)):
        self.type = bool
        super().__init__()
        self.label = label
        self.color = color
        self.confirm_message = confirm_message
        self.confirm = confirm_values if confirm_message else ()

    async def render(self) -> str:
        return await jinja_env.get_template('widgets/switch.htm').render_async(
            id=id(self), label=self.label, color=self.color,
            confirm_csv_int=",".join(str(int(v)) for v in self.confirm), confirm_message=self.confirm_message)


class Select(WebDisplayDatapoint[T], WebActionDatapoint[T], WebPageItem, Generic[T]):
    def __init__(self, values: List[Tuple[T, Union[str, markupsafe.Markup]]], label: str = ''):
        self.type = type(values[0][0])
        super().__init__()
        self.values = values
        self.label = label

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
        self.min: Optional[Ti] = min
        self.max: Optional[Ti] = max
        self.step: Optional[Ti] = step
        if self.step is None and issubclass(type_, int):
            self.step = 1
        self.input_type = "number" if issubclass(self.type, (int, float)) else "text"
        self.input_suffix = input_suffix

    def convert_from_ws_value(self, value: Any) -> Ti:
        return self.type(value)

    async def render(self) -> str:
        return await jinja_env.get_template('widgets/textinput.htm').render_async(
            id=id(self), label=self.label, type=self.input_type, min=self.min, max=self.max, step=self.step,
            input_suffix=self.input_suffix)


class Slider(WebDisplayDatapoint[RangeFloat1], WebActionDatapoint[RangeFloat1], WebPageItem):
    def __init__(self, label: Union[str, markupsafe.Markup] = '', color: str = ''):
        self.type = RangeFloat1
        super().__init__()
        self.label = label
        self.color = color

    def convert_from_ws_value(self, value: Any) -> RangeFloat1:
        return RangeFloat1(float(value))

    async def render(self) -> str:
        return await jinja_env.get_template('widgets/slider.htm').render_async(
            id=id(self), label=self.label, color=self.color)


class EnumSelect(Select):
    def __init__(self, type_: Type[enum.Enum], label: Union[str, markupsafe.Markup] = ''):
        values = [(entry, entry.name) for entry in type_]
        super().__init__(values, label)


class ButtonGroup(WebPageItem):
    def __init__(self, label: Union[str, markupsafe.Markup], buttons: Iterable["AbstractButton"]):
        super().__init__()
        self.label = label
        self.buttons = buttons

    def get_connectors(self) -> Iterable[WebUIConnector]:
        return self.buttons  # type: ignore

    async def render(self) -> str:
        return await jinja_env.get_template('widgets/buttongroup.htm')\
            .render_async(label=self.label, buttons=self.buttons)


class AbstractButton(metaclass=abc.ABCMeta):
    label: Union[str, markupsafe.Markup] = ''
    color: str = ''
    stateful: bool = True
    enabled: bool = True
    outline: bool = False
    confirm: Iterable[bool] = ()
    confirm_message: str = ""

    @property
    def confirm_csv_int(self) -> str:
        return ",".join(str(int(v)) for v in self.confirm)


jinja_env.tests['button'] = lambda item: isinstance(item, AbstractButton)


class StatelessButton(WebActionDatapoint[T], AbstractButton, Generic[T]):
    stateful = False

    def __init__(self, value: T, label: Union[str, markupsafe.Markup] = '', color: str = '', confirm_message: str = '',
                 outline: bool = False):
        self.type = type(value)
        super().__init__()
        self.value = value
        self.label = label
        self.color = color
        self.outline = outline
        if confirm_message:
            self.confirm = [False, True]
            self.confirm_message = confirm_message

    def convert_from_ws_value(self, value: Any) -> T:
        return self.value


class ValueButton(WebActionDatapoint[T], WebDisplayDatapoint[T], AbstractButton, Generic[T]):
    def __init__(self, value: T, label: Union[str, markupsafe.Markup] = '', color: str = 'blue',
                 confirm_message: str = '', outline: bool = False):
        self.type = type(value)
        super().__init__()
        self.value = value
        self.label = label
        self.color = color
        self.outline = outline
        if confirm_message:
            self.confirm = [False, True]
            self.confirm_message = confirm_message

    def convert_from_ws_value(self, value: Any) -> T:
        return self.value

    def convert_to_ws_value(self, value: T) -> Any:
        return value == self.value


class ToggleButton(WebActionDatapoint[bool], AbstractButton, WebDisplayDatapoint[bool]):
    def __init__(self, label: Union[str, markupsafe.Markup] = '', color: str = 'blue', confirm_message: str = '',
                 confirm_values: Iterable[bool] = (False, True), outline: bool = False):
        self.type = bool
        super().__init__()
        self.label = label
        self.color = color
        self.outline = outline
        if confirm_message:
            self.confirm_message = confirm_message
            self.confirm = confirm_values


class DisplayButton(WebDisplayDatapoint[T], AbstractButton, Generic[T]):
    enabled = False

    def __init__(self, value: T = True,  label: Union[str, markupsafe.Markup] = '',  # type: ignore
                 color: str = 'blue', outline: bool = False):
        self.type = type(value)
        super().__init__()
        self.value = value
        self.label = label
        self.color = color
        self.outline = outline

    def convert_to_ws_value(self, value: T) -> bool:
        return value == self.value


class TextDisplay(WebDisplayDatapoint[T], WebPageItem):
    def __init__(self, type_: Type[T], format_string: str, label: Union[str, markupsafe.Markup]):
        self.type = type_
        super().__init__()
        self.format_string = format_string
        self.label = label

    def convert_to_ws_value(self, value: T) -> Any:
        return self.format_string.format(value)

    async def render(self) -> str:
        return await jinja_env.get_template('widgets/textdisplay.htm').render_async(id=id(self), label=self.label)


class ValueListButtonGroup(ButtonGroup, ConnectableWrapper[T], Generic[T]):
    def __init__(self, values: List[Tuple[T, Union[str, markupsafe.Markup]]], label: Union[str, markupsafe.Markup],
                 color: str = 'blue', confirm_message: str = ''):
        buttons = [ValueButton(value=v[0], label=v[1], color=color, confirm_message=confirm_message) for v in values]
        super().__init__(label, buttons)

    def connect(self, *args, **kwargs):
        for button in self.buttons:
            button.connect(*args, **kwargs)
        return self


class EnumButtonGroup(ValueListButtonGroup):
    def __init__(self, type_: Type[enum.Enum], label: Union[str, markupsafe.Markup], color: str = 'blue',
                 confirm_message: str = ''):
        values = [(entry, entry.name) for entry in type_]
        super().__init__(values, label, color, confirm_message)


class HideRowBox(WebPageItem):
    def __init__(self, rows: List["HideRow"]):
        self.rows = rows

    def get_connectors(self) -> Iterable[WebUIConnector]:
        return itertools.chain.from_iterable(row.get_connectors() for row in self.rows)

    async def render(self) -> str:
        return await jinja_env.get_template('widgets/hiderowbox.htm').render_async(rows=self.rows)


class HideRow(WebDisplayDatapoint[bool], WebConnectorContainer):
    def __init__(self, label: Union[str, markupsafe.Markup], button: Optional[AbstractButton] = None,
                 color: str = 'blue',):
        self.type = bool
        super().__init__()
        self.label = label
        self.button = button
        self.color = color

    def get_connectors(self) -> Iterable[WebUIConnector]:
        if self.button:
            yield self.button  # type: ignore
        yield self


class ColorChoser(WebActionDatapoint[RGBUInt8], WebDisplayDatapoint[RGBUInt8], WebPageItem):
    type = RGBUInt8

    async def render(self) -> str:
        # TODO add label
        return await jinja_env.get_template('widgets/colorchoser.htm').render_async(id=id(self))


ImageMapItem = Union[AbstractButton, "ImageMapLabel"]


class ImageMap(WebPageItem):
    def __init__(self, image: PathLike, items: Iterable[Union[Tuple[float, float, ImageMapItem],
                                                              Tuple[float, float, ImageMapItem, List[WebPageItem]]]]):
        super().__init__()
        self.image = image
        self.image_url = None
        self.items: List[Tuple[float, float, ImageMapItem, List[WebPageItem]]]\
            = [item if len(item) >= 4 else (*item, [],)
               for item in items]

    def register_with_server(self, _page: WebPage, server: WebServer) -> None:
        self.image_url = server.root_url + server.serve_static_file(pathlib.Path(self.image))

    def get_connectors(self) -> Iterable[WebUIConnector]:
        for x, y, item, sub_items in self.items:
            if isinstance(item, WebUIConnector):
                yield item
            yield from sub_items

    async def render(self) -> str:
        return await jinja_env.get_template('widgets/imagemap.htm')\
            .render_async(items=self.items, image_url=self.image_url)


class ImageMapLabel(WebDisplayDatapoint[T]):
    def __init__(self, type_: Type[T], format_string: str = "{}", color: str = ""):
        self.type = type_
        super().__init__()
        self.color = color
        self.format_string = format_string

    def convert_to_ws_value(self, value: T) -> Any:
        return self.format_string.format(value)


jinja_env.tests['imageMapLabel'] = lambda item: isinstance(item, ImageMapLabel)
