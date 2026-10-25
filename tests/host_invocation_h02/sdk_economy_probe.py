#!/usr/bin/env python3
"""Bounded same-host comparison probe for the public C SDK hot path."""
from __future__ import annotations
import ctypes as c
import hashlib, json, os, platform, resource, statistics, time
from pathlib import Path
from sdk_composite_probe import (ROOT,U8,U32,U64,arr,opened,req_node,build,
    encode,raw_open,create,invoke,read,decode,drop,destroy,raw_close,close_sdk)

ITERATIONS=int(os.environ.get('OMNI_SDK_ECONOMY_ITERATIONS','2000'))
WARMUP=int(os.environ.get('OMNI_SDK_ECONOMY_WARMUP','200'))

def percentile(values,ratio):
    return values[min(len(values)-1,int((len(values)-1)*ratio))]

def latency(samples):
    samples.sort()
    return {
        'p50_ns': percentile(samples,.50),
        'p95_ns': percentile(samples,.95),
        'p99_ns': percentile(samples,.99),
        'mean_ns': round(statistics.fmean(samples),2),
    }

def probe(name):
    path=ROOT/f'artifacts/{name}.so';module,meta,path_bytes=opened(path);root=U32();assert req_node(module,0,c.byref(root))==0
    owned=[];argument=build(module,root.value,owned);arguments=(U64*1)(argument.value);length=U32();assert encode(module,arguments,1,None,0,c.byref(length))==6
    request=(U8*length.value)();assert encode(module,arguments,1,request,length.value,c.byref(length))==0
    raw=U64();assert raw_open(arr(path_bytes),len(path_bytes),arr(bytes.fromhex(meta['artifact_sha256'])),arr(bytes.fromhex(meta['descriptor_sha256'])),c.byref(raw))==0
    invocation=U64();trace=(U8*16)();assert create(raw,request,length.value,None,0,0,time.monotonic_ns()+5_000_000_000,1_000_000,65536,0,trace,c.byref(invocation))==0
    effect=U32();result_length=U32();assert invoke(invocation,c.byref(effect),c.byref(result_length))==0;result=(U8*result_length.value)();copied=U32();assert read(invocation,result,result_length.value,c.byref(copied))==0
    for _ in range(WARMUP):
        assert encode(module,arguments,1,request,len(request),c.byref(length))==0;decoded=U64();assert decode(module,result,copied.value,c.byref(decoded))==0;assert drop(decoded)==0
    encode_samples=[];decode_samples=[];total_started=time.perf_counter_ns();rss_before=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    for _ in range(ITERATIONS):
        started=time.perf_counter_ns();assert encode(module,arguments,1,request,len(request),c.byref(length))==0;encode_samples.append(time.perf_counter_ns()-started)
        decoded=U64();started=time.perf_counter_ns();assert decode(module,result,copied.value,c.byref(decoded))==0;assert drop(decoded)==0;decode_samples.append(time.perf_counter_ns()-started)
    total_elapsed_ns=time.perf_counter_ns()-total_started
    rss_after=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    for item in reversed(owned):assert drop(item)==0
    assert destroy(invocation)==0 and raw_close(raw)==0 and close_sdk(module)==0
    return {
        'fixture':name,
        'payload_request_bytes':len(request),
        'payload_result_bytes':copied.value,
        'iterations':ITERATIONS,
        'warmup':WARMUP,
        'encode_latency':latency(encode_samples),
        'decode_latency':latency(decode_samples),
        'roundtrip_throughput_per_second':round(ITERATIONS*1_000_000_000/total_elapsed_ns,2),
        'rss_delta_kib':rss_after-rss_before,
    }
def main():
    rows=[probe('echo'),probe('echo_choice'),probe('echo_nested')]
    report={
        'schema':'omni.host-sdk-economy/1',
        'source_sha':os.environ.get('OMNI_SDK_SOURCE_SHA','UNKNOWN'),
        'hot_path_json':False,
        'extra_process_hop':False,
        'thread_counts':[1],
        'concurrency_status':'OUT_OF_SCOPE_FOR_THREAD_CONFINED_HOST_SDK_V1',
        'host':platform.platform(),
        'runtime_library_sha256':hashlib.sha256((ROOT/'dist/runtime/libomni_invocation_v1.so').read_bytes()).hexdigest(),
        'fixtures':rows,
    }
    report_path=Path(os.environ.get('OMNI_SDK_ECONOMY_REPORT_PATH',ROOT/'sdk_economy_report.json'))
    report_path.write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,sort_keys=True))
if __name__=='__main__':main()
