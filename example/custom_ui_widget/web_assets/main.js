/* Copyright 2021 Michael Thies <mail@mhthies.de>
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

function CrossHairWidget(domElement, _writeValue) {
    // We could use the provided writeValue callback function to send a value to a WebUIConnector object the server,
    // identified by its id. In this case, the widget is read-only, so we don't need the function.

    // this.subscribeIds must contain the Python WebUIConnector object id(s) to which we want to subscribe for value
    // updates. The Python template is in charge to provide us with the relevant Python object ids in the HTML page,
    // typically as `data-` attributes of the widget's DOM element:
    this.subscribeIds = [parseInt(domElement.getAttribute('data-id'))];

    const indicator_element = domElement.querySelector('.indicator');

    // This method is called whenever a value update is received from one of the subscribed WebUIConnector objects.
    this.update = function(value, _for_id) {
        // the for_id parameter could be used to distinguish updates for different objects, if we subscribed to more
        // than one object id
        indicator_element.style.left = Math.round(value[0] * 100 + 100).toString() + 'px';
        indicator_element.style.top = Math.round(value[1] * 100 + 100).toString() + 'px';
    };
}

// Add the new widget type to the global Map of SHC widget types, to be constructed for each DOM element with the
// attribute value data-widget="crosshair"
SHC_WIDGET_TYPES.set('crosshair', CrossHairWidget);
