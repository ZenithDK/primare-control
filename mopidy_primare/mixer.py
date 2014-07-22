"""Mixer that controls volume using a Primare amplifier."""

from __future__ import unicode_literals

from mopidy import mixer

import logging
import primare_serial
import pykka

logger = logging.getLogger(__name__)


class PrimareMixer(pykka.ThreadingActor, mixer.Mixer):

    name = 'primare'

    def __init__(self, config):
        super(PrimareMixer, self).__init__(config)

        self.port = config['primare']['port']
        self.source = config['primare']['source'] or None

        self._volume_cache = 0
        self._mute_cache = False

        self._primare = None

        # Volume in range 0..VOLUME_LEVELS, None before calibration.
        self._primare_volume = None

    def on_start(self):
        self._connect_primare()

    def get_volume(self):
        return self._volume_cache

    def set_volume(self, volume):
        # Increase or decrease the amplifier volume until it matches the given
        # target volume.
        logger.debug('Setting volume to %d' % volume)
        success = self._primare.volume_set(volume)
        if success:
            self._volume_cache = volume
            self.trigger_volume_changed(volume)
        return success

    def get_mute(self):
        return self._mute_cache

    def set_mute(self, mute):
        success = self._primare.mute_set(mute)
        if success:
            self._mute_cache = mute
            self.trigger_mute_changed(mute)
        return success

    def _connect_primare(self):
        logger.info('Primare mixer: Connecting through "%s", using input: %s',
                    self.port,
                    self.source if self.source is not None else "<DEFAULT>")
        self._primare = primare_serial.PrimareTalker.start(
            port=self.port, input_source=self.source
            ).proxy()
