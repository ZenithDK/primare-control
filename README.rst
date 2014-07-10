**********
Mopidy-Primare
**********

.. image:: https://pypip.in/v/Mopidy-Primare/badge.png
    :target: https://pypi.python.org/pypi/Mopidy-Primare/
    :alt: Latest PyPI version

.. image:: https://pypip.in/d/Mopidy-Primare/badge.png
    :target: https://pypi.python.org/pypi/Mopidy-Primare/
    :alt: Number of PyPI downloads

.. image:: https://travis-ci.org/ZenithDK/mopidy-primare.png?branch=master
    :target: https://travis-ci.org/ZenithDK/mopidy-primare
    :alt: Travis CI build status

.. image:: https://coveralls.io/repos/ZenithDK/mopidy-primare/badge.png?branch=master
   :target: https://coveralls.io/r/ZenithDK/mopidy-primare?branch=master
   :alt: Test coverage

`Mopidy <http://www.mopidy.com/>`_ extension for controlling volume using an
external Primare amplifier. Developed and tested with a Primare i22.


Installation
============

Install by running::

    sudo pip install Mopidy-Primare

Or, if available, install the Debian/Ubuntu package from `apt.mopidy.com
<http://apt.mopidy.com/>`_.


Configuration
=============

The Mopidy-Primare extension is enabled by default. To disable it, add the
following to ``mopidy.conf``::

    [primare]
    enabled = false

The Primare amplifier must be connected to the machine running Mopidy using a
serial cable.

To use the Primare amplifier ot control volume, set the ``audio/mixer`` config
value in ``mopidy.conf`` to ``primaremixer``. You probably also needs to add some
properties to the ``audio/mixer`` config value.

Supported properties includes:

- ``port``: The serial device to use, defaults to ``/dev/ttyUSB0``. This must
  be set correctly for the mixer to work.

- ``source``: The source that should be selected on the amplifier, like
  ``aux``, ``disc``, ``tape``, ``tuner``, etc. Leave unset if you don't want
  the mixer to change it for you.

- ``speakers-a``: Set to ``on`` or ``off`` if you want the mixer to make sure
  that speaker set A is turned on or off. Leave unset if you don't want the
  mixer to change it for you.

- ``speakers-b``: See ``speakers-a``.

Configuration examples::

    # Minimum configuration, if the amplifier is available at /dev/ttyUSB0
    [audio]
    mixer = primaremixer

    # Minimum configuration, if the amplifier is available elsewhere
    [audio]
    mixer = primaremixer port=/dev/ttyUSB3

    # Full configuration
    [audio]
    mixer = primaremixer port=/dev/ttyUSB0 source=aux speakers-a=on speakers-b=off


Project resources
=================

- `Source code <https://github.com/ZenithDK/mopidy-primare>`_
- `Issue tracker <https://github.com/ZenithDK/mopidy-primare/issues>`_
- `Download development snapshot <https://github.com/ZenithDK/mopidy-primare/tarball/master#egg=Mopidy-Primare-dev>`_


Changelog
=========

v0.1 (2014-07-10)
-----------------

- Copied from Mopidy-NAD
