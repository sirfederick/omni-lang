#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Federico T. Begna
# SPDX-License-Identifier: MIT OR Apache-2.0
"""Small real subprocess fixtures; no Omni compilation is needed."""
import contextlib
import io
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / 'tools'))
from run_test_matrix import run_matrix

SUITE = '''import unittest
class Case(unittest.TestCase):
    def test_real(self): self.assertEqual(2 + 2, 4)
unittest.main()
'''


class MatrixTests(unittest.TestCase):
    def execute(self, text, timeout=5, no_skips=None, max_skips=None, contract=None):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            (root / 'case.py').write_text(text, encoding='utf-8')
            matrix = {'version': '0.1.0.00', 'groups': {'fixture': ['case.py']}}
            if contract:
                matrix['contracts'] = {'case.py': contract}
            return run_matrix(root, matrix, ['fixture'], dict(os.environ), timeout,
                              no_skips or set(), max_skips, stream=io.StringIO())

    def test_real_suite(self):
        report = self.execute(SUITE)
        self.assertEqual(report['status'], 'pass')
        self.assertEqual(report['totals']['tests_executed'], 1)

    def test_zero_cases(self):
        self.assertEqual(self.execute('import unittest; unittest.main()')['status'], 'fail')

    def test_zero_exit_without_summary(self):
        self.assertEqual(self.execute('raise SystemExit(0)')['status'], 'fail')

    def test_actual_failure(self):
        self.assertEqual(self.execute(SUITE.replace('2 + 2, 4', '2 + 2, 5'))['status'], 'fail')

    def test_failure_summary_with_zero_exit(self):
        text = "print('Ran 1 test in 0.001s\\n\\nFAILED (errors=1)')"
        self.assertEqual(self.execute(text)['status'], 'fail')

    def test_all_cases_skipped(self):
        text = SUITE.replace('    def test_real', '    @unittest.skip("fixture")\n    def test_real')
        self.assertEqual(self.execute(text)['status'], 'fail')

    def test_skip_policy_and_counts(self):
        text = SUITE.replace('unittest.main()', '    @unittest.skip("fixture")\n    def test_skip(self): pass\nunittest.main()')
        report = self.execute(text)
        self.assertEqual(report['status'], 'pass')
        self.assertEqual((report['totals']['tests_run'], report['totals']['tests_executed'], report['totals']['skipped']), (2, 1, 1))
        self.assertEqual(self.execute(text, max_skips=0)['status'], 'fail')
        self.assertEqual(self.execute(text, no_skips={'fixture'})['status'], 'fail')

    def test_timeout(self):
        report = self.execute('import time; time.sleep(5)', timeout=0.05)
        self.assertEqual(report['status'], 'fail')
        self.assertTrue(report['tests'][0]['timed_out'])

    def test_launch_error(self):
        with patch('run_test_matrix.subprocess.run', side_effect=OSError('launch fixture')):
            report = self.execute(SUITE)
        self.assertEqual(report['tests'][0]['returncode'], 127)

    def test_empty_selection_and_group(self):
        for groups, entries in [([], {}), (['empty'], {'empty': []})]:
            report = run_matrix(pathlib.Path.cwd(), {'version': 'x', 'groups': entries}, groups, {}, 1, set(), None, stream=io.StringIO())
            self.assertEqual(report['status'], 'fail')

    def test_explicit_probe_contract(self):
        text = 'print(' + repr(json.dumps({'schema': 'example.probe/1', 'status': 'PASS', 'checks': {'roundtrip': True}})) + ')'
        report = self.execute(text, contract={'kind': 'probe', 'schema': 'example.probe/1'})
        self.assertEqual(report['status'], 'pass')
        self.assertEqual(report['totals']['tests_run'], 0)
        self.assertEqual(report['totals']['probe_checks'], 1)

    def test_probe_without_checks_fails(self):
        self.assertEqual(self.execute('print(\'{"schema":"x","status":"PASS","checks":{}}\')', contract={'kind': 'probe', 'schema': 'x'})['status'], 'fail')


if __name__ == '__main__':
    unittest.main(verbosity=2)
