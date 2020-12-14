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

function forEachNodeRecursive(node, func) {
    /**
     * Iterate DOM subtree recursively in a depth-first pre-order, starting at `node`, and call `func` for each node
     * (incl. `node`).
     *
     * If `func` returns `false`, the iteration is stopped.
     */
    let res = func(node);
    if (res === false)
        return false;
    node = node.firstChild;
    while (node) {
        res = forEachNodeRecursive(node, func);
        if (res === false)
            return false;
        node = node.nextSibling;
    }
}

function SwitchWidget(domElement, writeValue) {
    $(domElement).closest('.checkbox').checkbox();
    const widget = this;
    this.subscribeIds = [parseInt(domElement.getAttribute('data-id'))];
    const confirm_values = domElement.getAttribute('data-confirm')
        ? domElement.getAttribute('data-confirm')
            .split(',')
            .map(v => parseInt(v))
        : [];
    const confirm_message = domElement.getAttribute('data-confirm-message');

    this.update = function(value, for_id) {
        domElement.checked = value;
    };

    domElement.addEventListener('change', function (event) {
        if (confirm_values.indexOf(1 * event.target.checked) !== -1) {
            event.target.checked = !event.target.checked;
            if (window.confirm(confirm_message || "Are you sure?")) {
                event.target.checked = !event.target.checked;
            } else {
                return;
            }
        }
        writeValue(widget.subscribeIds[0], event.target.checked);
    });
}

function SelectWidget(domElement, writeValue) {
    const widget = this;
    const $semanticUIDropdown = $(domElement).closest('.dropdown');
    let sendingDisabled = false;
    $semanticUIDropdown.dropdown({
        'onChange': onDropdownChange
    });
    this.subscribeIds = [parseInt(domElement.getAttribute('data-id'))];

    this.update = function(value, for_id) {
        sendingDisabled = true;
        $semanticUIDropdown.dropdown('set selected', JSON.stringify(value));
        sendingDisabled = false;
    };

    function onDropdownChange(value, text, $selectedItem) {
        if (!sendingDisabled)
            writeValue(widget.subscribeIds[0], JSON.parse(value));
    }
}

function ButtonWidget(domElement, writeValue) {
    const id = parseInt(domElement.getAttribute('data-id'));
    const stateful = domElement.getAttribute('data-stateful') === 'True';
    const confirm_values = domElement.getAttribute('data-confirm')
        ? domElement.getAttribute('data-confirm')
            .split(',')
            .map(v => parseInt(v))
        : [];
    const confirm_message = domElement.getAttribute('data-confirm-message');
    const onClasses = domElement.getAttribute('data-on-class')
        ? domElement.getAttribute('data-on-class').split(" ")
        : [];
    const offClasses = domElement.getAttribute('data-off-class')
        ? domElement.getAttribute('data-off-class').split(" ")
        : [];
    const send = !((domElement.getAttribute('data-send') || '') == 'false');
    let on = false;
    this.subscribeIds = [];

    if (stateful)
        this.subscribeIds.push(id);

    this.update = function(value, for_id) {
        on = value;
        for (const cls of onClasses)
            domElement.classList.toggle(cls, value);
        for (const cls of offClasses)
            domElement.classList.toggle(cls, !value);
        domElement.classList.remove('loading', 'active');
    };

    if (send) {
        domElement.addEventListener('click', function (event) {
            let value = !on;
            if (confirm_values.indexOf(1 * value) !== -1 && !window.confirm(confirm_message || "Are you sure?")) {
                return;
            }
            writeValue(id, value);
            if (stateful)
                domElement.classList.add('active');
        });
    }
}

function TextDisplayWidget(domElement, writeValue) {
    this.subscribeIds = [parseInt(domElement.getAttribute('data-id'))];

    this.update = function(value, for_id) {
        domElement.innerHTML = value;
    };
}

function TextInputWidget(domElement, writeValue) {
    const BLUR_TIMEOUT = 8000; // ms
    const id = parseInt(domElement.getAttribute('data-id'));
    this.subscribeIds = [id];
    let valueFromServer = null;
    let timeout = null;
    let sendingDisabled = false;

    this.update = function(value, for_id) {
        valueFromServer = value;
        if (document.activeElement !== domElement)
            domElement.value = value;
    };

    function sendValue() {
        writeValue(id, domElement.value);
    }
    function clearValue() {
        sendingDisabled = true;
        domElement.blur();
        sendingDisabled = false;
        domElement.value = valueFromServer;
    }

    domElement.addEventListener('blur', function (event) {
        if (!sendingDisabled)
            sendValue();
    });
    domElement.addEventListener('keydown', function (event) {
        clearTimeout(timeout);
        if (event.keyCode === 13) { /* ENTER */
            domElement.blur();
            event.preventDefault();
            return;
        } else if (event.keyCode === 27) { /* ESC */
            clearValue();
            return;
        }
        timeout = setTimeout(clearValue, BLUR_TIMEOUT);
    });
    domElement.addEventListener('mousedown', function (event) {
        clearTimeout(timeout);
        timeout = setTimeout(clearValue, BLUR_TIMEOUT);
    })
}

function SliderWidget(domElement, writeValue) {
    const id = parseInt(domElement.getAttribute('data-id'));
    this.subscribeIds = [id];
    let $semanticUiSlider = $(domElement);
    let sendingDisabled = false;
    $semanticUiSlider.slider({
        min: 0,
        max: 1000,
        step: 1,
        showLabelTicks: true,
        labelDistance: 200,
        interpretLabel: function(v) {
            if (v % 250 === 0)
                return Math.round(v / 10).toString() + " %";
            else
                return "";
        },
        onChange: onSliderChange
    });
    let displayBox = null;
    forEachNodeRecursive(domElement.parentNode, function(node) {
        if (node.nodeType === 1 && node.classList.contains('value-display')) {
            displayBox = node;
            return false;
        }
    });

    this.update = function(value, for_id) {
        sendingDisabled = true;
        $semanticUiSlider.slider('set value', Math.round(value * 1000));
        displayBox.textContent = Math.round(value * 100).toString() + " %";
        sendingDisabled = false;
    };

    function onSliderChange() {
        if (!sendingDisabled)
            writeValue(id, $semanticUiSlider.slider('get value') / 1000);
    }
}

function ColorChoserWidget(domElement, writeValue) {
    const id = parseInt(domElement.getAttribute('data-id'));
    this.subscribeIds = [id];
    var colorPicker = new iro.ColorPicker(domElement, {
        color: "#000"
    });

    colorPicker.on('input:end', function(color) {
        writeValue(id, [color.red, color.green, color.blue]);
    });

    this.update = function(value, for_id) {
        colorPicker.color.rgb = {'r': value[0], 'g': value[1], 'b': value[2]};
    };
}

function HideRowWidget(domElement, _writeValue) {
    const id = parseInt(domElement.getAttribute('data-id'));
    this.subscribeIds = [id];
    let displayBox = null;
    for (const node of domElement.parentNode.childNodes.values()) {
        if (node.nodeType === 1 && node.classList.contains('value-display')) {
            displayBox = node;
            break;
        }
    }

    this.update = function(value, for_id) {
        if (value === domElement.classList.contains('hidden'))
            $(domElement).transition('zoom ' + (value ? 'in' : 'out'));
    };
}

const WIDGET_TYPES = new Map([
   ['switch', SwitchWidget],
   ['select', SelectWidget],
   ['button', ButtonWidget],
   ['text-display', TextDisplayWidget],
   ['text-input', TextInputWidget],
   ['slider', SliderWidget],
   ['colorchoser', ColorChoserWidget],
   ['hiderow', HideRowWidget],
]);

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

        openWebsocket();
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

$(function() {
    $('.main-menu .ui.dropdown').dropdown();
    $('.ui.sidebar').sidebar({transition: 'overlay'}).sidebar('attach events', '#mobile_item');
    $('.shc.image-container .with-popup>*').each(function(){
        $(this).popup({
            on: 'click',
            popup: $(this).parent().attr('data-popup-id'),
            position: $(this).parent().attr('data-popup-position'),
            movePopup: false,
            forcePosition: true});
    });
});
