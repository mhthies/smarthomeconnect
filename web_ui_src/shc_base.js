/* Copyright 2020 Michael Thies <mail@mhthies.de>
 *
 * Licensed under the Apache License, Version 2.0 (the "License"); you may not use this file except in compliance with
 * the License. You may obtain a copy of the License at
 *
 *     http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software distributed under the License is distributed on
 * an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the License for the
 * specific language governing permissions and limitations under the License.
 */

import $ from 'jquery';

function ws_path(path) {
    if (path.startsWith("/")) {
        const loc = window.location;
        let new_proto;
        if (loc.protocol === "https:") {
            new_proto = "wss:";
        } else {
            new_proto = "ws:";
        }
        return new_proto + "//" + loc.host + path;
    } else {
        const loc = new URL(path);
        if (loc.protocol === "https:") {
            loc.protocol = "wss:";
        } else {
            loc.protocol = "ws:";
        }
        return loc.href;
    }
}

export let WIDGET_TYPES = new Map();

(function () {
    let widgetMap = new Map();
    let ws;
    let connectionErrorToast = null;  // The Semantic UI 'toast' element which indicates a lost websocket connection.
    let connectionPreviouslyEstablished = false; // true, once we established a websocket connection successfully.

    function init() {
        console.info("Intializing Smart Home Connect web UI.");
        const widgetElements = document.querySelectorAll('[data-widget]');
        for (const widgetElement of widgetElements) {
            let type = widgetElement.getAttribute('data-widget');
            let obj = new (WIDGET_TYPES.get(type))(widgetElement, writeValue);
            for (const the_id of obj.subscribeIds) {
                widgetMap.set(the_id, obj);
            }
        }
        if (widgetElements.length > 0) {
            openWebsocket();
        }
    }

    function openWebsocket() {
        console.info("Opening websocket ...");
        ws = new WebSocket(ws_path(shcRootURL + '/ws'));
        ws.onopen = subscribe;
        ws.onmessage = dispatch_message;
        ws.onclose = function (e) {
            console.info('Socket is closed. Reconnect will be attempted in 1 second.', e.reason);
            if (!connectionErrorToast) {
                connectionErrorToast = $('body').toast({
                    'message': connectionPreviouslyEstablished
                        ? "Connection to websocket server failed ..."
                        : "Connection to SHC server lost ...",
                    'class': 'error',
                    showIcon: 'exclamation circle',
                    displayTime: 0,
                    closeOnClick: false
                });
            }
            setTimeout(function () {
                openWebsocket();
            }, 1000);
        };
        ws.onerror = function (err) {
            console.error('Socket encountered error: ', err.message, 'Closing socket');
            ws.close();
        };
    }

    function subscribe() {
        if (connectionErrorToast) {
            connectionErrorToast.toast('close');
            connectionErrorToast = null;
        }
        console.info("Websocket opened. Subscribing widget values ...");
        // Send serverToken to server to reload page on server restarts
        ws.send(JSON.stringify({
            'serverToken': shcServerToken
        }));
        // Subscribe to WebConnector objects
        for (const id of widgetMap.keys()) {
            ws.send(JSON.stringify({
                'sub': true,
                'id': id
            }));
        }
    }

    function dispatch_message(messageEvent) {
        console.debug("Received message " + messageEvent.data);
        let data = JSON.parse(messageEvent.data);
        if (data['reload']) {
            console.debug("Reloading page, because server told us to do so.");
            location.reload();
        } else if (data['id']) {
            console.debug("Updating widget id " + data['id'].toString() + " ...");
            widgetMap.get(data['id']).update(data['v'], data['id']);
        } else {
            console.error("Don't know how to handle websocket message ", data);
        }
    }

    function writeValue(id, value) {
        console.debug("Writing new value " + JSON.stringify(value) + " for widget id " + id.toString());
        try {
            if (!ws)
                throw "Websocket not available";
            if (ws.readyState !== WebSocket.OPEN)
                throw "Websocket is not open."
            ws.send(JSON.stringify({
                'id': id,
                'v': value
            }));
        } catch (e) {
            console.error("Error while sending value via websocket:", e);
            $('body').toast({
                'message': "Error while sending value.",
                'class': 'warning',
                showIcon: 'exclamation circle'});
        }
    }

    document.addEventListener('DOMContentLoaded', (event) => init());
})();

