###############################################################################
#
#  Copyright (C) 2012-2014 Tavendo GmbH
#
#  Licensed under the Apache License, Version 2.0 (the "License");
#  you may not use this file except in compliance with the License.
#  You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
#  limitations under the License.
#
###############################################################################


import argparse
import logging
import sys
import time

from threading import Thread

from twisted.internet.serialport import SerialPort
from twisted.protocols.basic import LineReceiver
from twisted.internet import reactor
from twisted.internet import task

# from twisted.logger import (
#     FilteringLogObserver,
#     globalLogBeginner,
#     Logger,
#     LogLevel,
#     LogLevelFilterPredicate,
#     textFileLogObserver
# )

# log = Logger()

# globalLogBeginner.beginLoggingTo([
#     FilteringLogObserver(
#         textFileLogObserver(sys.stdout),
#         [LogLevelFilterPredicate(LogLevel.debug)]
#     )
# ])

from primare_serial import PrimareTalker

logger = logging.getLogger(__name__)
# Setup logging so that is available
logging.basicConfig(level=logging.DEBUG)

primare_talker = None

class PrimareProtocol(LineReceiver):
    """
    Primare serial communication protocol.
    """
    def __init__(self, debug=False):
        self._debug = debug
        self._primare_talker = primare_talker

        self.setRawMode()
        self._rawBuffer = bytearray()

    def wrapSendLine(self, line):
        logger.debug('LASSE wrapLine: {}'.format(line))
        self.sendLine(line)

    def connectionMade(self):
        logger.info('Serial port connected.')

    def lineReceived(self, line):
        logger.info('LASSE - BOOOOM!!! ERROR')

    def rawDataReceived(self, data):
        if self._debug:
            logger.debug("Serial RawRX({0}): {1}".format(len(data), data))
        _primare_talker._primare_reader(data)

    # def randomFunc(self, turn_on):
    #     """
    #     This method is exported as RPC and can be called by connected clients
    #     """
    #     if turn_on:
    #         payload = b'1'
    #     else:
    #         payload = b'0'
    #     if self._debug:
    #         logger.debug("Serial TX: {0}".format(payload))
    #         self.transport.write(payload)


def event_timer_func(talker, function):
    logger.debug("Running event_timer_func")
    methodToCall = getattr(talker, function)
    methodToCall()

if __name__ == '__main__':
    global _primare_talker
    # parse command line arguments
    parser = argparse.ArgumentParser()

    parser.add_argument("-d", "--debug", action="store_true",
                        help="Enable debug output.")

    parser.add_argument("--baudrate", type=int, default=4800,
                        choices=[
                            300, 1200, 2400, 4800, 9600, 19200, 57600, 115200],
                        help='Serial port baudrate.')

    parser.add_argument("--port", type=str, default='/dev/ttyUSB0',
                        help="Serial port to use (e.g. 3 for a COM port on \
                        Windows, /dev/ttyATH0 for Arduino Yun, /dev/ttyACM0 \
                        for Serial-over-USB on RaspberryPi.")

    args = parser.parse_args()

    try:
        # on Windows, we need port to be an integer
        args.port = int(args.port)
    except ValueError:
        pass


    logger.info("Using Twisted reactor {0}".format(reactor.__class__))

    params = {
        'port': args.port,
        'baudrate': args.baudrate,
        'debug': args.debug
    }

    serial_protocol = PrimareProtocol(params['debug'])
    _primare_talker = PrimareTalker(source=None, volume=None, writer=serial_protocol.sendLine)
    #_primare_talker.register_mcu_write_cb(serial_protocol.wrapSendLine)
    #_primare_talker.register_mcu_write_cb(serial_protocol.sendLine)

    logger.debug('About to open serial port {0} [{1} baud] ..'.format(params['port'],
                                                               params['baudrate']))
    # Prototype:
    # SerialPort(protocol, deviceNameOrPortNumber, reactor,
    #    baudrate=9600, bytesize=EIGHTBITS, parity=PARITY_NONE,
    #    stopbits=STOPBITS_ONE, xonxoff=0, rtscts=0)

    # Primare serial link config
    # BAUDRATE = 4800
    # BYTESIZE = 8
    # PARITY = 'N'
    # STOPBITS = 1
    SerialPort(serial_protocol, deviceNameOrPortNumber=params['port'], reactor=reactor, baudrate=int(params['baudrate']))
    thread_id = Thread(target=reactor.run, args=(False,))

    #event = task.LoopingCall(event_timer_func, _primare_talker, "input_next")
    #event.start(3)

    thread_id.start()

    _primare_talker.setup()
    _primare_talker._set_device_to_known_state()
    _primare_talker._print_device_info()
    #reactor.run()

    logger.info("After thread start")

    try:
        nb = ''
        while True:
            nb = raw_input('Cmd: ').strip()
            if not nb or nb == 'q':
                logger.info("Quit: '{}'".format(nb))
                break
            else:
                parsed_cmd = nb.split()
                logger.info("Input rcv: {} - len: {}".format(parsed_cmd, len(parsed_cmd)))
                command = getattr(_primare_talker, parsed_cmd[0], None)
                if command:
                    try:
                        if len(parsed_cmd) > 1:
                            if parsed_cmd[1].lower() == "true":
                                parsed_cmd[1] = True
                            elif parsed_cmd[1].lower() == "false":
                                parsed_cmd[1] = False
                            else:
                                parsed_cmd[1] = int(parsed_cmd[1])
                            command(parsed_cmd[1])
                        else:
                            command()
                    except TypeError as e:
                        logger.error("You called a method with an incorrect number of parameters: {}".format(e))
                else:
                    logger.info("No such function - try again")
    except KeyboardInterrupt:
        logger.info("User aborted")
    # in a non-main thread:
    reactor.callFromThread(reactor.stop)
