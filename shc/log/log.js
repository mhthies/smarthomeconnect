

function LogListWidget(domElement, _writeValue) {
    const id = parseInt(domElement.getAttribute('data-id'));
    const interval = parseInt(domElement.getAttribute('data-interval')); // in milliseconds
    const dateTimeFormat = new Intl.DateTimeFormat(undefined, {
        month: 'numeric', day: 'numeric', hour: 'numeric', minute: 'numeric', second: 'numeric'});
    this.subscribeIds = [id];

    let lastRow = null;

    /// Called regularly to remove old entries (older than `interval` milliseconds`)
    function cleanUp() {
        let now = new Date();
        let timeout = new Date(now.getTime() - interval);
        let children_reversed = Array.from(domElement.childNodes);
        children_reversed.reverse();
        for (let child of children_reversed) {
            if (child.logTimeStamp < timeout) {
                child.remove();
            } else {
                // rows are ordered, so we can break when finding the first one still in range.
                break;
            }
        }
    }
    setInterval(cleanUp, 5000);

    function addRow(timestamp, value) {
        // Create row
        let node = document.createElement("div");
        node.logTimeStamp = timestamp;
        domElement.prepend(node);

        // Add formatted timestamp
        node.appendChild(document.createTextNode(dateTimeFormat.format(timestamp)));

        // Add value box
        let value_box = document.createElement("div");
        value_box.classList.add('right');
        value_box.classList.add('floated');
        value_box.innerText = value;
        node.appendChild(value_box);

        return node;
    }

    this.update = function(value, for_id) {

        // Full initialization after (re)connect
        if (value['init']) {
            domElement.innerHTML = '';
            for (let row of value['data']) {
                // parse the timestamp
                let timestamp = Date.parse(row[0]);
                lastRow = addRow(timestamp, row[1]);
            }

        // Incremental update
        } else {
            for (let row of value['data']) {
                let timestamp = Date.parse(row[0]);
                // If timestamp is equal to the last record's timestamp, update that value
                if (lastRow && timestamp === lastRow.logTimeStamp) {
                    const last_value_box = lastRow.getElementsByTagName('div')[0];
                    last_value_box.innerText = row[1];

                // If the timestamp is newer, add a new row. If the row is older than the last row, we ignore it.
                } else if (!(lastRow && timestamp < lastRow.logTimeStamp)) {
                    lastRow = addRow(timestamp, row[1]);
                }
            }
        }
    };
}

WIDGET_TYPES.set('log.log_list', LogListWidget);
