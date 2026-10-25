#!/usr/bin/env python3
"""CP-13 row 13.6 (spec/MEMORY_MODEL_X86_64_CANDIDATE.md): the memory model of atomic.* checked three ways that do not depend on one another.

1. A bounded, exhaustive operational model of the CONTRACT (C++-style relaxed / acquire / release / seq_cst, views per thread, no load buffering): litmus tests MP, SB, CoRR and the
   mailbox protocol. It says which outcomes the orders allow, and that the release/acquire pair of the mailbox is necessary.
2. A bounded model of the HARDWARE (x86-TSO, one store buffer per CPU): every outcome x86 can show must be allowed by (1), and x86 must hide the MP violation (which is why a green x86 run
   cannot show that release/acquire is dispensable) but not the SB one.
3. The compiler and the backend: the order each form is lowered to in the IR and the instruction it becomes, and the two-vCPU store-buffering litmus under QEMU.
The models are tests, not part of the product; they are small on purpose so that their own definitions can be read in a page.
"""
from __future__ import annotations
import re
import shutil
import unittest
from language_0_8_3_alpha8 import ROOT, OMNI, proc, X64Harness

STORAGE = ROOT / 'examples' / 'storage'
CORPUS = ROOT / 'tests' / 'corpus' / 'cp13'

# ---------------------------------------------------------------------------------------------------------------------------------------------------------------
# Program form: a thread is a list of instructions.
#   ('st', loc, value, order)           value: int or ('reg', name)
#   ('ld', reg, loc, order)
#   ('fence', order)
#   ('guard', reg, minimum)             the thread stops here (gives up) unless regs[reg] >= minimum: a bounded "wait until"
# Orders: 'rlx', 'acq', 'rel', 'sc'.
# ---------------------------------------------------------------------------------------------------------------------------------------------------------------


def join(a, b):
    out = dict(a)
    for k, v in b.items():
        if out.get(k, 0) < v:
            out[k] = v
    return out


def freeze(d):
    return tuple(sorted(d.items()))


def explore_view(threads, locs, final_regs):
    """All outcomes of the contract model. Memory: per location a list of messages (value, timestamp, view). A thread has a view (location -> newest timestamp it knows)."""
    init_mem = tuple((loc, ((0, 0, ()),)) for loc in locs)
    start = (init_mem, tuple((0, (), ()) for _ in threads), ())     # memory, per thread (pc, regs, view), sc view
    seen = set()
    outcomes = set()
    todo = [start]
    while todo:
        state = todo.pop()
        if state in seen:
            continue
        seen.add(state)
        mem, ths, sc = state
        memd = dict(mem)
        progressed = False
        for i, (pc, regs, view) in enumerate(ths):
            prog = threads[i]
            if pc >= len(prog):
                continue
            progressed = True
            ins = prog[pc]
            regd = dict(regs)
            viewd = dict(view)
            kind = ins[0]

            def put(newmem, newregs, newview, newsc, npc):
                nth = list(ths)
                nth[i] = (npc, freeze(newregs), freeze(newview))
                todo.append((tuple(sorted(newmem.items())), tuple(nth), freeze(newsc)))

            if kind == 'guard':
                if regd.get(ins[1], 0) >= ins[2]:
                    put(memd, regd, viewd, dict(sc), pc + 1)
                else:
                    put(memd, regd, viewd, dict(sc), len(prog))       # gives up
            elif kind == 'st':
                _, loc, value, order = ins
                v = regd[value[1]] if isinstance(value, tuple) else value
                ts = memd[loc][-1][1] + 1
                nview = dict(viewd)
                nview[loc] = ts
                mview = dict(nview) if order in ('rel', 'sc') else {loc: ts}
                nmem = dict(memd)
                nmem[loc] = memd[loc] + ((v, ts, freeze(mview)),)
                nsc = dict(sc)
                if order == 'sc':                                     # an seq_cst store is a release store followed by an seq_cst fence (its x86 form is xchg)
                    nview = join(nview, nsc)
                    nsc = dict(nview)
                put(nmem, regd, nview, nsc, pc + 1)
            elif kind == 'ld':
                _, reg, loc, order = ins
                base = dict(viewd)
                nsc = dict(sc)
                if order == 'sc':                                     # an seq_cst load is preceded by an seq_cst fence
                    base = join(base, nsc)
                    nsc = dict(base)
                for (v, ts, mview) in memd[loc]:
                    if ts < base.get(loc, 0):
                        continue
                    nview = dict(base)
                    nview[loc] = max(nview.get(loc, 0), ts)
                    if order in ('acq', 'sc'):
                        nview = join(nview, dict(mview))
                    nregs = dict(regd)
                    nregs[reg] = v
                    put(memd, nregs, nview, nsc, pc + 1)
            elif kind == 'fence':
                nview, nsc = dict(viewd), dict(sc)
                if ins[1] == 'sc':
                    nview = join(nview, nsc)
                    nsc = dict(nview)
                put(memd, regd, nview, nsc, pc + 1)
            else:
                raise ValueError(ins)
        if not progressed:
            regs = {}
            for (pc, r, view) in ths:
                regs.update(dict(r))
            outcomes.add(tuple(regs.get(n) for n in final_regs))
    return outcomes


def explore_tso(threads, locs, final_regs):
    """All outcomes of x86-TSO: a store goes to the CPU's FIFO buffer and reaches memory later; a load takes the newest buffered value of its location, else memory.
    A seq_cst store (xchg) and a seq_cst fence (mfence) drain the buffer first. Other fences are nothing on x86."""
    start = (tuple((loc, 0) for loc in locs), tuple((0, (), ()) for _ in threads))
    seen = set()
    outcomes = set()
    todo = [start]
    while todo:
        state = todo.pop()
        if state in seen:
            continue
        seen.add(state)
        mem, ths = state
        memd = dict(mem)
        moved = False
        for i, (pc, regs, buf) in enumerate(ths):
            prog = threads[i]
            nth = list(ths)
            if buf:                                                   # the oldest store reaches memory
                moved = True
                nmem = dict(memd)
                nmem[buf[0][0]] = buf[0][1]
                nth[i] = (pc, regs, buf[1:])
                todo.append((tuple(sorted(nmem.items())), tuple(nth)))
                nth = list(ths)
            if pc >= len(prog):
                continue
            ins = prog[pc]
            regd = dict(regs)
            kind = ins[0]
            if kind == 'guard':
                moved = True
                nth[i] = (pc + 1 if regd.get(ins[1], 0) >= ins[2] else len(prog), regs, buf)
                todo.append((mem, tuple(nth)))
            elif kind == 'st':
                _, loc, value, order = ins
                v = regd[value[1]] if isinstance(value, tuple) else value
                if order == 'sc' and buf:
                    continue                                          # xchg: the buffer must be empty first (the drain steps above get it there)
                moved = True
                if order == 'sc':
                    nmem = dict(memd)
                    nmem[loc] = v
                    nth[i] = (pc + 1, regs, buf)
                    todo.append((tuple(sorted(nmem.items())), tuple(nth)))
                else:
                    nth[i] = (pc + 1, regs, buf + ((loc, v),))
                    todo.append((mem, tuple(nth)))
            elif kind == 'ld':
                _, reg, loc, order = ins
                moved = True
                v = memd[loc]
                for (l, bv) in buf:
                    if l == loc:
                        v = bv
                nregs = dict(regd)
                nregs[reg] = v
                nth[i] = (pc + 1, freeze(nregs), buf)
                todo.append((mem, tuple(nth)))
            elif kind == 'fence':
                if ins[1] == 'sc' and buf:
                    continue
                moved = True
                nth[i] = (pc + 1, regs, buf)
                todo.append((mem, tuple(nth)))
        if not moved:
            regs = {}
            for (pc, r, buf) in ths:
                regs.update(dict(r))
            outcomes.add(tuple(regs.get(n) for n in final_regs))
    return outcomes


def mp(store_order, load_order):
    return ([('st', 'x', 1, 'rlx'), ('st', 'y', 1, store_order)], [('ld', 'r1', 'y', load_order), ('ld', 'r2', 'x', 'rlx')])


def sb(kind):
    if kind == 'plain':
        a, b = [('st', 'x', 1, 'rlx'), ('ld', 'r1', 'y', 'rlx')], [('st', 'y', 1, 'rlx'), ('ld', 'r2', 'x', 'rlx')]
    elif kind == 'relacq':
        a, b = [('st', 'x', 1, 'rel'), ('ld', 'r1', 'y', 'acq')], [('st', 'y', 1, 'rel'), ('ld', 'r2', 'x', 'acq')]
    elif kind == 'fence':
        a, b = [('st', 'x', 1, 'rlx'), ('fence', 'sc'), ('ld', 'r1', 'y', 'rlx')], [('st', 'y', 1, 'rlx'), ('fence', 'sc'), ('ld', 'r2', 'x', 'rlx')]
    else:
        a, b = [('st', 'x', 1, 'sc'), ('ld', 'r1', 'y', 'sc')], [('st', 'y', 1, 'sc'), ('ld', 'r2', 'x', 'sc')]
    return (a, b)


def protocol(tail_store='rel', tail_load='acq', head_store='rel', head_load='acq'):
    """The mailbox with one slot and two messages. The producer waits (once) for the consumer to have taken the previous message, writes the payload with a relaxed (plain) store
    and publishes the tail; the consumer waits (once) for the tail, reads the payload (relaxed: a plain read) and releases the slot. A message that the consumer reads is
    wrong if its payload is not its number."""
    producer, consumer = [], []
    for k in (1, 2):
        producer += [('ld', 'h%d' % k, 'head', head_load), ('guard', 'h%d' % k, k - 1), ('st', 'data', k, 'rlx'), ('st', 'tail', k, tail_store)]
        consumer += [('ld', 't%d' % k, 'tail', tail_load), ('guard', 't%d' % k, k), ('ld', 'd%d' % k, 'data', 'rlx'), ('st', 'head', k, head_store)]
    return producer, consumer


PROTOCOL_REGS = ('d1', 'd2')
MPOUT = (1, 0)                                                         # r1 = 1 (the flag) and r2 = 0 (stale data)


class ViewModelTests(unittest.TestCase):
    """The contract: which outcomes each combination of orders allows."""

    def outcomes(self, threads, final=('r1', 'r2')):
        return explore_view(list(threads), ('x', 'y'), final)

    def test_message_passing_needs_a_release_store_and_an_acquire_load_together(self):
        allowed = {(so, lo): MPOUT in self.outcomes(mp(so, lo)) for so in ('rlx', 'rel', 'sc') for lo in ('rlx', 'acq', 'sc')}
        self.assertEqual(allowed, {('rlx', 'rlx'): True, ('rlx', 'acq'): True, ('rlx', 'sc'): True,
                                   ('rel', 'rlx'): True, ('rel', 'acq'): False, ('rel', 'sc'): False,
                                   ('sc', 'rlx'): True, ('sc', 'acq'): False, ('sc', 'sc'): False})

    def test_the_only_outcomes_of_message_passing_are_the_expected_ones(self):
        self.assertEqual(self.outcomes(mp('rel', 'acq')), {(0, 0), (0, 1), (1, 1)})
        self.assertEqual(self.outcomes(mp('rlx', 'rlx')), {(0, 0), (0, 1), (1, 0), (1, 1)})

    def test_store_buffering_is_allowed_unless_a_seq_cst_fence_or_seq_cst_accesses_order_it(self):
        weak = {kind: (0, 0) in self.outcomes(sb(kind)) for kind in ('plain', 'relacq', 'fence', 'sc')}
        self.assertEqual(weak, {'plain': True, 'relacq': True, 'fence': False, 'sc': False})
        # and nothing else is lost by the fence: the other three outcomes are all still possible
        self.assertEqual(self.outcomes(sb('fence')), {(0, 1), (1, 0), (1, 1)})

    def test_one_location_has_one_order_for_everybody(self):
        # CoRR: x is written 1 then 2; a thread that read 2 never reads 1 afterwards, with every order
        for order in ('rlx', 'acq'):
            prog = ([('st', 'x', 1, 'rlx'), ('st', 'x', 2, 'rlx')], [('ld', 'r1', 'x', order), ('ld', 'r2', 'x', order)])
            out = explore_view(list(prog), ('x',), ('r1', 'r2'))
            self.assertNotIn((2, 1), out)
            self.assertEqual(out, {(0, 0), (0, 1), (0, 2), (1, 1), (1, 2), (2, 2)})

    def test_the_mailbox_protocol_is_correct_with_release_and_acquire_and_the_model_does_not_make_it_vacuous(self):
        out = explore_view(list(protocol()), ('head', 'tail', 'data'), PROTOCOL_REGS)
        for d1, d2 in out:
            self.assertIn(d1, (None, 1), out)                  # a message that was read carries its number
            self.assertIn(d2, (None, 2), out)
        self.assertIn((1, 2), out)                              # both messages can be delivered
        self.assertIn((1, None), out)
        self.assertIn((None, None), out)

    def test_publishing_with_a_relaxed_store_or_reading_with_a_relaxed_load_lets_a_stale_payload_through(self):
        for name, kw in (('tail store relaxed', dict(tail_store='rlx')), ('tail load relaxed', dict(tail_load='rlx')), ('both relaxed', dict(tail_store='rlx', tail_load='rlx'))):
            out = explore_view(list(protocol(**kw)), ('head', 'tail', 'data'), PROTOCOL_REGS)
            self.assertTrue(any(d1 not in (None, 1) or d2 not in (None, 2) for d1, d2 in out), (name, out))

    def test_what_the_model_cannot_see_is_pinned_by_the_ir_test_instead(self):
        # Releasing the slot with a relaxed store (or taking the head with a relaxed load) is wrong against the contract (the consumer's read of the payload could be
        # satisfied after the producer's next write on a weaker target), but that is a load-buffering behaviour and this model has no load buffering: it finds nothing.
        # tests/cp13_atomics.py::MailboxContractTests pins the orders of push and pop on the IR, which is where a mutation of them shows.
        for kw in (dict(head_store='rlx'), dict(head_load='rlx')):
            out = explore_view(list(protocol(**kw)), ('head', 'tail', 'data'), PROTOCOL_REGS)
            self.assertFalse(any(d1 not in (None, 1) or d2 not in (None, 2) for d1, d2 in out), (kw, out))


class Tso(unittest.TestCase):
    """The hardware the contract is compiled to: x86-TSO."""

    def test_x86_hides_the_message_passing_violation_whatever_the_orders(self):
        # which is why a run on x86 that uses relaxed where release/acquire is needed passes
        for so in ('rlx', 'rel', 'sc'):
            for lo in ('rlx', 'acq', 'sc'):
                prog = mp(so, lo)
                self.assertNotIn(MPOUT, explore_tso(list(prog), ('x', 'y'), ('r1', 'r2')), (so, lo))

    def test_x86_shows_store_buffering_unless_the_store_is_an_xchg_or_there_is_an_mfence(self):
        weak = {kind: (0, 0) in explore_tso(list(sb(kind)), ('x', 'y'), ('r1', 'r2')) for kind in ('plain', 'relacq', 'fence', 'sc')}
        self.assertEqual(weak, {'plain': True, 'relacq': True, 'fence': False, 'sc': False})

    def test_every_outcome_x86_can_show_is_allowed_by_the_contract(self):
        cases = [mp(so, lo) for so in ('rlx', 'rel', 'sc') for lo in ('rlx', 'acq', 'sc')] + [sb(k) for k in ('plain', 'relacq', 'fence', 'sc')]
        for prog in cases:
            hw = explore_tso(list(prog), ('x', 'y'), ('r1', 'r2'))
            contract = explore_view(list(prog), ('x', 'y'), ('r1', 'r2'))
            self.assertLessEqual(hw, contract, prog)
        # and the contract is strictly weaker for the relaxed message passing: x86 never shows what the contract allows
        self.assertLess(explore_tso(list(mp('rlx', 'rlx')), ('x', 'y'), ('r1', 'r2')), explore_view(list(mp('rlx', 'rlx')), ('x', 'y'), ('r1', 'r2')))

    def test_the_protocol_that_is_wrong_against_the_contract_is_still_correct_on_x86(self):
        for kw in (dict(), dict(tail_store='rlx'), dict(tail_load='rlx'), dict(tail_store='rlx', tail_load='rlx')):
            out = explore_tso(list(protocol(**kw)), ('head', 'tail', 'data'), PROTOCOL_REGS)
            self.assertFalse(any(d1 not in (None, 1) or d2 not in (None, 2) for d1, d2 in out), (kw, out))


def instructions(disassembly, function):
    """The mnemonics of one function of an objdump listing."""
    m = re.search(r'<%s>:\n(.*?)(?:\n\n|\Z)' % re.escape(function), disassembly, re.S)
    assert m, function
    return [re.sub(r'\s+', ' ', l.split('\t', 1)[-1]).strip() for l in m.group(1).splitlines() if l.strip()]


class BackendTests(X64Harness):
    """What the compiler and the backend make of each order (section 3 of the spec), and the two-vCPU store-buffering litmus."""

    FORMS = [('st_rlx', 'atomic.store32(a, v, 0u32)'), ('st_rel', 'atomic.store32(a, v, 2u32)'), ('st_sc', 'atomic.store32(a, v, 4u32)'),
             ('ld_rlx', 'atomic.load32(a, 0u32)'), ('ld_acq', 'atomic.load32(a, 1u32)'), ('ld_sc', 'atomic.load32(a, 4u32)'),
             ('cas_rel', 'atomic.cas32(a, v, v + 1u32, 2u32, 0u32)'), ('cas_sc', 'atomic.cas32(a, v, v + 1u32, 4u32, 4u32)'),
             ('add_rlx', 'atomic.fetch_add32(a, v, 0u32)'), ('add_sc', 'atomic.fetch_add32(a, v, 4u32)'),
             ('fence_acq', 'atomic.fence(1u32)'), ('fence_rel', 'atomic.fence(2u32)'), ('fence_acqrel', 'atomic.fence(3u32)'), ('fence_sc', 'atomic.fence(4u32)')]

    def test_each_order_is_lowered_as_the_spec_says_and_only_seq_cst_has_an_instruction_of_its_own(self):
        body = ''.join('noinline func %s(a u64, v u32) u32 !{memory.atomic} {\n  return %s\n}\n' % (name, expr) for name, expr in self.FORMS)
        path = self.dir / 'forms.omni'
        path.write_text('module t\nimport rt "rt.omni"\n' + body + 'func main() u32 !{io.print,memory.atomic,port.io,cpu.control} {\n'
                        + ''.join('  print(%s(5308416u64, 7u32))\n' % name for name, _ in self.FORMS) + '  return rt.finish(0u32)\n}\n', encoding='utf-8')
        self.build(path)
        ir = (self.dir / 'prog.ll').read_text(encoding='utf-8')
        listing = self.sh('objdump', '-d', '--no-show-raw-insn', '-M', 'intel', 'payload.elf').stdout.decode()
        order = {'rlx': 'monotonic', 'acq': 'acquire', 'rel': 'release', 'sc': 'seq_cst', 'acqrel': 'acq_rel'}
        for name, _ in self.FORMS:
            kind, o = name.split('_')
            m = re.search(r'define [^\n@]*@omni\.fn\.t\.%s\(.*?\n\}' % name, ir, re.S)
            self.assertTrue(m, name)
            line = [l for l in m.group(0).splitlines() if re.search(r'atomic|cmpxchg|fence', l) and 'define' not in l]
            self.assertEqual(len(line), 1, (name, line))
            self.assertIn(order[o], line[0], (name, line))
            ins = ' | '.join(instructions(listing, 'omni.fn.t.' + name))
            expected = {'st_rlx': ('mov DWORD PTR', 'xchg'), 'st_rel': ('mov DWORD PTR', 'xchg'), 'st_sc': ('xchg', None),
                        'ld_rlx': ('mov', 'xchg'), 'ld_acq': ('mov', 'xchg'), 'ld_sc': ('mov', 'xchg'),
                        'cas_rel': ('lock cmpxchg', None), 'cas_sc': ('lock cmpxchg', None), 'add_rlx': ('lock xadd', None), 'add_sc': ('lock xadd', None),
                        'fence_sc': ('mfence', None)}.get(name)
            if expected:
                self.assertIn(expected[0], ins, (name, ins))
                if expected[1]:
                    self.assertNotIn(expected[1], ins, (name, ins))
            else:
                self.assertNotIn('mfence', ins, (name, ins))       # acquire / release / acq_rel fences are compiler barriers on x86
                self.assertNotIn('lock', ins, (name, ins))

    def run_litmus(self, variant):
        text = (CORPUS / 'sb_litmus.omni').read_text(encoding='utf-8')
        old = 'func variant() u32 { return 0u32 }'
        self.assertIn(old, text)
        path = self.dir / 'sb.omni'
        path.write_text(text.replace(old, 'func variant() u32 { return %du32 }' % variant), encoding='utf-8')
        rc, serial = self.boot(self.build(path, ap_main=True), smp=2)
        self.assertEqual(rc, 1, serial)
        return [int(x) for x in serial.split('\n')[:-1]]

    def test_the_fenced_store_buffering_litmus_never_shows_the_forbidden_outcome_on_two_vcpus(self):
        for variant in (1, 2):
            with self.subTest(variant=variant):
                self.assertEqual(self.run_litmus(variant), [20000, 20000, 0])

    def test_the_relaxed_store_buffering_litmus_completes_and_its_count_is_reported_not_required(self):
        finished, peer, weak = self.run_litmus(0)
        self.assertEqual((finished, peer), (20000, 20000))
        self.assertGreaterEqual(weak, 0)
        print('\nSB relaxed on QEMU TCG (2 vCPUs, 20000 rounds): r1 = r2 = 0 in %d rounds' % weak)


if __name__ == '__main__':
    unittest.main()
