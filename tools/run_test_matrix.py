#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Federico T. Begna
# SPDX-License-Identifier: MIT OR Apache-2.0
"""Run declared unittest suites or explicit JSON probes; reject empty success."""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import re
import subprocess
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
SUMMARY = re.compile(r'^Ran (\d+) tests? in [0-9.]+s\s*\n\s*\n(OK|FAILED)(?: \(([^)\n]*)\))?', re.M)


def unittest_summary(output):
    matches = list(SUMMARY.finditer(output))
    if not matches:
        return {}
    match = matches[-1]
    counts = {key.strip(): int(value) for key, value in re.findall(r'([a-z ]+)=(\d+)', match.group(3) or '')}
    discovered = int(match.group(1))
    skipped = counts.get('skipped', 0)
    return {'tests_run': discovered, 'tests_executed': discovered - skipped,
            'outcome': match.group(2), 'skipped': skipped,
            'failures': counts.get('failures', 0), 'errors': counts.get('errors', 0)}


def verification(output, contract):
    if contract.get('kind', 'unittest') == 'unittest':
        summary = unittest_summary(output)
        if not summary:
            return {}, 'missing unittest summary'
        if summary['tests_executed'] <= 0 or summary['skipped'] > summary['tests_run']:
            return summary, 'no non-skipped test cases executed'
        if summary['outcome'] != 'OK' or summary['failures'] or summary['errors']:
            return summary, 'unittest summary reports failure/error'
        return summary, None
    if contract.get('kind') != 'probe' or not contract.get('schema'):
        return {}, 'unknown or incomplete executable contract'
    try:
        payload = json.loads(output.strip().splitlines()[-1])
        checks = payload.get('checks')
        if (payload.get('schema') != contract['schema'] or payload.get('status') != 'PASS'
                or not isinstance(checks, dict) or not checks or not all(value is True for value in checks.values())):
            raise ValueError('expected schema, PASS, and nonempty true checks')
        return {'probe_checks': len(checks)}, None
    except (ValueError, IndexError, AttributeError) as error:
        return {}, 'invalid JSON probe result: ' + str(error)


def run_matrix(root, matrix, groups, env, timeout, no_skips, max_skips, stream=None):
    stream = stream or sys.stdout
    results = []
    selection_errors = []
    if not groups:
        selection_errors.append('no groups selected')
    for group in groups:
        paths = matrix.get('groups', {}).get(group)
        if not paths:
            selection_errors.append('empty or unknown group: ' + group)
            continue
        for relative in paths:
            start = time.monotonic()
            timed_out = False
            launch_error = None
            try:
                process = subprocess.run([sys.executable, '-B', str(root / relative)], cwd=root,
                                         env=env, capture_output=True, text=True, timeout=timeout)
                code, stdout, stderr = process.returncode, process.stdout, process.stderr
            except subprocess.TimeoutExpired as error:
                code, stdout, stderr, timed_out = 124, error.stdout or '', error.stderr or '', True
                stdout = stdout.decode('utf-8', 'replace') if isinstance(stdout, bytes) else stdout
                stderr = stderr.decode('utf-8', 'replace') if isinstance(stderr, bytes) else stderr
            except OSError as error:
                code, stdout, stderr = 127, '', str(error)
                launch_error = str(error)
            output = stdout + '\n' + stderr
            contract = matrix.get('contracts', {}).get(relative, {'kind': 'unittest'})
            summary, error = verification(output, contract)
            skipped = summary.get('skipped', 0)
            skip_violation = None
            if skipped and (relative in no_skips or group in no_skips):
                skip_violation = f'{relative}: {skipped} skipped case(s) in a suite that must not skip'
            elif max_skips is not None and skipped > max_skips:
                skip_violation = f'{relative}: {skipped} skipped case(s) exceed --max-skips {max_skips}'
            ok = code == 0 and error is None and skip_violation is None
            row = {'group': group, 'path': relative, 'kind': contract.get('kind', 'unittest'),
                   'status': 'pass' if ok else 'fail', 'returncode': code,
                   'duration_seconds': round(time.monotonic() - start, 3), **summary}
            for key, value in [('verification_error', error), ('skip_violation', skip_violation),
                               ('launch_error', launch_error), ('timed_out', timed_out)]:
                if value:
                    row[key] = value
            results.append(row)
            print(f'[{row["status"].upper()}] {group}: {relative} ({row["duration_seconds"]:.3f}s) '
                  f'[{summary}]' + (f' {error or skip_violation}' if error or skip_violation else ''), file=stream)
            if not ok and output.strip():
                print(output[-8000:], file=stream)
    totals = {'executables': len(results), 'passed': sum(row['status'] == 'pass' for row in results),
              'failed': sum(row['status'] == 'fail' for row in results),
              # Preserve tests_run: unittest's discovered/run count includes skips.
              'tests_run': sum(row.get('tests_run', 0) for row in results),
              'tests_executed': sum(row.get('tests_executed', 0) for row in results),
              'skipped': sum(row.get('skipped', 0) for row in results),
              'probe_checks': sum(row.get('probe_checks', 0) for row in results),
              'without_unittest_summary': sum('tests_run' not in row for row in results)}
    return {'schema': 'omni.test-matrix-result/1', 'version': matrix['version'],
            'status': 'fail' if selection_errors or not results or totals['failed'] else 'pass',
            'selected_groups': groups, 'tests': results, 'totals': totals,
            'selection_errors': selection_errors,
            'skip_policy_violations': [row['skip_violation'] for row in results if 'skip_violation' in row]}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--group', action='append', default=[])
    parser.add_argument('--report', type=pathlib.Path)
    parser.add_argument('--root', type=pathlib.Path, default=ROOT)
    parser.add_argument('--matrix', type=pathlib.Path)
    parser.add_argument('--timeout', type=float, default=3600)
    parser.add_argument('--no-skips', action='append', default=[])
    parser.add_argument('--max-skips', type=int)
    args = parser.parse_args(argv)
    root = args.root.resolve()
    matrix = json.loads((args.matrix or root / 'tests/MATRIX.json').read_text(encoding='utf-8'))
    selected = args.group or list(matrix['groups'])
    unknown = [name for name in selected if name not in matrix['groups']]
    if unknown or args.timeout <= 0 or (args.max_skips is not None and args.max_skips < 0):
        parser.error('invalid group or timeout/skip policy: ' + ','.join(unknown))
    if not (root / '.git').exists():
        blocked = [name for name in selected if name in matrix.get('group_requirements', {})]
        if blocked:
            parser.error('postcommit audit requires Git: ' + ','.join(blocked))
    env = dict(os.environ, OMNI_HOME=str(root), PYTHONDONTWRITEBYTECODE='1',
               OMNI_TEST_BIN=os.environ.get('OMNI_TEST_BIN', str(root / 'bin/linux-x86_64/omni')))
    report = run_matrix(root, matrix, selected, env, args.timeout, set(args.no_skips), args.max_skips)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({key: report[key] for key in ('schema', 'version', 'status', 'totals')}, indent=2))
    return report['status'] != 'pass'


if __name__ == '__main__':
    sys.exit(main())
