#!/usr/bin/env python3
"""Development sentinels only; this is not the H02 terminal 39-case matrix."""
import ctypes as c
import hashlib
import json
import os
import pathlib
import shutil
import struct
import subprocess
import time

ROOT = pathlib.Path(os.environ['OMNI_H02_EVIDENCE_ROOT'])
DIST = ROOT / 'dist'
FIXTURE = pathlib.Path(__file__).resolve().parents[1] / 'fixtures' / 'host_invocation_h02'
PACKAGE = ROOT / 'fixture'
ARTIFACTS = ROOT / 'artifacts'
ARTIFACTS.mkdir(exist_ok=True)
shutil.copytree(FIXTURE, PACKAGE, dirs_exist_ok=True)
compiler = DIST / 'bin/omni'
loader = DIST / 'runtime/libomni_invocation_v1.so'
env = os.environ.copy()
env['OMNI_HOME'] = str(DIST)
env['LD_LIBRARY_PATH'] = str(DIST / 'runtime')
builds = {}
for name in ('zero', 'echo', 'read_denied', 'divide'):
    artifact = ARTIFACTS / f'{name}.so'
    command = [str(compiler), 'build', str(PACKAGE), '--host-entry',
               f'src/host.omni:{name}', '-o', str(artifact), '--offline']
    process = subprocess.run(command, env=env, capture_output=True, text=True)
    if process.returncode:
        raise RuntimeError((name, process.stdout, process.stderr))
    builds[name] = {'artifact': artifact,
                    'receipt': json.loads(pathlib.Path(str(artifact)+'.omireceipt.json').read_text()),
                    'command': command, 'exit_code': process.returncode,
                    'output_sha256': hashlib.sha256((process.stdout+process.stderr).encode()).hexdigest()}

# The host-entry build profile exercised above is normative and already
# implemented; it must also be discoverable from `omni --help` directly,
# alongside the ordinary executable build it is easy to confuse it with.
help_output = subprocess.run([str(compiler), '--help'], env=env, capture_output=True, text=True).stdout
host_entry_help_lines = [line for line in help_output.splitlines() if '--host-entry' in line]

lib = c.CDLL(str(loader))
U8 = c.c_uint8
U32 = c.c_uint32
U64 = c.c_uint64
P8 = c.POINTER(U8)
lib.omni_invocation_v1_module_open.argtypes = [P8,U32,P8,P8,c.POINTER(U64)]
lib.omni_invocation_v1_module_open.restype = U32
lib.omni_invocation_v1_invocation_create.argtypes = [U64,P8,U32,P8,U32,U64,U64,U64,U32,U32,P8,c.POINTER(U64)]
lib.omni_invocation_v1_invocation_create.restype = U32
lib.omni_invocation_v1_invoke.argtypes = [U64,c.POINTER(U32),c.POINTER(U32)]
lib.omni_invocation_v1_invoke.restype = U32
lib.omni_invocation_v1_cancel.argtypes = [U64]
lib.omni_invocation_v1_cancel.restype = U32
lib.omni_invocation_v1_result_read.argtypes = [U64,P8,U32,c.POINTER(U32)]
lib.omni_invocation_v1_result_read.restype = U32
lib.omni_invocation_v1_invocation_destroy.argtypes = [U64]
lib.omni_invocation_v1_invocation_destroy.restype = U32
lib.omni_invocation_v1_module_close.argtypes = [U64]
lib.omni_invocation_v1_module_close.restype = U32


def arr(data):
    return (U8*len(data)).from_buffer_copy(data)


def frame(receipt, value=None, bad_magic=False, bad_version=False, trailing=False):
    payload = b'' if value is None else (b'\x04' +
        bytes.fromhex(receipt['parameter_type_ids'][0]) + struct.pack('<I', value))
    data = (b'OMIV1\0\0\0' + struct.pack('<II', 2 if bad_version else 1, 1) +
            bytes.fromhex(receipt['signature_digest']) +
            struct.pack('<II', len(payload), len(receipt['parameter_type_ids'])) + payload)
    if bad_magic: data = b'X' + data[1:]
    if trailing: data += b'X'
    return data


def open_module(name):
    build = builds[name]
    path = str(build['artifact']).encode()
    receipt = build['receipt']
    module = U64()
    status = lib.omni_invocation_v1_module_open(
        arr(path), len(path), arr(bytes.fromhex(receipt['artifact_sha256'])),
        arr(bytes.fromhex(receipt['descriptor_sha256'])), c.byref(module))
    return status, module.value


def create(module, data, deadline=None, limit=64*1024*1024):
    handle = U64()
    status = lib.omni_invocation_v1_invocation_create(
        module, arr(data), len(data), None, 0, 0,
        deadline if deadline is not None else time.clock_gettime_ns(time.CLOCK_MONOTONIC)+5_000_000_000,
        limit, 1024*1024, 0, arr(bytes(16)), c.byref(handle))
    return status, handle.value


def invoke(handle):
    effect, length = U32(), U32()
    status = lib.omni_invocation_v1_invoke(handle, c.byref(effect), c.byref(length))
    return status, effect.value, length.value


def read(handle, length):
    data, copied = (U8*length)(), U32()
    status = lib.omni_invocation_v1_result_read(handle,data,length,c.byref(copied))
    return status, bytes(data[:copied.value])


observed = []
def check(name, actual, expected):
    observed.append({'sentinel': name, 'actual': actual, 'expected': expected,
                     'passed': actual == expected})


status, module = open_module('zero')
check('open_exact',status,0)
request = frame(builds['zero']['receipt'])
status, invocation = create(module, request)
check('create_zero',status,0)
check('module_busy',lib.omni_invocation_v1_module_close(module),13)
check('invoke_zero',invoke(invocation)[:2],(0,0))
status, data = read(invocation,93)
check('result_zero',(status,struct.unpack_from('<I',data,89)[0]),(0,17))
check('double_result_read',read(invocation,93)[0],12)
check('destroy_zero',lib.omni_invocation_v1_invocation_destroy(invocation),0)
check('destroy_stale',lib.omni_invocation_v1_invocation_destroy(invocation),12)
check('close_zero',lib.omni_invocation_v1_module_close(module),0)

status, module = open_module('echo')
check('open_echo',status,0)
for value in (123,456,123):
    status, invocation = create(module,frame(builds['echo']['receipt'],value))
    check(f'create_echo_{value}',status,0)
    result_status, effect, length = invoke(invocation)
    status, data = read(invocation,length)
    check(f'echo_{value}',(result_status,effect,status,struct.unpack_from('<I',data,89)[0]),
          (0,0,0,value))
    check(f'destroy_echo_{value}',lib.omni_invocation_v1_invocation_destroy(invocation),0)
check('malformed_magic',create(module,frame(builds['echo']['receipt'],1,bad_magic=True))[0],2)
check('wrong_version',create(module,frame(builds['echo']['receipt'],1,bad_version=True))[0],4)
check('trailing_bytes',create(module,frame(builds['echo']['receipt'],1,trailing=True))[0],2)
check('expired_deadline',create(module,frame(builds['echo']['receipt'],1),deadline=1)[0],8)
status, invocation = create(module,frame(builds['echo']['receipt'],1))
check('cancel_request',lib.omni_invocation_v1_cancel(invocation),0)
check('cancel_result',invoke(invocation)[:2],(9,0))
check('destroy_cancelled',lib.omni_invocation_v1_invocation_destroy(invocation),0)
check('close_echo',lib.omni_invocation_v1_module_close(module),0)

status, module = open_module('read_denied')
check('open_denied',status,0)
status, invocation = create(module,frame(builds['read_denied']['receipt']))
result_status,effect,length = invoke(invocation)
read_status,data = read(invocation,length)
check('fs_deny_all',(result_status,effect,read_status,struct.unpack_from('<I',data,89)[0]),
      (0,0,0,1))
check('destroy_denied',lib.omni_invocation_v1_invocation_destroy(invocation),0)
check('close_denied',lib.omni_invocation_v1_module_close(module),0)

status, module = open_module('divide')
check('open_divide',status,0)
status, invocation = create(module,frame(builds['divide']['receipt'],0))
check('runtime_fault',invoke(invocation)[:2],(10,0))
check('destroy_fault',lib.omni_invocation_v1_invocation_destroy(invocation),0)
status, invocation = create(module,frame(builds['divide']['receipt'],1))
result_status,effect,length = invoke(invocation)
read_status,data = read(invocation,length)
check('recover_after_fault',(result_status,effect,read_status,struct.unpack_from('<I',data,89)[0]),
      (0,0,0,7))
check('destroy_recovery',lib.omni_invocation_v1_invocation_destroy(invocation),0)
check('close_divide',lib.omni_invocation_v1_module_close(module),0)

check('host_entry_discoverable_in_help',len(host_entry_help_lines)>0,True)
check('ordinary_build_still_in_help',any('omni build FILE' in line for line in help_output.splitlines()),True)

report = {'schema':'omni.h02-development-sentinels/1','status':'PASS' if all(x['passed'] for x in observed) else 'FAIL',
          'builds':{name:{**{k:v for k,v in build.items() if k!='artifact'},'artifact':str(build['artifact'])}
                    for name,build in builds.items()},'observations':observed}
(ROOT/'sentinel_report.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps({'status':report['status'],'passed':sum(x['passed'] for x in observed),
                  'total':len(observed),'failures':[x for x in observed if not x['passed']]}))
raise SystemExit(0 if report['status']=='PASS' else 1)
