#!/usr/bin/env python3
"""Synthetic trampoline fault injection for H02 failure isolation development."""
import ctypes as c
import hashlib
import json
import os
import pathlib
import struct
import subprocess
import time

ROOT=pathlib.Path(os.environ['OMNI_H02_EVIDENCE_ROOT'])
REAL=ROOT/'artifacts/zero.so'
RECEIPT=json.loads(pathlib.Path(str(REAL)+'.omireceipt.json').read_text())
raw=REAL.read_bytes()

def descriptor_at(start):
    position=start+12
    def take(n):
        nonlocal position
        if n<0 or position+n>len(raw):raise ValueError('descriptor truncated')
        result=raw[position:position+n];position+=n;return result
    def string():return take(struct.unpack('<I',take(4))[0])
    for _ in range(4):string()
    take(64)
    string();string()
    take(struct.unpack('<I',take(4))[0]*32+32)
    for _ in range(struct.unpack('<I',take(4))[0]):string()
    string();string()
    take(64)
    string()
    take(96)
    return raw[start:position]

descriptor=None
magic=b'OMID1\0\0\0'
for position in range(len(raw)):
    if raw.startswith(magic,position):
        try:candidate=descriptor_at(position)
        except ValueError:continue
        if hashlib.sha256(candidate).hexdigest()==RECEIPT['descriptor_sha256']:
            descriptor=candidate;break
if descriptor is None:raise RuntimeError('descriptor extraction failed')

type_id=bytes.fromhex(RECEIPT['return_type_id'])
signature=bytes.fromhex(RECEIPT['signature_digest'])
payload=b'\x04'+type_id+struct.pack('<I',17)
good=(b'OMIV1\0\0\0'+struct.pack('<II',1,2)+signature+
      struct.pack('<II',len(payload),1)+payload)
def cbytes(data):return ','.join(str(byte) for byte in data)
source=ROOT/'fault_module.c'
source.write_text('''#include <stdint.h>
#include <string.h>
__attribute__((visibility("default"))) const uint8_t omni_module_v1_descriptor[]={DESCRIPTOR};
static const uint8_t good[]={GOOD};
__attribute__((visibility("default"))) uint32_t omni_module_v1_entry(
  uint32_t mode,const uint8_t *request,uint32_t request_len,
  const uint8_t *policy,uint32_t policy_len,uint64_t policy_generation,
  uint64_t deadline_ns,uint64_t allocation_limit,const uint8_t trace_id[16],
  const uint32_t *cancel_flag,uint8_t *result,uint32_t result_capacity,
  uint32_t *result_len,uint32_t *effect_observation){
  (void)policy;(void)policy_len;(void)policy_generation;(void)deadline_ns;
  (void)allocation_limit;(void)cancel_flag;
  *result_len=0;*effect_observation=0;
  if(mode==0)return 0;
  if(mode==1){
    if(trace_id[0]==2){*result_len=result_capacity+1;return 0;}
    if(result_capacity<sizeof good)return 6;
    memcpy(result,good,sizeof good);*result_len=sizeof good;
    if(trace_id[0]==0)result[0]='X';
    return 0;
  }
  if(mode==2)return request_len==sizeof good &&
    memcmp(request,good,sizeof good)==0?0:2;
  return 2;
}
'''.replace('DESCRIPTOR',cbytes(descriptor))
   .replace('GOOD',cbytes(good)))
fake=ROOT/'fault_module.so'
command=['clang','--target=x86_64-unknown-linux-gnu','-O2','-shared','-fPIC',
         '-fvisibility=hidden','-nostartfiles','-Wl,-z,relro,-z,now',
         str(source),'-o',str(fake)]
subprocess.run(command,check=True)

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

encoded=str(fake).encode()
request=(b'OMIV1\0\0\0'+struct.pack('<II',1,1)+signature+struct.pack('<II',0,0))
observed=[]
for trace_byte,expected in ((0,10),(2,6),(1,0)):
    module=U64()
    status=LIB.omni_invocation_v1_module_open(arr(encoded),len(encoded),
        arr(hashlib.sha256(fake.read_bytes()).digest()),
        arr(hashlib.sha256(descriptor).digest()),c.byref(module))
    if status:raise AssertionError(('open',trace_byte,status))
    handle=U64();trace=bytes([trace_byte])+bytes(15)
    created=LIB.omni_invocation_v1_invocation_create(module,arr(request),len(request),
        None,0,0,time.clock_gettime_ns(time.CLOCK_MONOTONIC)+5_000_000_000,
        67108864,1048576,0,arr(trace),c.byref(handle))
    if created:raise AssertionError(('create',trace_byte,created))
    effect,length=U32(),U32()
    actual=LIB.omni_invocation_v1_invoke(handle,c.byref(effect),c.byref(length))
    read_status=None
    if actual==0:
        output=(U8*length.value)();copied=U32()
        read_status=LIB.omni_invocation_v1_result_read(handle,output,length,c.byref(copied))
        if bytes(output[:copied.value])!=good:raise AssertionError('good frame mismatch')
    observed.append({'trace_byte':trace_byte,'status':actual,'expected':expected,
                     'effect':effect.value,'length':length.value,'read_status':read_status,
                     'passed':actual==expected and effect.value==0 and
                       (length.value==0 if actual else length.value==len(good))})
    if LIB.omni_invocation_v1_invocation_destroy(handle):raise AssertionError('destroy')
    if trace_byte!=1:
        stale=U64()
        poisoned=LIB.omni_invocation_v1_invocation_create(module,arr(request),len(request),
            None,0,0,time.clock_gettime_ns(time.CLOCK_MONOTONIC)+5_000_000_000,
            67108864,1048576,0,arr(trace),c.byref(stale))
        observed.append({'trace_byte':trace_byte,'poisoned_status':poisoned,
                         'expected':14,'passed':poisoned==14 and stale.value==0})
    if LIB.omni_invocation_v1_module_close(module):raise AssertionError('close')
report={'schema':'omni.h02-fault-injection-preflight/1','source_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),
        'fake_artifact_sha256':hashlib.sha256(fake.read_bytes()).hexdigest(),
        'descriptor_sha256':hashlib.sha256(descriptor).hexdigest(),
        'command':command,'observed':observed}
(ROOT/'fault_injection_report.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps({'passed':sum(x['passed'] for x in observed),'total':len(observed),
                  'observed':observed}))
raise SystemExit(0 if all(x['passed'] for x in observed) else 1)
