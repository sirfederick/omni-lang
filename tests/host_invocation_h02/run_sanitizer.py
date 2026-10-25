#!/usr/bin/env python3
"""ASan/UBSan repeated native embedding check for the H02 loader/runtime."""
import argparse
import hashlib
import json
import os
import pathlib
import shutil
import subprocess
import sys

HERE=pathlib.Path(__file__).resolve().parent
CORE=HERE.parents[1]

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--evidence-root',type=pathlib.Path,required=True)
    args=parser.parse_args()
    parent=args.evidence_root.resolve()
    if not (parent/'dist/bin/omni').is_file() or not (parent/'fixture').is_dir():
        parser.error('run H02 build/fixture first')
    root=parent/'sanitizer'
    if root.exists():
        parser.error('sanitizer evidence destination already exists')
    (root/'dist/bin').mkdir(parents=True)
    (root/'dist/runtime').mkdir(parents=True)
    (root/'artifacts').mkdir()
    compiler=root/'dist/bin/omni'
    shutil.copy2(parent/'dist/bin/omni',compiler)
    for name in ('omni_invocation_v1.h','omni_invocation_internal.h'):
        shutil.copy2(CORE/'runtime'/name,root/'dist/runtime'/name)
    library=root/'dist/runtime/libomni_invocation_v1.so'
    zero_artifact=root/'artifacts/zero.so'
    echo_artifact=root/'artifacts/echo.so'
    spin_artifact=root/'artifacts/spin.so'
    host=root/'sanitizer_host'
    env=os.environ.copy()
    env.update({'OMNI_HOME':str(root/'dist'),
                'LD_LIBRARY_PATH':str(root/'dist/runtime'),
                'ASAN_OPTIONS':'detect_leaks=1:halt_on_error=1',
                'UBSAN_OPTIONS':'halt_on_error=1'})
    records=[]
    def run(command):
        process=subprocess.run(command,env=env,capture_output=True)
        index=len(records)
        stdout=root/f'{index:02d}.stdout';stderr=root/f'{index:02d}.stderr'
        stdout.write_bytes(process.stdout);stderr.write_bytes(process.stderr)
        records.append({'command':command,'exit_code':process.returncode,
                        'stdout_sha256':sha(stdout),'stderr_sha256':sha(stderr)})
        if process.returncode:
            print(process.stderr.decode(errors='replace')[-2000:],file=sys.stderr)
            raise RuntimeError(f'sanitizer command {index} failed')
        return process.stdout.decode(errors='replace')
    outcome='INCOMPLETE'
    try:
        run(['python3',str(CORE/'tools/build_invocation_loader.py'),
             '--output',str(library),'--jobs','4','--sanitizers'])
        for entry, artifact in (('zero',zero_artifact),('echo',echo_artifact),
                                ('spin',spin_artifact)):
            run([str(compiler),'build',str(parent/'fixture'),'--host-entry',
                 f'src/host.omni:{entry}','-o',str(artifact),'--offline'])
        runtime=root/'dist/runtime'
        run(['gcc','-std=c11','-D_POSIX_C_SOURCE=200809L','-O1','-g',
             '-fsanitize=address,undefined','-fno-omit-frame-pointer',
             str(HERE/'sanitizer_host.c'),'-I',str(runtime),'-L',str(runtime),
             '-lomni_invocation_v1',f'-Wl,-rpath,{runtime}','-pthread',
             '-o',str(host)])
        zero_receipt=json.loads(pathlib.Path(str(zero_artifact)+'.omireceipt.json').read_text())
        echo_receipt=json.loads(pathlib.Path(str(echo_artifact)+'.omireceipt.json').read_text())
        spin_receipt=json.loads(pathlib.Path(str(spin_artifact)+'.omireceipt.json').read_text())
        output=run([str(host),str(zero_artifact),zero_receipt['artifact_sha256'],
                    zero_receipt['descriptor_sha256'],zero_receipt['signature_digest'],
                    str(echo_artifact),echo_receipt['artifact_sha256'],
                    echo_receipt['descriptor_sha256'],echo_receipt['signature_digest'],
                    echo_receipt['parameter_type_ids'][0],str(spin_artifact),
                    spin_receipt['artifact_sha256'],spin_receipt['descriptor_sha256'],
                    spin_receipt['signature_digest']])
        if 'ASAN_UBSAN_HOST_INVOCATION_PASS iterations=512 fuzz=4096 echo=2 cancel=16' not in output:
            raise RuntimeError('host pass oracle absent')
        outcome='PASS'
    except Exception as error:
        outcome=f'FAIL: {error}'
    report={'schema':'omni.core-host-02-sanitizer/1','status':outcome,
            'compiler_sha256':sha(compiler),'loader_sha256':sha(library)
                if library.is_file() else None,
            'runtime_build_sha256':(root/'dist/runtime/omni_invocation_build_id.txt').read_text().strip()
                if (root/'dist/runtime/omni_invocation_build_id.txt').exists() else None,
            'artifacts':{name:sha(path) if path.is_file() else None for name,path in
                         {'zero':zero_artifact,'echo':echo_artifact,'spin':spin_artifact}.items()},
            'host_sha256':sha(host) if host.is_file() else None,
            'commands':records}
    (root/'sanitizer_report.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({'status':outcome,'commands':len(records)}))
    return 0 if outcome=='PASS' else 1

if __name__=='__main__':
    raise SystemExit(main())
