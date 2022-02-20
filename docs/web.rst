
HTTP Server and Web User Interface
==================================

.. py:module:: shc.web.interface

Each instance of :class:`WebServer` creates an HTTP server, listening on a specified local TCP port and providing two different services:

* a web user interface, consisting of multiple pages with interactive *Connectable* widgets, allowing users to interact with SHC from any device with a modern web browser
* an HTTP/REST + websocket API for accessing and updating values within the SHC instance from other applications or devices


Configuring the User Interface
------------------------------

Each page of the web user interface consists of one or more visual segments, each of them forming a vertical stack of different widgets.
By default, segments are placed alternating in two colums of equal width.
Optionally, they can be configured to span both columns.
On small screens (e.g. mobile devices) the columns are stacked vertically, such that the segments and widgets span the full screen width.

Each web page has a name for identification and linking and a title to be displayed as a heading.
To **create a new page** on a WebServer interface, use :meth:`WebServer.page`.
The page will be accessible at `http://<webserver.root_url>/page/<page.name>/`, e.g. `http://localhost:8080/page/index/`.

Different UI widget types are represented as Python classes derived from :class:`WebPageItem`.
Each instance of such a class represents a single widget on one web page.
They can be added to the web page via the :meth:`WebPage.add_item` method.
Typically, widgets are somehow dynamic or interactive, in a form that they are SHC *connectable* objects (or contain *connectable* objects) to be updated from subscribable objects or publish value updates from user interaction.

Widgets (WebPageItems), added via :meth:`WebPage.add_item`, are always added to the latest segment.
To start a new segment, for visually separating the following widgets, use :meth:`WebPage.new_segment`.
If :meth:`WebPage.new_segment` is called before adding a WebPageItem, it configures the first segment of the page.

The following example demonstrates the setup of a simple web UI page.
For a more full-blown example, take a look at the `ui_showcase.py` example script::

    import shc
    from shc.web import WebServer
    from shc.web.widgets import ButtonGroup, Switch, ToggleButton, icon

    server = WebServer('localhost', 8080)
    index_page = server.page('index', "Main page")

    state_variable = shc.Variable(bool, initial_value=False)

    # .connect() returns the object itself after connecting; so we can do connecting to the variable and adding to the
    # web page in a single line
    index_page.add_item(Switch(label="Foobar on/off").connect(state_variable))

    index_page.new_segment()

    # `ButtonGroup` is not connectable itself, but it takes a list of connectable Button spec objects
    index_page.add_item(ButtonGroup(label="Foobar on/off again", buttons=[
        ToggleButton(icon('power off')).connect(state_variable)
    ]))

See :ref:`web.widgets` and :ref:`web.log_widgets` for a reference of the available UI widget types.
See `Creating Custom Widgets` below for a detailed explanation of how widgets work and how to create custom widget types.

The WebServer can add a redirection from the root URL (e.g. `http://localhost:8080`) to one of the UI pages as an **index page**.
This index page can be configured via the `index_name` init parameter of the WebServer, e.g.::

    server = WebServer('localhost', 8080, index_name='index')

If it is not given (like in the example above), this redirection is not available and all pages are only accessible directly via their individual URL.

For navigating between pages, the WebServer can add a **navigation bar** to each page.
The navigation bar supports two nested menu layers:
Navigation links can either be placed in the navigation bar directly or in a labelled drop down menu of the navigation bar.
Each navigation bar entry (including dropdown menus) and each drop down menu entry has a label and an optional icon.

To add navigation bar entries manually, use :meth:`WebServer.add_menu_entry`, e.g.::

    server.add_menu_entry('index', "Main page", icon='home')
    server.add_menu_entry('another_page', "A submenu of rooms", 'boxes', "My other room", 'couch')

See https://fomantic-ui.com/elements/icon.html for a reference of available icons and their names.
The navigation bar is automatically added to every page, if there are any menu entries.

As shortcut, navigation bar entries can automatically added when creating a new page::

    bathroom_page = server.page(
        'bathroom', "Bathroom",
        menu_entry="A submenu of rooms", menu_icon='boxes',
        menu_sub_label="bathroom", menu_sub_icon='bath')

The `menu_entry` can also be set to `True`, in which case the page's title is used for the navigation bar entry label as well


.. toctree::
   :hidden:

   web/widgets
   web/log_widgets


.. _web.rest:

Configuring the HTTP REST + Websocket API
-----------------------------------------

The REST + Websocket API is automatically included with every :class:`WebServer` instance and can be configured by creating :class:`WebApiObject` s through :meth:`WebServer.api`.
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
In addition, it provides a “last will” mechanism, similar to `MQTT <https://www.hivemq.com/blog/mqtt-essentials-part-9-last-will-and-testament/>`_, allowing the client to deposit a value to be automatically published in the server when the client disconnects.
Though Websocket would allow binary messages, we still use JSON-formatted messages in UTF-8 encoding, for simplicity reasons.
(If this turns out to be a performance-bottleneck, SHC might be in general the wrong tool for your use case.)

The websocket interface works request-response-based (except for asynchronous updates from subscribed objects).
Each request message to the server has the following structure:

.. code-block:: JSON

    {"action": "ACTION", "name": "WEBAPI_OBJECT_NAME", "handle": "ANY_DATA"}

'ACTION' must be one of 'get', 'post', 'subscribe' or 'lastwill'.
'handle' is an optional field, that can contain any valid JSON data (it doesn't need to be a string).
If a 'handle' is provided it is copied into the respective response message by the server to allow the client matching requests and response messages.
`post` and `lastwill` messages must have an additional 'value' field, containing the JSON encoded value to be send to the WebApiObject.

Each response messages has the following structure:

.. code-block:: JSON

    {"status": 204, "name": "WEBAPI_OBJECT_NAME", "action": "ACTION", "handle": "ANY_DATA"}

The fields 'name', 'action' and 'handle' are provided to match the response message with the corresponding request message.
If no 'handle' has been provided in the request, 'handle' is null.
Response messages from the 'get' action additionally contain a 'value' field, containing the JSON-encoded object value.
The 'status' fields is a HTTP status code indicating the result of the action:

+------------+--------------------------------+--------------------------------------------------+
| 'status'   | actions                        | meaning                                          |
+============+================================+==================================================+
| 200        | get                            | success, 'value' field present                   |
+------------+--------------------------------+--------------------------------------------------+
| 204        | post, subscribe, lastwill      | success, no 'value' field present                |
+------------+--------------------------------+--------------------------------------------------+
| 400        | get, post, subscribe, lastwill | request message is not a valid JSON string       |
+------------+--------------------------------+--------------------------------------------------+
| 404        | get, post, subscribe, lastwill | not `WebApiObject` with the given name does exist|
+------------+--------------------------------+--------------------------------------------------+
| 409        | get                            | no value is available yet                        |
+------------+--------------------------------+--------------------------------------------------+
| 422        | –                              | 'action' is not a valid action                   |
+            +--------------------------------+--------------------------------------------------+
|            | post, lastwill                 | or POST'ed value has invalid type or value       |
+------------+--------------------------------+--------------------------------------------------+
| 500        | get, post, subscribe, lastwill | Unexpected exception while processing the action |
+------------+--------------------------------+--------------------------------------------------+

If the action resulted in an error (any status code other than 200 or 204), the response message contains an additional 'error' field with a textual description.

When subscribing an object, the server first responds with the usual response, typically with status code 204, if all went well.
Afterwards an asynchronous message of the following format is sent for each value update received by the WebApiObject from connected objects:

.. code-block:: JSON

    {"status": 200, "name": "WEBAPI_OBJECT_NAME", "value": "THE NEW VALUE"}

Note, that there is no 'action' or 'handle' field in these messages, as they do not represent a response to a request message.



Creating Custom Widgets
-----------------------

SHC allows to extend the web interface functionality with custom widget types.
A widget type consists of

- a Python class derived from :class:`WebPageItem`, that provides a method for rendering the widget's HTML code,
- and (optionally) Python classes derived from :class:`WebUIConnector` and a matching JavaScript constructor function for dynamic or interactive behaviour through SHC's websocket connection.

In most cases, the Python widget class can be derived from `WebPageItem` **and** `WebUIConnector`, such that the widget object can also serve as the websocket communication endpoint for the widget.
Only in cases that require multiple communication endpoints for the same widget (like the ButtonGroup widget, which has a *Connectable* websocket communication endpoint for each button), additional objects should be used.

The connection between an individual widget's JavaScript object and the corresponding Python `WebUIConnector` is automatically established by the SHC web framework.
It uses the Python object id (obtained by `id(foo)` in Python) for identifying the individual `WebUIConnector`.
The WebUIConnector's object id is typically rendered into the widget's HTML code as an HTML attribute by the `WebPageItem` object, then obtained by the JavaScript constructor function and provided to the client-side SHC framework via the object's `subscribeIds` attribute and as a parameter of the `writeValue` function.

Each widget's JavaScript object of the correct widget type is automatically constructed upon page load by the SHC framework.
For this purpose, each widget needs to have the `data-widget` attribute on some of it's HTML elements, specifying the widget type name, which is mapped to a type-specific constructor function via the global `SHC_WIDGET_TYPES` Map in JavaScript.

A full-blown example of all the required parts for creating a custom widget is shown in the `custom_ui_widget´ example in the `example` directory of the SHC repository.


Python Side
^^^^^^^^^^^

A :class:`WebPageItem` class for representing a type of item in the Python script must implement/override two methods:

- :meth:`render() <WebPageItem.render>` for generating the Widget's HTML code.
  Typically, a template engine like Jinja2 is used to fill dynamic values (such as the WebUIConnector's object id) into a static HTML string.
  However, for simple widgets, a simple Python format string (or f-string literal) might be sufficient.

- :meth:`get_connectors() <WebPageItem.get_connectors>`, returning a list of all `WebUIConnector` objects of the widget to make them known to the server, so that incoming subscriptions from the client can be routed to the objects.

  For typical widgets, where the `WebPageItem` is the (only) `WebUIConnector` of the widget at the same time, this method would simply return ``[self]``.
  More complex widgets might return other objects (additionally) or even call this method recursively when other widgets are embedded.
  For a static, non-interactive widget, an empty list can be returned.

In addition, the following method **can** be implemented:

- :meth:`register_with_server() <WebPageItem.register_with_server>`
  This method is called once on each widget object of the widget class, when the widget is added to a web page.
  It receives a reference to the :class:`WebServer` object and the :class:`WebPage` object, so that the widget can retrieve information about the server or page or register static files to be served by the server.

  An example use case for this method is demonstrated by SHC's :class:`ImageMap <shc.web.widgets.ImageMap>` widget:
  Each instance of this widget class has a user-defined background image file.
  The widget uses `register_with_server()` to register this file to be served as a static file, so it can be referenced in an ``<img />`` tag in the HTML code.


Within `register_with_server()` the widget will typically use the following methods of the web server:

- :meth:`WebServer.serve_static_file` for serving a single static file and/or
- :meth:`WebServer.add_static_directory` for serving a full directory of static files and optionally adding CSS stylesheets and JavaScript files to all web pages of the server.

As already discussed, the websocket communication of interactive widgets is handled at the server through :class:`WebUIConnector`.
It provides two basic methods for handling new connections of clients (i.e. instances of the widget instance in different browsers or browser tabs) and handling incoming messages from the widget.
In addition it has a method to publish a message to all current clients (client widget instances).

In most usecases these communication methods are used to implement a *Writable* SHC object that forwards value updates to all clients to update the UI state, or — the other way round — to implement a *Subscribable* SHC object, publishing values received from the clients upon user interaction.
For these common cases, there are two classes, which handle all the client subscription management and forwarding of value updates:

- :class:`WebDisplayDatapoint` is the base class for `Writable` objects, that transmit the SHC value updates to the clients
- :class:`WebActionDatapoint` is the base class for `Subscribable` objects that publish values received from the clients

Both of them can be combined via multi-inheritance, creating a `Writable` **and** `Subscribable` class for two-way interactive widgets.
They only require minor adjustments if the SHC value type of the value updates differs from the JSON data transferred to/from the clients.
By default, the values are encoded/decoded to/from JSON using :ref:`SHC's default JSON conversion <datatypes.json>` for the type specified by the object's ``type`` attribute.
To adjust that, override :meth:`WebDisplayDatapoint.convert_to_ws_value` resp. :meth:`WebActionDatapoint.convert_from_ws_value`.


Javascript Side
^^^^^^^^^^^^^^^

On the client, SHC takes care of constructing a JavaScript object for each widget instance.
For this purpose, a constructor function for each widget type must be provided, by inserting it into the global ``SHC_WIDGET_TYPES`` map:

.. code-block:: javascript

    function MyWidgetTypeConstructor(domElement, writeValue) {
        this.subscribeIds = [];  // TODO

        // TODO

        this.update = function(value, for_id) {
            // TODO
        }
    }

    SHC_WIDGET_TYPES.set('my-widget-type', MyWidgetTypeConstructor);


For the constructor to be executed, the widget's top-level HTML DOM element must have the `data-widget` attribute with the widget type name from the map; i.e. ``data-widget="my-widget-type"`` for the example above.

Each widget constructor function must take two parameters:

- ``domElement``: The widget's DOM element for which the widget object is constructed
- ``writeValue``: A callback function, which can be saved in the object and later be used to send value updates to the server.
  It takes two arguments: The object id of the `WebUIConnector` to send the value to and the value as a simple JavaScript object.
  The value is automatically JSON-encoded for sending it to the server.

The constructor function must create at least two attributes on the constructed object (``this``):

- ``subscribeIds``: a list of the Python object ids of all `WebUIConnector` objects to subscribe to.
  The SHC web framework will ensure to send a subscription request to these objects at the server, as soon as the websocket connection has been established.
  As the object ids are dynamic (i.e. they change with each restart of the SHC server application), they are typically provided as an additional HTML attribute in each widget's HTML code to be retrieved by the JavaScript:

  .. code-block:: javascript

    this.subscribeIds = [parseInt(domElement.getAttribute('data-id'))];

- ``update``: a method to be called when an update from the server is received for one of the subscribeIds.
  It takes two arguments: The received value and the object id of the publishing Python object.
  The object id can be used to differentiate between the different subscriptions for widgets that subscribe to more than one `WebUIConnector`.


``web`` Module Reference
------------------------

.. autoclass:: WebServer

    .. automethod:: page
    .. automethod:: add_menu_entry
    .. automethod:: api
    .. automethod:: serve_static_file
    .. automethod:: add_static_directory


.. autoclass:: WebPage

    .. automethod:: add_item
    .. automethod:: new_segment


.. autoclass:: WebPageItem

    .. automethod:: render
    .. automethod:: register_with_server
    .. automethod:: get_connectors

.. autoclass:: WebUIConnector

    .. automethod:: from_websocket
    .. automethod:: _websocket_before_subscribe
    .. automethod:: _websocket_publish

.. autoclass:: WebApiObject

.. autoclass:: WebDisplayDatapoint

    .. automethod:: convert_to_ws_value

.. autoclass:: WebActionDatapoint

    .. automethod:: convert_from_ws_value
