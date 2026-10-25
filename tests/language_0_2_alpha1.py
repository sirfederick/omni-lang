#!/usr/bin/env python3
from __future__ import annotations
import json, os, pathlib, subprocess, tempfile, unittest
ROOT=pathlib.Path(__file__).resolve().parents[1]
OMNI=pathlib.Path(os.environ.get('OMNI_TEST_BIN',ROOT/'bin/linux-x86_64/omni'))

def proc(*args,timeout=15):
    return subprocess.run([str(x) for x in args],capture_output=True,timeout=timeout,env={**os.environ,'OMNI_HOME':str(ROOT)})

class FoundationReconciliationTests(unittest.TestCase):
    def setUp(self): self.tmp=tempfile.TemporaryDirectory(prefix='omni-alpha1-'); self.d=pathlib.Path(self.tmp.name)
    def tearDown(self): self.tmp.cleanup()
    def source(self,text,name='a.omni'):
        p=self.d/name;p.write_text(text,encoding='utf-8');return p

    def test_version_identity(self):
        r=proc(OMNI,'--version'); self.assertEqual(r.returncode,0,r.stderr); self.assertEqual(r.stdout.strip(),b'omni '+(ROOT/'VERSION').read_bytes().strip())

    def test_normative_spec_set_exists(self):
        for name in ['LANGUAGE_0_2.md','TYPE_MEMORY_CONSTITUTION_0_2.md','IR_WAVE_WIRE_0_2.md','DIAGNOSTICS_0_2.md','COMPATIBILITY_0_2.md','CONFORMANCE_0_2.md','particle.ebnf']:
            self.assertTrue((ROOT/'spec'/name).is_file(),name)
        self.assertFalse(any(ROOT.glob('spec/*DEV*.md')))

    def test_grammar_tracks_option(self):
        g=(ROOT/'spec/particle.ebnf').read_text(encoding='utf-8')
        for token in ['"Option"','"Some"','"None"','match_option']:
            self.assertIn(token,g)
        self.assertIn((ROOT/'VERSION').read_text().strip(),g)

    def test_json_diagnostic_schema(self):
        p=self.source('module t\nfunc main() u32 {\n let x u32 = true\n return 0\n}\n')
        r=proc(OMNI,'check',p,'--diagnostic-format','json'); self.assertEqual(r.returncode,2,r.stderr)
        d=json.loads(r.stderr); self.assertEqual(d['schema'],'omni.diagnostic/1'); self.assertEqual(d['code'],'E_TYPE'); self.assertEqual(d['category'],'types'); self.assertEqual(d['span']['line'],3); self.assertGreater(d['span']['column'],0)

    def test_text_diagnostic_code_remains_stable(self):
        p=self.source('module t func main() u32 { return true; }')
        r=proc(OMNI,'check',p); self.assertEqual(r.returncode,2); self.assertTrue(r.stderr.startswith(b'E_TYPE:'))

    def test_diagnostic_registry(self):
        r=proc(OMNI,'diagnostics'); self.assertEqual(r.returncode,0,r.stderr); d=json.loads(r.stdout)
        self.assertEqual(d['schema'],'omni.diagnostics-registry/1')
        by={x['code']:x['category'] for x in d['codes']}; self.assertEqual(by['E_TYPE'],'types'); self.assertEqual(by['E_PARSE'],'syntax'); self.assertEqual(by['E_RESOURCE_MOVED'],'memory-resource')

    def test_historical_wave_1_to_6_are_self_contained(self):
        for version in range(1,7):
            p=ROOT/'reference/compat'/f'legacy{version}.owave'; self.assertTrue(p.is_file(),p)
            self.assertTrue(p.read_bytes().startswith(f'(omni-wave {version}'.encode()))
            c=proc(OMNI,'check',p); self.assertEqual(c.returncode,0,(version,c.stderr))
            w=proc(OMNI,'wave',p); self.assertEqual(w.returncode,0,w.stderr); self.assertTrue(w.stdout.startswith(b'(omni-wave 18'))

    def test_historical_wire_1_to_6_are_self_contained(self):
        for version in range(1,7):
            p=ROOT/'reference/compat'/f'legacy{version}.owire'; self.assertTrue(p.is_file(),p); self.assertEqual(p.read_bytes()[:4],f'OMC{version}'.encode())
            c=proc(OMNI,'check',p); self.assertEqual(c.returncode,0,(version,c.stderr))
            w=proc(OMNI,'wave',p); self.assertEqual(w.returncode,0,w.stderr); self.assertTrue(w.stdout.startswith(b'(omni-wave 18'))

    def test_option_type_arguments_are_invariant(self):
        p=self.source('module t func f() Option<bool> { return Some<bool>(true) } func main() u32 { let x Option<u32> = f(); return 0; }')
        r=proc(OMNI,'check',p); self.assertEqual(r.returncode,2); self.assertIn(b'E_TYPE',r.stderr)

    def test_match_arm_order_is_semantic_not_syntactic(self):
        p=self.source('module t func main() u32 { let x Option<u32> = None<u32>(); match x { None { return 0; } Some(v) { return v; } } }')
        r=proc(OMNI,'check',p); self.assertEqual(r.returncode,0,r.stderr)

    def test_current_writer_is_wave10_omc10(self):
        p=ROOT/'examples/option.omni'; w=proc(OMNI,'wave',p); self.assertTrue(w.stdout.startswith(b'(omni-wave 18'))
        out=self.d/'x.owire'; q=proc(OMNI,'pack',p,'-o',out); self.assertEqual(q.returncode,0,q.stderr); self.assertEqual(out.read_bytes()[:8],b'OMCX\x12\x00\x00\x00')

    def test_formatter_idempotence_option(self):
        p=ROOT/'examples/option.omni'; a=proc(OMNI,'fmt',p); self.assertEqual(a.returncode,0,a.stderr)
        q=self.source(a.stdout.decode(),'formatted.omni'); b=proc(OMNI,'fmt',q); self.assertEqual(b.returncode,0,b.stderr); self.assertEqual(a.stdout,b.stdout)

    def test_research_baseline_present(self):
        idx=(ROOT/'docs/research/PATENT_INTELLIGENCE_INDEX.md').read_text(encoding='utf-8')
        scan=(ROOT/'docs/research/TYPE_SYSTEM_TECHNOLOGY_SCAN_2026-09-19.md').read_text(encoding='utf-8')
        for x in ['US20220179949A1','EP4246316A1','US20250306874A1','DESIGN_AROUND','FTO_REQUIRED']:
            self.assertIn(x,idx+scan)

    def test_mainline_identity_not_ecu(self):
        self.assertIn('Omni Language '+(ROOT/'VERSION').read_text().strip(),(ROOT/'README.md').read_text())
        self.assertIn('general-purpose language mainline',(ROOT/'SECURITY.md').read_text())
        self.assertNotIn('Seguridad y límites — Omni Core 0.1.0-dev.6.1',(ROOT/'SECURITY.md').read_text())

if __name__=='__main__': unittest.main(verbosity=2)
