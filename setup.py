from __future__ import unicode_literals

import re

from setuptools import find_packages, setup


def get_version(filename):
    content = open(filename).read()
    metadata = dict(re.findall("__([a-z]+)__ = '([^']+)'", content))
    return metadata['version']


setup(
    name='Primare-Control',
    py_modules=['primare_control'],
    version=get_version('primare_control/__init__.py'),
    url='https://github.com/ZenithDK/primare_control',
    license='Apache License, Version 2.0',
    author='Lasse Bigum',
    author_email='lasse@bigum.org',
    description='Control your Primare amplifier via Python',
    long_description=open('README.rst').read(),
    packages=find_packages(exclude=['tests', 'tests.*']),
    zip_safe=False,
    include_package_data=True,
    install_requires=[
        'setuptools',
        'Click',
        'twisted',
    ],
    test_suite='nose.collector',
    tests_require=[
        'nose',
        'mock >= 1.0',
    ],
    entry_points='''
        [console_scripts]
        primare_control=primare_control:cli
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
