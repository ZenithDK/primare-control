import binascii
import logging
import pykka
import serial
import struct

logger = logging.getLogger(__name__)

# Primare documentation on their RS232 protocol writes this:
#  == Command structure ==
#  Commands are sent to the device using the following format, where each field
#  is one byte sent to the device:
#  <STX> <command> <variable> [<value>] <DLE> <ETX>
#  The <command> can be either 'W' for write or 'R' for read. The variable
#  table that follows specifies which variables supports which <command> types.
#  If verbose is active, the device will send replies on the following format
#  either when a command is received or when the variable in question is
#  changed on the device.
#  <STX> <variable> [<value>] <DLE> <ETX>
#  Note that the <value> field can contain several bytes of data for certain
#  commands.
#  == Command special chars ==
#  <STX> = 0x02
#  <DLE> = 0x10
#  <ETX> = 0x03
#  Write = 0x57 (ASCII: W)
#  Read = 0x52 (ASCII: R)
#  == Escape sequence ==
#  If any variable or value byte is equal to <DLE>, this byte must be sent
#  twice to avoid confusing this with end of message.
#  Protocol settings
#  Baud rate: 4800
#  Bits: 8
#  Stop bits: 1
#  Parity: None
#  == Example ==
#  The specific variables and commands will be defined later, here are
#  examples on what the commands looks like in bytes.
#  Command to toggle verbose setting. Command is write, variable is 13 (0x0d)
#  and value is 0.
#  0x02 0x57 0x0xd 0x00 0x10 0x03
STX = slice(0, 1)
DLE_ETX = slice(-2, None)
CMD_VAR = slice(2, 3)
REPLY_VAR = slice(2, 3)
REPLY_DATA_BYTE = slice(2, 3)

primare_cmd = {
    'standby': b'\x02\x57\x81\x00\x10\x03',
    'operate': b'\x02\x57\x81\x01\x10\x03',
    'input': b'\x02\x57\x82\xAA\x10\x03',  # AA is input 01..07
    #  'mute_toggle': b'\x02\x57\x09\x00\x10\x03',
    'mute_enable': b'\x02\x57\x89\x01\x10\x03',
    'mute_disable': b'\x02\x57\x89\x00\x10\x03',
    'vol_up': b'\x02\x57\x03\x01\x10\x03',
    'vol_down': b'\x02\x57\x03\xFF\x10\x03',  # 0xFF = -1, or down one
    'vol_ctrl': b'\x02\x57\x83\xAA\x10\x03',  # AA is absolute volume 00..79
    'verbose_enable': b'\x02\x57\x8D\x01\x10\x03',
    'verbose_disable': b'\x02\x57\x8D\x00\x10\x03',
    'read_volume': b'\x02\x52\x03\x10\x03',  # TODO: Not in documentation - May need a '\x00' after 03?
    'read_inputname': b'\x02\x52\x14\x00\x10\x03',
    'read_manufacturer': b'\x02\x52\x15\x00\x10\x03',
    'read_modelname': b'\x02\x52\x16\x00\x10\x03',
    'read_swversion': b'\x02\x52\x17\x00\x10\x03',
}

primare_reply = {
    'standby': b'\x02\x01\x00\x10\x03',
    'operate': b'\x02\x01\x01\x10\x03',
    'input': b'\x02\x02\xAA\x10\x03',  # AA is input 01..07
    'mute_enable': b'\x02\x09\x01\x10\x03',
    'mute_disable': b'\x02\x09\x00\x10\x03',
    'vol_ctrl': b'\x02\x03\xAA\x10\x03',  # AA equals current volume
    'verbose_enable': b'\x02\x0D\x01\x10\x03',
    'verbose_disable': b'\x02\x0D\x00\x10\x03',  # Never sent: verbose disabled
    'read_inputname': b'\x02\x14\xAA\x10\x03',  # AA+.. = Variable length
    'read_manufacturer': b'\x02\x15\xAA\x10\x03',  # AA+.. = Variable length
    'read_modelname': b'\x02\x16\xAA\x10\x03',  # AA+.. = Variable length
    'read_swversion': b'\x02\x17\xAA\x10\x03',  # AA+.. = Variable length
}

# TODO:
# * IMPORTANT: Implement vol_up/vol_down so the default volume can be read by
#       incr and decr volume, instead of setting it to arbitrary default value
# * Read out from serial while using remote to see if replies are sent when
#   verbose is enabled
# * Check if the volume can be read out - otherwise set it to a default value
#   and adjust from that
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
    TIMEOUT = 2.8  # TODO: Test different values

    # Number of volume levels the amplifier supports.
    # Primare amplifiers have 79 levels
    VOLUME_LEVELS = 50  # TODO: Set to 50 for now as safe testing :) 79

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
        self._command_device('verbose_enable')
        self._get_device_model()

    def _set_device_to_known_state(self):
        self._power_device_on()
        self._select_input_source()
        self.mute(False)
        self._primare_volume = self._get_current_volume()

    def _get_device_model(self):
        manufacturer = self._ask_device('read_manufacturer')
        model = self._ask_device('read_modelname')
        swversion = self._ask_device('read_swversion')
        inputname = self._ask_device('read_inputname')

        logger.info("""Connected to:
            Manufacturer:  %s
            Model:         %s
            SW Version:    %s
            Current input: %s """, manufacturer, model, swversion, inputname)

    def _power_device_on(self):
        self._command_device('operate')

    def _select_input_source(self):
        if self.source is not None:
            self._command_device('input', '\x04')  # self.source.title())

    def mute(self, mute):
        if mute:
            self._command_device('mute_enable')
        else:
            self._command_device('mute_disable')

    def set_volume(self, volume):
        # Set the amplifier volume
        target_primare_volume = int(round(volume * self.VOLUME_LEVELS / 100.0))
        logger.debug('Setting volume to %d (%d)' %
                    (volume, target_primare_volume))
        return self._command_device('vol_ctrl', target_primare_volume)

    def _get_current_volume(self):
        # Set the amplifier volume
        volume_down = 0 #+ self._command_device('vol_down')
        volume_up = 0 #+ self._command_device('vol_up')
        logger.debug('Getting volume')
        if volume_up == volume_down + 1:
            self._primare_volume = volume_up
        return self._command_device('vol_ctrl', self._primare_volume)

    def _ask_device(self, request):
#        if type(primare_cmd[request]) == unicode:
#            request = request.encode('utf-8')
        #logger.info('LASSE: request "%s" - binary: "%s"' % (request, binascii.hexlify(primare_cmd[request])))
        self._write(primare_cmd[request])
        actual_reply = self._readline()
        logger.info('LASSE: _ask_device reply "%s"' % actual_reply)
        # TODO:
        # >>> values = { 'vol_up' : b'\x02\x57\xAA\x00\x10\x03'}
        # >>> hex = struct.unpack('cccccc', values['vol_up'])
        # >>> hex[2]
        # >>> '\xaa'
        if len(actual_reply) < 5:
            logger.info('Primare amplifier: Reply (%s) shorter than expected, len: %d' %
                        (actual_reply, len(actual_reply)))
            return
        else:
            actual_reply_hex = struct.unpack('c' * len(actual_reply))
            if self._validate_reply(request, primare_reply[request], reply_hex):
                return ''.join(reply_hex[1:-2])
            else:
                logger.info('Primare amplifier: Reply (%s) does not match \
                            expected reply (%s)',
                            binascii.unhexlify(reply_hex),
                            binascii.unhexlify(reply[request]))
                return

    def _command_device(self, cmd, option=None):
        cmd_hex = primare_cmd[cmd]
        if cmd == 'vol_up' or cmd == 'vol_down':
            expected_reply_hex = primare_reply['vol_ctrl']
        else:
            expected_reply_hex = primare_reply[cmd]
        #logger.info('LASSE: cmd_hex: "%s" - exp_reply_hex: "%s"' % (cmd_hex, expected_reply_hex))
        if option is not None:
            cmd_hex = cmd_hex.replace('\xAA', option)
            expected_reply_hex = expected_reply_hex.replace('\xAA', option)
        logger.info('Primare amplifier: Sending "%s" (%s)', cmd, binascii.hexlify(cmd_hex))
        self._write(cmd_hex)
        actual_reply_hex = binascii.hexlify(self._readline())
        if self._validate_reply(cmd, expected_reply_hex, actual_reply_hex):
            return actual_reply_hex[REPLY_DATA_BYTE]
        else:
            return

    def _validate_reply(self, cmd, expected_reply_hex, actual_reply_hex):
        if len(actual_reply_hex) < 5:
            logger.error('Reply length must at least be 5 bytes!')
            return False
        if (expected_reply_hex[STX] != actual_reply_hex[STX] or
                expected_reply_hex[DLE_ETX] != actual_reply_hex[DLE_ETX]):
            logger.info('Primare amplifier: Reply header/footer (%s) does not \
                        match expected reply (%s)',
                        binascii.unhexlify(actual_reply_hex),
                        binascii.unhexlify(expected_reply_hex))
            return False
        if primare_cmd[cmd][CMD_VAR] != actual_reply_hex[REPLY_VAR]:
            logger.info('Reply variable (%d) different from expected \
                        variable: %d',
                        primare_cmd[cmd][CMD_VAR], actual_reply_hex[REPLY_VAR])
        else:
            logger.info('Primare amplifier: Reply (%s)',
                        binascii.unhexlify(actual_reply_hex))
            return True

    def _write(self, data):
        # Write data to device
        if not self._device.isOpen():
            self._device.open()
        self._device.write('%s' % data)
        logger.debug('Write: "%s"', binascii.hexlify(data))

    def _readline(self):
        # Read line from device. The result is stripped for leading and
        # trailing whitespace.
        if not self._device.isOpen():
            self._device.open()
        result = self._device.readline().strip()
        if result:
            logger.debug('Read: "%s"', result)
        else:
            logger.debug('Read: "%s" - len: %d' % (result, len(result)))
        return result
