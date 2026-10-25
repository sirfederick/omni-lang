#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Federico T. Begna
# SPDX-License-Identifier: MIT OR Apache-2.0
import pathlib
import subprocess
import sys
import tempfile
import shutil
import unittest
from unittest.mock import Mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / 'tools'))
from check_local import run_steps


class EntryTests(unittest.TestCase):
    def test_first_failure_is_propagated(self):
        runner = Mock(side_effect=[subprocess.CompletedProcess([], 9), subprocess.CompletedProcess([], 0)])
        self.assertEqual(run_steps([['first'], ['second']], pathlib.Path.cwd(), {}, runner), 9)
        self.assertEqual(runner.call_count, 1)

    def test_success_runs_every_step(self):
        runner = Mock(return_value=subprocess.CompletedProcess([], 0))
        self.assertEqual(run_steps([['first'], ['second']], pathlib.Path.cwd(), {}, runner), 0)
        self.assertEqual(runner.call_count, 2)

    def test_actual_shell_entry_preserves_failure(self):
        # Only the wrapper and a failing canonical-entry fixture are copied.
        # This tests real Bash/exit propagation without a compiler or checkout.
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            tools = root / 'tools'
            tools.mkdir()
            shutil.copyfile(pathlib.Path(__file__).resolve().parents[1] / 'tools/ci.sh', tools / 'ci.sh')
            (tools / 'check_local.py').write_text('raise SystemExit(23)\n', encoding='utf-8')
            result = subprocess.run(['bash', str(tools / 'ci.sh')], capture_output=True, text=True)
            self.assertEqual(result.returncode, 23, result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main(verbosity=2)
