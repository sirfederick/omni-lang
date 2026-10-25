#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Federico T. Begna
# SPDX-License-Identifier: MIT OR Apache-2.0
"""Prepare real SDK artifacts and run the documented C/Node/Python examples."""
import argparse
import json
import os
import pathlib
import shutil
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=pathlib.Path, default=pathlib.Path('build/sdk-example'))
    parser.add_argument('--sdk', type=pathlib.Path, help='use an extracted SDK instead of source-tree build outputs')
    args = parser.parse_args(argv)
    if sys.platform == 'win32':
        distro = os.environ.get('OMNI_WSL_DISTRO', 'Ubuntu-24.04')
        def linux(path):
            return subprocess.check_output(['wsl', '-d', distro, '--exec', 'wslpath', '-a', str(path.resolve())], text=True).strip()
        command = ['wsl', '-d', distro, '--cd', linux(ROOT), '--exec', 'python3', '-B', 'tools/run_sdk_examples.py', '--output', linux(args.output)]
        if args.sdk:
            command += ['--sdk', linux(args.sdk)]
        return subprocess.run(command).returncode
    output = args.output.resolve()
    if output.exists():
        parser.error('output already exists; choose a fresh --output under build/')
    output.mkdir(parents=True)
    installed = args.sdk is not None or (ROOT / 'bin/omni').is_file()
    sdk = args.sdk.resolve() if args.sdk else (ROOT if installed else ROOT / 'build/dev')
    compiler = sdk / 'bin/omni' if installed else sdk / 'omni'
    home = sdk if installed else ROOT
    env = dict(os.environ, OMNI_HOME=str(output / 'dist'), OMNI_H02_EVIDENCE_ROOT=str(output),
               LD_LIBRARY_PATH=str(output / 'dist/runtime'), PYTHONDONTWRITEBYTECODE='1')
    rows = []
    def run(name, command, expected_output=None):
        process = subprocess.run([str(value) for value in command], cwd=ROOT, env=env, capture_output=True, text=True)
        (output / (name + '.log')).write_text(process.stdout + process.stderr, encoding='utf-8')
        rows.append({'step': name, 'exit_code': process.returncode})
        if process.returncode or (expected_output is not None and expected_output not in process.stdout):
            raise RuntimeError(name + ': ' + process.stdout + process.stderr)
        print(process.stdout.strip(), flush=True)
    try:
        for name in ('bin', 'runtime', 'node', 'python', 'include'):
            (output / 'dist' / name).mkdir(parents=True)
        shutil.copy2(compiler, output / 'dist/bin/omni')
        for path in (sdk / 'runtime').iterdir():
            if path.is_file():
                shutil.copy2(path, output / 'dist/runtime' / path.name)
        if not installed:
            for path in (ROOT / 'runtime').iterdir():
                if path.is_file():
                    shutil.copy2(path, output / 'dist/runtime' / path.name)
        shutil.copy2(sdk / 'node/omni_host_sdk.node', output / 'dist/node/omni_host_sdk.node')
        binding = sdk / 'python/omni_host_sdk.py' if installed else ROOT / 'bindings/python/omni_host_sdk.py'
        shutil.copy2(binding, output / 'dist/python/omni_host_sdk.py')
        shutil.copytree(ROOT / 'examples/host-sdk', output / 'fixture')
        (output / 'artifacts').mkdir()
        run('lock', [compiler, 'package', 'lock', output / 'fixture', '--offline'])
        artifact = output / 'artifacts/echo_u8.so'
        run('host-entry', [compiler, 'build', output / 'fixture', '--host-entry', 'src/echo.omni:echo_u8', '--offline', '-o', artifact])
        include = sdk / 'include' if installed else ROOT / 'include'
        runtime_headers = sdk / 'runtime' if installed else ROOT / 'runtime'
        consumer = output / 'c-consumer'
        run('compile-c', ['cc', '-std=c11', '-Wall', '-Wextra', '-Werror', '-I', include, '-I', runtime_headers,
                          ROOT / 'examples/host-sdk/consumer.c', '-L', output / 'dist/runtime', '-lomni_invocation_v1', '-o', consumer])
        receipt = json.loads(pathlib.Path(str(artifact) + '.omireceipt.json').read_text())
        run('consume-c', [consumer, artifact, receipt['artifact_sha256'], receipt['descriptor_sha256'], output / 'node_echo_u8_result.omi1'], 'C: echo_u8(255) = 255 (real invocation)')
        run('consume-node', ['node', ROOT / 'examples/host-sdk/consumer.mjs', output], 'Node: encoded 255; decoded runtime response = 255')
        run('consume-python', ['python3', '-B', ROOT / 'examples/host-sdk/consumer.py', output], 'Python: encoded 255; decoded runtime response = 255')
    except (OSError, RuntimeError) as error:
        (output / 'report.json').write_text(json.dumps({'status': 'FAIL', 'steps': rows, 'error': str(error)}, indent=2) + '\n')
        print(str(error), file=sys.stderr)
        return 1
    (output / 'report.json').write_text(json.dumps({'status': 'PASS', 'steps': rows, 'product_version': (home / 'VERSION').read_text().strip(),
                                                  'scope': 'C invokes; Node/Python encode and decode a prepared real runtime response'}, indent=2) + '\n')
    return 0


if __name__ == '__main__':
    sys.exit(main())
