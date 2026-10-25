#!/usr/bin/env python3
from __future__ import annotations
import json, os, pathlib, subprocess, tempfile
ROOT=pathlib.Path(__file__).resolve().parents[1]
OMNI=pathlib.Path(os.environ.get('OMNI_TEST_BIN',ROOT/'bin/linux-x86_64/omni'))
def run(*a): return subprocess.run([str(x) for x in a],capture_output=True,env={**os.environ,'OMNI_HOME':str(ROOT)},timeout=45)
cases=[]
for ty,suffix in [('u8','u8'),('u16','u16'),('u32','u32'),('u64','u64'),('i8','i8'),('i16','i16'),('i32','i32'),('i64','i64')]:
    # Keep exits <=255 for native process status equality.
    cases.append(f'module t func add<T:Integer>(a T,b T) T {{ return a+b }} func main() u32 {{ let x {ty}=add<{ty}>(20{suffix},22{suffix}); return u32(x) }}')
cases += [
'module t func add<T:Integer>(a T,b T) T { return a+b } func main() u32 { let a u32=40u32; return a::add<u32>(2u32) }',
'module t func main() u32 { let a=array(10u32,12u32,20u32); var s u32=0u32; for x in a { s=s+x; } return s }',
'module t func main() u32 { let a=array(10u32,12u32,20u32); let v=view(a); var s u32=0u32; for x in v { s=s+x; } return s }',
]
obs=0
with tempfile.TemporaryDirectory(prefix='omni-alpha6-diff-') as td:
    d=pathlib.Path(td)
    for i,src in enumerate(cases):
        p=d/f'c{i}.omni'; p.write_text(src); e=run(OMNI,'eval',p); out=d/f'c{i}'; b=run(OMNI,'build',p,'-o',out,'--no-cache')
        if b.returncode!=0: raise SystemExit(f'build case {i} failed: {b.stderr.decode()}')
        n=run(out)
        if (e.returncode,e.stdout)!=(n.returncode,n.stdout): raise SystemExit(f'differential case {i}: eval={(e.returncode,e.stdout)!r} native={(n.returncode,n.stdout)!r} evalerr={e.stderr!r} nativeerr={n.stderr!r}')
        obs+=1
print(f'alpha6 abstraction differential: {obs}/{len(cases)} MATCH')

# Reached only after the original assertions/comparisons have all succeeded.
print(json.dumps({"schema": 'omni.abstraction-differential/1', "status": "PASS",
                  "observations": obs, "checks": {
    'all_evaluator_native_cases': obs == len(cases) and obs > 0,
}}))
