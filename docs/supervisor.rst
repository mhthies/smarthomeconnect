
Start, Stop and Status Monitoring
=================================

A typical SHC application consists of multiple parallel activities that need to be initialized and gracefully stopped at shutdown:
Most *Interfaces* have an internal loop task for interacting with external systems and each of SHC's :ref:`timers <timer>` has an internal loop to wait for the next trigger time.
In addition, “initializable” *Reading* objects, like SHC :ref:`variables` need to read their initial value during startup.

For this purpose, the :mod:`shc.supervisor` module implements functions for controlling startup and shutdown of SHC applications.

The main entry point of SHC applications, after all objects have been constructed and *connected*, should be the :func:`shc.supervisor.main` function, we already encountered in the examples.
It performs the following startup procedure:

* Register a signal handler to initiate shutdown when receiving a SIGTERM (or similar)
* Start all interface instances via their :meth:`start() <shc.supervisor.AbstractInterface.start>` coroutine and await their successful startup
* Trigger initialization of variables via *read*
* Start timers (incl. :class:`Once <shc.timer.Once>` triggers)

When a shutdown is initiated, all interfaces (and the SHC timers) are stopped by calling and awaiting their :meth:`stop() <shc.supervisor.AbstractInterface.stop>` coroutine.
The SHC application only quits when all these coroutines have returned successfully.

When an interface fails starting up, it shall raise an exception from its :meth:`start() <shc.supervisor.AbstractInterface.start>` coroutine, which will interrupt the SHC startup process.

When an interface encounters a critical error during operation, after successful startup, it may call :func:`shc.supervisor.interface_failure` to initiate a shutdown.
In this case, SHC will wait for the remaining interfaces to stop and exit with an non-zero exit code.

Some interfaces, especially client interfaces inheriting from :class:`shc.interfaces._helper.SupervisedClientInterface`, can be configured to automatically retry the external connection on errors, even if an an error is encountered during the initial startup.
As the SHC application will continue to run in these cases, it's useful to monitor the status of individual interfaces.


Monitoring of Interface Status
------------------------------

For this purpose, most interfaces, implement a "monitoring connector" (also called "status connector").
It is a *Readable* object of value type :class:`shc.supervisor.InterfaceStatus` that be retrieved via the :meth:`monitoring_connector <shc.supervisor.AbstractInterface.monitoring_connector>`.

If an interfaces does not provide monitoring capabilities, this method will raise a :class:`NotImplementedError`.

In many cases, the monitoring connector object is not only *Readable* but also *Subscribable*.
This can be used to interactively react to interface status changes, e.g. set some variables to an emergency-fallback mode when the :class:`SHC client <shc.interfaces.shc_client.SHCWebClient>` connection to a primary SHC server is lost.

.. autoclass:: shc.supervisor.ServiceStatus

.. autonamedtuple:: shc.supervisor.InterfaceStatus


Monitoring via HTTP
^^^^^^^^^^^^^^^^^^^

TODO monitoring via HTTP using the WebServer

TODO :meth:`shc.web.interface.WebServer.configure_monitoring`




Monitoring Helper classes
^^^^^^^^^^^^^^^^^^^^^^^^^

TODO :class:`shc.interfaces.system_monitoring.EventLoopMonitor`


