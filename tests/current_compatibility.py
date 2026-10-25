#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Federico T. Begna
# SPDX-License-Identifier: MIT OR Apache-2.0
"""Original compatibility behavior, with historical publication checks separated.

Four research/editorial presence checks are NOT_PORTABLE, not skipped passes.
Three mixed structural checks retain the applicable assertions below.
See COMPATIBILITY_COVERAGE.json for the precise mapping.
"""
import importlib.util, pathlib, unittest
ROOT=pathlib.Path(__file__).resolve().parents[1]

def load_tests(loader, tests, pattern):
    result=unittest.TestSuite()
    excluded={'test_research_baseline_present','test_mainline_identity_not_ecu',
              'test_numeric_research_and_patent_scan_present','test_research_and_fast_path_docs_exist'}
    for suffix in ('alpha','alpha1','alpha2','alpha3','alpha4'):
        path=ROOT/'tests'/f'language_0_2_{suffix}.py'
        spec=importlib.util.spec_from_file_location('compat_'+suffix,path)
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        for cls in list(vars(module).values()):
            if not isinstance(cls,type) or not issubclass(cls,unittest.TestCase):continue
            for name in excluded:
                if name in cls.__dict__:delattr(cls,name)
            if suffix=='alpha1':
                def test_normative_spec_set_exists(self):
                    for name in ('LANGUAGE_0_2.md','TYPE_MEMORY_CONSTITUTION_0_2.md','IR_WAVE_WIRE_0_2.md','DIAGNOSTICS_0_2.md','COMPATIBILITY_0_2.md','particle.ebnf','INDEX.md'):
                        self.assertTrue((ROOT/'spec'/name).is_file(),name)
                    self.assertFalse(any(ROOT.glob('spec/*DEV*.md')))
                def test_grammar_tracks_option(self):
                    grammar=(ROOT/'spec/particle.ebnf').read_text()
                    for token in ('"Option"','"Some"','"None"','match_option'):self.assertIn(token,grammar)
                    self.assertIn((ROOT/'VERSION').read_text().strip(),(ROOT/'compiler/src/omni.hpp').read_text())
                cls.test_normative_spec_set_exists=test_normative_spec_set_exists
                cls.test_grammar_tracks_option=test_grammar_tracks_option
            if suffix=='alpha3':
                def test_spec_research_and_design_around_present(self):
                    text=(ROOT/'spec/ADTS_0_2.md').read_text()
                    for token in ('closed nominal','E_MATCH_NON_EXHAUSTIVE','SisNervCent'):self.assertIn(token,text)
                cls.test_spec_research_and_design_around_present=test_spec_research_and_design_around_present
            result.addTests(loader.loadTestsFromTestCase(cls))
    return result

if __name__=='__main__':unittest.main(verbosity=2)
