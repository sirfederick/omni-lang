#!/usr/bin/env python3
from __future__ import annotations
import json, os, pathlib, subprocess, tempfile, unittest
ROOT=pathlib.Path(__file__).resolve().parents[1]
OMNI=pathlib.Path(os.environ.get('OMNI_TEST_BIN',ROOT/'bin/linux-x86_64/omni'))
def proc(*args,timeout=20): return subprocess.run([str(x) for x in args],capture_output=True,timeout=timeout,env={**os.environ,'OMNI_HOME':str(ROOT)})
class ProductTypesTests(unittest.TestCase):
    def setUp(self): self.tmp=tempfile.TemporaryDirectory(prefix='omni-alpha4-'); self.d=pathlib.Path(self.tmp.name)
    def tearDown(self): self.tmp.cleanup()
    def source(self,text,name='a.omni'): p=self.d/name; p.write_text(text,encoding='utf-8'); return p
    def check_ok(self,text):
        r=proc(OMNI,'check',self.source(text)); self.assertEqual(r.returncode,0,r.stderr); return r
    def check_err(self,text,code):
        r=proc(OMNI,'check',self.source(text)); self.assertEqual(r.returncode,2,r.stderr); self.assertIn(code.encode(),r.stderr); return r
    def native(self,text):
        p=self.source(text); out=self.d/'native'; b=proc(OMNI,'build',p,'-o',out); self.assertEqual(b.returncode,0,b.stderr); return proc(out)
    def test_version(self): self.assertEqual(proc(OMNI,'--version').stdout.strip(),b'omni '+(ROOT/'VERSION').read_bytes().strip())
    def test_tuple_heterogeneous_eval_native(self):
        src='module t func main() u32 !{io.print} { let x Tuple<u8,bool,u32>=tuple(7u8,true,99u32); print(tuple.get(x,0u32)); print(tuple.get(x,1u32)); print(tuple.get(x,2u32)); return 0 }'
        e=proc(OMNI,'eval',self.source(src)); self.assertEqual((e.returncode,e.stdout),(0,b'7\ntrue\n99\n'),e.stderr); n=self.native(src); self.assertEqual((n.returncode,n.stdout),(0,e.stdout),n.stderr)
    def test_unit_tuple(self): self.check_ok('module t func main() u32 { let x Tuple<>=tuple(); return 0 }')
    def test_tuple_index_literal_required(self): self.check_err('module t func main() u32 { let x=tuple(1u32,true); let i u32=0u32; let y u32=tuple.get(x,i); return y }','E_TUPLE_INDEX')
    def test_tuple_index_bounds(self): self.check_err('module t func main() u32 { let x=tuple(1u32,true); let y u32=tuple.get(x,2u32); return y }','E_BOUNDS')
    def test_array_make_len_get(self):
        src='module t func main() u32 !{io.print} { let a Array<u16,3>=array(10u16,20u16,30u16); print(array.len(a)); print(array.get(a,1u32)); return u32(array.get(a,2u32)) }'
        e=proc(OMNI,'eval',self.source(src)); self.assertEqual((e.returncode,e.stdout),(30,b'3\n20\n'),e.stderr); n=self.native(src); self.assertEqual((n.returncode,n.stdout),(30,e.stdout),n.stderr)
    def test_array_mixed_type_rejected(self): self.check_err('module t func main() u32 { let a=array(1u8,2u16); return 0 }','E_TYPE')
    def test_array_extent_is_part_of_type(self): self.check_err('module t func main() u32 { let a Array<u32,2>=array(1u32,2u32,3u32); return 0 }','E_TYPE')
    def test_array_fill_zero_and_four(self):
        src='module t func main() u32 !{io.print} { let z Array<u8,0>=array.fill(9u8,0u32); let a Array<u8,4>=array.fill(9u8,4u32); print(array.len(z)); print(array.get(a,3u32)); return 0 }'
        e=proc(OMNI,'eval',self.source(src)); self.assertEqual(e.stdout,b'0\n9\n'); n=self.native(src); self.assertEqual((n.returncode,n.stdout),(0,e.stdout),n.stderr)
    def test_array_with_is_functional(self):
        src='module t func main() u32 !{io.print} { let a=array(1u32,2u32,3u32); let b=array.with(a,1u32,9u32); print(array.get(a,1u32)); print(array.get(b,1u32)); return 0 }'
        e=proc(OMNI,'eval',self.source(src)); self.assertEqual(e.stdout,b'2\n9\n'); n=self.native(src); self.assertEqual((n.returncode,n.stdout),(0,e.stdout),n.stderr)
    def test_dynamic_bounds_trap_eval_native(self):
        src='module t func main() u32 { let a=array(1u32,2u32); let i u32=2u32; return array.get(a,i) }'; p=self.source(src)
        e=proc(OMNI,'eval',p); self.assertNotEqual(e.returncode,0); self.assertIn(b'E_BOUNDS',e.stderr)
        out=self.d/'bad'; b=proc(OMNI,'build',p,'-o',out); self.assertEqual(b.returncode,0,b.stderr); n=proc(out); self.assertNotEqual(n.returncode,0); self.assertIn(b'E_BOUNDS',n.stderr)
    def test_product_types_in_struct_and_enum(self):
        src='''module t struct S { p Tuple<u32,bool>, a Array<u8,2> } enum E { NoneE, Data(Array<u8,2>), } func main() u32 { let s S=S{p:tuple(3u32,true),a:array(1u8,2u8)}; let e E=E.Data(s.a); match e { NoneE { return 0 } Data(a) { return u32(array.get(a,1u32)) } } }'''
        self.check_ok(src); self.assertEqual(self.native(src).returncode,2)
    def test_product_linear_payload_rejected(self): self.check_err('module t func main() u32 !{memory.write} { let r=buffer.alloc(8u32); match r { Ok(b) { let x=array(borrow(b)); return 0 } Err(e) { return e } } }','E_PRODUCT_LINEAR')
    def test_array_function_boundary(self):
        src='module t func second(a Array<u32,2>) u32 { return array.get(a,1u32) } func main() u32 { return second(array(4u32,8u32)) }'; self.check_ok(src); self.assertEqual(self.native(src).returncode,8)
    def test_layout_array_descriptor(self):
        a=proc(OMNI,'type','layout','Array<u32,4>'); self.assertEqual(a.returncode,0,a.stderr); d=json.loads(a.stdout); self.assertEqual(d['schema'],'omni.layout-descriptor/1'); self.assertEqual(d['size_bytes'],16); self.assertEqual(d['alignment_bytes'],4); self.assertTrue(d['zero_copy_candidate'])
    def test_layout_tuple_offsets_and_stability(self):
        a=proc(OMNI,'type','layout','Tuple<u8,u32,bool>'); b=proc(OMNI,'type','layout','Tuple<u8,u32,bool>'); d=json.loads(a.stdout); self.assertEqual(d['field_offsets'],[0,4,8]); self.assertEqual(d['size_bytes'],12); self.assertEqual(d['layout_id'],json.loads(b.stdout)['layout_id'])
    def test_dynamic_type_not_zero_copy_candidate(self):
        d=json.loads(proc(OMNI,'type','layout','Text').stdout); self.assertFalse(d['zero_copy_candidate']); self.assertIn('reason',d)
    def test_type_identity_array_extent_and_tuple_order(self):
        def tid(t): return json.loads(proc(OMNI,'type','describe',t).stdout)['type_id']
        self.assertNotEqual(tid('Array<u32,4>'),tid('Array<u32,5>')); self.assertNotEqual(tid('Tuple<u8,u32>'),tid('Tuple<u32,u8>'))
    def test_product_type_descriptor_shape(self):
        a=json.loads(proc(OMNI,'type','describe','Array<u16,3>').stdout); self.assertEqual(a['kind'],'product'); self.assertEqual(a['element_type'],'u16'); self.assertEqual(a['length'],3)
        t=json.loads(proc(OMNI,'type','describe','Tuple<u8,bool,u32>').stdout); self.assertEqual(t['kind'],'product'); self.assertEqual(t['elements'],['u8','bool','u32'])
    def test_array_fill_linear_rejected(self):
        self.check_err('module t func main() u32 !{memory.write} { let r=buffer.alloc(8u32); match r { Ok(b) { let x=array.fill(move(b),2u32); return 0 } Err(e) { return e } } }','E_PRODUCT_LINEAR')
    def test_alpha4_products_canonicalize_in_wave10_omc10(self):
        p=ROOT/'examples/product_types.omni'; w=proc(OMNI,'wave',p); self.assertEqual(w.returncode,0,w.stderr); self.assertTrue(w.stdout.startswith(b'(omni-wave 18')); self.assertIn(b'Tuple<u32,bool,u8>',w.stdout); self.assertIn(b'Array<u32,4>',w.stdout)
        out=self.d/'p.owire'; q=proc(OMNI,'pack',p,'-o',out); self.assertEqual(q.returncode,0,q.stderr); self.assertEqual(out.read_bytes()[:8],b'OMCX\x12\x00\x00\x00'); u=proc(OMNI,'unpack',out); self.assertEqual(u.returncode,0,u.stderr)
    def test_product_semantics_cannot_hide_under_wave8(self):
        cur=proc(OMNI,'wave',ROOT/'examples/product_types.omni'); fake=self.d/'fake8.owave'; fake.write_bytes(cur.stdout.replace(b'(omni-wave 18',b'(omni-wave 8',1)); r=proc(OMNI,'check',fake); self.assertEqual(r.returncode,2); self.assertIn(b'E_VERSION',r.stderr)
    def test_product_semantics_cannot_hide_under_omc8(self):
        out=self.d/'p.owire'; self.assertEqual(proc(OMNI,'pack',ROOT/'examples/product_types.omni','-o',out).returncode,0); raw=out.read_bytes(); raw=b'OMC8'+raw[8:]; fake=self.d/'fake8.owire'; fake.write_bytes(raw); r=proc(OMNI,'check',fake); self.assertNotEqual(r.returncode,0); self.assertRegex(r.stderr,b'E_(VERSION|WIRE)')
    def test_historical_1_to_8_canonicalize_to_10(self):
        for v in range(1,9):
            for ext in ('owave','owire'):
                p=ROOT/'reference/compat'/f'legacy{v}.{ext}'; self.assertTrue(p.is_file(),p); c=proc(OMNI,'check',p); self.assertEqual(c.returncode,0,(p,c.stderr)); w=proc(OMNI,'wave',p); self.assertTrue(w.stdout.startswith(b'(omni-wave 18'))
    def test_research_and_fast_path_docs_exist(self):
        r=(ROOT/'docs/research/PRODUCT_TYPES_LAYOUT_FASTPATH_SCAN_2026-09-19.md').read_text(); self.assertIn('WebAssembly',r); self.assertIn('Apache Arrow',r); self.assertIn('Google Patents',r); self.assertIn('DESIGN_AROUND',r)
        f=(ROOT/'docs/architecture/ECU_HIGH_SPEED_DATA_SEAM.md').read_text(); self.assertIn('layout_id',f); self.assertIn('ResourceRef',f); self.assertIn('Node',f); self.assertIn('Python',f)
if __name__=='__main__': unittest.main(verbosity=2)
