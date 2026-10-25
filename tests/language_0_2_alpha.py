#!/usr/bin/env python3
from __future__ import annotations
import os, pathlib, subprocess, tempfile, unittest
ROOT=pathlib.Path(__file__).resolve().parents[1]
OMNI=pathlib.Path(os.environ.get('OMNI_TEST_BIN',ROOT/'bin/linux-x86_64/omni'))

def proc(*args,timeout=10): return subprocess.run([str(x) for x in args],capture_output=True,timeout=timeout)

class LanguageAlphaTests(unittest.TestCase):
    def setUp(self): self.t=tempfile.TemporaryDirectory(prefix='omni-lang-alpha-'); self.d=pathlib.Path(self.t.name)
    def tearDown(self): self.t.cleanup()
    def src(self,s,name='a.omni'): p=self.d/name; p.write_text(s,encoding='utf-8'); return p
    def test_option_native_some_none(self):
        p=ROOT/'examples/option.omni'
        e=proc(OMNI,'eval',p); self.assertEqual((e.returncode,e.stdout),(0,b'42\n99\n'),e.stderr)
        out=self.d/'app'; b=proc(OMNI,'build',p,'-o',out); self.assertEqual(b.returncode,0,b.stderr)
        n=proc(out); self.assertEqual((n.returncode,n.stdout),(0,b'42\n99\n'),n.stderr)
    def test_option_current_wave10_omc10_roundtrip(self):
        p=ROOT/'examples/option.omni'; w=proc(OMNI,'wave',p); self.assertEqual(w.returncode,0,w.stderr); self.assertTrue(w.stdout.startswith(b'(omni-wave 18'))
        wire=self.d/'x.owire'; q=proc(OMNI,'pack',p,'-o',wire); self.assertEqual(q.returncode,0,q.stderr); self.assertEqual(wire.read_bytes()[:8],b'OMCX\x12\x00\x00\x00')
        u=proc(OMNI,'unpack',wire); self.assertEqual(u.returncode,0,u.stderr); self.assertIn(b'Option<u32>',u.stdout); self.assertIn(b'Some(valor)',u.stdout); self.assertIn(b'None {',u.stdout)
        rt=self.src(u.stdout.decode()); c=proc(OMNI,'check',rt); self.assertEqual(c.returncode,0,c.stderr)
    def test_option_type_mismatch_rejected(self):
        p=self.src('module t func main() u32 { let x Option<u32> = Some<u32>(true); return 0; }')
        r=proc(OMNI,'check',p); self.assertEqual(r.returncode,2); self.assertIn(b'E_TYPE',r.stderr)
    def test_option_match_requires_option(self):
        p=self.src('module t func main() u32 { let x = 1; match x { Some(v) { return v; } None { return 0; } } }')
        r=proc(OMNI,'check',p); self.assertEqual(r.returncode,2); self.assertIn(b'E_TYPE',r.stderr)
    def test_option_borrow_and_abandoned_nested_pending_stay_rejected(self):
        for text,code in (('func f(x Option<Borrow<Buffer>>) u32 { return 0; } func main() u32 { return 0; }',b'E_TYPE'),
                          ('func f(x Option<Option<Resource<Buffer>>>) u32 { return 0; } func main() u32 { return 0; }',b'E_RESULT_UNHANDLED')):
            p=self.src('module t '+text)
            r=proc(OMNI,'check',p); self.assertEqual(r.returncode,2); self.assertIn(code,r.stderr)
    def test_prior_core_still_native(self):
        for name,expected in [('hola.omni',b'Hola, Omni\n720\n'),('sumatoria.omni',b'55\n')]:
            p=ROOT/'examples'/name; out=self.d/(name+'.bin'); b=proc(OMNI,'build',p,'-o',out); self.assertEqual(b.returncode,0,b.stderr); n=proc(out); self.assertEqual(n.stdout,expected,n.stderr)
    def test_result_still_works(self):
        p=ROOT/'examples/result_minimo.omni'; c=proc(OMNI,'check',p); self.assertEqual(c.returncode,0,c.stderr)
    def test_historical_wave5_loads(self):
        wf=ROOT/'reference/compat/legacy5.owave'
        self.assertTrue(wf.read_bytes().startswith(b'(omni-wave 5'))
        c=proc(OMNI,'check',wf); self.assertEqual(c.returncode,0,c.stderr)
        w=proc(OMNI,'wave',wf); self.assertEqual(w.returncode,0,w.stderr); self.assertTrue(w.stdout.startswith(b'(omni-wave 18'))
    def test_historical_omc5_loads(self):
        wf=ROOT/'reference/compat/legacy5.owire'
        self.assertEqual(wf.read_bytes()[:4],b'OMC5')
        c=proc(OMNI,'check',wf); self.assertEqual(c.returncode,0,c.stderr)
        w=proc(OMNI,'wave',wf); self.assertEqual(w.returncode,0,w.stderr); self.assertTrue(w.stdout.startswith(b'(omni-wave 18'))

if __name__=='__main__': unittest.main(verbosity=2)
