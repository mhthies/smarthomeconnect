
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



TODO filling the navigation bar (:meth:`WebServer.add_menu_entry`)


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
The variable will be encoded with SHC's :ref:`default json encoding <datatypes.json>` for the datatype, which is just the decimal integer representation in this case.
In the same way, the value can be updated via a *POST* request to the same URL.
Read more about that in the reference below.

For a quick test, you can use cURL:

.. code-block:: sh

    curl http://localhost:8080/api/v1/object/foo
    curl -d 42 http://localhost:8080/api/v1/object/foo
    curl http://localhost:8080/api/v1/object/foo


REST API reference
^^^^^^^^^^^^^^^^^^

.. http:get:: /api/v1/object/(str:object_name)

    Read the current value of the Readable object connected to the WebApiObject's with the given name (= its
    :ref:`default_provider <base.connectable_objects>`) or wait for the next value update received by the WebApiObject.

    The values are provided in the HTTP response body as an UTF-8 encoded JSON document, using the
    :ref:`SHC default JSON encoding <datatypes.json>` of the WebApiObject's value type.

    Without any parameters, the GET endpoint will read and return the current value of the connected object. If the
    `wait` query parameter is provided (optionally with a timeout), it will wait for the next value update instead
    (`"Long Polling" <https://en.wikipedia.org/wiki/Push_technology#Long_polling>`_). To avoid missing value updates
    while reconnecting for the next long poll, the GET endpoint always provides an `ETag` header in the response to be
    used with the `If-None-Match` request header. It will make the endpoint respond immediately with the current value,
    if it has changed since the state identified by the ETag.

    A typical example for long polling in a Python application, using the `requests` library, would look like this::

        e_tag = None
        while True:
            response = requests.get('http://localhost:8080/api/v1/object/foo?wait', headers={'If-None-Match': e_tag})
            e_tag = response.headers['ETag']
            print("New value: ", response.json())


    :query wait: If given, the server will not respond with the current object value immediately, but instead waits for
        the next value update to be received and returns the new value. If no value is received up to a certain timeout,
        the server returns an emtpy response with HTTP 304 status code. The timeout can be provided as an optional value
        to the `wait` parameter in seconds (e.g. ``?wait=60``). Otherwise it defaults to 30 seconds.
    :reqheader If-None-Match: If given and equal to the ETag value from a previous request, the server will respond with
        HTTP 304 status code and an empty response body if no new value update has been received sind this previous
        request. If a new value *has* been published in the meantime, the server will respond with the new value and
        HTTP status 200 immediately, even if the `wait` query parameter is given.
    :resheader ETag: The "entity tag" of the current value. It can be used as value of the `If-None-Match` request
        header in a subsequent request to detect intermittent changes of the value. This is especially useful to receive
        missed value updates when using long polling via the `wait` parameter.
    :resheader Content-Type: application/json
    :statuscode 200: no error
    :statuscode 304: value has not been changed since given ETag and has not changed within poll timeout (if given)
    :statuscode 400: parameters are not valid (esp. the value of the `wait` query parameter
    :statuscode 404: object with given object_name does not exist
    :statuscode 409: no value is available yet

.. http:post:: /api/v1/object/(str:object_name)

    Send a new value to the SHC server to be published by the `WebApiObject` with the given object name.

    The value must be submitted in the HTTP request body, as a plain UTF-8 encoded JSON document (no form-encoding),
    using the default JSON SHC encoding of the WebApiObject's value type.

    :statuscode 204: no error
    :statuscode 400: request body could not be parsed as a JSON document
    :statuscode 404: object with given object_name does not exist
    :statuscode 422: value has wrong datatype or has an invalid value for processing in the connected objects

.. http:get:: /api/v1/ws

    The websocket endpoint to connect to the Websocket API that allows true asynchronous interaction with the
    WebApiObjects (see below).

    :statuscode 101: no error, upgrading to WebSocket connection


Websocket API reference
^^^^^^^^^^^^^^^^^^^^^^^

The Websocket interface basically resembles the HTTP REST API, but offers better performance by using a single TCP connection and provides a true asynchronous publish-subscribe mechanism to receive value updates.
Though Websocket would allow binary messages, we still use JSON-formatted messages in UTF-8 encoding, for simplicity reasons.
(If this turns out to be a performance-bottleneck, SHC might be in general the wrong tool for your use case.)

The websocket interface works request-response-based (except for asynchronous updates from subscribed objects).
Each request message to the server has the following structure:

.. code-block:: JSON

    {"action": "ACTION", "name": "WEBAPI_OBJECT_NAME", "handle": "ANY_DATA"}

'ACTION' must be one of 'get', 'post' or 'subscribe'.
'handle' is an optional field, that can contain any valid JSON data (it doesn't need to be a string).
If a 'handle' is provided it is copied into the respective response message by the server to allow the client matching requests and response messages.
`post` messages must have an additional 'value' field, containing the JSON encoded value to be send to the WebApiObject.

Each response messages has the following structure:

.. code-block:: JSON

    {"status": 204, "name": "WEBAPI_OBJECT_NAME", "action": "ACTION", "handle": "ANY_DATA"}

The fields 'name', 'action' and 'handle' are provided to match the response message with the corresponding request message.
If no 'handle' has been provided in the request, 'handle' is null.
Response messages from the 'get' action additionally contain a 'value' field, containing the JSON-encoded object value.
The 'status' fields is a HTTP status code indicating the result of the action:

+------------+----------------------+--------------------------------------------------+
| 'status'   | actions              | meaning                                          |
+============+======================+==================================================+
| 200        | get                  | success, 'value' field present                   |
+------------+----------------------+--------------------------------------------------+
| 204        | post, subscribe      | success, no 'value' field present                |
+------------+----------------------+--------------------------------------------------+
| 400        | post                 | request message is not a valid JSON string       |
+------------+----------------------+--------------------------------------------------+
| 404        | get, post, subscribe | not `WebApiObject` with the given name does exist|
+------------+----------------------+--------------------------------------------------+
| 409        | get                  | no value is available yet                        |
+------------+----------------------+--------------------------------------------------+
| 422        | –                    | 'action' is not a valid action                   |
+            +----------------------+--------------------------------------------------+
|            | post                 | or POST'ed value has invalid type or value       |
+------------+----------------------+--------------------------------------------------+
| 500        | get, post, subscribe | Unexpected exception while processing the action |
+------------+----------------------+--------------------------------------------------+

If the action resulted in an error (any status code other than 200 or 204), the response message contains an additional 'error' field with a textual description.

When subscribing an object, the server first responds with the usual response, typically with status code 204, if all went well.
Afterwards an asynchronous message of the following format is sent for each value update received by the WebApiObject from connected objects:

.. code-block:: JSON

    {"status": 200, "name": "WEBAPI_OBJECT_NAME", "value": "THE NEW VALUE"}

Note, that there is no 'action' or 'handle' field in these messages, as they do not represent a response to a request message.



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
    .. automethod:: add_menu_entry
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

.. autoclass:: WebApiObject

.. autoclass:: WebDisplayDatapoint

    .. automethod:: convert_to_ws_value

.. autoclass:: WebActionDatapoint

    .. automethod:: convert_from_ws_value
