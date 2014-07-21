
from __future__ import with_statement

import binascii
import logging
import pykka
import serial
import struct
import threading

import time

logger = logging.getLogger(__name__)

#from mopidy_primare import primare_serial
#pt = primare_serial.PrimareTalker.start(port="/dev/ttyUSB0", input_source=None).proxy()
#pt.power_on()

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
POS_STX = slice(0, 1)
POS_DLE_ETX = slice(-2, None)
POS_CMD_VAR = slice(2, 3)
POS_REPLY_VAR = slice(1, 2)
POS_REPLY_DATA = slice(2, -2)
BYTE_STX = '\x02'
BYTE_WRITE = '\x57'
BYTE_READ = '\x52'
BYTE_DLE_ETX = '\x10\x03'

CMD = 0
VARIABLE = 1
REPLY = 2

PRIMARE_CMD = {
    'power_toggle': ['W', '0100', '01'],
    'power_on': ['W', '8101', '0101'],
    'power_off': ['W', '8100', '0100'],
    'input_set': ['W', '82YY', '02YY'],
    'input_next': ['W', '0201', '02'],
    'input_prev': ['W', '02FF', '01'],
    'volume_set': ['W', '83FF', '03FF'],
    'volume_up': ['W', '0301', '03'],
    'volume_down': ['W', '03FF', '03'],
    'balance_adjust': ['W', '04YY', '04'],
    'balance_set': ['W', '84YY', '04YY'],
    'mute_toggle': ['W', '0900', '09'],
    'mute_set': ['W', '89YY', '09YY'],
    'dim_cycle': ['W', '0A00', '0A'],
    'dim_set': ['W', '0AYY', '8AYY'],
    'verbose_toggle': ['W', '0D00', '0D'],
    'verbose_set': ['W', '8DYY', '0DYY'],
    'menu_toggle': ['W', '0E01', '0E'],
    'menu_set': ['W', '8EYY', '0EYY'],
    'remote_cmd': ['W', '0FYY', 'YY'],
    'ir_input_toggle': ['W', '1200', '12'],
    'ir_input_set': ['W', '92YY', '12YY'],
    'recall_factory_settings': ['R', '1300', ''],
    'inputname_current_get': ['R', '1400', '14YY'],
    'inputname_specific_get': ['R', '94YY', '94YY'],
    'manufacturer_get': ['R', '1500', '15'],
    'modelname_get': ['R', '1600', '16'],
    'swversion_get': ['R', '1700', '17']
}
# TODO:
# * IMPORTANT: Implement vol_up/vol_down so the default volume can be read by
#       incr and decr volume, instead of setting it to arbitrary default value
#     -- Done, but something is amiss, update to 0.19 first and test again
# * Read out from serial while using remote to see if replies are sent when
#   verbose is enabled
#     -- Replies ARE sent, need another thread to handle input and update status??
#     -- use this for EOL: http://pyserial.sourceforge.net/shortintro.html (pyserial eol)
# * Volume starts at 0? Test using ncmpcpp
# * Better error handling
# * ASAP: Update to 0.19 API
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
    # confirmations and calibration will decrease volume forever. If you set
    # the timeout too high, stuff takes more time. 0.8s seems like a good value
    # for Primare I22.
    TIMEOUT = 0.8

    # Number of volume levels the amplifier supports.
    # Primare amplifiers have 79 levels
    VOLUME_LEVELS = 79

    def __init__(self, port, input_source):
        super(PrimareTalker, self).__init__()

        self._port = port
        self._input_source = input_source
        self._device = None
        self._lock = threading.Lock()

        # Volume in range 0..VOLUME_LEVELS. :class:`None` before calibration.
        self._volume = None
        logger.debug('__init__ was called')

    def on_start(self):
        logger.debug('on_start is called')
        logging.basicConfig(level=logging.DEBUG)
        self._open_connection()
        self._set_device_to_known_state()
        self._print_device_info()
        self._primare_reader()

    # Private methods
    def _open_connection(self):
        logger.info('Primare amplifier: Connecting through "%s"', self._port)
        self._device = serial.Serial(
            port=self._port,
            baudrate=self.BAUDRATE,
            bytesize=self.BYTESIZE,
            parity=self.PARITY,
            stopbits=self.STOPBITS,
            timeout=self.TIMEOUT)

    def _set_device_to_known_state(self):
        logger.debug('_set_device_to_known_state')
        logger.debug('SET POWER ON')
        self.power_on()
        logger.debug('SET VERBOSE TRUE')
        self.verbose_set(True)
        logger.debug('SET INPUT SOURCE')
        if self._input_source is not None:
            self.input_set(self._input_source)
        self.mute_set(False)
        self._volume = self._get_current_volume()

    def _print_device_info(self):
        manufacturer = self._send_command('manufacturer_get')
        model = self._send_command('modelname_get')
        swversion = self._send_command('swversion_get')
        inputname = self._send_command('inputname_current_get')
        logger.info("""Connected to:
            Manufacturer:  %s
            Model:         %s
            SW Version:    %s
            Current input: %s """, manufacturer, model, swversion, inputname)

    def _primare_reader(self):
        # The reader will forever do readline, unless _send_command
        # takes the lock to send a command and get a reply
        time.sleep(5)
        logger.debug('_primare_reader - starting')
        # while(True):
        #     print "_primare_reader - pre lock"
        #     with self._lock:
        #         print "_primare_reader - in lock"
        #         logger.debug("_primare_reader running")
        #         reply = self._readline()
        #         print "_primare_reader - readline"
        #         if reply != "":
        #             self._handle_unsolicited_reply()
        #     print "_primare_reader - post lock"

    def _get_current_volume(self):
        volume = self.volume_down()
        if volume is not None:
            return self.volume_set(volume + 1)
        else:
            return None

    def _send_command(self, variable, option=None):
        #if type(value) == unicode:
        #    value = value.encode('utf-8')
        #logger.debug('_send_command - pre lock - lock.locked: %s',
        #             self._lock.locked())
        with self._lock:
            #logger.debug('_send_command - in lock')
            command = PRIMARE_CMD[variable][VARIABLE]
            data = PRIMARE_CMD[variable][CMD]
            if option is not None:
                logger.debug('_send_command - replace YY with "%s"', option)
                data = data.replace('YY', option)
            #logger.debug(
            #    '_send_command - before write - data: "%s", option: "%s"',
            #    data, option)
            self._write(command, data)
            logger.debug('_send_command - after write - data: %s', data)
            reply = self._readline()
        logger.debug('_send_command - post lock')
        #logger.debug('HU HEJ - reply: %s' % binascii.hexlify(reply))
        return reply

    def _handle_unsolicited_reply(self):
        pass

    def _validate_reply(self, variable, actual_reply_hex, option=None):
        pass

    def _write(self, cmd_type, data):
        # We need to replace single DLE (0x10) with double DLE to discern it
        data_safe = ''
        for index in xrange(0, len(data) - 1, 2):
            pair = data[index:index + 2]
            if pair == '10':
                data_safe += '1010'
            else:
                data_safe += pair
        # Convert ascii string to binary
        binary_cmd = binascii.unhexlify(data_safe)
        if cmd_type == 'W':
            binary_data = BYTE_STX + BYTE_WRITE + binary_cmd + BYTE_DLE_ETX
        else:
            binary_data = BYTE_STX + BYTE_READ + binary_cmd + BYTE_DLE_ETX
        # Write data to device.
        if not self._device.isOpen():
            self._device.open()
        self._device.write(binary_data)
        logger.debug('WriteHex(S): %s', binascii.hexlify(binary_data))

    def _readline(self):
        # Read line from device.
        if not self._device.isOpen():
            self._device.open()
        #eol = binascii.hexlify(BYTE_DLE_ETX)
        #result = self._device.readline(eol)
        result = self._device.readline()

        if result:
            logger.debug('Read: "%s"', binascii.hexlify(result))
            reply_string = struct.unpack('c' * len(result), result)

            # We need to replace single DLE (0x10) with double DLE to discern it
            data_safe = ''
            for index in xrange(0, len(reply_string) - 1, 2):
                pair = reply_string[index:index + 2]
                if pair == '10':
                    data_safe += '1010'
                else:
                    data_safe += pair

            result = ''.join(data_safe[POS_REPLY_DATA])
        else:
            logger.debug('Read(0): "%s" - len: %d' % (binascii.hexlify(result), len(result)))
        return result

    # Public methods
    def power_on(self):
        print "POWER ON"
        self._send_command('power_on')

    def power_off(self):
        print "POWER OFF"
        self._send_command('power_off')

    def power_toggle(self):
        pass

    def input_set(self, input_source):
        print "INPUT SET"
        self._send_command('input_set', input_source)

    def input_next(self):
        pass

    def input_prev(self):
        pass

    def volume_get(self):
        return self._volume

    def volume_set(self, volume):
        pass

    def volume_up(self):
        pass

    def volume_down(self):
        pass

    def balance_adjust(self, adjustment):
        pass

    def balance_set(self, balance):
        pass

    def mute_toggle(self):
        pass

    def mute_set(self, mute):
        pass

    def dim_cycle(self):
        pass

    def dim_set(self, level):
        pass

    def verbose_toggle(self):
        pass

    def verbose_set(self, verbose):
        if verbose:
            self._send_command('verbose_set', '01')
        else:
            self._send_command('verbose_set', '00')

    def menu_toggle(self, verbose):
        pass

    def menu_set(self, menu):
        pass

    def remote_cmd(self, cmd):
        pass

    def ir_input_toggle(self):
        pass

    def ir_input_set(self, ir_input):
        pass

    def recall_factory_settings(self):
        pass

    def manufacturer_get(self):
        pass

    def modelname_get(self):
        pass

    def swversion_get(self):
        pass

    def inputname_current_get(self):
        pass

    def inputname_specific_get(self, input):
        pass
