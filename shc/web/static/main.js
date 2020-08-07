
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
    const widget = this;
    this.subscribeIds = [parseInt(domElement.getAttribute('data-id'))];

    this.update = function(value, for_id) {
        domElement.checked = value;
    };

    domElement.addEventListener('change', function (event) {
        writeValue(widget.subscribeIds[0], event.target.checked);
    });
}

function EnumSelectWidget(domElement, writeValue) {
    const widget = this;
    this.subscribeIds = [parseInt(domElement.getAttribute('data-id'))];

    this.update = function(value, for_id) {
        domElement.value = JSON.stringify(value);
    };

    domElement.addEventListener('change', function (event) {
        writeValue(widget.subscribeIds[0], JSON.parse(event.target.value));
    });
}

function ButtonWidget(domElement, writeValue) {
    const widget = this;
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

const WIDGET_TYPES = new Map([
   ['switch', SwitchWidget],
   ['enum-select', EnumSelectWidget],
   ['button', ButtonWidget],
   ['text-display', TextDisplayWidget]
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


