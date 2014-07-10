import binascii
import logging
import pykka
import serial

logger = logging.getLogger(__name__)

cmd = {
  'standby'           : b'\x02\x57\x81\x00\x10\x03',
  'operate'           : b'\x02\x57\x81\x01\x10\x03',
  'input'             : b'\x02\x57\x82\xAA\x10\x03', # AA is input 01..07
#  'mute_toggle'       : b'\x02\x57\x09\x00\x10\x03',
  'mute_enable'       : b'\x02\x57\x89\x01\x10\x03',
  'mute_disable'      : b'\x02\x57\x89\x00\x10\x03',
# 'vol_up'            : b'\x02\x57\x03\x01\x10\x03',
# 'vol_down'          : b'\x02\x57\x03\xFF\x10\x03', # 0xFF = -1, or down one
  'vol_ctrl'          : b'\x02\x57\x83\xAA\x10\x03', # AA is absolute volume 00..79
  'verbose_enable'    : b'\x02\x57\x8D\x01\x10\x03',
  'verbose_disable'   : b'\x02\x57\x8D\x00\x10\x03',
  'read_volume'       : b'\x02\x52\x03\x10\x03',     # TODO: Not in documentation - May need a '\x00' after 03?
  'read_inputname'    : b'\x02\x52\x14\x00\x10\x03',
  'read_manufacturer' : b'\x02\x52\x15\x00\x10\x03',
  'read_modelname'    : b'\x02\x52\x16\x00\x10\x03',
  'read_swversion'    : b'\x02\x52\x17\x00\x10\x03',
}

primare_reply = {
  'standby'           : b'\x02\x01\x00\x10\x03',
  'operate'           : b'\x02\x01\x01\x10\x03',
  'input'             : b'\x02\x02\xAA\x10\x03', # AA is input 01..07
  'mute_enable'       : b'\x02\x09\x01\x10\x03',
  'mute_disable'      : b'\x02\x09\x00\x10\x03',
  'vol_ctrl'          : b'\x02\x03\xAA\x10\x03', # AA equals current volume
  'verbose_enable'    : b'\x02\x0D\x01\x10\x03',
  'verbose_disable'   : b'\x02\x0D\x00\x10\x03', # Never sent as verbose is disabled ;-)
  'read_inputname'    : b'\x02\x14\xAA\x10\x03', # AA+.. = Variable length name returned
  'read_manufacturer' : b'\x02\x15\xAA\x10\x03', # AA+.. = Variable length name returned
  'read_modelname'    : b'\x02\x16\xAA\x10\x03', # AA+.. = Variable length name returned
  'read_swversion'    : b'\x02\x17\xAA\x10\x03', # AA+.. = Variable length name returned
}

# TODO:
# * IMPORTANT: Implement vol_up/vol_down so the default volume can be read by incr and decr volume,
#              instead of setting it to arbitrary default value
# * Read out from serial while using remote to see if replies are sent when verbose is enabled
# * Check if the volume can be read out - otherwise set it to a default value and adjust from that
# * Enable verbose in _set_device_to_known_state
# * Newlines or not?
# * ...

class PrimareTalker(pykka.ThreadingActor):
    """
    Independent thread which does the communication with the Primare amplifier.

    Since the communication is done in an independent thread, Mopidy won't
    block other requests while doing rather time consuming work like
    calibrating the Primare amplifier's volume.
    """

    # Serial link config
    BAUDRATE = 4800
    BYTESIZE = 8
    PARITY = 'N'
    STOPBITS = 1

    # Timeout in seconds used for read/write operations.
    # If you set the timeout too low, the reads will never get complete
    # confirmations. If you set the timeout too high, stuff takes more time.
    # 0.8s seems like a good value for Primare i22.
    TIMEOUT = 0.8 # TODO: Test different values

    # Number of volume levels the amplifier supports.
    # Primare amplifiers have 79 levels
    VOLUME_LEVELS = 79

    def __init__(self, port, source):
        super(PrimareTalker, self).__init__()

        self.port = port
        self.source = source
        self._device = None

        # Volume in range 0..VOLUME_LEVELS. :class:`None` before calibration.
        self._primare_volume = None

    def on_start(self):
        self._open_connection()
        self._set_device_to_known_state()

    def _open_connection(self):
        logger.info('Primare amplifier: Connecting through "%s"', self.port)
        self._device = serial.Serial(
            port=self.port,
            baudrate=self.BAUDRATE,
            bytesize=self.BYTESIZE,
            parity=self.PARITY,
            stopbits=self.STOPBITS,
            timeout=self.TIMEOUT)
        self._get_device_model()

    def _set_device_to_known_state(self):
        self._power_device_on()
        self._select_input_source()
        self.mute(False)
        self._command_device(primare_cmd['verbose_enable'])
        #self._primare_volume = self.get_volume()

    def _get_device_model(self):
        manufacturer = self._ask_device(primare_cmd['read_manufacturer'])
        model = self._ask_device(primare_cmd['read_modelname'])
        swversion = self._ask_device(primare_cmd['read_swversion'])
        inputname = self._ask_device(primare_cmd['read_inputname'])

        logger.info("""Connected to:
            Manufacturer:  %s
            Model:         %s
            SW Version:    %s
            Current input: %s """, manufacturer, model, swversion, inputname)

    def _power_device_on(self):
        self._command_device(primare_cmd['operate'])

    def _select_input_source(self):
        if self.source is not None:
            self._command_device(primare_cmd['input'].replace('XX', '\x04')) #self.source.title())

    def mute(self, mute):
        if mute:
            self._command_device(primare_cmd['mute_enable'])
        else:
            self._command_device(primare_cmd['mute_disable'])

    def set_volume(self, volume):
        # Set the amplifier volume
        target_primare_volume = int(round(volume * self.VOLUME_LEVELS / 100.0))
        logger.debug('Setting volume to %d (%d)' % (volume, target_primare_volume))
        return self._command_device(primare_cmd['vol_ctrl'])

    def _ask_device(self, request):
        self._write(request)
        reply = self._readline()
        # TODO:
        # >>> values = { 'vol_up' : b'\x02\x57\xAA\x00\x10\x03'}
        # >>> hex = struct.unpack('cccccc', values['vol_up'])
        # >>> hex[2]
        # >>> '\xaa'

        struct.unpack(
        return .replace('%s=' % key, '')

    def _command_device(self, cmd):
            logger.info(
                'Primare amplifier: Setting "%s" to "%s" (attempt %d/3)',
                key, value, attempt)
        if type(value) == unicode:
            value = value.encode('utf-8')
        self._write(cmd)
        return self._readline() == reply[]

    def _write(self, data):
        # Write data to device
        if not self._device.isOpen():
            self._device.open()
        self._device.write('\n%s\n' % data)
        logger.debug('Write: %s', data)

    def _readline(self):
        # Read line from device. The result is stripped for leading and
        # trailing whitespace.
        if not self._device.isOpen():
            self._device.open()
        result = self._device.readline().strip()
        if result:
            logger.debug('Read: %s', result)
        return result
