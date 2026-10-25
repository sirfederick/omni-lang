#!/usr/bin/env python3
"""H03 EMB-02: installed artefact and loader work from a relocated package."""
import hashlib
import json
import os
import pathlib
import shutil
import subprocess
import sys

ROOT = pathlib.Path(os.environ['OMNI_H03_EVIDENCE_ROOT'])
OUT = ROOT / 'relocation'
PKG = OUT / 'installed'
if OUT.exists():
    shutil.rmtree(OUT)
(PKG / 'runtime').mkdir(parents=True)
(PKG / 'artifacts').mkdir()
for name in ('libomni_invocation_v1.so', 'omni_invocation_build_id.txt'):
    shutil.copy2(ROOT / 'dist/runtime' / name, PKG / 'runtime' / name)
for suffix in ('', '.omireceipt.json'):
    shutil.copy2(str(ROOT / 'artifacts/echo.so') + suffix,
                 str(PKG / 'artifacts/echo.so') + suffix)
driver = PKG / 'embedded_host.py'
driver.write_text('''import ctypes as c, hashlib, json, pathlib, struct, time
root=pathlib.Path.cwd(); lib=c.CDLL(str(root/'runtime/libomni_invocation_v1.so'))
u8,u32,u64,p8=c.c_uint8,c.c_uint32,c.c_uint64,c.POINTER(c.c_uint8)
for n,a in [("omni_invocation_v1_module_open",[p8,u32,p8,p8,c.POINTER(u64)]),("omni_invocation_v1_invocation_create",[u64,p8,u32,p8,u32,u64,u64,u64,u32,u32,p8,c.POINTER(u64)]),("omni_invocation_v1_invoke",[u64,c.POINTER(u32),c.POINTER(u32)]),("omni_invocation_v1_result_read",[u64,p8,u32,c.POINTER(u32)]),("omni_invocation_v1_invocation_destroy",[u64]),("omni_invocation_v1_module_close",[u64])]:
 f=getattr(lib,n); f.argtypes=a; f.restype=u32
def a(x): return (u8*len(x)).from_buffer_copy(x)
p=root/'artifacts/echo.so'; m=json.loads(pathlib.Path(str(p)+'.omireceipt.json').read_text()); h=u64()
assert lib.omni_invocation_v1_module_open(a(str(p).encode()),len(str(p).encode()),a(bytes.fromhex(m['artifact_sha256'])),a(bytes.fromhex(m['descriptor_sha256'])),c.byref(h))==0
tid=hashlib.sha256(b'omni.type/1\\nu32').digest()
for x in (7,99):
 v=bytes([4])+tid+struct.pack('<I',x); r=b'OMIV1\\0\\0\\0'+struct.pack('<II',1,1)+bytes.fromhex(m['signature_digest'])+struct.pack('<II',len(v),1)+v; i=u64()
 assert lib.omni_invocation_v1_invocation_create(h,a(r),len(r),None,0,0,time.clock_gettime_ns(time.CLOCK_MONOTONIC)+5000000000,67108864,1048576,0,a(bytes(16)),c.byref(i))==0
 e,l=u32(),u32(); assert lib.omni_invocation_v1_invoke(i,c.byref(e),c.byref(l))==0 and e.value==0; o=(u8*l.value)(); q=u32(); assert lib.omni_invocation_v1_result_read(i,o,l.value,c.byref(q))==0 and struct.unpack_from('<I',bytes(o),89)[0]==x; assert lib.omni_invocation_v1_invocation_destroy(i)==0
assert lib.omni_invocation_v1_module_close(h)==0; print('RELOCATED_EMBEDDING_PASS calls=2')
''')
env = {'PATH': '/usr/bin:/bin', 'LD_LIBRARY_PATH': str(PKG / 'runtime'),
       'LANG': 'C', 'HOME': str(PKG / 'home')}
run = subprocess.run([sys.executable, str(driver)], cwd=PKG, env=env,
                     capture_output=True, text=True)
report = {'schema': 'omni.core-host-03-relocation/1', 'exit_code': run.returncode,
          'stdout_sha256': hashlib.sha256(run.stdout.encode()).hexdigest(),
          'stderr_sha256': hashlib.sha256(run.stderr.encode()).hexdigest(),
          'source_checkout_in_package': (PKG / 'core').exists(),
          'compiler_in_package': (PKG / 'bin/omni').exists(),
          'passed': run.returncode == 0 and 'RELOCATED_EMBEDDING_PASS calls=2' in run.stdout
                    and not (PKG / 'core').exists() and not (PKG / 'bin/omni').exists()}
(OUT / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
print(json.dumps({'passed': report['passed'], 'exit_code': run.returncode}))
raise SystemExit(0 if report['passed'] else 1)
