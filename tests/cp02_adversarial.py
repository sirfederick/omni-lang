#!/usr/bin/env python3
"""CP-02 row 2.10: no cast, identifier or integer manufactures a lifetime or an authority.

Adversarial programs against the APIs of the 1.3 collections and registries (spec/OWNED_SLOTS_CANDIDATE.md, CALLBACK_REGISTRY_HOSTED_CANDIDATE.md,
COLLECTIONS_PROTOCOLS_CANDIDATE.md). Each attempt either does not compile (with the code that names the rule it breaks) or, when the language lets the value exist because
it is plain data, it is checked at every use and gives a typed result or a typed fault: never a read or a write through a forged position.
"""
from __future__ import annotations
import unittest
from cp06_callable_registry import RegCase, HANDLERS, HELPERS
from cp03_cleanup_failure import audit_lines, classify

TOK = ('struct Tok { h u64 }\nfunc mint(n u64) Resource<Tok> { return resource.seal(Tok { h: n }) }\n'
       'func val(x Borrow<Tok>) u64 { let r Tok = resource.peek(x)\n  return r.h }\n'
       'impl seq.Dispose for Tok { func dispose(x Resource<Tok>) u32 !{memory.write} { let r Tok = resource.unseal(move(x))\n  return 1u32 } }\n')


class ForgedLifetimeAndAuthorityTests(RegCase):
    def test_nothing_turns_an_integer_into_a_borrow_a_resource_or_a_buffer(self):
        cases = [
            ('an integer where a borrow is expected', TOK + 'func go(x Borrow<Tok>) u64 { return val(x) }\nfunc main() u32 { let n u64 = go(5u64)\n  return 0u32 }\n', b'E_TYPE'),
            ('an integer where a resource is expected', TOK + 'func eat(f Resource<Tok>) u64 { let r Tok = resource.unseal(move(f))\n  return r.h }\nfunc main() u32 { let n u64 = eat(7u64)\n  return 0u32 }\n', b'E_TYPE'),
            ('an integer where a buffer is expected', 'func main() u32 !{memory.read} {\n  let r = buffer.read_u8(borrow(5u64), 0u32)\n  return 0u32\n}\n', None),
            ('a resource cast to an integer', TOK + 'func main() u32 {\n  let x = mint(1u64)\n  let n u64 = u64(x)\n  return 0u32\n}\n', None),
            ('an integer cast to a resource', TOK + 'func main() u32 {\n  let x Resource<Tok> = Resource<Tok>(5u64)\n  return 0u32\n}\n', None),
        ]
        for label, program, code in cases:
            with self.subTest(label):
                path = self.source(program, 'bad.omni')
                from language_0_8_3_alpha8 import proc, OMNI
                checked = proc(OMNI, 'check', path)
                self.assertEqual(checked.returncode, 2, (label, checked.stderr))
                if code:
                    self.assertIn(code, checked.stderr, checked.stderr)

    def test_a_borrow_cannot_be_kept_returned_from_a_local_or_wrapped(self):
        cases = [
            ('a borrow kept in a record', TOK + 'struct Keep { p Borrow<Tok> }\nfunc main() u32 { return 0u32 }\n', b'E_TYPE'),
            ('a borrow of a local returned', TOK + 'func bad() Borrow<Tok> {\n  let x = mint(1u64)\n  return borrow(x)\n}\nfunc main() u32 { return 0u32 }\n', b'E_BORROW_ESCAPE'),
            ('a borrow inside a result', TOK + 'func bad(v Borrow<Tok>) Result<Borrow<Tok>,u32> { return Ok<Borrow<Tok>,u32>(v) }\nfunc main() u32 { return 0u32 }\n', b'E_TYPE'),
            ('the element lent by a cursor kept past the sequence', TOK + 'func main() u32 !{memory.read,memory.write} {\n  let c = seq.new<Tok>(1u32)\n  match c { Ok(s) {\n'
             '    let cur seq.Cursor = seq.cursor()\n    let e = seq.at<Tok>(borrow(s), cur)\n    let d u32 = seq.destroy<Tok>(move(s))\n    let w u64 = val(e)\n    return d\n  } Err(x) { return x } }\n}\n', b'E_BORROW_CONFLICT'),
        ]
        for label, program, code in cases:
            with self.subTest(label):
                self.rejected(program, code)

    def test_a_token_of_one_registry_does_not_open_another_kind_of_registry_nor_the_inside_of_one(self):
        cases = [
            ('a registry of one handler type lent where another is expected',
             HANDLERS + HELPERS + 'func main() u32 !{memory.read,memory.write} {\n  let c = registry.new<Acc>(1u32)\n  match c { Ok(r) {\n'
             '    let g = registry.fire<Mul>(borrow_mut(r), registry.Token { slot: 0u32, gen: 1u32 }, 1u32)\n    match g { Ok(v) { } Err(e) { } }\n'
             '    let d u32 = registry.destroy<Acc>(move(r))\n    return d\n  } Err(e) { return e } }\n}\n', b'E_TYPE'),
            ('the buffer inside a registry reached from outside its module',
             HANDLERS + 'func main() u32 !{memory.read,memory.write} {\n  let c = registry.new<Acc>(1u32)\n  match c { Ok(r) {\n    let n u32 = slots.len(resource.inner(borrow(r)))\n'
             '    let d u32 = registry.destroy<Acc>(move(r))\n    return d\n  } Err(e) { return e } }\n}\n', b'E_RESOURCE_PRIVATE'),
            # the literal itself is plain data and can be written; what no one outside the module can do is SEAL it, so it is never a registry that the API accepts
            ('a registry forged from a buffer and a record literal: it cannot be sealed',
             HANDLERS + 'func main() u32 !{memory.read,memory.write} {\n  let a = buffer.alloc(4u32)\n  match a { Ok(b) {\n    let forged registry.Registry<Acc> = registry.Registry<Acc> { buf: move(b) }\n'
             '    let sealed = resource.seal(move(forged))\n    return 0u32\n  } Err(e) { return e } }\n}\n', b'E_RESOURCE_PRIVATE'),
        ]
        for label, program, code in cases:
            with self.subTest(label):
                self.rejected(program, code)

    def test_a_forged_position_is_checked_at_every_use_and_never_reads_a_cell_that_is_not_there(self):
        # a cursor is plain data and can be written by anyone: beyond the end `more` is false, and asking `at` for it anyway is the typed fault E_SLOT_STATE in both engines
        base = (TOK + 'func main() u32 !{memory.read,memory.write} {\n  let c = seq.new<Tok>(2u32)\n  match c { Ok(s) {\n'
                '    let r = seq.push<Tok>(borrow_mut(s), mint(5u64))\n    match r { Ok(k) { } Err(back) { let z u32 = seq.Dispose.dispose<Tok>(move(back)) } }\n'
                '    let far seq.Cursor = seq.Cursor { index: 4000000000u32 }\n    if seq.more<Tok>(borrow(s), far) { let d0 u32 = seq.destroy<Tok>(move(s))\n      return 90u32 }\n')
        ok = base + '    let d u32 = seq.destroy<Tok>(move(s))\n    return 42u32\n  } Err(e) { return e } }\n}\n'
        ev, nat = self.run_both(self.source(ok, 'forged_ok.omni'))
        self.assertEqual((ev[0], nat[0]), (42, 42), (ev[1], nat[1]))
        bad = base + '    let e = seq.at<Tok>(borrow(s), far)\n    let w u64 = val(e)\n    let d u32 = seq.destroy<Tok>(move(s))\n    return d\n  } Err(e) { return e } }\n}\n'
        ev, nat = self.run_both(self.source(bad, 'forged_bad.omni'), {'OMNI_RESOURCE_AUDIT': '1'})
        self.assertNotEqual(ev[0], 0)
        self.assertIn(b'E_SLOT_STATE', ev[1])
        self.assertEqual(nat[0], 70, nat[1])
        self.assertIn(b'omni runtime E_SLOT_STATE', nat[1])

    def test_a_forged_key_of_the_wrong_type_never_reaches_the_cells_of_a_typed_buffer(self):
        # the cells of a slot buffer belong to ONE resource type: another type's put hands its resource back, its take and its state are refused (typed), no cell is changed
        self.both(self.source(TOK + 'struct Other { h u64 }\nfunc mint_other(n u64) Resource<Other> { return resource.seal(Other { h: n }) }\n'
            'func eat_other(f Resource<Other>) u64 { let r Other = resource.unseal(move(f))\n  return r.h }\n'
            'func eat(f Resource<Tok>) u64 { let r Tok = resource.unseal(move(f))\n  return r.h }\n'
            'func main() u32 !{memory.read,memory.write} {\n  let a = slots.alloc<Tok>(2u32)\n  match a { Ok(b) {\n    var code u32 = 0u32\n'
            '    let p = slots.put<Tok>(borrow_mut(b), 0u32, mint(1u64))\n    match p { Ok(i) { } Err(back) { let z u64 = eat(move(back))\n      code = 1u32 } }\n'
            '    let w = slots.put<Other>(borrow_mut(b), 1u32, mint_other(2u64))\n    match w { Ok(i) { code = 2u32 } Err(back) { if eat_other(move(back)) != 2u64 { code = 3u32 } } }\n'
            '    let t = slots.take<Other>(borrow_mut(b), 0u32)\n    match t { Ok(x) { let z u64 = eat_other(move(x))\n      code = 4u32 } Err(e) { if e != 3u32 { code = 5u32 } } }\n'
            '    if slots.state<Other>(borrow(b), 0u32) != 3u32 { code = 6u32 }\n    if slots.gen<Other>(borrow(b), 0u32) != 0u32 { code = 7u32 }\n'
            '    if slots.state<Tok>(borrow(b), 0u32) != 1u32 { code = 8u32 }\n'
            '    let tk = slots.take<Tok>(borrow_mut(b), 0u32)\n    match tk { Ok(x) { if eat(move(x)) != 1u64 { code = 9u32 } } Err(e) { code = 10u32 } }\n'
            '    let rl = slots.release(move(b))\n    match rl { Ok(k) { } Err(back) { code = 11u32 } }\n'
            '    if code != 0u32 { return code }\n    return 42u32\n  } Err(e) { return e } }\n}\n'))


if __name__ == '__main__':
    unittest.main()
