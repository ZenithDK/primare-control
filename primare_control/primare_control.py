"""Primare amplifier control.

This module allows you to control your Primare I22 and I32 amplifier from the
command line using Primare's binary protocol via the RS232 port on the
amplifier.
"""

from __future__ import with_statement

import binascii
import logging
import struct
import time

from threading import Thread
from twisted.internet import reactor
from twisted.internet.serialport import SerialPort
from twisted.protocols.basic import LineReceiver

# from twisted.logger import Logger
#
# logger = Logger()

# Setup logging so that is available
FORMAT = '%(asctime)-15s %(name)s %(levelname)-8s %(message)s'
logging.basicConfig(level=logging.DEBUG, format=FORMAT)

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
#  This is an example of a command to toggle verbose setting.
#  Command is write (0x57), variable is 13 (0x0d)
#  and value is 0. The footer is x10 x03
#  0x02 0x57 0x0xd 0x00 0x10 0x03
POS_STX = slice(0, 1)
POS_DLE_ETX = slice(-2, None)
POS_CMD_VAR = slice(2, 3)
POS_REPLY_VAR = slice(1, 2)
POS_REPLY_DATA = slice(2, None)
BYTE_STX = '\x02'
BYTE_WRITE = '\x57'
BYTE_READ = '\x52'
BYTE_DLE_ETX = '\x10\x03'

INDEX_CMD = 0
INDEX_VARIABLE = 1
INDEX_REPLY = 2
INDEX_WAIT = 3

PRIMARE_CMD = {
    'power_toggle': ['W', '0100', '01', True],
    'power_set': ['W', '81YY', '01YY', False],
    'input_set': ['W', '82YY', '02YY', True],
    'input_next': ['W', '0201', '02', True],
    'input_prev': ['W', '02FF', '02', True],
    'volume_set': ['W', '83YY', '03YY', True],
    'volume_get': ['W', '0300', '03', True],
    'volume_up': ['W', '0301', '03', True],
    'volume_down': ['W', '03FF', '03', True],
    'balance_adjust': ['W', '04YY', '04', True],
    'balance_set': ['W', '84YY', '04YY', True],
    'mute_toggle': ['W', '0900', '09', True],
    'mute_set': ['W', '89YY', '09YY', True],
    'dim_cycle': ['W', '0A00', '0A', True],
    'dim_set': ['W', '8AYY', '0AYY', True],
    'verbose_toggle': ['W', '0D00', '0D', True],
    'verbose_set': ['W', '8DYY', '0DYY', True],
    'menu_toggle': ['W', '0E01', '0E', True],
    'menu_set': ['W', '8EYY', '0EYY', True],
    'remote_cmd': ['W', '0FYY', 'YY', True],
    'ir_input_toggle': ['W', '1200', '12', True],
    'ir_input_set': ['W', '92YY', '12YY', True],
    'recall_factory_settings': ['R', '1300', '', False],
    'inputname_current_get': ['R', '1400', '14YY', True],
    'inputname_specific_get': ['R', '94YY', '94YY', True],
    'manufacturer_get': ['R', '1500', '15', True],
    'modelname_get': ['R', '1600', '16', True],
    'swversion_get': ['R', '1700', '17', True]
}

PRIMARE_REPLY = {
    '01': 'power',
    '02': 'input',
    '94': 'input',
    '03': 'volume',
    '04': 'balance',
    '09': 'mute',
    '0a': 'dim',
    '0d': 'verbose',
    '0e': 'menu',
    '12': 'ir_input',
    '13': 'recall_factory_settings',
    '14': 'inputname',
    '15': 'manufacturer',
    '16': 'modelname',
    '17': 'swversion'
}
# TODO:
# FIXING Better reply handling than table?
# * Better error handling
#       After suspend/resume, if volume up/down fails (or similar),
#       try turning amp on
#   Need to handle reads as "success" - now we get no reply
#
# LATER
# * v2: Seems like a factory would be better, so 'import primare_serial' then
#       primare_serial.initComs() which then creates the single Serial object.
#       http://stackoverflow.com/questions/6760685/creating-a-singleton-in-python/6798042#6798042
# * v2: Add notification callback mechanism to notify users of changes on
#       amp (dials or other SW)
#       http://bit.ly/WGRn0g
#       Better idea: websocket
#       http://forums.lantronix.com/showthread.php?p=3131
# * ...


class PrimareProtocol(LineReceiver):
    """Primare serial communication protocol."""

    def __init__(self, primare_talker=None, debug=False):
        r"""Initialization of LineReader.

        Default is to use BYTE_DLE_ETX (\10\03) delimiter and LineMode
        """
        self._debug = debug
        self._primare_talker = primare_talker
        self.delimiter = BYTE_DLE_ETX

    def connectionMade(self):
        """Indicate the connection is made."""
        if self._debug:
            logger.debug("Connection made to Primare")

    def connectionLost(self, reason):
        """Indicate that the connection is lost."""
        if self._debug:
            logger.debug("Lost connection to Primare due to '{}'".format(
                reason.getErrorMessage()))
        self._primare_talker = None

    def lineReceived(self, data):
        """Handle each line received by Twisted's SerialPort."""
        if self._debug:
            logger.debug("Serial LineRX({}): '{}'".format(len(data), data))
        self._primare_talker._primare_reader(data)


class PrimareController():
    """This class provides methods for controlling a Primare amplifier."""

    # Number of volume levels the amplifier supports.
    # Primare amplifiers have 79 levels
    _VOLUME_LEVELS = 79

    def __init__(self,
                 port="/dev/ttyUSB0",
                 baudrate=4800,
                 source=None,
                 volume=None,
                 debug=False):
        """Initialization."""
        self._serial_protocol = None
        self._thread_id = None

        self._device_info_print = True  # Only print device info once
        self._manufacturer = ''
        self._modelname = ''
        self._swversion = ''
        self._inputname = ''
        if source:
            self.input_set(source)
        # Volume in range 0..VOLUME_LEVELS.
        if volume:
            self.volume_set(volume)

        if debug:
            logger.setLevel(logging.DEBUG)

        self._serial_protocol = PrimareProtocol(self, debug)
        logger.debug('About to open serial port {0} [{1} baud] ..'.format(
            port,
            baudrate))
        SerialPort(protocol=self._serial_protocol,
                   deviceNameOrPortNumber=port,
                   reactor=reactor,
                   baudrate=int(baudrate))
        self._thread_id = Thread(name="TwistedReactor", target=reactor.run, args=((False,)))
        self._thread_id.start()

    def close(self):
        """Close down PrimareController transport and threads."""
        logger.info("close")
        self._serial_protocol.transport.loseConnection()
        reactor.callFromThread(reactor.stop)
        self._thread_id.join()

    # Private methods
    def _set_device_to_known_state(self):
        logger.debug('_set_device_to_known_state')
        self.verbose_set(True)
        self.power_on()
        self.mute_set(False)

    def _primare_reader(self, rawdata):
        logger.debug('_primare_reader - decoded: %s', binascii.hexlify(rawdata))

        # For some reason, an empty line is retrieved sometimes
        # This is seen after input_next/prev.
        if len(rawdata):
            variable_char, decoded_data = self._decode_raw_data(rawdata)

            if variable_char in ['14', '15', '16', '17']:
                self._parse_and_store(variable_char, decoded_data)
        else:
            logger.info("Received empty string")

    def _decode_raw_data(self, rawdata):
        r"""Decode raw data from the serial port.

        Replace any '\x10\x10' sequences with '\x10'.
        Returns the variable char and the data received between the STX and
        DLE+ETX markers
        """
        variable_char = ''
        data = ''

        # logger.debug('Read: "%s"', binascii.hexlify(rawdata))
        byte_string = struct.unpack('c' * len(rawdata), rawdata)
        variable_char = binascii.hexlify(''.join(byte_string[POS_REPLY_VAR]))
        byte_string = byte_string[POS_REPLY_DATA]

        # We need to replace double DLE (0x10) with single DLE
        for byte_pairs in zip(byte_string[0:None:2],
                              byte_string[1:None:2]):
            # Convert binary tuple to str to ascii
            str_pairs = binascii.hexlify(''.join(byte_pairs))
            if str_pairs == '1010':
                data += '10'
            else:
                data += str_pairs
        # Very often we have an odd amount of data which not handled by
        # the zip above, manually append that one byte
        if len(byte_string) % 2 != 0:
            data += binascii.hexlify(byte_string[-1])

        logger.debug('Read(%s) = %s (%s)', PRIMARE_REPLY[variable_char], data,
                     binascii.hexlify(rawdata))
        return variable_char, data

    def _parse_and_store(self, variable_char, data):
        logger.debug('_parse_and_store - index: "%s" - %s',
                     variable_char,
                     binascii.unhexlify(data))
        if variable_char == '14':
            self._inputname = data
            if self._device_info_print is True:
                self._device_info_print = False
                logger.info("""Connected to:
                            Manufacturer:  %s
                            Model:         %s
                            SW Version:    %s
                            Current input: %s """,
                            binascii.unhexlify(self._manufacturer),
                            binascii.unhexlify(self._modelname),
                            binascii.unhexlify(self._swversion),
                            binascii.unhexlify(self._inputname))
        elif variable_char == '15':
            self._manufacturer = data
        elif variable_char == '16':
            self._modelname = data
        elif variable_char == '17':
            self._swversion = data

    def _send_command(self, variable, option=None):
        """Send command to the amplifier with optional data.

        Variable: String key for the PRIMARE_CMD dict
        Option: String value needed for some of the commands, None if unused
        """
        command = PRIMARE_CMD[variable][INDEX_CMD]
        data = PRIMARE_CMD[variable][INDEX_VARIABLE]
        if option is not None:
            data = data.replace('YY', option)
        logger.debug('_send_command(%s), data: "%s"', variable, data)
        self._write(command, data)

    def _write(self, cmd_type, data):
        r"""Write data to the serial port.

        Any occurences of '\x10' must be replaced with '\x10\x10' and add
        the STX and DLE+ETX markers
        """
        # We need to replace single DLE (0x10) with double DLE
        # Seems redundant as there is no '0x10' command, and we only have one
        # variable that could be 0x10, followed by 0x10 0x03
        data_safe = ''
        for index in range(0, len(data) - 1, 2):
            pair = data[index:index + 2]
            if pair == '10':
                data_safe += '1010'
            else:
                data_safe += pair
        # Convert ascii string to binary
        binary_variable = binascii.unhexlify(data_safe)

        binary_data = BYTE_STX
        binary_data += BYTE_WRITE if cmd_type == 'W' else BYTE_READ
        binary_data += binary_variable + BYTE_DLE_ETX

        logger.debug('WriteHex: %s', binascii.hexlify(binary_data))
        self._serial_protocol.sendLine(binary_data)
        # TODO: Find a better way around this
        # Needed as we otherwise shut down too quickly, we won't have
        # time to read the buffer and parse the data.
        time.sleep(0.05)

    # Public methods
    def setup(self):
        """Setup the amplifier.

        Set the receiver to a known state:
        - Power on
        - Verbose mode on
        - Unmute
        Print information about the amplifier
        """
        self._set_device_to_known_state()
        self.device_info()

    def device_info(self):
        """Retrieve and print information on Primare amplifier."""
        self._device_info_print = True
        self.manufacturer_get()
        self.modelname_get()
        self.swversion_get()
        # We always get inputname last, this represents our initialization
        self.inputname_current_get()

    def power_on(self):
        """Power on the Primare amplifier."""
        self._send_command('power_set', '01')

    def power_off(self):
        """Power off the Primare amplifier."""
        self._send_command('power_set', '00')

    def power_toggle(self):
        """Toggle the power to the Primare amplifier.

        :rtype: :class:True if amplifier turned on as result of toggle,
          :class:False otherwise
        """
        self._send_command('power_toggle')

    def input_set(self, source):
        """Set the current input used by the Primare amplifier.

        Valid values are between 1 and 12 for I32.
        For I22 the valid values are between 1 and 7.
        1 = IN1
        2 = IN2
        3 = IN3
        4 = IN4
        5 = IN5
        6 = MEDIA
        7 = DIG1
        8 = DIG2
        9 = DIG3
        10 = DIG4
        11 = PC
        12 = BT
        """
        self._send_command('input_set', '{:02X}'.format(int(source) % 13))
        self.inputname_current_get()

    def input_next(self):
        """Select next input on device.
        
        After changing the input, we request the input name.
        """
        self._send_command('input_next')
        self.inputname_current_get()

    def input_prev(self):
        """Select previous input on device.
        
        After changing the input, we request the input name.
        """
        self._send_command('input_prev')
        self.inputname_current_get()

    def volume_get(self):
        """Get volume level of the amplifier on a linear scale from 0 to 79.

        Example values:
        0: Silent
        79: Maximum volume.
        """
        self._send_command('volume_get')

    def volume_set(self, volume):
        """Set volume level of the amplifier.

        Range is 0-79.
        """
        self._send_command('volume_set', '{:02X}'.format(
            volume if volume < 80 else 0x4F))
        # There's a crazy bug where setting the volume to 65 and above will
        # generate a reply indicating a volume of 1 less!?
        # Hence the work-around
        # if reply and (int(reply, 16) == target_primare_volume or
        #              int(reply, 16) == target_primare_volume - 1):
        #    self._volume = volume
        #    logger.debug("LASSE - target volume SUCCESS, _volume: %d",
        #                 self._volume)
        #    return True
        # else:
        #    return False

    def volume_up(self):
        """Increase volume by one step."""
        self._send_command('volume_up')

    def volume_down(self):
        """Decrease volume by one step."""
        self._send_command('volume_down')

    def balance_adjust_left(self):
        """Adjust balance to left."""
        self._send_command('balance_adjust', '{:02X}'.format(0x01))

    def balance_adjust_right(self):
        """Adjust balance to right."""
        self._send_command('balance_adjust', '{:02X}'.format(0xFF))

    def balance_set(self, balance):
        """Set specific balance setting.

        Value 0 means centered.
        1-9 adjusts balance to the right
        11-19 adjusts balance to the left.
        The documentation seems inconsistent with the real world?
        """
        if balance > 10:
            balance = 0xFF - (balance - 11)
        logger.info("balance set arg: {}".format(balance))
        self._send_command('balance_set', "{:02X}".format(balance))

    def mute_toggle(self):
        """Toggle mute on device."""
        self._send_command('mute_toggle')

    def mute_get(self):
        """Get mute state of the mixer."""
        self._send_command('mute_get')

    def mute_set(self, mute):
        """Enable or disable mute on device.

        True = mute
        False = Unmute
        """
        mute_value = '01' if mute is True else '00'
        self._send_command('mute_set', mute_value)

    def dim_cycle(self):
        """Cycle through the different dim levels on device."""
        self._send_command('dim_cycle')

    def dim_set(self, level):
        """Select a specific dim level on device."""
        if level >= 0:
            self._send_command('dim_set', '{:02X}'.format(int(level) % 4))

    def verbose_toggle(self):
        """Toggle verbose mode on device.

        When verbose is active, device will respond to commands and inform
        about changes to variables.
        """
        self._send_command('verbose_toggle')

    def verbose_set(self, verbose):
        """Enable or disables verbose mode on device.

        True = Enable verbose mode.
        False = Disable verbose mode.
        """
        verbose_value = '01' if verbose is True else '00'
        self._send_command('verbose_set', verbose_value)

    def menu_toggle(self):
        """Enter or leaves menu of device."""
        self._send_command('menu_toggle')

    def menu_set(self, menu):
        """Control menus on the amplifier.

        Allow closing of the menu or stepping into or out of a submenu if the
        menu is active.
        """
        self._send_command('menu_set', '{:02X}'.format(int(menu)))

    def remote_cmd(self, cmd):
        """Send an IR command to the device.

        The command will be treated as if the IR remote control has been used
        to send the command.
        """
        self._send_command('remote_cmd', cmd)

    def ir_input_toggle(self):
        """Toggle IR input source on device between front and back."""
        self._send_command('ir_input_toggle')

    def ir_input_set(self, ir_input):
        """Select either front or back as current IR input source on device.

        False = Front,
        True = Back
        """
        ir_value = '01' if ir_input is True else '00'
        self._send_command('ir_input_set', ir_value)

    def recall_factory_settings(self):
        """Perform a factory reset.

        Restore default values and restart the device.
        """
        self._send_command('recall_factory_settings')

    def manufacturer_get(self):
        """Read manufacturer name from the device."""
        self._send_command('manufacturer_get')

    def modelname_get(self):
        """Read model name from device."""
        self._send_command('modelname_get')

    def swversion_get(self):
        """Read current software version from device."""
        self._send_command('swversion_get')

    def inputname_current_get(self):
        """Read current input name from device."""
        self._send_command('inputname_current_get')

    def inputname_specific_get(self, input):
        """Read specified input name from device."""
        if input >= 0:
            self._send_command('inputname_specific_get',
                               '{:02X}'.format((int(input) % 8)))
