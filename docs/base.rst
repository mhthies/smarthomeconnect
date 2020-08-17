
Smart Home Connect Base Concepts
================================

Smart Home Connect does not bring a configuration language like the YAML-based configuration files of *HomeAssistant* or *SmartHomeNG*.
It also does not include a graphical editor or web interface for configuring your smart devices and interconnecting or automating them.
Instead, Smart Home Connect is a framework for building smart home applications in Python 3.
It works as a library, providing the building blocks for your application, like interfaces for different communication protocols, timers to trigger your logic/automation functions and a web user interface with many components.


Connectable Objects
-------------------

.. py:currentmodule:: shc.base

The core concept of building up a home automation application with SHC is connecting *Connectable* objects.
A *Connectable* object is a Python object that produces, consumes or stores values of a certain type.
It may implement one or more of the following traits (i.e. inherit from these classes):

* :class:`Writable`:
  The object can be updated with a new value via its :meth:`Writable.write` method.
  It will use this value to update its internal state or send it to an external bus/interface/database/etc.
* :class:`Readable`:
  The object has a current value that can be retrieved via its :meth:`Readable.read` method.
* :class:`Subscribable`:
  The object produces new values occasionally (e.g. received values from an external interface) and publishes them to its subscribers.
  A subscriber is a *Writable* object, that has been registered via the *Subscribable* object's :meth:`Subscribable.subscribe` method.
* :class:`Reading`:
  The object needs to *read* a value in certain situations.
  This may be an optional additional feature of the object (e.g. a KNX GroupAddress object answering to GroupRead telegrams) or mandatory for the object's functionality (e.g. a web UI widget which needs to get the current value, when a new client connects). This is denoted by the `is_reading_optional` attribute of the object (class or instance attribute).
  In any case, the object tries to *read* the value of it's *default provider* in such situations, which is a *Readable* object, registered via the :meth:`Reading.set_provider` method.

.. note::
    Not every *Connectable* object is *Readable*:
    A connector object for a bus address, for example, may send and receive values to/from the bus (i.e. it is *Writable* + *Subscribable*) but it does not have a "current value", which can be read.
    To cache the latest received value and make it *Readable*, the object must be combined with a :class:`shc.Variable` object.


The ``connect`` Method
----------------------

Typically, you'll want to connect two *Connectable* objects bidirectional, such that new values from one object are send/*published*/*written* to the other and vice versa.
Thus, you'll usually need two ``subscribe()`` calls and probably additional ``set_provider()`` calls.
To shorten this procedure, every *Connectable* object provides the :meth:`shc.base.Connectable.connect` method.
It connects two *Connectable* objects by

* subscribing each to the other if applicable (i.e. it is *Writable* and the other one is *Subscribable*) and
* setting each as the other's *default provider* if applicable (i.e. it is *Readable* and the other is *Reading*) and the other has *reading_is_mandatory*.

The default behaviour can be customized via the ``send``/``receive`` arguments (for subscribing) resp. the ``provide``/``read`` arguments (for registering as *default provider*).

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


.. _base.event-origin:

The ``origin`` of an Event
--------------------------

When updating an object's value using the :meth:`Writable.write` method, a second argument must be provided, called ``origin``.
It is expected to be a list of all objects that led to the update being performed, i.e. the “trace” of the update event, starting with its origin (typically an external event source/interface or a timer) and up to the object or function which now calls the *write* method.
This list is used by *Subscribable* objects to avoid recursive feedback loops:
When publishing a value, all subscribers which are already included in ``origin`` are automatically skipped, as they took part in causing this publishing event and probably will cause the same event again, closing the feedback loop.

When calling :meth:`Writable.write` from within a logic handler, decorated with the :func:`shc.handler` decorator, the ``origin`` argument may omitted, since it is magically provided via a hidden environment variable.
See the following section for more details.


Logic Handlers
--------------

A logic handler is a Python function which is executed (“triggered”) by a *Subscribable* object when it publishes a new value.
To register a logic handler to be triggered by an object, use the object's :meth:`Subscribable.trigger` method.
This method can either be used in a functional style (``subscribable_object.trigger(my_logic_handler)``) or as a decorator for the logic handler (shown below).
For triggering logic handlers at defined times or in a fixed interval, the :mod:`shc.timer` module provides *Subscribable* timer objects which publish a *None* value at defined times.

Since SHC is completely relying on asyncio for (pseudo-)concurrency, all methods dealing with runtime events (including *reading* and *writing* values) are defined as asynchronous coroutines.
This also applies to logic handlers, which must be defined with ``async def`` accordingly.

When triggered, a logic handler is called with two parameters: The new value of the triggering object and the :ref:`origin <base.event-origin>` of the event, i.e. the list of objects publishing to/writing to/triggering one another, resulting in the logic handler being triggered.

For avoiding recursive feedback loops, the logic handler should skip execution when it (the function object) is contained in the *origin* list.
It should also appended itself to a copy of the list and pass it to all calls of *write* and other logic handlers.
To help with that, there's the :func:`shc.handler` decorator.
It automatically skips recursive execution and ensures passing of the correctly modified ``origin`` list to *write* calls via a hidden context variable.

Putting it all together, a logic handler looks as follows::

    timer = shc.timer.Every(datetime.timedelta(minutes=5))
    some_variable = shc.Variable()
    some_knx_object = knx_interface.group(shc.knx.KNXGAD(1, 2, 3), dpt="5")

    @timer.trigger
    @some_variable.trigger
    @shc.handler()
    async def my_logics(_value, origin):
        """ Write value of `some_variable` to KNX bus every 5 minutes & when it changes, but only for values > 42 """
        # We cannot use the value provided, since it is not defined when triggered by the timer
        value = await some_variable.read()
        if value > 42:
            await some_knx_object.write(value)


``shc.base`` Module Reference
-----------------------------

.. autoclass:: Writable
    :members:
.. autoclass:: Readable
    :members:
.. autoclass:: Subscribable
    :members:
.. autoclass:: Reading
    :members:

.. autodecorator:: shc.handler
