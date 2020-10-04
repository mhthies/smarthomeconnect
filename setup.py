#!/usr/bin/env python
from setuptools import setup, find_packages

setup(
    name='smarthomeconnect',
    version='0.1',
    description='The Smart Home Connect home automation framework based on AsyncIO',
    author='Michael Thies',
    author_email='mail@mhthies.de',
    url='https://github.com/mhthies/smarthomeconnect',
    packages=find_packages(),
    include_package_data=True,
    python_requires='~=3.7',
    install_requires=[
        'aiohttp>=3.6,<4',
        'aiomysql==0.0.20',
        'jinja2>=2.11,<3',
        'MarkupSafe>=1.1,<2',
        'knxdclient==0.2.1',
        'pyserial-asyncio==0.3',
    ],
    classifiers=[
        'Development Status :: 3 - Alpha',
        'Programming Language :: Python :: 3.7',
        'Programming Language :: Python :: 3.8',
        'License :: OSI Approved :: Apache Software License',
        'Topic :: Home Automation',
        'Framework :: AsyncIO',
    ],
)
