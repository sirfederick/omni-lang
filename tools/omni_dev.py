#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Federico T. Begna
# SPDX-License-Identifier: MIT OR Apache-2.0
"""Build and exercise Omni from a checkout or source export."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import pathlib
import shutil
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]


def execute(args, env=None):
    return subprocess.run([str(value) for value in args], cwd=ROOT, env=env, check=False).returncode


def fingerprint(target):
    paths = [ROOT / 'tools/core_sources.txt', ROOT / 'tools/build_compiler.py']
    for directory in ('compiler/src', 'runtime', 'include'):
        paths += [path for path in (ROOT / directory).rglob('*') if path.is_file()]
    if target == 'loader':
        paths.append(ROOT / 'tools/build_invocation_loader.py')
    if target == 'node':
        paths += [ROOT / 'bindings/node/omni_host_sdk_node.cpp', ROOT / 'tools/build_host_sdk_node.py']
    digest = hashlib.sha256()
    for path in sorted(set(paths)):
        digest.update(path.relative_to(ROOT).as_posix().encode() + b'\0' + path.read_bytes())
    for name in ('CXX', 'CC', 'OMNI_CRYPTO_LIBS'):
        digest.update(name.encode() + b'=' + os.environ.get(name, '').encode())
    digest.update(target.encode())
    return digest.hexdigest()


def artifact_current(output, stamp, inputs):
    """Build and consumers use the same input AND actual-output validation."""
    try:
        previous = json.loads(stamp.read_text(encoding='utf-8'))
        return previous.get('inputs') == inputs and previous.get('output') == hashlib.sha256(output.read_bytes()).hexdigest()
    except (OSError, ValueError, AttributeError):
        return False


def arguments(argv):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--allow-slow-fs', action='store_true', help='allow an existing Windows-mounted workspace')
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('env')
    build = sub.add_parser('build')
    build.add_argument('--target', choices=('compiler', 'loader', 'node', 'all'), default='compiler')
    build.add_argument('--jobs', type=int, default=2)
    build.add_argument('--force', action='store_true')
    for name in ('check', 'run'):
        command = sub.add_parser(name)
        command.add_argument('source')
        command.add_argument('args', nargs=argparse.REMAINDER)
    test = sub.add_parser('test')
    test.add_argument('--group', action='append', default=[])
    test.add_argument('--report', default='build/dev/matrix.json')
    return parser, parser.parse_args(argv)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    parser, args = arguments(argv)
    if sys.platform == 'win32':
        distro = os.environ.get('OMNI_WSL_DISTRO', 'Ubuntu-24.04')
        path = subprocess.run(['wsl', '-d', distro, '--exec', 'wslpath', '-a', str(ROOT)], capture_output=True, text=True)
        if path.returncode:
            return path.returncode
        return execute(['wsl', '-d', distro, '--cd', path.stdout.strip(), '--exec', 'python3', '-B', 'tools/omni_dev.py', *argv])
    if str(ROOT).startswith('/mnt/') and not args.allow_slow_fs:
        parser.error('pass --allow-slow-fs for this mounted workspace; no source relocation is required')
    out = ROOT / 'build/dev'
    binary = out / 'omni'
    env = dict(os.environ, OMNI_HOME=str(ROOT), OMNI_TEST_BIN=str(binary), PYTHONDONTWRITEBYTECODE='1')
    if args.command == 'env':
        tools = {name: shutil.which(name) for name in ('c++', 'g++', 'clang', 'python3', 'node')}
        print(json.dumps({'platform': sys.platform, 'tools': tools,
                          'openssl_headers': pathlib.Path('/usr/include/openssl/evp.h').is_file(),
                          'node_headers': pathlib.Path('/usr/include/node/node_api.h').is_file(),
                          'product_version': (ROOT / 'VERSION').read_text(encoding='utf-8').strip(),
                          'git_required': False}, indent=2))
        return 0 if all(tools[name] for name in ('c++', 'clang', 'python3')) else 2
    if args.command == 'build':
        if not 1 <= args.jobs <= 16:
            parser.error('--jobs must be 1..16')
        targets = ('compiler', 'loader', 'node') if args.target == 'all' else (args.target,)
        out.mkdir(parents=True, exist_ok=True)
        for target in targets:
            output = {'compiler': binary, 'loader': out / 'runtime/libomni_invocation_v1.so',
                      'node': out / 'node/omni_host_sdk.node'}[target]
            stamp = out / (target + '.inputs.json')
            digest = fingerprint(target)
            if not args.force and artifact_current(output, stamp, digest):
                print('UP_TO_DATE ' + target)
                continue
            command = {'compiler': ['tools/build_compiler.py', '--output', output, '--jobs', args.jobs],
                       'loader': ['tools/build_invocation_loader.py', '--output', output, '--jobs', args.jobs],
                       'node': ['tools/build_host_sdk_node.py', '--runtime-dir', out / 'runtime', '--output', output]}[target]
            code = execute([sys.executable, '-B', *command], env)
            if code:
                return code
            if not output.is_file():
                return 1
            stamp.write_text(json.dumps({'inputs': digest, 'output': hashlib.sha256(output.read_bytes()).hexdigest()}, indent=2) + '\n', encoding='utf-8')
        return 0
    if not artifact_current(binary, out / 'compiler.inputs.json', fingerprint('compiler')):
        parser.error('compiler missing, stale or output changed; execute build')
    if args.command in ('check', 'run'):
        return execute([binary, args.command, args.source, *args.args], env)
    command = [sys.executable, '-B', 'tools/run_test_matrix.py', '--report', args.report, '--max-skips', '0']
    for group in args.group or ['core']:
        command += ['--group', group]
    return execute(command, env)


if __name__ == '__main__':
    sys.exit(main())
