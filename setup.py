#!/usr/bin/env python
# Copyright 2020-2021 Michael Thies <mail@mhthies.de>
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may not use this file except in compliance with
# the License. You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software distributed under the License is distributed on an
# "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the License for the
# specific language governing permissions and limitations under the License.

import subprocess
from setuptools import setup
from setuptools.command.build_py import build_py


class custom_build_py(build_py):
    def run(self):
        subprocess.check_call(['npm', 'install'])
        subprocess.check_call(['npm', 'run', 'build'])
        super().run()


setup(
    cmdclass={
        'build_py': custom_build_py
    },
)
