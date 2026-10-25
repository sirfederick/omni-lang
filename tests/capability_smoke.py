#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Federico T. Begna
# SPDX-License-Identifier: MIT OR Apache-2.0
"""Concrete oracles for the portable examples advertised in the catalog."""
import os
import pathlib
import subprocess
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
OMNI = pathlib.Path(os.environ.get('OMNI_TEST_BIN', ROOT / 'build/dev/omni'))


class CapabilityExamples(unittest.TestCase):
    def exercise(self, name, output, code=0):
        source = ROOT / 'examples' / (name + '.omni')
        env = dict(os.environ, OMNI_HOME=str(ROOT))
        def run(*args):
            return subprocess.run([str(arg) for arg in args], env=env, capture_output=True, text=True, timeout=90)
        checked = run(OMNI, 'check', source)
        self.assertEqual(checked.returncode, 0, checked.stderr)
        evaluated = run(OMNI, 'eval', source)
        self.assertEqual((evaluated.returncode, evaluated.stdout), (code, output), evaluated.stderr)
        with tempfile.TemporaryDirectory() as directory:
            native = pathlib.Path(directory) / 'program'
            built = run(OMNI, 'build', source, '-o', native)
            self.assertEqual(built.returncode, 0, built.stderr)
            executed = run(native)
            self.assertEqual((executed.returncode, executed.stdout), (code, output), executed.stderr)

    def test_numeric(self): self.exercise('numeric', '255\n4\n255\n-10\n255\n')
    def test_products(self): self.exercise('product_types', '42\n4\n10\n40\n')
    def test_option(self): self.exercise('option', '42\n99\n')
    def test_enums(self): self.exercise('adt_enum', '42\n4\n')
    def test_generics(self): self.exercise('generics_iteration', '', 42)
    def test_mutable_borrow(self): self.exercise('borrow_mut', '', 8)
    def test_views(self): self.exercise('borrowed_views', '2\n20\n', 50)
    def test_floats(self): self.exercise('floats', '3.75\n2.25\n3\n7\n', 7)
    def test_unicode(self): self.exercise('unicode_text', '7\n3\né\n233\n🙂\n', 3)
    def test_ranges(self): self.exercise('ranges', '22\n', 22)


if __name__ == '__main__':
    unittest.main(verbosity=2)
