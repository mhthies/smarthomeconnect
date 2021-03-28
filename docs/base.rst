
Smart Home Connect Base Concepts
================================

Smart Home Connect does not bring a configuration language like the YAML-based configuration files of *HomeAssistant* or *SmartHomeNG*.
It also does not include a graphical editor or web interface for configuring your smart devices and interconnecting or automating them.
Instead, Smart Home Connect is a framework for building smart home applications in Python 3.
It works as a library, providing the building blocks for your application, like interfaces for different communication protocols, timers to trigger your logic/automation functions and a web user interface with many components.


.. _base.connectable_objects:

Connectable Objects
-------------------

.. py:module:: shc.base

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
  This may be an optional additional feature of the object (e.g. a KNX GroupAddress object answering to GroupRead telegrams) or mandatory for the object's functionality (e.g. a web UI widget which needs to get the current value, when a new client connects). This difference is denoted by the `is_reading_optional` attribute of the object (class or instance attribute).
  In any case, the object tries to *read* the value of it's *default provider* in such situations, which is a *Readable* object, registered via the :meth:`Reading.set_provider` method.

.. note::
    Not every *Connectable* object is *Readable*:
    A connector object for a bus address, for example, may send and receive values to/from the bus (i.e. it is *Writable* + *Subscribable*) but it does not have a "current value", which can be read.
    To cache the latest received value and make it *Readable*, the object must be combined with a :class:`shc.Variable` object.


.. _base.connect:

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
        knx_connection = shc.interfaces.knx.KNXConnector()
        web_interface = shc.web.WebServer("localhost", 8080, "index")

        variable = shc.Variable(bool, "variable's name")
        knx_group_address = knx_connection.group(shc.interfaces.knx.KNXGAD(1, 2, 3), dpt="1")
        variable.subscribe(knx_group_address)
        knx_group_address.subscribe(variable)

        switch_widget = shc.web.widgets.Switch("Switch Label")
        variable.subscribe(switch_widget)
        switch_widget.subscribe(variable)
        switch_widget.set_provider(variable)

    Using the ``connect()`` method, it can be shortened to::

        import shc
        knx_connection = shc.interfaces.knx.KNXConnector()
        web_interface = shc.web.WebServer("localhost", 8080, "index")

        variable = shc.Variable(bool, "variable's name")\
            .connect(knx_connection.group(shc.interfaces.knx.KNXGAD(1, 2, 3), dpt="1"))
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


.. _base.typing:

Typing of Connectable Objects
-----------------------------

Connectable objects are statically typed.
This means, each object is supposed to handle (receive/publish/provide/read) only values of a defined Python type.
The object's type is indicated by its ``type`` attribute, which may be a class attribute (if the *Connectable* class specifies a fixed value type) or an instance attribute (for generic *Connectable* classes like :class:`shc.Variable`, where each instance may handle values of a different type).

The instance-specific ``type`` of generic *Connectable* classes may either be given to each object explicitly (as an argument to its *__init__* method as for :class:`shc.Variable`) or derived from other properties of the object (like the KNX Datapoint Type of :class:`shc.interfaces.knx.KNXGroupVar` objects).

When connecting two *Connectable* objects using :meth:`Connectable.conect`, :meth:`Subscribable.subscribe` or :meth:`Reading.set_provider`, the consistency of the two objects' ``type`` attributes are checked and a *TypeError* is raised if they don't match.
In many cases, you'll still want to connect those objects and make sure, the value is adequately converted when being written to/read from the other object.
For this purpose, the *connect*, *subscribe* and *set_provider* methods provide an optional argument ``convert``.

If ``convert=True`` is specified, the :mod:`shc.conversion` module is searched for a default conversion function for the relevant value types (using :func:`shc.conversion.get_converter`).
In case there is not default conversion for the relevant types or you want to convert values in a different way, *subscribe*, *set_provider* and *connect* allow to pass callables to the ``convert`` argument (e.g. a lambda function or function reference), which are used to convert the values exchanged via this particular subscription/Reading object.
Since *connect* can establish a connection between two objects in both directions, its ``convert`` parameter takes a tuple of two callables: ``a.connect(b, convert=(a2b, b2a))``, where ``a2b()`` is a function to convert *a*'s type to *b*'s type and ``b2a()`` a function for the other direction.

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

    We can shorten this by using the ``connect`` method::

        var1 = shc.Variable(int)
        var2 = shc.Variable(float)
        var1.connect(var2, convert=(lambda x: x, lambda x: ceil(x))


.. _base.logic-handlers:

Logic Handlers
--------------

A logic handler is a Python function which is executed (“triggered”) by a *Subscribable* object when it publishes a new value.
To register a logic handler to be triggered by an object, use the object's :meth:`Subscribable.trigger` method.
This method can either be used in a functional style (``subscribable_object.trigger(my_logic_handler)``) or as a decorator for the logic handler (as shown in the example below).
For triggering logic handlers at defined times or in a fixed interval, you may use a :ref:`Timer <timer>`.

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
    some_knx_object = knx_interface.group(shc.interfaces.knx.KNXGAD(1, 2, 3), dpt="5")

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

    If you're logic handler function does not need to interact with asynchronous functions (i.e. not read or write *Connectables*' values or trigger other logic handlers), you may write it as a non-async function and use the :func:`shc.blocking_handler` decorator, which does the thread executor scheduling::

        @shc.blocking_handler()
        def my_blocking_logic_handler(value, _origin):
            with open('/tmp/hello.txt', 'w') as f:
                f.write("Hello, World!")

            some_result = some_cpu_heavy_calculation(value)

            # Unfortunately, no .write() or .read() possible here.


.. _base.synchronous_subscriptions:

Synchronous vs. Asynchrounous Subscriptions
-------------------------------------------

By default, all subscriptions to *Subscribable* objects are *synchronous*.
This means, the publishing a value (via :meth:`_publish <Subscribable._publish>`) awaits the completion of *writing* the value to all subscribers.
Since *writing* a value to *Writable*+*Subscribable* objects (like :class:`Variables <shc.variables.Variable>`) typically awaits the successful value publishing to the object's own subscribers, the chain of subscriptions is synchronous as a whole.

.. admonition:: Example

    Take the following example of a variable, which is connected to two KNX group addresses, one directly, one to an :ref:`Expression <expressions>` for the variable's value plus 5::

        knx = shc.interfaces.knx.KNXConnector()

        var = shc.Variable(int)
        var.connect(knx.group(shc.interfaces.knx.KNXGAD(0,0,1), "7")
        var_plus_five = var.EX + 5
        knx.group(shc.interfaces.knx.KNXGAD(0,0,2), "7").subscribe(var_plus_five)

    In this example, *writing* a new value to the variable via ``await var.write(7, origin)`` will await the sending of KNX telegrams for both group addresses to the KNX bus.
    Publishing the variable's value to the first KNX group address and publishing it to the expression (and thus to the second KNX group address) is done in parallel, but the *_publish()* method (and thus the *write()* method) will wait for both to complete.
    If an exception occurs in one or more of the publishing "paths", it is indicated by raising a :class:`PublishError`.

In general, this is not a problem, even when forwarding a value to an external interface takes some time, because SHC can process multiple value updates in parallel if the originating interface publishes each value in a new asyncio Task.
However, Variables (and other objects) include a :ref:`locking mechanism <base.locking>` to serialize value updates, such that only one value update of that variable can be published at a time.
I.e., if a variable has multiple subscribers and one of them takes some time to complete *writing* a value, closely following value updates can be delayed.

To avoid this effect, subscriptions can be configured to be *asynchronous*, using the ``sync`` parameter of :meth:`Subscribable.subscribe`::

    some_variable.subscribe(some_unimportant_interface_object, sync=False)

Asynchronous subscriptions will not raise Exceptions up to the publishing object!
However, Exceptions occurring while publishing a value update are still logged via the Python logging facilities.

Similar to subscriptions, the **triggering of logic handler functions** can be configured to be synchronous or asynchronous.
Triggering functions from Subscribable objects is *asynchronous* by default, but can be manually configured to be synchronous via the ``sync`` parameter of :meth:`Subscribable.trigger`.
Unfortunately, this is not possible when using `trigger` as a decorator.
It also requires special caution when *writing* or synchronously *publishing* to another object from within the logic handler to avoid deadlocks.


.. _base.locking:

Shared Locking Mechanism
------------------------

One problem with with (pseudo-)parallel processing of multiple value updates is consistency of values stored in multiple connected variables and published to external interfaces:
When multiple value updates arrive at the same time from different interfaces, they may "cross over" each other somewhere in the subscriptions within SHC.
Thus, the order of values published to external interfaces would differ and multiple connected variables would store different values.

To solve this issue, :class:`Variables <shc.Variable>` use a "shared lock" by inheriting from :class:`HasSharedLock` (other *Connectable* objects can do this as well).
The shared lock is a mutex, that is locked by each Variable while updating the stored value and publishing the value update to synchronous subscribers.
Thus, only one value update can processed at a time, effectively serializing the value updates.
The mutex is shared across each group of synchronously connected Variables/objects, such that only one value update can processed at a time in this whole group.

It's really important that the mutex is shared across all synchronously connected objects.
Otherwise, two crossing-over value updates of two connected Variables would result in a deadlock, where each Variable waits for the acquiring the other's mutex before releasing their own.

To share the lock of a *Subscribable* object with a subscriber, which is :class:`HasSharedLock`, the :meth:`Subscribable.share_lock_with_subscriber` method is called.
**This is automatically done** by :meth:`Subscribable.subscribe` for synchronous subscriptions.
So, typically, you don't need to worry about this locking mechanism, when using SHC to build your smart home application.
Just make sure to avoid using asynchronous subscriptions when *connecting* multiple variables (e.g. for the purpose of type conversion) – it would disable the lock sharing, so the consistency is not guaranteed.

.. warning::

    :meth:`Subscribable.share_lock_with_subscriber` is **not** automatically called when *triggering* a :ref:`Logic Handler <base.logic-handlers>` synchronously from a Subscribable object.
    If you use a **synchronously** triggered logic handler to synchronously *write* a value to another :class:`HasSharedLock` object (e.g. a Variable), you **must** make sure to manually share the locks of the Subscribable object and the Writable object::

        some_variable = shc.Variable(int)
        another_variable = shc.Variable(int)

        @shc.handler()
        async def my_handler(value, _origin) -> None:
            await another_variable.write(value + 1)  # synchronously write to another_variable. It HasSharedLock.

        some_variable.trigger(my_handler, sync=True)  # my_handler is triggered synchronously by some_variable
        some_variable.share_lock_with_subscriber(another_variable)  # <-- this is important!

    Otherwise a (direct or indirect) subscription in the other direction can eventually result in a deadlock, which will be really ugly to debug in practice.

.. warning::

    Additional precautions are necessary, when you design a custom object, that republishes value updates of other Subscribable objects (like :ref:`variables`, :ref:`expressions`, :class:`shc.misc.Hysteresis`, :class:`shc.misc.BreakableSubscription`, etc.).
    Please read the documentation of :meth:`Subscribable.share_lock_with_subscriber` for further information.


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
    .. automethod:: share_lock_with_subscriber

.. autoclass:: Reading

    .. automethod:: set_provider
    .. automethod:: _from_provider

.. autodecorator:: shc.handler

.. autodecorator:: shc.blocking_handler

.. autoclass:: UninitializedError

.. autoclass:: PublishError

.. autoclass:: HasSharedLock

    .. automethod:: acquire_lock
    .. automethod:: release_lock
    .. automethod:: _share_lock_with
