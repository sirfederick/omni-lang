#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Federico T. Begna
# SPDX-License-Identifier: MIT OR Apache-2.0
"""Fault injection against the actual verifier, without mutating real inputs."""
import contextlib,io,json,pathlib,sys,tempfile,unittest
from unittest.mock import patch
ROOT=pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
SCRIPT=ROOT/'tools/check_spec_sync.py'

class StructuralFaultInjection(unittest.TestCase):
    def check_fault(self,path,transform,diagnostic):
        original=pathlib.Path.read_text
        def read(p,*args,**kwargs):
            text=original(p,*args,**kwargs)
            return transform(text) if p==ROOT/path else text
        output=io.StringIO()
        with patch.object(pathlib.Path,'read_text',read),contextlib.redirect_stdout(output):
            try:exec(compile(original(SCRIPT),str(SCRIPT),'exec'),{'__file__':str(SCRIPT),'__name__':'__main__'})
            except SystemExit as e:code=e.code
        report=json.loads(output.getvalue())
        self.assertEqual(code,1);self.assertEqual(report['status'],'FAIL')
        self.assertTrue(any(diagnostic in error for error in report['errors']),report)

    def test_rejects_mismatching_product_header(self):
        self.check_fault('compiler/src/omni.hpp',lambda s:s.replace('VERSION = "0.1.0.00"','VERSION = "9.9.9.99"'),'compiler VERSION mismatch')

    def test_rejects_missing_loan_grammar(self):
        self.check_fault('spec/particle.ebnf',lambda s:s.replace('"BorrowMut"','"MissingLoan"'),'grammar missing "BorrowMut"')

    def test_rejects_unresolved_compilation_unit(self):
        self.check_fault('tools/core_sources.txt',lambda s:s.replace('compiler/src/particle.cpp','compiler/src/nonexistent.cpp'),'core source manifest missing file')

    def test_rejects_private_profile_authority_in_general_registry(self):
        self.check_fault('compiler/src/capabilities.cpp',lambda s:s+'\n// model.call\n','profile capability leaked into Core registry')

class TreeFaultInjection(unittest.TestCase):
    def setUp(self):
        import importlib.util
        spec=importlib.util.spec_from_file_location('tree_verifier',ROOT/'tools/verify_tree.py')
        self.verifier=importlib.util.module_from_spec(spec);spec.loader.exec_module(self.verifier)

    def assert_rejected(self,diagnostic):
        out=io.StringIO()
        with patch.object(sys,'argv',['verify_tree.py']),contextlib.redirect_stdout(out):
            code=self.verifier.main()
        self.assertTrue(code)
        self.assertTrue(any(diagnostic in s for s in json.loads(out.getvalue())['errors']),out.getvalue())

    def test_accepts_actual_tree(self):
        report = self.verifier.verify()
        self.assertEqual(report['status'], 'PASS', report['errors'])

    def test_rejects_missing_license_annotation(self):
        original=pathlib.Path.read_text
        def read(p,*a,**kw):
            text=original(p,*a,**kw)
            return text.replace('"compiler/src/check.cpp",','') if p==ROOT/'REUSE.toml' else text
        with patch.object(pathlib.Path,'read_text',read):
            self.assert_rejected('license annotations missing: compiler/src/check.cpp')

    def test_rejects_machine_path_in_public_source(self):
        original=pathlib.Path.read_bytes
        def read(p):
            data=original(p)
            if p==ROOT/'compiler/src/check.cpp':data+=('\n// Z:'+chr(92)+'dev'+chr(92)+'sensitive').encode()
            return data
        with patch.object(pathlib.Path,'read_bytes',read):
            self.assert_rejected('private reference compiler/src/check.cpp')

class ExportAndWorktreeTests(unittest.TestCase):
    def setUp(self):
        import verify_tree
        self.verifier = verify_tree
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = pathlib.Path(self.temp.name)
        for name in ('README.md', 'README.es.md', 'DEVELOPMENT.md', 'spec/INDEX.md', 'spec/README.md',
                     'examples/README.md', 'tests/README.md', 'docs/language/CAPABILITY_STATUS.md',
                     'docs/language/FEATURES.md', 'LICENSE-MIT', 'LICENSE-APACHE',
                     'compiler/src/main.cpp', *verify_tree.SDK_ONLY_SOURCES):
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('fixture\n', encoding='utf-8')
        (self.root / 'VERSION').write_text('0.1.0.00\n')
        (self.root / 'stdlib').mkdir()
        (self.root / 'stdlib/omni.package.json').write_text(json.dumps({'name': 'omni.std', 'version': '0.8.4-alpha.8'}))
        (self.root / 'tools').mkdir()
        (self.root / 'tools/core_sources.txt').write_text('compiler/src/main.cpp\n')
        self.annotate()

    def annotate(self):
        paths = sorted(path.relative_to(self.root).as_posix() for path in self.root.rglob('*')
                       if path.is_file() and path.name not in ('REUSE.toml', 'LICENSE-MIT', 'LICENSE-APACHE', '.git'))
        (self.root / 'REUSE.toml').write_text('version = 1\n[[annotations]]\npath = '+json.dumps(paths)+'\n')

    def check(self):
        return self.verifier.verify(self.root)

    def test_source_export(self):
        self.assertEqual(self.check()['status'], 'PASS')

    def test_git_directory_is_not_public_content(self):
        (self.root / '.git').mkdir()
        (self.root / '.git/opaque').write_bytes(b'\xff')
        self.assertEqual(self.check()['status'], 'PASS')

    def test_worktree_pointer_is_not_public_content(self):
        (self.root / '.git').write_bytes(b'gitdir: ignored\xff')
        self.assertEqual(self.check()['status'], 'PASS')

    def test_legitimate_added_compiler_unit(self):
        (self.root / 'compiler/src/new.cpp').write_text('// new compilation unit\n')
        with (self.root / 'tools/core_sources.txt').open('a') as handle:
            handle.write('compiler/src/new.cpp\n')
        self.annotate()
        self.assertEqual(self.check()['status'], 'PASS')

    def test_duplicate_unit_rejected(self):
        (self.root / 'tools/core_sources.txt').write_text('compiler/src/main.cpp\ncompiler/src/main.cpp\n')
        self.assertIn('canonical compiler sources must be nonempty and unique', self.check()['errors'])

    def test_broken_link_rejected(self):
        (self.root / 'README.md').write_text('[broken](missing.md)\n')
        self.assertTrue(any('broken link' in error for error in self.check()['errors']))

    def test_broken_native_path_rejected(self):
        (self.root / 'tools/core_sources.txt').write_text('compiler/src/missing.cpp\n')
        self.assertTrue(any('bad native unit' in error for error in self.check()['errors']))

    def test_binary_fixture_boundary(self):
        (self.root / 'tests/legacy.owire').write_bytes(b'\xff')
        self.annotate()
        self.assertEqual(self.check()['status'], 'PASS')
        (self.root / 'tests/unknown.data').write_bytes(b'\xff')
        self.annotate()
        self.assertTrue(any('unclassified non-text' in error for error in self.check()['errors']))

    def test_both_private_prompt_aliases_ignored(self):
        for alias in ('prompts', 'promts'):
            directory = self.root / 'docs' / alias
            directory.mkdir(parents=True)
            (directory / 'private.py').write_text('not valid syntax !')
        self.assertEqual(self.check()['status'], 'PASS')


if __name__=='__main__':unittest.main(verbosity=2)
