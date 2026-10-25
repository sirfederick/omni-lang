#!/usr/bin/env python3
"""Verify listed package bytes before rebuilding. No publisher authentication is provided."""
from __future__ import annotations
import hashlib, json, os
from pathlib import Path, PurePosixPath
import sys
def digest(path: Path) -> str:
    h=hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda:f.read(1024*1024),b''): h.update(chunk)
    return h.hexdigest()
def main() -> int:
    root=Path(__file__).resolve().parents[1]; manifest_path=Path(os.environ.get('OMNI_PACKAGE_MANIFEST', root/'evidence/package_manifest.json')).resolve()
    try:
        manifest=json.loads(manifest_path.read_text(encoding='utf-8')); failures=[]; seen=set()
        for item in manifest['files']:
            name=item['path']; relative=PurePosixPath(name)
            if relative.is_absolute() or '..' in relative.parts or name in seen or '\\' in name:
                failures.append(f'unsafe or duplicate entry: {name}'); continue
            seen.add(name); path=root/name
            if not path.is_file() or path.is_symlink() or root not in path.resolve().parents:
                failures.append(f'missing or unsafe file: {name}'); continue
            if path.stat().st_size!=item['bytes'] or digest(path)!=item['sha256']: failures.append(f'mismatch: {name}')
        actual=set()
        for path in root.rglob('*'):
            if not path.is_file() or path.is_symlink() or '__pycache__' in path.parts: continue
            rel=path.relative_to(root).as_posix()
            if path.resolve()==manifest_path: continue
            actual.add(rel)
        for extra in sorted(actual-seen): failures.append(f'unlisted file: {extra}')
        for missing in sorted(seen-actual):
            if not any(x==f'missing or unsafe file: {missing}' for x in failures): failures.append(f'manifest-only file: {missing}')
        for failure in failures: print(failure,file=sys.stderr)
        print(f'{len(seen)} manifest files checked; {len(actual)} package files observed; {len(failures)} errors. Integrity, not authenticity.')
        return 1 if failures else 0
    except (OSError,ValueError,KeyError,TypeError) as exc:
        print(f'Cannot verify package: {exc}',file=sys.stderr); return 2
if __name__=='__main__': raise SystemExit(main())
