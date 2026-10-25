#!/usr/bin/env python3
from __future__ import annotations
import os, pathlib, subprocess, tempfile
ROOT=pathlib.Path(__file__).resolve().parents[1]
OMNI=pathlib.Path(os.environ.get('OMNI_TEST_BIN',ROOT/'bin/linux-x86_64/omni'))

def run(*args,timeout=30):
    return subprocess.run([str(x) for x in args],capture_output=True,timeout=timeout,env={**os.environ,'OMNI_HOME':str(ROOT)})

unsigned=[('u8',250,10),('u16',65000,1000),('u32',4294967200,1000),('u64',18446744073709551500,1000)]
signed=[('i8',120,20,-120,-20),('i16',32000,1000,-32000,-1000),('i32',2147483600,1000,-2147483600,-1000),('i64',9223372036854775700,1000,-9223372036854775700,-1000)]
lines=['module numericdiff','func main() u32 !{io.print} {']
count=0
for t,a,b in unsigned:
    safe=10; sb=3
    for expr in [f'{safe}{t} + {sb}{t}',f'{safe}{t} * {sb}{t}',f'{a}{t} +% {b}{t}',f'{a}{t} +| {b}{t}',f'{sb}{t} -| {safe}{t}',f'{a}{t} > {b}{t}']:
        lines.append(f' print({expr});'); count+=1
for t,pos,b,neg,nb in signed:
    for expr in [f'{pos}{t} +| {b}{t}',f'{pos}{t} +% {b}{t}',f'{neg}{t} -| {b}{t}',f'{neg}{t} +% {nb}{t}',f'{neg}{t} < {pos}{t}',f'{neg}{t} / 3{t}',f'{neg}{t} % 3{t}']:
        lines.append(f' print({expr});'); count+=1
lines += [' return 0','}']
source='\n'.join(lines)+'\n'
with tempfile.TemporaryDirectory(prefix='omni-numeric-diff-') as td:
    d=pathlib.Path(td); src=d/'diff.omni'; src.write_text(source,encoding='utf-8')
    chk=run(OMNI,'check',src); assert chk.returncode==0,chk.stderr
    ev=run(OMNI,'eval',src); assert ev.returncode==0,ev.stderr
    out=d/'diff'; build=run(OMNI,'build',src,'-o',out); assert build.returncode==0,build.stderr
    native=run(out); assert native.returncode==0,native.stderr
    assert ev.stdout==native.stdout,(ev.stdout,native.stdout)
    assert len(ev.stdout.splitlines())==count,(len(ev.stdout.splitlines()),count)
print(f'numeric evaluator/native differential: PASS ({count} observations)')
