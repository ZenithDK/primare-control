from __future__ import absolute_import, unicode_literals

import re

from setuptools import find_packages, setup


def get_version(filename):
    with open(filename) as fh:
        metadata = dict(re.findall("__([a-z]+)__ = '([^']+)'", fh.read()))
        return metadata['version']

setup(
    name='Primare-Control',
    version=get_version('primare_control/__init__.py'),
    url='https://github.com/ZenithDK/primare_control',
    license='Apache License, Version 2.0',
    author='Lasse Bigum',
    author_email='lasse@bigum.org',
    description='Control your Primare amplifier via Python',
    long_description=open('README.rst').read(),
    #py_modules=['primare_control'],
    packages=find_packages(exclude=['tests', 'tests.*']),
    zip_safe=False,
    include_package_data=True,
    install_requires=[
        'Click',
        'pyserial',
        'setuptools',
        'twisted',
    ],
    test_suite='nose.collector',
    tests_require=[
        'nose',
        'mock >= 1.0',
    ],
    entry_points='''
        [console_scripts]
        primare_control=primare_control.primare_interface:cli
    ''',
    classifiers=[
        'Environment :: No Input/Output (Daemon)',
        'Intended Audience :: End Users/Desktop',
        'License :: OSI Approved :: Apache Software License',
        'Operating System :: OS Independent',
        'Programming Language :: Python :: 2',
        'Topic :: Multimedia :: Sound/Audio :: Players',
    ],
)
