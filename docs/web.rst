
HTTP Server and Web User Interface
==================================

.. py:module:: shc.web.interface

Each instance of :class:`WebServer` creates an HTTP server, listening on a specified local TCP port and providing two different services:

* a web user interface, consisting of multiple pages with interactive *Connectable* widgets, allowing users to interact with SHC from any device with a modern web browser
* an HTTP/REST + websocket API for accessing and updating values within the SHC instance from other applications or devices


Configuring the User Interface
------------------------------

TODO creating a page (:meth:`WebServer.page`)

TODO page segments (:meth:`WebPage.new_segment`)

See :ref:`web.widgets` and :ref:`web.log_widgets` for a reference of the pre-defined ui widget types.



TODO filling the navigation bar


.. toctree::
   :hidden:

   web/widgets
   web/log_widgets


.. _web.rest:

Configuring the HTTP REST + Websocket API
-----------------------------------------

The REST + Websocket API is automatically included with every :class:`WebServer` instance and can be configured by creating :class:`WebApiObject`s through :meth:`WebServer.api`.
Each `WebApiObject` constitutes an API endpoint (i.e. "ressource" or path) of the REST API and an identifiable ressource in the Websocket API to interact with.
The REST API supports normal *GET* and *POST* requests as well as `"Long Polling" <https://en.wikipedia.org/wiki/Push_technology#Long_polling>`_ to let a client wait for value updates.

On the SHC-internal side, :class:`WebApiObject` are *Connectable* objects that are

- *Reading*, to answer GET requests by *reading* the connected provider's value,
- *Subscribable*, publishing a values that are POSTed to the API,
- *Writable*, to publish new values to the websocket API and answer long-polling clients

Each `WebApiObject` is identified by its `name` string.
The name is used as part of the respective endpoint path and in Websocket messages to interact with the specific `WebApiObject`.

Allowing interaction with an SHC Variable object via HTTP REST and websocket, is as simple as this::

    import shc
    import shc.web

    web_server = shc.web.WebServer('localhost', 8080)

    foo_variable = shc.Variable(int)
    web_server.api(int, 'foo').connect(foo_variable)

This will allow you to get the variable's value with a *GET* request to ``http://localhost:8080/api/v1/object/foo``.
The variable will be encoded with SHC's default json encoding for the datatype, which is just the decimal integer representation in this case.
In the same way, the value can be updated via a *POST* request to the same URL.
Read more about that in the reference below.

For a quick test, you can use cURL:

.. code-block:: sh

    curl http://localhost:8080/api/v1/object/foo
    curl -d 42 http://localhost:8080/api/v1/object/foo
    curl http://localhost:8080/api/v1/object/foo


REST API reference
^^^^^^^^^^^^^^^^^^

TODO

Websocket API reference
^^^^^^^^^^^^^^^^^^^^^^^

TODO


Creating Custom Widgets
-----------------------


Python Side
^^^^^^^^^^^

TODO rendering via :class:`WebPageItem`

TODO static files via :meth:`WebServer.serve_static_file`, :meth:`WebServer.add_js_file`, :meth:`WebServer.add_css_file`

TODO websocket service via :class:`WebUIConnector` or :class:`WebDisplayDatapoint`/:class:`WebActionDatapoint`


Javascript Side
^^^^^^^^^^^^^^^

* TODO: ``WIDGET_TYPES``
* TODO widget constructor arguments
* TODO: ``subscribeIds``
* TODO: ``update()``


``web`` Module Reference
------------------------

.. autoclass:: WebServer

    .. automethod:: page
    .. automethod:: api
    .. automethod:: serve_static_file
    .. automethod:: add_js_file
    .. automethod:: add_css_file


.. autoclass:: WebPage

    .. automethod:: add_item
    .. automethod:: new_segment


.. autoclass:: WebPageItem

    .. automethod:: render
    .. automethod:: register_with_server

.. autoclass:: WebUIConnector

    .. automethod:: from_websocket
    .. automethod:: _websocket_before_subscribe
    .. automethod:: _websocket_publish

.. autoclass:: WebDisplayDatapoint

    .. automethod:: convert_to_ws_value

.. autoclass:: WebActionDatapoint

    .. automethod:: convert_from_ws_value
