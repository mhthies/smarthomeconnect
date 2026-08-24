
Creating Custom Interfaces
--------------------------

Custom SHC interfaces allow you to let your SHC application communicate with other types of external systems.

The real magic of interface implementations comes from the *connectable* objects that they provide for interacting with specific data points of the external system.
The interface class itself typically holds a reference or connection client to the external system and provides methods for constructing the *connectable* objects.
In many cases—depending on the communication pattern—, the interface object also handles dispatching of received messages from the external system to the concerned *connectable* object(s), belonging to the interface.


Interface Startup and Shutdown
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

At application startup, each interface typically needs to initialize the underlying external connection and perhaps start a receive-loop task.
Both should be done after all connectable objects have been created, but before initial variable values are published.

For these purposes, interfaces should inherit from the :class:`shc.supervisor.AbstractInterface` class and implement its methods to integrate with SHC's application lifecycle functionality (see :ref:`application_start_stop`):

* :meth:`async start() <shc.supervisor.AbstractInterface.start>` is called for starting up the interface. It should initiate the external connection, start any required tasks and await full startup of the interface.
* :meth:`async stop() <shc.supervisor.AbstractInterface.stop>` is called for gracefully shutting down the interface. It should stop and await termination of all connections and running background tasks.
* :meth:`monitoring_connector() <shc.supervisor.AbstractInterface.monitoring_connector>` should return a *connectable* object for monitoring the interface status.
  See :ref:`monitoring`.

TODO call shc.supervisor.interface_failure() in case of unrecoverable error in interface start() or background task.

To simplify correct error handling and automatic reconnect for interfaces with a receive-loop task, interface classes can inherit from :class:`shc.interfaces._helper.SupervisedClientInterface`.
Then, instead of `start()` and `stop()`, the interface class needs to implement:

  * :meth:`async _connect() <shc.interfaces._helper.SupervisedClientInterface._connect>` – should connect (or reconnect) the underlying connection and return when established.
  * :meth:`async _run() <shc.interfaces._helper.SupervisedClientInterface._run>` – should set _running.set() and then spin in a loop to process messages etc. until _disconnect() is called.
  * :meth:`async _subscribe() <shc.interfaces._helper.SupervisedClientInterface._subscribe>` – can further initialize connection, when `_run()` is spinning (e.g. for sending MQTT-style subscriptions etc.)
  * :meth:`async _disconnect() <shc.interfaces._helper.SupervisedClientInterface._disconnect>` – should gracefully terminate the underlying connection, make `_run()` return and await full termination.

Based on these method implementations, the `SupervisedClientInterface` base class provides the `start()` and `stop()` coroutines, which handle calling of the above methods in the right sequence, handling exceptions which may be raised from any of those, handling of timeouts of `_connect()` and `_subscribe()`, reconnecting on error or unexpected disconnect with exponential backoff,  updating the SubscribableStatusConnector (status and message) with the current state, and calling interface_failure(), if retry is disabled.


Interface Implementation Guidelines
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

TODO make sure to use asyncio-compatible connection implementation. Typical approaches: aiohttp for HTTP clients (incl. websockets), shc.interface.mqtt for MQTT-based connections.
    If you need to use a thread-based client library, you can make use of ``asyncio.run_coroutine_threadsafe()`` or ``asyncio.AbstractEventLoop.call_soon_threadsafe()`` to dispatch into SHC's asyncio eventloop (like SHC's MIDI interface does).

TODO WARNING: make sure to not create asyncio.Queue(), asyncio.Event() or asyncio.Future() in the constructor. Instead, defer creation to the start() coroutine.

TODO caching of connectable objects


Interface Examples
^^^^^^^^^^^^^^^^^^

TODO example with connectable object and dispatching from websocket

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
