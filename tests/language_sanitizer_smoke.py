#!/usr/bin/env python3
from __future__ import annotations
import json, os, pathlib, subprocess, tempfile
ROOT=pathlib.Path(__file__).resolve().parents[1]
OMNI=pathlib.Path(os.environ['OMNI_TEST_BIN'])
def run(*args,timeout=20): return subprocess.run([str(x) for x in args],capture_output=True,timeout=timeout,env={**os.environ,'OMNI_HOME':str(ROOT)})
with tempfile.TemporaryDirectory(prefix='omni-lang-san-') as td:
    d=pathlib.Path(td)
    for src in (ROOT/'examples/option.omni',ROOT/'examples/numeric.omni',ROOT/'examples/adt_enum.omni'):
        for cmd in [('check',src),('fmt',src),('wave',src),('manifest',src),('hash',src)]:
            r=run(OMNI,*cmd); assert r.returncode==0,(cmd,r.stderr)
    wire=d/'adt.owire'; r=run(OMNI,'pack',ROOT/'examples/adt_enum.omni','-o',wire); assert r.returncode==0,r.stderr; assert wire.read_bytes()[:8]==b'OMCX\x12\x00\x00\x00'
    r=run(OMNI,'check',wire); assert r.returncode==0,r.stderr
    bad=d/'bad.omni'; bad.write_text('module t enum E { A, B, } func f(e E) u32 { match e { A { return 1 } } } func main() u32 { return 0 }')
    r=run(OMNI,'check',bad,'--diagnostic-format','json'); assert r.returncode==2; assert json.loads(r.stderr)['code']=='E_MATCH_NON_EXHAUSTIVE'
    for v in range(1,12):
        assert run(OMNI,'check',ROOT/'reference/compat'/f'legacy{v}.owave').returncode==0
        assert run(OMNI,'check',ROOT/'reference/compat'/f'legacy{v}.owire').returncode==0
    desc=run(OMNI,'type','describe','i64'); assert desc.returncode==0; d=json.loads(desc.stdout); assert d['schema']=='omni.type-descriptor/2'; assert d['type_identity_domain']=='omni.type/1'; assert 'legacy_descriptor_id' in d
print('language alpha.8 sanitizer compiler smoke: PASS')
