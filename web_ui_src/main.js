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

import 'fomantic-ui-css/semantic.css';
import './main.css'

// semantic.js requires jQuery to be accessible as a global.
var jquery = require("jquery");
window.$ = window.jQuery = jquery;
require('fomantic-ui-css/semantic.js');

// Load SHC widget JS functionality
require('./shc_base.js');
require('./widgets/basic_widgets');
require('./widgets/colorchoser_widget');
require('./widgets/log_widgets');

// Make SHC_WIDGET_TYPES Map accessible for adding custom widgets from JavaScript sources
import {WIDGET_TYPES} from "./shc_base";
window.SHC_WIDGET_TYPES = WIDGET_TYPES;

// Set up UI with Semantic UI components
$(function() {
    $('.main-menu .ui.dropdown').dropdown();
    $('.ui.sidebar').sidebar({transition: 'overlay'}).sidebar('attach events', '#mobile_item');
});
