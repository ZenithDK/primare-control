"""Mixer that controls volume using a Primare amplifier."""

from __future__ import unicode_literals

import logging

import pygst
pygst.require('0.10')
import gobject
import gst

try:
    import serial
except ImportError:
    serial = None  # noqa

from mopidy_primare import talker


logger = logging.getLogger(__name__)


class PrimareMixer(gst.Element, gst.ImplementsInterface, gst.interfaces.Mixer):
    __gstdetails__ = (
        'PrimareMixer',
        'Mixer',
        'Mixer to control Primare amplifiers using a serial link',
        'Mopidy')

    port = gobject.property(type=str, default='/dev/ttyUSB0')
    source = gobject.property(type=str)

    _volume_cache = 0
    _primare_talker = None

    def list_tracks(self):
        track = create_track(
            label='Master',
            initial_volume=0,
            min_volume=0,
            max_volume=100,
            num_channels=1,
            flags=(
                gst.interfaces.MIXER_TRACK_MASTER |
                gst.interfaces.MIXER_TRACK_OUTPUT))
        return [track]

    def get_volume(self, track):
        return [self._volume_cache]

    def set_volume(self, track, volumes):
        if len(volumes):
            volume = volumes[0]
            self._volume_cache = volume
            self._primare_talker.set_volume(volume)

    def set_mute(self, track, mute):
        self._primare_talker.mute(mute)

    def do_change_state(self, transition):
        if transition == gst.STATE_CHANGE_NULL_TO_READY:
            if serial is None:
                logger.warning('primaremixer dependency pyserial not found')
                return gst.STATE_CHANGE_FAILURE
            self._start_primare_talker()
        return gst.STATE_CHANGE_SUCCESS

    def _start_primare_talker(self):
        self._primare_talker = talker.PrimareTalker.start(
            port=self.port,
            source=self.source or None,
        ).proxy()


def create_track(label, initial_volume, min_volume, max_volume,
                 num_channels, flags):

    class Track(gst.interfaces.MixerTrack):
        def __init__(self):
            super(Track, self).__init__()
            self.volumes = (initial_volume,) * self.num_channels

        @gobject.property
        def label(self):
            return label

        @gobject.property
        def min_volume(self):
            return min_volume

        @gobject.property
        def max_volume(self):
            return max_volume

        @gobject.property
        def num_channels(self):
            return num_channels

        @gobject.property
        def flags(self):
            return flags

    return Track()
