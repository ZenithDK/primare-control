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


import time

from twisted.internet.defer import inlineCallbacks
from twisted.internet.serialport import SerialPort
from twisted.protocols.basic import LineReceiver

from autobahn.twisted.wamp import ApplicationSession

from primare_serial import PrimareTalker


class McuProtocol(LineReceiver):

    """
    MCU serial communication protocol.
    """

    # need a reference to our WS-MCU gateway factory to dispatch PubSub events
    #
    def __init__(self, session, primare_talker, debug=False):
        self._debug = debug
        self._session = session
        self._primare_talker = primare_talker

        self.setRawMode()
        self._rawBuffer = bytearray()

    def wrapSendLine(self, line):
        print('LASSE wrapLine: %s', line)
        self.sendLine(line)

    def connectionMade(self):
        print('Serial port connected.')

    def lineReceived(self, line):
        print('LASSE - BOOOOM!!! ERROR')
        # if self._debug:
        #     print("Serial LineRX({0}): {1}".format(len(line), line))

        # try:
        #     # parse data received from MCU
        #     #
        #     data = [int(x) for x in line.split()]

        #     # create payload for WAMP event
        #     #
        #     payload = {u'variable_char': data[0], u'value': data[1]}

        #     # publish WAMP event to all subscribers on topic
        #     #
        #     self._session.publish(u"com.mopidy.primare.lineData", payload)
        # except ValueError:
        #     print('Unable to parse value {0}'.format(line))

    def rawDataReceived(self, data):
        if self._debug:
            print("Serial RawRX({0}): {1}".format(len(data), data))
        self._primare_talker._primare_reader(data)

    def randomFunc(self, turn_on):
        """
        This method is exported as RPC and can be called by connected clients
        """
        if turn_on:
            payload = b'1'
        else:
            payload = b'0'
        if self._debug:
            print("Serial TX: {0}".format(payload))
            self.transport.write(payload)


class McuComponent(ApplicationSession):

    """
    MCU WAMP application component.
    """

    def __init__(self, config=None):
        ApplicationSession.__init__(self, config)
        self._primare_talker = PrimareTalker(source=None, volume=None)

    @inlineCallbacks
    def onJoin(self, details):
        print("MyComponent ready! Configuration: {}".format(self.config.extra))

        port = self.config.extra['port']
        baudrate = self.config.extra['baudrate']
        debug = self.config.extra['debug']

        serial_protocol = McuProtocol(self, self._primare_talker, debug)
        self._primare_talker.register_mcu_write_cb(
            serial_protocol.wrapSendLine)

        print('About to open serial port {0} [{1} baud] ..'.format(port,
                                                                   baudrate))
        try:
            # Prototype:
            # SerialPort(protocol, deviceNameOrPortNumber, reactor,
            #    baudrate=9600, bytesize=EIGHTBITS, parity=PARITY_NONE,
            #    stopbits=STOPBITS_ONE, xonxoff=0, rtscts=0)

            # Primare serial link config
            # BAUDRATE = 4800
            # BYTESIZE = 8
            # PARITY = 'N'
            # STOPBITS = 1

            # TODO: Try changing the name once everything works
            serialPort = SerialPort(
                serial_protocol, port, reactor, baudrate=baudrate)

            # self._primare_talker.setup()
            # yield self._primare_talker._set_device_to_known_state()
            yield self._primare_talker._print_device_info1()
            print("Sleep a while")
            time.sleep(0.6)
            yield self._primare_talker._print_device_info2()
            print("Sleep a while")
            time.sleep(0.6)
            yield self._primare_talker._print_device_info3()
            print("Sleep a while")
            time.sleep(0.6)
            yield self._primare_talker._print_device_info4()

        except Exception as e:
            print('Could not open serial port: {0}'.format(e))
            self.leave()
        else:
            yield self.register(serial_protocol.randomFunc,
                                u"com.mopidy.primare.randomFunc")


if __name__ == '__main__':
    import argparse
    import sys

    # parse command line arguments
    #
    parser = argparse.ArgumentParser()

    parser.add_argument("-d", "--debug", action="store_true",
                        help="Enable debug output.")

    parser.add_argument("--baudrate", type=int, default=4800,
                        choices=[
                            300, 1200, 2400, 4800, 9600, 19200, 57600, 115200],
                        help='Serial port baudrate.')

    parser.add_argument("--port", type=str, default='/dev/ttyUSB0',
                        help='Serial port to use (e.g. 3 for a COM port on \
                        Windows, /dev/ttyATH0 for Arduino Yun, /dev/ttyACM0 \
                        for Serial-over-USB on RaspberryPi.')

    parser.add_argument("--web", type=int, default=8000,
                        help='Web port to use for embedded Web server. \
                        Use 0 to disable.')

    parser.add_argument("--router", type=str, default=None,
                        help='If given, connect to this WAMP router. \
                        Else run an embedded router on 8998.')

    args = parser.parse_args()

    try:
        # on Windows, we need port to be an integer
        args.port = int(args.port)
    except ValueError:
        pass

    from twisted.python import log
    log.startLogging(sys.stdout)

    # import Twisted reactor
    #
    if sys.platform == 'win32':
        # on windows, we need to use the following reactor for serial support
        # http://twistedmatrix.com/trac/ticket/3802
        #
        from twisted.internet import win32eventreactor
        win32eventreactor.install()

    from twisted.internet import reactor
    print("Using Twisted reactor {0}".format(reactor.__class__))

    # create embedded web server for static files
    #
    if args.web:
        from twisted.web.server import Site
        from twisted.web.static import File
        reactor.listenTCP(args.web, Site(File(".")))

    # run WAMP application component
    #
    from autobahn.twisted.wamp import ApplicationRunner
    router = args.router or 'ws://localhost:8998/ws'

    params = {
        'port': args.port, 'baudrate': args.baudrate, 'debug': args.debug}
    runner = ApplicationRunner(router, u"realm1", extra=params,
                               # standalone=not args.router,
                               debug=args.debug, debug_wamp=args.debug,
                               debug_app=args.debug)

    # start the component and the Twisted reactor ..
    #
    runner.run(McuComponent)
