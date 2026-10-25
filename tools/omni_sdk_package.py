#!/usr/bin/env python3
"""Create the reproducible Linux Host SDK archive from supplied build outputs."""
from __future__ import annotations
import argparse, gzip, hashlib, io, json, pathlib, tarfile

ROOT=pathlib.Path(__file__).resolve().parents[1]
VERSION=(ROOT/'VERSION').read_text(encoding='utf-8').strip(); TARGET='linux-x86_64-gnu'

def sha(path: pathlib.Path)->str: return hashlib.sha256(path.read_bytes()).hexdigest()
def add(tar: tarfile.TarFile, src: pathlib.Path, name: str) -> None:
    info=tar.gettarinfo(str(src),arcname=name); info.uid=info.gid=0; info.uname=info.gname=''; info.mtime=0
    with src.open('rb') as handle: tar.addfile(info,handle)
def add_bytes(tar: tarfile.TarFile, name: str, value: bytes) -> None:
    info=tarfile.TarInfo(name); info.size=len(value); info.mode=0o644; info.uid=info.gid=0; info.uname=info.gname=''; info.mtime=0; tar.addfile(info,io.BytesIO(value))

def main()->None:
    parser=argparse.ArgumentParser(); parser.add_argument('--compiler',type=pathlib.Path,required=True); parser.add_argument('--runtime',type=pathlib.Path,required=True); parser.add_argument('--node',type=pathlib.Path,required=True); parser.add_argument('--output',type=pathlib.Path,required=True)
    parser.add_argument('--candidate-source-sha', help='full committed source SHA, verified by the build receipt')
    parser.add_argument('--provenance', type=pathlib.Path, help='build receipt for this compiler/runtime/addon')
    args=parser.parse_args()
    candidate=args.candidate_source_sha
    if candidate and (len(candidate)!=40 or any(c not in '0123456789abcdef' for c in candidate)):
        parser.error('--candidate-source-sha must be a full lowercase Git SHA')
    if bool(candidate)!=bool(args.provenance):
        parser.error('candidate source SHA and provenance must be supplied together')
    files=[
        (args.compiler,'bin/omni'),(args.runtime,'runtime/libomni_invocation_v1.so'),(args.runtime,'lib/libomni_host_sdk_v1.so'),
        (ROOT/'runtime/omni_runtime.c','runtime/omni_runtime.c'),(ROOT/'runtime/omni_invocation_v1.h','runtime/omni_invocation_v1.h'),(ROOT/'runtime/omni_invocation_internal.h','runtime/omni_invocation_internal.h'),
        (args.runtime.parent/'omni_invocation_build_id.txt','runtime/omni_invocation_build_id.txt'),(args.runtime.parent/'omni_invocation_backend_sha256.txt','runtime/omni_invocation_backend_sha256.txt'),
        (ROOT/'include/omni/omni_host_sdk_v1.h','include/omni/omni_host_sdk_v1.h'),(args.node,'node/omni_host_sdk.node'),
        (ROOT/'bindings/python/omni_host_sdk.py','python/omni_host_sdk.py'),(ROOT/'tools/omni_sdk_codegen.py','tools/omni_sdk_codegen.py'),(ROOT/'tools/omni_sdk_doctor.py','tools/omni_sdk_doctor.py'),
        (ROOT/'VERSION','VERSION'),(ROOT/'tools/omni_lsp.py','tools/omni_lsp.py'),
        (ROOT/'spec/CORE_1_3_0_0_PUBLIC_DELTA_CANDIDATE.json','spec/CORE_1_3_0_0_PUBLIC_DELTA_CANDIDATE.json'),
    ]
    files.extend([(ROOT/'LICENSE-MIT','LICENSE-MIT'),(ROOT/'LICENSE-APACHE','LICENSE-APACHE'),(ROOT/'THIRD_PARTY_NOTICES.md','THIRD_PARTY_NOTICES.md')])
    std=ROOT/'stdlib'
    std_manifest=json.loads((std/'omni.package.json').read_text(encoding='utf-8'))
    std_name=std_manifest.get('name'); std_version=std_manifest.get('version')
    if std_manifest.get('schema')!='omni.package/1' or std_name!='omni.std' or not isinstance(std_version,str) or std_version in ('','.','..') or any(char in std_version for char in '/\\\0'):
        raise RuntimeError('invalid authoritative stdlib manifest')
    std_prefix=f'packages/{std_name}/{std_version}/'
    for source in sorted(std.rglob('*')):
        if source.is_file() and not source.is_symlink(): files.append((source,std_prefix+source.relative_to(std).as_posix()))
    for source in sorted((ROOT/'examples').rglob('*')):
        if source.is_file() and not source.is_symlink(): files.append((source,'examples/'+source.relative_to(ROOT/'examples').as_posix()))
    if candidate:
        provenance=json.loads(args.provenance.read_text(encoding='utf-8'))
        if provenance.get('source_sha')!=candidate or provenance.get('source_status')!='COMMITTED_CLEAN':
            raise RuntimeError('candidate requires a matching clean-source build receipt')
        for key,source in [('compiler_sha256',args.compiler),('runtime_sha256',args.runtime),('node_sha256',args.node)]:
            if provenance.get(key)!=sha(source): raise RuntimeError('build receipt component mismatch: '+key)
        files.append((args.provenance,'metadata/build-provenance.json'))
        # Ship actual Core providers, ABI adapters, examples and their existing harness.
        # They are conformance fixtures, not a production kernel runtime.
        for source in sorted((ROOT/'tests/x64').rglob('*')):
            if source.is_file() and not source.is_symlink(): files.append((source,'tests/x64/'+source.relative_to(ROOT/'tests/x64').as_posix()))
        files.append((ROOT/'tests/language_0_8_3_alpha8.py','tests/language_0_8_3_alpha8.py'))
    for source in sorted((ROOT/'spec').glob('*.md')): files.append((source,'spec/'+source.name))
    for source,_ in files:
        if not source.is_file() or source.is_symlink(): raise RuntimeError(f'unsafe or missing bundle component: {source}')
    files.sort(key=lambda item:item[1]); metadata={'schema':'omni.sdk-distribution/1','version':VERSION,'target':TARGET,'components':[{'path':dest,'sha256':sha(source)} for source,dest in files]}
    prefix=f'omni-sdk-v{VERSION}-{TARGET}'
    if candidate:
        metadata.update(language_version=VERSION, source_sha=candidate, package_status='DEVELOPMENT_CANDIDATE',
                        compiler_sha256=sha(args.compiler), enterprise_complete_at_build=False,
                        certification_authority='external exact-SHA receipt')
        prefix+=f'-candidate+g{candidate[:12]}'
    args.output.parent.mkdir(parents=True,exist_ok=True)
    with args.output.open('wb') as raw:
        with gzip.GzipFile(filename='',mode='wb',fileobj=raw,mtime=0) as zipped:
            with tarfile.open(fileobj=zipped,mode='w',format=tarfile.GNU_FORMAT) as tar:
                for source,dest in files: add(tar,source,f'{prefix}/{dest}')
                add_bytes(tar,f'{prefix}/metadata/omni-sdk.json',(json.dumps(metadata,sort_keys=True,separators=(',',':'))+'\n').encode())
    print(json.dumps({'schema':'omni.sdk-package/1','status':'PASS','asset':args.output.name,'sha256':sha(args.output),'components':len(files)},sort_keys=True))

if __name__=='__main__': main()
