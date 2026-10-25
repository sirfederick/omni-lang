#!/usr/bin/env python3
from __future__ import annotations
import hashlib, json, os
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
OUT=Path(os.environ.get('OMNI_PACKAGE_MANIFEST', ROOT/'evidence/package_manifest.json')).resolve()
def digest(path: Path) -> str:
    h=hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda:f.read(1024*1024),b''): h.update(chunk)
    return h.hexdigest()
files=[]
for p in sorted(ROOT.rglob('*')):
    if not p.is_file() or p.is_symlink(): continue
    rel=p.relative_to(ROOT).as_posix()
    if p.resolve()==OUT or '__pycache__' in p.parts: continue
    files.append({'path':rel,'bytes':p.stat().st_size,'sha256':digest(p)})
OUT.parent.mkdir(parents=True,exist_ok=True)
OUT.write_text(json.dumps({'schema':'omni.package-manifest/1','version':(ROOT/'VERSION').read_text().strip(),'files':files},indent=2)+'\n',encoding='utf-8')
print(f'{len(files)} files recorded')
