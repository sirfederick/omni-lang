#!/usr/bin/env python3
"""CP-03 row 3.4 (spec/CANCELLATION_CANDIDATE.md): cancellation and withdrawal of a real task that owns resources.

The tasks are real: each has its own stack and context (cpu.switch_context), runs the function the image names with --thread-entry, owns two leases (a resource whose close can fail, with an
oracle in raw memory) and is scheduled by plain Omni code, on the bootstrap processor or on an application processor. The owner holds a Resource<coop.Task> that owns the control block and
the stack. What is shown, and what is not: spec/CANCELLATION_CANDIDATE.md section 4. QEMU TCG is not hardware; a task that never reaches a checkpoint cannot be stopped, only never freed."""
from __future__ import annotations
import re
import shutil
import unittest
from language_0_8_3_alpha8 import ROOT, OMNI, proc, X64Harness
from cp13_atomics import atomic_ops

STORAGE = ROOT / 'examples' / 'storage'
CORPUS = ROOT / 'tests' / 'corpus' / 'cp03'
THREAD = ('--thread-entry', 't.worker')

SINGLE_TRANSCRIPT = [
    '2', '2', '2', '3', '5', '0', '0', '0', '2', '2', '0', '0', '0',                    # normal: three yields, DONE (3); state 5 (RETIRED: the scheduler has left the task), joined with result 0, completed; leases 0 live, 2 taken, 2 closed; destroy 0; nothing left
    '1', '4', '4', '4', '0', '1', '0', '0', '0', '0', '0', '0',                         # cancel before start: 1 (never started), the scheduler cannot start it (4, 4); no lease was ever taken; outcome 1; destroy 0
    '2', '2', '0', '3', '5', '1', '1', '0', '2', '2', '0', '0', '0',                    # cancel while running: two leases live at the first yield, request made (0), the task closes both and ends with 1; outcome 1; clean
    '3', '70', '5', '70', '3', '0', '1', '1', '0', '0', '0',                            # the second acquisition fails (30 + 40): the first lease is closed, the task ends failed (outcome 3), one taken and one closed
    '3', '33', '5', '33', '3', '0', '2', '1', '1', '0', '0',                            # a close fails (33): the other lease is still closed, the first error wins; two taken, one closed, one closed with a failure
    '0', '0', '3', '5', '1', '1', '0', '2', '2', '0', '0',                              # effect, request BEFORE the dispatch: journal 0, outcome 1 (nothing was dispatched)
    '1', '0', '3', '5', '1', '2', '0', '2', '2', '0', '0',                              # effect, request AFTER the dispatch and before the confirmation: journal 1, outcome 2 (UNKNOWN_OUTCOME)
    '2', '0', '3', '5', '1', '5', '0', '2', '2', '0', '0',                              # effect, request after the confirmation: journal 2, outcome 5 (the effect is known to have happened)
    '2', '3', '5', '0', '0', '0', '2', '2', '0', '0',                                   # effect, no request: completed
    '2', '24', '2', '3', '0', '0', '0', '2', '2', '0',                                  # the owner gives the task back while it may still run: 24 (abandoned), 2 blocks kept; it ends correctly on them
    '1024', '3', '1', '1024', '5', '0', '0', '0', '2', '2', '0', '0', '2',              # a task that uses more than half of its stack and less than all of it: the head of the block below the stack is intact before and after, destroy 0
    '1023', '7', '1023', '1', '0', '2',                                                 # the waits: the retirement wait times out on a new task (1023); on DONE (result 7, journal 2) the end wait answers the RESULT (7) and the retirement wait still times out; a task that never started satisfies it (1); destroy 0; only the abandoned blocks are left
    '2', '2',                                                                           # the abandoned blocks are the only ones left; teardown of the heap reports them
]

SMP_TRANSCRIPTS = {
    4: ['1', '0', '1', '1', '1', '0', '0', '3', '0', '2', '2', '0', '0'],           # request, ACK (1), retirement (1), outcome 1, destroy frees (0, nothing left), the scheduler ended on DONE, leases balanced
    5: ['1', '0', '1', '24', '2', '3', '0', '2', '2', '0', '2'],                    # destroy at the ACK, before the retirement: refused (24), two blocks kept, the scheduler ends on DONE on memory that is still there
    1: ['1', '0', '1', '1', '3', '0', '2', '2', '0', '0', '0', '0'],             # progress seen, request, acknowledged (1), outcome 1, the AP's scheduler ended on DONE, leases balanced, destroy 0, nothing left
    2: ['0', '1023', '4', '2', '24', '2', '3', '1', '1', '0', '2', '2', '0', '2'],  # request; the wait TIMES OUT (23); outcome PENDING (4); state RUNNING; destroy ABANDONS (24); 2 blocks kept; released: ends on DONE with result 1 and the request seen; balanced; heap reports 2
    3: ['0', '1', '1', '3', '20000', '0', '1', '0', '2', '2', '0', '0', '0', '0'],  # request during the section; acknowledged; the section completed (20000), the lock is free, the request was already there when it ended; balanced
}


class CoopCase(X64Harness):
    def stage(self, program):
        for name in ('heap.omni', 'coop.omni', 'critical.omni'):
            shutil.copy(STORAGE / name, self.dir / name)
        for f in CORPUS.iterdir():
            if f.suffix == '.omni':
                shutil.copy(f, self.dir / f.name)
        return self.dir / program

    def lines(self, serial):
        return serial.split('\n')[:-1]

    def variant(self, program, number, name):
        text = (self.dir / program).read_text(encoding='utf-8')
        old = 'func variant() u32 { return 1u32 }'
        self.assertIn(old, text)
        path = self.dir / name
        path.write_text(text.replace(old, 'func variant() u32 { return %du32 }' % number), encoding='utf-8')
        return path


class CooperativeTaskTests(CoopCase):
    """One CPU: the scheduler is the program's main."""

    def test_every_scenario_of_cancellation_ends_with_the_resources_accounted_for(self):
        rc, serial = self.boot(self.build(self.stage('coop_single.omni'), emit_args=THREAD))
        self.assertEqual(self.lines(serial), SINGLE_TRANSCRIPT, serial)
        self.assertEqual(rc, 1)
        self.assertEqual(self.sh('nm', '-u', 'payload.elf').stdout, b'')


class TwoCpuTaskTests(CoopCase):
    """Two CPUs: the task runs on the application processor and is cancelled from the bootstrap processor."""

    def test_a_task_running_on_another_cpu_is_cancelled_acknowledged_and_only_then_destroyed(self):
        self.stage('coop_smp.omni')
        elf = self.build(self.variant('coop_smp.omni', 1, 'smp1.omni'), ap_main=True, emit_args=THREAD)
        for attempt in range(2):
            rc, serial = self.boot(elf, smp=2)
            self.assertEqual((rc, self.lines(serial)), (1, SMP_TRANSCRIPTS[1]), (attempt, serial))

    def test_a_task_that_does_not_cooperate_is_never_reported_as_cancelled_and_never_freed_under_itself(self):
        self.stage('coop_smp.omni')
        elf = self.build(self.variant('coop_smp.omni', 2, 'smp2.omni'), ap_main=True, emit_args=THREAD)
        for attempt in range(2):
            rc, serial = self.boot(elf, smp=2)
            self.assertEqual((rc, self.lines(serial)), (1, SMP_TRANSCRIPTS[2]), (attempt, serial))

    def test_a_request_that_arrives_inside_a_critical_section_is_seen_after_the_section_not_inside_it(self):
        self.stage('coop_smp.omni')
        elf = self.build(self.variant('coop_smp.omni', 3, 'smp3.omni'), ap_main=True, emit_args=THREAD)
        for attempt in range(2):
            rc, serial = self.boot(elf, smp=2)
            self.assertEqual((rc, self.lines(serial)), (1, SMP_TRANSCRIPTS[3]), (attempt, serial))

    # the scheduler is made slow to leave a task that has ended: a pause between the switch back (it has seen DONE) and the read that decides whether to retire
    SLOW = ('  let back u64 = cpu.switch_context(sched, ctrl + 40u64)\n  let after u32',
            '  let back u64 = cpu.switch_context(sched, ctrl + 40u64)\n  if atomic.load32(ctrl, 1u32) == s_done() {\n    for pause in 0u32..20000000u32 {\n      let t u32 = atomic.load32(5308800u64, 0u32)\n    }\n  }\n  let after u32')

    def slow(self, number, mutate=None):
        self.stage('coop_smp.omni')
        library = (self.dir / 'coop.omni').read_text(encoding='utf-8')
        self.assertIn(self.SLOW[0], library)
        library = library.replace(*self.SLOW)
        if mutate:
            self.assertIn(mutate[0], library)
            library = library.replace(*mutate)
        (self.dir / 'coop.omni').write_text(library, encoding='utf-8')
        return self.build(self.variant('coop_smp.omni', number, 'smp%d.omni' % number), ap_main=True, emit_args=THREAD)

    def test_the_acknowledgement_is_not_the_quiescence_the_owner_waits_for_the_scheduler_to_leave(self):
        elf = self.slow(4)
        for attempt in range(2):
            rc, serial = self.boot(elf, smp=2)
            self.assertEqual((rc, self.lines(serial)), (1, SMP_TRANSCRIPTS[4]), (attempt, serial))

    def test_a_destroy_at_the_acknowledgement_frees_nothing_while_the_scheduler_is_still_leaving(self):
        elf = self.slow(5)
        for attempt in range(2):
            rc, serial = self.boot(elf, smp=2)
            self.assertEqual((rc, self.lines(serial)), (1, SMP_TRANSCRIPTS[5]), (attempt, serial))

    def test_a_destroy_that_trusts_the_acknowledgement_frees_the_block_under_the_scheduler(self):
        # the control: destroy accepts DONE (the acknowledgement) instead of RETIRED; the scheduler then reads a block that was freed and zeroed (it ends on state 0, not on DONE)
        elf = self.slow(5, ('      if st != s_retired() {\n        if st != s_unstarted() { return 24u32 }\n      }\n', '      if st != s_done() {\n        if st != s_unstarted() { return 24u32 }\n      }\n'))
        rc, serial = self.boot(elf, smp=2)
        self.assertNotEqual((rc, self.lines(serial)), (1, SMP_TRANSCRIPTS[5]), serial)

    def test_without_the_second_cpu_the_scenario_fails_explicitly(self):
        self.stage('coop_smp.omni')
        rc, serial = self.boot(self.build(self.variant('coop_smp.omni', 1, 'smp1.omni'), ap_main=True, emit_args=THREAD), smp=1)
        self.assertEqual((rc, self.lines(serial)), (1, ['999', '2']), serial)   # the scheduler never came up: said so, the task that never ran was kept (24) and the heap reports its two blocks


class CancellationControlTests(CoopCase):
    """The controls: the oracle must notice a library that frees a stack that can still run, or an acknowledgement given by someone else."""

    def mutate(self, needle, replacement):
        library = (self.dir / 'coop.omni').read_text(encoding='utf-8')
        self.assertIn(needle, library)
        (self.dir / 'coop.omni').write_text(library.replace(needle, replacement), encoding='utf-8')

    def test_a_destroy_that_ignores_the_state_frees_a_stack_that_can_still_run(self):
        self.stage('coop_single.omni')
        self.mutate('      if st != s_retired() {\n        if st != s_unstarted() { return 24u32 }\n      }\n', '')
        rc, serial = self.boot(self.build(self.dir / 'coop_single.omni', emit_args=THREAD))
        self.assertNotEqual((rc, self.lines(serial)), (1, SINGLE_TRANSCRIPT), 'the abandon scenario must notice a freed stack')

    def test_an_owner_that_acknowledges_for_the_task_is_noticed(self):
        # request_cancel writes the DONE state itself (an acknowledgement nobody gave): the task is still running and the scheduler's view of it is wrong
        self.stage('coop_single.omni')
        self.mutate('      let flag u32 = atomic.store32(blk.addr + 4u64, 1u32, 2u32)\n', '      let flag u32 = atomic.store32(blk.addr + 4u64, 1u32, 2u32)\n      let fake u32 = atomic.store32(blk.addr, s_done(), 2u32)\n')
        rc, serial = self.boot(self.build(self.dir / 'coop_single.omni', emit_args=THREAD))
        self.assertNotEqual((rc, self.lines(serial)), (1, SINGLE_TRANSCRIPT))


class ProtocolOrderTests(CoopCase):
    """x86 shows none of the orders: the acknowledgement protocol is checked on the emitted IR (the orders are the contract of spec/MEMORY_MODEL_X86_64_CANDIDATE.md)."""

    def test_the_request_the_acknowledgement_and_the_journal_are_published_and_read_with_release_and_acquire(self):
        path = self.stage('coop_single.omni')
        self.assertEqual(self.emit(path, extra=THREAD).returncode, 0)
        ir = (self.dir / 'prog.ll').read_text(encoding='utf-8')
        A, R, Q = 'acquire', 'release', 'acq_rel'
        expected = {
            'coop.request_cancel': [('cas', (Q, A)), ('store', (R,))],        # NEW -> CANCELLED_UNSTARTED is acq_rel; the request is a release store
            'coop.await_end': [('load', (A,)), ('load', (A,)), ('load', (A,))],   # the state, then the result (after DONE, after RETIRED): acquire, so the result written before the acknowledgement is visible
            'coop.await_retired': [('load', (A,))],
            'coop.outcome': [('load', (A,)), ('load', (A,)), ('load', (A,))],
            'coop.destroy': [('load', (A,))],                                  # the state is read with acquire before anything is freed
            'coop.run': [('cas', (Q, A)), ('load', (A,)), ('load', (A,)), ('store', (R,))],     # NEW -> RUNNING is acq_rel; DONE -> RETIRED is the release store that ends the scheduler's use of the block
            'coop.checkpoint': [('load', (A,))],                               # the request is read with acquire when the task is resumed
            'coop.cancelled': [('load', (A,))],
            'coop.dispatch': [('store', (R,))], 'coop.confirm': [('store', (R,))],
            'coop.finish': [('store', (R,)), ('store', (R,))],                 # the result, then the state (the acknowledgement)
            'coop.state': [('load', (A,))],
        }
        for fn, ops in expected.items():
            with self.subTest(function=fn):
                self.assertEqual(atomic_ops(ir, fn), ops)
        body = re.search(r'define [^\n@]*@omni\.fn\.coop\.finish[^\n]*\{\n(.*?)^\}', ir, re.S | re.M).group(1)
        stores = [l for l in body.splitlines() if 'store atomic volatile i32' in l]
        self.assertEqual(len(stores), 2, stores)
        self.assertNotRegex(stores[0], r'i32 3,')                              # the result is written first ...
        self.assertRegex(stores[1], r'i32 3,')                                 # ... and the state DONE, the acknowledgement, last


class TaskOwnershipLawTests(CoopCase):
    """What the checker enforces on the task and on its body."""

    HEAD = ('module t\nimport rt "rt.omni"\nimport heap "heap.omni"\nimport coop "coop.omni"\nimport lease "lease.omni"\n')

    def rejected(self, source, code, label=''):
        path = self.dir / 'neg.omni'
        path.write_text(source, encoding='utf-8')
        result = self.emit(path, extra=THREAD)
        self.assertEqual(result.returncode, 2, (label, result.stderr))
        self.assertIn(code, result.stderr, (label, result.stderr))

    def test_the_owner_cannot_forget_forge_or_open_the_task(self):
        self.stage('coop_single.omni')
        owner = (self.HEAD + 'func worker() u32 { return 0u32 }\n'
                 'func run(hp BorrowMut<heap.Heap>) u32 !{memory.raw,memory.atomic,cpu.control} {\n  let n = coop.create(hp, 128u64, 1u64)\n  match n { Ok(t) {\n%s  } Err(e) { return e } }\n}\n'
                 'func main() u32 { return 0u32 }\n')
        for label, body, code in (
            ('never destroyed', '    return 0u32\n', b'E_RESOURCE_UNCONSUMED'),
            ('destroyed twice', '    let a u32 = coop.destroy(hp, move(t))\n    let b u32 = coop.destroy(hp, move(t))\n    return a\n', b'E_RESOURCE_MOVED'),
            ('used after destroy', '    let a u32 = coop.destroy(hp, move(t))\n    let s = coop.state(borrow(hp), borrow(t))\n    return a\n', b'E_RESOURCE_MOVED'),
            ('opened outside its module', '    let inner coop.Task = resource.peek(borrow(t))\n    let a u32 = coop.destroy(hp, move(t))\n    return a\n', b'E_RESOURCE_PRIVATE'),
            ('built from a number', '    let fake = coop.Task { m: 7340112u64 }\n    let a u32 = coop.destroy(hp, move(fake))\n    let b u32 = coop.destroy(hp, move(t))\n    return a\n', b'E_RESOURCE_ACCESS'),
            ('the task is given back while it is lent', '    let r = borrow(t)\n    let a u32 = coop.destroy(hp, move(t))\n    let s = coop.state(borrow(hp), r)\n    return a\n', b'E_BORROW_CONFLICT'),
        ):
            with self.subTest(label=label):
                self.rejected(owner % body, code, label)

    def test_a_body_cannot_leave_with_a_lease_it_took(self):
        self.stage('coop_single.omni')
        head = (self.HEAD + 'func work(ctrl u64, s u64) u32 !{memory.raw,memory.atomic,cpu.control} {\n  let a = lease.acquire(7274496u64)\n  match a {\n    Err(e) { return e }\n    Ok(la) {\n%s    }\n  }\n}\n'
                'func worker() u32 !{memory.raw,memory.atomic,cpu.control,port.io} {\n  let ctrl u64 = raw.load64(7278592u64)\n  let r u32 = work(ctrl, 7282688u64)\n  return coop.finish(ctrl, r, 7282688u64)\n}\nfunc main() u32 { return 0u32 }\n')
        cancelled = '      if coop.checkpoint(ctrl, s) != 0u32 {\n        return 1u32\n      }\n'
        close = '      let c = lease.release(7274496u64, move(la))\n      match c { Ok(n) { return 0u32 } Err(e) { return e } }\n'
        for label, body, code in (
            ('the path after a cancellation forgets the lease', cancelled + close, b'E_RESOURCE_UNCONSUMED'),
            ('the lease is never closed', '      return 0u32\n', b'E_RESOURCE_UNCONSUMED'),
            ('the lease is closed twice', '      let c = lease.release(7274496u64, move(la))\n      let d = lease.release(7274496u64, move(la))\n      match c { Ok(n) { return 0u32 } Err(e) { return e } }\n', b'E_RESOURCE_MOVED'),
            ('the result of the close is ignored', '      let c = lease.release(7274496u64, move(la))\n      return 0u32\n', b'E_RESULT_UNHANDLED'),
        ):
            with self.subTest(label=label):
                self.rejected(head % body, code, label)
        loan = '      let view = borrow(la)\n      if coop.checkpoint(ctrl, s) != 0u32 {\n        let c = lease.release(7274496u64, move(la))\n        let slot u64 = lease.slot(view)\n        match c { Ok(n) { return 1u32 } Err(e) { return e } }\n      }\n' + close
        with self.subTest(label='a loan of the lease is live across the cancellation point and the cleanup closes the lease'):
            self.rejected(head % loan, b'E_BORROW_CONFLICT', 'loan')
        ended = '      let slot u64 = looked(borrow(la), ctrl, s)\n' + close
        path = self.dir / 'loan_ok.omni'
        path.write_text((head % ended).replace('func work(', 'func looked(v Borrow<lease.Lease>, ctrl u64, s u64) u64 !{memory.raw,memory.atomic,cpu.control} {\n  let c u32 = coop.checkpoint(ctrl, s)\n  return lease.slot(v)\n}\nfunc work(', 1), encoding='utf-8')
        done = self.emit(path, extra=THREAD)
        self.assertEqual(done.returncode, 0, done.stderr)    # a loan taken only for the call, across the cancellation point, ends with the call: the lease can be closed after it
        ok = head % (cancelled.replace('        return 1u32\n', '        let c = lease.release(7274496u64, move(la))\n        match c { Ok(n) { return 1u32 } Err(e) { return e } }\n') + close)
        path = self.dir / 'ok.omni'
        path.write_text(ok, encoding='utf-8')
        done = self.emit(path, extra=THREAD)
        self.assertEqual(done.returncode, 0, done.stderr)

    def test_the_stack_has_a_geometry_and_a_half_made_task_is_given_back(self):
        self.stage('coop_single.omni')
        program = (self.HEAD + 'func worker() u32 { return 0u32 }\n'
                   'func made(r Result<Resource<coop.Task>,u32>, hp BorrowMut<heap.Heap>) u32 !{memory.raw,memory.atomic} {\n  match r { Ok(t) { return 100u32 + coop.destroy(hp, move(t)) } Err(e) { return e } }\n}\n'
                   'func main() u32 !{io.print,memory.raw,memory.atomic,port.io,cpu.control} {\n'
                   '  let c = heap.create(7340032u64, 65536u64)\n  match c { Ok(hp) {\n'
                   '    print(made(coop.create(borrow_mut(hp), 32u64, 1u64), borrow_mut(hp)))\n    print(made(coop.create(borrow_mut(hp), 65u64, 1u64), borrow_mut(hp)))\n    print(made(coop.create(borrow_mut(hp), 65538u64, 1u64), borrow_mut(hp)))\n'
                   '    print(made(coop.create(borrow_mut(hp), 64u64, 1u64), borrow_mut(hp)))\n    print(made(coop.create(borrow_mut(hp), 65536u64, 1u64), borrow_mut(hp)))\n'
                   '    let n = coop.create(borrow_mut(hp), 128u64, 1u64)\n    match n { Ok(t) {\n'
                   '      let a u32 = coop.destroy(borrow_mut(hp), move(t))\n      print(a)\n'
                   '    } Err(e) { print(e) } }\n    print(heap.destroy(move(hp)))\n  } Err(e) { print(e) } }\n'
                   '  let small = heap.create(7340032u64, 700u64)\n  match small { Ok(hs) {\n    print(made(coop.create(borrow_mut(hs), 64u64, 1u64), borrow_mut(hs)))\n    print(heap.live(borrow(hs)))\n    print(heap.destroy(move(hs)))\n  } Err(e) { print(e) } }\n  return rt.finish(0u32)\n}\n')
        path = self.dir / 'prog.omni'
        path.write_text(program, encoding='utf-8')
        rc, serial = self.boot(self.build(path, emit_args=THREAD))
        # bad geometry of the stack is refused (20: too small, odd, too large); a task that never started is not terminal until it is cancelled, so destroy keeps it (24 + 100) and the heap
        # reports the blocks it kept; a stack that fits the heap but not its control block is given back (1, nothing live)
        self.assertEqual((rc, self.lines(serial)), (1, ['20', '20', '20', '124', '1', '24', '4', '1', '0', '0']), serial)


if __name__ == '__main__':
    unittest.main()
