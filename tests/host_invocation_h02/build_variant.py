#!/usr/bin/env python3
import hashlib
import json
import os
import pathlib
import subprocess

ROOT = pathlib.Path(os.environ['OMNI_H02_EVIDENCE_ROOT'])
DIST = ROOT / 'dist'
PACKAGE = ROOT / 'fixture'
ARTIFACTS = ROOT / 'artifacts-v2'
NAMES = ('maybe_fail','read_effect','write_denied')
env = os.environ.copy()
env['OMNI_HOME'] = str(DIST)
env['LD_LIBRARY_PATH'] = str(DIST/'runtime')
results = []
for name in NAMES:
    artifact = ARTIFACTS/f'{name}.so'
    command = [str(DIST/'bin/omni'),'build',str(PACKAGE),'--host-entry',
               f'src/host.omni:{name}','-o',str(artifact),'--offline']
    p = subprocess.run(command,env=env,capture_output=True,text=True)
    record = {'entry':name,'command':command,'exit_code':p.returncode,
              'output_sha256':hashlib.sha256((p.stdout+p.stderr).encode()).hexdigest()}
    if p.returncode:
        record['output_tail']=(p.stdout+p.stderr)[-1000:]
    else:
        receipt = json.loads(pathlib.Path(str(artifact)+'.omireceipt.json').read_text())
        record['artifact_sha256']=hashlib.sha256(artifact.read_bytes()).hexdigest()
        record['descriptor_sha256']=receipt['descriptor_sha256']
        record['receipt_sha256']=hashlib.sha256(pathlib.Path(str(artifact)+'.omireceipt.json').read_bytes()).hexdigest()
    results.append(record)
    if p.returncode: break
report={'schema':'omni.h02-development-artifacts/1','results':results,
        'passed':sum(item['exit_code']==0 for item in results),'total':len(NAMES)}
(ROOT/'artifact_build_report.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps({'passed':report['passed'],'total':report['total'],
                  'failure':results[-1] if results[-1]['exit_code'] else None}))
raise SystemExit(0 if report['passed']==report['total'] else 1)
