

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
        node.setAttribute("class", "item");
        node.logTimeStamp = timestamp;
        domElement.prepend(node);

        // Add value box
        let value_box = document.createElement("div");
        value_box.setAttribute("class", "right floated content the-value");
        value_box.innerText = value;
        node.appendChild(value_box);

        // Add timestamp box
        let ts_box = document.createElement("div");
        ts_box.setAttribute("class", "content");
        ts_box.innerText = dateTimeFormat.format(timestamp);
        node.appendChild(ts_box);

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
                    const last_value_box = lastRow.getElementsByClassName('the-value')[0];
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


function LineChartWidget(domElement, _writeValue) {
    const id = parseInt(domElement.getAttribute('data-id'));
    const interval = parseInt(domElement.getAttribute('data-interval')); // in milliseconds
    const is_aggregated = domElement.getAttribute('data-aggregated') === "True";
    const alignTicksTo = parseInt(domElement.getAttribute('data-align-ticks-to'));
    const dateTimeFormat = new Intl.DateTimeFormat(undefined, {
        month: 'numeric', day: 'numeric', hour: 'numeric', minute: 'numeric', second: 'numeric'});
    this.subscribeIds = [id];

    let lastRow = null;
    let tickInterval = chartTickInterval(interval, 8);  // TODO: let it depend on diagram width

    // Initialize chart
    let ctx = domElement.getContext('2d');
    let theChart = new Chart(ctx, {
        type: 'line',
        data: {
            datasets: [{
                data: [],
                steppedLine: is_aggregated ? undefined : 'before',
                pointRadius: is_aggregated ? 3 : 0,
                lineTension: 0.2,
            }],
            labels: []
        },
        options: {
            legend: {
                display: false
            },
            scales: {
                xAxes: [{
                    type: 'time',
                    distribution: 'linear',
                    ticks: {
                        min: new Date(new Date() - interval),
                        max: new Date(),
                        source: 'labels',
                    }
                }]
            },
            responsive: true
        }
    });

    /** To shift the diagram's xaxis and call the diagram's update() method */
    function shiftAndUpdate() {
        let now = new Date();
        let begin = new Date(now.getTime() - interval);

        // Set xAxis minimum and maximum
        theChart.options.scales.xAxes[0].ticks.max = now;
        theChart.options.scales.xAxes[0].ticks.min = begin;

        // Calculate new ticks
        let firstTick = alignTicksTo + tickInterval * Math.ceil((begin.getTime() - alignTicksTo) / tickInterval);
        let ticks = [];
        let tick = firstTick;
        while (tick < now) {
            ticks.push(new Date(tick));
            tick += tickInterval;
        }
        theChart.data.labels = ticks;

        theChart.update();
    }

    /** Called regularly (and when a new entry is added) to move the diagram and remove old entries (older than
    * `interval` milliseconds`)
    *
    * Must be called before shiftAndUpdate, as otherwise the synchronous diagram update() within this function will
    * cancel the animated diagram update.
    */
    function cleanUp() {
        let now = new Date();
        let timeout = new Date(now.getTime() - interval);

        let currentData = theChart.data.datasets[0].data;
        if (currentData.length) {
            let i = 0;
            for (;i < currentData.length; i++) {
                if (currentData[i].x >= timeout)
                    break;
            }
            let begin = Math.max(0, i-1);
            if (begin > 0) {
                theChart.data.datasets[0].data = currentData.slice(begin);
                // Do an chart update without animation. Otherwise we do a little unwanted animation party due to the
                // shift in the datapoint indices.
                theChart.update(0);
            }
        }
    }
    setInterval(function() {
        cleanUp();
        shiftAndUpdate();
    }, 5000);

    this.update = function(value, for_id) {
        let data = theChart.data.datasets[0].data;

        // Full initialization after (re)connect
        if (value['init']) {
            data.length = 0;
            for (let row of value['data']) {
                data.push({
                    x: Date.parse(row[0]),
                    y: row[1]
                });
            }

        // Incremental update
        } else {
            let lastRow = data.length ? data[data.length - 1] : null;
            for (let row of value['data']) {
                let timestamp = Date.parse(row[0]);
                // If timestamp is equal to the last record's timestamp, update that value
                if (lastRow && timestamp === lastRow.x) {
                    lastRow.y = row[1];

                // If the timestamp is newer, add a new row. If the row is older than the last row, we ignore it.
                } else if (!(lastRow && timestamp < lastRow.x)) {
                    data.push({
                        x: timestamp,
                        y: row[1]
                    });
                }
            }
        }
        shiftAndUpdate();
    };
}

function chartTickInterval(interval, maxTicks) {
    const second = 1000; const minute = 60000; const hour = 3600000; const day = 86400000;
    const tickIntervals = [
        25, 50, 100, 250, 500,
        second, 2*second, 5*second, 10*second, 20*second, 30*second,
        minute, 2*minute, 5*minute, 10*minute, 20*minute, 30*minute,
        hour, 2*hour, 3*hour, 6*hour, 12*hour,
        day, 2*day, 5*day, 10*day, 20*day, 30*day, 60*day, 90*day, 120*day, 365*day,
        2*365*day, 3*365*day, 5*365*day, 10*365*day
    ]
    for (let int of tickIntervals) {
        if (interval / int < maxTicks) {
            return int;
        }
    }
    throw "No suiting tick interval found. 10 years is too less.";
}

WIDGET_TYPES.set('log.line_chart', LineChartWidget);
