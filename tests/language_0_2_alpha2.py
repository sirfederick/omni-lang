#!/usr/bin/env python3
from __future__ import annotations
import json, os, pathlib, subprocess, tempfile, unittest
ROOT=pathlib.Path(__file__).resolve().parents[1]
OMNI=pathlib.Path(os.environ.get('OMNI_TEST_BIN',ROOT/'bin/linux-x86_64/omni'))

def proc(*args,timeout=20):
    return subprocess.run([str(x) for x in args],capture_output=True,timeout=timeout,env={**os.environ,'OMNI_HOME':str(ROOT)})

class NumericFoundationTests(unittest.TestCase):
    def setUp(self): self.tmp=tempfile.TemporaryDirectory(prefix='omni-alpha2-'); self.d=pathlib.Path(self.tmp.name)
    def tearDown(self): self.tmp.cleanup()
    def source(self,text,name='a.omni'):
        p=self.d/name; p.write_text(text,encoding='utf-8'); return p
    def check_ok(self,text):
        r=proc(OMNI,'check',self.source(text)); self.assertEqual(r.returncode,0,r.stderr); return r
    def check_err(self,text,code):
        r=proc(OMNI,'check',self.source(text)); self.assertEqual(r.returncode,2,r.stderr); self.assertIn(code.encode(),r.stderr); return r
    def eval_out(self,text):
        p=self.source(text); r=proc(OMNI,'eval',p); self.assertEqual(r.returncode,0,r.stderr); return r.stdout
    def native(self,text):
        p=self.source(text); out=self.d/'native'; b=proc(OMNI,'build',p,'-o',out); self.assertEqual(b.returncode,0,b.stderr); return proc(out)

    def test_version_identity(self):
        r=proc(OMNI,'--version'); self.assertEqual(r.returncode,0,r.stderr); self.assertEqual(r.stdout.strip(),b'omni '+(ROOT/'VERSION').read_bytes().strip())

    def test_all_standard_integer_types_parse_and_execute(self):
        src='''module t
func main() u32 !{io.print} {
 let a u8 = 255u8
 let b u16 = 65535u16
 let c u32 = 4294967295u32
 let d u64 = 18446744073709551615u64
 let e i8 = -128i8
 let f i16 = -32768i16
 let g i32 = -2147483648i32
 let h i64 = -9223372036854775808i64
 print(a); print(b); print(c); print(d); print(e); print(f); print(g); print(h);
 return 0
}'''
        expected=b'255\n65535\n4294967295\n18446744073709551615\n-128\n-32768\n-2147483648\n-9223372036854775808\n'
        self.assertEqual(self.eval_out(src),expected)
        n=self.native(src); self.assertEqual((n.returncode,n.stdout),(0,expected),n.stderr)

    def test_positive_literal_boundaries_reject_overflow(self):
        cases=[('u8','256u8'),('u16','65536u16'),('u32','4294967296u32'),('i8','128i8'),('i16','32768i16'),('i32','2147483648i32'),('i64','9223372036854775808i64')]
        for typ,lit in cases:
            with self.subTest(typ=typ): self.check_err(f'module t func main() u32 {{ let x {typ} = {lit}; return 0; }}','E_OVERFLOW_LITERAL')

    def test_unsigned_unary_minus_rejected(self):
        self.check_err('module t func main() u32 { let x u8 = -1u8; return 0; }','E_TYPE')

    def test_no_implicit_mixed_integer_arithmetic(self):
        self.check_err('module t func main() u32 { let a u8=1u8; let b u16=2u16; let c u16=a+b; return 0; }','E_TYPE')

    def test_explicit_widening_cast(self):
        src='module t func main() u32 !{io.print} { let a u8=250u8; let b u16=u16(a); print(b); return 0; }'
        self.assertEqual(self.eval_out(src),b'250\n'); n=self.native(src); self.assertEqual((n.returncode,n.stdout),(0,b'250\n'),n.stderr)

    def test_narrowing_cast_runtime_range_error_eval_and_native(self):
        src='module t func main() u32 { let a u16=300u16; let b u8=u8(a); return u32(b); }'; p=self.source(src)
        e=proc(OMNI,'eval',p); self.assertNotEqual(e.returncode,0); self.assertIn(b'E_CAST_RANGE',e.stderr)
        out=self.d/'narrow'; b=proc(OMNI,'build',p,'-o',out); self.assertEqual(b.returncode,0,b.stderr); n=proc(out); self.assertNotEqual(n.returncode,0); self.assertIn(b'E_CAST_RANGE',n.stderr)

    def test_checked_overflow_is_deterministic_eval_and_native(self):
        src='module t func main() u32 { let a u8=255u8; let b u8=a+1u8; return u32(b); }'; p=self.source(src)
        e=proc(OMNI,'eval',p); self.assertNotEqual(e.returncode,0); self.assertIn(b'E_OVERFLOW',e.stderr)
        out=self.d/'overflow'; b=proc(OMNI,'build',p,'-o',out); self.assertEqual(b.returncode,0,b.stderr); n=proc(out); self.assertNotEqual(n.returncode,0); self.assertIn(b'E_OVERFLOW',n.stderr)

    def test_wrapping_operators(self):
        src='''module t func main() u32 !{io.print} {
 let a u8=250u8 +% 10u8
 let b u8=2u8 -% 5u8
 let c u8=100u8 *% 3u8
 let d i8=127i8 +% 1i8
 print(a); print(b); print(c); print(d); return 0 }'''
        expected=b'4\n253\n44\n-128\n'; self.assertEqual(self.eval_out(src),expected); n=self.native(src); self.assertEqual((n.returncode,n.stdout),(0,expected),n.stderr)

    def test_saturating_operators(self):
        src='''module t func main() u32 !{io.print} {
 let a u8=250u8 +| 10u8
 let b u8=2u8 -| 5u8
 let c u8=100u8 *| 3u8
 let d i8=127i8 +| 1i8
 let e i8=-128i8 -| 1i8
 print(a); print(b); print(c); print(d); print(e); return 0 }'''
        expected=b'255\n0\n255\n127\n-128\n'; self.assertEqual(self.eval_out(src),expected); n=self.native(src); self.assertEqual((n.returncode,n.stdout),(0,expected),n.stderr)

    def test_signed_division_semantics_and_min_overflow(self):
        src='module t func main() u32 !{io.print} { let a i8=-7i8; let b i8=3i8; print(a/b); print(a%b); return 0 }'
        self.assertEqual(self.eval_out(src),b'-2\n-1\n'); n=self.native(src); self.assertEqual((n.returncode,n.stdout),(0,b'-2\n-1\n'),n.stderr)
        bad='module t func main() u32 { let a i8=-128i8; let b i8=a / -1i8; return u32(b); }'; p=self.source(bad,'div_over.omni')
        e=proc(OMNI,'eval',p); self.assertNotEqual(e.returncode,0); self.assertIn(b'E_OVERFLOW',e.stderr)
        out=self.d/'div_over'; b=proc(OMNI,'build',p,'-o',out); self.assertEqual(b.returncode,0,b.stderr); n=proc(out); self.assertNotEqual(n.returncode,0); self.assertIn(b'E_OVERFLOW',n.stderr)

    def test_signed_comparisons_use_signed_order(self):
        src='module t func main() u32 !{io.print} { let a i8=-1i8; let b i8=1i8; if a < b { print(1) } else { print(0) } return 0 }'
        self.assertEqual(self.eval_out(src),b'1\n'); n=self.native(src); self.assertEqual((n.returncode,n.stdout),(0,b'1\n'),n.stderr)

    def test_numeric_example_eval_native_match(self):
        p=ROOT/'examples/numeric.omni'; e=proc(OMNI,'eval',p); self.assertEqual(e.returncode,0,e.stderr)
        out=self.d/'numeric'; b=proc(OMNI,'build',p,'-o',out); self.assertEqual(b.returncode,0,b.stderr); n=proc(out)
        self.assertEqual((n.returncode,n.stdout),(0,e.stdout),n.stderr); self.assertEqual(e.stdout,b'255\n4\n255\n-10\n255\n')

    def test_current_writer_is_wave8_omc8(self):
        p=ROOT/'examples/numeric.omni'; w=proc(OMNI,'wave',p); self.assertEqual(w.returncode,0,w.stderr); self.assertTrue(w.stdout.startswith(b'(omni-wave 18'))
        self.assertIn(b'(u8 250)',w.stdout); out=self.d/'x.owire'; q=proc(OMNI,'pack',p,'-o',out); self.assertEqual(q.returncode,0,q.stderr); self.assertEqual(out.read_bytes()[:8],b'OMCX\x12\x00\x00\x00')
        u=proc(OMNI,'unpack',out); self.assertEqual(u.returncode,0,u.stderr); c=proc(OMNI,'check',self.source(u.stdout.decode(),'roundtrip.omni')); self.assertEqual(c.returncode,0,c.stderr)

    def test_extended_integer_semantics_cannot_hide_under_old_headers(self):
        current=proc(OMNI,'wave',ROOT/'examples/numeric.omni'); self.assertEqual(current.returncode,0,current.stderr)
        fake=self.d/'fake6.owave'; fake.write_bytes(current.stdout.replace(b'(omni-wave 18',b'(omni-wave 6',1))
        r=proc(OMNI,'check',fake); self.assertEqual(r.returncode,2); self.assertIn(b'E_VERSION',r.stderr)
        wire=self.d/'current.owire'; q=proc(OMNI,'pack',ROOT/'examples/numeric.omni','-o',wire); self.assertEqual(q.returncode,0,q.stderr)
        raw=bytearray(wire.read_bytes()); raw[:4]=b'OMC6'; fakew=self.d/'fake6.owire'; fakew.write_bytes(raw)
        r=proc(OMNI,'check',fakew); self.assertEqual(r.returncode,2)

    def test_historical_wave_and_wire_1_to_6_canonicalize_to_wave8(self):
        for version in range(1,7):
            with self.subTest(kind='wave',version=version):
                p=ROOT/'reference/compat'/f'legacy{version}.owave'; self.assertTrue(p.is_file()); c=proc(OMNI,'check',p); self.assertEqual(c.returncode,0,(version,c.stderr)); w=proc(OMNI,'wave',p); self.assertEqual(w.returncode,0,w.stderr); self.assertTrue(w.stdout.startswith(b'(omni-wave 18'))
            with self.subTest(kind='wire',version=version):
                p=ROOT/'reference/compat'/f'legacy{version}.owire'; self.assertTrue(p.is_file()); self.assertEqual(p.read_bytes()[:4],f'OMC{version}'.encode()); c=proc(OMNI,'check',p); self.assertEqual(c.returncode,0,(version,c.stderr)); w=proc(OMNI,'wave',p); self.assertEqual(w.returncode,0,w.stderr); self.assertTrue(w.stdout.startswith(b'(omni-wave 18'))

    def test_type_descriptor_is_stable_and_distinct(self):
        a=proc(OMNI,'type','describe','i64'); b=proc(OMNI,'type','describe','i64'); c=proc(OMNI,'type','describe','u64')
        self.assertEqual(a.returncode,0,a.stderr); da=json.loads(a.stdout); db=json.loads(b.stdout); dc=json.loads(c.stdout)
        self.assertEqual(da['schema'],'omni.type-descriptor/2'); self.assertEqual(da['type_identity_domain'],'omni.type/1'); self.assertEqual(da['type_id'],db['type_id']); self.assertNotEqual(da['type_id'],dc['type_id']); self.assertEqual(da['width_bits'],64); self.assertTrue(da['signed']); self.assertEqual(da['legacy_descriptor_schema'],'omni.type-descriptor/1'); self.assertIn('legacy_descriptor_id',da)

    def test_type_descriptor_is_identity_not_authority(self):
        spec=(ROOT/'spec/TYPE_IDENTITY_0_2.md').read_text(encoding='utf-8')
        for phrase in ['does not grant authority','does not identify a runtime object','does not imply persistence','SisNervCent']:
            self.assertIn(phrase,spec)

    def test_numeric_research_and_patent_scan_present(self):
        p=(ROOT/'docs/research/INTEGER_NUMERIC_TECHNOLOGY_SCAN_2026-09-19.md').read_text(encoding='utf-8')
        for x in ['Go','C23','Rust','Zig','US5836014A','EP0528008A1','US8056064B2','DESIGN_AROUND']:
            self.assertIn(x,p)

if __name__=='__main__': unittest.main(verbosity=2)
