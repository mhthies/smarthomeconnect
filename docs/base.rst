
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

The ``origin`` of a New Value
-----------------------------

When updating an object's value using the :meth:`Writable.write` method, a second argument must be provided, called ``origin``.
It is expected to be a list of all objects that led to the update being performed, i.e. the “trace” of the update event, starting with its origin (typically an external event source/interface or a timer) and up to the object or function which now calls the *write* method.
This list is used by *Subscribable* objects to avoid recursive feedback loops:
When publishing a value, all subscribers which are already included in ``origin`` are automatically skipped, as they took part in causing this publishing event and probably will cause the same event again, closing the feedback loop.

When calling :meth:`Writable.write` from within a logic handler, decorated with the :func:`shc.handler` decorator, the ``origin`` argument may omitted, since it is magically provided via a hidden environment variable.
See the following section for more details.


Typing of Connectable Objects
-----------------------------

Connectable objects are statically typed.
This means, each object is supposed to handle (receive/publish/provide/read) only values of a defined Python type.
The object's type is indicated by its ``type`` attribute, which may be a class attribute (if the *Connectable* class specifies a fixed value type) or an instance attribute (for generic *Connectable* classes like :class:`shc.Variable`, where each instance may handle values of a different type).

The instance-specific ``type`` of generic *Connectable* classes may either be given to each object explicitly (as an argument to its *__init__* method as for :class:`shc.Variable`) or derived from other properties of the object (like the KNX Datapoint Type of :class:`shc.knxKNXGroupVar` objects).

When connecting two *Connectable* objects using :meth:`Connectable.conect`, :meth:`Subscribable.subscribe` or :meth:`Reading.set_provider`, the consistency of the two objects' ``type`` attributes are checked and a *TypeError* is raised if they don't match.
In many cases, you'll still want to connect those objects and make sure, the value is adequately converted when being written to/read from the other object.
For this purpose, the *connect*, *subscribe* and *set_provider* methods provide an optional argument ``convert``.

If ``convert=True`` is specified, the :mod:`shc.conversion` module is searched for a default conversion function for the relevant value types (using :func:`shc.conversion.get_converter`).
In case there is not default conversion for the relevant types or you want to convert values in a different way, *subscribe* and *set_provider* allow to pass a callable to the ``convert`` argument (e.g. a lambda function or function reference), which is used to convert the values exchanged via this particular subscription/Reading object.

.. admonition:: Example

    This code will raise a *TypeError*::

        var1 = shc.Variable(int)
        var2 = shc.Variable(float)
        var1.connect(var2)

    This code will make sure new values from ``var1`` are send to ``var2`` after being converted to its ``.type`` and vice versa, using the trivial int→float resp. float→int conversions::

        var1 = shc.Variable(int)
        var2 = shc.Variable(float)
        var1.connect(var2, convert=True)

    This code will work as well, but use the `ceil` function for converting float values to int::

        var1 = shc.Variable(int)
        var2 = shc.Variable(float)
        var1.subscribe(var2, convert=True)
        var2.subscribe(var1, convert=lambda x: ceil(x))


Logic Handlers
--------------

A logic handler is a Python function which is executed (“triggered”) by a *Subscribable* object when it publishes a new value.
To register a logic handler to be triggered by an object, use the object's :meth:`Subscribable.trigger` method.
This method can either be used in a functional style (``subscribable_object.trigger(my_logic_handler)``) or as a decorator for the logic handler (as shown in the example below).
For triggering logic handlers at defined times or in a fixed interval, the :mod:`shc.timer` module provides *Subscribable* timer objects which publish a *None* value at defined times.

Since SHC is completely relying on asyncio for (pseudo-)concurrency, all methods dealing with runtime events (including *reading* and *writing* values) are defined as asynchronous coroutines.
This also applies to logic handlers, which must be defined with ``async def`` accordingly.

When triggered, a logic handler is called with two parameters: The new value of the triggering object and the :ref:`origin <base.event-origin>` of the event, i.e. the list of objects publishing to/writing to/triggering one another, resulting in the logic handler being triggered.

For avoiding recursive feedback loops, the logic handler should skip execution when it (the function object) is contained in the *origin* list.
It should also appended itself to a copy of the list and pass it to all calls of *write* and other logic handlers.
To help with that, there's the :func:`shc.handler` decorator.
It automatically skips recursive execution and ensures passing of the correctly modified ``origin`` list to *write* calls via a hidden context variable.

Putting it all together, a logic handler may look as follows::

    timer = shc.timer.Every(datetime.timedelta(minutes=5))
    some_variable = shc.Variable(int)
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


.. warning::

    Since logic handlers are executed as asynchronous coroutines in the same AsyncIO event loop (thread) as all the logic of SHC, **they must not block the control flow**.
    This means, any function call which may block the execution for more than fractions of a millisecond (e.g. file I/O, network I/O, other synchronous system calls or CPU-heavy calculations) must be turned into an asynchronous call, which is *awaited*—allowing the event loop to schedule other coroutines in the meantime.
    This can be achieved by either replacing the blocking call with a call of an async function (using an AsyncIO-compatible library) or executing the blocking code in a different Python thread and awaiting its result with an AsyncIO Future (e.g. using :meth:`asyncio.loop.run_in_executor`).

    For example, instead of writing::

        @shc.handler()
        async def my_logic_handler(value, _origin):
            # DO NOT DO THIS!!! All of the following lines are blocking!
            with open('/tmp/hello.txt', 'w') as f:
                f.write("Hello, World!")

            some_result = some_cpu_heavy_calculation(value)


    … use::

        import asyncio
        import aiofile  # https://pypi.org/project/aiofile/

        @shc.handler()
        async def my_logic_handler(value, _origin):
            async with aiofile.AIOFile('/tmp/hello.txt', 'w') as f:
                await f.write("Hello, World!")

            loop = asyncio.get_event_loop()
            some_result = await loop.run_in_executor(None, some_cpu_heavy_calculation, value)


``shc.base`` Module Reference
-----------------------------

.. autoclass:: Connectable

    .. automethod:: connect

.. autoclass:: Writable

    .. automethod:: write
    .. automethod:: _write

.. autoclass:: Readable

    .. automethod:: read

.. autoclass:: Subscribable

    .. automethod:: subscribe
    .. automethod:: trigger
    .. automethod:: _publish

.. autoclass:: Reading

    .. automethod:: set_provider
    .. automethod:: _from_provider

.. autodecorator:: shc.handler
