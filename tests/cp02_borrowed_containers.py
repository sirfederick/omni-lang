#!/usr/bin/env python3
"""CP-02 / CP-05: containers handed around by Borrow / BorrowMut (spec/NOMINAL_BUFFER_RESOURCE_CANDIDATE.md).

* a nominal resource may wrap a Resource<Buffer> (not only a u64) and may be an instance of a generic struct: Resource<Vec<u32>>, Borrow<Vec<u32>>;
* resource.inner / resource.inner_mut give the module that declares it the Buffer inside a borrow of it, and nobody else;
* a Borrow/BorrowMut parameter is a loan held by the caller: borrow(p) is an ordinary reborrow (it used to be E_BORROW_EXPIRED) and p is suspended while
  a child reborrow is live;
* examples/storage/vec.omni is the library written on top of them: Vec<T: Codec, A: alloc.Allocator> for any element type that implements the trait.
Positive programs run in the evaluator and natively and must agree; the loops exceed the 1024-slot buffer table so a leak or a double release fails.
"""
from __future__ import annotations
import os
import pathlib
import shutil
import subprocess
import tempfile
import unittest
from language_0_8_3_alpha8 import ROOT, OMNI, proc

VEC = ROOT / 'examples' / 'storage' / 'vec.omni'


class ContainerCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='omni-cp02-')
        self.dir = pathlib.Path(self.tmp.name)
        shutil.copy(VEC, self.dir / 'vec.omni')
        shutil.copy(VEC.parent / 'alloc.omni', self.dir / 'alloc.omni')

    def tearDown(self):
        self.tmp.cleanup()

    def source(self, text, name='program.omni'):
        path = self.dir / name
        path.write_text('module t\nimport vec "vec.omni"\nimport alloc "alloc.omni"\n' + text, encoding='utf-8')
        return path

    def build_native(self, path, output):
        """The native executable of a program. With OMNI_NATIVE_SANITIZE=1 the executable and the C runtime are instrumented (ASan/UBSan) - a different check from
        running the instrumented COMPILER, which leaves the runtime and the programs it builds uninstrumented."""
        output.unlink(missing_ok=True)
        if os.environ.get('OMNI_NATIVE_SANITIZE') != '1':
            return proc(OMNI, 'build', path, '-o', output, '--cache-dir', self.dir / 'cache', timeout=180)
        ir = self.dir / (path.name + '.ll')
        ir.unlink(missing_ok=True)
        emitted = proc(OMNI, 'emit-llvm', path, '-o', ir, timeout=180)
        if emitted.returncode != 0:
            return emitted
        return subprocess.run(['clang', '-O1', '-g', '-fsanitize=address,undefined', '-fno-omit-frame-pointer', str(ir), str(ROOT / 'runtime' / 'omni_runtime.c'),
                               '-o', str(output), '-lcrypto'], capture_output=True, timeout=300)

    def both(self, path, expected=42):
        evaluated = proc(OMNI, 'eval', path, timeout=180)
        self.assertEqual(evaluated.returncode, expected, evaluated.stderr)
        native = self.dir / (path.name + '-native')
        built = self.build_native(path, native)
        self.assertEqual(built.returncode, 0, built.stderr)
        executed = proc(native, timeout=180)
        self.assertEqual(executed.returncode, expected, executed.stderr)

    def rejected(self, text, code, name='bad.omni'):
        path = self.source(text, name)
        checked = proc(OMNI, 'check', path)
        self.assertEqual(checked.returncode, 2, checked.stderr)
        self.assertIn(code, checked.stderr)
        output = self.dir / 'never'
        output.unlink(missing_ok=True)
        built = proc(OMNI, 'build', path, '-o', output, '--cache-dir', self.dir / 'cache')
        self.assertEqual(built.returncode, 2, built.stderr)
        self.assertFalse(output.exists())

    MAIN = 'func main() u32 !{memory.read,memory.write} {\n'


class GenericVectorTests(ContainerCase):
    # The work is done by functions that are LENT the vector (BorrowMut<Vec<T>>), so an early return never abandons it; main only creates, calls and destroys.
    def run_with(self, body_functions, call):
        return self.source(
            body_functions +
            'func main() u32 !{memory.read,memory.write} {\n  let c = ' + call + '\n  match c { Ok(v) {\n'
            '    let code u32 = exercise(borrow_mut(v))\n    let d = vec.destroy<u32,alloc.Heap>(move(v))\n    if code != 0u32 { return code }\n    return 42u32\n'
            '  } Err(e) { return e } }\n}\n')

    def test_u32_vector_grows_reads_writes_and_pops_through_borrows(self):
        self.both(self.run_with(
            'func exercise(v BorrowMut<vec.Vec<u32,alloc.Heap>>) u32 !{memory.read,memory.write} {\n'
            '  var i u32 = 0u32\n  for i < 300u32 {\n    let r = vec.push<u32,alloc.Heap>(v, i * 3u32)\n    match r { Ok(n) { } Err(e) { return 200u32 + e } }\n    i = i + 1u32\n  }\n'
            '  if vec.len<u32,alloc.Heap>(borrow(v)) != 300u32 { return 1u32 }\n  if vec.capacity<u32,alloc.Heap>(borrow(v)) != 512u32 { return 2u32 }\n'
            '  let g = vec.get<u32,alloc.Heap>(borrow(v), 299u32)\n  match g { Ok(x) { if x != 897u32 { return 3u32 } } Err(e) { return 4u32 } }\n'
            '  let s = vec.set<u32,alloc.Heap>(v, 0u32, 7u32)\n  match s { Ok(x) { } Err(e) { return 5u32 } }\n'
            '  let g0 = vec.get<u32,alloc.Heap>(borrow(v), 0u32)\n  match g0 { Ok(x) { if x != 7u32 { return 6u32 } } Err(e) { return 7u32 } }\n'
            '  let p = vec.pop<u32,alloc.Heap>(v)\n  match p { Ok(x) { if x != 897u32 { return 8u32 } } Err(e) { return 9u32 } }\n'
            '  if vec.len<u32,alloc.Heap>(borrow(v)) != 299u32 { return 10u32 }\n'
            '  let past = vec.get<u32,alloc.Heap>(borrow(v), 299u32)\n  match past { Ok(x) { return 11u32 } Err(e) { if e != 10u32 { return 12u32 } } }\n'
            '  return 0u32\n}\n', 'vec.new<u32,alloc.Heap>(0u32)'))

    def test_two_instantiations_are_distinct_types_and_both_work(self):
        self.both(self.source(
            'func exercise(x BorrowMut<vec.Vec<u32,alloc.Heap>>, y BorrowMut<vec.Vec<u64,alloc.Heap>>) u32 !{memory.read,memory.write} {\n'
            '  let r1 = vec.push<u32,alloc.Heap>(x, 40u32)\n  match r1 { Ok(n) { } Err(e) { return 1u32 } }\n'
            '  let r2 = vec.push<u64,alloc.Heap>(y, 5000000000u64)\n  match r2 { Ok(n) { } Err(e) { return 2u32 } }\n'
            '  var total u32 = 0u32\n'
            '  let g1 = vec.get<u32,alloc.Heap>(borrow(x), 0u32)\n  match g1 { Ok(v) { total = total + v } Err(e) { return 3u32 } }\n'
            '  let g2 = vec.get<u64,alloc.Heap>(borrow(y), 0u32)\n  match g2 { Ok(v) { if v != 5000000000u64 { return 4u32 } total = total + 2u32 } Err(e) { return 5u32 } }\n'
            '  return total\n}\n'
            'func main() u32 !{memory.read,memory.write} {\n  let a = vec.new<u32,alloc.Heap>(2u32)\n'
            '  match a { Ok(x) {\n    let b = vec.new<u64,alloc.Heap>(2u32)\n    match b { Ok(y) {\n'
            '      let code u32 = exercise(borrow_mut(x), borrow_mut(y))\n'
            '      let d1 = vec.destroy<u32,alloc.Heap>(move(x))\n      let d2 = vec.destroy<u64,alloc.Heap>(move(y))\n      return code\n'
            '    } Err(e) { let d = vec.destroy<u32,alloc.Heap>(move(x)); return e } }\n  } Err(e) { return e } }\n}\n'))

    def test_a_user_element_type_implements_the_trait_from_another_module(self):
        self.both(self.source(
            'struct Pair { a u32, b u32 }\n'
            'impl vec.Codec for Pair {\n  func size() u32 { return 8u32 }\n'
            '  func put(b BorrowMut<Buffer>, off u32, v Pair) Result<u32,u32> !{memory.write} {\n'
            '    let w = buffer.write_u32le(b, off, v.a)\n    match w { Ok(n) { return buffer.write_u32le(b, off + 4u32, v.b) } Err(e) { return Err<u32,u32>(e) } }\n  }\n'
            '  func get(b Borrow<Buffer>, off u32) Result<Pair,u32> !{memory.read} {\n'
            '    let x = buffer.read_u32le(b, off)\n    match x { Ok(a) {\n      let y = buffer.read_u32le(b, off + 4u32)\n'
            '      match y { Ok(c) { return Ok<Pair,u32>(Pair { a: a, b: c }) } Err(e) { return Err<Pair,u32>(e) } }\n    } Err(e) { return Err<Pair,u32>(e) } }\n  }\n}\n'
            'func exercise(v BorrowMut<vec.Vec<Pair,alloc.Heap>>) u32 !{memory.read,memory.write} {\n'
            '  var i u32 = 0u32\n  for i < 10u32 {\n    let r = vec.push<Pair,alloc.Heap>(v, Pair { a: i, b: i * 2u32 })\n    match r { Ok(n) { } Err(e) { return 100u32 + e } }\n    i = i + 1u32\n  }\n'
            '  let g = vec.get<Pair,alloc.Heap>(borrow(v), 9u32)\n  match g { Ok(p) { if p.a + p.b != 27u32 { return 1u32 } } Err(e) { return 2u32 } }\n  return 0u32\n}\n'
            'func main() u32 !{memory.read,memory.write} {\n  let c = vec.new<Pair,alloc.Heap>(1u32)\n  match c { Ok(v) {\n'
            '    let code u32 = exercise(borrow_mut(v))\n    let d = vec.destroy<Pair,alloc.Heap>(move(v))\n    if code != 0u32 { return code }\n    return 42u32\n  } Err(e) { return e } }\n}\n'))

    def test_typed_failures_leave_the_vector_intact_and_in_the_callers_hands(self):
        self.both(self.source(
            'func exercise(v BorrowMut<vec.Vec<u32,alloc.Heap>>) u32 !{memory.read,memory.write} {\n'
            '  let e1 = vec.pop<u32,alloc.Heap>(v)\n  match e1 { Ok(x) { return 1u32 } Err(e) { if e != 11u32 { return 2u32 } } }\n'
            '  let e2 = vec.set<u32,alloc.Heap>(v, 0u32, 1u32)\n  match e2 { Ok(x) { return 3u32 } Err(e) { if e != 10u32 { return 4u32 } } }\n'
            '  let ok = vec.push<u32,alloc.Heap>(v, 9u32)\n  match ok { Ok(n) { if n != 1u32 { return 7u32 } } Err(e) { return 8u32 } }\n'
            '  if vec.len<u32,alloc.Heap>(borrow(v)) != 1u32 { return 9u32 }\n'
            '  return 0u32\n}\n'
            'func too_big() u32 !{memory.read,memory.write} {\n  let big = vec.new<u32,alloc.Heap>(300000u32)\n'
            '  match big { Ok(w) { let d = vec.destroy<u32,alloc.Heap>(move(w)); return 5u32 } Err(e) { if e != 1u32 { return 6u32 } } }\n  return 0u32\n}\n'
            'func main() u32 !{memory.read,memory.write} {\n  let c = vec.new<u32,alloc.Heap>(4u32)\n  match c { Ok(v) {\n'
            '    let code u32 = exercise(borrow_mut(v))\n    let d = vec.destroy<u32,alloc.Heap>(move(v))\n    if code != 0u32 { return code }\n'
            '    let big u32 = too_big()\n    if big != 0u32 { return big }\n    return 42u32\n  } Err(e) { return e } }\n}\n'))

    def test_pop_clears_the_slot_it_vacates_and_a_huge_capacity_cannot_wrap(self):
        # A Codec sees the buffer: Spy.get reads the slot AFTER its own, so it reveals whether pop cleared the slot it vacated.
        self.both(self.source(
            'struct Spy { a u32 }\n'
            'impl vec.Codec for Spy {\n  func size() u32 { return 4u32 }\n'
            '  func put(b BorrowMut<Buffer>, off u32, v Spy) Result<u32,u32> !{memory.write} { return buffer.write_u32le(b, off, v.a) }\n'
            '  func get(b Borrow<Buffer>, off u32) Result<Spy,u32> !{memory.read} {\n'
            '    let x = buffer.read_u32le(b, off + 4u32)\n    match x { Ok(a) { return Ok<Spy,u32>(Spy { a: a }) } Err(e) { return Err<Spy,u32>(e) } }\n  }\n}\n'
            'func exercise(v BorrowMut<vec.Vec<Spy,alloc.Heap>>) u32 !{memory.read,memory.write} {\n'
            '  let a = vec.push<Spy,alloc.Heap>(v, Spy { a: 1u32 })\n  match a { Ok(n) { } Err(e) { return 1u32 } }\n'
            '  let b = vec.push<Spy,alloc.Heap>(v, Spy { a: 2u32 })\n  match b { Ok(n) { } Err(e) { return 2u32 } }\n'
            '  let before = vec.get<Spy,alloc.Heap>(borrow(v), 0u32)\n  match before { Ok(x) { if x.a != 2u32 { return 3u32 } } Err(e) { return 4u32 } }\n'
            '  let p = vec.pop<Spy,alloc.Heap>(v)\n  match p { Ok(x) { } Err(e) { return 5u32 } }\n'
            '  let after = vec.get<Spy,alloc.Heap>(borrow(v), 0u32)\n  match after { Ok(x) { if x.a != 0u32 { return 6u32 } } Err(e) { return 7u32 } }\n'
            '  return 0u32\n}\n'
            'func wrap() u32 !{memory.read,memory.write} {\n'
            '  let w = vec.new<u32,alloc.Heap>(1073741825u32)\n  match w { Ok(x) { let d = vec.destroy<u32,alloc.Heap>(move(x)); return 1u32 } Err(e) { if e != 1u32 { return 2u32 } } }\n  return 0u32\n}\n'
            'func main() u32 !{memory.read,memory.write} {\n  let c = vec.new<Spy,alloc.Heap>(4u32)\n  match c { Ok(v) {\n'
            '    let code u32 = exercise(borrow_mut(v))\n    let d = vec.destroy<Spy,alloc.Heap>(move(v))\n    if code != 0u32 { return code }\n'
            '    let wrapped u32 = wrap()\n    if wrapped != 0u32 { return 10u32 + wrapped }\n    return 42u32\n  } Err(e) { return e } }\n}\n'))

    def test_every_vector_is_released_exactly_once_beyond_the_handle_table(self):
        self.both(self.source(
            'func fill(v BorrowMut<vec.Vec<u32,alloc.Heap>>, n u32) u32 !{memory.read,memory.write} {\n  var i u32 = 0u32\n  for i < n {\n    let r = vec.push<u32,alloc.Heap>(v, i)\n'
            '    match r { Ok(k) { } Err(e) { return 1u32 } }\n    i = i + 1u32\n  }\n  return 0u32\n}\n'
            'func cycle(n u32) u32 !{memory.read,memory.write} {\n  let c = vec.new<u32,alloc.Heap>(0u32)\n  match c { Ok(v) {\n'
            '    let code u32 = fill(borrow_mut(v), n)\n    let d = vec.destroy<u32,alloc.Heap>(move(v))\n    return code\n  } Err(e) { return 2u32 } }\n}\n'
            'func main() u32 !{memory.read,memory.write} {\n  var i u32 = 0u32\n  for i < 1200u32 {\n    if cycle(3u32) != 0u32 { return 1u32 }\n    i = i + 1u32\n  }\n'
            '  let probe = buffer.alloc(8u32)\n  match probe { Ok(p) { return buffer.len(borrow(p)) + 34u32 } Err(e) { return e } }\n}\n'))


class NominalBufferResourceLawTests(ContainerCase):
    PRE = 'func new_vec() Resource<vec.Vec<u32,alloc.Heap>> !{memory.read,memory.write} {\n'

    def test_the_laws_of_a_nominal_resource_hold_for_a_wrapped_buffer(self):
        pre = ('func make() Result<Resource<vec.Vec<u32,alloc.Heap>>,u32> !{memory.read,memory.write} { return vec.new<u32,alloc.Heap>(2u32) }\n'
               'func main() u32 !{memory.read,memory.write} {\n  let c = make()\n  match c { Ok(v) {\n')
        post = '  } Err(e) { return e } }\n}\n'
        for name, body, code in (
            ('never destroyed', '    return 0u32\n', b'E_RESOURCE_UNCONSUMED'),
            ('destroyed twice', '    let a = vec.destroy<u32,alloc.Heap>(move(v))\n    let b = vec.destroy<u32,alloc.Heap>(move(v))\n    return 0u32\n', b'E_RESOURCE_MOVED'),
            ('used after destroy', '    let a = vec.destroy<u32,alloc.Heap>(move(v))\n    let n = vec.len<u32,alloc.Heap>(borrow(v))\n    return n\n', b'E_RESOURCE_MOVED'),
            ('copied', '    let twin = v\n    let a = vec.destroy<u32,alloc.Heap>(move(twin))\n    return 0u32\n', b'E_RESOURCE_ACCESS'),
            ('lent as the wrong element type', '    let a = vec.len<u64,alloc.Heap>(borrow(v))\n    let d = vec.destroy<u32,alloc.Heap>(move(v))\n    return a\n', b'E_TYPE'),
            ('pushed with the wrong element type',
             '    let r = vec.push<u32,alloc.Heap>(borrow_mut(v), 1u64)\n    match r { Ok(n) { } Err(e) { } }\n    let d = vec.destroy<u32,alloc.Heap>(move(v))\n    return 0u32\n', b'E_TYPE'),
            ('mutated through a shared borrow',
             '    let r = vec.push<u32,alloc.Heap>(borrow(v), 1u32)\n    match r { Ok(n) { } Err(e) { } }\n    let d = vec.destroy<u32,alloc.Heap>(move(v))\n    return 0u32\n', b'E_TYPE'),
        ):
            with self.subTest(name=name):
                self.rejected(pre + body + post, code)

    def test_only_the_declaring_module_can_look_inside(self):
        for name, body, code in (
            ('seal', 'func f(b Resource<Buffer>) Resource<vec.Vec<u32,alloc.Heap>> { return resource.seal(vec.Vec<u32,alloc.Heap> { buf: move(b) }) }\nfunc main() u32 { return 0u32 }\n', b'E_RESOURCE_PRIVATE'),
            ('inner', 'func f(v Borrow<vec.Vec<u32,alloc.Heap>>) u32 !{memory.read} { return buffer.len(resource.inner(v)) }\nfunc main() u32 { return 0u32 }\n', b'E_RESOURCE_PRIVATE'),
            ('unseal', 'func f(v Resource<vec.Vec<u32,alloc.Heap>>) u32 { let x = resource.unseal(move(v)); return 0u32 }\nfunc main() u32 { return 0u32 }\n', b'E_RESOURCE_PRIVATE'),
        ):
            with self.subTest(name=name):
                self.rejected(body, code)

    BOX = 'struct Box { buf Resource<Buffer> }\nstruct Handle { h u64 }\n'

    def test_inner_and_peek_belong_to_their_own_kind_of_nominal_resource(self):
        for name, body, code in (
            ('inner of a u64 handle', 'func f(x Borrow<Handle>) u32 !{memory.read} { return buffer.len(resource.inner(x)) }\n', b'E_RESOURCE_TYPE'),
            ('peek of a wrapped buffer', 'func f(x Borrow<Box>) u32 { let c Box = resource.peek(x); return 0u32 }\n', b'E_RESOURCE_TYPE'),
            ('inner_mut through a shared borrow', 'func f(x Borrow<Box>) u32 !{memory.read} { return buffer.len(resource.inner_mut(x)) }\n', b'E_TYPE'),
            ('inner of the Buffer itself', 'func f(x Borrow<Buffer>) u32 !{memory.read} { return buffer.len(resource.inner(x)) }\n', b'E_TYPE'),
        ):
            with self.subTest(name=name):
                self.rejected(self.BOX + body + 'func main() u32 { return 0u32 }\n', code)

    def test_the_buffer_inside_an_inline_borrow_and_a_second_argument_that_touches_the_container(self):
        # (1) resource.inner of a borrow written in place, not only of a name: the Place comes from the borrow expression
        self.both(self.source(self.BOX.replace('struct Handle { h u64 }\n', '') +
                              'func make() Resource<Box> !{memory.write} {\n  let a = buffer.alloc(42u32)\n  match a { Ok(b) { return resource.seal(Box { buf: move(b) }) } Err(e) { return make() } }\n}\n'
                              'func drop(x Resource<Box>) u32 !{memory.write} {\n  let i Box = resource.unseal(move(x))\n  return buffer.release(move(i.buf))\n}\n'
                              'func blen(a Borrow<Buffer>) u32 !{memory.read} { return buffer.len(a) }\n'
                              'func main() u32 !{memory.read,memory.write} {\n  let r = make()\n  let n = blen(resource.inner(borrow(r)))\n  let d = drop(move(r))\n  return n\n}\n'))
        # (2) the exclusive view of a container is a live loan while the OTHER arguments of the same call are evaluated
        self.rejected(self.BOX + 'func two(a BorrowMut<Buffer>, n u32) u32 !{memory.read} { return n }\n'
                      'func size(x Borrow<Box>) u32 !{memory.read} { return buffer.len(resource.inner(x)) }\n'
                      'func f(x BorrowMut<Box>) u32 !{memory.read} { return two(resource.inner_mut(x), size(borrow(x))) }\n'
                      'func main() u32 { return 0u32 }\n', b'E_BORROW_CONFLICT')

    def test_the_buffers_of_two_different_fields_are_disjoint_places(self):
        # inner / inner_mut keep the field path of the borrow they came from, so the views of h.a and h.b can be lent together; two views of h.a cannot
        holder = (self.BOX.replace('struct Handle { h u64 }\n', '') + 'struct Holder { a Resource<Box>, b Resource<Box> }\n'
                  'func make(n u32) Resource<Box> !{memory.write} {\n  let a = buffer.alloc(n)\n  match a { Ok(b) { return resource.seal(Box { buf: move(b) }) } Err(e) { return make(n) } }\n}\n'
                  'func drop(x Resource<Box>) u32 !{memory.write} {\n  let i Box = resource.unseal(move(x))\n  return buffer.release(move(i.buf))\n}\n'
                  'func pair(x Borrow<Buffer>, y BorrowMut<Buffer>) u32 !{memory.read} { return buffer.len(x) + buffer.len(y) }\n')
        self.both(self.source(holder +
                              'func main() u32 !{memory.read,memory.write} {\n  let h = Holder { a: make(20u32), b: make(22u32) }\n'
                              '  let n = pair(resource.inner(borrow(h.a)), resource.inner_mut(borrow_mut(h.b)))\n'
                              '  let d1 = drop(move(h.a))\n  let d2 = drop(move(h.b))\n  return n\n}\n'))
        self.rejected(holder +
                      'func main() u32 !{memory.read,memory.write} {\n  let h = Holder { a: make(20u32), b: make(22u32) }\n'
                      '  let n = pair(resource.inner(borrow(h.a)), resource.inner_mut(borrow_mut(h.a)))\n'
                      '  let d1 = drop(move(h.a))\n  let d2 = drop(move(h.b))\n  return n\n}\n', b'E_BORROW_CONFLICT')

    def test_the_buffer_inside_a_borrow_is_the_same_loan_for_the_arguments_of_a_call(self):
        # inner / inner_mut stand on the Place of the borrow they came from: the exclusive and the shared view of one container cannot meet in one call
        self.rejected(self.BOX + 'func two(a BorrowMut<Buffer>, b Borrow<Buffer>) u32 !{memory.read} { return buffer.len(b) }\n'
                      'func f(x BorrowMut<Box>) u32 !{memory.read} { return two(resource.inner_mut(x), resource.inner(x)) }\n'
                      'func main() u32 { return 0u32 }\n', b'E_BORROW_CONFLICT')
        self.both(self.source(self.BOX.replace('struct Handle { h u64 }\n', '') +
                              'func two(a Borrow<Buffer>, b Borrow<Buffer>) u32 !{memory.read} { return buffer.len(a) + buffer.len(b) }\n'
                              'func f(x Borrow<Box>) u32 !{memory.read} { return two(resource.inner(x), resource.inner(x)) }\n'
                              'func make() Resource<Box> !{memory.write} {\n  let a = buffer.alloc(21u32)\n  match a { Ok(b) { return resource.seal(Box { buf: move(b) }) } Err(e) { return make() } }\n}\n'
                              'func drop(x Resource<Box>) u32 !{memory.write} {\n  let i Box = resource.unseal(move(x))\n  return buffer.release(move(i.buf))\n}\n'
                              'func main() u32 !{memory.read,memory.write} {\n  let r = make()\n  let n = f(borrow(r))\n  let d = drop(move(r))\n  return n\n}\n'))

    def test_an_element_type_without_the_trait_is_refused(self):
        self.rejected('func main() u32 !{memory.read,memory.write} {\n  let c = vec.new<Text,alloc.Heap>(1u32)\n  match c { Ok(v) { return 0u32 } Err(e) { return e } }\n}\n',
                      b'E_GENERIC_CONSTRAINT')


class BorrowedParameterTests(ContainerCase):
    """A Borrow/BorrowMut parameter is a loan held by the caller for the whole call."""
    HEAD = ('func use(b Borrow<Buffer>) u32 !{memory.read} { return buffer.len(b) }\n'
            'func edit(b BorrowMut<Buffer>) u32 !{memory.read,memory.write} { return buffer.len(b) }\n')

    def program(self, body):
        return (self.HEAD + 'func f(p BorrowMut<Buffer>) u32 !{memory.read,memory.write} {\n' + body + '}\n'
                'func main() u32 !{memory.read,memory.write} {\n  let a = buffer.alloc(4u32)\n  match a { Ok(b) {\n'
                '    let r = f(borrow_mut(b))\n    let rel = buffer.release(move(b))\n    return r + 34u32\n  } Err(e) { return e } }\n}\n')

    def test_a_parameter_can_be_reborrowed_explicitly_shared_and_exclusive(self):
        self.both(self.source(self.program(
            '  let a = use(borrow(p))\n  let b = edit(borrow_mut(p))\n  let c = buffer.len(borrow(p))\n  return a + b + c - 4u32\n')))

    def test_a_parameter_is_usable_again_when_the_child_is_no_longer_needed(self):
        self.both(self.source(self.program(
            '  let r = borrow(p)\n  let a = buffer.len(r)\n  let b = edit(p)\n  return a + b\n')))

    def test_the_parent_is_suspended_while_a_child_reborrow_is_live(self):
        for name, body, code in (
            ('exclusive use of the parent while a shared child lives',
             '  let r = borrow(p)\n  let b = edit(p)\n  return buffer.len(r) + b\n', b'E_BORROW_CONFLICT'),
            ('two exclusive children',
             '  let r = borrow_mut(p)\n  let s = borrow_mut(p)\n  return buffer.len(r) + buffer.len(s)\n', b'E_BORROW_CONFLICT'),
            ('a shared child and an exclusive child',
             '  let r = borrow(p)\n  let s = borrow_mut(p)\n  return buffer.len(r) + buffer.len(s)\n', b'E_BORROW_CONFLICT'),
        ):
            with self.subTest(name=name):
                self.rejected(self.program(body), code)

    def test_a_shared_parameter_cannot_be_reborrowed_exclusively(self):
        self.rejected('func f(p Borrow<Buffer>) u32 !{memory.read,memory.write} {\n  let r = borrow_mut(p)\n  return buffer.len(r)\n}\n'
                      'func main() u32 { return 0u32 }\n', b'E_REBORROW_KIND')

    def test_growing_a_container_while_a_borrow_of_it_is_live_is_a_conflict(self):
        self.rejected(
            'func main() u32 !{memory.read,memory.write} {\n  let c = vec.new<u32,alloc.Heap>(1u32)\n  match c { Ok(v) {\n'
            '    let view = borrow(v)\n    let r = vec.push<u32,alloc.Heap>(borrow_mut(v), 1u32)\n    match r { Ok(n) { } Err(e) { } }\n'
            '    let n = vec.len<u32,alloc.Heap>(view)\n    let d = vec.destroy<u32,alloc.Heap>(move(v))\n    return n\n  } Err(e) { return e } }\n}\n', b'E_BORROW_CONFLICT')


class RepresentationTests(ContainerCase):
    PROGRAM = ('func exercise(v BorrowMut<vec.Vec<u32,alloc.Heap>>) u32 !{memory.read,memory.write} {\n'
               '  let r = vec.push<u32,alloc.Heap>(v, 40u32)\n  match r { Ok(n) { } Err(e) { return 1u32 } }\n'
               '  let g = vec.get<u32,alloc.Heap>(borrow(v), 0u32)\n  match g { Ok(x) { return x } Err(e) { return 99u32 } }\n}\n'
               'func main() u32 !{memory.read,memory.write} {\n  let c = vec.new<u32,alloc.Heap>(1u32)\n  match c { Ok(v) {\n'
               '    let out u32 = exercise(borrow_mut(v))\n    let d = vec.destroy<u32,alloc.Heap>(move(v))\n    return out + 2u32\n  } Err(e) { return e } }\n}\n')

    # one module, no generics and no trait: the representation is decided by the nominal Buffer-wrapping resource alone (a program with generics or traits keeps its
    # authoring capsule and is Wave22, which would hide whether this feature has its own fence)
    STANDALONE = ('struct Box { buf Resource<Buffer> }\n'
                  'func make() Resource<Box> !{memory.write} {\n  let a = buffer.alloc(4u32)\n  match a { Ok(b) { return resource.seal(Box { buf: move(b) }) } Err(e) { return make() } }\n}\n'
                  'func size(x Borrow<Box>) u32 !{memory.read} { return buffer.len(resource.inner(x)) }\n'
                  'func drop(x Resource<Box>) u32 !{memory.write} {\n  let i Box = resource.unseal(move(x))\n  return buffer.release(move(i.buf))\n}\n'
                  'func main() u32 !{memory.read,memory.write} {\n  let r = make()\n  let n = size(borrow(r))\n  let d = drop(move(r))\n  return n + 38u32\n}\n')

    def test_programs_with_a_buffer_wrapping_nominal_resource_cannot_be_relabelled_as_older(self):
        path = self.dir / 'standalone.omni'
        path.write_text('module t\n' + self.STANDALONE, encoding='utf-8')
        wave = proc(OMNI, 'wave', path)
        self.assertEqual(wave.returncode, 0, wave.stderr)
        self.assertTrue(wave.stdout.startswith(b'(omni-wave 21'))
        old = self.dir / 'old.owave'
        old.write_bytes(wave.stdout.replace(b'(omni-wave 21', b'(omni-wave 20', 1))
        refused = proc(OMNI, 'check', old)
        self.assertEqual(refused.returncode, 2)
        self.assertIn(b'E_VERSION', refused.stderr)
        wire = self.dir / 'new.owire'
        self.assertEqual(proc(OMNI, 'pack', path, '-o', wire).returncode, 0)
        raw = bytearray(wire.read_bytes())
        raw[4] = 20
        older = self.dir / 'old.owire'
        older.write_bytes(bytes(raw))
        refused = proc(OMNI, 'check', older)
        self.assertEqual(refused.returncode, 2)
        self.assertIn(b'E_VERSION', refused.stderr)

    def test_resource_inner_alone_is_enough_to_need_wave21(self):
        # no seal and no unseal anywhere: the fence must come from resource.inner / resource.inner_mut themselves
        for call in ('resource.inner(x)', 'resource.inner_mut(x)'):
            with self.subTest(call=call):
                kind = 'BorrowMut' if call.endswith('mut(x)') else 'Borrow'
                path = self.dir / 'inner_only.omni'
                path.write_text('module t\nstruct Box { buf Resource<Buffer> }\nfunc size(x ' + kind + '<Box>) u32 !{memory.read} { return buffer.len(' + call + ') }\n'
                                'func main() u32 { return 0u32 }\n', encoding='utf-8')
                wave = proc(OMNI, 'wave', path)
                self.assertEqual(wave.returncode, 0, wave.stderr)
                self.assertTrue(wave.stdout.startswith(b'(omni-wave 21'), wave.stdout[:40])
                old = self.dir / 'inner_old.owave'
                old.write_bytes(wave.stdout.replace(b'(omni-wave 21', b'(omni-wave 20', 1))
                refused = proc(OMNI, 'check', old)
                self.assertEqual(refused.returncode, 2)
                self.assertIn(b'E_VERSION', refused.stderr)

    def test_the_program_round_trips_through_every_representation(self):
        path = self.source(self.PROGRAM)
        wave = proc(OMNI, 'wave', path)
        owave = self.dir / 'rt.owave'
        owave.write_bytes(wave.stdout)
        self.assertEqual(proc(OMNI, 'wave', owave).stdout, wave.stdout)
        wire = self.dir / 'rt.owire'
        self.assertEqual(proc(OMNI, 'pack', path, '-o', wire).returncode, 0)
        self.assertEqual(proc(OMNI, 'wave', wire).stdout, wave.stdout)
        rewire = self.dir / 'rt2.owire'
        self.assertEqual(proc(OMNI, 'pack', owave, '-o', rewire).returncode, 0)
        self.assertEqual(rewire.read_bytes(), wire.read_bytes())
        onme = self.dir / 'rt.onme'
        self.assertEqual(proc(OMNI, 'onme', path, '-o', onme).returncode, 0)
        self.assertEqual(proc(OMNI, 'wave', onme).stdout, wave.stdout)
        for artifact in (path, owave, wire, onme):
            self.assertEqual(proc(OMNI, 'eval', artifact).returncode, 42, artifact.name)


if __name__ == '__main__':
    unittest.main()
