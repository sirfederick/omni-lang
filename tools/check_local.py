#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Federico T. Begna
# SPDX-License-Identifier: MIT OR Apache-2.0
"""Shared local/CI acceptance command for the supported Linux profile."""
import argparse
import os
import pathlib
import subprocess
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]


def run_steps(steps, root, env, runner=None):
    runner = runner or subprocess.run
    for command in steps:
        print('+ ' + ' '.join(map(str, command)), flush=True)
        try:
            code = runner([str(value) for value in command], cwd=root, env=env).returncode
        except OSError as error:
            print(str(error), file=sys.stderr)
            return 127
        if code:
            return code
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--scope', choices=('tools', 'compiler', 'all'), default='all')
    args = parser.parse_args(argv)
    if sys.platform == 'win32':
        distro = os.environ.get('OMNI_WSL_DISTRO', 'Ubuntu-24.04')
        path = subprocess.run(['wsl', '-d', distro, '--exec', 'wslpath', '-a', str(ROOT)], capture_output=True, text=True, check=True).stdout.strip()
        return subprocess.run(['wsl', '-d', distro, '--cd', path, '--exec', 'python3', '-B',
                               'tools/check_local.py', '--scope', args.scope]).returncode
    python = [sys.executable, '-B']
    dev = [*python, 'tools/omni_dev.py']
    if str(ROOT).startswith('/mnt/'):
        dev.append('--allow-slow-fs')
    env = dict(os.environ, OMNI_HOME=str(ROOT), OMNI_TEST_BIN=str(ROOT / 'build/dev/omni'), PYTHONDONTWRITEBYTECODE='1')
    steps = [[*python, 'tools/check_spec_sync.py'],
             [*python, 'tools/verify_tree.py', '--report', 'build/reports/tree.json'],
             [*python, 'tools/run_test_matrix.py', '--group', 'structural', '--group', 'tooling',
              '--max-skips', '0', '--report', 'build/reports/tools.json']]
    if args.scope != 'tools':
        steps += [[*dev, 'env'], [*dev, 'build', '--target', 'compiler', '--jobs', '2'],
                  [*dev, 'test', '--group', 'cli', '--report', 'build/reports/cli.json']]
    if args.scope == 'all':
        steps += [[*dev, 'build', '--target', 'loader', '--jobs', '2'],
                  [*dev, 'build', '--target', 'node'], [*python, 'tools/run_sdk_smoke.py']]
        env.setdefault('OMNI_SDK_SMOKE_DIR', str(ROOT / 'build' / f'sdk-smoke-{time.time_ns()}'))
    return run_steps(steps, ROOT, env)


if __name__ == '__main__':
    sys.exit(main())
