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

import iro from '@jaames/iro';
import {WIDGET_TYPES} from "../shc_base";


import './colorchoser_widget.css'

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

WIDGET_TYPES.set('colorchoser', ColorChoserWidget);
