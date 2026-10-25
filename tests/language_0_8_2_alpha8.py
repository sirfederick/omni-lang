from __future__ import annotations
import os,pathlib,subprocess,tempfile,unittest

ROOT=pathlib.Path(__file__).resolve().parents[1]
OMNI=pathlib.Path(os.environ.get('OMNI_TEST_BIN',ROOT/'bin/linux-x86_64/omni'))

def proc(*args,timeout=45):
    return subprocess.run([str(x) for x in args],capture_output=True,timeout=timeout,env={**os.environ,'OMNI_HOME':str(ROOT)})

class A82MarkerTraitTests(unittest.TestCase):
    def setUp(self): self.tmp=tempfile.TemporaryDirectory(prefix='omni-a82-'); self.d=pathlib.Path(self.tmp.name)
    def tearDown(self): self.tmp.cleanup()
    def source(self,text,name='main.omni'):
        p=self.d/name; p.write_text(text,encoding='utf-8'); return p
    def check(self,text): return proc(OMNI,'check',self.source(text))

    def test_marker_trait_constrains_monomorphization_and_round_trips_concrete_wave(self):
        p=self.source('''module t
trait Marked {}
impl Marked for u32 {}
func identity<T:Marked>(x T) T { return x }
func main() u32 { return identity<u32>(42u32) }
''')
        checked=proc(OMNI,'check',p); self.assertEqual(checked.returncode,0,checked.stderr)
        evaluated=proc(OMNI,'eval',p); self.assertEqual(evaluated.returncode,42,evaluated.stderr)
        native=self.d/'marker-native'; built=proc(OMNI,'build',p,'-o',native,'--no-cache',timeout=90); self.assertEqual(built.returncode,0,built.stderr)
        executed=proc(native); self.assertEqual((executed.returncode,executed.stdout),(evaluated.returncode,evaluated.stdout),executed.stderr)
        wave=proc(OMNI,'wave',p); self.assertEqual(wave.returncode,0,wave.stderr)
        wp=self.d/'marker.owave'; wp.write_bytes(wave.stdout)
        round_checked=proc(OMNI,'check',wp); self.assertEqual(round_checked.returncode,0,round_checked.stderr)
        self.assertEqual(proc(OMNI,'eval',wp).returncode,42)

    def test_unsatisfied_marker_trait_fails_closed(self):
        r=self.check('''module t
trait Marked {}
func identity<T:Marked>(x T) T { return x }
func main() u32 { return identity<u32>(42u32) }
''')
        self.assertEqual(r.returncode,2); self.assertIn(b'E_GENERIC_CONSTRAINT',r.stderr)

    def test_unknown_and_duplicate_impls_are_rejected(self):
        unknown=self.check('module t\nimpl Missing for u32 {}\nfunc main() u32 { return 0 }')
        self.assertEqual(unknown.returncode,2); self.assertIn(b'E_TRAIT',unknown.stderr)
        duplicate=self.check('module t\ntrait Marked {}\nimpl Marked for u32 {}\nimpl Marked for u32 {}\nfunc main() u32 { return 0 }')
        self.assertEqual(duplicate.returncode,2); self.assertIn(b'E_TRAIT_COHERENCE',duplicate.stderr)

class A82ImmediateClosureTests(unittest.TestCase):
    def setUp(self): self.tmp=tempfile.TemporaryDirectory(prefix='omni-a82-closure-'); self.d=pathlib.Path(self.tmp.name)
    def tearDown(self): self.tmp.cleanup()
    def source(self,text,name='main.omni'):
        p=self.d/name; p.write_text(text,encoding='utf-8'); return p
    def check(self,text): return proc(OMNI,'check',self.source(text))

    def test_copy_capture_is_evaluator_native_differential(self):
        p=self.source('''module t
func main() u32 {
  let base u32 = 40u32
  return closure(x u32) u32 { return base + x }(2u32)
}
''')
        checked=proc(OMNI,'check',p); self.assertEqual(checked.returncode,0,checked.stderr)
        evaluated=proc(OMNI,'eval',p); self.assertEqual(evaluated.returncode,42,evaluated.stderr)
        native=self.d/'closure-native'; built=proc(OMNI,'build',p,'-o',native,'--no-cache',timeout=90); self.assertEqual(built.returncode,0,built.stderr)
        executed=proc(native); self.assertEqual((executed.returncode,executed.stdout),(evaluated.returncode,evaluated.stdout),executed.stderr)

    def test_mutable_and_authority_bearing_captures_fail_closed(self):
        mutable=self.check('''module t
func main() u32 { var x u32 = 1u32; return closure(y u32) u32 { return x + y }(1u32) }
''')
        self.assertEqual(mutable.returncode,2); self.assertIn(b'E_CLOSURE_CAPTURE',mutable.stderr)
        resource=self.check('''module t
func main() u32 !{memory.read,memory.write} {
  let r Result<Resource<Buffer>,u32> = buffer.alloc(1u32)
  match r { Ok(b) { return closure(x u32) u32 { return buffer.len(borrow(b)) + x }(1u32) } Err(e) { return e } }
}
''')
        self.assertEqual(resource.returncode,2); self.assertIn(b'E_CLOSURE_CAPTURE',resource.stderr)

    def test_closure_wave_wire_onme_round_trip(self):
        p=self.source('''module t
func main() u32 { let x u32 = 1u32; return closure(y u32) u32 { return x + y }(41u32) }
''')
        wave=proc(OMNI,'wave',p); self.assertEqual(wave.returncode,0,wave.stderr)
        wp=self.d/'closure.owave'; wp.write_bytes(wave.stdout)
        self.assertEqual(proc(OMNI,'eval',wp).returncode,42)
        bp=self.d/'closure.owire'
        wire=proc(OMNI,'pack',p,'-o',bp); self.assertEqual(wire.returncode,0,wire.stderr)
        unpacked=proc(OMNI,'eval',bp); self.assertEqual(unpacked.returncode,42,unpacked.stderr)
        onme=proc(OMNI,'onme',p); self.assertEqual(onme.returncode,0,onme.stderr)
        op=self.d/'closure.onme'; op.write_bytes(onme.stdout)
        self.assertEqual(proc(OMNI,'eval',op).returncode,42)
        legacy_wave=self.d/'closure-as16.owave'; legacy_wave.write_bytes(wave.stdout.replace(b'(omni-wave 18',b'(omni-wave 16',1))
        legacy_result=proc(OMNI,'check',legacy_wave); self.assertEqual(legacy_result.returncode,2); self.assertIn(b'E_VERSION',legacy_result.stderr)
        legacy_wire=self.d/'closure-as16.owire'; legacy=bytearray(bp.read_bytes()); legacy[4:8]=(16).to_bytes(4,'little'); legacy_wire.write_bytes(legacy)
        legacy_result=proc(OMNI,'check',legacy_wire); self.assertEqual(legacy_result.returncode,2); self.assertIn(b'E_WIRE',legacy_result.stderr)

class A82StaticMethodTests(unittest.TestCase):
    def setUp(self): self.tmp=tempfile.TemporaryDirectory(prefix='omni-a82-method-'); self.d=pathlib.Path(self.tmp.name)
    def tearDown(self): self.tmp.cleanup()
    def source(self,text):
        p=self.d/'main.omni'; p.write_text(text,encoding='utf-8'); return p
    def test_read_receiver_ufcs_is_static_and_differential(self):
        p=self.source('''module t
func add(read self u32, rhs u32) u32 { return self + rhs }
func main() u32 { return (40u32)::add(2u32) }
''')
        self.assertEqual(proc(OMNI,'check',p).returncode,0)
        ev=proc(OMNI,'eval',p); self.assertEqual(ev.returncode,42,ev.stderr)
        native=self.d/'method-native'; built=proc(OMNI,'build',p,'-o',native,'--no-cache',timeout=90); self.assertEqual(built.returncode,0,built.stderr)
        run=proc(native); self.assertEqual((run.returncode,run.stdout),(ev.returncode,ev.stdout),run.stderr)
        wave=proc(OMNI,'wave',p); self.assertEqual(wave.returncode,0,wave.stderr)
        wp=self.d/'method.owave'; wp.write_bytes(wave.stdout); self.assertEqual(proc(OMNI,'eval',wp).returncode,42)
        legacy=self.d/'method-as16.owave'; legacy.write_bytes(wave.stdout.replace(b'(omni-wave 18',b'(omni-wave 16',1))
        rejected=proc(OMNI,'check',legacy); self.assertEqual(rejected.returncode,2); self.assertIn(b'E_VERSION',rejected.stderr)
        wire=self.d/'method.owire'; self.assertEqual(proc(OMNI,'pack',p,'-o',wire).returncode,0); self.assertEqual(proc(OMNI,'eval',wire).returncode,42)
    def test_legacy_ufcs_remains_compatible_and_unproved_modes_fail_closed(self):
        no_receiver=proc(OMNI,'check',self.source('''module t
func add(x u32, y u32) u32 { return x + y }
func main() u32 { return (1u32)::add(2u32) }
''')); self.assertEqual(no_receiver.returncode,0,no_receiver.stderr)
        mutable=proc(OMNI,'check',self.source('''module t
func bad(mutate self u32) u32 { return self }
func main() u32 { return 0u32 }
''')); self.assertEqual(mutable.returncode,2); self.assertIn(b'E_METHOD_RECEIVER',mutable.stderr)

    def test_read_receiver_checks_recursive_resource_and_pending_ownership(self):
        cases = (
            'struct P { r Result<u32,u32> }\nfunc bad(read self P) u32 { let r = self.r\n'
            ' match r { Ok(n) { return n } Err(n) { return n } } }\n',
            'struct P { b Resource<Buffer> }\n'
            'func bad(read self P) u32 !{memory.read} { return buffer.len(borrow(self.b)) }\n',
            'func bad(read self Option<Result<u32,u32>>) u32 { match self { Some(r) {\n'
            ' match r { Ok(n) { return n } Err(n) { return n } } } None { return 0u32 } } }\n',
        )
        for declaration in cases:
            with self.subTest(declaration=declaration):
                source = self.source('module t\n' + declaration + 'func main() u32 { return 0u32 }\n')
                result = proc(OMNI, 'check', source)
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertIn(b'E_METHOD_RECEIVER', result.stderr)
        source = self.source('module t\nstruct P { n u32 }\n'
            'func read_it(read self P) u32 { return self.n }\n'
            'func main() u32 { let p = P { n: 21u32 }; return p::read_it() + p::read_it() }\n')
        evaluated = proc(OMNI, 'eval', source)
        self.assertEqual(evaluated.returncode, 42, evaluated.stderr)
        output = self.d/'copy-read'
        built = proc(OMNI, 'build', source, '-o', output, '--no-cache', timeout=90)
        self.assertEqual(built.returncode, 0, built.stderr)
        self.assertEqual(proc(output).returncode, 42)

class A82StaticIterationProtocolTests(unittest.TestCase):
    def setUp(self): self.tmp=tempfile.TemporaryDirectory(prefix='omni-a82-iteration-'); self.d=pathlib.Path(self.tmp.name)
    def tearDown(self): self.tmp.cleanup()
    def source(self,text,name='main.omni'): p=self.d/name; p.write_text(text,encoding='utf-8'); return p
    def test_builtin_protocols_are_static_and_differential(self):
        p=self.source('''module t
func main() u32 {
  let xs=array(10u32,20u32,12u32)
  let r=1u32..=2u32
  var sum u32=0u32
  for x in xs { sum=sum+x }
  for y in r { sum=sum+y }
  return sum
}
''')
        e=proc(OMNI,'eval',p); self.assertEqual(e.returncode,45,e.stderr)
        native=self.d/'iteration-native'; b=proc(OMNI,'build',p,'-o',native); self.assertEqual(b.returncode,0,b.stderr)
        n=proc(native); self.assertEqual((n.returncode,n.stdout),(e.returncode,e.stdout),n.stderr)
        wave=proc(OMNI,'wave',p); self.assertEqual(wave.returncode,0,wave.stderr); self.assertIn(b'(for-each ',wave.stdout)
        wp=self.d/'iteration.owave'; wp.write_bytes(wave.stdout); self.assertEqual(proc(OMNI,'eval',wp).returncode,45)
        wire=self.d/'iteration.owire'; self.assertEqual(proc(OMNI,'pack',p,'-o',wire).returncode,0); self.assertEqual(proc(OMNI,'eval',wire).returncode,45)
    def test_unresolved_iterator_trait_cannot_create_runtime_dispatch(self):
        p=self.source('''module t
trait Iterator {}
impl Iterator for u32 {}
func main() u32 { for x in 1u32 { } return 0u32 }
''')
        r=proc(OMNI,'check',p); self.assertEqual(r.returncode,2); self.assertIn(b'E_ITERABLE',r.stderr)

if __name__=='__main__': unittest.main(verbosity=2)
