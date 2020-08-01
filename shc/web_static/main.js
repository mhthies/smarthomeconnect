
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
        const widgetElements = document.querySelectorAll('[data-widget]');
        widgetElements.forEach(function (widgetElement) {
            let type = widgetElement.getAttribute('data-widget');
            let obj = new (WIDGET_TYPES.get(type))(widgetElement, writeValue);
            widgetMap.set(obj.id, obj);
        });

        ws = new WebSocket(ws_path('/ws'));
        ws.onopen = subscribe;
        ws.onmessage = dispatch_message;
    }

    function subscribe() {
        widgetMap.forEach(function(widget, id){
            ws.send(JSON.stringify({
                'action': 'subscribe',
                'id': id
            }));
        });
    }

    function dispatch_message(messageEvent) {
        let data = JSON.parse(messageEvent.data);
        let widget = widgetMap.get(data['id']).update(data['value']);
    }

    function writeValue(id, value) {
        ws.send(JSON.stringify({
            'action': 'write',
            'id': id,
            'value': value
        }));
    }

    window.onload = init;
})();


