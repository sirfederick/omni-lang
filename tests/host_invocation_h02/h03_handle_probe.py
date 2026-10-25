#!/usr/bin/env python3
"""H03 lifecycle proof for stale handles and the fail-closed serial ceiling.

This deliberately builds a test-only loader.  The public production ABI never
exports the injection symbol; the test binary exercises the same `newHandle`
implementation with its counter placed at the terminal boundary.
"""
import ctypes as c
import hashlib
import json
import os
import pathlib
import shutil
import struct
import subprocess
import time

HERE = pathlib.Path(__file__).resolve().parent
CORE = HERE.parents[1]
ROOT = pathlib.Path(os.environ['OMNI_H03_EVIDENCE_ROOT'])
OUT = ROOT / 'life-07'
DIST = OUT / 'dist'
ARTIFACT = OUT / 'zero.so'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(command, env):
    result = subprocess.run(command, env=env, capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError(f'{command!r}\n{result.stdout}{result.stderr}')
    return result


def byte_array(data):
    return (c.c_uint8 * len(data)).from_buffer_copy(data)


def main():
    if OUT.exists():
        raise SystemExit('LIFE-07 evidence already exists')
    (DIST / 'bin').mkdir(parents=True)
    (DIST / 'runtime').mkdir()
    shutil.copy2(ROOT / 'dist/bin/omni', DIST / 'bin/omni')
    for name in ('omni_invocation_v1.h', 'omni_invocation_internal.h'):
        shutil.copy2(CORE / 'runtime' / name, DIST / 'runtime' / name)
    env = os.environ.copy()
    env.update({'OMNI_HOME': str(DIST), 'LD_LIBRARY_PATH': str(DIST / 'runtime')})
    commands = []
    command = ['python3', str(CORE / 'tools/build_invocation_loader.py'),
               '--output', str(DIST / 'runtime/libomni_invocation_v1.so'),
               '--jobs', '4', '--testing']
    run(command, env); commands.append(command)
    command = [str(DIST / 'bin/omni'), 'build', str(CORE / 'tests/fixtures/host_invocation_h02'),
               '--host-entry', 'src/host.omni:zero', '-o', str(ARTIFACT), '--offline']
    run(command, env); commands.append(command)
    receipt = json.loads(pathlib.Path(str(ARTIFACT) + '.omireceipt.json').read_text())
    library = c.CDLL(str(DIST / 'runtime/libomni_invocation_v1.so'))
    U8, U32, U64 = c.c_uint8, c.c_uint32, c.c_uint64
    P8 = c.POINTER(U8)
    library.omni_invocation_v1_module_open.argtypes = [P8, U32, P8, P8, c.POINTER(U64)]
    library.omni_invocation_v1_module_open.restype = U32
    library.omni_invocation_v1_invocation_create.argtypes = [U64, P8, U32, P8, U32, U64, U64, U64, U32, U32, P8, c.POINTER(U64)]
    library.omni_invocation_v1_invocation_create.restype = U32
    library.omni_invocation_v1_invoke.argtypes = [U64, c.POINTER(U32), c.POINTER(U32)]
    library.omni_invocation_v1_invoke.restype = U32
    library.omni_invocation_v1_invocation_destroy.argtypes = [U64]
    library.omni_invocation_v1_invocation_destroy.restype = U32
    library.omni_invocation_v1_module_close.argtypes = [U64]
    library.omni_invocation_v1_module_close.restype = U32
    force = library.omni_invocation_v1_test_force_next_handle
    force.argtypes = [U64]
    force.restype = U32

    path = str(ARTIFACT).encode()
    artifact_hash = bytes.fromhex(receipt['artifact_sha256'])
    descriptor_hash = bytes.fromhex(receipt['descriptor_sha256'])
    request = (b'OMIV1\0\0\0' + struct.pack('<II', 1, 1) +
               bytes.fromhex(receipt['signature_digest']) + struct.pack('<II', 0, 0))
    rows = []
    def check(name, observed, expected):
        rows.append({'name': name, 'observed': observed, 'expected': expected,
                     'passed': observed == expected})

    check('force_near_wrap', force((1 << 63) - 1), 0)
    module = U64()
    status = library.omni_invocation_v1_module_open(byte_array(path), len(path),
        byte_array(artifact_hash), byte_array(descriptor_hash), c.byref(module))
    check('near_wrap_open_fails_closed', (status, module.value), (6, 0))
    check('reset_counter', force(1), 0)
    stale = 0
    for index in range(128):
        module = U64()
        status = library.omni_invocation_v1_module_open(byte_array(path), len(path),
            byte_array(artifact_hash), byte_array(descriptor_hash), c.byref(module))
        if status:
            raise RuntimeError(f'open {index}: {status}')
        invocation = U64()
        status = library.omni_invocation_v1_invocation_create(
            module, byte_array(request), len(request), None, 0, 0,
            time.clock_gettime_ns(time.CLOCK_MONOTONIC) + 5_000_000_000,
            67_108_864, 1_048_576, 0, byte_array(bytes(16)), c.byref(invocation))
        if status:
            raise RuntimeError(f'create {index}: {status}')
        effect, length = U32(), U32()
        if library.omni_invocation_v1_invoke(invocation, c.byref(effect), c.byref(length)):
            raise RuntimeError(f'invoke {index}')
        if stale:
            check(f'stale_{index}', library.omni_invocation_v1_invocation_destroy(stale), 12)
        stale = invocation.value
        if library.omni_invocation_v1_invocation_destroy(invocation):
            raise RuntimeError(f'destroy {index}')
        if library.omni_invocation_v1_module_close(module):
            raise RuntimeError(f'close {index}')
    report = {'schema': 'omni.core-host-03-life-07/1', 'commands': commands,
              'loader_sha256': sha(DIST / 'runtime/libomni_invocation_v1.so'),
              'artifact_sha256': sha(ARTIFACT), 'descriptor_sha256': receipt['descriptor_sha256'],
              'checks': rows, 'passed': sum(row['passed'] for row in rows), 'total': len(rows)}
    (OUT / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({'passed': report['passed'], 'total': report['total']}))
    return 0 if report['passed'] == report['total'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
