
Smart Home Connect Base Concepts
================================

.. py:currentmodule:: shc.base

The core concept of building up a home automation application with shc is connecting *Connectable* objects.
A *Connectable* object is a Python object that produces, consumes or stores values of a certain type.
It may implement one or more of the following traits (i.e. inherit from these classes):

* :class:`Writable`:
  The object can be updated with a new value via its :meth:`Writable.write` method.
  It will use this value to update its internal state or send it to an external bus/interface/database/etc.
* :class:`Readable`:
  The object has a current value that can be retrieved via its :meth:`Readable.read` method.
* :class:`Subscribable`:
  The object produces new values occasionally (e.g. received values from an external interface) and publishes them to its subscribers.
  A subscriber is a *Writable* object, that has be registered via the *Subscribable* object's :meth:`Subscribable.subscribe` method.
* :class:`Reading`:
  The object needs to *read* a value in certain situations.
  This may be an optional additional feature of the object (e.g. a KNX GroupAddress object answering to GroupRead telegrams) or mandatory for the object's functionality (e.g. a web UI widget which needs the current value of an object, when a new client connects). This is denoted by the `is_reading_optional` attribute of the object (class or instance attribute).
  In any case, in such situations the object tries to *read* the value of it's *default provider*, which is a *Readable* object, registered with the :meth:`Reading.set_provider` method.

.. note::

    Not every *Connectable* object is *Readable*:
    A connector object for a bus address, for example, may send and receive values to/from the bus (i.e. it is *Writable* + *Subscribable*) but it does not have a "current value", which can be read.
    To cache the latest received value and make it *Readable*, the object must be combined with a :class:`shc.Variable` object.


The `connect` Method
--------------------

Typically, you want to connect two *Connectable* objects bidirectional, such that new values from one object are *written* to the other and vice versa.
Thus you'll usually need two ``subscribe()`` calls and probably additional ``set_provider()`` calls.
To shorten this procedure, every *Connectable* object provides the :meth:`shc.base.Connectable.connect` method.
It connects two *Connectable* objects by subscribing each to the other if applicable (i.e. it es *Writable* and the other one is *Subscribable*) and setting each as the other's *default provider* if applicable (i.e. it is *Readable* and the other is *Reading*) and the other has *reading_is_mandatory*.
The behaviour can be customized via the ``send``/``receive`` arguments (for subscribing) resp. the ``provide``/``read`` arguments (for registering as *default provider*).

.. admonition:: Example

    Connecting a switch widget in the web UI to a KNX Group Address via a *Variable* object for caching the value manually would look like this::

        import shc
        knx_connection = shc.knx.KNXConnector()
        web_interface = shc.web.WebServer("localhost", 8080, "index")

        variable = shc.Variable(bool, "variable's name")
        knx_group_address = knx_connection.group(shc.knx.KNXGAD(1, 2, 3), dpt="1")
        variable.subscribe(knx_group_address)
        knx_group_address.subscribe(variable)

        switch_widget = shc.web.widgets.Switch("Switch Label")
        variable.subscribe(switch_widget)
        switch_widget.subscribe(variable)
        switch_widget.set_provider(variable)

    Using the ``connect()`` method, it can be shortened to::

        import shc
        knx_connection = shc.knx.KNXConnector()
        web_interface = shc.web.WebServer("localhost", 8080, "index")

        variable = shc.Variable(bool, "variable's name")\
            .connect(knx_connection.group(shc.knx.KNXGAD(1, 2, 3), dpt="1"))
        switch_widget = shc.web.widgets.Switch("Switch Label")\
            .connect(variable)


Logic Handlers
--------------

TODO


`base` module Reference
-----------------------

.. autoclass:: Writable
    :members:
.. autoclass:: Readable
    :members:
.. autoclass:: Subscribable
    :members:
.. autoclass:: Reading
    :members:
