#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Federico T. Begna
# SPDX-License-Identifier: MIT OR Apache-2.0
"""Exercise the integrated SDK using real artifacts and an extracted package."""
from __future__ import annotations
import json, os, pathlib, shutil, subprocess, sys
ROOT = pathlib.Path(__file__).resolve().parents[1]

def main():
    out = pathlib.Path(os.environ.get('OMNI_SDK_SMOKE_DIR', ROOT/'build/sdk-smoke')).resolve()
    if out.exists():
        raise SystemExit('Output already exists; retain its evidence and select a fresh OMNI_SDK_SMOKE_DIR')
    out.mkdir(parents=True)
    for directory in ('bin', 'runtime', 'node'):
        (out/'dist'/directory).mkdir(parents=True)
    shutil.copy2(ROOT/'build/dev/omni', out/'dist/bin/omni')
    for p in (ROOT/'build/dev/runtime').iterdir():
        if p.is_file(): shutil.copy2(p, out/'dist/runtime'/p.name)
    for p in (ROOT/'runtime').iterdir():
        if p.is_file(): shutil.copy2(p, out/'dist/runtime'/p.name)
    shutil.copy2(ROOT/'build/dev/node/omni_host_sdk.node', out/'dist/node/omni_host_sdk.node')
    env = dict(os.environ, OMNI_H02_EVIDENCE_ROOT=str(out), OMNI_HOME=str(out/'dist'),
               LD_LIBRARY_PATH=str(out/'dist/runtime'), PYTHONDONTWRITEBYTECODE='1')
    rows = []
    probes = ('sentinel.py', 'build_artifacts.py', 'sdk_public_probe.py',
              'binding_roundtrip_fixture.py', 'node_public_probe.mjs',
              'python_public_probe.py', 'sdk_distribution_probe.py')
    for name in probes:
        command = ['node' if name.endswith('.mjs') else sys.executable,
                   str(ROOT/'tests/host_invocation_h02'/name)]
        p = subprocess.run(command, cwd=out, env=env, capture_output=True, text=True)
        (out/(name+'.log')).write_text(p.stdout+p.stderr, encoding='utf-8')
        rows.append({'probe':name,'exit_code':p.returncode})
        print(json.dumps(rows[-1]), flush=True)
        if p.returncode: break
    status = 'PASS' if len(rows)==len(probes) and all(r['exit_code']==0 for r in rows) else 'FAIL'
    (out/'report.json').write_text(json.dumps({'status':status,'probes':rows},indent=2)+'\n')
    return status!='PASS'

if __name__=='__main__': sys.exit(main())
