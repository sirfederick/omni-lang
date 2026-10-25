#!/usr/bin/env python3
"""CP-01 1.7 / CP-04 4.7-4.8 / CP-05 5.7: a dynamic collection whose elements are resources (spec/OWNED_SLOTS_CANDIDATE.md, examples/storage/seq.omni).

The elements are moved in and out whole by the runtime; no handle is ever an integer in Omni code. These tests demonstrate, in the evaluator and natively:
creation, transfer in and out, lending, growth, a failing allocation, extraction and exact cleanup (loops that exceed the 1024-slot buffer table, so a leak or a
double release fails), and what must stay refused: use after move, an element left unconsumed, a sequence left alive, opening a sequence from another module,
growth under a live element borrow, a plain value as an element, byte access to cells, a foreign type tag, and freeing a buffer that still owns resources.
"""
from __future__ import annotations
import shutil
import unittest
from cp02_borrowed_containers import ContainerCase
from language_0_8_3_alpha8 import ROOT, OMNI, proc

SEQ = ROOT / 'examples' / 'storage' / 'seq.omni'

TOK = ('struct Tok { h u64 }\nstruct Other { h u64 }\n'
       'func mint_other(n u64) Resource<Other> { return resource.seal(Other { h: n }) }\n'
       'func eat_other(f Resource<Other>) u64 { let r Other = resource.unseal(move(f))\n  return r.h }\n'
       'func mint(n u64) Resource<Tok> { return resource.seal(Tok { h: n }) }\n'
       'func val(x Borrow<Tok>) u64 { let r Tok = resource.peek(x)\n  return r.h }\n'
       'func eat(f Resource<Tok>) u64 { let r Tok = resource.unseal(move(f))\n  return r.h }\n'
       'impl seq.Dispose for Tok { func dispose(x Resource<Tok>) u32 !{memory.write} { let r Tok = resource.unseal(move(x))\n  return 1u32 } }\n')

BLOB = ('struct Blob { b Resource<Buffer> }\n'
        'func blob(n u32) Result<Resource<Blob>,u32> !{memory.write} {\n  let a = buffer.alloc(n)\n'
        '  match a { Ok(buf) {\n    let i Blob = Blob { b: move(buf) }\n    return Ok<Resource<Blob>,u32>(resource.seal(move(i)))\n  } Err(e) { return Err<Resource<Blob>,u32>(e) } }\n}\n'
        'func blob_set(x BorrowMut<Blob>, v u32) u32 !{memory.write} {\n  let w = buffer.write_u32le(resource.inner_mut(x), 0u32, v)\n  match w { Ok(n) { return 0u32 } Err(e) { return e } }\n}\n'
        'func blob_get(x Borrow<Blob>) u32 !{memory.read} {\n  let r = buffer.read_u32le(resource.inner(x), 0u32)\n  match r { Ok(v) { return v } Err(e) { return 1000u32 + e } }\n}\n'
        'impl seq.Dispose for Blob { func dispose(x Resource<Blob>) u32 !{memory.write} {\n'
        '  let i Blob = resource.unseal(move(x))\n  let z u32 = buffer.release(move(i.b))\n  return 1u32 } }\n')


class SeqCase(ContainerCase):
    def setUp(self):
        super().setUp()
        shutil.copy(SEQ, self.dir / 'seq.omni')

    def source(self, text, name='program.omni'):
        return super().source('import seq "seq.omni"\n' + text, name)

    def faults(self, path, code):
        evaluated = proc(OMNI, 'eval', path, timeout=180)
        self.assertNotEqual(evaluated.returncode, 0, evaluated.stderr)
        self.assertIn(code, evaluated.stderr)
        native = self.dir / 'fault-native'
        built = self.build_native(path, native)
        self.assertEqual(built.returncode, 0, built.stderr)
        executed = proc(native, timeout=180)
        self.assertNotEqual(executed.returncode, 0)
        self.assertIn(code, executed.stderr)


class OwnedSequenceTests(SeqCase):
    def test_elements_move_in_grow_are_lent_and_move_out_and_the_rest_is_disposed_once(self):
        self.both(self.source(TOK +
            'func put(v BorrowMut<seq.Seq<Tok>>, n u64) u32 !{memory.read,memory.write} {\n'
            '  let g = seq.reserve<Tok>(borrow_mut(v))\n  match g { Ok(c) { } Err(e) { return 100u32 + e } }\n'
            '  let r = seq.push<Tok>(borrow_mut(v), mint(n))\n  match r { Ok(i) { return 0u32 } Err(back) { let z u64 = eat(move(back))\n    return 200u32 } }\n}\n'
            'func peek_at(v Borrow<seq.Seq<Tok>>, i u32) u64 !{memory.read} {\n  let e = seq.get<Tok>(v, i)\n  return val(e)\n}\n'
            'func exercise(v BorrowMut<seq.Seq<Tok>>) u32 !{memory.read,memory.write} {\n'
            '  var i u64 = 0u64\n  for i < 300u64 {\n    let c u32 = put(v, i * 3u64)\n    if c != 0u32 { return c }\n    i = i + 1u64\n  }\n'
            '  if seq.len<Tok>(borrow(v)) != 300u32 { return 1u32 }\n  if seq.capacity<Tok>(borrow(v)) != 512u32 { return 2u32 }\n'
            '  if peek_at(borrow(v), 299u32) != 897u64 { return 3u32 }\n  if peek_at(borrow(v), 0u32) != 0u64 { return 4u32 }\n'
            '  let p = seq.pop<Tok>(v)\n  match p { Ok(x) { if eat(move(x)) != 897u64 { return 5u32 } } Err(e) { return 6u32 } }\n'
            '  if seq.len<Tok>(borrow(v)) != 299u32 { return 7u32 }\n  return 0u32\n}\n'
            'func main() u32 !{memory.read,memory.write} {\n  let c = seq.new<Tok>(0u32)\n'
            '  match c { Ok(s) {\n    let code u32 = exercise(borrow_mut(s))\n    let d u32 = seq.destroy<Tok>(move(s))\n'
            '    if code != 0u32 { return code }\n    if d != 299u32 { return 8u32 }\n    return 42u32\n  } Err(e) { return e } }\n}\n'))

    def test_elements_that_own_storage_are_mutated_through_a_borrow_and_released_exactly_once(self):
        # 1100 rounds of (sequence + 2 blobs): each round leaks at least one buffer if cleanup is wrong, and 1100 exceeds the 1024-slot buffer table
        self.both(self.source(TOK + BLOB +
            'func set_at(s BorrowMut<seq.Seq<Blob>>, i u32, v u32) u32 !{memory.read,memory.write} {\n  let b = seq.get_mut<Blob>(s, i)\n  return blob_set(b, v)\n}\n'
            'func get_at(s Borrow<seq.Seq<Blob>>, i u32) u32 !{memory.read} {\n  let b = seq.get<Blob>(s, i)\n  return blob_get(b)\n}\n'
            'func round(k u32) u32 !{memory.read,memory.write} {\n  let c = seq.new<Blob>(2u32)\n'
            '  match c { Ok(s) {\n    var n u32 = 0u32\n    for n < 2u32 {\n      let b = blob(4u32)\n'
            '      match b { Ok(x) {\n'
            '        let r = seq.push<Blob>(borrow_mut(s), move(x))\n'
            '        match r { Ok(i) { let st u32 = set_at(borrow_mut(s), i, k + n) } Err(back) { let z u32 = seq.Dispose.dispose<Blob>(move(back))\n          let d u32 = seq.destroy<Blob>(move(s))\n          return 90u32 } }\n'
            '      } Err(e) { let d u32 = seq.destroy<Blob>(move(s))\n        return 91u32 } }\n      n = n + 1u32\n    }\n'
            '    if get_at(borrow(s), 1u32) != k + 1u32 { let d u32 = seq.destroy<Blob>(move(s))\n      return 92u32 }\n'
            '    let freed u32 = seq.destroy<Blob>(move(s))\n    if freed != 2u32 { return 93u32 }\n    return 0u32\n  } Err(e) { return 94u32 } }\n}\n'
            'func main() u32 !{memory.read,memory.write} {\n  var k u32 = 0u32\n  for k < 1100u32 {\n    let c u32 = round(k)\n    if c != 0u32 { return c }\n    k = k + 1u32\n  }\n  return 42u32\n}\n'))

    def test_a_push_into_a_full_sequence_is_refused_and_the_element_comes_back(self):
        self.both(self.source(TOK +
            'func main() u32 !{memory.read,memory.write} {\n  let c = seq.new<Tok>(1u32)\n'
            '  match c { Ok(s) {\n    var code u32 = 0u32\n    let a = seq.push<Tok>(borrow_mut(s), mint(5u64))\n    match a { Ok(i) { } Err(back) { let z u64 = eat(move(back))\n      code = 1u32 } }\n'
            '    let b = seq.push<Tok>(borrow_mut(s), mint(9u64))\n    match b { Ok(i) { code = 2u32 } Err(back) { if eat(move(back)) != 9u64 { code = 3u32 } } }\n'
            '    let d u32 = seq.destroy<Tok>(move(s))\n    if d != 1u32 { code = 4u32 }\n    if code != 0u32 { return code }\n    return 42u32\n  } Err(e) { return e } }\n}\n'))

    def test_a_failing_allocation_leaves_everything_intact_and_the_budget_returns_when_the_buffers_are_released(self):
        # each maximal slot buffer accounts 13 bytes per cell (8 + occupancy + generation); the 16 MiB budget holds 9 of them, the 10th is refused with outcome 2
        self.both(self.source(TOK +
            'func exhaust(depth u32) u32 !{memory.read,memory.write} {\n  let a = slots.alloc<Tok>(131072u32)\n'
            '  match a { Ok(b) {\n    let r u32 = exhaust(depth + 1u32)\n    let z = slots.release(move(b))\n    match z { Ok(k) { return r } Err(back) { return 999u32 } }\n'
            '  } Err(code) { return code * 100u32 + depth } }\n}\n'
            'func exhaust_grow(depth u32) u32 !{memory.read,memory.write} {\n  let a = slots.alloc<Tok>(1u32)\n'
            '  match a { Ok(b) {\n    let g = slots.grow(borrow_mut(b), 131072u32)\n    match g {\n'
            '      Ok(n) { let r u32 = exhaust_grow(depth + 1u32)\n        let z = slots.release(move(b))\n        match z { Ok(k) { return r } Err(back) { return 999u32 } } }\n'
            '      Err(code) { let z = slots.release(move(b))\n        match z { Ok(k) { return code * 100u32 + depth } Err(back) { return 998u32 } } }\n'
            '    }\n  } Err(code) { return 997u32 } }\n}\n'
            'func main() u32 !{memory.read,memory.write} {\n  let r u32 = exhaust(0u32)\n  if r != 209u32 { return 1u32 }\n'
            '  let q u32 = exhaust_grow(0u32)\n  if q != 209u32 { return 3u32 }\n'
            '  let again = slots.alloc<Tok>(131072u32)\n  match again { Ok(b) {\n    let z = slots.release(move(b))\n    match z { Ok(k) { return 42u32 } Err(back) { return 2u32 } }\n  } Err(code) { return code } }\n}\n'))


class SlotPrimitiveTests(SeqCase):
    def test_cells_are_not_bytes_a_foreign_type_is_refused_and_release_refuses_while_occupied(self):
        self.both(self.source(TOK +
            'func main() u32 !{memory.read,memory.write} {\n  let a = slots.alloc<Tok>(2u32)\n'
            '  match a { Ok(b) {\n    var code u32 = 0u32\n'
            '    let r1 = buffer.read_u8(borrow(b), 0u32)\n    match r1 { Ok(v) { code = 21u32 } Err(e) { if e != 8u32 { code = 22u32 } } }\n'
            '    let r2 = buffer.read_u32le(borrow(b), 0u32)\n    match r2 { Ok(v) { code = 23u32 } Err(e) { if e != 8u32 { code = 24u32 } } }\n'
            '    let r3 = buffer.read_u64le(borrow(b), 0u32)\n    match r3 { Ok(v) { code = 25u32 } Err(e) { if e != 8u32 { code = 26u32 } } }\n'
            '    let w1 = buffer.write_u8(borrow_mut(b), 0u32, 1u32)\n    match w1 { Ok(v) { code = 27u32 } Err(e) { if e != 8u32 { code = 28u32 } } }\n'
            '    let w2 = buffer.write_u32le(borrow_mut(b), 0u32, 1u32)\n    match w2 { Ok(v) { code = 29u32 } Err(e) { if e != 8u32 { code = 30u32 } } }\n'
            '    let w3 = buffer.write_u64le(borrow_mut(b), 0u32, 1u64)\n    match w3 { Ok(v) { code = 31u32 } Err(e) { if e != 8u32 { code = 32u32 } } }\n'
            '    let z1 = buffer.zero(borrow_mut(b), 0u32, 1u32)\n    match z1 { Ok(v) { code = 33u32 } Err(e) { if e != 8u32 { code = 34u32 } } }\n'
            '    let g1 = buffer.grow(borrow_mut(b), 100u32)\n    match g1 { Ok(v) { code = 35u32 } Err(e) { if e != 8u32 { code = 36u32 } } }\n'
            '    if slots.state<Other>(borrow(b), 0u32) != 3u32 { code = 3u32 }\n    if slots.state<Tok>(borrow(b), 5u32) != 2u32 { code = 4u32 }\n'
            '    let p1 = slots.put<Tok>(borrow_mut(b), 0u32, mint(7u64))\n    match p1 { Ok(i) { } Err(back) { let z u64 = eat(move(back))\n      code = 5u32 } }\n'
            '    let p2 = slots.put<Tok>(borrow_mut(b), 0u32, mint(8u64))\n    match p2 { Ok(i) { code = 6u32 } Err(back) { if eat(move(back)) != 8u64 { code = 7u32 } } }\n'
            '    let wp = slots.put<Other>(borrow_mut(b), 1u32, mint_other(5u64))\n'
            '    match wp { Ok(i) { code = 12u32 } Err(back) { if eat_other(move(back)) != 5u64 { code = 13u32 } } }\n'
            '    let wt = slots.take<Other>(borrow_mut(b), 0u32)\n'
            '    match wt { Ok(x) { let z u64 = eat_other(move(x))\n      code = 14u32 } Err(e) { if e != 3u32 { code = 15u32 } } }\n'
            '    let rl = slots.release(move(b))\n'
            '    match rl {\n      Ok(z) { return 8u32 }\n      Err(back) {\n        let t = slots.take<Tok>(borrow_mut(back), 0u32)\n'
            '        match t { Ok(x) { if eat(move(x)) != 7u64 { code = 9u32 } } Err(e) { code = 10u32 } }\n'
            '        let again = slots.release(move(back))\n        match again { Ok(z) { } Err(b2) { code = 11u32 } }\n      }\n    }\n'
            '    let fz = slots.alloc<Tok>(1u32)\n'
            '    match fz { Ok(c) {\n      let f = buffer.freeze(move(c))\n      match f { Ok(bytes) { code = 40u32 } Err(e) { if e != 8u32 { code = 41u32 } } }\n    } Err(e) { code = 42u32 } }\n'
            '    if code != 0u32 { return code }\n    return 42u32\n  } Err(e) { return e } }\n}\n'))

    def test_freezing_and_releasing_empty_slot_buffers_never_leaks_a_buffer(self):
        # 1100 rounds exceed the 1024-slot buffer table, so a buffer that freeze or release forgot to free would make a later allocation fail
        self.both(self.source(TOK +
            'func main() u32 !{memory.read,memory.write} {\n  var k u32 = 0u32\n  for k < 1100u32 {\n'
            '    let a = slots.alloc<Tok>(1u32)\n'
            '    match a { Ok(b) {\n      let f = buffer.freeze(move(b))\n      match f { Ok(bytes) { return 1u32 } Err(e) { if e != 8u32 { return 2u32 } } }\n    } Err(e) { return 100u32 + e } }\n'
            '    let c = slots.alloc<Tok>(1u32)\n'
            '    match c { Ok(b) {\n      let z = slots.release(move(b))\n      match z { Ok(n) { } Err(back) { return 3u32 } }\n    } Err(e) { return 200u32 + e } }\n'
            '    k = k + 1u32\n  }\n  return 42u32\n}\n'))

    def test_freeing_a_buffer_that_still_owns_a_resource_is_a_fault_not_a_silent_loss(self):
        self.faults(self.source(TOK +
            'func main() u32 !{memory.read,memory.write} {\n  let a = slots.alloc<Tok>(1u32)\n'
            '  match a { Ok(b) {\n    let p = slots.put<Tok>(borrow_mut(b), 0u32, mint(1u64))\n    match p { Ok(i) { } Err(back) { let z u64 = eat(move(back)) } }\n'
            '    return 0u32\n  } Err(e) { return e } }\n}\n'), b'E_SLOT_OCCUPIED')

    def test_a_function_without_arguments_runs_while_a_slot_buffer_is_live(self):
        # the evaluator looked at the first argument of EVERY call to decide whether the callee was a byte operation on a slot buffer: a call with no argument
        # (here `zero()`) made it read past the end of the argument list as soon as a slot buffer was alive
        self.both(self.source(TOK + 'func zero() u32 { return 7u32 }\n'
            'func main() u32 !{memory.read,memory.write} {\n  let a = slots.alloc<Tok>(1u32)\n'
            '  match a { Ok(b) {\n    let z u32 = zero()\n    let r = slots.release(move(b))\n'
            '    match r { Ok(k) { if z == 7u32 { return 42u32 }\n      return 1u32 } Err(back) { return 2u32 } }\n  } Err(e) { return e } }\n}\n'))

    def test_lending_an_empty_cell_is_a_fault(self):
        self.faults(self.source(TOK +
            'func main() u32 !{memory.read,memory.write} {\n  let a = slots.alloc<Tok>(1u32)\n'
            '  match a { Ok(b) {\n    let v u64 = val(slots.borrow<Tok>(borrow(b), 0u32))\n    let z = slots.release(move(b))\n    match z { Ok(k) { return 0u32 } Err(back) { return 1u32 } }\n'
            '  } Err(e) { return e } }\n}\n'), b'E_SLOT_STATE')


class OwnedSlotLawTests(SeqCase):
    def test_ownership_authority_and_borrow_rules_still_hold_for_a_collection_of_resources(self):
        make = ('func main() u32 !{memory.read,memory.write} {\n  let c = seq.new<Tok>(2u32)\n  match c { Ok(s) {\n%s\n  } Err(e) { return e } }\n}\n')
        push = '    let r = seq.push<Tok>(borrow_mut(s), move(x))\n    match r { Ok(i) { } Err(back) { let z u64 = eat(move(back)) } }\n'
        destroy = '    let d u32 = seq.destroy<Tok>(move(s))\n    return d\n'
        cases = [
            ('an element is used after it was moved in', make % ('    let x = mint(1u64)\n' + push + '    let z u64 = eat(move(x))\n' + destroy), b'E_RESOURCE_MOVED'),
            ('an element taken out is left unconsumed', make % ('    let p = seq.pop<Tok>(borrow_mut(s))\n    match p { Ok(x) { } Err(e) { } }\n' + destroy), b'E_RESOURCE_UNCONSUMED'),
            ('the sequence is never destroyed', make % '    return 0u32', b'E_RESOURCE_UNCONSUMED'),
            ('the sequence is opened outside its module', make % '    let inner seq.Seq<Tok> = resource.unseal(move(s))\n    return 0u32', b'E_RESOURCE_PRIVATE'),
            ('growth while an element is lent', make % ('    let e = seq.get<Tok>(borrow(s), 0u32)\n    let g = seq.reserve<Tok>(borrow_mut(s))\n    let w u64 = val(e)\n' + destroy),
             b'E_BORROW_CONFLICT'),
            ('a plain value as an element', 'func main() u32 !{memory.write} {\n  let a = slots.alloc<u32>(1u32)\n  return 0u32\n}\n', b'E_GENERIC_CONSTRAINT'),
            ('a record that is not a resource handle as an element',
             'struct Pair { a u32, b u32 }\nfunc main() u32 !{memory.write} {\n  let a = slots.alloc<Pair>(1u32)\n  return 0u32\n}\n', b'E_RESOURCE_TYPE'),
            ('a slot is written through a shared borrow',
             'func main() u32 !{memory.write} {\n  let a = slots.alloc<Tok>(1u32)\n  match a { Ok(b) {\n    let p = slots.put<Tok>(borrow(b), 0u32, mint(1u64))\n    return 0u32\n  } Err(e) { return e } }\n}\n',
             b'E_TYPE'),
            # provenance of a projected borrow: it must stand on the region parameter and keep its owner from being moved, emptied or destroyed
            ('an element borrow is returned from a function with two borrowed parameters',
             'func pick(a Borrow<seq.Seq<Tok>>, b Borrow<seq.Seq<Tok>>) Borrow<Tok> !{memory.read} { return seq.get<Tok>(a, 0u32) }\nfunc main() u32 { return 0u32 }\n', b'E_BORROW_ESCAPE'),
            ('an element borrow of a local container is returned as if it came from the parameter',
             'func bad(v Borrow<Tok>) Borrow<Tok> !{memory.read,memory.write} {\n  let a = slots.alloc<Tok>(1u32)\n'
             '  match a { Ok(b) { return slots.borrow<Tok>(borrow(b), 0u32) } Err(e) { return v } }\n}\nfunc main() u32 { return 0u32 }\n', b'E_BORROW_ESCAPE'),
            ('an element borrow is returned through a call that is not the direct initializer of a let',
             'func peek_at(v Borrow<seq.Seq<Tok>>) u64 !{memory.read} { return val(seq.get<Tok>(v, 0u32)) }\nfunc main() u32 { return 0u32 }\n', b'E_BORROW_ESCAPE'),
            ('the owner is destroyed while an element is lent',
             make % ('    let e = seq.get<Tok>(borrow(s), 0u32)\n    let d u32 = seq.destroy<Tok>(move(s))\n    let w u64 = val(e)\n    return d\n'), b'E_BORROW_CONFLICT'),
            ('an element is extracted while another is lent',
             make % ('    let e = seq.get<Tok>(borrow(s), 0u32)\n    let p = seq.pop<Tok>(borrow_mut(s))\n    match p { Ok(x) { let z u64 = eat(move(x)) } Err(c) { } }\n    let w u64 = val(e)\n' + destroy),
             b'E_BORROW_CONFLICT'),
            ('a mutable element borrow is projected from a shared one',
             'func up(v Borrow<seq.Seq<Tok>>) BorrowMut<Tok> !{memory.read} { return seq.get_mut<Tok>(v, 0u32) }\nfunc main() u32 { return 0u32 }\n', b'E_BORROW_ESCAPE'),
            ('a sequence of one resource type is lent where another is expected',
             BLOB + 'func wants(v Borrow<seq.Seq<Blob>>) u32 !{memory.read} { return seq.len<Blob>(v) }\n'
             'func main() u32 !{memory.read,memory.write} {\n  let c = seq.new<Tok>(1u32)\n  match c { Ok(s) {\n    let n u32 = wants(borrow(s))\n    let d u32 = seq.destroy<Tok>(move(s))\n    return d\n'
             '  } Err(e) { return e } }\n}\n', b'E_TYPE'),
        ]
        for label, program, code in cases:
            with self.subTest(label):
                self.rejected(TOK + program, code)


class RepresentationTests(SeqCase):
    """The new calls are new semantics: they share the Wave21/OMC21 fence, an older label over them is E_VERSION, the current reader accepts what the writer
    produced and runs it, and a Wave that names another resource type is refused by the checker (the identity is the key, not a label)."""
    PRELUDE = ('struct Tok { h u64 }\nstruct Other { h u64 }\nfunc mint(n u64) Resource<Tok> { return resource.seal(Tok { h: n }) }\n'
               'func eat(f Resource<Tok>) u64 { let r Tok = resource.unseal(move(f))\n  return r.h }\n')
    PROGRAM = (PRELUDE + 'func main() u32 !{memory.read,memory.write} {\n  let a = slots.alloc<Tok>(2u32)\n  match a { Ok(b) {\n'
               '    let p = slots.put<Tok>(borrow_mut(b), 0u32, mint(42u64))\n    match p { Ok(i) { } Err(back) { let z u64 = eat(move(back)) } }\n'
               '    var out u32 = 1u32\n    let t = slots.take<Tok>(borrow_mut(b), 0u32)\n    match t { Ok(x) { if eat(move(x)) == 42u64 { out = 42u32 } } Err(e) { out = e } }\n'
               '    let z = slots.release(move(b))\n    match z { Ok(k) { return out } Err(back) { return 99u32 } }\n  } Err(e) { return e } }\n}\n')

    def program(self):
        # a module of its own, without imports: a program that uses generics or traits is written as Wave22 (authoring capsule), which is a different fence
        path = self.dir / 'slots.omni'
        path.write_text('module t\n' + self.PROGRAM, encoding='utf-8')
        return path

    def test_slot_programs_are_wave21_and_omc21_and_the_current_reader_runs_them(self):
        path = self.program()
        wave = proc(OMNI, 'wave', path)
        self.assertEqual(wave.returncode, 0, wave.stderr)
        self.assertTrue(wave.stdout.startswith(b'(omni-wave 21'), wave.stdout[:20])
        wire = self.dir / 'slots.owire'
        self.assertEqual(proc(OMNI, 'pack', path, '-o', wire).returncode, 0)
        self.assertEqual(wire.read_bytes()[:8], b'OMCX\x15\x00\x00\x00')
        owave = self.dir / 'slots.owave'
        owave.write_bytes(wave.stdout)
        self.assertEqual(proc(OMNI, 'check', owave).returncode, 0)
        self.assertEqual(proc(OMNI, 'check', wire).returncode, 0)
        for artifact in (owave, wire):
            self.assertEqual(proc(OMNI, 'eval', artifact, timeout=180).returncode, 42, artifact.name)

    def test_relabelling_a_slot_program_as_an_older_version_is_rejected_with_e_version(self):
        path = self.program()
        wave = proc(OMNI, 'wave', path).stdout
        wire = self.dir / 'slots.owire'
        self.assertEqual(proc(OMNI, 'pack', path, '-o', wire).returncode, 0)
        for old in (18, 19, 20):
            relabelled = self.dir / f'as-wave{old}.owave'
            relabelled.write_bytes(wave.replace(b'(omni-wave 21', f'(omni-wave {old}'.encode(), 1))
            result = proc(OMNI, 'check', relabelled)
            self.assertEqual(result.returncode, 2, (old, result.stderr))
            self.assertIn(b'E_VERSION', result.stderr)
            raw = bytearray(wire.read_bytes())
            raw[4] = old
            older = self.dir / f'as-omc{old}.owire'
            older.write_bytes(bytes(raw))
            result = proc(OMNI, 'check', older)
            self.assertEqual(result.returncode, 2, (old, result.stderr))
            self.assertIn(b'E_VERSION', result.stderr)

    def test_a_wave_that_names_another_resource_type_is_refused(self):
        wave = proc(OMNI, 'wave', self.program()).stdout
        self.assertIn(b'slots.put<t.Tok>', wave)
        forged = self.dir / 'forged.owave'
        forged.write_bytes(wave.replace(b'slots.put<t.Tok>', b'slots.put<t.Other>'))
        result = proc(OMNI, 'check', forged)
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn(b'E_TYPE', result.stderr)


if __name__ == '__main__':
    unittest.main()
