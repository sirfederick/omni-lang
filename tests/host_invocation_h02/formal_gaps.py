#!/usr/bin/env python3
"""H02 identity, precedence, lifecycle, and cancellation oracles.

All generated files stay in OMNI_H02_EVIDENCE_ROOT. The synthetic ELF variants
exercise verification before module code can run; they are never trusted builds.
"""
import ctypes as c
import hashlib
import json
import os
import pathlib
import shutil
import struct
import subprocess
import threading
import time

ROOT = pathlib.Path(os.environ['OMNI_H02_EVIDENCE_ROOT'])
DIST = ROOT / 'dist'
LIB = c.CDLL(str(DIST / 'runtime/libomni_invocation_v1.so'))
U8, U32, U64 = c.c_uint8, c.c_uint32, c.c_uint64
P8 = c.POINTER(U8)
LIB.omni_invocation_v1_module_open.argtypes = [P8, U32, P8, P8, c.POINTER(U64)]
LIB.omni_invocation_v1_module_open.restype = U32
LIB.omni_invocation_v1_invocation_create.argtypes = [U64, P8, U32, P8, U32,
    U64, U64, U64, U32, U32, P8, c.POINTER(U64)]
LIB.omni_invocation_v1_invocation_create.restype = U32
LIB.omni_invocation_v1_invoke.argtypes = [U64, c.POINTER(U32), c.POINTER(U32)]
LIB.omni_invocation_v1_invoke.restype = U32
LIB.omni_invocation_v1_cancel.argtypes = [U64]
LIB.omni_invocation_v1_cancel.restype = U32
LIB.omni_invocation_v1_result_read.argtypes = [U64, P8, U32, c.POINTER(U32)]
LIB.omni_invocation_v1_result_read.restype = U32
LIB.omni_invocation_v1_diagnostic_read.argtypes = [U64, P8, U32, c.POINTER(U32)]
LIB.omni_invocation_v1_diagnostic_read.restype = U32
LIB.omni_invocation_v1_invocation_destroy.argtypes = [U64]
LIB.omni_invocation_v1_invocation_destroy.restype = U32
LIB.omni_invocation_v1_module_close.argtypes = [U64]
LIB.omni_invocation_v1_module_close.restype = U32

checks = []

def check(name, actual, expected):
    passed = actual == expected
    def serial(value):
        if isinstance(value, bytes):
            return {'length':len(value),'sha256':hashlib.sha256(value).hexdigest()}
        if isinstance(value, (tuple, list)):
            return [serial(item) for item in value]
        return value
    checks.append(dict(name=name, actual=serial(actual), expected=serial(expected),
                       passed=passed))

def arr(data):
    return (U8 * len(data)).from_buffer_copy(data)

def receipt(name):
    path = ROOT / 'artifacts' / f'{name}.so'
    return path, json.loads(pathlib.Path(str(path) + '.omireceipt.json').read_text())

def module_open(path, artifact_hash, descriptor_hash):
    output = U64()
    name = str(path).encode()
    status = LIB.omni_invocation_v1_module_open(arr(name), len(name),
        arr(bytes.fromhex(artifact_hash)), arr(bytes.fromhex(descriptor_hash)),
        c.byref(output))
    return status, output.value

def open_named(name):
    path, meta = receipt(name)
    status, handle = module_open(path, meta['artifact_sha256'],
                                 meta['descriptor_sha256'])
    check(f'{name}_open', status, 0)
    return handle, meta

def frame(meta, payload=b'', version=1):
    return (b'OMIV1\0\0\0' + struct.pack('<II', version, 1) +
            bytes.fromhex(meta['signature_digest']) +
            struct.pack('<II', len(payload), len(meta['parameter_type_ids'])) + payload)

def create(module, request, policy=b'', generation=0, result_limit=1048576):
    output = U64()
    status = LIB.omni_invocation_v1_invocation_create(module, arr(request),
        len(request), arr(policy) if policy else None, len(policy), generation,
        time.clock_gettime_ns(time.CLOCK_MONOTONIC) + 5_000_000_000,
        67108864, result_limit, 0, arr(bytes(16)), c.byref(output))
    return status, output.value

def invoke(handle):
    effect, length = U32(), U32()
    status = LIB.omni_invocation_v1_invoke(handle, c.byref(effect), c.byref(length))
    return status, effect.value, length.value

def descriptor_region(elf, expected_hash):
    magic = b'OMID1\0\0\0'
    for start in range(len(elf)):
        if not elf.startswith(magic, start):
            continue
        pos = start + 8
        fields = {}
        try:
            def take(n):
                nonlocal pos
                if n < 0 or pos+n > len(elf):
                    raise ValueError('truncated descriptor')
                where = pos
                pos += n
                return elf[where:pos], where
            def string(label):
                n = struct.unpack('<I', take(4)[0])[0]
                data, where = take(n)
                fields[label] = (where, n)
                return data
            take(4)  # version
            string('abi')
            for label in ('origin', 'package', 'version'):
                string(label)
            for label in ('manifest', 'source'):
                fields[label] = (pos, 32); take(32)
            string('module'); string('entry')
            params = struct.unpack('<I', take(4)[0])[0]
            take(params*32+32)
            effects = struct.unpack('<I', take(4)[0])[0]
            for index in range(effects): string(f'effect{index}')
            string('target'); string('runtime_abi')
            fields['runtime_build'] = (pos, 32); take(32)
            fields['compiler'] = (pos, 32); take(32)
            string('profile')
            fields['lock'] = (pos, 32); take(32)
            fields['signature'] = (pos, 32); take(32)
            fields['build_input'] = (pos, 32); take(32)
        except (ValueError, struct.error):
            continue
        descriptor = elf[start:pos]
        if hashlib.sha256(descriptor).hexdigest() == expected_hash:
            return start, pos, fields
    raise AssertionError('verified descriptor not found')

# POS-01: operational paths do not change semantic build identity.
first_path, first_meta = receipt('zero')
other = ROOT / 'identity-second'
other.mkdir(exist_ok=True)
other_package = other / 'fixture'
shutil.copytree(ROOT / 'fixture', other_package, dirs_exist_ok=True)
other_artifact = other / 'zero.so'
env = os.environ.copy()
env['OMNI_HOME'] = str(DIST)
env['LD_LIBRARY_PATH'] = str(DIST / 'runtime')
env['TMPDIR'] = str(other)
env['OMNI_CACHE_DIR'] = str(other / 'cache')
build_command = [str(DIST / 'bin/omni'), 'build', str(other_package),
                 '--host-entry', 'src/host.omni:zero', '-o', str(other_artifact),
                 '--offline', '--force']
build = subprocess.run(build_command, cwd=other, env=env,
                       capture_output=True, text=True)
check('pos01_second_build_exit', build.returncode, 0)
if build.returncode == 0:
    other_meta = json.loads(pathlib.Path(str(other_artifact)+'.omireceipt.json').read_text())
    check('pos01_digests',
          (other_meta['signature_digest'], other_meta['build_input_digest']),
          (first_meta['signature_digest'], first_meta['build_input_digest']))
    status, handle = module_open(other_artifact, other_meta['artifact_sha256'],
                                 other_meta['descriptor_sha256'])
    check('pos01_relocated_open', status, 0)
    if status == 0:
        check('pos01_relocated_close', LIB.omni_invocation_v1_module_close(handle), 0)

# NEG-04: even when caller supplies hashes for a tampered ELF, internal
# descriptor consistency and installed runtime identity reject it.
elf = first_path.read_bytes()
start, end, fields = descriptor_region(elf, first_meta['descriptor_sha256'])
tamper_dir = ROOT / 'identity-tamper'
tamper_dir.mkdir(exist_ok=True)
for label in ('compiler', 'runtime_build', 'source', 'lock', 'entry', 'profile'):
    offset, length = fields[label]
    modified = bytearray(elf)
    modified[offset] = ord('X') if label in ('entry', 'profile') else modified[offset] ^ 1
    path = tamper_dir / f'{label}.so'
    path.write_bytes(modified)
    descriptor_hash = hashlib.sha256(modified[start:end]).hexdigest()
    artifact_hash = hashlib.sha256(modified).hexdigest()
    check(f'neg04_{label}', module_open(path, artifact_hash, descriptor_hash), (3, 0))
abi_offset, _ = fields['abi']
wrong_abi = bytearray(elf)
wrong_abi[abi_offset] = ord('X')
wrong_abi_path = tamper_dir / 'wrong-abi.so'
wrong_abi_path.write_bytes(wrong_abi)
check('neg03_module_abi', module_open(wrong_abi_path,
      hashlib.sha256(wrong_abi).hexdigest(),
      hashlib.sha256(wrong_abi[start:end]).hexdigest()), (4, 0))
check('neg04_wrong_artifact',
      module_open(first_path, '00'*32, first_meta['descriptor_sha256']), (3, 0))
check('neg04_wrong_descriptor',
      module_open(first_path, first_meta['artifact_sha256'], '00'*32), (3, 0))

# NEG-05: selected entry is intentionally public and the build profile fixed.
def rejected_build(label, entry, extra=()):
    artifact = other / f'reject-{label}.so'
    command = [str(DIST / 'bin/omni'), 'build', str(other_package),
               '--host-entry', entry, '-o', str(artifact), '--offline', *extra]
    process = subprocess.run(command, cwd=other, env=env,
                             capture_output=True, text=True)
    check(f'neg05_{label}', (process.returncode != 0, artifact.exists()),
          (True, False))
rejected_build('missing', 'src/host.omni:does_not_exist')
rejected_build('private', 'src/host.omni:main')
rejected_build('override', 'src/host.omni:zero', ('--opt', '2'))
rejected_build('unsafe_path', '../src/host.omni:zero')
variant_package = other / 'signature-variant'
shutil.copytree(ROOT / 'fixture', variant_package, dirs_exist_ok=True)
variant_source = variant_package / 'src/host.omni'
deep_type = 'u32'
for _ in range(33):
    deep_type = f'Option<{deep_type}>'
variant_source.write_text(variant_source.read_text() +
    '\npub func generic_host<T:Plain>(x T) T !pure { return x }\n'
    'pub func borrowed_host(x Borrow<Buffer>) u32 !{memory.read} '
    '{ return buffer.len(x) }\n'
    'pub func fail_secret(x Text) u32 !pure '
    '{ let n u32 = text.len(x); return 7u32 / (n - n) }\n')
lock_command = [str(DIST / 'bin/omni'), 'package', 'lock',
                str(variant_package), '--offline']
locked = subprocess.run(lock_command, cwd=other, env=env,
                        capture_output=True, text=True)
check('neg05_variant_lock', locked.returncode, 0)
if locked.returncode == 0:
    for label, selected in (('generic', 'generic_host'),
                            ('unsupported', 'borrowed_host')):
        artifact = other / f'reject-{label}.so'
        command = [str(DIST / 'bin/omni'), 'build', str(variant_package),
                   '--host-entry', f'src/host.omni:{selected}', '-o',
                   str(artifact), '--offline']
        process = subprocess.run(command, cwd=other, env=env,
                                 capture_output=True, text=True)
        check(f'neg05_{label}', (process.returncode != 0, artifact.exists()),
              (True, False))
    secret_artifact = other / 'fail-secret.so'
    secret_build = subprocess.run([str(DIST / 'bin/omni'), 'build',
        str(variant_package), '--host-entry', 'src/host.omni:fail_secret',
        '-o', str(secret_artifact), '--offline', '--force'],
        cwd=other, env=env, capture_output=True, text=True)
    check('sec06_secret_fixture_build', secret_build.returncode, 0)
    if secret_build.returncode == 0:
        secret_meta = json.loads(pathlib.Path(str(secret_artifact)+'.omireceipt.json').read_text())
        status, secret_module = module_open(secret_artifact,
            secret_meta['artifact_sha256'], secret_meta['descriptor_sha256'])
        check('sec06_secret_open', status, 0)
        secret = b'API_KEY=never-diagnose-this'
        text_payload = (bytes([11]) + hashlib.sha256(b'omni.type/1\nText').digest() +
                        struct.pack('<I', len(secret)) + secret)
        status, secret_context = create(secret_module, frame(secret_meta,text_payload))
        check('sec06_secret_create', status, 0)
        check('sec06_secret_runtime', invoke(secret_context)[:2], (10, 0))
        diagnostic = (U8 * 16384)()
        copied = U32()
        read = LIB.omni_invocation_v1_diagnostic_read(secret_context, diagnostic,
            16384, c.byref(copied))
        check('sec06_secret_diagnostic',
              (read, copied.value <= 16384, secret in bytes(diagnostic)),
              (0, True, False))
        check('sec06_secret_destroy',
              LIB.omni_invocation_v1_invocation_destroy(secret_context), 0)
        check('sec06_secret_close',
              LIB.omni_invocation_v1_module_close(secret_module), 0)

deep_package = other / 'depth-variant'
shutil.copytree(ROOT / 'fixture', deep_package, dirs_exist_ok=True)
deep_source = deep_package / 'src/host.omni'
deep_source.write_text(deep_source.read_text() +
    f'\npub func too_deep(x {deep_type}) {deep_type} !pure {{ return x }}\n')
deep_lock = subprocess.run([str(DIST / 'bin/omni'), 'package', 'lock',
    str(deep_package), '--offline'], cwd=other, env=env,
    capture_output=True, text=True)
check('neg09_deep_lock', deep_lock.returncode, 0)
deep_artifact = other / 'reject-too-deep.so'
deep_build = subprocess.run([str(DIST / 'bin/omni'), 'build',
    str(deep_package), '--host-entry', 'src/host.omni:too_deep',
    '-o', str(deep_artifact), '--offline'], cwd=other, env=env,
    capture_output=True, text=True)
check('neg09_deep_signature_rejected',
      (deep_build.returncode != 0, deep_artifact.exists()), (True, False))

option_module, option_meta = open_named('echo_option')
option_id = hashlib.sha256(b'omni.type/1\nOption<u32>').digest()
over_nested = bytes([17]) + option_id + b'\x01' + bytes([17]) + option_id + b'\x00'
check('neg09_extra_nesting', create(option_module,
      frame(option_meta, over_nested)), (2, 0))
check('neg09_option_close', LIB.omni_invocation_v1_module_close(option_module), 0)

secret_marker = b'API_KEY=malformed-no-echo'
module, meta = open_named('echo_text')
malformed = frame(meta, secret_marker)
check('sec06_malformed_secret', create(module, malformed), (2, 0))
check('sec06_malformed_close', LIB.omni_invocation_v1_module_close(module), 0)

# NEG-12: scalar limit precedes frame and policy parsing; OMI1 version
# precedes policy parsing after scalar bounds are valid.
module, meta = open_named('echo_bool')
bad_policy = b'INVALID-POLICY'
wrong_version = frame(meta, b'', version=2)
check('neg12_scalar_first', create(module, wrong_version, bad_policy,
                                   result_limit=1048577), (6, 0))
check('neg12_frame_first', create(module, wrong_version, bad_policy), (4, 0))
check('neg12_close', LIB.omni_invocation_v1_module_close(module), 0)

# LIFE-06 / SEC-03: no second read or wrong-kind/cross-module handle reuse.
module_a, meta_a = open_named('zero')
module_b, _ = open_named('zero')
status, invocation = create(module_a, frame(meta_a))
check('life06_create', status, 0)
status, effect, length = invoke(invocation)
check('life06_invoke', (status, effect), (0, 0))
output = (U8 * length)()
copied = U32()
check('life06_first_read', LIB.omni_invocation_v1_result_read(
    invocation, output, length, c.byref(copied)), 0)
check('life06_second_read', LIB.omni_invocation_v1_result_read(
    invocation, output, length, c.byref(copied)), 12)
check('sec03_wrong_kind_read', LIB.omni_invocation_v1_result_read(
    module_b, output, length, c.byref(copied)), 12)
check('sec03_wrong_kind_close', LIB.omni_invocation_v1_module_close(invocation), 12)
check('sec03_other_binding_busy', LIB.omni_invocation_v1_module_close(module_a), 13)
check('life06_destroy', LIB.omni_invocation_v1_invocation_destroy(invocation), 0)
check('life06_double_destroy', LIB.omni_invocation_v1_invocation_destroy(invocation), 12)
check('life06_close_a', LIB.omni_invocation_v1_module_close(module_a), 0)
check('life06_close_b', LIB.omni_invocation_v1_module_close(module_b), 0)
check('life06_double_close', LIB.omni_invocation_v1_module_close(module_b), 12)

module_a, meta_a = open_named('zero')
module_b, meta_b = open_named('echo')
status, stale_context = create(module_a, frame(meta_a))
check('sec03_create_a', status, 0)
status, live_context = create(module_b, frame(meta_b,
    bytes([4]) + hashlib.sha256(b'omni.type/1\nu32').digest() +
    struct.pack('<I', 456)))
check('sec03_create_b', status, 0)
check('sec03_destroy_a', LIB.omni_invocation_v1_invocation_destroy(stale_context), 0)
shared_host_buffer = (U8 * 256)(*([0xa5] * 256))
copied = U32()
bad_read = LIB.omni_invocation_v1_result_read(stale_context, shared_host_buffer,
                                               256, c.byref(copied))
check('sec03_cross_context_read',
      (bad_read, copied.value, bytes(shared_host_buffer)),
      (12, 0, bytes([0xa5] * 256)))
status, effect, length = invoke(live_context)
check('sec03_live_b_invoke', (status, effect), (0, 0))
read_status = LIB.omni_invocation_v1_result_read(live_context,
    shared_host_buffer, 256, c.byref(copied))
check('sec03_live_b_result',
      (read_status, struct.unpack_from('<I', bytes(shared_host_buffer), 89)[0]),
      (0, 456))
check('sec03_destroy_b', LIB.omni_invocation_v1_invocation_destroy(live_context), 0)
check('sec03_close_a', LIB.omni_invocation_v1_module_close(module_a), 0)
check('sec03_close_b', LIB.omni_invocation_v1_module_close(module_b), 0)

# TIME-03: one pure invocation is cancelled from another thread while active.
spin_module, spin_meta = open_named('spin')
status, spin = create(spin_module, frame(spin_meta))
check('time03_create', status, 0)
cancelled = []
def cancel_while_running():
    time.sleep(0.01)
    cancelled.append(LIB.omni_invocation_v1_cancel(spin))
    cancelled.append(LIB.omni_invocation_v1_cancel(spin))
thread = threading.Thread(target=cancel_while_running)
thread.start()
spin_status = invoke(spin)
thread.join(timeout=2)
check('time03_active_cancel_requests', cancelled, [0, 0])
check('time03_active_cancel_terminal', spin_status[:2], (9, 0))
check('time03_destroy', LIB.omni_invocation_v1_invocation_destroy(spin), 0)
check('time03_close', LIB.omni_invocation_v1_module_close(spin_module), 0)

report = {'schema':'omni.host-invocation-h02-formal-gaps/1',
          'command':'python3 tests/host_invocation_h02/formal_gaps.py',
          'build_command':build_command, 'checks':checks,
          'passed':sum(row['passed'] for row in checks),'total':len(checks)}
(ROOT/'formal_gaps_report.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps({'passed':report['passed'],'total':report['total'],
                  'failures':[row for row in checks if not row['passed']]}))
raise SystemExit(0 if report['passed']==report['total'] else 1)
