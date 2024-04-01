
import {
    Chart,
    LineElement,
    LineController,
    LinearScale,
    TimeScale,
    Decimation,
    Filler,
    Legend,
    Tooltip,
    _adapters,
    PointElement
} from 'chart.js';
import {WIDGET_TYPES} from "../shc_base";

Chart.register(
  LineElement,
  PointElement,
  LineController,
  LinearScale,
  TimeScale,
  Decimation,
  Filler,
  Legend,
  Tooltip
);

import './log_list_widget.css'

function LogListWidget(domElement, _writeValue) {
    const interval = parseInt(domElement.getAttribute('data-interval')); // in milliseconds
    const dateTimeFormat = new Intl.DateTimeFormat(undefined, {
        month: 'numeric', day: 'numeric', hour: 'numeric', minute: 'numeric', second: 'numeric'});
    const objectSpecs = JSON.parse(domElement.getAttribute('data-spec'));

    this.subscribeIds = [];  // filled in the loop below
    let lastRowMap = new Map();  // maps Python object id to the last visible entry of that object in the log list
    let colorMap = new Map();  // maps the Python object id to the color class to be added to rows of that object

    for (const spec of objectSpecs) {
        this.subscribeIds.push(spec.id);
        colorMap.set(spec.id, spec.color);
    }

    /// Called regularly to remove old entries (older than `interval` milliseconds`)
    function cleanUp() {
        let now = new Date();
        let timeout = new Date(now.getTime() - interval);
        let children_reversed = Array.from(domElement.childNodes);
        children_reversed.reverse();
        for (let child of children_reversed) {
            if (child.logTimeStamp < timeout) {
                child.remove();
                if (lastRowMap.get(child.logObjectId) === child)
                    lastRowMap.delete(child.logObjectId);
            } else {
                // rows are ordered, so we can break when finding the first one still in range.
                break;
            }
        }
    }
    setInterval(cleanUp, 5000);

    function addRow(timestamp, value, objectId) {
        // Create row
        let node = document.createElement("div");
        node.setAttribute("class", "item " + colorMap.get(objectId));
        node.logTimeStamp = timestamp;
        node.logObjectId = objectId;

        // Search correct position to insert
        let nextRow = null;
        for (let someRow of domElement.childNodes) {
            if (someRow.logTimeStamp <= timestamp) {
                break;
            }
            nextRow = someRow;
        }
        if (nextRow) {
            nextRow.after(node);
        } else {
            domElement.prepend(node);
        }

        // Add value box
        let value_box = document.createElement("div");
        value_box.setAttribute("class", "right floated content the-value");
        value_box.innerHTML = value;
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
            for (let rowElement of domElement.childNodes) {
                if (rowElement.logObjectId === for_id) {
                    rowElement.remove();
                }
            }
            for (let row of value['data']) {
                // parse the timestamp
                let timestamp = Date.parse(row[0]);
                let rowElement = addRow(timestamp, row[1], for_id);
                lastRowMap.set(for_id, rowElement);
            }

        // Incremental update
        } else {
            let lastRow = lastRowMap.get(for_id);
            for (let row of value['data']) {
                let timestamp = Date.parse(row[0]);
                // If timestamp is equal to the last record's timestamp, update that value
                if (lastRow && timestamp === lastRow.logTimeStamp) {
                    const last_value_box = lastRow.getElementsByClassName('the-value')[0];
                    last_value_box.innerHTML = row[1];


                // If the timestamp is newer, add a new row. If the row is older than the last row, we ignore it.
                } else if (!(lastRow && timestamp < lastRow.logTimeStamp)) {
                    let rowElement = addRow(timestamp, row[1], for_id);
                    lastRowMap.set(for_id, rowElement);
                }
            }
        }
    };
}

WIDGET_TYPES.set('log.log_list', LogListWidget);


function LineChartWidget(domElement, _writeValue) {
    const seriesSpec = JSON.parse(domElement.getAttribute('data-spec'));
    const interval = parseInt(domElement.getAttribute('data-interval')); // in milliseconds
    const alignTicksTo = parseInt(domElement.getAttribute('data-align-ticks-to'));

    this.subscribeIds = [];  // filled in the dataset initialization below

    let tickInterval = chartTickInterval(interval, 8);  // TODO: let it depend on diagram width

    // datasets (and subscribeIds)
    let datasets = [];
    let dataMap = new Map();  // maps the Python datapoint/object id to the associated chart dataset's data list
    let numStacked = 0;
    for (const spec of seriesSpec) {
        this.subscribeIds.push(spec.id);
        let data = [];
        datasets.push({
            data: data,
            label: spec.label,
            backgroundColor: (spec.style == "area"
                              ? `rgba(${spec.color[0]}, ${spec.color[1]}, ${spec.color[2]}, 0.5)`
                              : `rgba(${spec.color[0]}, ${spec.color[1]}, ${spec.color[2]}, 0.1)`),
            borderColor: `rgba(${spec.color[0]}, ${spec.color[1]}, ${spec.color[2]}, .5)`,
            pointBackgroundColor: `rgba(${spec.color[0]}, ${spec.color[1]}, ${spec.color[2]}, 0.5)`,
            pointBorderColor: `rgba(${spec.color[0]}, ${spec.color[1]}, ${spec.color[2]}, 0.5)`,
            stepped: ["before", "after"].includes(spec.interpolation) ? spec.interpolation : undefined,
            pointRadius: spec.style == "line_dots" ? 3 : 0,
            pointHitRadius: 5,
            tension: spec.interpolation == "smooth" ? 0.2 : 0.0,
            stack: spec.stack_group,
            fill: (spec.style == "area" || spec.style == "line_filled"
                   ? (spec.stack_group !== null && numStacked > 0 ? "-1" : "origin")
                   : undefined),
            showLine: ["line", "line_filled", "line_dots"].includes(spec.style),
        });
        dataMap.set(spec.id, [data, spec]);
        if (spec.stack_group !== null) {
            numStacked++;
        }
    }

    // Initialize chart
    let ctx = domElement.getContext('2d');
    let theChart = new Chart(ctx, {
        type: 'line',
        data: {
            datasets: datasets,
            labels: []
        },
        options: {
            plugins: {
                legend: {
                    display: (datasets.length > 1)
                },
                tooltip: {
                    callbacks: {
                        label: function(context) {
                            let label = context.dataset.label || '';
                            if (label) {
                                label += ': ';
                            }
                            label += context.formattedValue;
                            let unit_symbol = seriesSpec[context.datasetIndex].unit_symbol || '';
                            if (unit_symbol) {
                                label += " " + unit_symbol;
                            }
                            return label;
                        }
                    }
                }
            },
            scales: {
                x: {
                    type: 'time',
                    min: new Date(new Date() - interval),
                    max: new Date(),
                    ticks: {
                        source: 'labels',
                    }
                },
                y: {
                    stacked: numStacked > 0 ? true : false,
                }
            },
            responsive: true
        }
    });

    /** To shift the diagram's xaxis and call the diagram's update() method */
    function shiftAndUpdate() {
        let now = new Date();
        let begin = new Date(now.getTime() - interval);

        // Set xAxis minimum and maximum
        theChart.options.scales.x.max = now;
        theChart.options.scales.x.min = begin;

        // Calculate new ticks
        let firstTick = alignTicksTo + tickInterval * Math.ceil((begin.getTime() - alignTicksTo) / tickInterval);
        let ticks = [];
        let tick = firstTick;
        while (tick < now) {
            ticks.push(new Date(tick));
            tick += tickInterval;
        }
        theChart.data.labels = ticks;

        for ([i, dataset] of theChart.data.datasets.entries()) {
            if (seriesSpec[i].extend_graph_to_now && dataset.data.length > 0) {
                dataset.data[dataset.data.length - 1].x = new Date(new Date().getTime() + 10000);
            }
        }

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

        let splicedDatasets = 0;
        for (let dataset of theChart.data.datasets) {
            let currentData = dataset.data;
            if (!currentData.length)
                continue;

            let i = 0;
            for (;i < currentData.length; i++) {
                if (currentData[i].x >= timeout)
                    break;
            }
            let begin = Math.max(0, i-1);
            if (begin > 0) {
                currentData.splice(0, begin);
                splicedDatasets++;
            }
        }
        // If we deleted points, do a chart update without animation. Otherwise we do a little unwanted animation party
        // due to the shift in the datapoint indices.
        if (splicedDatasets)
            theChart.update(0);
    }
    setInterval(function() {
        cleanUp();
        shiftAndUpdate();
    }, Math.max(interval / 500, 5000));

    this.update = function(value, for_id) {
        let [data, spec] = dataMap.get(for_id);

        // Full initialization after (re)connect
        if (value['init']) {
            data.length = 0;
            for (let row of value['data']) {
                data.push({
                    x: Date.parse(row[0]),
                    y: row[1]
                });
            }
            if (spec.extend_graph_to_now && data.length > 0) {
                data.push({
                    x: new Date(new Date().getTime() + 10000),
                    y: data[data.length - 1].y
                });
            }

        // Incremental update
        } else {
            if (data.length && spec.extend_graph_to_now) {
                data.pop();
            }
            let lastEntry = data.length ? data[data.length - 1] : null;
            for (let row of value['data']) {
                let timestamp = Date.parse(row[0]);
                // If timestamp is equal to the last record's timestamp, update that value
                if (lastEntry && timestamp === lastEntry.x) {
                    console.debug(`Updating last value of dataset with ${row}`);
                    lastEntry.y = row[1];

                // If the timestamp is newer, add a new row. If the row is older than the last row, we ignore it.
                } else if (!(lastEntry && timestamp < lastEntry.x)) {
                    console.debug(`Adding entry ${row} to chart`);
                    data.push({
                        x: timestamp,
                        y: row[1]
                    });
                } else {
                    console.warn(`chart update ${row} ignored, since it is older than the current last row`);
                }
            }
            if (spec.extend_graph_to_now && data.length > 0) {
                data.push({
                    x: new Date(new Date().getTime() + 10000),
                    y: data[data.length - 1].y
                });
            }
        }
        shiftAndUpdate();
    };
}

const second = 1000; const minute = 60000; const hour = 3600000; const day = 86400000;
const tickIntervals = [
    25, 50, 100, 250, 500,
    second, 2*second, 5*second, 10*second, 20*second, 30*second,
    minute, 2*minute, 5*minute, 10*minute, 20*minute, 30*minute,
    hour, 2*hour, 3*hour, 6*hour, 12*hour,
    day, 2*day, 5*day, 10*day, 20*day, 30*day, 60*day, 90*day, 120*day, 365*day,
    2*365*day, 3*365*day, 5*365*day, 10*365*day
]

function chartTickInterval(interval, maxTicks) {
    for (let int of tickIntervals) {
        if (interval / int < maxTicks) {
            return int;
        }
    }
    throw "No suiting tick interval found. 10 years is too less.";
}

WIDGET_TYPES.set('log.line_chart', LineChartWidget);

/**
 * This is a minimal datetime adapter for Chart.js which does not need an external library, but does not provide `add`,
 * `startOf`, `endOf` methods. It uses Intl.DateTimeFormat for date formatting.
 *
 * This is fine, since we define our bounds and tick interval manually, so we only need the
 * adapter for date formatting.
 */
_adapters._date.override({
	_id: 'minimal-intl',

	formats: function() {
		let result = {
            datetime: new Intl.DateTimeFormat(undefined, {
                year: 'numeric', month: 'numeric', day: 'numeric', hour: 'numeric', minute: 'numeric',
                second: 'numeric'}),
            millisecond: new Intl.DateTimeFormat(undefined, {
                hour: 'numeric', minute: 'numeric', second: 'numeric'}),
            second: new Intl.DateTimeFormat(undefined, {
                hour: 'numeric', minute: 'numeric', second: 'numeric'}),
            minute: new Intl.DateTimeFormat(undefined, {hour: 'numeric', minute: 'numeric'}),
            hour: new Intl.DateTimeFormat(undefined, {hour: 'numeric', minute: 'numeric'}),
            day: new Intl.DateTimeFormat(undefined, {month: 'numeric', day: 'numeric'}),
            week: new Intl.DateTimeFormat(undefined, {month: 'numeric', day: 'numeric'}),
            month: new Intl.DateTimeFormat(undefined, {year: 'numeric', month: 'numeric'}),
            quater: new Intl.DateTimeFormat(undefined, {year: 'numeric', month: 'numeric'}),
            year: new Intl.DateTimeFormat(undefined, {year: 'numeric'})
        }
        // A dirty hack to fix Chart.js' magic `merge` function (or more precisely: the `clone` function) for the
        // DateTimeFormat objects on browers which do not yet have correct @@toStringTags for the Intl library
        // (see https://caniuse.com/mdn-javascript_builtins_intl_--tostringtag):
        // We simply add an intermediate object in the prototype chain of our DateTimeFormat objects, which injects the
        // correct @@toStringTag
        let DTFProto = {};
        DTFProto[Symbol.toStringTag] = "Intl.DateTimeFormat";
        DTFProto.__proto__ = Intl.DateTimeFormat.prototype;
        for (const key in result) {
            result[key].__proto__ = DTFProto;
        }
        return result;
	},

	parse: function(value, fmt) {
		return value;
	},

	format: function(time, fmt) {
		return fmt.format(time);
	},

	add: undefined,

	diff: function(max, min, unit) {
		switch (unit) {
            case 'millisecond': return (max-min);
            case 'second': return (max-min)/second;
            case 'minute': return (max-min)/minute;
            case 'hour': return (max-min)/hour;
            case 'day': return (max-min)/day;
            case 'week': return (max-min)/day/7;
            case 'month': return (max-min)/day/30;
            case 'quarter': return (max-min)/7884000000;
            case 'year': return (max-min)/day/365;
            default: return 0;
		}
	},

	startOf: undefined,
	endOf: undefined
});
