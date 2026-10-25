#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Federico T. Begna
# SPDX-License-Identifier: MIT OR Apache-2.0
"""Real compiler/probe integration; kept out of compiler-free tooling tests."""
import copy
import io
import json
import os
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from run_test_matrix import run_matrix


class CompilerMatrixIntegration(unittest.TestCase):
    def test_registered_real_smoke_needs_and_satisfies_probe_contract(self):
        matrix = json.loads((ROOT / 'tests/MATRIX.json').read_text())
        path = 'tests/language_sanitizer_smoke.py'
        self.assertIn(path, matrix['groups']['smoke'])
        self.assertEqual(matrix['contracts'][path],
                         {'kind': 'probe', 'schema': 'omni.language-compiler-smoke/1'})
        env = dict(os.environ, OMNI_HOME=str(ROOT))
        old_registration = copy.deepcopy(matrix)
        del old_registration['contracts'][path]
        before = run_matrix(ROOT, old_registration, ['smoke'], env, 120, set(), 0,
                            stream=io.StringIO())
        self.assertEqual(before['tests'][0]['returncode'], 0)
        self.assertEqual(before['status'], 'fail')
        self.assertEqual(before['tests'][0]['verification_error'], 'missing unittest summary')

        after = run_matrix(ROOT, matrix, ['smoke'], env, 120, set(), 0, stream=io.StringIO())
        self.assertEqual(after['status'], 'pass', after)
        self.assertEqual(after['totals']['tests_executed'], 0)
        self.assertEqual(after['totals']['probe_checks'], 5)
        self.assertEqual(after['totals']['skipped'], 0)


if __name__ == '__main__':
    unittest.main(verbosity=2)
