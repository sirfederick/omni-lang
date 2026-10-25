#!/usr/bin/env python3
from __future__ import annotations
import json, os, pathlib, subprocess, tempfile
# Historical filename: sanitizer instrumentation is not inferred from this smoke.
ROOT=pathlib.Path(__file__).resolve().parents[1]
OMNI=pathlib.Path(os.environ['OMNI_TEST_BIN'])
def run(*args,timeout=20): return subprocess.run([str(x) for x in args],capture_output=True,timeout=timeout,env={**os.environ,'OMNI_HOME':str(ROOT)})
checks = {}
with tempfile.TemporaryDirectory(prefix='omni-lang-san-') as td:
    d=pathlib.Path(td)
    surface_commands = 0
    for src in (ROOT/'examples/option.omni',ROOT/'examples/numeric.omni',ROOT/'examples/adt_enum.omni'):
        for cmd in [('check',src),('fmt',src),('wave',src),('manifest',src),('hash',src)]:
            r=run(OMNI,*cmd); assert r.returncode==0,(cmd,r.stderr)
            surface_commands += 1
    checks['compiler_surfaces'] = surface_commands == 15
    wire=d/'adt.owire'; r=run(OMNI,'pack',ROOT/'examples/adt_enum.omni','-o',wire); assert r.returncode==0,r.stderr; assert wire.read_bytes()[:8]==b'OMCX\x12\x00\x00\x00'
    r=run(OMNI,'check',wire); assert r.returncode==0,r.stderr
    checks['wire_roundtrip'] = r.returncode == 0
    bad=d/'bad.omni'; bad.write_text('module t enum E { A, B, } func f(e E) u32 { match e { A { return 1 } } } func main() u32 { return 0 }')
    r=run(OMNI,'check',bad,'--diagnostic-format','json'); assert r.returncode==2; assert json.loads(r.stderr)['code']=='E_MATCH_NON_EXHAUSTIVE'
    checks['nonexhaustive_match_rejected'] = r.returncode == 2
    legacy_checks = 0
    for v in range(1,12):
        assert run(OMNI,'check',ROOT/'reference/compat'/f'legacy{v}.owave').returncode==0
        assert run(OMNI,'check',ROOT/'reference/compat'/f'legacy{v}.owire').returncode==0
        legacy_checks += 2
    checks['legacy_representations'] = legacy_checks == 22
    desc=run(OMNI,'type','describe','i64'); assert desc.returncode==0; d=json.loads(desc.stdout); assert d['schema']=='omni.type-descriptor/2'; assert d['type_identity_domain']=='omni.type/1'; assert 'legacy_descriptor_id' in d
    checks['type_descriptor_contract'] = desc.returncode == 0
print('language compiler smoke: PASS (sanitizer instrumentation not inferred)')
print(json.dumps({'schema': 'omni.language-compiler-smoke/1', 'status': 'PASS', 'checks': checks}))
