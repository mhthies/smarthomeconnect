

function LogListWidget(domElement, _writeValue) {
    const id = parseInt(domElement.getAttribute('data-id'));
    this.subscribeIds = [id];

    this.update = function(value, for_id) {
        for (let row of value) {
            let node = document.createElement("div");
            node.appendChild(document.createTextNode(row[0] + "  --  " + row[1]));
            domElement.appendChild(node);
        }
    };
}

WIDGET_TYPES.set('log.log_list', LogListWidget);
