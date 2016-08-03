"""Interface to Primare amplifiers using Twisted SerialPort.

This module allows you to control your Primare I22 and I32 amplifier from the
command line using Primare's binary protocol via the RS232 port on the
amplifier.
"""

import logging
from threading import Thread

import click

from twisted.internet import reactor
from twisted.internet.serialport import SerialPort
from twisted.protocols.basic import LineReceiver

from primare_control import PrimareController

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

    def rawDataReceived(self, data):
        """Handle raw data received by Twisted's SerialPort."""
        if self._debug:
            logger.debug("Serial RawRX({0}): {1}".format(len(data), data))
        _primare_talker._primare_reader(data)


class DefaultCmdGroup(click.Group):
    """Custom implementation for handling Primare methods in a unified way."""

    def list_commands(self, ctx):
        """List Primare Control methods."""
        rv = [method for method in dir(PrimareController)
              if not method.startswith('_')]
        rv.append('interactive')
        rv.sort()
        return rv

    def get_command(self, ctx, name):
        """Return click command."""
        @click.pass_context
        def subcommand(ctx):
            try:
                method = getattr(PrimareController, name)
                method(_primare_talker)
            except KeyboardInterrupt:
                logger.info("User aborted")
            except TypeError as e:
                logger.error(e)
            finally:
                # in a non-main thread:
                reactor.callFromThread(reactor.stop)

        # attach doc from original callable so it will appear
        # in CLI output
        if name == "interactive":
            cmd = click.Group.get_command(self, ctx, 'interactive')
        else:
            subcommand.__doc__ = getattr(PrimareController, name).__doc__
            if getattr(PrimareController, name).__func__.__code__.co_argcount > 1:
                # click.echo("Arguments!")
                ctx.command.params.append(click.Argument(("value",)))
                # click.echo("ctx.args: {}".format(ctx.command.params))
                # click.echo("dir: {}".format((ctx.__dict__)))
            # else:
                # click.echo("None")
            cmd = click.command(name)(subcommand)
        return cmd


@click.command(cls=DefaultCmdGroup)
@click.pass_context
@click.option("--amp-info",
              default=False,
              is_flag=True,
              help="Retrieve and print amplifier information")
@click.option("--baudrate",
              default='4800',
              type=click.Choice(['300',
                                 '1200',
                                 '2400',
                                 '4800',
                                 '9600',
                                 '19200',
                                 '57600',
                                 '115200']),
              help="Serial port baudrate. For I22 it _must_ be 4800.")
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
def cli(ctx, amp_info, baudrate, debug, port):
    """Prototype."""
    global _primare_talker

    ctx.obj = {}

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


@cli.command()
def interactive():
    """Start interactive shell for controlling a Primare amplifier.

    Press enter (blank line), 'q' or 'quit' to exit.

    For a list of available commands, type 'help'
    """
    method_list = [
        (method,
            getattr(PrimareController, method).__doc__) for
        method in dir(PrimareController) if not method.startswith('_')]
    help_string = """To exit, press enter (blank line) or type 'q' or 'quit'.\n
Available commands are:
{}""".format('\n'.join("  {} {}".format(method.ljust(25), doc.splitlines()[0])
                       for method, doc in method_list))
    try:
        logger.info(help_string)
        nb = ''
        while True:
            nb = raw_input('Cmd: ').strip()
            if not nb or nb == 'q' or nb == 'quit':
                logger.info("Quit: '{}'".format(nb))
                break
            elif nb.startswith('help '):
                if len(nb.split()) == 2:
                    help_method = nb.split()[1]
                    matches = [item for item in method_list if item[0].startswith(help_method)]
                    if len(matches):
                        logger.info("\n".join("\n== {}\n{}".format(method.ljust(25), doc_string) for method, doc_string in matches))
                    else:
                        logger.error("Help requested on unknown method: {}".format(help_method))
                else:
                    logger.info(help_string)

            else:
                parsed_cmd = nb.split()
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


if __name__ == '__main__':
    cli()
