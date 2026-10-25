#!/usr/bin/env python3
"""Old versus new in one cheap test: every program of the identified corpus, compiled by the BASELINE compiler (the previous accepted line) and by the candidate
under the same configuration, must give the same artifacts - Wave, Wire and LLVM IR - apart from each compiler's own version string.

What this establishes is bounded: in the corpus (the *.omni files of examples/, stdlib/, tests/ and profiles/) the valid programs the change does not affect keep
Wave, Wire and IR byte for byte, and any unexpected difference fails the gate. It is not a guarantee for every possible program, and it does not preserve a defect:
a program the baseline wrongly accepted and a deliberate semantic correction are documented and verified separately, by their own tests, not by this one.
Programs only the candidate accepts are counted, not compared. Without OMNI_BASELINE_BIN the test is skipped, and a gate that was given a baseline
(omni_gate.py --baseline-rev) refuses skips, so it cannot pass vacuously.
"""
from __future__ import annotations
import concurrent.futures
import os
import pathlib
import re
import subprocess
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
CANDIDATE = pathlib.Path(os.environ.get('OMNI_TEST_BIN', ROOT / 'bin/linux-x86_64/omni'))
BASELINE = os.environ.get('OMNI_BASELINE_BIN')
MINIMUM_COMPARED = 40          # fewer than this means the corpus or the baseline is not what it claims to be
ARTIFACTS = (('wave', None), ('pack', '.owire'), ('emit-llvm', '.ll'))


def corpus() -> list[pathlib.Path]:
    files = []
    for top in ('examples', 'stdlib', 'tests', 'profiles'):
        files += sorted((ROOT / top).rglob('*.omni'))
    return [f for f in files if '__pycache__' not in f.parts]


def version_of(binary: pathlib.Path) -> bytes:
    out = subprocess.run([str(binary), '--version'], capture_output=True, timeout=30).stdout.decode().split()
    return out[-1].encode() if out else b''


def render(binary: pathlib.Path, program: pathlib.Path, work: pathlib.Path, tag: str) -> dict:
    """{'check': rc, 'wave': bytes, 'pack': bytes, 'emit-llvm': bytes} for one compiler (artifacts only when the program checks)."""
    env = {**os.environ, 'OMNI_HOME': str(ROOT)}
    result = {'check': subprocess.run([str(binary), 'check', str(program)], capture_output=True, cwd=program.parent, env=env, timeout=120).returncode}
    if result['check'] != 0:
        return result
    for command, suffix in ARTIFACTS:
        args = [str(binary), command, str(program)]
        out = None
        if suffix:
            out = work / f'{tag}-{command}{suffix}'
            out.unlink(missing_ok=True)
            args += ['-o', str(out)]
        done = subprocess.run(args, capture_output=True, cwd=program.parent, env=env, timeout=120)
        result[command] = (out.read_bytes() if out is not None and out.exists() else done.stdout) if done.returncode == 0 else b'FAILED:' + done.stderr[:200]
    return result


@unittest.skipUnless(BASELINE, 'needs OMNI_BASELINE_BIN (compiler of the previous accepted line)')
class ArtifactIdentityTests(unittest.TestCase):
    def test_the_candidate_renders_what_the_baseline_accepts_byte_for_byte(self):
        baseline = pathlib.Path(BASELINE)
        old_version, new_version = version_of(baseline), version_of(CANDIDATE)
        programs = corpus()
        self.assertGreater(len(programs), MINIMUM_COMPARED, 'the corpus is too small to mean anything')
        with tempfile.TemporaryDirectory(prefix='omni-identity-') as tmp:
            work = pathlib.Path(tmp)

            def both(item):
                index, program = item
                sub = work / str(index)
                sub.mkdir()
                return program, render(baseline, program, sub, 'old'), render(CANDIDATE, program, sub, 'new')

            with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
                rows = list(pool.map(both, enumerate(programs)))
        compared = new_only = 0
        for program, old, new in rows:
            name = str(program.relative_to(ROOT))
            if old['check'] != 0:
                new_only += new['check'] == 0
                continue
            with self.subTest(program=name):
                self.assertEqual(new['check'], 0, f'{name}: the baseline accepts it and the candidate does not')
                for command, _ in ARTIFACTS:
                    left = re.sub(re.escape(old_version), b'VERSION', old[command]) if old_version else old[command]
                    right = re.sub(re.escape(new_version), b'VERSION', new[command]) if new_version else new[command]
                    self.assertEqual(left, right, f'{name}: {command} differs')
                compared += 1
        self.assertGreaterEqual(compared, MINIMUM_COMPARED, f'only {compared} programs were compared ({new_only} are accepted only by the candidate)')


if __name__ == '__main__':
    unittest.main()
