#!/usr/bin/env python3
"""Invoke Node-produced opaque request frames with the real runtime."""
from __future__ import annotations
import ctypes as c
import hashlib
import json
import os
import time
from pathlib import Path
from sdk_composite_probe import U8, U32, U64, arr, create, destroy, invoke, raw_close, raw_open, read

ROOT=Path(os.environ['OMNI_H02_EVIDENCE_ROOT']); FRAMES=ROOT/'node_structural_frames'
ENCODE=json.loads((ROOT/'node_structural_encode.json').read_text())
def main():
    rows=[]
    for fixture in ENCODE['fixtures']:
        name,alternate=fixture['fixture'],fixture['alternate']; key=f"{name}-{'alternate' if alternate else 'primary'}"
        artifact=ROOT/f'artifacts/{name}.so'; receipt=json.loads(Path(f'{artifact}.omireceipt.json').read_text()); request=(FRAMES/f'{key}.request.omi1').read_bytes()
        path=str(artifact).encode(); module=U64(); invocation=None
        try:
            assert raw_open(arr(path),len(path),arr(bytes.fromhex(receipt['artifact_sha256'])),arr(bytes.fromhex(receipt['descriptor_sha256'])),c.byref(module)) == 0
            trace=(U8*16)(); out=U64(); assert create(module.value,arr(request),len(request),None,0,0,time.monotonic_ns()+5_000_000_000,1_000_000,65_536,0,trace,c.byref(out)) == 0; invocation=out.value
            effect,length=U32(),U32(); assert invoke(invocation,c.byref(effect),c.byref(length)) == 0
            frame=(U8*length.value)(); copied=U32(); assert read(invocation,frame,length.value,c.byref(copied)) == 0
            response=bytes(frame[:copied.value]); (FRAMES/f'{key}.result.omi1').write_bytes(response)
            rows.append({'fixture':name,'alternate':alternate,'request_sha256':hashlib.sha256(request).hexdigest(),'response_sha256':hashlib.sha256(response).hexdigest(),'result_bytes':len(response),'real_runtime_exercised':True})
        finally:
            if invocation is not None: assert destroy(invocation) == 0
            assert raw_close(module.value) == 0
    report={'schema':'omni.host-sdk-node-structural-runtime/1','status':'PASS','fixtures':rows,'real_runtime_exercised':True}
    (ROOT/'node_structural_runtime.json').write_text(json.dumps(report,indent=2)+'\n'); print(json.dumps({'status':'PASS','fixtures':len(rows)}))
if __name__ == '__main__': main()
