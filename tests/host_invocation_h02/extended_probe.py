#!/usr/bin/env python3
"""Lifecycle, authority and isolation development probes for H02."""
import ctypes as c
import hashlib
import json
import os
import pathlib
import struct
import threading
import time

ROOT=pathlib.Path(os.environ['OMNI_H02_EVIDENCE_ROOT'])
LIB=c.CDLL(str(ROOT/'dist/runtime/libomni_invocation_v1.so'))
U8,U32,U64=c.c_uint8,c.c_uint32,c.c_uint64
P8=c.POINTER(U8)
LIB.omni_invocation_v1_module_open.argtypes=[P8,U32,P8,P8,c.POINTER(U64)]
LIB.omni_invocation_v1_module_open.restype=U32
LIB.omni_invocation_v1_invocation_create.argtypes=[U64,P8,U32,P8,U32,U64,U64,U64,U32,U32,P8,c.POINTER(U64)]
LIB.omni_invocation_v1_invocation_create.restype=U32
LIB.omni_invocation_v1_invoke.argtypes=[U64,c.POINTER(U32),c.POINTER(U32)]
LIB.omni_invocation_v1_invoke.restype=U32
LIB.omni_invocation_v1_cancel.argtypes=[U64]
LIB.omni_invocation_v1_cancel.restype=U32
LIB.omni_invocation_v1_result_read.argtypes=[U64,P8,U32,c.POINTER(U32)]
LIB.omni_invocation_v1_result_read.restype=U32
LIB.omni_invocation_v1_diagnostic_read.argtypes=[U64,P8,U32,c.POINTER(U32)]
LIB.omni_invocation_v1_diagnostic_read.restype=U32
LIB.omni_invocation_v1_invocation_destroy.argtypes=[U64]
LIB.omni_invocation_v1_invocation_destroy.restype=U32
LIB.omni_invocation_v1_module_close.argtypes=[U64]
LIB.omni_invocation_v1_module_close.restype=U32

def arr(data):return (U8*len(data)).from_buffer_copy(data)
def tid(name):return hashlib.sha256(('omni.type/1\n'+name).encode()).digest()
def val(tag,name,content):return bytes([tag])+tid(name)+content
def u32(value):return val(4,'u32',struct.pack('<I',value))
def text(value):
    data=value.encode() if isinstance(value,str) else value
    return val(11,'Text',struct.pack('<I',len(data))+data)
def receipt(name,variant=False):
    path=ROOT/('artifacts-v2' if variant else 'artifacts')/f'{name}.so'
    return path,json.loads(pathlib.Path(str(path)+'.omireceipt.json').read_text())
def frame(r,payload=b''):
    return b'OMIV1\0\0\0'+struct.pack('<II',1,1)+bytes.fromhex(r['signature_digest'])+struct.pack('<II',len(payload),len(r['parameter_type_ids']))+payload
def module_open(name,variant=False):
    path,r=receipt(name,variant);encoded=str(path).encode();handle=U64()
    status=LIB.omni_invocation_v1_module_open(arr(encoded),len(encoded),
        arr(bytes.fromhex(r['artifact_sha256'])),arr(bytes.fromhex(r['descriptor_sha256'])),c.byref(handle))
    return status,handle.value,r
def create(module,data,policy=b'',generation=0,deadline_ns=None,trace=None):
    handle=U64();status=LIB.omni_invocation_v1_invocation_create(module,
        arr(data),len(data),arr(policy) if policy else None,len(policy),generation,
        deadline_ns or time.clock_gettime_ns(time.CLOCK_MONOTONIC)+5_000_000_000,
        67108864,1048576,0,arr(trace or bytes(16)),c.byref(handle))
    return status,handle.value
def invoke(handle):
    effect,length=U32(),U32()
    status=LIB.omni_invocation_v1_invoke(handle,c.byref(effect),c.byref(length))
    return status,effect.value,length.value
def result(handle,length):
    output=(U8*length)();copied=U32()
    status=LIB.omni_invocation_v1_result_read(handle,output,length,c.byref(copied))
    return status,bytes(output[:copied.value]),output
def payload_number(data):return struct.unpack_from('<I',data,89)[0]
def fd_count():return len(list(pathlib.Path('/proc/self/fd').iterdir()))

checks=[]
def safe(value):
    if isinstance(value,bytes):
        return {'length':len(value),'sha256':hashlib.sha256(value).hexdigest()}
    if isinstance(value,(tuple,list)):return [safe(item) for item in value]
    return value
def check(name,actual,expected):
    checks.append({'name':name,'actual':safe(actual),'expected':safe(expected),
                   'passed':actual==expected})

# Repeated open/close must return descriptors to baseline.
baseline=fd_count()
for _ in range(32):
    status,module,r=module_open('zero')
    if status or LIB.omni_invocation_v1_module_close(module):raise AssertionError('open/close loop')
check('repeated_open_close_fd_delta',fd_count()-baseline,0)

# Same binding: semantic Err, recoverable trap, then clean semantic Ok.
status,module,r=module_open('maybe_fail',True)
check('maybe_fail_open',status,0)
for argument,expected_status,expected_value in ((0,1,7),(1,10,None),(2,0,2)):
    status,handle=create(module,frame(r,u32(argument)))
    check(f'maybe_create_{argument}',status,0)
    actual,effect,length=invoke(handle)
    check(f'maybe_status_{argument}',(actual,effect),(expected_status,0))
    if expected_value is not None:
        read,data,output=result(handle,length)
        check(f'maybe_result_{argument}',(read,struct.unpack_from('<I',data,123)[0]),
              (0,expected_value))
    check(f'maybe_destroy_{argument}',LIB.omni_invocation_v1_invocation_destroy(handle),0)
check('maybe_close',LIB.omni_invocation_v1_module_close(module),0)

# A granted read does not confer authority to the next invocation.
data_file=ROOT/'granted-read.txt'
data_file.write_bytes(b'abc')
status,module,r=module_open('read_effect',True)
check('read_effect_open',status,0)
path=str(data_file)
policy=(f'OHP1\ngeneration|1\nnot_after_tick|100000\n'
        f'grant|fs.read|{path}|64\n').encode()
for label,grant,expected in (('granted',True,3),('deny_next',False,1)):
    status,handle=create(module,frame(r,text(path)),policy if grant else b'',1 if grant else 0)
    check(f'read_{label}_create',status,0)
    actual,effect,length=invoke(handle)
    read,data,output=result(handle,length)
    check(f'read_{label}_result',(actual,effect,read,payload_number(data)),
          (0,1 if grant else 0,0,expected))
    check(f'read_{label}_destroy',LIB.omni_invocation_v1_invocation_destroy(handle),0)
check('read_effect_close',LIB.omni_invocation_v1_module_close(module),0)

# Host request and result memory never alias the module's copied values.
status,module,r=module_open('echo_text')
secret=b'secret=never-log-this'
original=frame(r,text(secret))
host_input=arr(original)
handle=U64()
created=LIB.omni_invocation_v1_invocation_create(module,host_input,len(original),
    None,0,0,time.clock_gettime_ns(time.CLOCK_MONOTONIC)+5_000_000_000,
    67108864,1048576,0,arr(bytes(16)),c.byref(handle))
check('input_copy_create',created,0)
for index in range(len(host_input)):host_input[index]=0
actual,effect,length=invoke(handle)
read,data,output=result(handle.value,length)
check('input_copy_roundtrip',(actual,effect,read,data[56:]),
      (0,0,0,text(secret)))
diagnostic=(U8*16384)();copied=U32()
check('diagnostic_redacted',(LIB.omni_invocation_v1_diagnostic_read(handle,diagnostic,16384,c.byref(copied)),
      copied.value,secret in bytes(diagnostic)),(0,0,False))
for index in range(len(output)):output[index]=0
check('input_copy_destroy',LIB.omni_invocation_v1_invocation_destroy(handle),0)
status,second=create(module,original)
actual,effect,length=invoke(second)
read,data,output=result(second,length)
check('output_copy_independent',(actual,effect,read,data[56:]),(0,0,0,text(secret)))
check('output_copy_destroy',LIB.omni_invocation_v1_invocation_destroy(second),0)
check('echo_text_close',LIB.omni_invocation_v1_module_close(module),0)

# Denied filesystem writes cannot create a file.
write_target=pathlib.Path('/tmp/omni-host02-denied-write')
if write_target.exists():raise RuntimeError('denied write target already exists')
status,module,r=module_open('write_denied',True)
status,handle=create(module,frame(r))
actual,effect,length=invoke(handle)
read,data,output=result(handle,length)
check('write_deny_all',(actual,effect,read,payload_number(data),write_target.exists()),
      (0,0,0,1,False))
check('write_destroy',LIB.omni_invocation_v1_invocation_destroy(handle),0)
check('write_close',LIB.omni_invocation_v1_module_close(module),0)

# Stale and wrong-kind handles fail without touching an unrelated live context.
status,module,r=module_open('zero')
status,handle=create(module,frame(r))
actual,effect,length=invoke(handle)
read,data,output=result(handle,length)
check('wrong_kind_result_read',LIB.omni_invocation_v1_result_read(module,output,length,c.byref(copied)),12)
check('wrong_kind_module_close',LIB.omni_invocation_v1_module_close(handle),12)
check('stale_destroy_first',LIB.omni_invocation_v1_invocation_destroy(handle),0)
effect_out,length_out=U32(),U32()
check('stale_invoke',LIB.omni_invocation_v1_invoke(handle,c.byref(effect_out),c.byref(length_out)),12)
check('stale_cancel',LIB.omni_invocation_v1_cancel(handle),12)
check('stale_read',LIB.omni_invocation_v1_result_read(handle,output,length,c.byref(copied)),12)
check('stale_diagnostic',LIB.omni_invocation_v1_diagnostic_read(handle,diagnostic,16384,c.byref(copied)),12)
check('stale_destroy',LIB.omni_invocation_v1_invocation_destroy(handle),12)
check('module_close_first',LIB.omni_invocation_v1_module_close(module),0)
check('stale_module_close',LIB.omni_invocation_v1_module_close(module),12)
check('stale_module_create',create(module,frame(r)),(12,0))

# One invocation remains active while a hosted worker waits; BUSY and cancel
# must preserve resources, then UNKNOWN_OUTCOME remains distinct.
adapter=ROOT/'slow_adapter'
pid_file=ROOT/'slow_adapter.pid'
if not adapter.exists():raise RuntimeError('composite probe must create slow_adapter first')
pid_file.write_text('')
status,module,r=module_open('process_effect')
policy=(f'OHP1\ngeneration|1\nnot_after_tick|100000\n'
        f'grant|process.spawn|{adapter}|64\n').encode()
status,active=create(module,frame(r,text(str(adapter))),policy,1,
    time.clock_gettime_ns(time.CLOCK_MONOTONIC)+5_000_000_000)
check('running_create',status,0)
completed=[]
thread=threading.Thread(target=lambda:completed.append(invoke(active)))
thread.start()
until=time.monotonic()+2
while not pid_file.read_text() and time.monotonic()<until:time.sleep(0.001)
if not pid_file.read_text():raise AssertionError('worker did not start')
check('running_module_close',LIB.omni_invocation_v1_module_close(module),13)
check('running_invocation_destroy',LIB.omni_invocation_v1_invocation_destroy(active),13)
status,other=create(module,frame(r,text(str(adapter))),policy,1)
check('second_create',status,0)
check('concurrent_second_invoke',invoke(other)[0],13)
check('cross_thread_cancel',LIB.omni_invocation_v1_cancel(active),0)
thread.join(timeout=3)
if thread.is_alive():raise AssertionError('cancel did not terminate worker')
check('cancel_after_dispatch',completed[0][:2],(11,2))
check('destroy_active',LIB.omni_invocation_v1_invocation_destroy(active),0)
check('destroy_other',LIB.omni_invocation_v1_invocation_destroy(other),0)
check('close_after_cancel',LIB.omni_invocation_v1_module_close(module),0)
try:os.kill(int(pid_file.read_text()),0);orphan=True
except ProcessLookupError:orphan=False
check('no_orphan_worker',orphan,False)

report={'schema':'omni.h02-extended-preflight/1','checks':checks,
        'passed':sum(item['passed'] for item in checks),'total':len(checks)}
(ROOT/'extended_report.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps({'passed':report['passed'],'total':report['total'],
                  'failures':[item for item in checks if not item['passed']]}))
raise SystemExit(0 if report['passed']==report['total'] else 1)
