
.. _data_logging:

Data Logging
============

.. py:module:: shc.data_logging

There are SHC interfaces for accepting value updates and store them to a (typically persistent) database, together with the current timestamp.
This allows retrieving of historic data series for a certain value (e.g. a room temperature, measured by some thermometer, connected to your SHC server).
SHC provides a generic interface to retrieve such time series ("data logs") from the underlying database, to be implemented by the respective database interface: The :class:`DataLogVariable` class.

It also includes functionality to retrieve aggregated log data (e.g. average value per time interval instead of raw data points) and subscribing to live updates from the (raw or aggregated) timeseries.
Live updates are automatically created from SHC internal writes or a regular timer if the database does not support them natively.

Typically, `DataLogVariables` are used to add :ref:`Log Widgets <web.log_widgets>` to a WebPage in the web user interface, for displaying live data plots (or listings) of the recent trend of variables.


Included interfaces with data logging support 
---------------------------------------------

* :class:`shc.interfaces.mysql.MySQLConnector`
* :class:`shc.interfaces.in_memory_data_logging.InMemoryDataLogVariable`



``shc.data_logging`` Module Reference
-------------------------------------

.. autoclass:: DataLogVariable
    :members:

.. autoclass:: AggregationMethod
    :members:

.. autoclass:: WritableDataLogVariable
    :members:

.. autoclass:: LiveDataLogView
    :members:

.. autoclass:: LoggingWebUIView
    :show-inheritance:
    :members:

``shc.interfaces.in_memory_data_logging`` Module Reference
----------------------------------------------------------

.. automodule:: shc.interfaces.in_memory_data_logging

    .. autoclass:: InMemoryDataLogVariable
        :show-inheritance:
