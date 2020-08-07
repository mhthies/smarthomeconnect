
function ws_path(path) {
    const loc = window.location;
    let new_proto;
    if (loc.protocol === "https:") {
        new_proto = "wss:";
    } else {
        new_proto = "ws:";
    }
    return new_proto + "//" + loc.host + path;
}

function SwitchWidget(domElement, writeValue) {
    $(domElement).closest('.checkbox').checkbox();
    const widget = this;
    this.subscribeIds = [parseInt(domElement.getAttribute('data-id'))];

    this.update = function(value, for_id) {
        domElement.checked = value;
    };

    domElement.addEventListener('change', function (event) {
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
    let on = false;
    this.subscribeIds = [];

    if (stateful)
        this.subscribeIds.push(id);

    this.update = function(value, for_id) {
        on = value;
        domElement.classList.toggle(domElement.getAttribute('data-on-class'), value);
        domElement.classList.remove('loading', 'active');
    };

    domElement.addEventListener('click', function (event) {
        writeValue(id, !on);
        if (stateful)
            domElement.classList.add('active');
    });
}

function TextDisplayWidget(domElement, writeValue) {
    this.subscribeIds = [parseInt(domElement.getAttribute('data-id'))];

    this.update = function(value, for_id) {
        domElement.textContent = value;
    };
}

function TextInputWidget(domElement, writeValue) {
    const BLUR_TIMEOUT = 8000; // ms
    const id = parseInt(domElement.getAttribute('data-id'));
    const parseAs = domElement.getAttribute("data-parse-as");
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

const WIDGET_TYPES = new Map([
   ['switch', SwitchWidget],
   ['select', SelectWidget],
   ['button', ButtonWidget],
   ['text-display', TextDisplayWidget],
   ['text-input', TextInputWidget]
]);

(function () {
    let widgetMap = new Map();
    let ws;

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
        ws = new WebSocket(ws_path('/ws'));
        ws.onopen = subscribe;
        ws.onmessage = dispatch_message;
        ws.onclose = function (e) {
            console.info('Socket is closed. Reconnect will be attempted in 1 second.', e.reason);
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
        console.info("Websocket opened. Subscribing widget values ...");
        for (const id of widgetMap.keys()) {
            ws.send(JSON.stringify({
                'action': 'subscribe',
                'id': id
            }));
        }
    }

    function dispatch_message(messageEvent) {
        console.debug("Received message " + messageEvent.data);
        let data = JSON.parse(messageEvent.data);
        console.debug("Updating widget id " + data['id'].toString() + " ...");
        widgetMap.get(data['id']).update(data['value'], data['id']);
    }

    function writeValue(id, value) {
        console.debug("Writing new value " + JSON.stringify(value) + " for widget id " + id.toString());
        ws.send(JSON.stringify({
            'action': 'write',
            'id': id,
            'value': value
        }));
    }

    window.onload = init;
})();


