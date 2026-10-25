#!/usr/bin/env python3
"""H03 EFF-04/EFF-05: real grant-bound effect and sticky uncertainty."""
import ctypes as c, hashlib, json, os, pathlib, struct, subprocess, time
ROOT=pathlib.Path(os.environ['OMNI_H03_EVIDENCE_ROOT']); OUT=ROOT/'effects'; OUT.mkdir(exist_ok=True)
LIB=c.CDLL(str(ROOT/'dist/runtime/libomni_invocation_v1.so')); U8,U32,U64,P8=c.c_uint8,c.c_uint32,c.c_uint64,c.POINTER(c.c_uint8)
for n,a in [('omni_invocation_v1_module_open',[P8,U32,P8,P8,c.POINTER(U64)]),('omni_invocation_v1_invocation_create',[U64,P8,U32,P8,U32,U64,U64,U64,U32,U32,P8,c.POINTER(U64)]),('omni_invocation_v1_invoke',[U64,c.POINTER(U32),c.POINTER(U32)]),('omni_invocation_v1_result_read',[U64,P8,U32,c.POINTER(U32)]),('omni_invocation_v1_invocation_destroy',[U64]),('omni_invocation_v1_module_close',[U64])]:f=getattr(LIB,n);f.argtypes=a;f.restype=U32
def arr(x):return(U8*len(x)).from_buffer_copy(x)
def value_text(x):return bytes([11])+hashlib.sha256(b'omni.type/1\nText').digest()+struct.pack('<I',len(x))+x
path=ROOT/'artifacts/process_effect.so'; meta=json.loads(pathlib.Path(str(path)+'.omireceipt.json').read_text())
source=OUT/'adapter.c'; source.write_text('''#include <stdint.h>\n#include <stdlib.h>\n#include <string.h>\n#include <unistd.h>\nstatic unsigned get(const unsigned char*p){return p[0]|p[1]<<8|p[2]<<16|p[3]<<24;}static void put(unsigned char*p,unsigned x){p[0]=x;p[1]=x>>8;p[2]=x>>16;p[3]=x>>24;}int main(int n,char**v){if(n>1&&strcmp(v[1],"--fail")==0)return 1;unsigned char h[20],o[20];if(read(0,h,20)!=20)return 2;unsigned z=get(h+8);unsigned char*id=malloc(z);if(!id||read(0,id,z)!=(int)z)return 3;memcpy(o,"OMNIHR1\\0",8);put(o+8,z);put(o+12,0);put(o+16,2);if(write(1,o,20)!=20||write(1,id,z)!=(int)z||write(1,"ok",2)!=2)return 4;free(id);return 0;}\n''')
good=OUT/'adapter'; bad=OUT/'adapter-fail'; subprocess.run(['clang',str(source),'-O2','-o',str(good)],check=True); shutil=__import__('shutil');shutil.copy2(good,bad)
# failure adapter is a small wrapper whose basename selects deliberate exit.
bad.unlink(); bad.write_text('#!/bin/sh\nexit 1\n'); bad.chmod(0o700)
def run(adapter):
 h=U64();raw=str(path).encode();opened=LIB.omni_invocation_v1_module_open(arr(raw),len(raw),arr(bytes.fromhex(meta['artifact_sha256'])),arr(bytes.fromhex(meta['descriptor_sha256'])),c.byref(h)); text=str(adapter).encode();payload=value_text(text);request=b'OMIV1\0\0\0'+struct.pack('<II',1,1)+bytes.fromhex(meta['signature_digest'])+struct.pack('<II',len(payload),1)+payload; policy=(f'OHP1\ngeneration|1\nnot_after_tick|100000\ngrant|process.spawn|{adapter}|64\n').encode();i=U64();created=LIB.omni_invocation_v1_invocation_create(h,arr(request),len(request),arr(policy),len(policy),1,time.clock_gettime_ns(time.CLOCK_MONOTONIC)+5_000_000_000,67108864,1048576,0,arr(bytes(16)),c.byref(i));e,l=U32(),U32();status=LIB.omni_invocation_v1_invoke(i,c.byref(e),c.byref(l)) if created==0 else created;out=(U8*l.value)();copied=U32();read=LIB.omni_invocation_v1_result_read(i,out,l.value,c.byref(copied)) if status==0 else status;value=struct.unpack_from('<I',bytes(out),89)[0] if read==0 else None;destroyed=LIB.omni_invocation_v1_invocation_destroy(i) if created==0 else created;closed=LIB.omni_invocation_v1_module_close(h);return(created,status,e.value,read,value,destroyed,closed)
rows=[]
def check(case,actual,expected):rows.append({'case_id':case,'actual':actual,'expected':expected,'passed':actual==expected})
check('EFF-04',run(good),(0,0,1,0,2,0,0))
check('EFF-05',run(bad),(0,0,2,0,9,0,0))
report={'schema':'omni.core-host-03-effects/1','checks':rows,'passed':sum(x['passed'] for x in rows),'total':len(rows)};(OUT/'report.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps({'passed':report['passed'],'total':report['total']}));raise SystemExit(0 if report['passed']==report['total'] else 1)
