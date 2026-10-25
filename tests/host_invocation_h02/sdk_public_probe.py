#!/usr/bin/env python3
"""Exercise the public SDK without a host-side OMI1 implementation."""
from __future__ import annotations
import ctypes as c
import hashlib
import json
import os
import time
from pathlib import Path

ROOT=Path(os.environ['OMNI_H02_EVIDENCE_ROOT']);LIB=c.CDLL(str(ROOT/'dist/runtime/libomni_invocation_v1.so'))
U8,U32,U64,P8=c.c_uint8,c.c_uint32,c.c_uint64,c.POINTER(c.c_uint8)
def sig(name,args,ret=U32):
    fn=getattr(LIB,name);fn.argtypes=args;fn.restype=ret;return fn
sdk_open=sig('omni_host_sdk_v1_module_open',[P8,U32,P8,P8,c.POINTER(U64)])
sdk_close=sig('omni_host_sdk_v1_module_close',[U64]);req_count=sig('omni_host_sdk_v1_module_request_count',[U64,c.POINTER(U32)])
req_node=sig('omni_host_sdk_v1_module_request_node',[U64,U32,c.POINTER(U32)]);result_node=sig('omni_host_sdk_v1_module_result_node',[U64,c.POINTER(U32)])
make=sig('omni_host_sdk_v1_value_create',[U64,U32,c.POINTER(U64)]);drop=sig('omni_host_sdk_v1_value_destroy',[U64]);set_bits=sig('omni_host_sdk_v1_value_scalar_set',[U64,U64]);get_bits=sig('omni_host_sdk_v1_value_scalar_get',[U64,c.POINTER(U64)])
encode=sig('omni_host_sdk_v1_request_encode',[U64,c.POINTER(U64),U32,P8,U32,c.POINTER(U32)]);decode=sig('omni_host_sdk_v1_result_decode',[U64,P8,U32,c.POINTER(U64)])
raw_open=sig('omni_invocation_v1_module_open',[P8,U32,P8,P8,c.POINTER(U64)]);create=sig('omni_invocation_v1_invocation_create',[U64,P8,U32,P8,U32,U64,U64,U64,U32,U32,P8,c.POINTER(U64)])
invoke=sig('omni_invocation_v1_invoke',[U64,c.POINTER(U32),c.POINTER(U32)]);read=sig('omni_invocation_v1_result_read',[U64,P8,U32,c.POINTER(U32)]);destroy=sig('omni_invocation_v1_invocation_destroy',[U64]);raw_close=sig('omni_invocation_v1_module_close',[U64])
def arr(data): return (U8*len(data)).from_buffer_copy(data) if data else None
def open_one(fn):
    receipt=json.loads(Path(str(fn)+'.omireceipt.json').read_text());path=str(fn).encode();out=U64();code=sdk_open(arr(path),len(path),arr(bytes.fromhex(receipt['artifact_sha256'])),arr(bytes.fromhex(receipt['descriptor_sha256'])),c.byref(out));return code,out,receipt,path
def main():
    artifact=ROOT/'artifacts/echo.so';code,mod,receipt,path=open_one(artifact);checks={'sdk_open':code==0};count=U32();checks['request_count']=req_count(mod,c.byref(count))==0 and count.value==1;root=U32();checks['request_node']=req_node(mod,0,c.byref(root))==0
    arg=U64();checks['value_create']=make(mod,root,c.byref(arg))==0;checks['value_set']=set_bits(arg,41)==0
    args=(U64*1)(arg.value);size=U32();checks['encode_probe']=encode(mod,args,1,None,0,c.byref(size))==6 and size.value>56;frame=(U8*size.value)();checks['encode']=encode(mod,args,1,frame,size.value,c.byref(size))==0
    raw=U64();checks['raw_open']=raw_open(arr(path),len(path),arr(bytes.fromhex(receipt['artifact_sha256'])),arr(bytes.fromhex(receipt['descriptor_sha256'])),c.byref(raw))==0
    inv=U64();trace=(U8*16)();checks['create']=create(raw,frame,size.value,None,0,0,time.monotonic_ns()+5_000_000_000,1_000_000,65536,0,trace,c.byref(inv))==0
    effect=U32();result_size=U32();checks['invoke']=invoke(inv,c.byref(effect),c.byref(result_size))==0;result=(U8*result_size.value)();copied=U32();checks['read']=read(inv,result,result_size.value,c.byref(copied))==0
    decoded=U64();checks['decode']=decode(mod,result,copied.value,c.byref(decoded))==0;bits=U64();checks['value_get']=get_bits(decoded,c.byref(bits))==0 and bits.value==41
    bad=bytearray(bytes(result[:copied.value]));bad[0]^=1;checks['malformed_denied']=decode(mod,arr(bad),len(bad),c.byref(U64()))==2
    other_code,other,_,_=open_one(artifact);checks['second_module']=other_code==0
    checks['cross_module_denied']=encode(other,args,1,None,0,c.byref(U32()))==3
    checks['module_busy_with_value']=sdk_close(mod)==13
    checks['value_destroy']=drop(decoded)==0 and drop(arg)==0
    checks['stale_value_denied']=get_bits(arg,c.byref(U64()))==12 and drop(arg)==12
    checks['cleanup']=destroy(inv)==0 and raw_close(raw)==0 and sdk_close(mod)==0 and sdk_close(mod)==12 and sdk_close(other)==0
    def scalar_roundtrip(name: str, bits: int) -> bool:
        code,sm,meta,sp=open_one(ROOT/f'artifacts/{name}.so')
        if code: return False
        rn=U32(); value=U64(); need=U32()
        ok=req_node(sm,0,c.byref(rn))==0 and make(sm,rn,c.byref(value))==0 and set_bits(value,bits)==0
        args2=(U64*1)(value.value); ok=ok and encode(sm,args2,1,None,0,c.byref(need))==6
        request=(U8*need.value)(); ok=ok and encode(sm,args2,1,request,need.value,c.byref(need))==0
        raw2=U64(); p=str(ROOT/f'artifacts/{name}.so').encode()
        ok=ok and raw_open(arr(p),len(p),arr(bytes.fromhex(meta['artifact_sha256'])),arr(bytes.fromhex(meta['descriptor_sha256'])),c.byref(raw2))==0
        inv2=U64(); effect2=U32(); length2=U32(); trace2=(U8*16)()
        ok=ok and create(raw2,request,need.value,None,0,0,time.monotonic_ns()+5_000_000_000,1_000_000,65536,0,trace2,c.byref(inv2))==0
        ok=ok and invoke(inv2,c.byref(effect2),c.byref(length2))==0
        response=(U8*length2.value)(); copied2=U32(); decoded2=U64(); found=U64()
        ok=ok and read(inv2,response,length2.value,c.byref(copied2))==0 and decode(sm,response,copied2.value,c.byref(decoded2))==0 and get_bits(decoded2,c.byref(found))==0 and found.value==bits
        ok=ok and drop(decoded2)==0 and drop(value)==0 and destroy(inv2)==0 and raw_close(raw2)==0 and sdk_close(sm)==0
        return ok
    for name,bits in {'echo_u8':255,'echo_u16':65535,'echo_u64':(1<<64)-1,'echo_i8':(1<<64)-1,'echo_i16':(1<<64)-1,'echo_i32':(1<<64)-(1<<31),'echo_i64':(1<<63)+1}.items():
        checks[f'lossless_{name}']=scalar_roundtrip(name,bits)
    report={'schema':'omni.host-sdk-public-probe/1','status':'PASS' if all(checks.values()) else 'FAIL','checks':checks,'request_sha256':hashlib.sha256(bytes(frame[:size.value])).hexdigest(),'response_sha256':hashlib.sha256(bytes(result[:copied.value])).hexdigest()}
    (ROOT/'sdk_public_report.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,sort_keys=True));raise SystemExit(report['status']!='PASS')
if __name__=='__main__':main()
