#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Federico T. Begna
# SPDX-License-Identifier: MIT OR Apache-2.0
"""Regression for nominal fields being mistaken for generic type arguments."""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class NominalProjectionTests(unittest.TestCase):
    def test_real_sdk_projection_preserves_identity_and_rejects_malformed_schemas(self):
        runtime = Path(os.environ.get('OMNI_TEST_RUNTIME', ROOT / 'build/dev/runtime/libomni_invocation_v1.so')).resolve()
        self.assertTrue(runtime.is_file(), 'build the actual loader before sdk13')
        with tempfile.TemporaryDirectory(prefix='omni-nominal-projection-') as temporary:
            executable = Path(temporary) / 'probe'
            compiled = subprocess.run([
                os.environ.get('CXX', 'c++'), '-std=c++20', '-Wall', '-Wextra', '-Werror',
                '-I', str(ROOT / 'compiler/src'),
                str(ROOT / 'tests/host_invocation_h02/nominal_projection.cpp'),
                str(runtime), '-Wl,-rpath,' + str(runtime.parent), '-o', str(executable),
            ], capture_output=True, text=True, timeout=90)
            self.assertEqual(compiled.returncode, 0, compiled.stdout + compiled.stderr)
            observed = subprocess.run([str(executable)], capture_output=True, text=True, timeout=15)
            self.assertEqual(observed.returncode, 0, observed.stdout + observed.stderr)
            self.assertEqual(observed.stdout, 'NOMINAL_PROJECTION positive=9 negative=9\n')


if __name__ == '__main__':
    unittest.main()
