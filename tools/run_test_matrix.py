#!/usr/bin/env python3
"""Run the official test matrix (tests/MATRIX.json).

A zero exit code is not evidence that a suite ran its cases: a unittest suite whose cases are guarded by `skipUnless`
(QEMU, clang, a baseline compiler) exits 0 with every guarded case skipped. This runner therefore records, for every
executable, how many tests it ran and how many it skipped, and can refuse skips (`--no-skips`, `--max-skips`).
The report stays `omni.test-matrix-result/1`; the new fields are additive.
"""
from __future__ import annotations
import argparse, json, os, pathlib, re, subprocess, sys, time

ROOT = pathlib.Path(__file__).resolve().parents[1]
# unittest prints its summary on stderr: "Ran N test(s) in T s", a blank line, then "OK[ (skipped=K, ...)]" or "FAILED (failures=F, ...)".
_SUMMARY = re.compile(r'^Ran (\d+) tests? in [0-9.]+s\s*\n\s*\n(OK|FAILED)(?: \(([^)\n]*)\))?', re.M)


def unittest_summary(output: str) -> dict:
    """The LAST unittest summary in `output` (suites may embed nested runs in assertion messages); {} when none is printed."""
    found = None
    for found in _SUMMARY.finditer(output):
        pass
    if found is None:
        return {}
    details = found.group(3) or ''
    counts = {key.strip(): int(value) for key, value in re.findall(r'([a-z ]+)=(\d+)', details)}
    return {'tests_run': int(found.group(1)), 'outcome': found.group(2), 'skipped': counts.get('skipped', 0),
            'failures': counts.get('failures', 0), 'errors': counts.get('errors', 0)}


def run_matrix(root: pathlib.Path, matrix: dict, groups: list[str], env: dict, timeout: int, no_skips: set[str], max_skips: int | None,
               stream=sys.stdout) -> dict:
    results = []
    failed = False
    reasons = []
    for group in groups:
        for rel in matrix['groups'][group]:
            path = root / rel
            start = time.monotonic()
            try:
                process = subprocess.run([sys.executable, '-B', str(path)], cwd=root, env=env, capture_output=True, text=True, timeout=timeout)
                returncode, stdout, stderr, timed_out = process.returncode, process.stdout, process.stderr, False
            except subprocess.TimeoutExpired as error:
                returncode, stdout, stderr, timed_out = 124, error.stdout or '', error.stderr or '', True
                stdout = stdout.decode('utf-8', 'replace') if isinstance(stdout, bytes) else stdout
                stderr = stderr.decode('utf-8', 'replace') if isinstance(stderr, bytes) else stderr
            duration = round(time.monotonic() - start, 3)
            summary = unittest_summary(stdout + '\n' + stderr)
            skipped = summary.get('skipped', 0)
            ok = returncode == 0
            skip_violation = None
            if ok and skipped and (rel in no_skips or group in no_skips):
                skip_violation = f'{rel}: {skipped} skipped case(s) in a suite that must not skip'
            elif ok and max_skips is not None and skipped > max_skips:
                skip_violation = f'{rel}: {skipped} skipped case(s) exceed --max-skips {max_skips}'
            if skip_violation:
                reasons.append(skip_violation)
            status = 'pass' if ok and not skip_violation else 'fail'
            failed |= status == 'fail'
            note = ' TIMEOUT' if timed_out else ''
            note += f' [{summary["tests_run"]} tests, {skipped} skipped]' if summary else ' [no unittest summary]'
            print(f'[{status.upper()}] {group}: {rel} ({duration:.3f}s){note}', file=stream)
            if status == 'fail' and not ok:
                if stdout:
                    print(stdout[-8000:], file=stream)
                if stderr:
                    print(stderr[-8000:], file=sys.stderr)
            row = {'group': group, 'path': rel, 'status': status, 'returncode': returncode, 'duration_seconds': duration}
            if summary:
                row.update(tests_run=summary['tests_run'], skipped=skipped)
            if timed_out:
                row['timed_out'] = True
            if skip_violation:
                row['skip_violation'] = skip_violation
            results.append(row)
    totals = {'executables': len(results), 'passed': sum(r['status'] == 'pass' for r in results),
              'failed': sum(r['status'] == 'fail' for r in results),
              'tests_run': sum(r.get('tests_run', 0) for r in results), 'skipped': sum(r.get('skipped', 0) for r in results),
              'without_unittest_summary': sum('tests_run' not in r for r in results)}
    report = {'schema': 'omni.test-matrix-result/1', 'version': matrix['version'], 'status': 'fail' if failed else 'pass',
              'selected_groups': groups, 'tests': results, 'totals': totals}
    if reasons:
        report['skip_policy_violations'] = reasons
    return report


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--group', action='append', default=[])
    ap.add_argument('--report', type=pathlib.Path)
    ap.add_argument('--root', type=pathlib.Path, default=ROOT, help='tree under test (default: this tree)')
    ap.add_argument('--matrix', type=pathlib.Path, help='matrix file (default: <root>/tests/MATRIX.json)')
    ap.add_argument('--timeout', type=int, default=3600, help='seconds allowed per executable')
    ap.add_argument('--no-skips', action='append', default=[], metavar='PATH_OR_GROUP', help='fail if this executable/group skips any case')
    ap.add_argument('--max-skips', type=int, default=None, help='fail if any executable skips more than N cases')
    args = ap.parse_args(argv)
    root = args.root.resolve()
    matrix = json.loads((args.matrix or root / 'tests/MATRIX.json').read_text())
    selected = args.group or list(matrix['groups'])
    unknown = [g for g in selected if g not in matrix['groups']]
    if unknown:
        ap.error('unknown group(s): ' + ','.join(unknown))
    if not (root/'.git').exists():
        blocked=[g for g in selected if g in matrix.get('group_requirements',{})]
        if blocked:
            ap.error('postcommit audit requires Git; not a precommit semantic check: '+','.join(blocked))
    env = {**os.environ, 'OMNI_HOME': str(root), 'OMNI_TEST_BIN': os.environ.get('OMNI_TEST_BIN', str(root / 'bin/linux-x86_64/omni')),
           'PYTHONDONTWRITEBYTECODE': '1'}
    report = run_matrix(root, matrix, selected, env, args.timeout, set(args.no_skips), args.max_skips)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({'schema': report['schema'], 'version': report['version'], 'status': report['status'],
                      'executables': report['totals']['executables'], 'tests_run': report['totals']['tests_run'],
                      'skipped': report['totals']['skipped']}, indent=2))
    return 1 if report['status'] == 'fail' else 0


if __name__ == '__main__':
    raise SystemExit(main())
