
Variables and Expressions
=========================

Variables
---------

.. py:currentmodule:: shc.variables

Variables are the most important *Connectable* objects in an SHC application.
They allow to keep track of the current state of some dynamic value (allowing to *read* it at any time), receive updates for that state and re-publish state changes to other connected objects.
Thus, they are typically used as a "central connection point" for a certain value, to which all other *Connectable* objects for that value are *connected*, as in the following example::

    ceiling_lights = shc.Variable(bool, "ceiling lights")
    ceiling_lights.connect(knx_connection.group(shc.knx.KNXGAD(1, 2, 3), dpt="1", init=True))

    web_switch = shc.web.widgets.Switch("Ceiling Lights")\
        .connect(ceiling_lights)

.. note::

    However, *Variables* are not absolutely necessary to interconnect datapoints of different interfaces with SHC.
    Especially, when dealing with stateless events (i.e. values which are used to trigger some action instead of representing a change in state), it is more appropriate to *connect* the relevant objects directly::

        some_button = shc.web.widgets.StatelessButton(shc.knx.KNXUpDown.DOWN, "down")
        some_button.connect(knx_connection.group(shc.knx.KNXGAD(3, 2, 1), dpt="1.008"))

    In such cases, it is even harmful to use a variable as a middle link, since it only publishes **changes** in value and suppresses updates of an unchanged value.

*Variables* are :class:`shc.base.Readable` (providing their current value), :class:`shc.base.Writable` (to update the value) and :class:`shc.base.Subscribable` (to publish changes of the value).
In addition, they are optionally :class:`shc.base.Reading` for initialization purposes:
When a default provider is set, they will *read* its value once, immediately after startup of SHC, to initialize their value.

The value type of a variable must be given when it is instantiated.
Optionally, a name and and initial value can be provided:

.. automethod:: shc.variables.Variable.__init__


Tuple Field Access
^^^^^^^^^^^^^^^^^^

When Variables are used with a value type based on :class:`typing.NamedTuple`, they provide a special feature to access the individual fields of the tuple value:
For each (type hinted) field of the named tuple type, a :class:`VariableField` is created as an attribute of the *Variable* object, named after the tuple field.
These objects are *Connectable* (taking their ``type`` attribute from the NamedTuple field's type hint), which allows to subscribe other objects to that field's value or let the field be updated from another *Subscribable* object::

    from typing import NamedTuple

    class Coordinate(NamedTuple):
        x: float
        y: float

    var1 = shc.Variable(Coordinate, initial_value=Coordinate(0.0, 0.0))
    # `var1` automatically gains two attributes 'x' and 'y' to access the value's 'x' and 'y' fields.
    # They are Connectables of `float` type, so we can connect them to a KNX GroupVariable with DPT 9:
    var1.x.connect(knx_connection.group(shc.knx.KNXGAD(1, 2, 0), dpt="9"))
    var1.y.connect(knx_connection.group(shc.knx.KNXGAD(1, 2, 1), dpt="9"))

    @var1.trigger
    @shc.handler()
    async def my_handler(value, _origin):
        # This handler is triggered on any change of the var1 value, even if it originates from one of
        # the VariableFields. We could check the `origin` list here to find out about the source of the
        # update.
        if value.x > value.y:
            print("Value is in lower right half of the coordinate plane")


Expressions
-----------

.. py:currentmodule:: shc.expressions

TODO


