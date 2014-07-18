
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
REPLY = 1
PRIMARE_CMD = {
    'power_toggle': ['0100', '01'],
    'power_on': ['8101', '0101'],
    'power_off': ['8100', '0100'],
    'ir_input_set': ['02YY', '02YY'],
    'input_next': ['0201', '02'],
    'input_prev': ['02FF', '01'],
    'volume_set': ['83FF', '03FF'],
    'volume_up': ['0301', '03'],
    'volume_down': ['03FF', '03'],
    'balance_adjust': ['04YY', '04'],
    'balance_set': ['84YY', '04YY'],
    'mute_toggle': ['0900', '09'],
    'mute_set': ['89YY', '09YY'],
    'dim_cycle': ['0A00', '0A'],
    'dim_set': ['0AYY', '8AYY'],
    'verbose_toggle': ['0D00', '0D'],
    'verbose_set': ['8DYY', '0DYY'],
    'menu_toggle': ['0E01', '0E'],
    'menu_set': ['8EYY', '0EYY'],
    'remote_cmd': ['0FYY', 'YY'],
    'ir_input_toggle': ['1200', '12'],
    'ir_input_set': ['92YY', '12YY'],
    'recall_factory_settings': ['1300', ''],
    'inputname_current_get': ['1400', '14YY'],
    'inputname_specific_get': ['94YY', '94YY'],
    'manufacturer_get': ['1500', '15'],
    'modelname_get': ['16', '16'],
    'swversion_get': ['17', '17']
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

    def on_start(self):
        self._open_connection()
        #self._print_device_info()
        #self._set_device_to_known_state()
        pass

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
        self.verbose_set(True)
        self.operate()
        self.input_set(self._input_source)
        self.mute(False)
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
        print "_primare_reader - starting"
        while(True):
            print "_primare_reader - pre lock"
            with self._lock:
                print "_primare_reader - in lock"
                logger.debug("_primare_reader running")
                reply = self._readline()
                print "_primare_reader - readline"
                if reply != "":
                    self._handle_unsolicited_reply()
            print "_primare_reader - post lock"

    def _get_current_volume(self):
        volume = self.volume_down()
        return self.volume_set(volume + 1)

    def _send_command(self, cmd, option=None):
        #if type(value) == unicode:
        #    value = value.encode('utf-8')
        print "_send_command - pre lock"
        print "_send_command - pre lock - lock.locked: %s" % self._lock.locked()
        with self._lock:
            print "_send_command - in lock"
            cmd = PRIMARE_CMD['power_on'][CMD]
            if option is not None:
                cmd = cmd.replace('YY', option)
            self._write(cmd)
            reply = self._readline()
            print "HU HEJ - reply: %s" % binascii.hexlify(reply)
        print "_send_command - post lock"

    def _handle_unsolicited_reply(self):
        pass

    def _validate_reply(self, cmd, actual_reply_hex, option=None):
        pass

    def _write(self, data):
        # Write data to device.
        if not self._device.isOpen():
            self._device.open()
        # We need to replace single DLE (0x10) with double DLE to discern it
        data = data.replace('10', '1010')
        # Convert ascii string to binary
        data_hex = binascii.unhexlify(data)
        data = BYTE_STX + BYTE_WRITE + data_hex + BYTE_DLE_ETX
        self._device.write(data)
        logger.debug('Write: %s', data)

    def _readline(self):
        # Read line from device.
        if not self._device.isOpen():
            self._device.open()
        eol = binascii.hexlify(BYTE_DLE_ETX)
        result = self._device.readline(eol)
        logger.debug('Read: %s', binascii.hexlify(result))  # if result else "")
        if result:
            reply_string = struct.unpack('c' * len(result), result)
            # reply_string = reply_string.replace('1010', '10') # TODO: How to do this?
            result = ''.join(reply_string[POS_REPLY_DATA])
        return result

    # Public methods
    def power_on(self):
        print "POWER ON"
        self._send_command('power_on')

    def power_off(self):
        self._send_command('power_off')

    def power_toggle(self):
        pass

    def input_set(self, input_source):
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
        pass

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
