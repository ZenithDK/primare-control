"""Interface to Primare amplifiers using Twisted SerialPort.

This module allows you to control your Primare I22 and I32 amplifier from the
command line using Primare's binary protocol via the RS232 port on the
amplifier.
"""

import click
import logging

from threading import Thread

from twisted.internet.serialport import SerialPort
from twisted.protocols.basic import LineReceiver
from twisted.internet import reactor

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

from primare_serial import PrimareController

logger = logging.getLogger(__name__)
# Setup logging so that is available
logging.basicConfig(level=logging.DEBUG)

primare_talker = None


class PrimareProtocol(LineReceiver):
    """Primare serial communication protocol."""

    def __init__(self, debug=False):
        """Initialization."""
        self._debug = debug
        self._primare_talker = primare_talker

        self.setRawMode()
        self._rawBuffer = bytearray()

    # def connectionMade(self):
    #     logger.info('Serial port connected.')

    def rawDataReceived(self, data):
        """Handle raw data received by Twisted's SerialPort."""
        if self._debug:
            logger.debug("Serial RawRX({0}): {1}".format(len(data), data))
        _primare_talker._primare_reader(data)


@click.group()
@click.option("--amp-info",
              default=False,
              is_flag=True,
              help="Retrieve and print amplifier information")
@click.option("--baudrate",
              default=4800,
              type=click.Choice([300,
                                 1200,
                                 2400,
                                 4800,
                                 9600,
                                 19200,
                                 57600,
                                 115200]),
              help="Serial port baudrate.")
@click.option("--debug",
              "-d",
              default=False,
              is_flag=True,
              help="Enable debug output.")
@click.option("--port",
              "-p",
              default="/dev/ttyUSB0",
              help="Serial port to use (e.g. 3 for a COM port on Windows, "
              "/dev/ttyATH0 for Arduino Yun, /dev/ttyACM0 for Serial-over-USB "
              "on RaspberryPi.")
def cli(amp_info, baudrate, debug, port):
    """Prototype."""
    global _primare_talker

    try:
        # on Windows, we need port to be an integer
        port = int(port)
    except ValueError:
        pass

    serial_protocol = PrimareProtocol(debug)
    _primare_talker = PrimareController(source=None,
                                        volume=None,
                                        writer=serial_protocol.sendLine)

    logger.debug('About to open serial port {0} [{1} baud] ..'.format(
        port,
        baudrate))
    SerialPort(serial_protocol,
               deviceNameOrPortNumber=port,
               reactor=reactor, baudrate=int(baudrate))
    thread_id = Thread(target=reactor.run, args=(False,))

    thread_id.start()

    if amp_info:
        _primare_talker.setup()

    logger.info("After thread start, end of cli()")


class PrimareCommands(click.Group):
    """Fuck off."""

    def list_commands(self, ctx, cmd_name):
        """Fuck off."""
        click.echo(ctx.args)
        cmd = click.Group.get_command(self, ctx, cmd_name)
        if cmd is not None:
            return cmd
        else:
            return click.Group.get_command(self, ctx, 'interactive')
        # rv = []
        # for method in dir(_primare_talker):
        #     if not method.beginswith('_'):
        #         rv.append(method)
        # rv.sort()
        # logger.info("Dynamic methods: {}".format(rv))
        # return rv

    # def get_command(self, ctx, name):
    #     """Fuck off."""
    #     return getattr(_primare_talker, name)


@click.command(cls=PrimareCommands)
@click.pass_context
def main(ctx):
    """Blah."""
    pass

# @cli.command()
# def volume_up():
#     """Increase the volume on the amplifier."""
#     _primare_talker.volume_up()
#     # in a non-main thread:
#     reactor.callFromThread(reactor.stop)


@cli.command()
def interactive():
    """Waah."""
    try:
        nb = ''
        while True:
            nb = raw_input('Cmd: ').strip()
            if not nb or nb == 'q':
                logger.info("Quit: '{}'".format(nb))
                break
            else:
                parsed_cmd = nb.split()
                logger.info("Input rcv: {} - len: {}".format(parsed_cmd,
                                                             len(parsed_cmd)))
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
                        logger.error("You called a method with an incorrect"
                                     "number of parameters: {}".format(e))
                else:
                    logger.info("No such function - try again")
    except KeyboardInterrupt:
        logger.info("User aborted")
    # in a non-main thread:
    reactor.callFromThread(reactor.stop)


# cli_dynamic = PrimareCommands(help='Blah blah')

# cmds = click.CommandCollection(sources=[cli, cli_dynamic])


if __name__ == '__main__':
    main()
