"""Interface to Primare amplifiers using Twisted SerialPort.

This module allows you to control your Primare I22 and I32 amplifier from the
command line using Primare's binary protocol via the RS232 port on the
amplifier.
"""

import click
import logging

from contextlib import closing

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

# Setup logging so that is available
FORMAT = '%(asctime)-15s %(levelname)-8s %(message)s'
logging.basicConfig(level=logging.DEBUG, format=FORMAT)

logger = logging.getLogger(__name__)


class DefaultCmdGroup(click.Group):
    """Custom implementation for handling Primare methods in a unified way."""

    def list_commands(self, ctx):
        """List Primare Control methods."""
        rv = [method for method in dir(PrimareController)
              if not method.startswith('_')]
        rv.append('interactive')
        rv.sort()
        logger.debug("list_commands done")
        return rv

    def get_command(self, ctx, name):
        """Return click command."""
        logger.debug("get_command start")

        @click.pass_context
        def subcommand(ctx):
            with closing(ctx.obj):
                try:
                    method = getattr(PrimareController, name)
                    method(ctx.obj)
                except KeyboardInterrupt:
                    logger.info("User aborted")
                except TypeError as e:
                    logger.error(e)
            logger.debug("get_command.subcommand() done")

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
        logger.debug("get_command done")
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

    logger.debug("cli() start")
    try:
        # on Windows, we need port to be an integer
        port = int(port)
    except ValueError:
        pass

    ctx.obj = PrimareController(port=port,
                                baudrate=baudrate,
                                source=None,
                                volume=None,
                                debug=debug)

    if amp_info:
        ctx.obj.setup()

    logger.debug("After thread start, end of cli()")


@cli.command()
@click.pass_context
def interactive(ctx):
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
                logger.debug("Quit: '{}'".format(nb))
                break
            elif nb.startswith('help '):
                if len(nb.split()) == 2:
                    help_method = nb.split()[1]
                    matches = [item for item in method_list
                               if item[0].startswith(help_method)]
                    if len(matches):
                        logger.info("\n".join("\n== {}\n{}".format(
                            method.ljust(25), doc_string) for
                            method, doc_string in matches))
                    else:
                        logger.info("Help requested on unknown method: {}".format(
                            help_method))
                else:
                    logger.info(help_string)

            else:
                parsed_cmd = nb.split()
                command = getattr(ctx.obj, parsed_cmd[0], None)
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
                        logger.warn("You called a method with an incorrect"
                                     "number of parameters: {}".format(e))
                else:
                    logger.info("No such function - try again")
    except KeyboardInterrupt:
        logger.info("User aborted")
    # in a non-main thread:
    ctx.obj.close()
    del ctx.obj
    ctx.obj = None

if __name__ == '__main__':
    logger.debug("Starting primare_interface.py")
    cli()
