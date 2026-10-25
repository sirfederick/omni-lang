#!/usr/bin/env python3
from __future__ import annotations
import json, os, pathlib, subprocess, tempfile, unittest
ROOT=pathlib.Path(__file__).resolve().parents[1]
OMNI=pathlib.Path(os.environ.get('OMNI_TEST_BIN',ROOT/'bin/linux-x86_64/omni'))
def proc(*args,timeout=45): return subprocess.run([str(x) for x in args],capture_output=True,timeout=timeout,env={**os.environ,'OMNI_HOME':str(ROOT)})
class Alpha6AbstractionTests(unittest.TestCase):
    def setUp(self): self.tmp=tempfile.TemporaryDirectory(prefix='omni-alpha6-'); self.d=pathlib.Path(self.tmp.name)
    def tearDown(self): self.tmp.cleanup()
    def source(self,text,name='main.omni'): p=self.d/name; p.write_text(text,encoding='utf-8'); return p
    def check_ok(self,text,name='main.omni'):
        r=proc(OMNI,'check',self.source(text,name)); self.assertEqual(r.returncode,0,r.stderr); return r
    def check_err(self,text,code,name='main.omni'):
        r=proc(OMNI,'check',self.source(text,name)); self.assertEqual(r.returncode,2,r.stderr); self.assertIn(code.encode(),r.stderr); return r
    def eval(self,text):
        p=self.source(text); r=proc(OMNI,'eval',p); return r
    def test_version(self): self.assertEqual(proc(OMNI,'--version').stdout.strip(),b'omni '+(ROOT/'VERSION').read_bytes().strip())
    def test_explicit_generic_integer(self):
        s='module t func add<T:Integer>(a T,b T) T { return a+b } func main() u32 { return add<u32>(20u32,22u32) }'
        r=self.eval(s); self.assertEqual(r.returncode,42,r.stderr)
    def test_generic_constraint_rejects_bool(self):
        self.check_err('module t func id<T:Integer>(x T) T { return x } func main() u32 { let x bool=id<bool>(true); return 0 }','E_GENERIC_CONSTRAINT')
    def test_generic_missing_type_args_rejected(self):
        self.check_err('module t func id<T>(x T) T { return x } func main() u32 { return id(1u32) }','E_GENERIC_ARGS')
    def test_type_args_on_nongeneric_rejected(self):
        self.check_err('module t func id(x u32) u32 { return x } func main() u32 { return id<u32>(1u32) }','E_GENERIC_TARGET')
    def test_unknown_constraint_rejected(self):
        self.check_err('module t func id<T:Magical>(x T) T { return x } func main() u32 { return id<u32>(1u32) }','E_GENERIC_CONSTRAINT')
    def test_duplicate_specialization_reused(self):
        p=self.source('module t func id<T:Plain>(x T) T { return x } func main() u32 { return id<u32>(id<u32>(7u32)) }')
        m=proc(OMNI,'manifest',p); self.assertEqual(m.returncode,0,m.stderr); d=json.loads(m.stdout)
        self.assertEqual(d['properties']['generic_templates'],1); self.assertEqual(d['properties']['generated_specializations'],1)
    def test_imported_public_generic(self):
        self.source('module lib pub func add<T:Integer>(a T,b T) T { return a+b }','lib.omni')
        p=self.source('module app\nimport l "lib.omni"\nfunc main() u32 { return l.add<u32>(19u32,23u32) }')
        r=proc(OMNI,'eval',p); self.assertEqual(r.returncode,42,r.stderr)
    def test_imported_private_generic_denied(self):
        self.source('module lib func id<T>(x T) T { return x }','lib.omni')
        p=self.source('module app\nimport l "lib.omni"\nfunc main() u32 { return l.id<u32>(1u32) }')
        r=proc(OMNI,'check',p); self.assertEqual(r.returncode,2,r.stderr); self.assertIn(b'E_VISIBILITY',r.stderr)
    def test_generic_capability_propagates(self):
        self.check_err('module t func emit<T:Scalar>(x T) T !{io.print} { print(x); return x } func main() u32 { return emit<u32>(3u32) }','E_CAPABILITY')
        self.check_ok('module t func emit<T:Scalar>(x T) T !{io.print} { print(x); return x } func main() u32 !{io.print} { return emit<u32>(3u32) }')
    def test_ufcs_method_sugar(self):
        s='module t func add<T:Integer>(a T,b T) T { return a+b } func main() u32 { let a u32=37u32; return a::add<u32>(5u32) }'
        r=self.eval(s); self.assertEqual(r.returncode,42,r.stderr); f=proc(OMNI,'fmt',self.d/'main.omni'); self.assertEqual(f.returncode,0,f.stderr); self.assertIn(b'::add<u32>',f.stdout)
    def test_for_in_array(self):
        s='module t func main() u32 { let xs=array(10u32,11u32,21u32); var sum u32=0u32; for x in xs { sum=sum+x; } return sum }'
        self.assertEqual(self.eval(s).returncode,42)
    def test_for_in_view(self):
        s='module t func main() u32 { let xs=array(10u32,11u32,21u32); let v=view(xs); var sum u32=0u32; for x in v { sum=sum+x; } return sum }'
        self.assertEqual(self.eval(s).returncode,42)
    def test_for_iterable_evaluated_once(self):
        s='module t func main() u32 { let xs=array(1u32,2u32,3u32); var sum u32=0u32; for x in xs { sum=sum+x; } return sum }'
        self.assertEqual(self.eval(s).returncode,6)
    def test_for_in_rejects_text(self): self.check_err('module t func main() u32 { for x in "abc" { } return 0 }','E_ITERABLE')
    def test_iteration_binding_is_immutable(self): self.check_err('module t func main() u32 { let xs=array(1u32,2u32); for x in xs { x=3u32; } return 0 }','E_IMMUTABLE')
    def test_iteration_binding_scope(self): self.check_err('module t func main() u32 { let xs=array(1u32); for x in xs { } return x }','E_UNDEFINED')
    def test_wave11_and_omc11(self):
        p=self.source('module t func add<T:Integer>(a T,b T) T { return a+b } func main() u32 { let xs=array(20u32,22u32); var s u32=0u32; for x in xs { s=add<u32>(s,x); } return s }')
        w=proc(OMNI,'wave',p); self.assertEqual(w.returncode,0,w.stderr); self.assertTrue(w.stdout.startswith(b'(omni-wave 22')); self.assertIn(b'authoring-source',w.stdout); self.assertIn(b'add<T:Integer>',w.stdout); self.assertNotIn(b'__g_',w.stdout)
        out=self.d/'a.owire'; q=proc(OMNI,'pack',p,'-o',out); self.assertEqual(q.returncode,0,q.stderr); raw=out.read_bytes(); self.assertEqual(raw[:4],b'OMCX'); self.assertEqual(int.from_bytes(raw[4:8],'little'),22)
        u=proc(OMNI,'wave',out); self.assertEqual(u.returncode,0,u.stderr); self.assertEqual(u.stdout,w.stdout); self.assertEqual(proc(OMNI,'eval',out).returncode,42)
    def test_for_in_cannot_hide_under_wave10(self):
        p=self.source('module t func main() u32 { let xs=array(1u32); for x in xs { } return 0 }'); w=proc(OMNI,'wave',p); self.assertEqual(w.returncode,0,w.stderr)
        fake=self.d/'fake10.owave'; fake.write_bytes(w.stdout.replace(b'(omni-wave 18',b'(omni-wave 10',1)); r=proc(OMNI,'check',fake); self.assertEqual(r.returncode,2,r.stderr); self.assertIn(b'E_VERSION',r.stderr)
    def test_for_in_cannot_hide_under_omc10(self):
        p=self.source('module t func main() u32 { let xs=array(1u32); for x in xs { } return 0 }'); out=self.d/'a.owire'; self.assertEqual(proc(OMNI,'pack',p,'-o',out).returncode,0)
        raw=bytearray(out.read_bytes()); raw[4:8]=(10).to_bytes(4,'little'); fake=self.d/'fake10.owire'; fake.write_bytes(raw); r=proc(OMNI,'check',fake); self.assertEqual(r.returncode,2,r.stderr); self.assertRegex(r.stderr,b'E_(VERSION|WIRE)')
    def test_legacy10_reads_and_canonicalizes_to_wave11(self):
        for ext in ('owave','owire'):
            p=ROOT/'reference/compat'/f'legacy10.{ext}'; self.assertTrue(p.is_file()); c=proc(OMNI,'check',p); self.assertEqual(c.returncode,0,c.stderr); w=proc(OMNI,'wave',p); self.assertTrue(w.stdout.startswith(b'(omni-wave 18'))
    def test_generic_source_never_leaks_open_template_into_ir(self):
        p=self.source('module t func id<T:Plain>(x T) T { return x } func main() u32 { return id<u32>(42u32) }')
        w=proc(OMNI,'wave',p); self.assertEqual(w.returncode,0,w.stderr); self.assertIn(b'id<T:Plain>',w.stdout)
        # Open authoring parameters are rechecked; only concrete functions reach native LLVM.
        out=self.d/'generic.ll'; result=proc(OMNI,'emit-llvm',p,'-o',out)
        self.assertEqual(result.returncode,0,result.stderr); ir=out.read_bytes()
        self.assertIn(b'id__g_',ir); self.assertNotIn(b'Param',ir); self.assertNotIn(b'id<T',ir)
        self.assertEqual(proc(OMNI,'eval',p).returncode,42)
    def test_unused_generic_unknown_capability_fails_closed(self):
        self.check_err('module t func dormant<T>(x T) T !{zz.root} { return x } func main() u32 { return 0 }','E_CAPABILITY')
    def test_generic_calls_generic_after_substitution(self):
        s='module t func id<T:Plain>(x T) T { return x } func add_ids<T:Integer>(a T,b T) T { return id<T>(a)+id<T>(b) } func main() u32 { return add_ids<u32>(20u32,22u32) }'
        self.assertEqual(self.eval(s).returncode,42)
    def test_generic_view_element(self):
        s='module t func first<T:Plain>(v View<T>) T { return view.get(v,0u32) } func main() u32 { let a=array(42u32,1u32); let v=view(a); return first<u32>(v) }'
        self.assertEqual(self.eval(s).returncode,42)
    def test_generic_plain_text(self):
        s='module t func id<T:Plain>(x T) T { return x } func main() u32 { let x Text=id<Text>("abcd"); return text.len(x) }'
        self.assertEqual(self.eval(s).returncode,4)
if __name__=='__main__': unittest.main(verbosity=2)
