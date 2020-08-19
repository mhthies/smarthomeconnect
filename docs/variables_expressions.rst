
Variables and Expressions
=========================

Variables
---------

Variables are the most important *Connectable* objects in an SHC application.
They allow to keep track of the current state of some dynamic value (allowing to *read* it at any time), receive updates for that state and re-publish state changes to other connected objects.
Thus, they are typically used as a "central connection point" for a certain value, to which all other *Connectable* objects for that value are *connected*, as in the following example::

    ceiling_lights = shc.Variable(bool, "ceiling lights")\
    .connect(knx_connection.group(shc.knx.KNXGAD(1, 2, 3), dpt="1", init=True))

    web_index_page.add_item(shc.web.widgets.Switch("Ceiling Lights")
                            .connect(ceiling_lights))

However, they are not absolutely necessary to interconnect datapoints of different interfaces with SHC.
Especially, when dealing with stateless events (i.e. values which are used to trigger some action instead of representing a change in state), it is more appropriate (and probably even required) to *connect* the relevant objects directly::

    some_button = shc.web.widgets.StatelessButton(shc.knx.KNXUpDown.DOWN, "down")\
        .connect(knx_connection.group(shc.knx.KNXGAD(3, 2, 1), dpt="1.008"))




Expressions
-----------

TODO


