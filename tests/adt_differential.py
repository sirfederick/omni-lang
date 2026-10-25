#!/usr/bin/env python3
from __future__ import annotations
import json, os, pathlib, subprocess, tempfile
ROOT=pathlib.Path(__file__).resolve().parents[1]
OMNI=pathlib.Path(os.environ.get('OMNI_TEST_BIN',ROOT/'bin/linux-x86_64/omni'))

def run(*args,timeout=30):
    return subprocess.run([str(x) for x in args],capture_output=True,timeout=timeout,env={**os.environ,'OMNI_HOME':str(ROOT)})

calls=[]
for v in [1,2,7,42,200]: calls.append(f'print(score(Signal.Code({v}u8)))')
for v in [1,2,9,123,30000]: calls.append(f'print(score(Signal.Signed({v}i16)))')
for s in ['a','ab','omni','variant','abcdefghij']: calls.append(f'print(score(Signal.Message("{s}")))')
for _ in range(5): calls.append('print(score(Signal.Idle()))')
for v in [3,8,15,31,63]: calls.append(f'print(outer(Envelope.Wrap(Signal.Code({v}u8))))')
for _ in range(5): calls.append('print(outer(Envelope.Empty()))')
source='''module adtdiff
enum Signal { Idle, Code(u8), Signed(i16), Message(Text), }
enum Envelope { Empty, Wrap(Signal), }
func score(s Signal) u32 {
 match s {
  Idle { return 0 }
  Code(v) { return u32(v) }
  Signed(v) { return u32(v) }
  Message(t) { return text.len(t) }
 }
}
func outer(e Envelope) u32 {
 match e {
  Empty { return 99 }
  Wrap(s) { return score(s) }
 }
}
func main() u32 !{io.print} {
'''+''.join(' '+c+';\n' for c in calls)+''' return 0
}
'''
with tempfile.TemporaryDirectory(prefix='omni-adt-diff-') as td:
    d=pathlib.Path(td); src=d/'diff.omni'; src.write_text(source,encoding='utf-8')
    chk=run(OMNI,'check',src); assert chk.returncode==0,chk.stderr
    ev=run(OMNI,'eval',src); assert ev.returncode==0,ev.stderr
    out=d/'diff'; build=run(OMNI,'build',src,'-o',out); assert build.returncode==0,build.stderr
    native=run(out); assert native.returncode==0,native.stderr
    assert ev.stdout==native.stdout,(ev.stdout,native.stdout)
    assert len(ev.stdout.splitlines())==len(calls),(len(ev.stdout.splitlines()),len(calls))
print(f'ADT evaluator/native differential: PASS ({len(calls)} observations)')

# Reached only after the original assertions/comparisons have all succeeded.
print(json.dumps({"schema": 'omni.adt-differential/1', "status": "PASS",
                  "observations": len(calls), "checks": {
    'semantic_check': chk.returncode == 0,
    'evaluator_execution': ev.returncode == 0,
    'native_build': build.returncode == 0,
    'native_execution': native.returncode == 0,
    'evaluator_native_output': ev.stdout == native.stdout,
    'observation_count': len(ev.stdout.splitlines()) == len(calls) and len(calls) > 0,
}}))
