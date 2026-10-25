#!/usr/bin/env python3
from __future__ import annotations

import json
import hashlib
import os
import pathlib
import subprocess
import tempfile
import unittest

ROOT=pathlib.Path(__file__).resolve().parents[1]
OMNI=pathlib.Path(os.environ.get('OMNI_TEST_BIN',ROOT/'bin/linux-x86_64/omni'))

def run(*args:object)->subprocess.CompletedProcess[bytes]:
    return subprocess.run([str(x) for x in args],capture_output=True,env={**os.environ,'OMNI_HOME':str(ROOT)})

class A84PackageResolverTests(unittest.TestCase):
    def setUp(self)->None:
        self.tmp=tempfile.TemporaryDirectory(prefix='omni-a84-')
        self.root=pathlib.Path(self.tmp.name)/'app'
        (self.root/'src').mkdir(parents=True)
        (self.root/'src'/'main.omni').write_text('module app\nfunc main() u32 { return 7u32 }\n',encoding='utf-8')

    def tearDown(self)->None: self.tmp.cleanup()
    def manifest(self,dependencies:dict[str,object]|None=None)->None:
        data={'schema':'omni.package/1','name':'example.app','version':'0.1.0','entry':'src/main.omni'}
        if dependencies is not None:data['dependencies']=dependencies
        (self.root/'omni.package.json').write_text(json.dumps(data),encoding='utf-8')
    def package(self,action:str,*extra:str)->subprocess.CompletedProcess[bytes]:
        return run(OMNI,'package',action,self.root,*extra)
    def rejects(self,code:bytes,action:str='lock')->None:
        r=self.package(action,'--offline');self.assertEqual(r.returncode,2,r.stderr);self.assertIn(code,r.stderr)

    def legacy_lock(self)->bytes:
        files=[]
        for path in self.root.rglob('*'):
            if not path.is_file() or path.name=='omni.lock.json': continue
            rel=path.relative_to(self.root).as_posix()
            if rel.split('/',1)[0] in {'bin','.omni-cert','.cache'}: continue
            files.append((rel,hashlib.sha256(path.read_bytes()).hexdigest()))
        canonical=''.join(f'{rel}\n{digest}\n' for rel,digest in sorted(files))
        manifest=hashlib.sha256((self.root/'omni.package.json').read_bytes()).hexdigest()
        source=hashlib.sha256(canonical.encode()).hexdigest()
        return ('{\n  "schema": "omni.lock/1",\n  "packages": [\n'
                f'    {{"origin":"local:.","name":"example.app","version":"0.1.0","manifest_sha256":"{manifest}","source_sha256":"{source}"}}\n'
                '  ]\n}\n').encode()

    def test_lock_and_offline_check_are_deterministic(self)->None:
        self.manifest()
        first=self.package('lock','--offline');self.assertEqual(first.returncode,0,first.stderr)
        a=(self.root/'omni.lock.json').read_bytes()
        second=self.package('lock','--offline');self.assertEqual(second.returncode,0,second.stderr)
        self.assertEqual(a,(self.root/'omni.lock.json').read_bytes())
        checked=self.package('check','--offline');self.assertEqual(checked.returncode,0,checked.stderr)
        result=json.loads(checked.stdout);self.assertEqual(result['schema'],'omni.package-resolution/1');self.assertEqual(result['lock_schema'],'omni.lock/2');self.assertTrue(result['lock_verified'])
        self.assertEqual(self.package('check').returncode,2)

    def test_tampered_source_is_lock_drift(self)->None:
        self.manifest();self.assertEqual(self.package('lock','--offline').returncode,0)
        (self.root/'src'/'main.omni').write_text('module app\nfunc main() u32 { return 8u32 }\n',encoding='utf-8')
        self.rejects(b'E_PACKAGE_LOCK','check')

    def test_v2_ignores_non_semantic_local_artifacts(self)->None:
        self.manifest();self.assertEqual(self.package('lock','--offline').returncode,0)
        lock=(self.root/'omni.lock.json').read_bytes()
        (self.root/'.env').write_text('TOKEN=never-a-lock-input\n',encoding='utf-8')
        (self.root/'docs').mkdir();(self.root/'docs'/'notes.md').write_text('not Omni source\n',encoding='utf-8')
        cache=self.root/'src'/'__pycache__';cache.mkdir();(cache/'helper.pyc').write_bytes(b'cache')
        checked=self.package('check','--offline');self.assertEqual(checked.returncode,0,checked.stderr)
        self.assertEqual(lock,(self.root/'omni.lock.json').read_bytes())

    def test_v2_hashes_every_omni_source_under_src(self)->None:
        self.manifest();self.assertEqual(self.package('lock','--offline').returncode,0)
        extra=self.root/'src'/'extra.omni';extra.write_text('module extra\nfunc value() u32 { return 1u32 }\n',encoding='utf-8')
        self.rejects(b'E_PACKAGE_LOCK','check')
        self.assertEqual(self.package('lock','--offline').returncode,0)
        self.assertEqual(self.package('check','--offline').returncode,0)
        extra.write_text('module extra\nfunc value() u32 { return 2u32 }\n',encoding='utf-8')
        self.rejects(b'E_PACKAGE_LOCK','check')

    def test_legacy_v1_is_read_only_compatibility_not_ambient_state(self)->None:
        self.manifest();(self.root/'omni.lock.json').write_bytes(self.legacy_lock())
        before=(self.root/'omni.lock.json').read_bytes()
        checked=self.package('check','--offline');self.assertEqual(checked.returncode,0,checked.stderr)
        self.assertEqual(json.loads(checked.stdout)['lock_schema'],'omni.lock/1');self.assertEqual(before,(self.root/'omni.lock.json').read_bytes())
        (self.root/'.env').write_text('TOKEN=legacy-drift\n',encoding='utf-8')
        self.rejects(b'E_PACKAGE_LOCK','check')
        self.assertEqual(self.package('lock','--offline').returncode,0)
        self.assertEqual(json.loads((self.root/'omni.lock.json').read_text())['schema'],'omni.lock/2')
        self.assertEqual(self.package('check','--offline').returncode,0)

    def test_v2_rejects_symlink_in_selected_source_tree(self)->None:
        self.manifest();os.symlink(self.root/'src'/'main.omni',self.root/'src'/'linked.omni')
        self.rejects(b'E_PACKAGE_PATH','lock')

    def test_entry_must_be_a_source_file_below_src(self)->None:
        self.manifest();data=json.loads((self.root/'omni.package.json').read_text());data['entry']='../outside.omni';(self.root/'omni.package.json').write_text(json.dumps(data))
        self.rejects(b'E_PACKAGE_PATH','lock')

    def test_versioned_stdlib_dependency_has_a_clean_offline_consumer(self)->None:
        stdlib=self.root.parent/'stdlib';(stdlib/'src').mkdir(parents=True)
        (stdlib/'src'/'prelude.omni').write_text('module omni_std\npub func ok(value u32) Result<u32,u32> { return Ok<u32,u32>(value) }\n',encoding='utf-8')
        (stdlib/'omni.package.json').write_text(json.dumps({'schema':'omni.package/1','name':'omni.std','version':'0.8.4-alpha.8','entry':'src/prelude.omni'}),encoding='utf-8')
        self.manifest({'omni.std':{'path':'../stdlib','version':'0.8.4-alpha.8'}})
        self.assertEqual(run(OMNI,'package','lock',stdlib,'--offline').returncode,0)
        self.assertEqual(self.package('lock','--offline').returncode,0)
        checked=self.package('check','--offline');self.assertEqual(checked.returncode,0,checked.stderr)
        self.assertEqual(json.loads(checked.stdout)['packages'],2)
        self.assertEqual(run(OMNI,'check',self.root/'src'/'main.omni').returncode,0)

    def test_manifest_unknown_and_unsafe_dependency_fail_closed(self)->None:
        self.manifest();data=json.loads((self.root/'omni.package.json').read_text());data['script']='run';(self.root/'omni.package.json').write_text(json.dumps(data));self.rejects(b'E_PACKAGE_MANIFEST')
        self.manifest({'evil':{'path':'../other','version':'0.1.0'}});self.rejects(b'E_PACKAGE_PATH')

    def test_missing_dependency_and_cycle_reject(self)->None:
        self.manifest({'missing':{'path':'missing','version':'0.1.0'}});self.rejects(b'E_PACKAGE_PATH')
        dep=self.root/'dep';(dep/'src').mkdir(parents=True);(dep/'src'/'main.omni').write_text('module dep\nfunc main() u32 { return 0u32 }\n')
        (dep/'omni.package.json').write_text(json.dumps({'schema':'omni.package/1','name':'example.dep','version':'0.1.0','entry':'src/main.omni','dependencies':{'app':{'path':'..','version':'0.1.0'}}}))
        self.manifest({'dep':{'path':'dep','version':'0.1.0'}});self.rejects(b'E_PACKAGE_CYCLE')

if __name__=='__main__': unittest.main(verbosity=2)
