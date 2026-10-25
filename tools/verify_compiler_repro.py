#!/usr/bin/env python3
from __future__ import annotations
import hashlib,json,os,pathlib,subprocess,tempfile
ROOT=pathlib.Path(__file__).resolve().parents[1]
def digest(p:pathlib.Path)->str:
 h=hashlib.sha256()
 with p.open('rb') as f:
  for chunk in iter(lambda:f.read(1024*1024),b''):h.update(chunk)
 return h.hexdigest()
def main()->int:
 current=ROOT/'bin/linux-x86_64/omni'
 if not current.is_file():raise SystemExit('compiler binary missing; run tools/build.sh first')
 jobs=os.environ.get('OMNI_BUILD_JOBS','2')
 with tempfile.TemporaryDirectory(prefix='omni-repro-') as td:
  rebuilt=pathlib.Path(td)/'omni';cmd=['python3',str(ROOT/'tools/build_compiler.py'),'--output',str(rebuilt),'--jobs',jobs,'--quiet'];r=subprocess.run(cmd,capture_output=True,text=True,env=os.environ.copy())
  if r.returncode:
   print(json.dumps({'schema':'omni.compiler-repro/3','status':'build-failed','stdout':r.stdout,'stderr':r.stderr},indent=2));return 2
  a,b=digest(current),digest(rebuilt);same=a==b
  result={'schema':'omni.compiler-repro/3','version':(ROOT/'VERSION').read_text().strip(),'status':'pass' if same else 'fail','distributed_sha256':a,'clean_rebuild_sha256':b,'identical':same,'language_standard':'c++20','warnings_as_errors':['Wall','Wextra','Wpedantic','Wshadow','Wconversion','Wsign-conversion'],'source_manifest':'tools/core_sources.txt','source_count':sum(1 for x in (ROOT/'tools/core_sources.txt').read_text().splitlines() if x.strip() and not x.lstrip().startswith('#')),'build_driver':'tools/build_compiler.py','parallel_jobs':int(jobs)}
  print(json.dumps(result,indent=2));return 0 if same else 1
if __name__=='__main__':raise SystemExit(main())
