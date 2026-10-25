#!/usr/bin/env python3
"""Verify an extracted Omni SDK without consulting its source checkout."""
from __future__ import annotations
import argparse, hashlib, json, os, pathlib, subprocess, sys

def sha(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()

def component_path(root: pathlib.Path, name: object) -> pathlib.Path | None:
    if not isinstance(name, str) or not name or '\0' in name:
        return None
    relative = pathlib.PurePosixPath(name)
    if relative.is_absolute() or '..' in relative.parts or relative.as_posix() != name:
        return None
    path = root.joinpath(*relative.parts)
    for parent in (path, *path.parents):
        if parent == root:
            break
        if parent.is_symlink():
            return None
    return path if path.resolve().is_relative_to(root) else None

def main() -> int:
    parser=argparse.ArgumentParser(); parser.add_argument('--sdk-root',type=pathlib.Path,required=True); args=parser.parse_args()
    root=args.sdk_root.resolve(); metadata=root/'metadata/omni-sdk.json'; checks=[]
    if not metadata.is_file() or metadata.is_symlink():
        print(json.dumps({'schema':'omni.sdk-doctor/1','status':'FAIL','reason':'metadata missing'})); return 1
    try:
        data=json.loads(metadata.read_text(encoding='utf-8'))
    except (OSError, UnicodeError, ValueError):
        print(json.dumps({'schema':'omni.sdk-doctor/1','status':'FAIL','reason':'invalid metadata'})); return 1
    if not isinstance(data,dict) or data.get('schema')!='omni.sdk-distribution/1' or not isinstance(data.get('components'),list):
        print(json.dumps({'schema':'omni.sdk-doctor/1','status':'FAIL','reason':'invalid component inventory'})); return 1
    verified={}; libraries=[]
    for item in data['components']:
        name=item.get('path') if isinstance(item,dict) else None
        path=component_path(root,name)
        ok=path is not None and path.is_file() and sha(path)==item.get('sha256') and name not in verified
        if isinstance(name,str):
            verified[name]=bool(ok)
        checks.append({'component':name,'status':'PASS' if ok else 'FAIL'})
        if ok and pathlib.PurePosixPath(name).parts[0]=='packages' and path.name=='omni.package.json':
            try:
                package=json.loads(path.read_text(encoding='utf-8'))
                if package.get('schema')=='omni.package/1' and package.get('name')=='omni.std' and isinstance(package.get('version'),str) and package['version']:
                    libraries.append({'manifest':name,'version':package['version']})
            except (OSError, UnicodeError, ValueError, AttributeError):
                checks.append({'component':name,'status':'FAIL'})
    compiler=root/'bin/omni'; compiler_ok=verified.get('bin/omni',False)
    if compiler_ok:
        version=subprocess.run([str(compiler),'--version'],env={**os.environ,'OMNI_HOME':str(root)},capture_output=True,text=True,timeout=15)
        compiler_ok=version.returncode==0 and version.stdout.strip()=='omni '+str(data.get('version'))
    checks.extend([
        {'component':'compiler','status':'PASS' if compiler_ok else 'FAIL'},
        {'component':'omni_std','status':'PASS' if len(libraries)==1 else 'FAIL'},
    ])
    for label, relative in (
            ('runtime','runtime/libomni_invocation_v1.so'),
            ('host_sdk_header','include/omni/omni_host_sdk_v1.h'),
            ('host_sdk_library','lib/libomni_host_sdk_v1.so'),
            ('node_binding','node/omni_host_sdk.node'),
            ('python_binding','python/omni_host_sdk.py'),
            ('codegen','tools/omni_sdk_codegen.py'),
            ('lsp','tools/omni_lsp.py'), ('version_file','VERSION'),
            ('public_delta','spec/CORE_1_3_0_0_PUBLIC_DELTA_CANDIDATE.json')):
        checks.append({'component':label,'status':'PASS' if verified.get(relative,False) else 'FAIL'})
    if verified.get('VERSION',False):
        checks.append({'component':'version_matches_metadata',
                       'status':'PASS' if (root/'VERSION').read_text().strip()==data.get('version') else 'FAIL'})
    status='PASS' if all(row['status']=='PASS' for row in checks) else 'FAIL'
    print(json.dumps({'schema':'omni.sdk-doctor/1','status':status,'version':data.get('version'),'target':data.get('target'),'stdlib':libraries[0] if len(libraries)==1 else None,'source_checkout_dependency':'NONE','checks':checks},indent=2))
    return 0 if status=='PASS' else 1

if __name__=='__main__': raise SystemExit(main())
