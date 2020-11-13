# Copyright 2020 Michael Thies <mail@mhthies.de>
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may not use this file except in compliance with
# the License. You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software distributed under the License is distributed on an
# "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the License for the
# specific language governing permissions and limitations under the License.
import datetime
import random

import shc.log.in_memory
import shc.log.widgets
from shc.log import AggregationMethod

random_float_log = shc.log.in_memory.InMemoryPersistenceVariable(float, keep=datetime.timedelta(minutes=10))
random_bool_log = shc.log.in_memory.InMemoryPersistenceVariable(bool, keep=datetime.timedelta(minutes=10))

# Some hacks to prefill logs with random data
ts = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=7.5)
while ts < datetime.datetime.now(datetime.timezone.utc):
    random_bool_log.data.append((ts, bool(random.getrandbits(1))))
    ts += datetime.timedelta(seconds=random.uniform(0.2, 90))
ts = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=10)
while ts < datetime.datetime.now(datetime.timezone.utc):
    random_float_log.data.append((ts, random.uniform(0, 40)))
    ts += datetime.timedelta(seconds=random.uniform(0.2, 90))


# Now, generate new events at random intervals
@shc.timer.every(datetime.timedelta(seconds=20), random=datetime.timedelta(seconds=19.8))
@shc.handler()
async def new_float(_v, _o):
    await random_float_log.write(random.uniform(0, 40))


@shc.timer.every(datetime.timedelta(seconds=20), random=datetime.timedelta(seconds=19.8))
@shc.handler()
async def new_bool(_v, _o):
    await random_bool_log.write(bool(random.getrandbits(1)))


# The web server and web page
web_server = shc.web.WebServer('localhost', 8081, index_name='index')
index_page = web_server.page('index', 'Home', menu_entry=True, menu_icon='home')


#############################################################################################
# Log list widget                                                                           #
#############################################################################################
index_page.add_item(shc.log.widgets.LogListWidget(random_bool_log, datetime.timedelta(minutes=5)))

index_page.add_item(shc.log.widgets.LogListWidget(random_bool_log, datetime.timedelta(minutes=5),
                                                  aggregation=AggregationMethod.ON_TIME))

index_page.add_item(shc.log.widgets.LogListWidget(random_float_log, datetime.timedelta(minutes=5)))

index_page.add_item(shc.log.widgets.LogListWidget(random_float_log, datetime.timedelta(minutes=5),
                                                  aggregation=AggregationMethod.AVERAGE))

index_page.new_segment()

index_page.add_item(shc.log.widgets.ChartWidget(random_float_log, datetime.timedelta(minutes=5)))

index_page.add_item(shc.log.widgets.ChartWidget(random_float_log, datetime.timedelta(minutes=5),
                                                aggregation=AggregationMethod.AVERAGE))


if __name__ == '__main__':
    shc.main()
