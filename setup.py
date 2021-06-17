#!/usr/bin/env python
import os.path
from setuptools import setup, find_packages

with open(os.path.join(os.path.dirname(__file__), 'README.md'), encoding='utf-8') as f:
    long_description = f.read()

setup(
    name='smarthomeconnect',
    version='0.3.1',
    description='The Smart Home Connect home automation framework based on AsyncIO',
    long_description=long_description,
    long_description_content_type='text/markdown',
    author='Michael Thies',
    author_email='mail@mhthies.de',
    url='https://github.com/mhthies/smarthomeconnect',
    packages=find_packages(),
    include_package_data=True,
    python_requires='~=3.7',
    install_requires=[
        'aiohttp>=3.6,<4',
        'jinja2>=2.11,<3',
        'MarkupSafe>=1.1,<2',
    ],
    extras_require={
        'mysql': ['aiomysql==0.0.21'],
        'knx': ['knxdclient~=0.3.0'],
        'dmx': ['pyserial-asyncio==0.3'],
        'midi': ['mido>=1.2.9,<2', 'python-rtmidi>=1.4.6,<2'],
        'mqtt': ['paho-mqtt>=1.5.1,<2', 'asyncio-mqtt>=0.8.0,<0.9'],
    },
    classifiers=[
        'Development Status :: 3 - Alpha',
        'Programming Language :: Python :: 3.7',
        'Programming Language :: Python :: 3.8',
        'Programming Language :: Python :: 3.9',
        'License :: OSI Approved :: Apache Software License',
        'Topic :: Home Automation',
        'Framework :: AsyncIO',
    ],
)
