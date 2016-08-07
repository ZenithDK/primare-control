from __future__ import absolute_import, unicode_literals

import os
import subprocess
import sys
import unittest

import primare_control.primare_control


class CliHelpTest(unittest.TestCase):

    def test_help_has_primare_cli_options(self):
        primare_cli_dir = os.path.join(
            os.path.dirname(primare_control.__file__),
            "primare_interface.py")
        args = [sys.executable, primare_cli_dir, '--help']
        print("LASSE: {}".format(args))
        process = subprocess.Popen(
            args,
            env={'PYTHONPATH': ':'.join([
                os.path.join(primare_cli_dir, '..'),
                os.environ.get('PYTHONPATH', '')
            ])},
            stdout=subprocess.PIPE)
        output = process.communicate()[0]
        self.assertIn('--amp-info', output)
        self.assertIn('--baudrate', output)
        self.assertIn('--debug', output)
        self.assertIn('--port', output)
