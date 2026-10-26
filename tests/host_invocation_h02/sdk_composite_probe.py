#!/usr/bin/env python3
"""Descriptor-bound public SDK roundtrips for real composite host entries."""
from __future__ import annotations
import ctypes as c
import json, os, time
from pathlib import Path

ROOT=Path(os.environ['OMNI_H02_EVIDENCE_ROOT']);LIB=c.CDLL(str(ROOT/'dist/runtime/libomni_invocation_v1.so'))
U8,U32,U64,P8=c.c_uint8,c.c_uint32,c.c_uint64,c.POINTER(c.c_uint8)
def fn(name,args): f=getattr(LIB,name);f.argtypes=args;f.restype=U32;return f
open_sdk=fn('omni_host_sdk_v1_module_open',[P8,U32,P8,P8,c.POINTER(U64)]);close_sdk=fn('omni_host_sdk_v1_module_close',[U64]);req_node=fn('omni_host_sdk_v1_module_request_node',[U64,U32,c.POINTER(U32)])
kind=fn('omni_host_sdk_v1_schema_node_kind',[U64,U32,c.POINTER(U32)]);scount=fn('omni_host_sdk_v1_schema_node_child_count',[U64,U32,c.POINTER(U32)]);schild=fn('omni_host_sdk_v1_schema_node_child',[U64,U32,U32,c.POINTER(U32)])
make=fn('omni_host_sdk_v1_value_create',[U64,U32,c.POINTER(U64)]);drop=fn('omni_host_sdk_v1_value_destroy',[U64]);set_scalar=fn('omni_host_sdk_v1_value_scalar_set',[U64,U64]);set_data=fn('omni_host_sdk_v1_value_data_set',[U64,P8,U32]);set_disc=fn('omni_host_sdk_v1_value_discriminant_set',[U64,U32]);vcount=fn('omni_host_sdk_v1_value_child_count',[U64,c.POINTER(U32)]);set_child=fn('omni_host_sdk_v1_value_child_set',[U64,U32,U64]);encode=fn('omni_host_sdk_v1_request_encode',[U64,c.POINTER(U64),U32,P8,U32,c.POINTER(U32)]);decode=fn('omni_host_sdk_v1_result_decode',[U64,P8,U32,c.POINTER(U64)])
raw_open=fn('omni_invocation_v1_module_open',[P8,U32,P8,P8,c.POINTER(U64)]);create=fn('omni_invocation_v1_invocation_create',[U64,P8,U32,P8,U32,U64,U64,U64,U32,U32,P8,c.POINTER(U64)]);invoke=fn('omni_invocation_v1_invoke',[U64,c.POINTER(U32),c.POINTER(U32)]);read=fn('omni_invocation_v1_result_read',[U64,P8,U32,c.POINTER(U32)]);destroy=fn('omni_invocation_v1_invocation_destroy',[U64]);raw_close=fn('omni_invocation_v1_module_close',[U64])
def arr(b): return (U8*len(b)).from_buffer_copy(b) if b else None
def opened(path):
 r=json.loads(Path(str(path)+'.omireceipt.json').read_text());p=str(path).encode();m=U64();assert open_sdk(arr(p),len(p),arr(bytes.fromhex(r['artifact_sha256'])),arr(bytes.fromhex(r['descriptor_sha256'])),c.byref(m))==0;return m,r,p
def build(m,node,owned,alternate=False):
 k=U32();assert kind(m,node,c.byref(k))==0;v=U64();assert make(m,node,c.byref(v))==0;owned.append(v)
 if k.value<=10: assert set_scalar(v,0x1f642 if k.value==10 else 1)==0
 elif k.value in (11,12):
  data='Ω'.encode() if k.value==11 else b'\0\xffx';assert set_data(v,arr(data),len(data))==0
 elif k.value in (16,17,18):
  n=U32();assert scount(m,node,c.byref(n))==0;choice=0 if alternate else (1 if k.value==16 and n.value>1 else (1 if k.value==17 else 0));assert set_disc(v,choice)==0
 n=U32();assert vcount(v,c.byref(n))==0
 for i in range(n.value):
  child=U32();base=0 if k.value==14 else (choice if k.value==16 else i);assert schild(m,node,base,c.byref(child))==0
  cv=build(m,child.value,owned,alternate);assert set_child(v,i,cv)==0
 return v
def one(name,alternate=False):
 path=ROOT/f'artifacts/{name}.so';m,meta,p=opened(path);root=U32();assert req_node(m,0,c.byref(root))==0;owned=[];arg=build(m,root.value,owned,alternate);args=(U64*1)(arg.value);need=U32();assert encode(m,args,1,None,0,c.byref(need))==6;request=(U8*need.value)();assert encode(m,args,1,request,need.value,c.byref(need))==0
 raw=U64();assert raw_open(arr(p),len(p),arr(bytes.fromhex(meta['artifact_sha256'])),arr(bytes.fromhex(meta['descriptor_sha256'])),c.byref(raw))==0;inv=U64();trace=(U8*16)();assert create(raw,request,need.value,None,0,0,time.monotonic_ns()+5_000_000_000,1_000_000,65536,0,trace,c.byref(inv))==0;eff=U32();length=U32();assert invoke(inv,c.byref(eff),c.byref(length))==0;frame=(U8*length.value)();copied=U32();assert read(inv,frame,length.value,c.byref(copied))==0;out=U64();assert decode(m,frame,copied.value,c.byref(out))==0;owned.append(out)
 # Echo entries have identical request/result types. Re-encode the returned
 # value using the public SDK and compare canonical requests, without parsing
 # or reconstructing OMI1 in this consumer.
 returned=(U64*1)(out.value);roundtrip=(U8*need.value)();assert encode(m,returned,1,roundtrip,need.value,c.byref(copied))==0;assert copied.value==need.value and bytes(roundtrip)==bytes(request)
 for x in reversed(owned): assert drop(x)==0
 assert destroy(inv)==0 and raw_close(raw)==0 and close_sdk(m)==0
def main():
 names=(('echo_bool',False),('echo_char',False),('echo_text',False),('echo_bytes',False),('echo_tuple',False),('echo_array',False),('echo_pair',False),('echo_choice',False),('echo_choice',True),('echo_option',False),('echo_option',True),('echo_result',False),('echo_result',True),('echo_nested',False),('echo_box',False),('echo_box_nested',False),('echo_generic_choice',False),('echo_generic_choice',True))
 checks={f'{name}_{"alternate" if alternate else "primary"}':True for name,alternate in names};errors={}
 for name,alternate in names:
  key=f'{name}_{"alternate" if alternate else "primary"}'
  try: one(name,alternate)
  except Exception as error: checks[key]=False;errors[key]=repr(error)
 report={'schema':'omni.host-sdk-composite-probe/1','status':'PASS' if all(checks.values()) else 'FAIL','checks':checks,'errors':errors}
 (ROOT/'sdk_composite_report.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,sort_keys=True));raise SystemExit(report['status']!='PASS')
if __name__=='__main__':main()
