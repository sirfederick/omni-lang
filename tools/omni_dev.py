#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Federico T. Begna
# SPDX-License-Identifier: MIT OR Apache-2.0
"""Build and exercise Omni from a source tree; Git is not required."""
from __future__ import annotations
import argparse,hashlib,json,os,pathlib,shutil,subprocess,sys
ROOT=pathlib.Path(__file__).resolve().parents[1]

def execute(args,env=None):
    return subprocess.run([str(x) for x in args],cwd=ROOT,env=env,check=False).returncode

def fingerprint(target):
    paths=[ROOT/'tools/core_sources.txt',ROOT/'tools/build_compiler.py']
    for directory in ('compiler/src','runtime','include'):
        paths += [p for p in (ROOT/directory).rglob('*') if p.is_file()]
    if target=='loader':paths.append(ROOT/'tools/build_invocation_loader.py')
    if target=='node':paths += [ROOT/'bindings/node/omni_host_sdk_node.cpp',ROOT/'tools/build_host_sdk_node.py']
    h=hashlib.sha256()
    for p in sorted(set(paths)):h.update(p.relative_to(ROOT).as_posix().encode()+b'\0'+p.read_bytes())
    for name in ('CXX','CC','OMNI_CRYPTO_LIBS'):h.update(name.encode()+b'='+os.environ.get(name,'').encode())
    h.update(target.encode())
    return h.hexdigest()

def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--allow-slow-fs',action='store_true',help='allow the existing Windows-mounted workspace')
    sub=parser.add_subparsers(dest='command',required=True)
    sub.add_parser('env')
    build=sub.add_parser('build');build.add_argument('--target',choices=('compiler','loader','node','all'),default='compiler');build.add_argument('--jobs',type=int,default=2);build.add_argument('--force',action='store_true')
    for name in ('check','run'):
        p=sub.add_parser(name);p.add_argument('source');p.add_argument('args',nargs=argparse.REMAINDER)
    test=sub.add_parser('test');test.add_argument('--group',action='append',default=[]);test.add_argument('--report',default='build/dev/matrix.json')
    args=parser.parse_args(argv)
    if sys.platform=='win32':
        distro=os.environ.get('OMNI_WSL_DISTRO','Ubuntu-24.04')
        path=subprocess.run(['wsl','-d',distro,'--exec','wslpath','-a',str(ROOT)],capture_output=True,text=True)
        if path.returncode:return path.returncode
        return execute(['wsl','-d',distro,'--cd',path.stdout.strip(),'--exec','python3','-B','tools/omni_dev.py',*(sys.argv[1:] if argv is None else argv)])
    if str(ROOT).startswith('/mnt/') and not args.allow_slow_fs:
        parser.error('pass --allow-slow-fs for this mounted workspace; no source relocation is required')
    out=ROOT/'build/dev';binary=out/'omni'
    env=dict(os.environ,OMNI_HOME=str(ROOT),OMNI_TEST_BIN=str(binary),PYTHONDONTWRITEBYTECODE='1')
    if args.command=='env':
        tools={name:shutil.which(name) for name in ('c++','g++','clang','python3','node')}
        print(json.dumps({'platform':sys.platform,'tools':tools,'openssl_headers':pathlib.Path('/usr/include/openssl/evp.h').is_file(),'node_headers':pathlib.Path('/usr/include/node/node_api.h').is_file(),'product_version':(ROOT/'VERSION').read_text().strip(),'git_required':False},indent=2))
        return 0 if all(tools[x] for x in ('c++','clang','python3')) else 2
    if args.command=='build':
        if not 1<=args.jobs<=16:parser.error('--jobs must be 1..16')
        targets=('compiler','loader','node') if args.target=='all' else (args.target,)
        out.mkdir(parents=True,exist_ok=True)
        for target in targets:
            output={'compiler':binary,'loader':out/'runtime/libomni_invocation_v1.so','node':out/'node/omni_host_sdk.node'}[target]
            stamp=out/(target+'.inputs.json');digest=fingerprint(target)
            if not args.force and output.is_file() and stamp.is_file():
                previous=json.loads(stamp.read_text())
                if previous['inputs']==digest and previous['output']==hashlib.sha256(output.read_bytes()).hexdigest():
                    print('UP_TO_DATE '+target);continue
            command={'compiler':['tools/build_compiler.py','--output',output,'--jobs',args.jobs],
                     'loader':['tools/build_invocation_loader.py','--output',output,'--jobs',args.jobs],
                     'node':['tools/build_host_sdk_node.py','--runtime-dir',out/'runtime','--output',output]}[target]
            code=execute([sys.executable,'-B',*command],env)
            if code:return code
            if not output.is_file():return 1
            stamp.write_text(json.dumps({'inputs':digest,'output':hashlib.sha256(output.read_bytes()).hexdigest()},indent=2)+'\n')
        return 0
    if not binary.is_file():parser.error('compiler missing; execute build first')
    stamp=out/'compiler.inputs.json'
    if not stamp.is_file() or json.loads(stamp.read_text())['inputs']!=fingerprint('compiler'):
        parser.error('compiler input stamp is stale; execute build')
    if args.command in ('check','run'):
        return execute([binary,args.command,args.source,*args.args],env)
    command=[sys.executable,'-B','tools/run_test_matrix.py','--report',args.report,'--max-skips','0']
    for group in args.group or ['core']:command+=['--group',group]
    return execute(command,env)

if __name__=='__main__':sys.exit(main())
