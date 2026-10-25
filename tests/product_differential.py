#!/usr/bin/env python3
from __future__ import annotations
import json, os, pathlib, subprocess, tempfile
ROOT=pathlib.Path(__file__).resolve().parents[1]
OMNI=pathlib.Path(os.environ.get('OMNI_TEST_BIN',ROOT/'bin/linux-x86_64/omni'))

def run(*args,timeout=30):
    return subprocess.run([str(x) for x in args],capture_output=True,timeout=timeout,env={**os.environ,'OMNI_HOME':str(ROOT)})

lines=['module productdiff','func main() u32 !{io.print} {']
count=0
# Tuples: heterogeneous construction/projection.
for i in range(10):
    b='true' if i%2 else 'false'
    lines += [f' let t{i}=tuple({i}u8,{b},{i*100+7}u32);',f' print(tuple.get(t{i},0u32));',f' print(tuple.get(t{i},1u32));',f' print(tuple.get(t{i},2u32));']
    count += 3
# Arrays: dynamic index + copy update. 4 observations per case.
for i in range(5):
    base=i*10
    lines += [
      f' let a{i}=array({base+1}u32,{base+2}u32,{base+3}u32,{base+4}u32);',
      f' let j{i} u32={i%4}u32;',
      f' let b{i}=array.with(a{i},j{i},{900+i}u32);',
      f' print(array.len(a{i}));',
      f' print(array.get(a{i},j{i}));',
      f' print(array.get(b{i},j{i}));',
      f' print(array.get(b{i},3u32));'
    ]
    count += 4
# Nested products.
lines += [
 ' let inner=tuple(11u16,22u16);',
 ' let outer=tuple(inner,array(5u8,6u8,7u8));',
 ' let inner2=tuple.get(outer,0u32);',
 ' let arr2=tuple.get(outer,1u32);',
 ' print(tuple.get(inner2,1u32));',
 ' print(array.get(arr2,2u32));',
 ' let aa=array(array(1u8,2u8),array(3u8,4u8));',
 ' let row=array.get(aa,1u32);',
 ' print(array.get(row,0u32));',
 ' print(array.get(row,1u32));'
]
count += 4
lines += [' return 0','}']
source='\n'.join(lines)+'\n'
with tempfile.TemporaryDirectory(prefix='omni-product-diff-') as td:
    d=pathlib.Path(td); src=d/'diff.omni'; src.write_text(source,encoding='utf-8')
    chk=run(OMNI,'check',src); assert chk.returncode==0,chk.stderr
    ev=run(OMNI,'eval',src); assert ev.returncode==0,ev.stderr
    out=d/'diff'; build=run(OMNI,'build',src,'-o',out); assert build.returncode==0,build.stderr
    native=run(out); assert native.returncode==0,native.stderr
    assert ev.stdout==native.stdout,(ev.stdout,native.stdout)
    assert len(ev.stdout.splitlines())==count,(len(ev.stdout.splitlines()),count)
print(f'product evaluator/native differential: PASS ({count} observations)')

# Reached only after the original assertions/comparisons have all succeeded.
print(json.dumps({"schema": 'omni.product-differential/1', "status": "PASS",
                  "observations": count, "checks": {
    'semantic_check': chk.returncode == 0,
    'evaluator_execution': ev.returncode == 0,
    'native_build': build.returncode == 0,
    'native_execution': native.returncode == 0,
    'evaluator_native_output': ev.stdout == native.stdout,
    'observation_count': len(ev.stdout.splitlines()) == count and count > 0,
}}))
