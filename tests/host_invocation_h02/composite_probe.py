#!/usr/bin/env python3
"""Development OMI1 round-trip falsification, separate from formal H02 cases."""
import ctypes as c
import hashlib
import json
import os
import pathlib
import struct
import subprocess
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

def arr(data): return (U8*len(data)).from_buffer_copy(data)
def tid(name): return hashlib.sha256(('omni.type/1\n'+name).encode()).digest()
def val(tag,name,content): return bytes([tag])+tid(name)+content
def u32(x): return val(4,'u32',struct.pack('<I',x))
def frame(sig,kind,payload,count):
    return b'OMIV1\0\0\0'+struct.pack('<II',1,kind)+bytes.fromhex(sig)+struct.pack('<II',len(payload),count)+payload

def call(name,payload,expected_status=0):
    path=ROOT/'artifacts'/f'{name}.so'
    receipt=json.loads(pathlib.Path(str(path)+'.omireceipt.json').read_text())
    module=U64();p=str(path).encode()
    status=LIB.omni_invocation_v1_module_open(arr(p),len(p),arr(bytes.fromhex(receipt['artifact_sha256'])),arr(bytes.fromhex(receipt['descriptor_sha256'])),c.byref(module))
    if status: raise AssertionError((name,'open',status))
    request=frame(receipt['signature_digest'],1,payload,len(receipt['parameter_type_ids']))
    invocation=U64();status=LIB.omni_invocation_v1_invocation_create(module,arr(request),len(request),None,0,0,time.clock_gettime_ns(time.CLOCK_MONOTONIC)+5_000_000_000,64*1024*1024,1048576,0,arr(bytes(16)),c.byref(invocation))
    if status: raise AssertionError((name,'create',status))
    effect,length=U32(),U32();status=LIB.omni_invocation_v1_invoke(invocation,c.byref(effect),c.byref(length))
    if status!=expected_status: raise AssertionError((name,'invoke',status,effect.value))
    output=(U8*length.value)();copied=U32();read=LIB.omni_invocation_v1_result_read(invocation,output,length,c.byref(copied))
    if read: raise AssertionError((name,'read',read))
    if LIB.omni_invocation_v1_invocation_destroy(invocation):raise AssertionError((name,'destroy'))
    if LIB.omni_invocation_v1_module_close(module):raise AssertionError((name,'close'))
    data=bytes(output[:copied.value])
    if len(data)!=length.value or data[:16]!=request[:12]+struct.pack('<I',2):
        raise AssertionError((name,'frame'))
    return data[56:],receipt

results=[]
def roundtrip(name,payload,expected_status=0):
    response,receipt=call(name,payload,expected_status)
    passed=response==payload
    results.append({'entry':name,'payload_bytes':len(payload),'payload_sha256':hashlib.sha256(payload).hexdigest(),
                    'receipt_sha256':hashlib.sha256((ROOT/'artifacts'/f'{name}.so.omireceipt.json').read_bytes()).hexdigest(),
                    'passed':passed})
    if not passed:raise AssertionError((name,'mismatch',response[:100].hex(),payload[:100].hex()))

pair=val(15,'record:host_probe.Pair',struct.pack('<H',2)+u32(4)+u32(5))
choice=val(16,'enum:host_probe.Choice',struct.pack('<HB',1,1)+u32(6))
nested=val(15,'record:host_probe.Nested',struct.pack('<H',2)+pair+choice)
roundtrip('echo_pair',pair)
roundtrip('echo_choice',choice)
roundtrip('echo_nested',nested)
roundtrip('echo_option',val(17,'Option<u32>',b'\x01'+u32(7)))
roundtrip('echo_option',val(17,'Option<u32>',b'\x00'))
roundtrip('echo_result',val(18,'Result<u32,u32>',b'\x00'+u32(8)))
roundtrip('echo_result',val(18,'Result<u32,u32>',b'\x01'+u32(7)),expected_status=1)
roundtrip('echo_choice',val(16,'enum:host_probe.Choice',struct.pack('<HB',0,0)))
roundtrip('echo_tuple',val(13,'Tuple<u32,bool>',struct.pack('<H',2)+u32(2)+val(1,'bool',b'\x01')))
roundtrip('echo_array',val(14,'Array<u32,3>',struct.pack('<I',3)+u32(1)+u32(2)+u32(3)))
roundtrip('echo_array_zero',val(14,'Array<u8,0>',struct.pack('<I',0)))
roundtrip('echo_bool',val(1,'bool',b'\x01'))
roundtrip('echo_char',val(10,'Char',struct.pack('<I',0x1f680)))
for kind in ('echo_text','echo_bytes'):
    tag,name=(11,'Text') if kind=='echo_text' else (12,'Bytes')
    for length in (0,1048483):
        content=b'x'*length
        roundtrip(kind,val(tag,name,struct.pack('<I',length)+content))
response,receipt=call('semantic_err',b'',expected_status=1)
expected=val(18,'Result<u32,u32>',b'\x01'+u32(7))
results.append({'entry':'semantic_err','passed':response==expected,
                'payload_sha256':hashlib.sha256(response).hexdigest()})
if response!=expected:raise AssertionError('semantic_err mismatch')
for arm,value,expected_number in ((0,8,8),(1,7,1007)):
    payload=val(18,'Result<u32,u32>',bytes([arm])+u32(value))
    response,receipt=call('classify_result',payload)
    expected=u32(expected_number)
    results.append({'entry':f'classify_result_{arm}','passed':response==expected,
                    'payload_sha256':hashlib.sha256(response).hexdigest()})
    if response!=expected:raise AssertionError(('classify_result',arm,response.hex()))

adapter_source=ROOT/'slow_adapter.c'
adapter=ROOT/'slow_adapter'
pid_file=ROOT/'slow_adapter.pid'
adapter_source.write_text('#include <stdio.h>\n#include <unistd.h>\nint main(void){'
    f'FILE *f=fopen("{pid_file}","w");if(f){{fprintf(f,"%ld",(long)getpid());fclose(f);}}'
    'sleep(5);return 0;}\n')
subprocess.run(['clang',str(adapter_source),'-o',str(adapter)],check=True)
path=ROOT/'artifacts/process_effect.so'
receipt=json.loads(pathlib.Path(str(path)+'.omireceipt.json').read_text())
module=U64();encoded_path=str(path).encode()
status=LIB.omni_invocation_v1_module_open(arr(encoded_path),len(encoded_path),
    arr(bytes.fromhex(receipt['artifact_sha256'])),arr(bytes.fromhex(receipt['descriptor_sha256'])),c.byref(module))
if status:raise AssertionError(('process_effect','open',status))
text=str(adapter).encode()
request=frame(receipt['signature_digest'],1,val(11,'Text',struct.pack('<I',len(text))+text),1)
policy=(f'OHP1\ngeneration|1\nnot_after_tick|100000\n'
        f'grant|process.spawn|{adapter}|64\n').encode()
invocation=U64()
status=LIB.omni_invocation_v1_invocation_create(module,arr(request),len(request),
    arr(policy),len(policy),1,time.clock_gettime_ns(time.CLOCK_MONOTONIC)+300_000_000,
    64*1024*1024,1048576,0,arr(bytes(16)),c.byref(invocation))
if status:raise AssertionError(('process_effect','create',status))
effect,length=U32(),U32()
started=time.monotonic()
status=LIB.omni_invocation_v1_invoke(invocation,c.byref(effect),c.byref(length))
elapsed=time.monotonic()-started
if LIB.omni_invocation_v1_invocation_destroy(invocation):raise AssertionError('destroy process')
if LIB.omni_invocation_v1_module_close(module):raise AssertionError('close process')
orphan=False
if pid_file.exists():
    try:os.kill(int(pid_file.read_text()),0);orphan=True
    except ProcessLookupError:pass
passed=(status==11 and effect.value==2 and length.value==0 and elapsed<2 and not orphan)
results.append({'entry':'process_effect_timeout','passed':passed,'status':status,
                'effect':effect.value,'elapsed_seconds':elapsed,'orphan':orphan})
if not passed:raise AssertionError(results[-1])
report={'schema':'omni.h02-composite-preflight/1','status':'PASS','results':results}
(ROOT/'composite_report.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps({'status':'PASS','roundtrips':len(results)}))
