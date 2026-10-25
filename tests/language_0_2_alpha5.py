#!/usr/bin/env python3
from __future__ import annotations
import json, os, pathlib, subprocess, tempfile, unittest
ROOT=pathlib.Path(__file__).resolve().parents[1]
OMNI=pathlib.Path(os.environ.get('OMNI_TEST_BIN',ROOT/'bin/linux-x86_64/omni'))
def proc(*args,timeout=30): return subprocess.run([str(x) for x in args],capture_output=True,timeout=timeout,env={**os.environ,'OMNI_HOME':str(ROOT)})
class BorrowedViewTests(unittest.TestCase):
    def setUp(self): self.tmp=tempfile.TemporaryDirectory(prefix='omni-alpha5-'); self.d=pathlib.Path(self.tmp.name)
    def tearDown(self): self.tmp.cleanup()
    def source(self,text,name='a.omni'): p=self.d/name; p.write_text(text,encoding='utf-8'); return p
    def check_ok(self,text):
        r=proc(OMNI,'check',self.source(text)); self.assertEqual(r.returncode,0,r.stderr); return r
    def check_err(self,text,code):
        r=proc(OMNI,'check',self.source(text)); self.assertEqual(r.returncode,2,r.stderr); self.assertIn(code.encode(),r.stderr); return r
    def native(self,text,name='app'):
        p=self.source(text); out=self.d/name; b=proc(OMNI,'build',p,'-o',out,'--no-cache'); self.assertEqual(b.returncode,0,b.stderr); return proc(out)
    def test_version(self): self.assertEqual(proc(OMNI,'--version').stdout.strip(),b'omni '+(ROOT/'VERSION').read_bytes().strip())
    def test_view_basic_eval_native(self):
        src='module t func main() u32 !{io.print} { let a Array<u32,4>=array(10u32,20u32,30u32,40u32); let v View<u32>=view(a); print(view.len(v)); print(view.get(v,2u32)); return view.get(v,3u32) }'
        p=self.source(src); e=proc(OMNI,'eval',p); self.assertEqual((e.returncode,e.stdout),(40,b'4\n30\n'),e.stderr); out=self.d/'n'; self.assertEqual(proc(OMNI,'build',p,'-o',out,'--no-cache').returncode,0); n=proc(out); self.assertEqual((n.returncode,n.stdout),(40,e.stdout),n.stderr)
    def test_subview_and_function_boundary(self):
        src='module t func sum(v View<u32>) u32 { return view.get(v,0u32)+view.get(v,1u32) } func main() u32 !{io.print} { let a=array(5u32,7u32,11u32,13u32); let v=view(a); let s=view.sub(v,1u32,2u32); print(view.len(s)); print(view.get(s,1u32)); return sum(s) }'
        p=self.source(src); e=proc(OMNI,'eval',p); self.assertEqual((e.returncode,e.stdout),(18,b'2\n11\n'),e.stderr); out=self.d/'n'; self.assertEqual(proc(OMNI,'build',p,'-o',out,'--no-cache').returncode,0); n=proc(out); self.assertEqual((n.returncode,n.stdout),(18,e.stdout),n.stderr)
    def test_zero_length_view_and_end_subview(self):
        src='module t func main() u32 !{io.print} { let a Array<u8,0>=array.fill(7u8,0u32); let v=view(a); let s=view.sub(v,0u32,0u32); print(view.len(v)); print(view.len(s)); return 0 }'
        p=self.source(src); e=proc(OMNI,'eval',p); self.assertEqual((e.returncode,e.stdout),(0,b'0\n0\n'),e.stderr); out=self.d/'n'; self.assertEqual(proc(OMNI,'build',p,'-o',out,'--no-cache').returncode,0); n=proc(out); self.assertEqual((n.returncode,n.stdout),(0,e.stdout),n.stderr)
    def test_subview_at_array_end_zero_length(self):
        src='module t func main() u32 { let a=array(1u32,2u32); let v=view(a); let z=view.sub(v,2u32,0u32); return view.len(z) }'
        self.assertEqual(self.native(src).returncode,0)
    def test_view_get_bounds_eval_native(self):
        src='module t func main() u32 { let a=array(1u32,2u32); let v=view(a); let i u32=2u32; return view.get(v,i) }'; p=self.source(src)
        e=proc(OMNI,'eval',p); self.assertNotEqual(e.returncode,0); self.assertIn(b'E_BOUNDS',e.stderr)
        out=self.d/'bad'; self.assertEqual(proc(OMNI,'build',p,'-o',out,'--no-cache').returncode,0); n=proc(out); self.assertNotEqual(n.returncode,0); self.assertIn(b'E_BOUNDS',n.stderr)
    def test_subview_bounds_eval_native(self):
        src='module t func main() u32 { let a=array(1u32,2u32,3u32); let v=view(a); let s=view.sub(v,2u32,2u32); return view.len(s) }'; p=self.source(src)
        e=proc(OMNI,'eval',p); self.assertNotEqual(e.returncode,0); self.assertIn(b'E_BOUNDS',e.stderr)
        out=self.d/'bad'; self.assertEqual(proc(OMNI,'build',p,'-o',out,'--no-cache').returncode,0); n=proc(out); self.assertNotEqual(n.returncode,0); self.assertIn(b'E_BOUNDS',n.stderr)
    def test_subview_offset_overflow_safe(self):
        src='module t func main() u32 { let a=array(1u32,2u32); let v=view(a); let s=view.sub(v,4294967295u32,2u32); return view.len(s) }'; p=self.source(src)
        e=proc(OMNI,'eval',p); self.assertNotEqual(e.returncode,0); self.assertIn(b'E_BOUNDS',e.stderr)
        out=self.d/'bad'; self.assertEqual(proc(OMNI,'build',p,'-o',out,'--no-cache').returncode,0); n=proc(out); self.assertNotEqual(n.returncode,0); self.assertIn(b'E_BOUNDS',n.stderr)
    def test_view_requires_reference_source(self): self.check_err('module t func main() u32 { let v=view(array(1u32,2u32)); return 0 }','E_VIEW_SOURCE')
    def test_view_requires_array_source(self): self.check_err('module t func main() u32 { let x u32=1u32; let v=view(x); return 0 }','E_VIEW_SOURCE')
    def test_view_rejects_mutable_array_source(self): self.check_err('module t func main() u32 { var a=array(1u32,2u32); let v=view(a); return view.len(v) }','E_VIEW_SOURCE')
    def test_view_binding_cannot_be_var(self): self.check_err('module t func main() u32 { let a=array(1u32,2u32); var v View<u32>=view(a); return 0 }','E_VIEW_MUTABLE')
    def test_view_cannot_escape_return(self): self.check_err('module t func f(a Array<u32,2>) View<u32> { return view(a) } func main() u32 { return 0 }','E_VIEW_ESCAPE')
    def test_view_cannot_store_in_struct(self): self.check_err('module t struct S { v View<u32> } func main() u32 { return 0 }','E_TYPE')
    def test_view_cannot_store_in_enum(self): self.check_err('module t enum E { V(View<u32>), } func main() u32 { return 0 }','E_TYPE')
    def test_view_cannot_nest_in_tuple(self): self.check_err('module t func main() u32 { let a=array(1u32,2u32); let v=view(a); let t=tuple(v); return 0 }','E_PRODUCT_LINEAR')
    def test_view_cannot_nest_in_array(self): self.check_err('module t func main() u32 { let a=array(1u32,2u32); let v=view(a); let x=array(v,v); return 0 }','E_PRODUCT_LINEAR')
    def test_view_cannot_nest_in_option(self): self.check_err('module t func f(v View<u32>) u32 { let x Option<View<u32>>=Some<View<u32>>(v); return 0 } func main() u32 { return 0 }','E_TYPE')
    def test_nested_view_type_rejected(self): self.check_err('module t func f(v View<View<u32>>) u32 { return 0 } func main() u32 { return 0 }','E_TYPE')
    def test_slice_not_promoted_in_alpha5(self):
        r=proc(OMNI,'type','describe','Slice<u32>'); self.assertEqual(r.returncode,2); self.assertIn(b'E_TYPE',r.stderr)
    def test_view_type_descriptor_is_borrowed_non_authority_surface(self):
        d=json.loads(proc(OMNI,'type','describe','View<u32>').stdout); self.assertEqual(d['kind'],'borrowed-view'); self.assertEqual(d['element_type'],'u32'); self.assertEqual(d['ownership'],'borrowed-readonly'); self.assertFalse(d['portable_address']); self.assertIn('type_id',d); self.assertNotIn('capability',d); self.assertNotIn('authority',d)
    def test_view_layout_never_claims_plain_data_fast_path(self):
        d=json.loads(proc(OMNI,'type','layout','View<u32>').stdout); self.assertFalse(d['zero_copy_candidate']); self.assertEqual(d['ownership'],'borrowed-readonly'); self.assertFalse(d['portable_address']); self.assertIn('reason',d); self.assertEqual(d['size_bytes'],0)
    def test_view_element_type_participates_in_identity(self):
        def tid(t): return json.loads(proc(OMNI,'type','describe',t).stdout)['type_id']
        self.assertNotEqual(tid('View<u8>'),tid('View<u32>'))
    def test_wave10_and_extended_omc10_roundtrip(self):
        p=ROOT/'examples/borrowed_views.omni'; w=proc(OMNI,'wave',p); self.assertEqual(w.returncode,0,w.stderr); self.assertTrue(w.stdout.startswith(b'(omni-wave 18')); self.assertIn(b'View<u32>',w.stdout)
        out=self.d/'v.owire'; self.assertEqual(proc(OMNI,'pack',p,'-o',out).returncode,0); raw=out.read_bytes(); self.assertEqual(raw[:4],b'OMCX'); self.assertEqual(int.from_bytes(raw[4:8],'little'),18); u=proc(OMNI,'unpack',out); self.assertEqual(u.returncode,0,u.stderr); self.assertIn(b'View<u32>',u.stdout)
    def test_view_semantics_cannot_hide_under_wave9(self):
        cur=proc(OMNI,'wave',ROOT/'examples/borrowed_views.omni'); fake=self.d/'fake9.owave'; fake.write_bytes(cur.stdout.replace(b'(omni-wave 18',b'(omni-wave 9',1)); r=proc(OMNI,'check',fake); self.assertEqual(r.returncode,2); self.assertIn(b'E_VERSION',r.stderr)
    def test_view_semantics_cannot_hide_under_omc9(self):
        out=self.d/'v.owire'; self.assertEqual(proc(OMNI,'pack',ROOT/'examples/borrowed_views.omni','-o',out).returncode,0); raw=out.read_bytes(); fake=self.d/'fake9.owire'; fake.write_bytes(b'OMC9'+raw[8:]); r=proc(OMNI,'check',fake); self.assertEqual(r.returncode,2); self.assertRegex(r.stderr,b'E_(VERSION|WIRE)')
    def test_legacy9_reads_and_canonicalizes_to_wave10(self):
        for ext in ('owave','owire'):
            p=ROOT/'reference/compat'/f'legacy9.{ext}'; self.assertTrue(p.is_file()); c=proc(OMNI,'check',p); self.assertEqual(c.returncode,0,c.stderr); w=proc(OMNI,'wave',p); self.assertTrue(w.stdout.startswith(b'(omni-wave 18'))
if __name__=='__main__': unittest.main(verbosity=2)
