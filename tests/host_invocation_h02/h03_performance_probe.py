#!/usr/bin/env python3
"""H03 PERF-01..04 measurements; records observations without an SLA."""
import ctypes as c, hashlib, json, os, pathlib, statistics, struct, time
ROOT=pathlib.Path(os.environ['OMNI_H03_EVIDENCE_ROOT']); OUT=ROOT/'performance'; OUT.mkdir(exist_ok=True)
LIB=c.CDLL(str(ROOT/'dist/runtime/libomni_invocation_v1.so')); U8,U32,U64,P8=c.c_uint8,c.c_uint32,c.c_uint64,c.POINTER(c.c_uint8)
for n,a in [('omni_invocation_v1_module_open',[P8,U32,P8,P8,c.POINTER(U64)]),('omni_invocation_v1_invocation_create',[U64,P8,U32,P8,U32,U64,U64,U64,U32,U32,P8,c.POINTER(U64)]),('omni_invocation_v1_invoke',[U64,c.POINTER(U32),c.POINTER(U32)]),('omni_invocation_v1_result_read',[U64,P8,U32,c.POINTER(U32)]),('omni_invocation_v1_invocation_destroy',[U64]),('omni_invocation_v1_module_close',[U64])]:f=getattr(LIB,n);f.argtypes=a;f.restype=U32
def arr(x):return(U8*len(x)).from_buffer_copy(x)
def meta(name):
 p=ROOT/'artifacts'/f'{name}.so';return p,json.loads(pathlib.Path(str(p)+'.omireceipt.json').read_text())
def frame(m,p=b''):return b'OMIV1\0\0\0'+struct.pack('<II',1,1)+bytes.fromhex(m['signature_digest'])+struct.pack('<II',len(p),len(m['parameter_type_ids']))+p
def text(x):return bytes([11])+hashlib.sha256(b'omni.type/1\nText').digest()+struct.pack('<I',len(x))+x
def open(p,m):
 h=U64();raw=str(p).encode();s=LIB.omni_invocation_v1_module_open(arr(raw),len(raw),arr(bytes.fromhex(m['artifact_sha256'])),arr(bytes.fromhex(m['descriptor_sha256'])),c.byref(h));return s,h.value
def quantiles(values):return {'samples':len(values),'min_ns':min(values),'median_ns':int(statistics.median(values)),'max_ns':max(values)}
def rss():return int(pathlib.Path('/proc/self/statm').read_text().split()[1])*os.sysconf('SC_PAGE_SIZE')
checks=[]
def check(n,a,e):checks.append({'name':n,'actual':a,'expected':e,'passed':a==e})
zero,zm=meta('zero'); loads=[]
for _ in range(12):
 start=time.perf_counter_ns();s,h=open(zero,zm);loads.append(time.perf_counter_ns()-start);check('load_close', (s,LIB.omni_invocation_v1_module_close(h)),(0,0))
check('PERF-01_measurement',len(loads),12)
cases=[('zero',zm,frame(zm)),('medium',meta('echo_text')[1],frame(meta('echo_text')[1],text(b'x'*4096))),('maximum',meta('echo_text')[1],frame(meta('echo_text')[1],text(b'x'*1048483)))]
latencies={}; baseline=rss(); rss_samples=[]
for label,m,request in cases:
 path=zero if label=='zero' else meta('echo_text')[0];s,h=open(path,m);check(label+'_open',s,0);data=[]
 for _ in range(12):
  inv=U64();created=LIB.omni_invocation_v1_invocation_create(h,arr(request),len(request),None,0,0,time.clock_gettime_ns(time.CLOCK_MONOTONIC)+5_000_000_000,67108864,1048576,0,arr(bytes(16)),c.byref(inv));effect=U32();length=U32();start=time.perf_counter_ns();called=LIB.omni_invocation_v1_invoke(inv,c.byref(effect),c.byref(length));data.append(time.perf_counter_ns()-start);out=(U8*length.value)();copied=U32();read=LIB.omni_invocation_v1_result_read(inv,out,length,c.byref(copied));destroyed=LIB.omni_invocation_v1_invocation_destroy(inv);rss_samples.append(rss());check(label+'_call',(created,called,effect.value,read,destroyed),(0,0,0,0,0))
 latencies[label]=quantiles(data);check(label+'_close',LIB.omni_invocation_v1_module_close(h),0)
check('PERF-02_measurements',sorted(latencies),['maximum','medium','zero']);check('PERF-03_peak_recorded',max(rss_samples)>=baseline,True);check('PERF-04_memory_stability',max(rss_samples)-baseline<=16*1024*1024,True)
report={'schema':'omni.core-host-03-performance/1','checks':checks,'passed':sum(x['passed'] for x in checks),'total':len(checks),'module_load_ns':quantiles(loads),'invocation_ns':latencies,'rss_baseline':baseline,'rss_samples':rss_samples,'kernel':os.uname().release}
(OUT/'report.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps({'passed':report['passed'],'total':report['total']}));raise SystemExit(0 if report['passed']==report['total'] else 1)
