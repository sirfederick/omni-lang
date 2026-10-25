#!/usr/bin/env python3
"""CP-05 (spec/COLLECTIONS_PROTOCOLS_CANDIDATE.md, examples/storage/{alloc,vec,map,seq}.omni): the allocator contract of the program, hash and equality, Map and Set
written in Omni, and the iterator contracts (a keyed table, and a collection of resources).

Everything that runs Omni runs twice, in the evaluator and natively, and they must agree. The programs that must not compile are checked by `check` and `build`.
"""
from __future__ import annotations
import shutil
import unittest
from cp02_borrowed_containers import ContainerCase
from cp03_cleanup_failure import CleanupCase, audit_lines, classify
from language_0_8_3_alpha8 import ROOT, OMNI, proc

STORAGE = ROOT / 'examples' / 'storage'
HEAP = 'alloc.Heap'

# Allocators written in the PROGRAM: they replace alloc.Heap by naming another type. `Deny` refuses everything; `Tiny` refuses any buffer above 256 bytes;
# `Roomy` gives 16 bytes more than asked and its release answers 77, so that a container is seen to go through it.
ALLOCATORS = (
    'struct Deny { tag u32 }\n'
    'impl alloc.Allocator for Deny {\n'
    '  func allocate(bytes u32) Result<Resource<Buffer>,u32> !{memory.write} { return Err<Resource<Buffer>,u32>(3u32) }\n'
    '  func resize(b BorrowMut<Buffer>, bytes u32) Result<u32,u32> !{memory.write} { return Err<u32,u32>(3u32) }\n'
    '  func release(b Resource<Buffer>) u32 !{memory.write} { return buffer.release(move(b)) }\n}\n'
    'struct Tiny { tag u32 }\n'
    'impl alloc.Allocator for Tiny {\n'
    '  func allocate(bytes u32) Result<Resource<Buffer>,u32> !{memory.write} {\n    if bytes > 256u32 { return Err<Resource<Buffer>,u32>(1u32) }\n    return buffer.alloc(bytes)\n  }\n'
    '  func resize(b BorrowMut<Buffer>, bytes u32) Result<u32,u32> !{memory.write} {\n    if bytes > 256u32 { return Err<u32,u32>(1u32) }\n    return buffer.grow(b, bytes)\n  }\n'
    '  func release(b Resource<Buffer>) u32 !{memory.write} { return buffer.release(move(b)) }\n}\n'
    'struct Roomy { tag u32 }\n'
    'impl alloc.Allocator for Roomy {\n'
    '  func allocate(bytes u32) Result<Resource<Buffer>,u32> !{memory.write} { return buffer.alloc(bytes + 16u32) }\n'
    '  func resize(b BorrowMut<Buffer>, bytes u32) Result<u32,u32> !{memory.write} { return buffer.grow(b, bytes + 16u32) }\n'
    '  func release(b Resource<Buffer>) u32 !{memory.write} {\n    let z u32 = buffer.release(move(b))\n    return 77u32\n  }\n}\n')


class CollCase(CleanupCase):
    def setUp(self):
        super().setUp()
        shutil.copy(STORAGE / 'map.omni', self.dir / 'map.omni')

    def source(self, text, name='program.omni'):
        return super().source('import map "map.omni"\n' + text, name)

    def run_ok(self, text, env=None, name='program.omni', expected=42):
        path = self.source(text, name)
        ev, nat = self.run_both(path, env)
        self.assertEqual((ev[0], nat[0]), (expected, expected), (ev[1], nat[1]))
        return ev, nat


class QualifiedBoundTests(CollCase):
    """A bound can name a pub trait of an imported module; a private one, an alias that is not an import and a type without the impl are refused."""
    LIB = ('module lib\npub trait Open { func code() u32 !pure }\ntrait Closed { func code() u32 !pure }\nimpl Open for u32 { func code() u32 { return 7u32 } }\n')
    LIB2 = ('module lib2\nimport lib "lib.omni"\npub func ask<T: lib.Open>(x T) u32 { return lib.Open.code<T>() + 1u32 }\n'
            'pub struct Holder<T: lib.Open> { v u32 }\npub func make<T: lib.Open>() Holder<T> { return Holder<T> { v: lib.Open.code<T>() } }\n'
            'pub enum Pick<T: lib.Open> { Just(T), Nothing }\n'
            'pub func none<T: lib.Open>() u32 {\n  let k Pick<T> = Pick.Nothing<T>()\n  match k { Just(v) { return 1u32 } Nothing { return 42u32 } }\n}\n')

    def lib(self, extra=''):
        (self.dir / 'lib.omni').write_text(self.LIB, encoding='utf-8')
        (self.dir / 'lib2.omni').write_text(self.LIB2 + extra, encoding='utf-8')

    def test_a_library_bounds_a_parameter_on_a_trait_of_another_module(self):
        self.lib()
        self.run_ok('import lib "lib.omni"\nimport lib2 "lib2.omni"\nfunc main() u32 {\n  let h lib2.Holder<u32> = lib2.make<u32>()\n'
                    '  if h.v != 7u32 { return 1u32 }\n  if lib2.ask<u32>(5u32) != 8u32 { return 2u32 }\n  if lib2.none<u32>() != 42u32 { return 3u32 }\n  return 42u32\n}\n')

    def test_what_is_refused(self):
        cases = [
            ('a type with no impl of the trait', '', 'func main() u32 { return lib2.ask<u64>(5u64) }\n', b'E_GENERIC_CONSTRAINT'),
            ('a private trait of another module as a bound', 'pub func hid<T: lib.Closed>(x T) u32 { return 0u32 }\n', 'func main() u32 { return 0u32 }\n', b'E_VISIBILITY'),
            ('an alias that is not an import', 'pub func lost<T: nope.Open>(x T) u32 { return 0u32 }\n', 'func main() u32 { return 0u32 }\n', b'E_GENERIC_CONSTRAINT'),
            ('a trait the module does not have', 'pub func gone<T: lib.Missing>(x T) u32 { return 0u32 }\n', 'func main() u32 { return 0u32 }\n', b'E_GENERIC_CONSTRAINT'),
        ]
        for label, extra, body, code in cases:
            with self.subTest(label):
                self.lib(extra)
                self.rejected('import lib "lib.omni"\nimport lib2 "lib2.omni"\n' + body, code)


class AllocatorTests(CollCase):
    def test_the_program_substitutes_the_allocator_by_naming_another_type(self):
        # the same code with Heap and with Tiny: a vector grows without bound with the first and is refused (typed) by the second once its buffer would pass 256 bytes
        def program(alloc_type, want_ok):
            return (ALLOCATORS +
                'func fill(v BorrowMut<vec.Vec<u32,%s>>, n u32) u32 !{memory.read,memory.write} {\n  var i u32 = 0u32\n'
                '  for i < n {\n    let r = vec.push<u32,%s>(v, i)\n    match r { Ok(k) { } Err(e) { return e } }\n    i = i + 1u32\n  }\n  return 0u32\n}\n'
                'func main() u32 !{memory.read,memory.write} {\n  let c = vec.new<u32,%s>(0u32)\n  match c { Ok(v) {\n'
                '    let code u32 = fill(borrow_mut(v), 100u32)\n    let n u32 = vec.len<u32,%s>(borrow(v))\n'
                '    var out u32 = 42u32\n    if code != %du32 { out = 1u32 }\n    if n != %du32 { out = 2u32 }\n'
                '    let d u32 = vec.destroy<u32,%s>(move(v))\n    return out\n  } Err(e) { return e } }\n}\n'
                % (alloc_type, alloc_type, alloc_type, alloc_type, 0 if want_ok else 1, 100 if want_ok else 32, alloc_type))
        self.run_ok(program('alloc.Heap', True), name='heap.omni')
        # Tiny: 8 header bytes + 4 per element, doubling 4, 8, 16, 32, then 64 elements would need 264 bytes: the 33rd push is Err(1) and the vector keeps its 32 elements
        self.run_ok(program('Tiny', False), name='tiny.omni')

    def test_a_refusing_allocator_gives_a_typed_failure_to_every_collection(self):
        self.run_ok(ALLOCATORS +
            'func main() u32 !{memory.read,memory.write} {\n  var code u32 = 0u32\n'
            '  let v = vec.new<u32,Deny>(4u32)\n  match v { Ok(x) { let d u32 = vec.destroy<u32,Deny>(move(x))\n    code = 1u32 } Err(e) { if e != 3u32 { code = 2u32 } } }\n'
            '  let m = map.new<u32,u64,Deny>(4u32)\n  match m { Ok(x) { let d u32 = map.destroy<u32,u64,Deny>(move(x))\n    code = 3u32 } Err(e) { if e != 3u32 { code = 4u32 } } }\n'
            '  let s = map.set_new<u32,Deny>(4u32)\n  match s { Ok(x) { let d u32 = map.set_destroy<u32,Deny>(move(x))\n    code = 5u32 } Err(e) { if e != 3u32 { code = 6u32 } } }\n'
            '  if code != 0u32 { return code }\n  return 42u32\n}\n')

    def test_a_container_goes_through_its_allocator_for_allocation_growth_and_release(self):
        # Roomy gives 16 bytes more on allocate and on resize and answers 77 on release: the capacity shows the first two, the result of destroy the third
        self.run_ok(ALLOCATORS +
            'func main() u32 !{memory.read,memory.write} {\n  let c = vec.new<u32,Roomy>(2u32)\n  match c { Ok(v) {\n    var code u32 = 0u32\n'
            '    if vec.capacity<u32,Roomy>(borrow(v)) != 6u32 { code = 1u32 }\n'
            '    var i u32 = 0u32\n    for i < 7u32 {\n      let r = vec.push<u32,Roomy>(borrow_mut(v), i)\n      match r { Ok(k) { } Err(e) { code = 2u32 } }\n      i = i + 1u32\n    }\n'
            # 7 elements overflow the 6 of the first buffer: want = 12, 8 + 48 = 56 bytes, Roomy grows to 72: (72 - 8) / 4 = 16
            '    if vec.capacity<u32,Roomy>(borrow(v)) != 16u32 { code = 3u32 }\n'
            '    let d u32 = vec.destroy<u32,Roomy>(move(v))\n    if d != 77u32 { code = 4u32 }\n'
            '    let m = map.new<u32,u64,Roomy>(2u32)\n    match m { Ok(x) { let dm u32 = map.destroy<u32,u64,Roomy>(move(x))\n      if dm != 77u32 { code = 5u32 } } Err(e) { code = 6u32 } }\n'
            '    let s = map.set_new<u32,Roomy>(2u32)\n    match s { Ok(x) { let ds u32 = map.set_destroy<u32,Roomy>(move(x))\n      if ds != 77u32 { code = 7u32 } } Err(e) { code = 8u32 } }\n'
            '    if code != 0u32 { return code }\n    return 42u32\n  } Err(e) { return e } }\n}\n')

    def test_a_type_that_is_not_an_allocator_is_refused(self):
        self.rejected('struct Plain { tag u32 }\nfunc main() u32 !{memory.read,memory.write} {\n  let c = vec.new<u32,Plain>(2u32)\n  return 0u32\n}\n', b'E_GENERIC_CONSTRAINT')

    def test_a_table_that_cannot_grow_keeps_every_entry_and_reuses_the_room_of_removed_ones(self):
        # Tiny allows 18 slots of 13 bytes; the table doubles 4, 8, 16, then the growth to 32 is refused: it fills its 16 slots, the 17th insert is Err(1) and nothing is lost
        self.run_ok(ALLOCATORS +
            'func main() u32 !{memory.read,memory.write} {\n  let c = map.new<u32,u64,Tiny>(0u32)\n  match c { Ok(m) {\n    var code u32 = 0u32\n    var stopped u32 = 0u32\n    var i u32 = 0u32\n'
            '    for i < 40u32 {\n      if stopped == 0u32 {\n        let r = map.insert<u32,u64,Tiny>(borrow_mut(m), i, u64(i) + 1000u64)\n'
            '        match r { Ok(k) { } Err(e) { stopped = i + 1u32\n          if e != 1u32 { code = 1u32 } } }\n      }\n      i = i + 1u32\n    }\n'
            '    if stopped != 17u32 { code = 2u32 }\n    if map.len<u32,u64,Tiny>(borrow(m)) != 16u32 { code = 3u32 }\n'
            '    i = 0u32\n    for i < 16u32 {\n      let g = map.get<u32,u64,Tiny>(borrow(m), i)\n      match g { Ok(v) { if v != u64(i) + 1000u64 { code = 4u32 } } Err(e) { code = 5u32 } }\n      i = i + 1u32\n    }\n'
            # removing four entries leaves tombstones: the table drops them in place and takes four new keys although it can no longer grow
            '    i = 0u32\n    for i < 4u32 {\n      let r = map.remove<u32,u64,Tiny>(borrow_mut(m), i)\n      match r { Ok(v) { } Err(e) { code = 6u32 } }\n      i = i + 1u32\n    }\n'
            '    i = 100u32\n    for i < 104u32 {\n      let r = map.insert<u32,u64,Tiny>(borrow_mut(m), i, u64(i))\n      match r { Ok(k) { if k != 1u32 { code = 7u32 } } Err(e) { code = 8u32 } }\n      i = i + 1u32\n    }\n'
            '    if map.len<u32,u64,Tiny>(borrow(m)) != 16u32 { code = 9u32 }\n'
            '    let g = map.get<u32,u64,Tiny>(borrow(m), 15u32)\n    match g { Ok(v) { if v != 1015u64 { code = 10u32 } } Err(e) { code = 11u32 } }\n'
            '    let g2 = map.get<u32,u64,Tiny>(borrow(m), 102u32)\n    match g2 { Ok(v) { if v != 102u64 { code = 12u32 } } Err(e) { code = 13u32 } }\n'
            '    let d u32 = map.destroy<u32,u64,Tiny>(move(m))\n    if code != 0u32 { return code }\n    return 42u32\n  } Err(e) { return e } }\n}\n')


# a key type that decides identity itself: any two values with the same last decimal digit are the SAME key
MOD10 = ('struct Mod10 { v u32 }\n'
         'impl map.Key for Mod10 {\n'
         '  func size() u32 { return 4u32 }\n'
         '  func put(b BorrowMut<Buffer>, off u32, k Mod10) Result<u32,u32> !{memory.write} { return buffer.write_u32le(b, off, k.v) }\n'
         '  func get(b Borrow<Buffer>, off u32) Result<Mod10,u32> !{memory.read} {\n'
         '    let r = buffer.read_u32le(b, off)\n    match r { Ok(x) { return Ok<Mod10,u32>(Mod10 { v: x }) } Err(e) { return Err<Mod10,u32>(e) } }\n  }\n'
         '  func hash(k Mod10) u64 { return u64(k.v % 10u32) }\n'
         '  func same(a Mod10, b Mod10) bool { return a.v % 10u32 == b.v % 10u32 }\n}\n')


class MapTests(CollCase):
    def test_insert_get_replace_remove_and_growth(self):
        self.run_ok(
            'func main() u32 !{memory.read,memory.write} {\n  let c = map.new<u32,u64,alloc.Heap>(0u32)\n  match c { Ok(m) {\n    var code u32 = 0u32\n    var i u32 = 0u32\n'
            '    for i < 200u32 {\n      let r = map.insert<u32,u64,alloc.Heap>(borrow_mut(m), i, u64(i) * 10u64)\n      match r { Ok(k) { if k != 1u32 { code = 1u32 } } Err(e) { code = 100u32 + e } }\n      i = i + 1u32\n    }\n'
            '    if map.len<u32,u64,alloc.Heap>(borrow(m)) != 200u32 { code = 2u32 }\n'
            '    if map.capacity<u32,u64,alloc.Heap>(borrow(m)) != 512u32 { code = 3u32 }\n'
            '    i = 0u32\n    for i < 200u32 {\n      let g = map.get<u32,u64,alloc.Heap>(borrow(m), i)\n      match g { Ok(v) { if v != u64(i) * 10u64 { code = 4u32 } } Err(e) { code = 5u32 } }\n      i = i + 1u32\n    }\n'
            # a key that is there is replaced: Ok(0), the count does not move
            '    let rp = map.insert<u32,u64,alloc.Heap>(borrow_mut(m), 17u32, 999u64)\n    match rp { Ok(k) { if k != 0u32 { code = 6u32 } } Err(e) { code = 7u32 } }\n'
            '    if map.len<u32,u64,alloc.Heap>(borrow(m)) != 200u32 { code = 8u32 }\n'
            '    let g17 = map.get<u32,u64,alloc.Heap>(borrow(m), 17u32)\n    match g17 { Ok(v) { if v != 999u64 { code = 9u32 } } Err(e) { code = 10u32 } }\n'
            # an absent key is Err(13); a removed one is gone and gives its value back
            '    let gx = map.get<u32,u64,alloc.Heap>(borrow(m), 5000u32)\n    match gx { Ok(v) { code = 11u32 } Err(e) { if e != 13u32 { code = 12u32 } } }\n'
            '    if map.contains<u32,u64,alloc.Heap>(borrow(m), 5000u32) { code = 13u32 }\n    if !map.contains<u32,u64,alloc.Heap>(borrow(m), 42u32) { code = 14u32 }\n'
            '    i = 0u32\n    for i < 200u32 {\n      let rm = map.remove<u32,u64,alloc.Heap>(borrow_mut(m), i)\n'
            '      match rm { Ok(v) { if i != 17u32 { if v != u64(i) * 10u64 { code = 15u32 } } } Err(e) { code = 16u32 } }\n      i = i + 2u32\n    }\n'
            '    if map.len<u32,u64,alloc.Heap>(borrow(m)) != 100u32 { code = 17u32 }\n'
            '    if map.contains<u32,u64,alloc.Heap>(borrow(m), 4u32) { code = 18u32 }\n    if !map.contains<u32,u64,alloc.Heap>(borrow(m), 5u32) { code = 19u32 }\n'
            '    let again = map.remove<u32,u64,alloc.Heap>(borrow_mut(m), 4u32)\n    match again { Ok(v) { code = 20u32 } Err(e) { if e != 13u32 { code = 21u32 } } }\n'
            # a removed key can come back, and the tombstones do not break the keys that probed past them
            '    let back = map.insert<u32,u64,alloc.Heap>(borrow_mut(m), 4u32, 44u64)\n    match back { Ok(k) { if k != 1u32 { code = 22u32 } } Err(e) { code = 23u32 } }\n'
            '    i = 1u32\n    for i < 200u32 {\n      let g = map.get<u32,u64,alloc.Heap>(borrow(m), i)\n      match g { Ok(v) { } Err(e) { code = 24u32 } }\n      i = i + 2u32\n    }\n'
            '    let d u32 = map.destroy<u32,u64,alloc.Heap>(move(m))\n    if code != 0u32 { return code }\n    return 42u32\n  } Err(e) { return e } }\n}\n')

    def test_a_removed_key_leaves_a_slot_that_the_next_insert_of_that_key_takes_again(self):
        # the slot of an entry is the cursor position before the one it returns: insert, remove, insert again must put the key in the SAME slot (the tombstone is reused)
        self.run_ok(
            'func slot_of(m Borrow<map.Map<u32,u32,alloc.Heap>>) u32 !{memory.read} {\n'
            '  let n = map.next<u32,u32,alloc.Heap>(m, map.cursor<u32,u32,alloc.Heap>(m))\n'
            '  match n { Ok(e) { return e.next.slot - 1u32 } Err(code) { return 4000000000u32 } }\n}\n'
            'func main() u32 !{memory.read,memory.write} {\n  let c = map.new<u32,u32,alloc.Heap>(8u32)\n  match c { Ok(m) {\n    var code u32 = 0u32\n'
            '    let a = map.insert<u32,u32,alloc.Heap>(borrow_mut(m), 5u32, 1u32)\n    match a { Ok(k) { } Err(e) { code = 1u32 } }\n'
            '    let first u32 = slot_of(borrow(m))\n'
            '    let r = map.remove<u32,u32,alloc.Heap>(borrow_mut(m), 5u32)\n    match r { Ok(v) { } Err(e) { code = 2u32 } }\n'
            '    let b = map.insert<u32,u32,alloc.Heap>(borrow_mut(m), 5u32, 2u32)\n    match b { Ok(k) { } Err(e) { code = 3u32 } }\n'
            '    if slot_of(borrow(m)) != first { code = 4u32 }\n'
            '    let d u32 = map.destroy<u32,u32,alloc.Heap>(move(m))\n    if code != 0u32 { return code }\n    return 42u32\n  } Err(e) { return e } }\n}\n')

    def test_inserting_and_removing_without_end_does_not_grow_the_table(self):
        # 100 distinct keys (the evaluator has a step budget), each inserted and removed: the tombstones pile up and are compacted in place, the table stays at 4 slots with nothing live
        self.run_ok(
            'func main() u32 !{memory.read,memory.write} {\n  let c = map.new<u32,u64,alloc.Heap>(4u32)\n  match c { Ok(m) {\n    var code u32 = 0u32\n    var i u32 = 0u32\n'
            '    for i < 100u32 {\n      let a = map.insert<u32,u64,alloc.Heap>(borrow_mut(m), i, u64(i))\n      match a { Ok(k) { if k != 1u32 { code = 1u32 } } Err(e) { code = 100u32 + e } }\n'
            '      let r = map.remove<u32,u64,alloc.Heap>(borrow_mut(m), i)\n      match r { Ok(v) { if v != u64(i) { code = 2u32 } } Err(e) { code = 3u32 } }\n      i = i + 1u32\n    }\n'
            '    if map.len<u32,u64,alloc.Heap>(borrow(m)) != 0u32 { code = 4u32 }\n    if map.capacity<u32,u64,alloc.Heap>(borrow(m)) != 4u32 { code = 5u32 }\n'
            '    let d u32 = map.destroy<u32,u64,alloc.Heap>(move(m))\n    if code != 0u32 { return code }\n    return 42u32\n  } Err(e) { return e } }\n}\n')

    def test_64_bit_keys_are_kept_apart_even_when_they_share_their_low_bits(self):
        self.run_ok(
            'func main() u32 !{memory.read,memory.write} {\n  let c = map.new<u64,u32,alloc.Heap>(4u32)\n  match c { Ok(m) {\n    var code u32 = 0u32\n    var i u64 = 0u64\n'
            '    for i < 50u64 {\n      let r = map.insert<u64,u32,alloc.Heap>(borrow_mut(m), i * 4294967296u64 + 7u64, 1u32 + u32(i))\n      match r { Ok(k) { if k != 1u32 { code = 1u32 } } Err(e) { code = 2u32 } }\n      i = i + 1u64\n    }\n'
            '    if map.len<u64,u32,alloc.Heap>(borrow(m)) != 50u32 { code = 3u32 }\n'
            '    i = 0u64\n    for i < 50u64 {\n      let g = map.get<u64,u32,alloc.Heap>(borrow(m), i * 4294967296u64 + 7u64)\n      match g { Ok(v) { if v != 1u32 + u32(i) { code = 4u32 } } Err(e) { code = 5u32 } }\n      i = i + 1u64\n    }\n'
            '    if map.contains<u64,u32,alloc.Heap>(borrow(m), 7u64 + 1u64) { code = 6u32 }\n'
            '    let d u32 = map.destroy<u64,u32,alloc.Heap>(move(m))\n    if code != 0u32 { return code }\n    return 42u32\n  } Err(e) { return e } }\n}\n')

    def test_the_program_decides_what_the_same_key_is(self):
        # Mod10 hashes and compares by the last decimal digit: 3, 13 and 23 are one key, 4 is another
        self.run_ok(MOD10 +
            'func main() u32 !{memory.read,memory.write} {\n  let c = map.new<Mod10,u32,alloc.Heap>(0u32)\n  match c { Ok(m) {\n    var code u32 = 0u32\n'
            '    let a = map.insert<Mod10,u32,alloc.Heap>(borrow_mut(m), Mod10 { v: 3u32 }, 1u32)\n    match a { Ok(k) { if k != 1u32 { code = 1u32 } } Err(e) { code = 2u32 } }\n'
            '    let b = map.insert<Mod10,u32,alloc.Heap>(borrow_mut(m), Mod10 { v: 13u32 }, 2u32)\n    match b { Ok(k) { if k != 0u32 { code = 3u32 } } Err(e) { code = 4u32 } }\n'
            '    let d4 = map.insert<Mod10,u32,alloc.Heap>(borrow_mut(m), Mod10 { v: 4u32 }, 9u32)\n    match d4 { Ok(k) { if k != 1u32 { code = 5u32 } } Err(e) { code = 6u32 } }\n'
            '    if map.len<Mod10,u32,alloc.Heap>(borrow(m)) != 2u32 { code = 7u32 }\n'
            '    let g = map.get<Mod10,u32,alloc.Heap>(borrow(m), Mod10 { v: 23u32 })\n    match g { Ok(v) { if v != 2u32 { code = 8u32 } } Err(e) { code = 9u32 } }\n'
            '    let r = map.remove<Mod10,u32,alloc.Heap>(borrow_mut(m), Mod10 { v: 93u32 })\n    match r { Ok(v) { if v != 2u32 { code = 10u32 } } Err(e) { code = 11u32 } }\n'
            '    if map.contains<Mod10,u32,alloc.Heap>(borrow(m), Mod10 { v: 3u32 }) { code = 12u32 }\n'
            '    let d u32 = map.destroy<Mod10,u32,alloc.Heap>(move(m))\n    if code != 0u32 { return code }\n    return 42u32\n  } Err(e) { return e } }\n}\n')

    def test_a_cursor_visits_every_live_entry_once_and_refuses_a_table_that_changed(self):
        self.run_ok(
            'func main() u32 !{memory.read,memory.write} {\n  let c = map.new<u32,u64,alloc.Heap>(0u32)\n  match c { Ok(m) {\n    var code u32 = 0u32\n    var i u32 = 1u32\n'
            '    for i <= 30u32 {\n      let r = map.insert<u32,u64,alloc.Heap>(borrow_mut(m), i, u64(i) * 100u64)\n      match r { Ok(k) { } Err(e) { code = 1u32 } }\n      i = i + 1u32\n    }\n'
            '    i = 1u32\n    for i <= 30u32 {\n      let r = map.remove<u32,u64,alloc.Heap>(borrow_mut(m), i)\n      match r { Ok(v) { } Err(e) { code = 2u32 } }\n      i = i + 3u32\n    }\n'
            # 10 keys were removed (1, 4, ..., 28): 20 remain; their keys add up to 465 - 145 = 320
            '    var cur map.Cursor = map.cursor<u32,u64,alloc.Heap>(borrow(m))\n    var seen u32 = 0u32\n    var keys u64 = 0u64\n    var vals u64 = 0u64\n    var more u32 = 1u32\n'
            '    for more == 1u32 {\n      let n = map.next<u32,u64,alloc.Heap>(borrow(m), cur)\n'
            '      match n { Ok(e) { seen = seen + 1u32\n        keys = keys + u64(e.key)\n        vals = vals + e.value\n        cur = e.next }\n'
            '        Err(code2) { more = 0u32\n          if code2 != 14u32 { code = 3u32 } } }\n    }\n'
            '    if seen != 20u32 { code = 4u32 }\n    if keys != 320u64 { code = 5u32 }\n    if vals != 32000u64 { code = 6u32 }\n'
            # the exhausted cursor stays exhausted; a table that changed makes the cursor stale
            '    let again = map.next<u32,u64,alloc.Heap>(borrow(m), cur)\n    match again { Ok(e) { code = 7u32 } Err(code2) { if code2 != 14u32 { code = 8u32 } } }\n'
            '    let fresh map.Cursor = map.cursor<u32,u64,alloc.Heap>(borrow(m))\n'
            '    let ins = map.insert<u32,u64,alloc.Heap>(borrow_mut(m), 500u32, 1u64)\n    match ins { Ok(k) { } Err(e) { code = 9u32 } }\n'
            '    let stale = map.next<u32,u64,alloc.Heap>(borrow(m), fresh)\n    match stale { Ok(e) { code = 10u32 } Err(code2) { if code2 != 15u32 { code = 11u32 } } }\n'
            # replacing a value is not a change of the table
            '    let fresh2 map.Cursor = map.cursor<u32,u64,alloc.Heap>(borrow(m))\n'
            '    let rep = map.insert<u32,u64,alloc.Heap>(borrow_mut(m), 500u32, 2u64)\n    match rep { Ok(k) { } Err(e) { code = 12u32 } }\n'
            '    let still = map.next<u32,u64,alloc.Heap>(borrow(m), fresh2)\n    match still { Ok(e) { } Err(code2) { code = 13u32 } }\n'
            # a removal is a change too
            '    let fresh3 map.Cursor = map.cursor<u32,u64,alloc.Heap>(borrow(m))\n'
            '    let rmv = map.remove<u32,u64,alloc.Heap>(borrow_mut(m), 500u32)\n    match rmv { Ok(v) { } Err(e) { code = 14u32 } }\n'
            '    let gone = map.next<u32,u64,alloc.Heap>(borrow(m), fresh3)\n    match gone { Ok(e) { code = 15u32 } Err(code2) { if code2 != 15u32 { code = 16u32 } } }\n'
            '    let d u32 = map.destroy<u32,u64,alloc.Heap>(move(m))\n    if code != 0u32 { return code }\n    return 42u32\n  } Err(e) { return e } }\n}\n')

    def test_a_set_keeps_each_key_once(self):
        self.run_ok(
            'func main() u32 !{memory.read,memory.write} {\n  let c = map.set_new<u32,alloc.Heap>(0u32)\n  match c { Ok(s) {\n    var code u32 = 0u32\n    var i u32 = 0u32\n'
            '    for i < 60u32 {\n      let r = map.set_insert<u32,alloc.Heap>(borrow_mut(s), i % 40u32)\n      match r { Ok(k) { if i < 40u32 { if k != 1u32 { code = 1u32 } } else { if k != 0u32 { code = 2u32 } } } Err(e) { code = 3u32 } }\n      i = i + 1u32\n    }\n'
            '    if map.set_len<u32,alloc.Heap>(borrow(s)) != 40u32 { code = 4u32 }\n'
            '    if !map.set_contains<u32,alloc.Heap>(borrow(s), 39u32) { code = 5u32 }\n    if map.set_contains<u32,alloc.Heap>(borrow(s), 40u32) { code = 6u32 }\n'
            '    let rm = map.set_remove<u32,alloc.Heap>(borrow_mut(s), 7u32)\n    match rm { Ok(k) { if k != 1u32 { code = 12u32 } } Err(e) { code = 7u32 } }\n'
            '    let rm2 = map.set_remove<u32,alloc.Heap>(borrow_mut(s), 7u32)\n    match rm2 { Ok(k) { code = 8u32 } Err(e) { if e != 13u32 { code = 9u32 } } }\n'
            '    var cur map.Cursor = map.set_cursor<u32,alloc.Heap>(borrow(s))\n    var seen u32 = 0u32\n    var keys u64 = 0u64\n    var more u32 = 1u32\n'
            '    for more == 1u32 {\n      let n = map.set_next<u32,alloc.Heap>(borrow(s), cur)\n'
            '      match n { Ok(e) { seen = seen + 1u32\n        keys = keys + u64(e.key)\n        cur = e.next }\n        Err(code2) { more = 0u32 } }\n    }\n'
            '    if seen != 39u32 { code = 10u32 }\n    if keys != 780u64 - 7u64 { code = 11u32 }\n'
            '    let d u32 = map.set_destroy<u32,alloc.Heap>(move(s))\n    if code != 0u32 { return code }\n    return 42u32\n  } Err(e) { return e } }\n}\n')

    def test_what_must_not_compile(self):
        main_with = ('func main() u32 !{memory.read,memory.write} {\n  let c = map.new<u32,u64,alloc.Heap>(2u32)\n  match c { Ok(m) {\n%s\n  } Err(e) { return e } }\n}\n')
        destroy = '    let d u32 = map.destroy<u32,u64,alloc.Heap>(move(m))\n    return d\n'
        cases = [
            ('a table never destroyed', main_with % '    return 0u32', b'E_RESOURCE_UNCONSUMED'),
            ('a table used after it was destroyed', main_with % (destroy.replace('return d', '') + '    let n u32 = map.len<u32,u64,alloc.Heap>(borrow(m))\n    return n'), b'E_RESOURCE_MOVED'),
            ('a table destroyed twice', main_with % ('    let d u32 = map.destroy<u32,u64,alloc.Heap>(move(m))\n    let e2 u32 = map.destroy<u32,u64,alloc.Heap>(move(m))\n    return e2'), b'E_RESOURCE_MOVED'),
            ('a table opened from outside its module', main_with % '    let inner map.Map<u32,u64,alloc.Heap> = resource.unseal(move(m))\n    return 0u32', b'E_RESOURCE_PRIVATE'),
            ('a key type with no Key impl', 'struct Bare { v u32 }\nfunc main() u32 !{memory.read,memory.write} {\n  let c = map.new<Bare,u64,alloc.Heap>(2u32)\n  return 0u32\n}\n', b'E_GENERIC_CONSTRAINT'),
            ('a value type with no Codec impl', 'struct Bare { v u32 }\nfunc main() u32 !{memory.read,memory.write} {\n  let c = map.new<u32,Bare,alloc.Heap>(2u32)\n  return 0u32\n}\n', b'E_GENERIC_CONSTRAINT'),
            ('a growing insert while the table is only lent shared', main_with % ('    let r = map.insert<u32,u64,alloc.Heap>(borrow(m), 1u32, 2u64)\n' + destroy), b'E_TYPE'),
        ]
        for label, program, code in cases:
            with self.subTest(label):
                self.rejected(program, code)


class GrowthFailureTests(CollCase):
    def test_a_failure_at_every_acquisition_point_of_a_growing_table_leaves_it_intact_and_nothing_leaked(self):
        # points: the buffer of the table, then every growth (4, 8, 16, 32 slots for 20 entries). Whatever fails, the keys that were inserted are all still there.
        path = self.source(
            'func main() u32 !{memory.read,memory.write} {\n  let c = map.new<u32,u64,alloc.Heap>(0u32)\n  match c { Ok(m) {\n    var inserted u32 = 0u32\n    var failed u32 = 0u32\n    var i u32 = 0u32\n'
            '    for i < 20u32 {\n      let r = map.insert<u32,u64,alloc.Heap>(borrow_mut(m), i, u64(i) + 1u64)\n'
            '      match r { Ok(k) { inserted = inserted + 1u32 } Err(e) { failed = failed + 1u32 } }\n      i = i + 1u32\n    }\n'
            # every key that was accepted is readable with its value; the count agrees
            '    var bad u32 = 0u32\n    i = 0u32\n    var present u32 = 0u32\n    for i < 20u32 {\n      let g = map.get<u32,u64,alloc.Heap>(borrow(m), i)\n'
            '      match g { Ok(v) { present = present + 1u32\n          if v != u64(i) + 1u64 { bad = bad + 1u32 } } Err(e) { } }\n      i = i + 1u32\n    }\n'
            '    var out u32 = 42u32\n    if bad != 0u32 { out = 1u32 }\n    if present != inserted { out = 2u32 }\n    if map.len<u32,u64,alloc.Heap>(borrow(m)) != inserted { out = 3u32 }\n'
            '    if failed != 0u32 { if out == 42u32 { out = 43u32 } }\n'
            '    let d u32 = map.destroy<u32,u64,alloc.Heap>(move(m))\n    return out\n  } Err(e) { return 60u32 + e } }\n}\n', 'sweep.omni')
        base_ev, base_nat = self.run_both(path, {'OMNI_RESOURCE_AUDIT': '1'})
        self.assertEqual((base_ev[0], base_nat[0]), (42, 42), (base_ev[1], base_nat[1]))
        outcomes = []
        for n in range(1, 9):
            ev, nat = self.run_both(path, {'OMNI_FAIL_AT': str(n), 'OMNI_RESOURCE_AUDIT': '1'})
            outcomes.append(ev[0])
            self.assertEqual(ev[0], nat[0], (n, ev[1], nat[1]))
            self.assertIn(ev[0], (42, 43, 63), (n, ev[0], ev[1]))   # done despite a refused growth, an insert that said Err, or the table itself refused
            self.assertEqual(audit_lines(ev[1]), audit_lines(nat[1]), n)
            self.assertEqual(classify(ev[1]), 'CLEAN', (n, ev[1]))
        self.assertIn(63, outcomes)       # the failure of the first acquisition: no table
        self.assertIn(43, outcomes)       # a growth refused with no room left: the insert says so and the earlier keys survive
        self.assertIn(42, outcomes)       # the injection past the last point changes nothing


class SeqCursorTests(CollCase):
    TOK = ('struct Tok { h u64 }\nfunc mint(n u64) Resource<Tok> { return resource.seal(Tok { h: n }) }\n'
           'func val(x Borrow<Tok>) u64 { let r Tok = resource.peek(x)\n  return r.h }\n'
           'impl seq.Dispose for Tok { func dispose(x Resource<Tok>) u32 !{memory.write} { let r Tok = resource.unseal(move(x))\n  return 1u32 } }\n'
           'func total(v Borrow<seq.Seq<Tok>>) u64 !{memory.read} {\n  var c seq.Cursor = seq.cursor()\n  var sum u64 = 0u64\n'
           '  for seq.more<Tok>(v, c) {\n    let e = seq.at<Tok>(v, c)\n    sum = sum + val(e)\n    c = seq.advance(c)\n  }\n  return sum\n}\n'
           'func fill(v BorrowMut<seq.Seq<Tok>>, n u64) u32 !{memory.read,memory.write} {\n  var i u64 = 1u64\n  for i <= n {\n'
           '    let g = seq.reserve<Tok>(v)\n    match g { Ok(c) { } Err(e) { return 1u32 } }\n'
           '    let r = seq.push<Tok>(v, mint(i))\n    match r { Ok(k) { } Err(back) { let z u32 = seq.Dispose.dispose<Tok>(move(back))\n      return 2u32 } }\n    i = i + 1u64\n  }\n  return 0u32\n}\n')

    def test_walking_a_collection_of_resources_lends_each_element_and_moves_none(self):
        # the walk is repeated, the elements are still all there afterwards and are disposed exactly once by destroy (five elements: dispose reports 5)
        self.run_ok(self.TOK +
            'func main() u32 !{memory.read,memory.write} {\n  let c = seq.new<Tok>(0u32)\n  match c { Ok(s) {\n    var code u32 = fill(borrow_mut(s), 5u64)\n'
            '    if total(borrow(s)) != 15u64 { code = 3u32 }\n    if total(borrow(s)) != 15u64 { code = 4u32 }\n    if seq.len<Tok>(borrow(s)) != 5u32 { code = 5u32 }\n'
            '    let d u32 = seq.destroy<Tok>(move(s))\n    if d != 5u32 { code = 6u32 }\n    if code != 0u32 { return code }\n    return 42u32\n  } Err(e) { return e } }\n}\n')

    def test_a_cursor_never_reaches_a_cell_that_is_not_there(self):
        self.run_ok(self.TOK +
            'func main() u32 !{memory.read,memory.write} {\n  let c = seq.new<Tok>(0u32)\n  match c { Ok(s) {\n    var code u32 = fill(borrow_mut(s), 3u64)\n'
            '    var cur seq.Cursor = seq.cursor()\n    cur = seq.advance(seq.advance(cur))\n'
            '    if !seq.more<Tok>(borrow(s), cur) { code = 3u32 }\n'
            '    let p = seq.pop<Tok>(borrow_mut(s))\n    match p { Ok(x) { let z u32 = seq.Dispose.dispose<Tok>(move(x)) } Err(e) { code = 4u32 } }\n'
            '    if seq.more<Tok>(borrow(s), cur) { code = 5u32 }\n'
            '    let d u32 = seq.destroy<Tok>(move(s))\n    if code != 0u32 { return code }\n    return 42u32\n  } Err(e) { return e } }\n}\n')

    def test_the_sequence_cannot_change_while_an_element_is_lent(self):
        main_with = ('func main() u32 !{memory.read,memory.write} {\n  let c = seq.new<Tok>(2u32)\n  match c { Ok(s) {\n%s\n  } Err(e) { return e } }\n}\n')
        destroy = '    let d u32 = seq.destroy<Tok>(move(s))\n    return d\n'
        cases = [
            ('a push while an element is lent', main_with % ('    let cur seq.Cursor = seq.cursor()\n    let e = seq.at<Tok>(borrow(s), cur)\n'
                                                              '    let r = seq.push<Tok>(borrow_mut(s), mint(1u64))\n    match r { Ok(k) { } Err(back) { let z u32 = seq.Dispose.dispose<Tok>(move(back)) } }\n'
                                                              '    let w u64 = val(e)\n' + destroy), b'E_BORROW_CONFLICT'),
            ('the element lent by the walk is moved out', main_with % ('    let cur seq.Cursor = seq.cursor()\n    let e = seq.at<Tok>(borrow(s), cur)\n    let x Resource<Tok> = e\n' + destroy), b'E_TYPE'),
        ]
        for label, program, code in cases:
            with self.subTest(label):
                self.rejected(self.TOK + program, code)


if __name__ == '__main__':
    unittest.main()
