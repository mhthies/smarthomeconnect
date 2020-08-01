
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
    this.id = parseInt(domElement.getAttribute('data-id'));
    this.subscribe = true;

    this.update = function(value) {
        domElement.checked = value;
    };

    domElement.addEventListener('change', function (event) {
        writeValue(widget.id, event.target.checked);
    });
}

const WIDGET_TYPES = new Map([
   ['switch', SwitchWidget]
]);

(function () {
    let widgetMap = new Map();
    let ws;

    function init() {
        console.info("Intializing Smart Home Connect web UI.");
        const widgetElements = document.querySelectorAll('[data-widget]');
        widgetElements.forEach(function (widgetElement) {
            let type = widgetElement.getAttribute('data-widget');
            let obj = new (WIDGET_TYPES.get(type))(widgetElement, writeValue);
            widgetMap.set(obj.id, obj);
        });

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
        widgetMap.forEach(function(widget, id){
            if (!widget.subscribe) {
                return;
            }
            ws.send(JSON.stringify({
                'action': 'subscribe',
                'id': id
            }));
        });
    }

    function dispatch_message(messageEvent) {
        console.debug("Received message " + messageEvent.data);
        let data = JSON.parse(messageEvent.data);
        console.debug("Updating widget id " + data['id'].toString() + " ...");
        let widget = widgetMap.get(data['id']).update(data['value']);
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


