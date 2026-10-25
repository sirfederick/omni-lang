#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Federico T. Begna
# SPDX-License-Identifier: MIT OR Apache-2.0
"""Fault injection against the actual verifier, without mutating real inputs."""
import contextlib,io,json,pathlib,sys,unittest
from unittest.mock import patch
ROOT=pathlib.Path(__file__).resolve().parents[1]
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

    def test_rejects_reserved_editorial_readme(self):
        original=pathlib.Path.exists
        with patch.object(pathlib.Path,'exists',lambda p:True if p==ROOT/'README.md' else original(p)):
            self.assert_rejected('reserved/unexpected README.md')

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

if __name__=='__main__':unittest.main(verbosity=2)
