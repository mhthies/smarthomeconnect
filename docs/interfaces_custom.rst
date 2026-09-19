
Creating Custom Interfaces
--------------------------

Custom SHC interfaces allow you to let your SHC application communicate with other types of external systems.

The real magic of interface implementations comes from the *connectable* objects that they provide for interacting with specific data points of the external system (henceforth referred to as ‘Connector objects’.).
The interface class itself typically holds a reference or connection client to the external system and provides methods for constructing the Connector objects.
In many cases —depending on the external communication protocol—, the interface object also handles dispatching of received messages from the external system to the concerned Connector object(s).


Interface Startup and Shutdown
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

At application startup, each interface typically needs to initialize the underlying external connection and perhaps start a receive-loop task.
Both should be done *after* all connectable objects have been created, but *before* initial variable values are published.

For these purposes, interfaces should inherit from the :class:`shc.supervisor.AbstractInterface` class and implement its methods to integrate with SHC's application lifecycle functionality (see :ref:`application_start_stop`):

* :meth:`async start() <shc.supervisor.AbstractInterface.start>` is called for starting up the interface.
  It should initiate the external connection, start any required tasks and await full startup of the interface.
* :meth:`async stop() <shc.supervisor.AbstractInterface.stop>` is called for gracefully shutting down the interface.
  It should stop and await termination of all connections and running background tasks.
* :meth:`monitoring_connector() <shc.supervisor.AbstractInterface.monitoring_connector>` should return a *connectable* object for monitoring the interface status.
  See :ref:`monitoring`.

In case of a critical or unrecoverable failure within an interface (e.g. when the external system the interface connects to cannot be reached and the interface is deemed critical for the whole application), the interface's `start()` method can raise an exception *or* :func:`shc.supervisor.interface_failure` can be called.
Both will gracefully terminate the SHC application.

Using SupervisedClientInterface
"""""""""""""""""""""""""""""""

To simplify correct error handling and automatic reconnect for interfaces with a receive-loop task, interface classes can inherit from :class:`shc.interfaces._helper.SupervisedClientInterface`.
Then, instead of `start()` and `stop()`, the interface class needs to implement:

  * :meth:`async _connect() <shc.interfaces._helper.SupervisedClientInterface._connect>` – should connect (or reconnect) the underlying connection and return when established.
  * :meth:`async _run() <shc.interfaces._helper.SupervisedClientInterface._run>` – should set _running.set() and then spin in a loop to process messages etc. until `_disconnect()` is called.
  * :meth:`async _subscribe() <shc.interfaces._helper.SupervisedClientInterface._subscribe>` – can further initialize connection, when `_run()` is spinning (e.g. for sending MQTT-style subscriptions etc.)
  * :meth:`async _disconnect() <shc.interfaces._helper.SupervisedClientInterface._disconnect>` – should gracefully terminate the underlying connection, make `_run()` return and await full termination.

Based on these method implementations, the `SupervisedClientInterface` base class provides the `start()` and `stop()` coroutines, which handle calling of the above methods in the right sequence.
It will also handle exceptions, which may be raised from any of those, monitor timeouts for `_connect()` and `_subscribe()` and check for unexpected return of `_run()` (without explicit call to `stop()`).
In any of those error conditions, a reconnect will be attempted with an exponential backoff delay, or —when `auto_reconnect` is disabled— a graceful application shutdown will be initiated.
In addition, a :class:`SubscribableStatusConnector` is provided by the `monitoring_connector()` method, which updates its `status` and `message` automatically, based on the current connection state.

Thus, In case of an error, all of the `SupervisedClientInterface` methods shall simply raise an exception to trigger a coordinated reconnection (or shutdown) procedure.


Interface Implementation Guidelines
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

First, I'd recommend to read the full introduction of SHC *connectable* objects: :ref:`base.connectable_objects`.
In addition, see :ref:`datatypes` for information for recommendations about which data types to use with SHC and how to integrate custom types with SHC.

The following sections describe further topics that need to be considered when implementing SHC interfaces.

asyncio Compatibility
"""""""""""""""""""""

SHC is fully based on asynchronous coroutines and an asyncio event loop, running in a single OS-level thread.
All interface methods (`start()` etc.) and the *connectable object*'s methods (`read()`, `write()` etc.) are called within the event loop thread.

.. warning::

    Thus, none of these methods must *block* the thread, e.g. with synchronous network/file operations, sleeping, waiting for `threading.Lock`, `threading.Event` etc.
    Instead, proper async libraries with *awaitable* objects and coroutines must be used.

Typical approaches:

* for HTTP-based interfaces (client or server, incl. websockets), use `aiohttp <https://pypi.org/project/aiohttp/>`__
* for MQTT-based interfaces, use SHC's own :class:`shc.interfaces.mqtt.MQTTClientInterface`
* for (virtual or physical) serial ports, use `pyserial-asyncio <https://pypi.org/project/pyserial-asyncio/>`__
* for filesystem access, use `aiofile <https://pypi.org/project/aiofile/>`__

If no async implementation is available, make sure that blocking code runs in a separate thread and interaction with SHC code is decoupled via callback functions.
You can make use of ``asyncio.run_coroutine_threadsafe()`` or ``asyncio.AbstractEventLoop.call_soon_threadsafe()`` to dispatch callbacks into the asyncio event loop.
(See source code of SHC's :class:`shc.interfaces.midi.MidiInterface` for an example.)
``asyncio.wrap_future()`` can be used to wait for results from separate threads without blocking the event loop.

Construction Outside Of Event Loop
""""""""""""""""""""""""""""""""""

The recommended way to setup a larger-scale SHC application is to statically construct the Interfaces and *connectable objects* in multiple Python modules, then import all those modules into a main file, and finally start the asyncio event loop via :func:`shc.supervisor.main`.
This requires that the Interface objects and *Connector objects* can be constructed **before** an asyncio event loop is running!

.. warning::

    Do not create *asyncio.Queue()*, *asyncio.Event()* or *asyncio.Future()* within the ``__init__()`` method of an Interface or *Connector object*.
    These classes require to be constructed *within* an event loop (depending on the Python version).

    Instead, initialize such member variables in your interface class as ``None`` and defer creation of the objects to the ``start()`` coroutine of the interface.
    See source code of :class:`shc.interfaces.file_persistence.FilePersistenceStore` for an example.

Handling Value Updates Correctly
""""""""""""""""""""""""""""""""

*Writing* to a *writable* Interface Connector object should asynchronously *await* the completed delivery of the value update to the external system.
I.e., the :meth:`_write() <shc.base.Writable._write>` method should only return when the new value has been fully processed by the external system.
This is required for SHC to detect concurrent conflicting value updates from different origins correctly and ensure synchronized states in this case.

If sending the value update to the external system fails (for any reason), the `_write()` method shall raise an Exception.

Interface Connector objects that are *subscribable* **and** *writable* should write back local value updates (calls to ``write()``) to all subscribers (similar to how :class:`UpdateExchange <shc.misc.UpdateExchange>` behaves).
In this case, the value update shall be written to *subscribed* objects only **once** and the ``origin`` value of the value update (see :ref:`base.event-origin`) must be preserved!
This is required for SHC to prevent endless recursive update loops between two interfaces.
In addition, the ``_stateful_publishing`` attribute of these Connector objects must be set to ``True`` to enable the before-mentioned conflicting value update detection.

.. note::

    If the external system itself reflects the sent values back to the SHC application, the interface implementation needs to distinguish them from genuine external updates, in order to avoid *writing* the reflected updates back to *Subscribers* of the Connector object **without the correct origin**.
    This may require temporary caching of the sent values for recognition of the reflected values, if the interface does not provide means to determine if the value update has been created by the SHC interface.
    (MQTT is an example of a protocol where this is necessary, as MQTT messages do not carry information about the originating MQTT client.)

    This temporary caching of the sent values and update recognition mechanism can then also be used to determine when the new value has been fully processed by the external system, so the `_write()` method can return.
    Unfortunately, this whole mechanism tends to get quite complex.
    See source code of :meth:`shc.interfaces.mqtt.AbstractMQTTTopicVariable._write` for an example implementation of this mechanism.

Implementing this behaviour might become easier when there is only a single Connector object for each data point (endpoint / variable / topic / routing key / etc.) of the external system.
Thus, it is recommended that the created Connector objects of an interface are cached, so the Interface's methods will return the same Connector object instance when a Connector for the same data point is requested multiple times.


Interface Examples
^^^^^^^^^^^^^^^^^^

TODO example with Connector object and dispatching from websocket

TODO example with MQTT



Interface Base and Helper Classes Reference
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

.. autoclass:: shc.supervisor.AbstractInterface
    :members:

.. autofunction:: shc.supervisor.interface_failure


.. automodule:: shc.interfaces._helper

    .. autoclass:: ReadableStatusInterface

        .. automethod:: _get_status

    .. autoclass:: SubscribableStatusInterface

    .. autoclass:: SubscribableStatusConnector

        .. automethod:: update_status

    .. autoclass:: SupervisedClientInterface

        .. automethod:: __init__
        .. automethod:: _connect
        .. automethod:: _run
        .. automethod:: _subscribe
        .. automethod:: _disconnect
        .. automethod:: wait_running
