#!/usr/bin/env python3
from __future__ import annotations
import argparse,hashlib,os,pathlib,shlex,shutil,subprocess,tempfile
from concurrent.futures import ThreadPoolExecutor,as_completed
ROOT=pathlib.Path(__file__).resolve().parents[1]
BASE_WARN=['-Wall','-Wextra','-Wpedantic','-Werror','-Wshadow','-Wconversion','-Wsign-conversion']
def sources():
 return [ROOT/x.strip() for x in (ROOT/'tools/core_sources.txt').read_text().splitlines() if x.strip() and not x.lstrip().startswith('#')]
def main():
 ap=argparse.ArgumentParser();ap.add_argument('--output',type=pathlib.Path,required=True);ap.add_argument('--jobs',type=int,default=max(1,min(2,os.cpu_count() or 1)));ap.add_argument('--quiet',action='store_true');ap.add_argument('--sanitizers',action='store_true');ap.add_argument('--object-cache',type=pathlib.Path,help='optional directory of compiled objects keyed by compiler, flags, the source and every header under src/ (developer and mutation builds; never used by the SDK build)');a=ap.parse_args()
 if a.jobs<1 or a.jobs>16:ap.error('--jobs must be 1..16')
 cxx=os.environ.get('SAN_CXX' if a.sanitizers else 'CXX','g++' if a.sanitizers else 'c++');libs=shlex.split(os.environ.get('OMNI_CRYPTO_LIBS','-lcrypto'));libs+=[] if '-ldl' in libs else ['-ldl'];srcs=sources();a.output.parent.mkdir(parents=True,exist_ok=True);flags=['-std=c++20','-pthread',*(['-O0','-g1','-fsanitize=address,undefined','-fno-omit-frame-pointer'] if a.sanitizers else ['-O2']),*BASE_WARN];link_extra=['-pthread',*(['-fsanitize=address,undefined','-fno-omit-frame-pointer'] if a.sanitizers else [])]
 with tempfile.TemporaryDirectory(prefix='omni-build-') as td:
  td=pathlib.Path(td);objs=[td/(s.stem+'.o') for s in srcs]
  def compile_one(pair):
   src,obj=pair;cmd=[cxx,*flags,'-c',str(src),'-o',str(obj)]
   if a.object_cache:
    key=hashlib.sha256(b'|'.join([cxx.encode(),subprocess.run([cxx,'--version'],capture_output=True).stdout,' '.join(flags).encode(),src.read_bytes(),*[h.read_bytes() for h in sorted((ROOT / "compiler/src").glob('*.hpp'))]])).hexdigest();hit=a.object_cache/(src.stem+'-'+key+'.o')
    if hit.exists():shutil.copyfile(hit,obj);return src,subprocess.CompletedProcess(cmd,0,'','')
   r=subprocess.run(cmd,capture_output=True,text=True)
   if a.object_cache and r.returncode==0:
    a.object_cache.mkdir(parents=True,exist_ok=True);tmp=hit.with_suffix('.tmp%d'%os.getpid());shutil.copyfile(obj,tmp);os.replace(tmp,hit)
   return src,r
  with ThreadPoolExecutor(max_workers=a.jobs) as ex:
   fs=[ex.submit(compile_one,p) for p in zip(srcs,objs)]
   for f in as_completed(fs):
    src,r=f.result()
    if r.returncode:
     if r.stdout:print(r.stdout,end='')
     if r.stderr:print(r.stderr,end='',file=__import__('sys').stderr)
     raise SystemExit(f'compile failed: {src.relative_to(ROOT)}')
  cmd=[cxx,*map(str,objs),*link_extra,'-o',str(a.output),*libs];r=subprocess.run(cmd,capture_output=True,text=True)
  if r.returncode:
   if r.stdout:print(r.stdout,end='')
   if r.stderr:print(r.stderr,end='',file=__import__('sys').stderr)
   raise SystemExit('link failed')
 if not a.quiet:print(f'built {a.output} from {len(srcs)} Core translation units (jobs={a.jobs})')
if __name__=='__main__':main()
