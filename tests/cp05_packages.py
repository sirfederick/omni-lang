#!/usr/bin/env python3
"""CP-05 row 5.10 (spec/PACKAGE_DEPENDENCY_IMPORTS_CANDIDATE.md): a library in its own package is consumed by another package WITHOUT copying its source, and the elements
it owns stay owned.

`import alias "@dependency/relative.omni"` names a module of a dependency declared in the manifest of the importing package. The dependency must be locked (`omni package lock`)
and its lock must still match its bytes (`E_PACKAGE_LOCK`); a dependency that is not declared, a path that escapes the dependency's `src/` and a file outside every package are
`E_IMPORT_PATH`. Evaluator and native binary run the consumer and agree.
"""
from __future__ import annotations
import json
import hashlib
import importlib.util
import io
import contextlib
import os
import pathlib
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest import mock
from language_0_8_3_alpha8 import ROOT, OMNI, proc

STORAGE = ROOT / 'examples' / 'storage'
APP = ('module app\nimport seq "@acme.coll/seq.omni"\n'
       'struct Tok { h u64 }\nfunc mint(n u64) Resource<Tok> { return resource.seal(Tok { h: n }) }\n'
       'func val(x Borrow<Tok>) u64 { let r Tok = resource.peek(x)\n  return r.h }\n'
       'impl seq.Dispose for Tok { func dispose(x Resource<Tok>) u32 !{memory.write} { let r Tok = resource.unseal(move(x))\n  return 1u32 } }\n'
       'func main() u32 !{memory.read,memory.write} {\n  let c = seq.new<Tok>(0u32)\n  match c { Ok(s) {\n    var code u32 = 0u32\n    var i u64 = 1u64\n'
       '    for i <= 4u64 {\n      let g = seq.reserve<Tok>(borrow_mut(s))\n      match g { Ok(k) { } Err(e) { code = 1u32 } }\n'
       '      let r = seq.push<Tok>(borrow_mut(s), mint(i))\n      match r { Ok(k) { } Err(back) { let z u32 = seq.Dispose.dispose<Tok>(move(back))\n        code = 2u32 } }\n      i = i + 1u64\n    }\n'
       '    let e = seq.at<Tok>(borrow(s), seq.cursor())\n    if val(e) != 1u64 { code = 3u32 }\n'
       '    let d u32 = seq.destroy<Tok>(move(s))\n    if d != 4u32 { code = 4u32 }\n    if code != 0u32 { return code }\n    return 42u32\n  } Err(e) { return e } }\n}\n')


class SdkPackagingManifestTests(unittest.TestCase):
    def test_the_archive_stdlib_path_comes_from_its_authoritative_manifest(self):
        spec = importlib.util.spec_from_file_location('cp05_sdk_package', ROOT / 'tools/omni_sdk_package.py')
        packager = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(packager)
        with tempfile.TemporaryDirectory(prefix='omni-package-manifest-') as temporary:
            directory = pathlib.Path(temporary)
            fixture = directory / 'source'
            for relative in ('runtime/omni_runtime.c', 'runtime/omni_invocation_v1.h',
                             'runtime/omni_invocation_internal.h', 'include/omni/omni_host_sdk_v1.h',
                             'bindings/python/omni_host_sdk.py', 'tools/omni_sdk_codegen.py',
                             'tools/omni_sdk_doctor.py', 'tools/omni_lsp.py', 'tools/run_sdk_examples.py', 'VERSION',
                             'LICENSE-MIT','LICENSE-APACHE','THIRD_PARTY_NOTICES.md',
                             'spec/CORE_1_3_0_0_PUBLIC_DELTA_CANDIDATE.json'):
                destination = fixture / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(ROOT / relative, destination)
            shutil.copytree(ROOT / 'stdlib', fixture / 'stdlib')
            manifest_path = fixture / 'stdlib/omni.package.json'
            manifest = json.loads(manifest_path.read_text())
            manifest['version'] = '9.7.3'
            manifest_path.write_text(json.dumps(manifest))
            # Structural packaging only: these bytes are never executed and
            # do not claim runtime/addon conformance.
            runtime = directory / 'runtime/libomni_invocation_v1.so'
            runtime.parent.mkdir()
            runtime.write_bytes(b'packaging-only-runtime')
            for name in ('omni_invocation_build_id.txt', 'omni_invocation_backend_sha256.txt'):
                (runtime.parent / name).write_text('0' * 64 + '\n')
            addon = directory / 'addon.node'
            addon.write_bytes(b'packaging-only-addon')
            archive = directory / 'sdk.tar.gz'
            argv = ['omni_sdk_package.py', '--compiler', str(OMNI), '--runtime', str(runtime),
                    '--node', str(addon), '--output', str(archive)]
            with mock.patch.object(packager, 'ROOT', fixture), mock.patch.object(sys, 'argv', argv), contextlib.redirect_stdout(io.StringIO()):
                packager.main()
            expected = 'packages/omni.std/' + manifest['version'] + '/omni.package.json'
            with tarfile.open(archive) as package:
                members = {item.name.split('/', 1)[1]: item for item in package.getmembers()}
                self.assertIn(expected, members)
                metadata = json.load(package.extractfile(members['metadata/omni-sdk.json']))
                self.assertEqual(metadata['version'], (ROOT / 'VERSION').read_text().strip())
                entry, = [item for item in metadata['components'] if item['path'] == expected]
                self.assertEqual(entry['sha256'], hashlib.sha256(manifest_path.read_bytes()).hexdigest())


class PackageImportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='omni-cp05pkg-')
        self.ws = pathlib.Path(self.tmp.name)
        lib = self.ws / 'lib'
        (lib / 'src').mkdir(parents=True)
        (lib / 'omni.package.json').write_text(json.dumps({'schema': 'omni.package/1', 'name': 'acme.coll', 'version': '0.1.0', 'entry': 'src/coll.omni'}), encoding='utf-8')
        (lib / 'src' / 'coll.omni').write_text('module coll\nfunc version() u32 { return 1u32 }\n', encoding='utf-8')
        shutil.copy(STORAGE / 'seq.omni', lib / 'src' / 'seq.omni')
        app = self.ws / 'app'
        (app / 'src').mkdir(parents=True)
        self.manifest(app)
        (app / 'src' / 'main.omni').write_text(APP, encoding='utf-8')
        self.lib, self.app = lib, app

    def tearDown(self):
        self.tmp.cleanup()

    def manifest(self, app, deps=None):
        deps = {'acme.coll': {'path': '../lib', 'version': '0.1.0'}} if deps is None else deps
        (app / 'omni.package.json').write_text(json.dumps({'schema': 'omni.package/1', 'name': 'acme.app', 'version': '0.1.0', 'entry': 'src/main.omni', 'dependencies': deps}), encoding='utf-8')

    def lock(self):
        done = proc(OMNI, 'package', 'lock', self.app, '--offline')
        self.assertEqual(done.returncode, 0, done.stderr)

    def test_bundled_stdlib_imports_preserve_locks_round_trips_and_local_precedence(self):
        sdk = self.ws / 'installed-sdk'
        relative_std = pathlib.Path('packages/stdlib-Ã¡')
        bundled = sdk / relative_std
        shutil.copytree(ROOT / 'stdlib', bundled)
        std_manifest = bundled / 'omni.package.json'
        std_data = json.loads(std_manifest.read_text())
        std_data['version'] = '9.7.3'  # isolated dependency fixture, SDK VERSION unchanged
        std_manifest.write_text(json.dumps(std_data))
        (sdk / 'metadata').mkdir()
        inventory = {'schema': 'omni.sdk-distribution/1', 'version': (ROOT / 'VERSION').read_text().strip(),
                     'enterprise_complete': False, 'component_count': 1,
                     'components': [{'path': (relative_std / 'omni.package.json').as_posix(),
                                     'sha256': hashlib.sha256(std_manifest.read_bytes()).hexdigest()}]}
        inventory_path = sdk / 'metadata/omni-sdk.json'
        inventory_path.write_text(json.dumps(inventory))
        shutil.copytree(ROOT / 'runtime', sdk / 'runtime',
                        ignore=shutil.ignore_patterns('*.so', '*.o', '*.a'))
        app = self.ws / 'std-consumer'
        (app / 'src').mkdir(parents=True)
        (app / 'omni.package.json').write_text(json.dumps({
            'schema': 'omni.package/1', 'name': 'consumer.std', 'version': '1.0.0',
            'entry': 'src/main.omni', 'dependencies': {
                'omni.std': {'path': '../missing-source', 'version': std_data['version']}}}))
        source = app / 'src/main.omni'
        source.write_text('module app\nimport std "@omni.std/prelude.omni"\n'
                          'func main() u32 { let r = std.ok_u32(42u32)\n'
                          'match r { Ok(v) { return v } Err(e) { return e } } }\n')
        env = {**os.environ, 'OMNI_HOME': str(sdk)}

        def command(*args):
            return subprocess.run([str(OMNI), *map(str, args)], capture_output=True, timeout=120, env=env)

        def accepted(*args):
            result = command(*args)
            self.assertEqual(result.returncode, 0, result.stderr)
            return result.stdout

        accepted('package', 'lock', app, '--offline')
        accepted('check', source)
        doctor = subprocess.run([sys.executable, '-B', str(ROOT / 'tools/omni_sdk_doctor.py'),
                                 '--sdk-root', str(sdk)], capture_output=True, timeout=30)
        doctor_data = json.loads(doctor.stdout)
        self.assertEqual(doctor.returncode, 1)  # intentionally incomplete SDK fixture
        self.assertEqual(doctor_data['stdlib']['version'], std_data['version'])
        self.assertEqual(doctor_data['stdlib']['manifest'], (relative_std / 'omni.package.json').as_posix())
        self.assertIn({'component': 'omni_std', 'status': 'PASS'}, doctor_data['checks'])
        expected = json.loads(accepted('manifest', source))['program_content_id']
        for extension, writer in (('owave', 'wave'), ('owire', 'pack'), ('onme', 'onme')):
            artifact = self.ws / ('stdlib.' + extension)
            if writer == 'wave':
                artifact.write_bytes(accepted(writer, source))
            else:
                accepted(writer, source, '-o', artifact)
            accepted('check', artifact)
            self.assertEqual(json.loads(accepted('manifest', artifact))['program_content_id'], expected)
            self.assertEqual(command('eval', artifact).returncode, 42)
        binary = self.ws / 'std-app'
        accepted('build', source, '-o', binary)
        self.assertEqual(subprocess.run([str(binary)], env=env).returncode, 42)
        previous = binary.read_bytes()
        prelude = bundled / 'src/prelude.omni'
        original = prelude.read_bytes()
        prelude.write_bytes(original + b'\n// source commitment drift\n')
        refused = command('build', source, '-o', binary, '--force')
        self.assertEqual(refused.returncode, 2, refused.stderr)
        self.assertIn(b'E_PACKAGE_LOCK', refused.stderr)
        self.assertEqual(binary.read_bytes(), previous)
        prelude.write_bytes(original)
        inventory['components'][0]['sha256'] = '0' * 64
        inventory_path.write_text(json.dumps(inventory))
        refused_metadata = command('check', source)
        self.assertEqual(refused_metadata.returncode, 2)
        self.assertIn(b'E_PACKAGE_LOCK', refused_metadata.stderr)
        inventory['components'][0]['sha256'] = hashlib.sha256(std_manifest.read_bytes()).hexdigest()
        inventory_path.write_text(json.dumps(inventory))
        local = self.ws / 'missing-source'
        shutil.copytree(bundled, local)
        local_prelude = local / 'src/prelude.omni'
        text = local_prelude.read_text()
        old = 'return Ok<u32,u32>(value)'
        self.assertEqual(text.count(old), 1)
        local_prelude.write_text(text.replace(old, 'return Ok<u32,u32>(7u32)'))
        # The SDK lock cannot silently authorize a newly present local package.
        self.assertIn(b'E_PACKAGE_LOCK', command('check', source).stderr)
        accepted('package', 'lock', app, '--offline')
        accepted('check', source)
        self.assertEqual(command('eval', source).returncode, 7)
        inventory['components'].append(dict(inventory['components'][0]))
        inventory_path.write_text(json.dumps(inventory))
        ambiguous = command('check', source)
        self.assertEqual(ambiguous.returncode, 2)
        self.assertIn(b'E_PACKAGE_MANIFEST', ambiguous.stderr)
        inventory['components'].pop()
        outside = self.ws / 'outside-stdlib'
        shutil.copytree(bundled, outside)
        inventory['components'][0]['path'] = 'packages/../../outside-stdlib/omni.package.json'
        inventory_path.write_text(json.dumps(inventory))
        escaped = command('check', source)
        self.assertEqual(escaped.returncode, 2)
        self.assertIn(b'E_PACKAGE_PATH', escaped.stderr)

    def test_a_locked_library_is_consumed_without_copying_its_source_and_its_elements_stay_owned(self):
        self.lock()
        main = self.app / 'src' / 'main.omni'
        evaluated = proc(OMNI, 'eval', main, timeout=180)
        self.assertEqual(evaluated.returncode, 42, evaluated.stderr)
        native = self.ws / 'app-native'
        built = proc(OMNI, 'build', main, '-o', native, '--cache-dir', self.ws / 'cache', timeout=300)
        self.assertEqual(built.returncode, 0, built.stderr)
        executed = proc(native, timeout=180)
        self.assertEqual(executed.returncode, 42, executed.stderr)
        # nothing of the library was copied into the consumer
        self.assertEqual([p.name for p in (self.app / 'src').iterdir()], ['main.omni'])
        # and the elements are owned: dropping the sequence without destroying it does not compile, with the library imported the same way
        (self.app / 'src' / 'main.omni').write_text(APP.replace('let d u32 = seq.destroy<Tok>(move(s))\n    if d != 4u32 { code = 4u32 }\n', ''), encoding='utf-8')
        self.lock()
        checked = proc(OMNI, 'check', main)
        self.assertEqual(checked.returncode, 2, checked.stderr)
        self.assertIn(b'E_RESOURCE_UNCONSUMED', checked.stderr)

    def test_a_dependency_that_changed_after_the_lock_is_refused(self):
        self.lock()
        with open(self.lib / 'src' / 'seq.omni', 'a', encoding='utf-8') as f:
            f.write('\n// tampered after the lock\n')
        checked = proc(OMNI, 'check', self.app / 'src' / 'main.omni')
        self.assertEqual(checked.returncode, 2, checked.stderr)
        self.assertIn(b'E_PACKAGE_LOCK', checked.stderr)

    def test_without_a_lock_the_dependency_is_not_read(self):
        checked = proc(OMNI, 'check', self.app / 'src' / 'main.omni')
        self.assertEqual(checked.returncode, 2, checked.stderr)
        self.assertIn(b'E_PACKAGE_LOCK', checked.stderr)

    def test_what_is_refused_is_refused_with_the_code_that_names_it(self):
        self.lock()
        main = self.app / 'src' / 'main.omni'
        cases = [
            ('a dependency that is not declared', APP.replace('@acme.coll/seq.omni', '@acme.other/seq.omni'), b'E_IMPORT_PATH'),
            ('a path that escapes the dependency', APP.replace('@acme.coll/seq.omni', '@acme.coll/../omni.package.json'), b'E_IMPORT_PATH'),
            ('a path that climbs out of src', APP.replace('@acme.coll/seq.omni', '@acme.coll/../../app/src/main.omni'), b'E_IMPORT_PATH'),
            ('an absolute path after the dependency name', APP.replace('@acme.coll/seq.omni', '@acme.coll//etc/seq.omni'), b'E_IMPORT_PATH'),
            ('a dependency with no module name', APP.replace('@acme.coll/seq.omni', '@acme.coll'), b'E_IMPORT_PATH'),
            ('a file that is not a source file', APP.replace('@acme.coll/seq.omni', '@acme.coll/seq.txt'), b'E_IMPORT_PATH'),
            ('a module the dependency does not have', APP.replace('@acme.coll/seq.omni', '@acme.coll/missing.omni'), None),
        ]
        for label, text, code in cases:
            with self.subTest(label):
                main.write_text(text, encoding='utf-8')
                checked = proc(OMNI, 'check', main)
                self.assertEqual(checked.returncode, 2, (label, checked.stderr))
                if code:
                    self.assertIn(code, checked.stderr, checked.stderr)

    def test_a_file_outside_every_package_cannot_import_a_dependency(self):
        loose = self.ws / 'loose.omni'
        loose.write_text('module loose\nimport seq "@acme.coll/seq.omni"\nfunc main() u32 { return 0u32 }\n', encoding='utf-8')
        checked = proc(OMNI, 'check', loose)
        self.assertEqual(checked.returncode, 2, checked.stderr)
        self.assertIn(b'E_IMPORT_PATH', checked.stderr)

    def test_a_file_of_the_package_outside_src_cannot_import_a_dependency_either(self):
        self.lock()
        stray = self.app / 'stray.omni'
        stray.write_text('module stray\nimport seq "@acme.coll/seq.omni"\nfunc main() u32 { return 0u32 }\n', encoding='utf-8')
        checked = proc(OMNI, 'check', stray)
        self.assertEqual(checked.returncode, 2, checked.stderr)
        self.assertIn(b'E_IMPORT_PATH', checked.stderr)

    def test_a_module_name_that_both_packages_declare_is_a_duplicate(self):
        self.lock()
        clash = APP.replace('module app', 'module seq')
        main = self.app / 'src' / 'main.omni'
        main.write_text(clash, encoding='utf-8')
        self.lock()
        checked = proc(OMNI, 'check', main)
        self.assertEqual(checked.returncode, 2, checked.stderr)
        self.assertIn(b'E_DUPLICATE', checked.stderr)

    def test_the_relative_imports_of_a_dependency_stay_inside_it(self):
        # a dependency whose own file imports a sibling by a relative path works; one that tries to climb out of its src is refused
        (self.lib / 'src' / 'helper.omni').write_text('module helper\npub func two() u32 { return 2u32 }\n', encoding='utf-8')
        (self.lib / 'src' / 'user.omni').write_text('module user\nimport helper "helper.omni"\npub func three() u32 { return helper.two() + 1u32 }\n', encoding='utf-8')
        main = self.app / 'src' / 'main.omni'
        main.write_text('module app\nimport user "@acme.coll/user.omni"\nfunc main() u32 { return user.three() + 39u32 }\n', encoding='utf-8')
        self.lock()
        evaluated = proc(OMNI, 'eval', main)
        self.assertEqual(evaluated.returncode, 42, evaluated.stderr)
        (self.lib / 'src' / 'user.omni').write_text('module user\nimport out "../../app/src/main.omni"\npub func three() u32 { return 3u32 }\n', encoding='utf-8')
        self.lock()
        checked = proc(OMNI, 'check', main)
        self.assertEqual(checked.returncode, 2, checked.stderr)
        self.assertIn(b'E_IMPORT_PATH', checked.stderr)


if __name__ == '__main__':
    unittest.main()
