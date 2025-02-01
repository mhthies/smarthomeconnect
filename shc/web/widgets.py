# Copyright 2020-2022 Michael Thies <mail@mhthies.de>
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may not use this file except in compliance with
# the License. You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software distributed under the License is distributed on an
# "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the License for the
# specific language governing permissions and limitations under the License.
"""
This module contains all the predefined user interface widget (:class:`shc.web.WebPageItem`) classes, which can be
instantiated and added to :class:`WebPage` s in order to compose the web user interface.

In addition, there are descriptor classes, like the button classes (e.g. :class:`ToggleButton`) and the
:class:`ImageMapLabel`. Instances of these classes are used to create an interactive element within another widget.
They cannot be added to a ui page directly, but must be added to a compatible container element (like
:class:`ButtonGroup` or :class:`ImageMap`) instead. Still, they form the endpoint for the dynamic interaction and thus
are `Connectable` objects.

Please note that each widget or button instance must not be used multiple times (neither on the same nor on
different pages). To create two or more similar and synchronized widgets/buttons, create two instances with the same
settings and `connect` both of them to the same :class:`shc.Variable`.
"""

import abc
import enum
import itertools
import json
import pathlib
from os import PathLike
from typing import (
    Any,
    Callable,
    Generic,
    Iterable,
    List,
    Optional,
    Tuple,
    Type,
    TypeVar,
    Union,
    cast,
)

import markupsafe
from markupsafe import Markup

from ..base import Connectable, ConnectableWrapper, T
from ..conversion import SHCJsonEncoder
from ..datatypes import RangeFloat1, RGBUInt8
from .interface import (
    WebActionDatapoint,
    WebConnectorContainer,
    WebDisplayDatapoint,
    WebPage,
    WebPageItem,
    WebServer,
    WebUIConnector,
    jinja_env,
)

__all__ = [
    "icon",
    "Switch",
    "Select",
    "EnumSelect",
    "ButtonGroup",
    "ValueListButtonGroup",
    "EnumButtonGroup",
    "ToggleButton",
    "ValueButton",
    "DisplayButton",
    "StatelessButton",
    "TextDisplay",
    "TextInput",
    "Slider",
    "MinMaxButtonSlider",
    "HideRowBox",
    "HideRow",
    "ColorChoser",
    "ImageMap",
    "ImageMapLabel",
]


def icon(icon_name: str, label: str = "") -> Markup:
    """
    Create HTML markup for a Fontawesome/Semantic UI icon, to be used in PageItem labels, button labels, etc.

    :param icon_name: Name of the icon. See https://fomantic-ui.com/elements/icon.html for reference.
    :param label: Optional textual label to be placed along with the icon. The styling of the icon is slightly changed,
        when `label` is non-empty to optimize the spacing between icon an text.
    :return: (safe) HTML markup to be passed to a Jinja template (of a web page or web widget), e.g. via one of the
        `label` attributes.
    """
    return Markup('<i class="ui {}{} icon"></i>'.format("" if label else "fitted ", icon_name)) + label


class Switch(WebDisplayDatapoint[bool], WebActionDatapoint[bool], WebPageItem):
    """
    A `WebPageItem` showing a label and a right-aligned toggle switch.

    This widget is a `Connectable` object with type `bool`. It should be connected to a `Readable` object for
    initialization, e.g. a :class:`shc.Variable` of bool type.

    :param label: The label to be displayed near the switch. Either a plain string (which is automatically escaped for
        embedding in HTML) or a :class:`markupsafe.Markup` object, which may contain pre-formattet HTML, e.g.
        produced by :func:`icon`.
    :param color: Background color of the switch, when in 'on' position. The available colors are the same as for
        buttons. See https://fomantic-ui.com/elements/button.html#colored for reference.
    :param confirm_message: If provided, the user is asked for confirmation of each interaction with the switch with
        this message and "OK" and "Cancel" buttons. `confirm_values` may be used to restrict the confirmation to
        switching on or switching off.
    :param confirm_values: If `confirm_message` is given, this parameter specifies, which changes of the switch must be
        confirmed by the user. When set to `[True]`, only switching on (sending True) must be confirmed, when set to
        `[False]`, only switching off must be confirmed. Defaults to `[False, True]`, i.e. every change must be
        confirmed.
    """

    def __init__(
        self,
        label: Union[str, Markup],
        color: str = "",
        confirm_message: str = "",
        confirm_values: Iterable[bool] = (False, True),
    ):
        self.type = bool
        super().__init__()
        self.label = label
        self.color = color
        self.confirm_message = confirm_message
        self.confirm = confirm_values if confirm_message else ()

    async def render(self) -> str:
        return await jinja_env.get_template("widgets/switch.htm").render_async(
            id=id(self),
            label=self.label,
            color=self.color,
            confirm_csv_int=",".join(str(int(v)) for v in self.confirm),
            confirm_message=self.confirm_message,
        )


class Select(WebDisplayDatapoint[T], WebActionDatapoint[T], WebPageItem, Generic[T]):
    """
    A dropdown (HTML <select>) ui widget with label.

    This widget is a generic `Connectable` object. The type is determined by the values' type. It should be connected to
    a `Readable` object for initialization.

    :param options: List of options in the dropdown. Each option is a tuple of (value, label). All values must be of the
        same type. Each label can either be a plain string or a :class:`markupsafe.Markup` with pre-formatted HTML,
        e.g. from the :func:`icon` function. Since Semantic UI's JavaScript-based <select>-replacement is used, even
        complex HTML should be rendered properly.
    :param label: The label to be displayed near the dropdown. Either a plain string (which is automatically escaped for
        embedding in HTML) or a :class:`markupsafe.Markup` object, which may contain pre-formattet HTML, e.g.
        produced by :func:`icon`.
    """

    def __init__(self, options: List[Tuple[T, Union[str, Markup]]], label: str = ""):
        self.type = type(options[0][0])
        super().__init__()
        self.options = options
        self.label = label

    async def render(self) -> str:
        return await jinja_env.get_template("widgets/select.htm").render_async(
            id=id(self),
            label=self.label,
            options=[(json.dumps(value, cls=SHCJsonEncoder), label) for value, label in self.options],
        )


class EnumSelect(Select):
    """
    Specialized version of :class:`Select` for choosing between the entries of a given enum type by their `name`.

    :param type_: The enum type. It is used as the `type` attribute for `connecting` and to generate the dropdown
        entries from its enum members.
    :param label: The label to be displayed near the dropdown. Either a plain string (which is automatically escaped for
        embedding in HTML) or a :class:`markupsafe.Markup` object, which may contain pre-formattet HTML, e.g.
        produced by :func:`icon`.
    """

    def __init__(self, type_: Type[enum.Enum], label: Union[str, Markup] = ""):
        values = [(entry, entry.name) for entry in type_]
        super().__init__(values, label)


Ti = TypeVar("Ti", int, float, str)


class TextInput(WebDisplayDatapoint[Ti], WebActionDatapoint[Ti], WebPageItem, Generic[Ti]):
    """
    An input field ui widget for numbers and strings with label.

    This widget is a generic `Connectable` object. The type is specified by the `type_` parameter. The `TextInput`
    should be connected to a `Readable` object for initialization.

    :param type_: The value type to be entered. Used as the `type` for connecting with other Connectables and to
        determine the HTML input type. Must be int, float or str.
    :param label: The label to be displayed near the input. Either a plain string (which is automatically escaped for
        embedding in HTML) or a :class:`markupsafe.Markup` object, which may contain pre-formattet HTML, e.g.
        produced by :func:`icon`.
    :param min: The minimal value to be entered (only useful if `type_` is int or float). Used as the HTML `min`
        attribute.
    :param max: The maximal value to be entered (only useful if `type_` is int or float). Used as the HTML `max`
        attribute.
    :param step: The default increment step when using the arrow buttons or arrow keys in the input field (only useful
        if `type_` is int or float). Used as the HTML `step` attribute.
    :param input_suffix: A plain string or HTML markup to be appended to the right of the input field, using Semantic
        UI's `labeled inputs <https://fomantic-ui.com/elements/input.html#labeled>`_.
    """

    def __init__(
        self,
        type_: Type[Ti],
        label: Union[str, Markup] = "",
        min: Optional[Ti] = None,
        max: Optional[Ti] = None,
        step: Optional[Ti] = None,
        input_suffix: Union[str, Markup] = "",
    ):
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
        return await jinja_env.get_template("widgets/textinput.htm").render_async(
            id=id(self),
            label=self.label,
            type=self.input_type,
            min=self.min,
            max=self.max,
            step=self.step,
            input_suffix=self.input_suffix,
        )


class TextDisplay(WebDisplayDatapoint[T], WebPageItem):
    """
    A ui widget which simply displays the value of the connected `Connectable` object as text.

    This widget is a generic `Connectable` object. The type is specified by the `type_` parameter. The `TextInput`
    should be connected to a `Readable` object for initialization. In contrast to interactive widgets, it does only
    consume, but not produce values, so it's not `Subscribable`.

    The formatting of the value can be controlled via the `format_string` parameter, which is used with Python 3's
    `str.format()` method. To show the value with default formatting, use the '{}' format. Other format specifiers may
    be used, e.g. to specify the floating point accuracy::

        TextDisplay(float, '{:.2f}', "Current value of my_float").connect(my_float_variable)

    The format string may, of course, contain additional characters outside the format specifier to prepend and/or
    append static strings to the dynamically formatted value.
    See https://docs.python.org/3/library/string.html#formatstrings for a full reference of valid format strings.

    :param type_: The expected value type, used as the `type` attribute of this `Connectable`
    :param format: Either a Python string or safely escpaed HTML markup, which is used to format the value into a string
        representation using the `format()` method or otherwise a callable which transforms a value to a string or
        escaped HTML Markup (in form of a :class:`markupsafe.Markup` object).
    :param label: A label to be displayed left of the formatted value. Either a plain string (which is automatically
        escaped for embedding in HTML) or a :class:`markupsafe.Markup` object, which may contain pre-formattet HTML,
        e.g. produced by :func:`icon`.
    """

    def __init__(
        self, type_: Type[T], format: Union[str, Markup, Callable[[T], Union[str, Markup]]], label: Union[str, Markup]
    ):
        self.type = type_
        super().__init__()
        self.formatter: Callable[[T], Union[str, Markup]] = (
            (lambda x: format.format(x)) if isinstance(format, (str, Markup)) else format
        )
        self.label = label

    def convert_to_ws_value(self, value: T) -> Any:
        return markupsafe.escape(self.formatter(value))

    async def render(self) -> str:
        return await jinja_env.get_template("widgets/textdisplay.htm").render_async(id=id(self), label=self.label)


class Slider(WebDisplayDatapoint[RangeFloat1], WebActionDatapoint[RangeFloat1], WebPageItem):
    """
    A visual slider ui widget, labeled with a scale from 0%-100% to set range values.

    This widget is a generic `Connectable` object with type :class:`shc.datatypes.RangeFloat1`. It should be connected
    to a `Readable` object for initialization. Using the `convert` parameter of the `connect()` method, a `Slider`
    can be connected to `Connectable` objects of other default range types, like :class:`shc.datatypes.RangeUInt8`.

    :param label: The label to be displayed above the slider (left). Either a plain string (which is automatically
        escaped for embedding in HTML) or a :class:`markupsafe.Markup` object, which may contain pre-formattet HTML,
        e.g. produced by :func:`icon`.
    :param color: Background color of the slider and the upper right label showing the current value. Must be one of
        Semantic UI's predefined slider colors: https://fomantic-ui.com/modules/slider.html#colored
    :param left_button: An optional button descriptor to attach a button to the left end of the slider. All different
        kinds of buttons and all layout features of :class:`AbstractButton` are supported.
    :param right_button: An optional button descriptor to attach a button to the right end of the slider (can be used
        independently from `left_button`).  All different kinds of buttons and all layout features of
        :class:`AbstractButton` are supported.
    """

    def __init__(
        self,
        label: Union[str, Markup] = "",
        color: str = "",
        left_button: Optional["AbstractButton"] = None,
        right_button: Optional["AbstractButton"] = None,
    ):
        self.type = RangeFloat1
        super().__init__()
        self.label = label
        self.color = color
        self.left_button = left_button
        self.right_button = right_button

    def convert_from_ws_value(self, value: Any) -> RangeFloat1:
        return RangeFloat1(float(value))

    async def render(self) -> str:
        return await jinja_env.get_template("widgets/slider.htm").render_async(
            id=id(self),
            label=self.label,
            color=self.color,
            left_button=self.left_button,
            right_button=self.right_button,
        )


class MinMaxButtonSlider(WebPageItem, ConnectableWrapper[RangeFloat1]):
    """
    A pre-configured version of :class:`Slider` with left_button and right_button for quick access to 0% and 100%.

    This object is a ConnectableWrapper that includes the Slider object as well as the two button descriptor objects.
    When `connecting` to it, using the :meth:`connect` method, it will connect all three objects with the given `other`
    object.

    The buttons are configured to be highlighted in the same color as the slider. They use the `circle outline` and
    (filled) `circle` icons as label.

    :param label: The label to be displayed left above the slider. Either a plain string (which is automatically
        escaped for embedding in HTML) or a :class:`markupsafe.Markup` object, which may contain pre-formattet HTML,
        e.g. produced by :func:`icon`.
    :param color: Background color of the slider, the upper right label showing the current value and the two buttons
        (when hightlighted). Must be one of Semantic UI's predefined slider colors:
        https://fomantic-ui.com/modules/slider.html#colored
    """

    def __init__(self, label: Union[str, Markup] = "", color: str = ""):
        super().__init__()
        self.left_button = ValueButton(RangeFloat1(0), icon("circle outline"), color=color or "black")
        self.right_button = ValueButton(RangeFloat1(1), icon("circle"), color=color or "black")
        self.slider = Slider(label, color, self.left_button, self.right_button)

    async def render(self) -> str:
        return await self.slider.render()

    def get_connectors(self) -> Iterable["WebUIConnector"]:
        return self.slider, self.left_button, self.right_button

    def connect(
        self,
        other: "Connectable",
        send: Optional[bool] = None,
        receive: Optional[bool] = None,
        read: Optional[bool] = None,
        provide: Optional[bool] = None,
        convert: Union[bool, Tuple[Callable[[RangeFloat1], Any], Callable[[Any], RangeFloat1]]] = False,
    ) -> "MinMaxButtonSlider":
        self.slider.connect(other, send, receive, read, provide, convert)
        self.left_button.connect(other, send, receive, read, provide, convert)
        self.right_button.connect(other, send, receive, read, provide, convert)
        return self


class ButtonGroup(WebPageItem):
    """
    A ui widget consisting of one or more (right-aligned) buttons with a label.

    The appearance (color, label, etc.) and possible interactions of each individual button is specified by a button
    descriptor (any subclass of :class:`AbstractButton`) for each button. These button descriptors form the SHC-side
    interface to the buttons to connect them with other `Connectable` objects. The `ButtonGroup` itself is not
    `Connectable`.

    :param label: The label to be shown left of the buttons
    :param buttons: List or a List of Lists of button descriptors.  A plain list of button descriptors will be
        grouped all together, whereas providing multiple lists each list will be grouped together with a small gap
        between each group of button descriptors.
    """

    def __init__(
        self,
        label: Union[str, Markup],
        buttons: Union[Iterable["AbstractButton"], Iterable[Iterable["AbstractButton"]]],
    ):
        super().__init__()
        self.label = label
        if all(isinstance(item, Iterable) for item in buttons):
            self.buttons: Iterable["AbstractButton"] = list(itertools.chain(*buttons))
            self.button_groups = cast(Iterable[Iterable["AbstractButton"]], buttons)
        else:
            self.buttons = cast(Iterable["AbstractButton"], buttons)
            self.button_groups = cast(Iterable[Iterable["AbstractButton"]], [buttons])

    def get_connectors(self) -> Iterable[WebUIConnector]:
        return self.buttons  # type: ignore

    async def render(self) -> str:
        return await jinja_env.get_template("widgets/buttongroup.htm").render_async(
            label=self.label, button_groups=self.button_groups
        )


class AbstractButton(metaclass=abc.ABCMeta):
    """
    Abstract base class for button descriptor objects.

    Instances of Concrete subclasses can be passed to container widgets like :class:`ButtonGroup` and :class:`ImageMap`
    and specify the layout (color, label, etc.) and functionality of a button. They also form the SHC-side interface
    for interacting with the button, i.e. they are `Subscriable` and/or `Reading`+`Writable`.

    Existing concrete subclasses:

    * :class:`StatelessButton` (`Subscribable`, any type): Publishes a fixed value on click (no state feedback)
    * :class:`ValueButton` (`Subscribable`, `Writable`, `Reading`, any type): Publishes a fixed value on click. Lights
        up, when current value of connected object equals the fixed value
    * :class:`ToggleButton` (`Subscribable`, `Writable`, `Reading`, ``bool``): Lights up when value of connected object
        is True. Sends the opposite boolean value on click. (Similar to :class:`Switch`)
    * :class:`DisplayButton` (`Writable`, `Reading`, ``bool`` or any type): Lights up when value of connected object
        equals a fixed value (`True` by default). No interaction.

    :var label: The label/text content of the button. Either a plain string (which should automatically be escaped for
        embedding in HTML) or a :class:`markupsafe.Markup` object, which may contain pre-formattet and properly
        escaped HTML code.
    :var color: The color of the button. One of the Semantic UI button colors.
    :var stateful: If True, the button has an on/off state. It should only be shown fully colored, when in 'on' state.
        Additionally, it should be shown in 'loading' state until an initial value is received from the server.
    :var enabled: If False, the button should not be clickable (HTML disabled attribute)
    :var outline: If True (and `stateful==True`), the button should be shown with a colored outline in 'off' state
    :var confirm: A list of all values (True and/or False) which should be confirmed by the user after a click on the
        button, before being sent to the server. An emtpy list/tuple means no confirmation is required for any
        interaction with this button.
    :var confirm_message: The message to be shown in the confirm window, when a confirmation is required for an
        interaction with this button.
    """

    label: Union[str, Markup] = ""
    color: str = ""
    stateful: bool = True
    enabled: bool = True
    outline: bool = False
    confirm: Iterable[bool] = ()
    confirm_message: str = ""

    @property
    def confirm_csv_int(self) -> str:
        return ",".join(str(int(v)) for v in self.confirm)


jinja_env.tests["button"] = lambda item: isinstance(item, AbstractButton)


class StatelessButton(WebActionDatapoint[T], AbstractButton, Generic[T]):
    """
    Button descriptor for a stateless button, i.e. a button that has no visual on/off state and always sends the same
    value, when clicked.

    `StatelessButtons` are `Subscribable`, but not `Writable`. The `type` is the type of their `value`.

    :param value: The value to be published by this object when the button is clicked by the user
    :param label: The label/text content of the button. Either a plain string (which is automatically
        escaped for embedding in HTML) or a :class:`markupsafe.Markup` object, which may contain pre-formattet HTML,
        e.g. produced by :func:`icon`.
    :param color: The color of the button. One of the Semantic UI button colors. See
        https://fomantic-ui.com/elements/button.html#colored for reference. If not specified, the button is shown in the
        grey-ish default color. Since the button has no on/off state, the specified color is always shown.
    :param confirm_message: If not empty, the user must confirm each click on the button in a confirm windows with this
        message.
    :param outline: If True, the button is not shown fully colored, but only with its outline
        (`Semantic UI basic button <https://fomantic-ui.com/elements/button.html#basic>`_). Since the button has no
        on/off state, this holds all the time.
    """

    stateful = False

    def __init__(
        self,
        value: T,
        label: Union[str, Markup] = "",
        color: str = "",
        confirm_message: str = "",
        outline: bool = False,
    ):
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
    """
    Button descriptor for a button with a fixed value.

    This button publishes a fixed value upon every click, just like the :class:`StatelessButton`. Unlike a
    `StatelessButton`, it is dynamically lit up (shown in full color) when the current value of the connected object
    matches the fixed value of the button.

    The `type` of this `Connectable` object is determined from the `value`. The `ValueButton` should be connected
    to a `Readable` object for initialization of the ui.

    For creating multiple `ValueButtons` with different values for the same variable, take a look a the
    :class:`ValueListButtonGroup` widget.

    :param value: The value to be published by this object when the button is clicked by the user. Also the value which
        is compared to the `connected` object's current value to determine if the button should be lit up.
    :param label: The label/text content of the button. Either a plain string (which is automatically
        escaped for embedding in HTML) or a :class:`markupsafe.Markup` object, which may contain pre-formattet HTML,
        e.g. produced by :func:`icon`.
    :param color: The color of the button when it is lit up (i.e. `conncted` object's current value matches the
        `value`). Must be one of the Semantic UI button colors. See https://fomantic-ui.com/elements/button.html#colored
        for reference. Defaults to 'blue'.
    :param confirm_message: If not empty, the user must confirm each click on the button in a confirm windows with this
        message.
    :param outline: If True, the button is shown with a colored outline in its configured `color` **when not lit up**,
        instead of its grey-ish default appearance.
    """

    def __init__(
        self,
        value: T,
        label: Union[str, Markup] = "",
        color: str = "blue",
        confirm_message: str = "",
        outline: bool = False,
    ):
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
    """
    Button descriptor for an on/off button.

    Click such a button once to turn it 'on', click it again to turn it 'off'. The button is lit up (fully colored),
    when in 'on' state (the `connected` object's value is `True`) and shown in the grey-ish default color, when in 'off'
    state (unless `outline==True`). When clicked in 'on' state, a `False` value is published and vice versa.

    A `ToggleButton` is a `Connectable` object with type `bool´. It should be connected to a `Readable` object for
    initialization of the ui – otherwise it will show a spinner animation until the first True/False value is received.

    :param label: The label/text content of the button. Either a plain string (which is automatically
        escaped for embedding in HTML) or a :class:`markupsafe.Markup` object, which may contain pre-formattet HTML,
        e.g. produced by :func:`icon`.
    :param color: The color of the button when in 'on' state. Must be one of the Semantic UI button colors.
        See https://fomantic-ui.com/elements/button.html#colored for reference. Defaults to 'blue'.
    :param confirm_message: If provided, the user is asked for confirmation of each interaction with the button with
        this message and "OK" and "Cancel" buttons. `confirm_values` may be used to restrict the confirmation to
        switching on or switching off.
    :param confirm_values: If `confirm_message` is given, this parameter specifies, which changes of the button must be
        confirmed by the user. When set to `[True]`, only switching on (sending True, i.e. clicking in 'off' state) must
        be confirmed; when set to `[False]`, only switching off must be confirmed. Defaults to `[False, True]`, i.e.
        every click must be confirmed.
    :param outline: If True, the button is shown with a colored outline in its configured `color` **in 'off' state**,
        instead of its grey-ish default appearance.
    """

    def __init__(
        self,
        label: Union[str, Markup] = "",
        color: str = "blue",
        confirm_message: str = "",
        confirm_values: Iterable[bool] = (False, True),
        outline: bool = False,
    ):
        self.type = bool
        super().__init__()
        self.label = label
        self.color = color
        self.outline = outline
        if confirm_message:
            self.confirm_message = confirm_message
            self.confirm = confirm_values


class DisplayButton(WebDisplayDatapoint[T], AbstractButton, Generic[T]):
    """
    Button descriptor for a read-only (non-clickable) button.

    A `DisplayButton` behaves similar to a :class:`ValueButton`: It has a preconfigured fixed `value` and is lit up
    (displayed in full color) when the `connected` object's value equals this fixed value. However the `DisplayButton`
    is not clickable. It is a pure display widget, which does not provide user interaction. This, on the SHC-side it
    is not `Subscribable`.

    The `type` of this `Connectable` object is determined from the `value`. The `DisplayButton` should be connected
    to a `Readable` object for initialization of the ui.

    :param value: The value which is compared to the `connected` object's current value to determine if the button
        should be lit up. Defaults to `True`, resulting in a behaviour of a disabled :class:`ToggleButton`.
    :param label: The label/text content of the button. Either a plain string (which is automatically
        escaped for embedding in HTML) or a :class:`markupsafe.Markup` object, which may contain pre-formattet HTML,
        e.g. produced by :func:`icon`.
    :param color: The color of the button when in 'on' state. Must be one of the Semantic UI button colors.
        See https://fomantic-ui.com/elements/button.html#colored for reference. Defaults to 'blue'.
    :param outline: If True, the button is shown with a colored outline in its configured `color` **when not lit up**,
        instead of its grey-ish default appearance.
    """

    enabled = False

    def __init__(
        self,
        value: T = True,  # type: ignore
        label: Union[str, Markup] = "",  # type: ignore
        color: str = "blue",
        outline: bool = False,
    ):
        self.type = type(value)
        super().__init__()
        self.value = value
        self.label = label
        self.color = color
        self.outline = outline

    def convert_to_ws_value(self, value: T) -> bool:
        return value == self.value


class ValueListButtonGroup(ButtonGroup, ConnectableWrapper[T], Generic[T]):
    """
    A derived :class:`ButtonGroup` widget to simplify creating a list of :class:`ValueButtons` for the same variable.

    For convenience, this object is a :class:`ConnectableWrapper`. This means, you can use the :meth:`connect` method
    with another `Connectable` object (like a `Variable`), to connect all the contained `ValueButtons` to that object
    at once.

    :param values: A list of `(value, label)` tuples. For each tuple, a :class:`ValueButton` is created. All values must
        be of the same type.
    :param label: The label of the :class:`ButtonGroup`
    :param color: A common `color` for all buttons
    :param confirm_message: A common `confirm_message` for all buttons
    """

    def __init__(
        self,
        values: List[Tuple[T, Union[str, Markup]]],
        label: Union[str, Markup],
        color: str = "blue",
        confirm_message: str = "",
    ):
        buttons = [ValueButton(value=v[0], label=v[1], color=color, confirm_message=confirm_message) for v in values]
        super().__init__(label, buttons)

    def connect(self, *args, **kwargs):
        for button in self.buttons:
            assert isinstance(button, Connectable)
            button.connect(*args, **kwargs)
        return self


class EnumButtonGroup(ValueListButtonGroup):
    """
    A derived of :class:`ValueListButtonGroup`, which is a :class:`ButtonGroup` of :class:`ValueButtons`.

    This specialized variant takes an enum type (derived from :class:`enum.Enum`) and creates a :class:`ValueButton` for
    each entry/member of that enum, with the members' names as button labels. Like `ValueListButtonGroup`, this object
    is a :class:`ConnectableWrapper`, so you can use the :meth:`connect` to connect all the contained `ValueButtons` to
    another `Connectable` object at once.

    :param type_: The enum type to create the value buttons for
    :param label: The label of the :class:`ButtonGroup`
    :param color: A common `color` for all buttons
    :param confirm_message: A common `confirm_message` for all buttons
    """

    def __init__(
        self, type_: Type[enum.Enum], label: Union[str, Markup], color: str = "blue", confirm_message: str = ""
    ):
        values = [(entry, entry.name) for entry in type_]
        super().__init__(values, label, color, confirm_message)


class HideRowBox(WebPageItem):
    """
    A container for a list of :class:`HideRows <HideRow>`.

    The HideRowBox is a *WebPageItem*, so it can be added to web pages, and takes a list of :class:`HideRow` which are
    dynamically shown or hidden.
    """

    def __init__(self, rows: List["HideRow"]):
        self.rows = rows

    def get_connectors(self) -> Iterable[WebUIConnector]:
        return itertools.chain.from_iterable(row.get_connectors() for row in self.rows)

    async def render(self) -> str:
        return await jinja_env.get_template("widgets/hiderowbox.htm").render_async(rows=self.rows)


class HideRow(WebDisplayDatapoint[bool], WebConnectorContainer):
    """
    A colorful box that is dynamically shown or hidden inside a :class:`HideRowBox`, based on a bool condition.

    The HideRow is a `Connectable` widget of value type *bool* that is dynamically displayed when the `connected`
    object's value is True and is hidden otherwise. It can be used as a kind of indicator: Create a `HideRowBox` with a
    `HideRow` for each light in your home and connect them to the respective `Variables`. Then, the HideRowBox will
    dynamically show a list of all turned-on lights at any time, because the `HideRows` of all turned-off lights are
    hidden. Similiarly, you can use it to indicate a list of different errors.

    Each `HideRow` can be configured with an individual label (including :func:`icons <icon>`) and an individual color.

    In addition, it can take an optional :class:`button descriptor <AbstractButton>`, which defines a button to be
    displayed on the right side of the `HideRow`, whenever it is visible. The button can be connected to any custom
    function. Typically, it will be a :class:`StatelessButton` to turn off the light or acknowledge the error report.

    :param label: The (static) label displayed in the *HideRow*
    :param button: If not None: A button descriptor, describing (and connecting to) a button, displayed on the right
                   side of the *HideRow* when displayed.
    :param color: The background color of the *HideRow* when displayed. Must be one Fomantic UI's color names
    """

    def __init__(
        self,
        label: Union[str, Markup],
        button: Optional[AbstractButton] = None,
        color: str = "blue",
    ):
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
    """
    An interactive color chooser widget in the HSV color space for selecting 24bit RGB colors (:class:`RGBUInt8`).

    The *ColorChooser* widget uses the `iro.js <https://github.com/jaames/iro.js>`_ JavaScript library for displaying
    an interactive color chooser widget. It is updated dynamically from *connected* objects and allows the user to
    select a color, which is published by the *ColorChoser* object in SHC.
    """

    type = RGBUInt8

    async def render(self) -> str:
        # TODO add label
        return await jinja_env.get_template("widgets/colorchoser.htm").render_async(id=id(self))


ImageMapItem = Union[AbstractButton, "ImageMapLabel"]


class ImageMap(WebPageItem):
    """
    A widget showing placeable buttons and labels on a background image.

    The *ImageMap* allows to place dynamic and interactive items on a custom background image. The items are placed
    statically at a relative x and y coordinate of the image (in percent of the image width/height). The relative
    coordinates ensure a stable position of the items relative to the image, even when the image is automatically scaled
    to fit different screen sizes. Typically, the *ImageMap* widget is used to show smart home devices as interactive
    buttons at their respective location on a ground plan of the apartment.

    The available items are:

    - buttons, definable via any of the :class:`button descriptors <AbstractButton>`, described above
      (The styling of the buttons is slightly different from buttons in button groups, but the customization options
      work equivalently.)
    - text labels with dynamic text, defined via :class:`ImageMapLabel`

    Every item can carry an individual pop-up menu that is displayed, when the item is clicked. The pop-up menu can
    contain any number and any kind of web page widgets. A typical use case is showing the basic on/off state of a
    device as a *DisplayButton* on the *ImageMap* and providing fine-grained controls for the device in the pop-up menu,
    as demonstrated in the following example::

        web_page.add_item(
            ImageMap(
                Path("background.png"),
                [
                    # A simple ToggleButton for displaying/switching the ceiling lights
                    (0.51, 0.665, ToggleButton(icon('lightbulb'), color='yellow', outline=True)
                                  .connect(ceiling_lights)),
                    # A DisplayButton with pop-up menu for controlling the stereo
                    (
                        0.375, 0.08,
                        DisplayButton(label=icon('volume up'), color='blue', outline=True)
                            .connect(stereo_power),
                        [
                            Switch("Power", color="blue").connect(stereo_power),
                            Slider("Volume", color='blue').connect(stereo_input_select),
                            EnumSelect(StereoInputOptions, "Select Input").connect(stereo_input_select),
                        ]),
                ]
            ))

    Currently, there are no invisible items (to create interactive "regions" on the background image) or user-definable
    interactive graphics.

    :param image: The background image. Either a local path (preferably as a :class:`pathlib.Path` object) or a URL.
                  If a local path is given, we let the web server serve it as a static file.
                  If an absolute URL (including the schema, like 'https://') is given, it will simply be used as the
                  image source URL of the background image.
    :param items: The list of items to be positioned on the ImageMap. Each list element is a tuple
                  ``(x, y, item)`` or ``(x, y, item, [pop_up_items])``, where

                  - `x` and `y` are the relative coordinates on the background image in the range 0.0 (left/top edge) to
                    1.0 (right/bottom edge)
                  - `item` is the item descriptor, i.e. a :class:`ImageMapLabel` or :class:`AbstractButton` object
                  - (optional) `[pop_up_items]` is a list of :class:`web widgets <shc.web.WebPageItem>` to be displayed
                    in the pop-up menu
    :param max_width: If given and not None, defines the maximum width of the background image on large screens in
                      pixels.
    """

    def __init__(
        self,
        image: Union[PathLike, str],
        items: Iterable[Union[Tuple[float, float, ImageMapItem], Tuple[float, float, ImageMapItem, List[WebPageItem]]]],
        max_width: Optional[int] = None,
    ):
        super().__init__()
        self.image = image
        self.image_url: str = ""
        # Allow using external images: If `image` is an absolute URI, simply use it as the img src, instead of trying
        # to serve it via our http server
        if isinstance(image, str) and "://" in image:
            self.image_url = image

        self.max_width = max_width
        self.items: List[Tuple[float, float, ImageMapItem, List[WebPageItem]]] = [
            item
            if len(item) >= 4
            else (
                item[0],
                item[1],
                item[2],
                [],
            )
            for item in items
        ]

    def register_with_server(self, _page: WebPage, server: WebServer) -> None:
        if not self.image_url:
            self.image_url = server.serve_static_file(pathlib.Path(self.image))

    def get_connectors(self) -> Iterable[WebUIConnector]:
        for _x, _y, item, sub_items in self.items:
            if isinstance(item, WebUIConnector):
                yield item
            yield from itertools.chain.from_iterable(i.get_connectors() for i in sub_items)

    async def render(self) -> str:
        return await jinja_env.get_template("widgets/imagemap.htm").render_async(
            items=self.items, image_url=self.image_url, max_width=self.max_width
        )


class ImageMapLabel(WebDisplayDatapoint[T]):
    def __init__(self, type_: Type[T], format_string: str = "{}", color: str = ""):
        self.type = type_
        super().__init__()
        self.color = color
        self.format_string = format_string

    def convert_to_ws_value(self, value: T) -> Any:
        return self.format_string.format(value)


jinja_env.tests["imageMapLabel"] = lambda item: isinstance(item, ImageMapLabel)
