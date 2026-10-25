#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Federico T. Begna
# SPDX-License-Identifier: MIT OR Apache-2.0
"""First-use oracles shared by documentation and local/remote CI."""
import os
import pathlib
import subprocess
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
OMNI = pathlib.Path(os.environ.get('OMNI_TEST_BIN', ROOT / 'build/dev/omni'))


class FirstUseTests(unittest.TestCase):
    def command(self, *args, expected=0):
        result = subprocess.run([str(value) for value in args], cwd=ROOT,
                                env=dict(os.environ, OMNI_HOME=str(ROOT)), capture_output=True, text=True, timeout=120)
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        return result

    def exercise(self, relative, output):
        self.command(OMNI, 'check', relative)
        self.assertEqual(self.command(OMNI, 'eval', relative).stdout, output)
        self.assertEqual(self.command(OMNI, 'run', relative).stdout, output)
        with tempfile.TemporaryDirectory() as directory:
            native = pathlib.Path(directory) / 'example'
            self.command(OMNI, 'build', relative, '-o', native)
            self.assertEqual(self.command(native).stdout, output)

    def test_identity_and_help(self):
        self.assertEqual(self.command(OMNI, '--version').stdout.strip(), 'omni ' + (ROOT / 'VERSION').read_text().strip())
        self.assertIn('--host-entry', self.command(OMNI, '--help').stdout)

    def test_hola(self):
        self.exercise('examples/hola.omni', 'Hola, Omni\n720\n')

    def test_result_and_continuation(self):
        self.exercise('examples/result_minimo.omni', '100\nEl programa continua\n')

    def test_explicit_effect(self):
        self.exercise('tests/fixtures/dx/io_allowed.omni', 'Capability accepted\n')

    def test_pure_io_rejection_is_semantic(self):
        result = self.command(OMNI, 'check', 'tests/fixtures/dx/pure_io_denied.omni', expected=2)
        self.assertIn('E_CAPABILITY', result.stderr)
        self.assertNotIn('E_PARSE', result.stderr)


if __name__ == '__main__':
    unittest.main(verbosity=2)
