
The SHC HTTP Server and Web User Interface
==========================================

.. py:currentmodule:: shc.web.interface

Each instance of :class:`WebServer` creates an HTTP server, listening on a specified local TCP port and providing two different services:

* a web user interface, consisting of multiple pages with interactive *Connectable* widgets, allowing users to interact with SHC from any device with a modern web browser
* an HTTP/REST + websocket API for accessing and updating values within the SHC instance from other applications or devices


Configuring the User Interface
------------------------------

TODO creating a page (:meth:`WebServer.page`)

TODO page segments (:meth:`WebPage.new_segment`)

See :ref:`web.widgets` for a reference of the pre-defined ui widget types.



TODO filling the navigation bar


.. toctree::
   :hidden:

   web/widgets



Configuring the HTTP + Websocket API
------------------------------------

TODO creating and using an API object (:meth:`WebServer.api`)

TODO API reference



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
