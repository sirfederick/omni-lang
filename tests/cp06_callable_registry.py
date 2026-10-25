#!/usr/bin/env python3
"""CP-06 (spec/CALLBACK_REGISTRY_HOSTED_CANDIDATE.md, examples/storage/registry.omni): callables whose environment owns resources, stored by a consumer, used
later and retired, in the hosted profile.

The oracles of the master prompt (section 3.5) are exercised in the evaluator and natively: two environments with their own state selected by the consumer, a
registry returned by a constructor and used later, an environment that owns a Buffer closed exactly once (the audit of CP-03 says so), a stale or reused token
refused with a typed result, the effects of the callback required of its caller, the failure of every acquisition point, and the programs that must not compile
(a short-lived capture, a registry inside an environment, a leaked or double-used registration).
"""
from __future__ import annotations
import shutil
import unittest
from cp01_owned_slots import SeqCase
from cp02_borrowed_containers import ContainerCase
from cp03_cleanup_failure import CleanupCase, audit_lines, classify
from language_0_8_3_alpha8 import ROOT

REGISTRY = ROOT / 'examples' / 'storage' / 'registry.omni'

# Two handlers with different code and each with state of its own, kept in a Buffer the environment owns
HANDLERS = (
    'struct Acc { b Resource<Buffer> }\n'
    'struct Mul { b Resource<Buffer> }\n'
    'func make_acc(init u32) Result<Resource<Acc>,u32> !{memory.write} {\n  let a = buffer.alloc(4u32)\n'
    '  match a { Ok(buf) {\n    let w = buffer.write_u32le(borrow_mut(buf), 0u32, init)\n    match w { Ok(k) { } Err(e) { } }\n'
    '    let i Acc = Acc { b: move(buf) }\n    return Ok<Resource<Acc>,u32>(resource.seal(move(i)))\n  } Err(e) { return Err<Resource<Acc>,u32>(e) } }\n}\n'
    'func make_mul(init u32) Result<Resource<Mul>,u32> !{memory.write} {\n  let a = buffer.alloc(4u32)\n'
    '  match a { Ok(buf) {\n    let w = buffer.write_u32le(borrow_mut(buf), 0u32, init)\n    match w { Ok(k) { } Err(e) { } }\n'
    '    let i Mul = Mul { b: move(buf) }\n    return Ok<Resource<Mul>,u32>(resource.seal(move(i)))\n  } Err(e) { return Err<Resource<Mul>,u32>(e) } }\n}\n'
    'impl registry.Handler for Acc {\n'
    '  func call(h BorrowMut<Acc>, x u32) u32 !{memory.read,memory.write} {\n'
    '    var cur u32 = 0u32\n    let r = buffer.read_u32le(resource.inner(borrow(h)), 0u32)\n    match r { Ok(v) { cur = v } Err(e) { } }\n'
    '    let n u32 = cur + x\n    let w = buffer.write_u32le(resource.inner_mut(h), 0u32, n)\n    match w { Ok(k) { } Err(e) { } }\n    return n\n  }\n'
    '  func dispose(h Resource<Acc>) u32 !{memory.read,memory.write} {\n'
    '    let i Acc = resource.unseal(move(h))\n    var cur u32 = 0u32\n    let r = buffer.read_u32le(borrow(i.b), 0u32)\n    match r { Ok(v) { cur = v } Err(e) { } }\n'
    '    let z u32 = buffer.release(move(i.b))\n    return cur\n  }\n}\n'
    'impl registry.Handler for Mul {\n'
    '  func call(h BorrowMut<Mul>, x u32) u32 !{memory.read,memory.write} {\n'
    '    var cur u32 = 0u32\n    let r = buffer.read_u32le(resource.inner(borrow(h)), 0u32)\n    match r { Ok(v) { cur = v } Err(e) { } }\n'
    '    let n u32 = cur * x\n    let w = buffer.write_u32le(resource.inner_mut(h), 0u32, n)\n    match w { Ok(k) { } Err(e) { } }\n    return n\n  }\n'
    '  func dispose(h Resource<Mul>) u32 !{memory.read,memory.write} {\n'
    '    let i Mul = resource.unseal(move(h))\n    var cur u32 = 0u32\n    let r = buffer.read_u32le(borrow(i.b), 0u32)\n    match r { Ok(v) { cur = v } Err(e) { } }\n'
    '    let z u32 = buffer.release(move(i.b))\n    return cur\n  }\n}\n')

# helpers that keep the registry lent (so an early return never abandons it): register an Acc and return its token, or fail with a code
HELPERS = (
    'func reg_acc(r BorrowMut<registry.Registry<Acc>>, init u32) Result<registry.Token,u32> !{memory.read,memory.write} {\n'
    '  let m = make_acc(init)\n  match m { Ok(env) {\n'
    '    let g = registry.register<Acc>(r, move(env))\n'
    '    match g { Ok(t) { return Ok<registry.Token,u32>(t) } Err(back) { let z u32 = registry.Handler.dispose<Acc>(move(back))\n      return Err<registry.Token,u32>(1000u32) } }\n'
    '  } Err(e) { return Err<registry.Token,u32>(e) } }\n}\n'
    'func run(r BorrowMut<registry.Registry<Acc>>, t registry.Token, x u32) u32 !{memory.read,memory.write} {\n'
    '  let g = registry.fire<Acc>(r, t, x)\n  match g { Ok(v) { return v } Err(e) { return 900000u32 + e } }\n}\n'
    'func end(r BorrowMut<registry.Registry<Acc>>, t registry.Token) u32 !{memory.read,memory.write} {\n'
    '  let g = registry.retire<Acc>(r, t)\n  match g { Ok(v) { return v } Err(e) { return 900000u32 + e } }\n}\n')


class RegCase(CleanupCase):
    def setUp(self):
        super().setUp()
        shutil.copy(REGISTRY, self.dir / 'registry.omni')

    def source(self, text, name='program.omni'):
        return ContainerCase.source(self, 'import seq "seq.omni"\nimport registry "registry.omni"\n' + text, name)

    def with_registry(self, body, cap=0):
        """A program whose `exercise(r)` function gets the registry lent; main creates it, runs exercise, destroys it and returns 42 when exercise returned 0."""
        return self.source(HANDLERS + HELPERS + body +
            'func main() u32 !{memory.read,memory.write} {\n  let c = registry.new<Acc>(%du32)\n  match c { Ok(r) {\n'
            '    let code u32 = exercise(borrow_mut(r))\n    let d u32 = registry.destroy<Acc>(move(r))\n    if code != 0u32 { return code }\n    return 42u32\n'
            '  } Err(e) { return e } }\n}\n' % cap)


class RegisterUseRetireTests(RegCase):
    def test_two_environments_keep_their_own_state_and_the_consumer_selects_which_one_runs(self):
        self.both(self.with_registry(
            'func exercise(r BorrowMut<registry.Registry<Acc>>) u32 !{memory.read,memory.write} {\n'
            '  var a registry.Token = registry.Token { slot: 0u32, gen: 0u32 }\n  var b registry.Token = registry.Token { slot: 0u32, gen: 0u32 }\n'
            '  let ra = reg_acc(r, 10u32)\n  match ra { Ok(t) { a = t } Err(e) { return 1u32 } }\n'
            '  let rb = reg_acc(r, 100u32)\n  match rb { Ok(t) { b = t } Err(e) { return 2u32 } }\n'
            '  if run(r, a, 5u32) != 15u32 { return 3u32 }\n  if run(r, b, 5u32) != 105u32 { return 4u32 }\n'
            '  if run(r, a, 1u32) != 16u32 { return 5u32 }\n  if run(r, b, 0u32) != 105u32 { return 6u32 }\n'
            '  if registry.count<Acc>(borrow(r)) != 2u32 { return 7u32 }\n'
            '  if end(r, b) != 105u32 { return 8u32 }\n  if end(r, a) != 16u32 { return 9u32 }\n'
            '  if registry.count<Acc>(borrow(r)) != 0u32 { return 10u32 }\n  return 0u32\n}\n'))

    def test_a_second_kind_of_callable_has_its_own_code_and_registry(self):
        self.both(self.source(HANDLERS +
            'func main() u32 !{memory.read,memory.write} {\n  let ca = registry.new<Acc>(1u32)\n'
            '  match ca { Ok(ra) {\n    let cm = registry.new<Mul>(1u32)\n    match cm { Ok(rm) {\n'
            '    var code u32 = 0u32\n    var ta registry.Token = registry.Token { slot: 0u32, gen: 0u32 }\n    var tm registry.Token = registry.Token { slot: 0u32, gen: 0u32 }\n'
            '    let ea = make_acc(7u32)\n    match ea { Ok(e) { let g = registry.register<Acc>(borrow_mut(ra), move(e))\n'
            '      match g { Ok(t) { ta = t } Err(b) { let z u32 = registry.Handler.dispose<Acc>(move(b))\n        code = 1u32 } } } Err(x) { code = 2u32 } }\n'
            '    let em = make_mul(7u32)\n    match em { Ok(e) { let g = registry.register<Mul>(borrow_mut(rm), move(e))\n'
            '      match g { Ok(t) { tm = t } Err(b) { let z u32 = registry.Handler.dispose<Mul>(move(b))\n        code = 3u32 } } } Err(x) { code = 4u32 } }\n'
            '    let fa = registry.fire<Acc>(borrow_mut(ra), ta, 3u32)\n    match fa { Ok(v) { if v != 10u32 { code = 5u32 } } Err(x) { code = 6u32 } }\n'
            '    let fm = registry.fire<Mul>(borrow_mut(rm), tm, 3u32)\n    match fm { Ok(v) { if v != 21u32 { code = 7u32 } } Err(x) { code = 8u32 } }\n'
            '    let da u32 = registry.destroy<Acc>(move(ra))\n    let dm u32 = registry.destroy<Mul>(move(rm))\n'
            '    if da != 10u32 { code = 9u32 }\n    if dm != 21u32 { code = 10u32 }\n    if code != 0u32 { return code }\n    return 42u32\n'
            '    } Err(e) { let d u32 = registry.destroy<Acc>(move(ra))\n      return e } }\n  } Err(e) { return e } }\n}\n'))

    def test_a_registry_built_by_a_constructor_is_used_later_with_its_environments_alive(self):
        self.both(self.source(HANDLERS + HELPERS +
            'func build(n u32) Result<Resource<registry.Registry<Acc>>,u32> !{memory.read,memory.write} {\n'
            '  let c = registry.new<Acc>(0u32)\n  match c { Ok(r) {\n    var i u32 = 0u32\n    for i < n {\n'
            '      let t = reg_acc(borrow_mut(r), (i + 1u32) * 10u32)\n      match t { Ok(k) { } Err(e) { let d u32 = registry.destroy<Acc>(move(r))\n        return Err<Resource<registry.Registry<Acc>>,u32>(e) } }\n'
            '      i = i + 1u32\n    }\n    return Ok<Resource<registry.Registry<Acc>>,u32>(move(r))\n  } Err(e) { return Err<Resource<registry.Registry<Acc>>,u32>(e) } }\n}\n'
            'func main() u32 !{memory.read,memory.write} {\n  let b = build(3u32)\n  match b { Ok(r) {\n    var code u32 = 0u32\n'
            # the first registration of a fresh cell has generation 1; the constructor is gone, the environments are still there and keep their data
            '    if run(borrow_mut(r), registry.Token { slot: 0u32, gen: 1u32 }, 1u32) != 11u32 { code = 1u32 }\n'
            '    if run(borrow_mut(r), registry.Token { slot: 2u32, gen: 1u32 }, 2u32) != 32u32 { code = 2u32 }\n'
            '    let d u32 = registry.destroy<Acc>(move(r))\n    if d != 11u32 + 20u32 + 32u32 { code = 3u32 }\n    if code != 0u32 { return code }\n    return 42u32\n'
            '  } Err(e) { return e } }\n}\n'))

    def test_the_registry_grows_and_a_freed_cell_is_reused_with_a_new_generation(self):
        self.both(self.with_registry(
            'func exercise(r BorrowMut<registry.Registry<Acc>>) u32 !{memory.read,memory.write} {\n'
            '  var first registry.Token = registry.Token { slot: 0u32, gen: 0u32 }\n  var i u32 = 0u32\n'
            '  for i < 9u32 {\n    let t = reg_acc(r, i)\n    match t { Ok(k) { if i == 0u32 { first = k }\n      if i == 8u32 { if k.gen != 1u32 { return 8u32 } } } Err(e) { return 100u32 + e } }\n    i = i + 1u32\n  }\n'
            '  if registry.capacity<Acc>(borrow(r)) != 16u32 { return 1u32 }\n  if registry.count<Acc>(borrow(r)) != 9u32 { return 2u32 }\n'
            '  if end(r, first) != 0u32 { return 3u32 }\n'
            '  let again = reg_acc(r, 50u32)\n'
            '  match again { Ok(k) {\n    if k.slot != first.slot { return 4u32 }\n    if k.gen == first.gen { return 5u32 }\n    if run(r, k, 1u32) != 51u32 { return 6u32 }\n'
            '  } Err(e) { return 7u32 } }\n  return 0u32\n}\n'))

    def test_destroying_the_registry_disposes_every_environment_left_exactly_once(self):
        # three environments (10, 20, 30) are left registered; destroy returns the sum of what their dispose reported
        self.both(self.source(HANDLERS + HELPERS +
            'func main() u32 !{memory.read,memory.write} {\n  let c = registry.new<Acc>(0u32)\n  match c { Ok(r) {\n    var code u32 = 0u32\n'
            '    let a = reg_acc(borrow_mut(r), 10u32)\n    match a { Ok(k) { } Err(e) { code = 1u32 } }\n'
            '    let b = reg_acc(borrow_mut(r), 20u32)\n    match b { Ok(k) { } Err(e) { code = 2u32 } }\n'
            '    let d = reg_acc(borrow_mut(r), 30u32)\n    match d { Ok(k) { } Err(e) { code = 3u32 } }\n'
            '    let sum u32 = registry.destroy<Acc>(move(r))\n    if sum != 60u32 { code = 4u32 }\n    if code != 0u32 { return code }\n    return 42u32\n'
            '  } Err(e) { return e } }\n}\n'))

    def test_every_environment_is_released_exactly_once_over_more_rounds_than_the_buffer_table_holds(self):
        # 1100 rounds of (registry + 2 environments that own a buffer each); a leak or a double release makes a later allocation or the audit fail
        self.both(self.source(HANDLERS + HELPERS +
            'func round(k u32) u32 !{memory.read,memory.write} {\n  let c = registry.new<Acc>(2u32)\n  match c { Ok(r) {\n    var code u32 = 0u32\n'
            '    var ta registry.Token = registry.Token { slot: 0u32, gen: 0u32 }\n    var tb registry.Token = registry.Token { slot: 0u32, gen: 0u32 }\n'
            '    let a = reg_acc(borrow_mut(r), k)\n    match a { Ok(t) { ta = t } Err(e) { code = 4u32 } }\n'
            '    let b = reg_acc(borrow_mut(r), k + 1u32)\n    match b { Ok(t) { tb = t } Err(e) { code = 3u32 } }\n'
            '    if code == 0u32 {\n'
            '      if run(borrow_mut(r), ta, 1u32) != k + 1u32 { code = 1u32 }\n      if end(borrow_mut(r), tb) != k + 1u32 { code = 2u32 }\n    }\n'
            '    let d u32 = registry.destroy<Acc>(move(r))\n    if code == 0u32 { if d != k + 1u32 { code = 5u32 } }\n    return code\n  } Err(e) { return 90u32 } }\n}\n'
            'func main() u32 !{memory.read,memory.write} {\n  var k u32 = 0u32\n  for k < 1100u32 {\n    let c u32 = round(k)\n    if c != 0u32 { return c }\n    k = k + 1u32\n  }\n  return 42u32\n}\n'))

    def test_the_audit_shows_one_acquisition_and_one_release_per_environment_and_in_the_order_of_use(self):
        path = self.source(HANDLERS + HELPERS +
            'func exercise(r BorrowMut<registry.Registry<Acc>>) u32 !{memory.read,memory.write} {\n'
            '  var ta registry.Token = registry.Token { slot: 0u32, gen: 0u32 }\n  var tb registry.Token = registry.Token { slot: 0u32, gen: 0u32 }\n'
            '  let a = reg_acc(r, 1u32)\n  match a { Ok(t) { ta = t } Err(e) { return 4u32 } }\n'
            '  let b = reg_acc(r, 2u32)\n  match b { Ok(t) { tb = t } Err(e) { return 3u32 } }\n'
            '  if end(r, tb) != 2u32 { return 1u32 }\n  if end(r, ta) != 1u32 { return 2u32 }\n  return 0u32\n}\n'
            'func main() u32 !{memory.read,memory.write} {\n  let c = registry.new<Acc>(0u32)\n  match c { Ok(r) {\n'
            '    let code u32 = exercise(borrow_mut(r))\n    let d u32 = registry.destroy<Acc>(move(r))\n    if code != 0u32 { return code }\n    return 42u32\n'
            '  } Err(e) { return e } }\n}\n', 'audit.omni')
        ev, nat = self.run_both(path, {'OMNI_RESOURCE_AUDIT': '1'})
        self.assertEqual((ev[0], nat[0]), (42, 42), (ev[1], nat[1]))
        # acq 1 = the registry, 2 and 3 = the environments (Acc 1 and Acc 2); the second is retired first, then the first, then the registry is destroyed
        expected = ['audit acq 1', 'audit acq 2', 'audit acq 3', 'audit rel 3', 'audit rel 2', 'audit rel 1', 'audit summary acquired=3 released=3 live=0']
        self.assertEqual(audit_lines(ev[1]), expected)
        self.assertEqual(audit_lines(nat[1]), expected)
        self.assertEqual(classify(ev[1]), 'CLEAN')


class GenerationHorizonTests(RegCase):
    """A cell whose generation reached the horizon is retired for good (slot state 4), so an old token can never match a later occupant. The real horizon is 2^32
    registrations of one cell, out of reach of a test; OMNI_SLOT_GEN_MAX=3 lowers it for both engines (documented in the spec, like OMNI_FAIL_AT)."""
    def program(self, third_slot, capacity):
        return self.with_registry(
            'func exercise(r BorrowMut<registry.Registry<Acc>>) u32 !{memory.read,memory.write} {\n'
            '  var t1 registry.Token = registry.Token { slot: 0u32, gen: 0u32 }\n  var t2 registry.Token = registry.Token { slot: 0u32, gen: 0u32 }\n'
            '  var t3 registry.Token = registry.Token { slot: 0u32, gen: 0u32 }\n'
            '  let a = reg_acc(r, 10u32)\n  match a { Ok(t) { t1 = t } Err(e) { return 1u32 } }\n'
            '  if t1.gen != 1u32 { return 2u32 }\n  if end(r, t1) != 10u32 { return 3u32 }\n'
            '  let b = reg_acc(r, 20u32)\n  match b { Ok(t) { t2 = t } Err(e) { return 4u32 } }\n'
            '  if t2.slot != 0u32 { return 5u32 }\n  if t2.gen != 2u32 { return 6u32 }\n  if end(r, t2) != 20u32 { return 7u32 }\n'
            # the cell has now seen its last occupant under the lowered horizon
            '  let c = reg_acc(r, 30u32)\n  match c { Ok(t) { t3 = t } Err(e) { return 8u32 } }\n'
            '  if t3.slot != %du32 { return 9u32 }\n  if registry.capacity<Acc>(borrow(r)) != %du32 { return 10u32 }\n'
            '  if run(r, t3, 1u32) != 31u32 { return 11u32 }\n'
            # the tokens of the earlier occupants never reach the new one, whichever cell it lives in
            '  if run(r, t1, 1u32) == 31u32 { return 12u32 }\n  if run(r, t2, 1u32) == 31u32 { return 13u32 }\n'
            '  if end(r, t3) != 31u32 { return 14u32 }\n  return 0u32\n}\n' % (third_slot, capacity), cap=1)

    def test_an_exhausted_cell_is_never_reused_and_registration_moves_to_another_cell(self):
        path = self.program(1, 4)
        ev, nat = self.run_both(path, {'OMNI_SLOT_GEN_MAX': '3', 'OMNI_RESOURCE_AUDIT': '1'})
        self.assertEqual((ev[0], nat[0]), (42, 42), (ev[1], nat[1]))
        self.assertEqual(audit_lines(ev[1]), audit_lines(nat[1]))
        self.assertEqual(classify(ev[1]), 'CLEAN')

    def test_with_the_real_horizon_the_same_cell_is_reused(self):
        ev, nat = self.run_both(self.program(0, 1))
        self.assertEqual((ev[0], nat[0]), (42, 42), (ev[1], nat[1]))

    def test_a_malformed_or_too_small_horizon_is_ignored(self):
        path = self.program(0, 1)
        for value in ('', '1', '0', 'x', '3x', '-3'):
            with self.subTest(value=value):
                ev, nat = self.run_both(path, {'OMNI_SLOT_GEN_MAX': value})
                self.assertEqual((ev[0], nat[0]), (42, 42), (ev[1], nat[1]))


class StaleAndForgedTokenTests(RegCase):
    def test_a_retired_a_reused_and_a_forged_token_are_refused_with_a_typed_result_and_never_reach_another_environment(self):
        self.both(self.with_registry(
            'func exercise(r BorrowMut<registry.Registry<Acc>>) u32 !{memory.read,memory.write} {\n'
            '  var old registry.Token = registry.Token { slot: 0u32, gen: 0u32 }\n  var cur registry.Token = registry.Token { slot: 0u32, gen: 0u32 }\n'
            '  let a = reg_acc(r, 10u32)\n  match a { Ok(t) { old = t } Err(e) { return 1u32 } }\n'
            '  if end(r, old) != 10u32 { return 2u32 }\n'
            # a retired registration: nothing live in the cell
            '  if run(r, old, 1u32) != 900001u32 { return 3u32 }\n  if end(r, old) != 900001u32 { return 4u32 }\n'
            # the cell is reused by another registration: the old token is stale (2), the new one works and its state was not touched by the stale attempts
            '  let b = reg_acc(r, 500u32)\n  match b { Ok(t) { cur = t } Err(e) { return 5u32 } }\n'
            '  if cur.slot != old.slot { return 6u32 }\n  if cur.gen == old.gen { return 7u32 }\n'
            '  if run(r, old, 1u32) != 900002u32 { return 8u32 }\n  if end(r, old) != 900002u32 { return 9u32 }\n'
            '  if run(r, cur, 1u32) != 501u32 { return 10u32 }\n'
            # forged: another cell, one never used, a generation that was never issued
            '  if run(r, registry.Token { slot: 99u32, gen: 1u32 }, 1u32) != 900001u32 { return 11u32 }\n'
            '  if run(r, registry.Token { slot: cur.slot, gen: cur.gen + 1u32 }, 1u32) != 900002u32 { return 12u32 }\n'
            '  if run(r, registry.Token { slot: cur.slot, gen: 0u32 }, 1u32) != 900002u32 { return 13u32 }\n'
            '  if registry.check<Acc>(borrow(r), cur) != 0u32 { return 14u32 }\n  if end(r, cur) != 501u32 { return 15u32 }\n  return 0u32\n}\n'))


class FailureAtEveryPointTests(RegCase):
    def test_a_failure_at_every_acquisition_point_hands_the_environment_back_and_leaves_nothing_behind(self):
        # points, in order: the registry's own buffer, then for each of 5 environments its buffer and, when the registry is full, the growth of the registry
        path = self.source(HANDLERS + HELPERS +
            'func build(r BorrowMut<registry.Registry<Acc>>, n u32) u32 !{memory.read,memory.write} {\n  var i u32 = 0u32\n'
            '  for i < n {\n    let m = make_acc(i + 1u32)\n    match m { Ok(env) {\n'
            '      let g = registry.register<Acc>(r, move(env))\n'
            '      match g { Ok(t) { } Err(back) { let z u32 = registry.Handler.dispose<Acc>(move(back))\n        return 30u32 + z } }\n'
            '    } Err(e) { return 10u32 + e } }\n    i = i + 1u32\n  }\n  return 0u32\n}\n'
            'func main() u32 !{memory.read,memory.write} {\n  let c = registry.new<Acc>(0u32)\n  match c { Ok(r) {\n'
            '    let code u32 = build(borrow_mut(r), 5u32)\n    let d u32 = registry.destroy<Acc>(move(r))\n'
            '    if code != 0u32 { return code }\n    if d != 1u32 + 2u32 + 3u32 + 4u32 + 5u32 { return 60u32 }\n    return 42u32\n'
            '  } Err(e) { return 50u32 + e } }\n}\n', 'sweep.omni')
        # new -> 53; env0: alloc(13), grow(33 = the registry cannot grow: the environment, whose dispose reports its value 1, comes back); ...
        outcomes = []
        for n in range(1, 40):
            ev, nat = self.run_both(path, {'OMNI_FAIL_AT': str(n), 'OMNI_RESOURCE_AUDIT': '1'})
            outcomes.append(ev[0])
            self.assertEqual(ev[0], nat[0], (n, ev[1], nat[1]))
            self.assertEqual(audit_lines(ev[1]), audit_lines(nat[1]), n)
            self.assertEqual(classify(ev[1]), 'CLEAN', (n, ev[1]))
            if ev[0] == 42:
                break
        # the sweep ended in a run without injection and went through the three kinds of outcome: the registry itself, an environment, a registration that could not grow
        self.assertEqual(outcomes[-1], 42)
        self.assertIn(53, outcomes)
        self.assertTrue(any(11 <= o <= 19 for o in outcomes), outcomes)
        self.assertTrue(any(31 <= o <= 39 for o in outcomes), outcomes)
        self.assertEqual(len(outcomes), 9, outcomes)   # 8 points, then the run that no injection reaches


class NoUnwindTests(RegCase):
    def test_a_fault_inside_a_callback_ends_the_run_and_unwinds_nothing_through_the_registry(self):
        # the callback shifts by a runtime count of 64: a trap. Omni has no unwinding in the hosted profile: the process stops with the fault, no environment is
        # disposed on the way out, and the audit says the registry and its environment were still live (a termination is not a cleanup guarantee, CP-03 row 3.6)
        trap = ('struct Trap { b Resource<Buffer> }\n'
                'func make_trap() Result<Resource<Trap>,u32> !{memory.write} {\n  let a = buffer.alloc(4u32)\n'
                '  match a { Ok(buf) {\n    let i Trap = Trap { b: move(buf) }\n    return Ok<Resource<Trap>,u32>(resource.seal(move(i)))\n  } Err(e) { return Err<Resource<Trap>,u32>(e) } }\n}\n'
                'impl registry.Handler for Trap {\n'
                '  func call(h BorrowMut<Trap>, x u32) u32 !{memory.read,memory.write} {\n    let v u64 = bit.shl(1u64, x)\n    return 0u32\n  }\n'
                '  func dispose(h Resource<Trap>) u32 !{memory.read,memory.write} {\n    let i Trap = resource.unseal(move(h))\n    let z u32 = buffer.release(move(i.b))\n    return 0u32\n  }\n}\n')

        def program(count):
            return self.source(trap +
                'func main() u32 !{memory.read,memory.write} {\n  let c = registry.new<Trap>(1u32)\n  match c { Ok(r) {\n    var code u32 = 0u32\n'
                '    let m = make_trap()\n    match m { Ok(env) {\n      let g = registry.register<Trap>(borrow_mut(r), move(env))\n'
                '      match g { Ok(t) {\n        let f = registry.fire<Trap>(borrow_mut(r), t, %du32)\n        match f { Ok(v) { code = 0u32 } Err(e) { code = e } }\n'
                '      } Err(back) { let z u32 = registry.Handler.dispose<Trap>(move(back))\n        code = 1u32 } }\n    } Err(e) { code = 2u32 } }\n'
                '    let d u32 = registry.destroy<Trap>(move(r))\n    if code != 0u32 { return code }\n    return 42u32\n  } Err(e) { return e } }\n}\n' % count,
                'trap%d.omni' % count)

        ev, nat = self.run_both(program(3), {'OMNI_RESOURCE_AUDIT': '1'})          # contrast: without the trap everything is disposed
        self.assertEqual((ev[0], nat[0]), (42, 42), (ev[1], nat[1]))
        self.assertEqual(classify(nat[1]), 'CLEAN')
        ev, nat = self.run_both(program(64), {'OMNI_RESOURCE_AUDIT': '1'})
        self.assertNotEqual(ev[0], 0)
        self.assertIn(b'E_BOUNDS', ev[1])
        self.assertEqual(nat[0], 70, nat[1])
        self.assertIn(b'omni runtime E_BOUNDS', nat[1])
        for who, err in (('evaluator', ev[1]), ('native', nat[1])):
            lines = audit_lines(err)
            self.assertFalse([l for l in lines if l.startswith('audit rel')], (who, lines))     # nothing was released on the way out
            self.assertEqual(lines[-1], 'audit summary acquired=2 released=0 live=2', who)       # the registry and the environment were still live


class RegistryLawTests(RegCase):
    def test_what_must_not_compile(self):
        main_with = ('func main() u32 !{memory.read,memory.write} {\n  let c = registry.new<Acc>(2u32)\n  match c { Ok(r) {\n%s\n  } Err(e) { return e } }\n}\n')
        destroy = '    let d u32 = registry.destroy<Acc>(move(r))\n    return d\n'
        cases = [
            ('a short-lived capture: a record cannot hold a borrow at all',
             'struct Cap { p Borrow<Acc> }\nfunc main() u32 { return 0u32 }\n', b'E_TYPE'),
            ('an environment that holds the registry (the way back into it) is not a valid slot type',
             'struct Loop { r Resource<registry.Registry<Acc>> }\nfunc main() u32 !{memory.write} {\n  let a = slots.alloc<Loop>(1u32)\n  return 0u32\n}\n', b'E_RESOURCE_TYPE'),
            ('an environment with state that is not owned storage',
             'struct Pair { a u32, b u32 }\nfunc main() u32 !{memory.write} {\n  let a = slots.alloc<Pair>(1u32)\n  return 0u32\n}\n', b'E_RESOURCE_TYPE'),
            ('a registration that is never retired nor destroyed', main_with % '    return 0u32', b'E_RESOURCE_UNCONSUMED'),
            ('the environment is used after it was registered',
             main_with % ('    let m = make_acc(1u32)\n    match m { Ok(env) {\n      let g = registry.register<Acc>(borrow_mut(r), move(env))\n'
                          '      match g { Ok(t) { } Err(back) { let z u32 = registry.Handler.dispose<Acc>(move(back)) } }\n'
                          '      let z u32 = registry.Handler.dispose<Acc>(move(env))\n    } Err(e) { return e } }\n' + destroy), b'E_RESOURCE_MOVED'),
            ('the result of register is dropped, so the environment that came back is leaked',
             main_with % ('    let m = make_acc(1u32)\n    match m { Ok(env) {\n      let g = registry.register<Acc>(borrow_mut(r), move(env))\n    } Err(e) { return e } }\n' + destroy), b'E_RESULT_UNHANDLED'),
            ('the registry is destroyed twice',
             main_with % ('    let first u32 = registry.destroy<Acc>(move(r))\n    let again u32 = registry.destroy<Acc>(move(r))\n    return again\n'), b'E_RESOURCE_MOVED'),
            ('the registry is opened from outside its module',
             main_with % ('    let inner registry.Registry<Acc> = resource.unseal(move(r))\n    return 0u32'), b'E_RESOURCE_PRIVATE'),
            ('a type with no Handler impl is fired',
             'struct Plain { b Resource<Buffer> }\nfunc go(r BorrowMut<registry.Registry<Plain>>, t registry.Token) Result<u32,u32> !{memory.read,memory.write} {\n'
             '  return registry.fire<Plain>(r, t, 1u32)\n}\nfunc main() u32 { return 0u32 }\n', b'E_GENERIC_CONSTRAINT'),
            ('the callback asks for more authority than the trait grants',
             'struct Raw { b Resource<Buffer> }\nimpl registry.Handler for Raw {\n  func call(h BorrowMut<Raw>, x u32) u32 !{memory.raw} { return x }\n'
             '  func dispose(h Resource<Raw>) u32 !{memory.write} { let i Raw = resource.unseal(move(h))\n    let z u32 = buffer.release(move(i.b))\n    return 0u32 }\n}\nfunc main() u32 { return 0u32 }\n',
             b'E_TRAIT_EFFECT'),
            ('the caller of fire does not hold the effects of the callback',
             'func go(r BorrowMut<registry.Registry<Acc>>, t registry.Token) Result<u32,u32> {\n  return registry.fire<Acc>(r, t, 1u32)\n}\nfunc main() u32 { return 0u32 }\n', b'E_CAPABILITY'),
            ('a token is passed where a registry is expected',
             main_with % ('    let t registry.Token = registry.Token { slot: 0u32, gen: 1u32 }\n    let n u32 = registry.count<Acc>(t)\n' + destroy), b'E_TYPE'),
        ]
        for label, program, code in cases:
            with self.subTest(label):
                path = self.source(HANDLERS + program, 'bad.omni')
                checked = subprocess_check(path)
                self.assertEqual(checked.returncode, 2, checked.stderr)
                if code is not None:
                    self.assertIn(code, checked.stderr, checked.stderr)


def subprocess_check(path):
    from language_0_8_3_alpha8 import proc, OMNI
    return proc(OMNI, 'check', path)


if __name__ == '__main__':
    unittest.main()
