from setuptools import setup

setup(
    name='primare-receiver-control',
    version='0.1',
    py_modules=['yourscript'],
    install_requires=[
        'Click',
    ],
    entry_points='''
        [console_scripts]
        yourscript=yourscript:cli
    ''',
)