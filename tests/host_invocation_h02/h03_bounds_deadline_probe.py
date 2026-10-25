#!/usr/bin/env python3
"""H03 NEG-11, ISO-03 and TIME-02 executable loader probes."""
import ctypes as c
import hashlib
import json
import os
import pathlib
import struct
import time

ROOT = pathlib.Path(os.environ['OMNI_H03_EVIDENCE_ROOT'])
OUT = ROOT / 'bounds-deadline'
OUT.mkdir(exist_ok=True)
LIB = c.CDLL(str(ROOT / 'dist/runtime/libomni_invocation_v1.so'))
U8, U32, U64, P8 = c.c_uint8, c.c_uint32, c.c_uint64, c.POINTER(c.c_uint8)
for name, args, result in (
 ('omni_invocation_v1_module_open',[P8,U32,P8,P8,c.POINTER(U64)],U32),
 ('omni_invocation_v1_invocation_create',[U64,P8,U32,P8,U32,U64,U64,U64,U32,U32,P8,c.POINTER(U64)],U32),
 ('omni_invocation_v1_invoke',[U64,c.POINTER(U32),c.POINTER(U32)],U32),
 ('omni_invocation_v1_result_read',[U64,P8,U32,c.POINTER(U32)],U32),
 ('omni_invocation_v1_invocation_destroy',[U64],U32),
 ('omni_invocation_v1_module_close',[U64],U32)):
    fn=getattr(LIB,name); fn.argtypes=args; fn.restype=result

def arr(value): return (U8 * len(value)).from_buffer_copy(value)
def receipt(name):
    path=ROOT/'artifacts'/f'{name}.so'
    return path,json.loads(pathlib.Path(str(path)+'.omireceipt.json').read_text())
def frame(meta,payload=b''):
    return b'OMIV1\0\0\0'+struct.pack('<II',1,1)+bytes.fromhex(meta['signature_digest'])+struct.pack('<II',len(payload),len(meta['parameter_type_ids']))+payload
def value_text(data):
    return bytes([11])+hashlib.sha256(b'omni.type/1\nText').digest()+struct.pack('<I',len(data))+data
def open_module(path,meta):
    result=U64(); encoded=str(path).encode()
    return LIB.omni_invocation_v1_module_open(arr(encoded),len(encoded),arr(bytes.fromhex(meta['artifact_sha256'])),arr(bytes.fromhex(meta['descriptor_sha256'])),c.byref(result)),result.value
def create(module,request,allocation=67108864,deadline=None):
    result=U64(); status=LIB.omni_invocation_v1_invocation_create(module,arr(request),len(request),None,0,0,
      deadline or time.clock_gettime_ns(time.CLOCK_MONOTONIC)+5_000_000_000,allocation,1048576,0,arr(bytes(16)),c.byref(result))
    return status,result.value
def rss(): return int(pathlib.Path('/proc/self/statm').read_text().split()[1]) * os.sysconf('SC_PAGE_SIZE')

rows=[]
def check(case,name,actual,expected): rows.append({'case_id':case,'name':name,'actual':actual,'expected':expected,'passed':actual==expected})

# The fstat load cap precedes read/hash/mapping; a sparse over-limit file must
# never be mapped or copied, even with arbitrary expected identity material.
oversized=OUT/'oversized.so'
with oversized.open('wb') as f: f.truncate(268435457)
handle=U64()
check('NEG-11','oversized_artifact_pre_mapping',LIB.omni_invocation_v1_module_open(arr(str(oversized).encode()),len(str(oversized).encode()),arr(bytes(32)),arr(bytes(32)),c.byref(handle)),6)
zero,zm=receipt('zero'); status,module=open_module(zero,zm); check('NEG-11','valid_control_open',status,0)
check('NEG-11','allocation_quota_zero',create(module,frame(zm),0)[0],6)
check('NEG-11','allocation_quota_above_cap',create(module,frame(zm),67108865)[0],6)
check('NEG-11','close_control',LIB.omni_invocation_v1_module_close(module),0)

# Repeated maximum admitted OMI1 values must release each invocation result and
# context. RSS is recorded as an external stability measurement; ASan leak
# campaign separately supplies allocator-level confirmation.
text_path,tm=receipt('echo_text'); status,module=open_module(text_path,tm); check('ISO-03','maximum_frame_open',status,0)
payload=value_text(b'x'*1048483); request=frame(tm,payload); baseline=rss(); peaks=[]
for index in range(16):
    status,inv=create(module,request); effect=U32(); length=U32()
    invoked=LIB.omni_invocation_v1_invoke(inv,c.byref(effect),c.byref(length)) if status==0 else status
    output=(U8*length.value)(); copied=U32()
    read=LIB.omni_invocation_v1_result_read(inv,output,length.value,c.byref(copied)) if invoked==0 else invoked
    destroyed=LIB.omni_invocation_v1_invocation_destroy(inv) if status==0 else status
    peaks.append(rss())
    check('ISO-03',f'maximum_call_{index}',(status,invoked,effect.value,read,destroyed,copied.value==length.value),(0,0,0,0,0,True))
check('ISO-03','rss_stable_after_destroy',max(peaks)-baseline <= 16*1024*1024,True)
check('ISO-03','maximum_frame_close',LIB.omni_invocation_v1_module_close(module),0)

# The compiled loop contains runtime safe points. A deadline set just ahead of
# dispatch must produce a terminal deadline rather than hanging the host.
spin,sm=receipt('spin'); status,module=open_module(spin,sm); check('TIME-02','spin_open',status,0)
status,inv=create(module,frame(sm),deadline=time.clock_gettime_ns(time.CLOCK_MONOTONIC)+1_000_000)
effect=U32(); length=U32(); started=time.monotonic(); invoked=LIB.omni_invocation_v1_invoke(inv,c.byref(effect),c.byref(length)) if status==0 else status; elapsed=time.monotonic()-started
check('TIME-02','pure_loop_deadline',(status,invoked,effect.value,length.value,elapsed < 2),(0,8,0,0,True))
check('TIME-02','deadline_destroy',LIB.omni_invocation_v1_invocation_destroy(inv),0)
check('TIME-02','deadline_close',LIB.omni_invocation_v1_module_close(module),0)

report={'schema':'omni.core-host-03-bounds-deadline/1','checks':rows,'passed':sum(x['passed'] for x in rows),'total':len(rows),'rss_baseline':baseline,'rss_samples':peaks}
(OUT/'report.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps({'passed':report['passed'],'total':report['total']}))
raise SystemExit(0 if report['passed']==report['total'] else 1)
