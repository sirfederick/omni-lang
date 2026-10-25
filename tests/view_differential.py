#!/usr/bin/env python3
from __future__ import annotations
import json, os, pathlib, subprocess, tempfile
ROOT=pathlib.Path(__file__).resolve().parents[1]
OMNI=pathlib.Path(os.environ.get('OMNI_TEST_BIN',ROOT/'bin/linux-x86_64/omni'))
def run(*args,timeout=30): return subprocess.run([str(x) for x in args],capture_output=True,timeout=timeout,env={**os.environ,'OMNI_HOME':str(ROOT)})
lines=['module viewdiff','func main() u32 !{io.print} {']; count=0
for i in range(12):
    base=i*10
    lines += [
      f' let a{i}=array({base+1}u32,{base+2}u32,{base+3}u32,{base+4}u32,{base+5}u32);',
      f' let v{i}=view(a{i});',
      f' let s{i}=view.sub(v{i},1u32,3u32);',
      f' print(view.len(v{i}));',
      f' print(view.len(s{i}));',
      f' print(view.get(s{i},0u32));',
      f' print(view.get(s{i},2u32));'
    ]; count += 4
lines += [' return 0','}']
source='\n'.join(lines)+'\n'
with tempfile.TemporaryDirectory(prefix='omni-view-diff-') as td:
    d=pathlib.Path(td); src=d/'diff.omni'; src.write_text(source,encoding='utf-8')
    chk=run(OMNI,'check',src); assert chk.returncode==0,chk.stderr
    ev=run(OMNI,'eval',src); assert ev.returncode==0,ev.stderr
    out=d/'diff'; build=run(OMNI,'build',src,'-o',out,'--no-cache'); assert build.returncode==0,build.stderr
    native=run(out); assert native.returncode==0,native.stderr
    assert ev.stdout==native.stdout,(ev.stdout,native.stdout)
    assert len(ev.stdout.splitlines())==count,(len(ev.stdout.splitlines()),count)
print(f'view evaluator/native differential: PASS ({count} observations)')

# Reached only after the original assertions/comparisons have all succeeded.
print(json.dumps({"schema": 'omni.view-differential/1', "status": "PASS",
                  "observations": count, "checks": {
    'semantic_check': chk.returncode == 0,
    'evaluator_execution': ev.returncode == 0,
    'native_build': build.returncode == 0,
    'native_execution': native.returncode == 0,
    'evaluator_native_output': ev.stdout == native.stdout,
    'observation_count': len(ev.stdout.splitlines()) == count and count > 0,
}}))
