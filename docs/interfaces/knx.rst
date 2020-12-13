
KNX Interface
=============

.. py:currentmodule:: shc.interfaces.knx

Smart Home Connect allows to interconnect with KNX home automation systems.
Actually, it has initially been built for providing a web interface and additional connectivity for a KNX bus system.
For connecting to a KNX system, it requires the ``knxdclient`` Python library and a running KNXD (KNX deamon, formerly known as EIBD).
``knxdclient`` is an asynchronous Python implementation of KNXD's native client protocol (or at least relevant parts of it) and was originally developed as part of SHC.

TODO setting up KNXD

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

.. note::
    For KNX group addresses, that represent events or commands (like Up/Down) instead of state (like On/Off), you typically don't want to use SHC Variables!
    See :ref:`variables`.


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


Relevant classes from ``knxdclient``
------------------------------------

.. py:currentmodule:: knxdclient

.. autoclass:: KNXTime

.. autoclass:: GroupAddress
