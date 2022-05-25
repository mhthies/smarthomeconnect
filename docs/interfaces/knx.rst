
KNX Interface
=============

.. py:currentmodule:: shc.interfaces.knx

Smart Home Connect allows to interconnect with KNX home automation systems.
Actually, it has initially been built for providing a web interface and additional connectivity for a KNX bus system.
For connecting to a KNX system, it requires the ``knxdclient`` Python library and a running KNXD (KNX deamon, formerly known as EIBD).
``knxdclient`` is an asynchronous Python implementation of KNXD's native client protocol (or at least relevant parts of it) and was originally developed as part of SHC.

Setting up KNXD
---------------

KNXD is curently only available for unixoid operating systems (esp. Linux).
However, you don't have to run the KNXD on the same machine as SHC, as the knxdclient library can connect to KNXD via a TCP network port.
The installation instructions for KNXD depend on the specific OS and distribution:

On modern Debian and Ubuntu systems (≥ Debian 10 buster, including Raspbian, or Ubuntu 20.04 focal), KNXD is packaged in the official software repositories and can be installed with a simple::

    sudo apt install knxd

For other systems, head over to https://github.com/knxd/knxd, select the git branch for your specific distribution and follow the instructions in the *Building* section of the `README.md` file.

Afterwards, KNXD must be configured to be started as a service with the correct command line arguments to connect to your KNX bus via some interface (typically IP or USB) and provide a "local-listener" on a TCP port or UNIX socket for SHC to connect to.
A reference of all available arguments can be found at https://github.com/knxd/knxd/wiki/Command-line-parameters.
The Debian and Ubuntu packages already include a systemd unit to run KNXD as a service with a local listener at TCP port 6720 and `/run/knx`.
Additional commandline arguments for KNXD (e.g. for specifying the bus interface) can be configured in the `/etc/default/knxd` on these Linux distributions.



Configuration Examples
----------------------

The following example demonstrates a minimal configuration for connecting an SHC `bool` variable to KNX group address 1/2/4 with datapoint type 1.xxx (which is typical for controlling light switches)::

    import shc
    import shc.interfaces.knx
    from shc.interfaces.knx import KNXGAD

    knx_connection = shc.interfaces.knx.KNXConnector(host='localhost', port=6720)  # Connect to KNXD

    my_group_address = knx_connection.group(KNXGAD(1,2,4), '1')  # datapoint type (dtp) '1' is a general bool (1.xxx)

    my_variable = shc.Variable(bool, "my cool variable")\
        .connect(my_group_address)

    # Start SHC event loop
    shc.main()


Group Read Telegrams
^^^^^^^^^^^^^^^^^^^^

If you have a device in your KNX system, which responds to *group read* telegrams (i.e. (R)EAD flag is set), you can initialize the value of the variable with the current state from the KNX system by using the ``init`` parameter of :meth:`KNXConnector.group`::

    my_group_address = knx_connection.group(KNXGAD(1,2,4), '1', init=True)

It tells the `KNXConnector` to send a *group read* telegram to this group address upon startup of SHC.
The response telegram will be consumed by SHC in the same way as usual *group write* telegrams.

SHC can respond to *group read* telegrams from other KNX devices itself by sending the current value of a *Readable* object.
To enable this functionality, simply provide a *default provider* (see :ref:`base.connectable_objects`) to the group address object, for example using the `read` and `provide` parameters of :meth:`shc.base.Connectable.connect`::

    my_group_address = knx_connection.group(KNXGAD(1,2,4), '1')

    my_variable = shc.Variable(bool, "my cool variable")\
        .connect(my_group_address, provide=True)


Datapoint Types
^^^^^^^^^^^^^^^

If the KNX group address represents a blind control (UP/DOWN), it is typically represented as KNX datapoint type '1.008' (DPT_UpDown).
This is only a special interpretation of a dpt '1.xxx', so it is binary-compatible to this type.
However, at least the author of this text often confuses the values, so there's special support for this type in SHC::

    my_blind_group_address = knx_connection.group(KNXGAD(1,2,6), '1.008')

On the KNX side, this group address object behaves just like the one defined above.
On the SHC side, it does not take plain ``bool`` values, but instead members of the :class:`KNXUpDown` enum, which are ``UP`` and ``DOWN``.
To satisfy SHC's type checking, we must only connect it to other *Connectable* objects of type :class:`KNXUpDown` or use the `convert` functionality (see :ref:`base.typing`).

For a full list of supported KNX datapoint types and the corresponding SHC Python types, see :meth:`KNXConnector.group`.

.. warning::
    For KNX group addresses, that represent events or commands (like Up/Down) instead of state (like On/Off), you typically don't want to use SHC Variables!
    Please read the following section for more information.


Stateless Group Objects
^^^^^^^^^^^^^^^^^^^^^^^

In its modular publish-subscribe-based structure, SHC is inherently capable of dealing with stateless group addresses, i.e. group addresses that represent events or commands (like Up/Down) instead of state (like On/Off).
However, :ref:`as noted in the ‘Variables’ section <variables.stateless>` you **must not** use :class:`shc.variables.Variable` objects to connect such group addresses to other SHC *Connectable* objects, like Buttons in the web user interface:
A *Variable* only forwards value updates to all its subscribers *if the value changes*.
Thus, moving your blinds in the same direction twice from a web UI button, for example, will not work with a *Variable* between the button and the KNX group address.

On the other hand, you also *don't need* a variable in such cases, because there *is* no state to be cached and you will only use *Connectable* objects that do not need to *read* the current state (e.g. :class:`shc.web.widgets.StatelessButton` instead of :class:`shc.web.widgets.ToggleButton`).
So you can simply connect the objects *immediately* to forward events between them.
For example, to move your blind's down via UI button::

    some_button = shc.web.widgets.StatelessButton(shc.interfaces.knx.KNXUpDown.DOWN, "down")
    my_blind_group_address = knx_connection.group(KNXGAD(1,2,6), '1.008')

    some_button.connect(my_blind_group_address)

… or, to react to an incoming telegram on that group address::

    my_blind_group_address = knx_connection.group(KNXGAD(1,2,6), '1.008')

    @my_blind_group_address.trigger
    @shc.handler()
    async def on_blinds_move(direction, origin):
        if direction is shc.interfaces.knx.KNXUpDown.DOWN:
            print("Blinds are moving down")


Central Functions and Status Feedback
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

The modular structure of SHC also allows us to connect a Variable (or other *Connectable* objects) to multiple KNX group addresses.
This is required for central functions and status-feedback addresses in KNX systems.
In doing so, though, you have to be careful not to create any undesired effects, like feedback loops or unwanted central switching telegrams.
This is where the ``send``/``receive`` parameters of the :ref:`connect method <base.connect>` method and—in more complicated cases—the :class:`shc.misc.TwoWayPipe` will become handy.

Let's assume that you have two **central group addresses**, one to switch (off) all lights on the ground floor and one for *all* lights::

    central_lights_ground_floor = knx_connection.group(KNXGAD(0,0,5), '1')
    central_lights_all = knx_connection.group(KNXGAD(0,0,1), '1')

    group_light_kitchen = knx_connection.group(KNXGAD(1,2,1), '1')
    group_light_living_room = knx_connection.group(KNXGAD(1,3,1), '1')
    ...

In the parameterization of the KNX application programs of your switching actuators and wall-mounted switches, you will use the individual lights' group addresses as primary (send) group address and add the two *central* group addresses as multiple listening addresses.
This way, the switching actuators of each light react to all three addresses and the wall-mounted switches will update their internal state and status LEDs correctly when one of the central functions is used.

In SHC, we can connect to group addresses in the same way, using ``send=False`` (resp. ``receive=False``) to turn off forwarding values to KNX group address objects where undesired.
But watch out, this simple approach will probably not yet do, what you expect::


    # WARNING! This will probably not do, what you want
    light_kitchen = shc.Variable(bool)\
        .connect(group_light_kitchen)\
        .connect(central_lights_ground_floor, send=False)\
        .connect(central_lights_all, send=False)

The problem with this approach is that SHC will route value updates from one of the group addresses to the others, in this case from `central_lights_ground_floor` and `central_lights_all` to `group_light_kitchen`:
When a telegram is received by `central_lights_all`, the variable `light_kitchen` is updated with that value and publishes the new value to all subscribers, including `group_light_kitchen`, which will send the value as a new telegram the KNX bus.
This is not required (because all relevant devices on the KNX bus are configured to listen to the central group address, anyway) and may even be harmful in some situations.
While SHC :ref:`does actually not send value updates back to their origin <base.event-origin>` to prevent internal feedback loops, in this case the two group address objects are considered to be separate objects, so forwarding the value update is not suppressed.
This is not considered a bug, as in other scenarios, you might actually want to reach this behaviour.

To prevent the undesired "cross-talk" between the connected group addresses, we can use a :class:`shc.misc.TwoWayPipe`:
It connects a number of *Connectable* objects to its left end with objects at its right end, **without** connecting the objects at either side among themselves.
In our case, we want to connect the `Variable` object to all the group address objects without establishing connections between them::

    light_kitchen = shc.Variable(bool)\
        .connect(shc.misc.TwoWayPipe(bool)
                 .connect_right(group_light_kitchen)
                 .connect_right(central_lights_ground_floor, send=False)
                 .connect_right(central_lights_all, send=False)
                 )

The usual internal feedback prevention of SHC will now ensure that value updates from the variable will only be send to the KNX bus if they did not pass the `TwoWayPipe` before, i.e. if they did not originate from the KNX bus.

The same trick can be used for **status-feedback group addresses**:
Let's say, you have a dimmer actuator that has two KNX datapoints: a boolean on/off state and a integer/range variable for the current dimming value.
The two datapoints are internally linked, such that sending a `false` value to the boolean datapoint will set the float datapoint to `0` and so on.
The dimmer actor will probably provide additional status-feedback datapoints, which can transmit the current state of both datapoints to separate group addresses when the state changed internally.
Let's further assume that we connected the datapoints to the four group addresses `1/4/1` (on/off), `2/4/1` (on/off state-feedback), `1/4/2` (value), `2/4/2` (value state-feedback).
Then we can connect these group addresses to SHC variables in the following way::

    dimmer_hallway_onoff = shc.Variable(bool)\
        .connect(shc.misc.TwoWayPipe(bool)
                 .connect_right(knx_connection.group(KNXGAD(1,4,1), '1'))              # on/off send
                 .connect_right(knx_connection.group(KNXGAD(2,4,1), '1'), send=False)  # on/off state-feedback
                 .connect_right(central_lights_ground_floor, send=False)               # on/off central function (as seen above)
                 )
    dimmer_hallway_value = shc.Variable(shc.datatypes.RangeUInt8)\
        .connect(shc.misc.TwoWayPipe(shc.datatypes.RangeUInt8)
                 .connect_right(knx_connection.group(KNXGAD(1,4,2), '5.001'))              # value send
                 .connect_right(knx_connection.group(KNXGAD(2,4,2), '5.001'), send=False)  # value state-feedback
                 )


Emulating a dimming actuator
^^^^^^^^^^^^^^^^^^^^^^^^^^^^

With SHC, you can create a KNX dimming actuator yourself, i.e. listen for incoming "Control Dimming" telegrams (KNX datapoint type 3.007) and adjust a percentage Variable in SHC accordingly.
This can be used to control non-KNX dimmable devices (such as a Tasmota-based LED strip) using a KNX wall switch with dimming function.

In theory, the KNX "Control Dimming" datatype supports differently sized steps, which can be directly applied to the value, via a :class:`FadeStepAdapter <shc.misc.FadeStepAdapter>`. We only need to convert the KNXControlDimming values to FadeStep values (via :class:`ConvertSubscription <shc.misc.ConvertSubscription>`, in the simplest way)::

    led_strip_brightness = shc.Variable(RangeFloat1, "LED strip brightness")
    led_strip_dimming_group = knx_interface.group(KNXGAD(4, 2, 9), "3")

    led_strip_brightness\
        .connect(shc.misc.FadeStepAdapter(
            shc.misc.ConvertSubscription(led_strip_dimming_group, FadeStep)))

However, at least some KNX wall switches only send start- and stop commands for dimming, i.e. a single dimming step of
+100% or -100%. Then, they expect the dimming actuator to apply this step gradually and stop at the current value when
a stop command is received. To emulate this behaviour with SHC, we need to replace the :class:`FadeStepAdapter <shc.misc.FadeStepAdapter>` with a
:class:`FadeStepRamp <shc.timer.FadeStepRamp>`::

    led_strip_brightness = shc.Variable(RangeFloat1, "LED strip brightness")
    led_strip_dimming_group = knx_interface.group(KNXGAD(4, 2, 9), "3")

    led_strip_brightness\
        .connect(shc.timer.FadeStepRamp(
            shc.misc.ConvertSubscription(led_strip_dimming_group, FadeStep),
            ramp_duration=datetime.timedelta(seconds=5), max_frequency=5.0))
    #           ↑ Full range dimming duration: 5 sec           ↑ max value update rate: 5 Hz    (⇒ 25 dimming steps)


``interfaces.knx`` Module Reference
-----------------------------------

.. automodule:: shc.interfaces.knx

    .. autoclass:: KNXConnector
        :members:

    .. autoclass:: KNXGAD
        :members:

    .. autoclass:: KNXHVACMode
        :members:
        :undoc-members:

    .. autoclass:: KNXUpDown
        :members:
        :undoc-members:

    .. autonamedtuple:: KNXControlDimming
        :members:
        :undoc-members:


Relevant classes from ``knxdclient``
------------------------------------

.. py:module:: knxdclient

.. autoclass:: KNXTime

.. autoclass:: GroupAddress
