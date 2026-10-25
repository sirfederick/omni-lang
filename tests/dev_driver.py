#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Federico T. Begna
# SPDX-License-Identifier: MIT OR Apache-2.0
import contextlib
import hashlib
import io
import json
import pathlib
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / 'tools'))
import omni_dev


class DriverIntegrity(unittest.TestCase):
    def test_consumers_require_inputs_and_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            out = root / 'build/dev'
            out.mkdir(parents=True)
            binary = out / 'omni'
            binary.write_bytes(b'valid fixture binary')
            stamp = out / 'compiler.inputs.json'
            metadata = {'inputs': 'current', 'output': hashlib.sha256(binary.read_bytes()).hexdigest()}
            for command in (['check', 'x.omni'], ['run', 'x.omni'], ['test', '--group', 'core']):
                for fault in ('none', 'inputs', 'output'):
                    with self.subTest(command=command[0], fault=fault):
                        binary.write_bytes(b'changed' if fault == 'output' else b'valid fixture binary')
                        stamp.write_text(json.dumps(metadata))
                        digest = 'changed' if fault == 'inputs' else 'current'
                        with patch.object(omni_dev, 'ROOT', root), patch.object(omni_dev.sys, 'platform', 'linux'), patch.object(omni_dev, 'fingerprint', return_value=digest), patch.object(omni_dev, 'execute', return_value=0) as execute, contextlib.redirect_stderr(io.StringIO()):
                            if fault == 'none':
                                self.assertEqual(omni_dev.main(command), 0)
                                execute.assert_called_once()
                            else:
                                with self.assertRaises(SystemExit) as error:
                                    omni_dev.main(command)
                                self.assertEqual(error.exception.code, 2)
                                execute.assert_not_called()

    def test_current_build_is_reused(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            out = root / 'build/dev'
            out.mkdir(parents=True)
            (out / 'omni').write_bytes(b'valid')
            (out / 'compiler.inputs.json').write_text(json.dumps({'inputs': 'same', 'output': hashlib.sha256(b'valid').hexdigest()}))
            with patch.object(omni_dev, 'ROOT', root), patch.object(omni_dev.sys, 'platform', 'linux'), patch.object(omni_dev, 'fingerprint', return_value='same'), patch.object(omni_dev, 'execute') as execute, contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(omni_dev.main(['build']), 0)
                execute.assert_not_called()

    def test_invalid_stamp_is_stale(self):
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / 'stamp'
            path.write_text('not json')
            self.assertFalse(omni_dev.artifact_current(path, path, 'x'))


if __name__ == '__main__':
    unittest.main(verbosity=2)
