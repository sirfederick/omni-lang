#!/usr/bin/env python3
from __future__ import annotations
import json, os, pathlib, subprocess, tempfile, unittest
ROOT=pathlib.Path(__file__).resolve().parents[1]
OMNI=pathlib.Path(os.environ.get('OMNI_TEST_BIN',ROOT/'bin/linux-x86_64/omni'))

def proc(*args,timeout=20):
    return subprocess.run([str(x) for x in args],capture_output=True,timeout=timeout,env={**os.environ,'OMNI_HOME':str(ROOT)})

class UserADTFoundationTests(unittest.TestCase):
    def setUp(self): self.tmp=tempfile.TemporaryDirectory(prefix='omni-alpha3-'); self.d=pathlib.Path(self.tmp.name)
    def tearDown(self): self.tmp.cleanup()
    def source(self,text,name='a.omni'):
        p=self.d/name; p.write_text(text,encoding='utf-8'); return p
    def check_ok(self,text,name='a.omni'):
        r=proc(OMNI,'check',self.source(text,name)); self.assertEqual(r.returncode,0,r.stderr); return r
    def check_err(self,text,code,name='a.omni'):
        r=proc(OMNI,'check',self.source(text,name)); self.assertEqual(r.returncode,2,r.stderr); self.assertIn(code.encode(),r.stderr); return r
    def eval_out(self,text,name='a.omni'):
        p=self.source(text,name); r=proc(OMNI,'eval',p); self.assertEqual(r.returncode,0,r.stderr); return r.stdout
    def native(self,text,name='a.omni'):
        p=self.source(text,name); out=self.d/'native'; b=proc(OMNI,'build',p,'-o',out); self.assertEqual(b.returncode,0,b.stderr); return proc(out)

    def test_version_identity(self):
        r=proc(OMNI,'--version'); self.assertEqual(r.returncode,0,r.stderr); self.assertEqual(r.stdout.strip(),b'omni '+(ROOT/'VERSION').read_bytes().strip())

    def test_unit_and_payload_variants_eval_native(self):
        src='''module t
        enum State { Pending, Active(u32), Failed(Text), }
        func score(s State) u32 {
          match s { Pending { return 1 } Active(v) { return v } Failed(msg) { return text.len(msg) } }
        }
        func main() u32 !{io.print} {
          print(score(State.Pending())); print(score(State.Active(42u32))); print(score(State.Failed("oops"))); return 0
        }'''
        expected=b'1\n42\n4\n'; self.assertEqual(self.eval_out(src),expected); n=self.native(src); self.assertEqual((n.returncode,n.stdout),(0,expected),n.stderr)

    def test_example_eval_native(self):
        p=ROOT/'examples/adt_enum.omni'; e=proc(OMNI,'eval',p); self.assertEqual(e.returncode,0,e.stderr); self.assertEqual(e.stdout,b'42\n4\n')
        out=self.d/'adt'; b=proc(OMNI,'build',p,'-o',out); self.assertEqual(b.returncode,0,b.stderr); n=proc(out); self.assertEqual((n.returncode,n.stdout),(0,e.stdout),n.stderr)

    def test_non_exhaustive_rejected(self):
        self.check_err('''module t enum E { A, B, } func f(x E) u32 { match x { A { return 1 } } } func main() u32 { return f(E.A()) }''','E_MATCH_NON_EXHAUSTIVE')

    def test_duplicate_arm_rejected(self):
        self.check_err('''module t enum E { A, B, } func f(x E) u32 { match x { A { return 1 } A { return 2 } B { return 3 } } } func main() u32 { return 0 }''','E_MATCH_DUPLICATE')

    def test_unknown_arm_rejected(self):
        self.check_err('''module t enum E { A, B, } func f(x E) u32 { match x { A { return 1 } C { return 2 } } } func main() u32 { return 0 }''','E_MATCH_VARIANT')

    def test_payload_binding_required(self):
        self.check_err('''module t enum E { A(u32), B, } func f(x E) u32 { match x { A { return 1 } B { return 0 } } } func main() u32 { return 0 }''','E_MATCH_BINDING')

    def test_unit_binding_forbidden(self):
        self.check_err('''module t enum E { A, B, } func f(x E) u32 { match x { A(v) { return v } B { return 0 } } } func main() u32 { return 0 }''','E_MATCH_BINDING')

    def test_constructor_wrong_payload_type(self):
        self.check_err('module t enum E { A(u32), B, } func main() u32 { let x E=E.A(true); return 0 }','E_TYPE')

    def test_constructor_wrong_arity_unit(self):
        self.check_err('module t enum E { A, } func main() u32 { let x E=E.A(1); return 0 }','E_ARITY')

    def test_constructor_wrong_arity_payload(self):
        self.check_err('module t enum E { A(u32), } func main() u32 { let x E=E.A(); return 0 }','E_ARITY')

    def test_unknown_constructor_variant(self):
        self.check_err('module t enum E { A, } func main() u32 { let x E=E.B(); return 0 }','E_MATCH_VARIANT')

    def test_nominal_enums_are_not_structurally_interchangeable(self):
        self.check_err('module t enum A { X, } enum B { X, } func main() u32 { let b B=A.X(); return 0 }','E_TYPE')

    def test_duplicate_variant_declaration_rejected(self):
        self.check_err('module t enum E { A, A, } func main() u32 { return 0 }','E_DUPLICATE')

    def test_enum_match_requires_enum_subject(self):
        self.check_err('module t func main() u32 { let x u32=1; match x { A { return 1 } } }','E_TYPE')

    def test_enum_in_struct_field(self):
        src='''module t enum E { A, B(u32), } struct Box { value E } func get(b Box) u32 { match b.value { A { return 0 } B(x) { return x } } } func main() u32 { let b Box=Box{value:E.B(7u32)}; return get(b) }'''
        self.check_ok(src); n=self.native(src); self.assertEqual(n.returncode,7,n.stderr)

    def test_nested_enum_payload_and_nested_match(self):
        src='''module t
        enum Inner { EmptyInner, Value(u32), }
        enum Outer { Empty, Wrap(Inner), }
        func get(o Outer) u32 {
          match o {
            Empty { return 1 }
            Wrap(i) { match i { EmptyInner { return 2 } Value(v) { return v } } }
          }
        }
        func main() u32 { return get(Outer.Wrap(Inner.Value(9u32))) }'''
        self.check_ok(src); n=self.native(src); self.assertEqual(n.returncode,9,n.stderr)

    def test_recursive_enum_layout_rejected(self):
        self.check_err('module t enum Loop { End, More(Loop), } func main() u32 { return 0 }','E_LAYOUT_CYCLE')

    def test_borrow_and_async_payloads_stay_rejected(self):
        # Core 1.3 admits Resource/Result payloads under the pending-sum law.
        cases=[('Borrow<Buffer>','Borrow'),('Future<u32>','Future'),('Stream<u32>','Stream')]
        for typ,label in cases:
            with self.subTest(label=label): self.check_err(f'module t enum E {{ X({typ}), }} func main() u32 {{ return 0 }}','E_TYPE' if label not in ('Future','Stream') else 'E_ASYNC_UNSUPPORTED')

    def test_imported_public_enum_constructor_and_match(self):
        (self.d/'types.omni').write_text('''module types pub enum Status { Idle, Running(u32), }''',encoding='utf-8')
        main='''module app
        import t "types.omni"
        func value(s t.Status) u32 { match s { Idle { return 0 } Running(v) { return v } } }
        func main() u32 { return value(t.Status.Running(11u32)) }'''
        p=self.source(main,'main.omni'); c=proc(OMNI,'check',p); self.assertEqual(c.returncode,0,c.stderr); out=self.d/'app'; b=proc(OMNI,'build',p,'-o',out); self.assertEqual(b.returncode,0,b.stderr); n=proc(out); self.assertEqual(n.returncode,11,n.stderr)

    def test_imported_private_enum_rejected(self):
        (self.d/'types.omni').write_text('module types enum Hidden { A, }',encoding='utf-8')
        p=self.source('module app\nimport t "types.omni"\nfunc main() u32 { let x t.Hidden=t.Hidden.A(); return 0 }','main.omni')
        r=proc(OMNI,'check',p); self.assertEqual(r.returncode,2,r.stderr); self.assertIn(b'E_VISIBILITY',r.stderr)

    def test_public_enum_cannot_expose_private_payload_type(self):
        self.check_err('module t struct Secret { x u32 } pub enum Public { Hide(Secret), EmptyPublic, } func main() u32 { return 0 }','E_VISIBILITY')

    def test_match_all_return_satisfies_function_return(self):
        self.check_ok('module t enum E { A, B(u32), } func f(e E) u32 { match e { A { return 3 } B(v) { return v } } } func main() u32 { return f(E.A()) }')

    def test_wave8_omc8_roundtrip(self):
        p=ROOT/'examples/adt_enum.omni'; w=proc(OMNI,'wave',p); self.assertEqual(w.returncode,0,w.stderr); self.assertTrue(w.stdout.startswith(b'(omni-wave 18')); self.assertIn(b'(enum State',w.stdout); self.assertIn(b'(match-enum',w.stdout); self.assertIn(b'(variant State.Active',w.stdout)
        out=self.d/'adt.owire'; q=proc(OMNI,'pack',p,'-o',out); self.assertEqual(q.returncode,0,q.stderr); self.assertEqual(out.read_bytes()[:8],b'OMCX\x12\x00\x00\x00')
        u=proc(OMNI,'unpack',out); self.assertEqual(u.returncode,0,u.stderr); c=proc(OMNI,'check',self.source(u.stdout.decode(),'unpacked.omni')); self.assertEqual(c.returncode,0,c.stderr)

    def test_enum_semantics_rejected_under_wave7_header(self):
        cur=proc(OMNI,'wave',ROOT/'examples/adt_enum.omni'); self.assertEqual(cur.returncode,0,cur.stderr); fake=self.d/'fake7.owave'; fake.write_bytes(cur.stdout.replace(b'(omni-wave 18',b'(omni-wave 7',1)); r=proc(OMNI,'check',fake); self.assertEqual(r.returncode,2); self.assertIn(b'E_VERSION',r.stderr)

    def test_enum_wire_relabelled_omc7_is_not_accepted(self):
        p=self.d/'current.owire'; q=proc(OMNI,'pack',ROOT/'examples/adt_enum.omni','-o',p); self.assertEqual(q.returncode,0,q.stderr); raw=p.read_bytes(); fake=self.d/'fake7.owire'; fake.write_bytes(b'OMC7'+raw[8:]); r=proc(OMNI,'check',fake); self.assertNotEqual(r.returncode,0)

    def test_historical_wave_wire_1_to_7_canonicalize_to_wave8(self):
        for v in range(1,8):
            with self.subTest(kind='wave',version=v):
                p=ROOT/'reference/compat'/f'legacy{v}.owave'; self.assertTrue(p.is_file()); c=proc(OMNI,'check',p); self.assertEqual(c.returncode,0,c.stderr); w=proc(OMNI,'wave',p); self.assertEqual(w.returncode,0,w.stderr); self.assertTrue(w.stdout.startswith(b'(omni-wave 18'))
            with self.subTest(kind='wire',version=v):
                p=ROOT/'reference/compat'/f'legacy{v}.owire'; self.assertTrue(p.is_file()); self.assertEqual(p.read_bytes()[:4],f'OMC{v}'.encode()); c=proc(OMNI,'check',p); self.assertEqual(c.returncode,0,c.stderr); w=proc(OMNI,'wave',p); self.assertEqual(w.returncode,0,w.stderr); self.assertTrue(w.stdout.startswith(b'(omni-wave 18'))

    def test_manifest_tracks_enums_and_omc8(self):
        r=proc(OMNI,'manifest',ROOT/'examples/adt_enum.omni'); self.assertEqual(r.returncode,0,r.stderr); d=json.loads(r.stdout); self.assertEqual(d['wire_profile'],'OMC18'); self.assertEqual(d['properties']['enums'],1); self.assertIn(';e=1;',d['omnihash'])

    def test_spec_research_and_design_around_present(self):
        spec=(ROOT/'spec/ADTS_0_2.md').read_text(encoding='utf-8'); research=(ROOT/'docs/research/ADT_PATTERN_MATCHING_TECHNOLOGY_SCAN_2026-09-19.md').read_text(encoding='utf-8')
        for x in ['closed nominal','E_MATCH_NON_EXHAUSTIVE','SisNervCent']: self.assertIn(x,spec)
        for x in ['Rust','Swift','Kotlin','OCaml','US20240338186A1','DESIGN_AROUND','DIRECT SET EXHAUSTIVENESS']: self.assertIn(x,research)

    def test_enum_formatter_idempotence(self):
        p=ROOT/'examples/adt_enum.omni'; a=proc(OMNI,'fmt',p); self.assertEqual(a.returncode,0,a.stderr); q=self.source(a.stdout.decode(),'fmt.omni'); b=proc(OMNI,'fmt',q); self.assertEqual(b.returncode,0,b.stderr); self.assertEqual(a.stdout,b.stdout)

    def test_adt_diagnostics_are_registered(self):
        r=proc(OMNI,'diagnostics'); self.assertEqual(r.returncode,0,r.stderr); d=json.loads(r.stdout); codes={x['code']:x['category'] for x in d['codes']}
        for code in ['E_MATCH_NON_EXHAUSTIVE','E_MATCH_DUPLICATE','E_MATCH_VARIANT','E_MATCH_BINDING']:
            self.assertIn(code,codes); self.assertEqual(codes[code],'flow')

if __name__=='__main__': unittest.main(verbosity=2)
