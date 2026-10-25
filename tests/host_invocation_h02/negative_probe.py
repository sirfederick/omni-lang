#!/usr/bin/env python3
"""Adversarial development probe; canonical H02 cases require later binding."""
import ctypes as c
import hashlib
import json
import os
import pathlib
import struct
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
LIB.omni_invocation_v1_result_read.argtypes=[U64,P8,U32,c.POINTER(U32)]
LIB.omni_invocation_v1_result_read.restype=U32
LIB.omni_invocation_v1_invocation_destroy.argtypes=[U64]
LIB.omni_invocation_v1_invocation_destroy.restype=U32
LIB.omni_invocation_v1_module_close.argtypes=[U64]
LIB.omni_invocation_v1_module_close.restype=U32

def arr(data):return (U8*len(data)).from_buffer_copy(data)
def tid(name):return hashlib.sha256(('omni.type/1\n'+name).encode()).digest()
def val(tag,name,content):return bytes([tag])+tid(name)+content
def artifact(name):
    path=ROOT/'artifacts'/f'{name}.so'
    return path,json.loads(pathlib.Path(str(path)+'.omireceipt.json').read_text())
def request(receipt,payload=b'',count=None,kind=1,version=1):
    if count is None:count=len(receipt['parameter_type_ids'])
    return (b'OMIV1\0\0\0'+struct.pack('<II',version,kind)+
        bytes.fromhex(receipt['signature_digest'])+struct.pack('<II',len(payload),count)+payload)
def open_artifact(name,artifact_hash=None,descriptor_hash=None):
    path,receipt=artifact(name);encoded=str(path).encode();module=U64()
    status=LIB.omni_invocation_v1_module_open(arr(encoded),len(encoded),
        arr(artifact_hash or bytes.fromhex(receipt['artifact_sha256'])),
        arr(descriptor_hash or bytes.fromhex(receipt['descriptor_sha256'])),c.byref(module))
    return status,module.value,receipt
def create(module,frame,policy=b'',generation=0,result_limit=1048576,
           deadline=None,allocation_limit=67108864):
    handle=U64()
    status=LIB.omni_invocation_v1_invocation_create(module,arr(frame),len(frame),
        arr(policy) if policy else None,len(policy),generation,
        deadline or time.clock_gettime_ns(time.CLOCK_MONOTONIC)+5_000_000_000,
        allocation_limit,result_limit,0,arr(bytes(16)),c.byref(handle))
    return status,handle.value
def invoke(handle):
    effect,length=U32(),U32()
    status=LIB.omni_invocation_v1_invoke(handle,c.byref(effect),c.byref(length))
    return status,effect.value,length.value

checks=[]
def check(name,observed,expected):
    checks.append({'name':name,'observed':observed,'expected':expected,
                   'passed':observed==expected})
def malformed_set(name,items):
    status,module,receipt=open_artifact(name)
    check(name+'_open',status,0)
    for label,payload,kwargs,expected in items:
        frame=request(receipt,payload,**kwargs)
        actual,handle=create(module,frame)
        check(label,(actual,handle),(expected,0))
    check(name+'_close',LIB.omni_invocation_v1_module_close(module),0)

bool_ok=val(1,'bool',b'\x01')
malformed_set('echo_bool',[
    ('wrong_tag',bytes([2])+bool_ok[1:],{},2),
    ('wrong_typeid',bool_ok[:1]+bytes(32)+bool_ok[33:],{},2),
    ('bad_bool',val(1,'bool',b'\x02'),{},2),
    ('truncated_bool',bool_ok[:-1],{},2),
    ('wrong_kind',bool_ok,{'kind':2},2),
    ('wrong_version',bool_ok,{'version':2},4),
])
char_ok=val(10,'Char',struct.pack('<I',65))
malformed_set('echo_char',[
    ('surrogate_char',val(10,'Char',struct.pack('<I',0xd800)),{},2),
    ('large_char',val(10,'Char',struct.pack('<I',0x110000)),{},2),
])
malformed_set('echo_text',[
    ('nul_text',val(11,'Text',struct.pack('<I',1)+b'\0'),{},2),
    ('bad_utf8',val(11,'Text',struct.pack('<I',1)+b'\xff'),{},2),
    ('truncated_text',val(11,'Text',struct.pack('<I',2)+b'a'),{},2),
])
u32=lambda n:val(4,'u32',struct.pack('<I',n))
malformed_set('echo_choice',[
    ('bad_enum_variant',val(16,'enum:host_probe.Choice',struct.pack('<HB',2,0)),{},2),
    ('bad_enum_payload_flag',val(16,'enum:host_probe.Choice',struct.pack('<HB',1,0)),{},2),
])
malformed_set('echo_pair',[
    ('bad_record_count',val(15,'record:host_probe.Pair',struct.pack('<H',1)+u32(1)+u32(2)),{},2),
])
malformed_set('echo_array',[
    ('bad_array_count',val(14,'Array<u32,3>',struct.pack('<I',4)+u32(1)*3),{},2),
    ('overflow_array_count',val(14,'Array<u32,3>',struct.pack('<I',0xffffffff)),{},2),
])

status,module,receipt=open_artifact('echo_bool')
good=request(receipt,bool_ok)
check('bad_magic',create(module,b'X'+good[1:]),(2,0))
check('trailing_bytes',create(module,good+b'X'),(2,0))
check('oversize_request',create(module,good+b'x'*(1048577-len(good))),(6,0))
check('small_quota',create(module,good,allocation_limit=1),(6,0))
check('expired',create(module,good,deadline=1),(8,0))
check('wrong_kind_handle_create',create(module<<1,good),(12,0))
check('echo_bool_close',LIB.omni_invocation_v1_module_close(module),0)

status,module,receipt=open_artifact('echo_text')
payload=val(11,'Text',struct.pack('<I',5)+b'hello')
status,handle=create(module,request(receipt,payload),result_limit=64)
check('result_limited_create',status,0)
check('oversize_result',invoke(handle)[:2],(6,0))
check('result_limited_destroy',LIB.omni_invocation_v1_invocation_destroy(handle),0)
check('echo_text_close',LIB.omni_invocation_v1_module_close(module),0)

status,module,receipt=open_artifact('read_denied')
frame=request(receipt)
for label,policy,generation in [
    ('bad_policy_magic',b'NOPE\n',1),
    ('unknown_capability',b'OHP1\ngeneration|1\nnot_after_tick|1000\ngrant|magic.power|/tmp|64\n',1),
    ('excess_capability',b'OHP1\ngeneration|1\nnot_after_tick|1000\ngrant|net.connect|127.0.0.1:8042|64\n',1),
    ('wrong_generation',b'OHP1\ngeneration|1\nnot_after_tick|1000\ngrant|fs.read|/tmp|64\n',2),
]:
    check(label,create(module,frame,policy,generation),(7,0))
check('read_denied_close',LIB.omni_invocation_v1_module_close(module),0)

for name in ('tcp_denied','process_denied','ffi_denied'):
    status,module,receipt=open_artifact(name)
    check(name+'_open',status,0)
    status,handle=create(module,request(receipt))
    check(name+'_create',status,0)
    actual,effect,length=invoke(handle)
    output=(U8*length)();copied=U32()
    read=LIB.omni_invocation_v1_result_read(handle,output,length,c.byref(copied))
    number=struct.unpack_from('<I',bytes(output[:copied.value]),89)[0] if read==0 else None
    check(name+'_invoke_deny_all',(actual,effect,read,number),(0,0,0,1))
    check(name+'_destroy',LIB.omni_invocation_v1_invocation_destroy(handle),0)
    check(name+'_close',LIB.omni_invocation_v1_module_close(module),0)

for name,bad_artifact,bad_descriptor in [
    ('wrong_artifact_hash',bytes(32),None),
    ('wrong_descriptor_hash',None,bytes(32)),
]:
    status,handle,_=open_artifact('zero',bad_artifact,bad_descriptor)
    check(name,(status,handle),(3,0))

report={'schema':'omni.h02-negative-preflight/1','checks':checks,
        'passed':sum(row['passed'] for row in checks),'total':len(checks)}
(ROOT/'negative_report.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps({'passed':report['passed'],'total':report['total'],
    'failures':[row for row in checks if not row['passed']]}))
raise SystemExit(0 if report['passed']==report['total'] else 1)
