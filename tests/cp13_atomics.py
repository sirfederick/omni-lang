#!/usr/bin/env python3
"""CP-13 (atomics and safe transfer, rows 13.5 - 13.7): a bounded hand-off between two vCPUs, the memory model that backs it, and what may cross between CPUs.

Everything freestanding runs as an x86-64 image under QEMU TCG with real host threads per vCPU (`-smp 2`); the observation is separated from the claim: QEMU is not hardware, and
x86 hides the difference between relaxed, release and acquire, so the ordering contract is checked on the emitted IR and on the bounded models of tests/cp13_memory_model.py.
"""
from __future__ import annotations
import re
import shutil
import unittest
from language_0_8_3_alpha8 import ROOT, OMNI, proc, X64Harness

STORAGE = ROOT / 'examples' / 'storage'
CORPUS = ROOT / 'tests' / 'corpus' / 'cp13'

MAILBOX_TRANSCRIPT = [
    '1', '1', '5', '14',                                    # format, the producer end opens once, an unaligned base is refused, a second producer end is refused (14)
    '4', '15', '4',                                         # four messages fit in the four slots, the fifth meets "full" and changes nothing, four are pending
    '16', '14',                                             # the consumer found the queue empty before any push (16) and could not open its end twice (14)
    '20000', '0', '19999', '1', '0',                        # every message arrived once, in order, intact: received, bad, last sequence number, checksum equal, no error flag
    '0', '0', '1',                                          # nothing pending at the end, the producer end is closed (0) and can be opened again (1)
]


SINGLE_TRANSCRIPT = [
    '5', '5', '5', '5', '5', '5', '5', '5', '5', '1', '1', '1',  # A: null base, unaligned base, no slots, 3 slots, too many slots, stride 4 / 12 / 8192 refused; the largest geometry and the smallest accepted
    '13', '1', '14', '14',                                  # B: an address that was never formatted is not a mailbox (13); each end opens once (14 for the second)
    '8', '8', '1000016', '0', '0',                          # C: a message larger than a slot is refused by both ends (8), an empty queue answers 16, nothing pending
    '4', '15', '4', '4', '0', '1', '2', '3', '1000016',     # D: four fit, the fifth is "full" (15), four pending on both sides, FIFO order, empty again
    '0', '24', '24',                                        # E: ten rounds through four slots keep their order; both indices advanced by 24
    '0', '0', '12', '1000012', '5', '5', '12', '1000012', '1001', '77',   # F: head beyond tail and more than capacity pending are reported (12), pending is never negative, repaired cells work
    '0', '1', '0',                                          # G: the ends are given back (0), reopened (1), the producer end closed (0)
    '14', '25', '25', '1',                                  # H: formatting again over a mailbox with an end open is refused (14) and changes nothing
    '14', '25', '25', '1',                                  # H2: the same with the PRODUCER end open (14), nothing changed, its claim cell still 1
    '1', '0', '0', '0',                                     # H: with the end given back it starts from tail 0, head 0, no claim
    '13',                                                   # I: the magic constant at an address that is not 64-aligned is not a mailbox (13), nothing is claimed there
    '13',                                                   # a damaged magic is refused (13)
]


class MailboxSingleTests(X64Harness):
    """Row 13.5, one CPU: geometry, ends, order, full / empty, wrap and damage. Evaluator and image under QEMU print the same transcript."""

    def stage(self):
        shutil.copy(STORAGE / 'mailbox.omni', self.dir / 'mailbox.omni')
        shutil.copy(CORPUS / 'mailbox_single.omni', self.dir / 'mailbox_single.omni')
        return self.dir / 'mailbox_single.omni'

    def test_the_evaluator_prints_the_transcript(self):
        path = self.stage()
        text = path.read_text(encoding='utf-8')
        self.assertIn('return rt.finish(0u32)', text)
        evalp = self.dir / 'single_eval.omni'
        evalp.write_text(text.replace('return rt.finish(0u32)', 'return 0u32'), encoding='utf-8')
        done = proc(OMNI, 'eval', evalp, timeout=120)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(done.stdout.decode().split('\n')[:-1], SINGLE_TRANSCRIPT)

    def test_the_freestanding_image_prints_the_same_transcript(self):
        rc, serial = self.boot(self.build(self.stage()))
        self.assertEqual(serial.split('\n')[:-1], SINGLE_TRANSCRIPT, serial)
        self.assertEqual(rc, 1)
        self.assertEqual(self.sh('nm', '-u', 'payload.elf').stdout, b'')

    def test_a_range_that_would_wrap_the_address_space_is_refused_before_any_store(self):
        # the evaluator keeps raw memory sparse, so the top of the address space can be exercised here (a guest image cannot touch it)
        shutil.copy(STORAGE / 'mailbox.omni', self.dir / 'mailbox.omni')
        shutil.copy(ROOT / 'tests' / 'x64' / 'rt.omni', self.dir / 'rt.omni')
        rows = ((18446744073709551552, 4, 8, 6), (18446744073709551104, 1, 56, 1), (18446744073709551104, 1, 64, 6), (18446744073709551104, 8, 8, 6), (18446744073709551104, 2, 8, 1))
        body = ''.join('  print(made(mailbox.create(%du64, %du64, %du64)))\n' % (b, c, st) for b, c, st, _ in rows)
        path = self.dir / 'wrap.omni'
        path.write_text('module t\nimport mailbox "mailbox.omni"\nfunc made(r Result<u32,u32>) u32 {\n  match r { Ok(n) { return 1u32 } Err(e) { return e } }\n}\n'
                        'func main() u32 !{io.print,memory.raw,memory.atomic} {\n' + body + '  return 0u32\n}\n', encoding='utf-8')
        done = proc(OMNI, 'eval', path, timeout=60)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(done.stdout.decode().split('\n')[:-1], [str(r[3]) for r in rows])


class MailboxHandoffTests(X64Harness):
    """Row 13.5: producer on the bootstrap processor, consumer on an application processor, capacity 4, 20000 messages."""

    def stage(self, program):
        shutil.copy(STORAGE / 'mailbox.omni', self.dir / 'mailbox.omni')
        shutil.copy(CORPUS / program, self.dir / program)
        return self.dir / program

    def test_two_vcpus_hand_off_20000_messages_in_order_without_loss_or_repetition(self):
        elf = self.build(self.stage('mailbox_handoff.omni'), ap_main=True)
        for run in range(3):                                # the interleavings differ from run to run; the oracle does not
            rc, serial = self.boot(elf, smp=2)
            self.assertEqual(serial.split('\n')[:-1], MAILBOX_TRANSCRIPT, (run, serial))
            self.assertEqual(rc, 1)

    def test_without_the_second_cpu_the_hand_off_fails_explicitly(self):
        elf = self.build(self.stage('mailbox_handoff.omni'), ap_main=True)
        rc, serial = self.boot(elf, smp=1)
        self.assertEqual(rc, (2 << 1) | 1, (rc, serial))    # finish(2): the consumer never came up, the wait is bounded and says so
        self.assertEqual(serial.split('\n')[-2], '999', serial)


def atomic_ops(ir, function):
    """The atomic operations of the functions whose name contains `function`, in program order, as (kind, orders)."""
    ops = []
    for m in re.finditer(r'^define [^\n@]*@([\w.$]+)\([^\n]*\{\n(.*?)^\}', ir, re.S | re.M):
        if function not in m.group(1):
            continue
        for line in m.group(2).splitlines():
            for key, name in (('load atomic volatile', 'load'), ('store atomic volatile', 'store'), ('atomicrmw volatile', 'rmw'), ('cmpxchg volatile', 'cas'), ('fence ', 'fence')):
                if key in line:
                    ops.append((name, tuple(re.findall(r'\b(monotonic|acquire|release|acq_rel|seq_cst)\b', line))))
                    break
    return ops


class MailboxControlTests(X64Harness):
    """Row 13.5, controls: the oracle that passes the library must notice a hand-off whose order of publication or whose consumer is wrong."""

    def run_mode(self, mode):
        shutil.copy(STORAGE / 'mailbox.omni', self.dir / 'mailbox.omni')
        text = (CORPUS / 'mailbox_controls.omni').read_text(encoding='utf-8')
        old = 'func mode() u32 { return 0u32 }'
        self.assertIn(old, text)
        path = self.dir / 'controls.omni'
        path.write_text(text.replace(old, 'func mode() u32 { return %du32 }' % mode), encoding='utf-8')
        rc, serial = self.boot(self.build(path, ap_main=True), smp=2)
        self.assertEqual(rc, 1, serial)
        return serial.split('\n')[:-1]

    def test_the_correct_order_of_publication_is_not_reported(self):
        self.assertEqual(self.run_mode(0), ['200', '0', '0', '0'])

    def test_a_tail_published_before_the_payload_is_reported(self):
        self.assertEqual(self.run_mode(1), ['200', '1', '0', '0'])

    def test_a_consumer_that_does_not_look_at_the_tail_is_reported(self):
        self.assertEqual(self.run_mode(2), ['200', '1', '0', '0'])


class MailboxEndRaceTests(X64Harness):
    """Adenda 009A MAILBOX-01: two CPUs open the same end at the same moment, 5000 times; exactly one wins every time. A nominal resource cannot be copied, but nothing in the type stops a
    second open: what makes the end exclusive is the compare-and-swap on the claim cell, so the control that claims it with a load and a store shows two winners."""

    def run_variant(self, number, mutate=None):
        shutil.copy(STORAGE / 'mailbox.omni', self.dir / 'mailbox.omni')
        if mutate:
            library = (self.dir / 'mailbox.omni').read_text(encoding='utf-8')
            self.assertIn(mutate[0], library)
            (self.dir / 'mailbox.omni').write_text(library.replace(*mutate), encoding='utf-8')
        text = (CORPUS / 'mailbox_race.omni').read_text(encoding='utf-8')
        old = 'func variant() u32 { return 1u32 }'
        self.assertIn(old, text)
        path = self.dir / 'race.omni'
        path.write_text(text.replace(old, 'func variant() u32 { return %du32 }' % number), encoding='utf-8')
        rc, serial = self.boot(self.build(path, ap_main=True), smp=2)
        self.assertEqual(rc, 1, serial)
        return [int(x) for x in serial.split('\n')[:-1]]

    def test_exactly_one_of_two_simultaneous_opens_of_the_producer_end_wins(self):
        for attempt in range(2):
            self.assertEqual(self.run_variant(1), [5000, 0, 0, 5000, 5000], attempt)    # rounds with one winner, two, none; rounds each CPU completed

    def test_exactly_one_of_two_simultaneous_opens_of_the_consumer_end_wins(self):
        for attempt in range(2):
            self.assertEqual(self.run_variant(2), [5000, 0, 0, 5000, 5000], attempt)

    def test_a_claim_made_with_a_load_and_a_store_lets_both_open_it(self):
        mutate = ('let seen u32 = atomic.cas32(claim_p(base), 0u32, 1u32, 3u32, 1u32)',
                  'let seen u32 = atomic.load32(claim_p(base), 0u32)\n  let taken u32 = atomic.store32(claim_p(base), 1u32, 0u32)')
        both = [self.run_variant(1, mutate)[1] for attempt in range(3)]
        self.assertTrue(any(b > 0 for b in both), both)         # the window is a few instructions wide: some rounds in some runs have two winners


class MailboxContractTests(X64Harness):
    """Row 13.5: the orders of the library on the emitted IR (x86 shows none of them), and the laws the checker enforces on the two ends."""

    def emit_ir(self):
        shutil.copy(STORAGE / 'mailbox.omni', self.dir / 'mailbox.omni')
        shutil.copy(CORPUS / 'mailbox_handoff.omni', self.dir / 'mailbox_handoff.omni')
        emitted = self.emit(self.dir / 'mailbox_handoff.omni')
        self.assertEqual(emitted.returncode, 0, emitted.stderr)
        return (self.dir / 'prog.ll').read_text(encoding='utf-8')

    def test_publication_is_a_release_store_and_consumption_an_acquire_load(self):
        ir = self.emit_ir()
        M, A, R, Q = 'monotonic', 'acquire', 'release', 'acq_rel'
        # push: stride, capacity and own tail are relaxed (immutable or single writer), the head is ACQUIRE (the consumer is done with the slot), the tail is published with RELEASE
        self.assertEqual(atomic_ops(ir, 'mailbox.push'), [('load', (M,)), ('load', (M,)), ('load', (M,)), ('load', (A,)), ('store', (R,))])
        # pop: own head relaxed, the tail ACQUIRE (the payload is visible), the head released with RELEASE
        self.assertEqual(atomic_ops(ir, 'mailbox.pop'), [('load', (M,)), ('load', (M,)), ('load', (M,)), ('load', (A,)), ('store', (R,))])
        # opening an end: the magic is read with ACQUIRE and the claim is an acq_rel compare-and-swap; closing releases the claim
        self.assertEqual(atomic_ops(ir, 'mailbox.formatted'), [('load', (A,))])
        self.assertEqual(atomic_ops(ir, 'mailbox.open_producer'), [('cas', (Q, A))])
        self.assertEqual(atomic_ops(ir, 'mailbox.open_consumer'), [('cas', (Q, A))])
        self.assertEqual(atomic_ops(ir, 'mailbox.close_producer'), [('store', (R,))])
        self.assertEqual(atomic_ops(ir, 'mailbox.close_consumer'), [('store', (R,))])
        # create first looks (ACQUIRE) at the magic and, when there is one, at the two claims, to refuse a mailbox with an open end; then it publishes the geometry with relaxed stores and the magic LAST, with RELEASE
        created = atomic_ops(ir, 'mailbox.create')
        self.assertEqual(created[-1], ('store', (R,)))
        self.assertEqual(created[:-1], [('load', (A,))] * 3 + [('store', (M,))] * 6)

    def rejected(self, body, code, extra=''):
        shutil.copy(STORAGE / 'mailbox.omni', self.dir / 'mailbox.omni')
        path = self.dir / 'neg.omni'
        path.write_text('module t\nimport rt "rt.omni"\nimport mailbox "mailbox.omni"\nstruct Msg { seq u64, a u64 }\n' + extra
                        + 'func main() u32 !{memory.raw,memory.atomic,port.io,cpu.control} {\n' + body + '  return rt.finish(0u32)\n}\n', encoding='utf-8')
        result = self.emit(path)
        self.assertEqual(result.returncode, 2, (body, result.stderr))
        self.assertIn(code, result.stderr, (body, result.stderr))
        self.assertFalse((self.dir / 'prog.ll').exists())

    def test_the_two_ends_are_affine_resources_with_their_own_operations(self):
        open_p = '  let o = mailbox.open_producer(6029312u64)\n  match o { Ok(p) {\n'
        open_c = '  let o = mailbox.open_consumer(6029312u64)\n  match o { Ok(c) {\n'
        end = '  } Err(e) { } }\n'
        for name, body, code in (
            ('a producer end that is never closed', open_p + '    let n u32 = 0u32\n' + end, b'E_RESOURCE_UNCONSUMED'),
            ('a producer end closed twice', open_p + '    let a u32 = mailbox.close_producer(move(p))\n    let b u32 = mailbox.close_producer(move(p))\n' + end, b'E_RESOURCE_MOVED'),
            ('a push after the end was closed', open_p + '    let a u32 = mailbox.close_producer(move(p))\n    let r = mailbox.push<Msg>(borrow_mut(p), Msg { seq: 1u64, a: 2u64 })\n' + end, b'E_RESOURCE_MOVED'),
            ('a consumer end used to push', open_c + '    let r = mailbox.push<Msg>(borrow_mut(c), Msg { seq: 1u64, a: 2u64 })\n    let a u32 = mailbox.close_consumer(move(c))\n' + end, b'E_TYPE'),
            ('a producer end used to pop', open_p + '    let r = mailbox.pop<Msg>(borrow_mut(p))\n    let a u32 = mailbox.close_producer(move(p))\n' + end, b'E_TYPE'),
            ('a push through a shared loan', open_p + '    let r = mailbox.push<Msg>(borrow(p), Msg { seq: 1u64, a: 2u64 })\n    let a u32 = mailbox.close_producer(move(p))\n' + end, b'E_TYPE'),
            ('an end copied', open_p + '    let twin = p\n    let a u32 = mailbox.close_producer(move(twin))\n' + end, b'E_RESOURCE_ACCESS'),
            ('a push whose result is ignored', open_p + '    let r = mailbox.push<Msg>(borrow_mut(p), Msg { seq: 1u64, a: 2u64 })\n    let a u32 = mailbox.close_producer(move(p))\n' + end, b'E_RESULT_UNHANDLED'),
        ):
            with self.subTest(name=name):
                self.rejected(body, code)

    def test_only_plain_data_crosses_the_queue_and_authority_is_not_implied(self):
        holds = ('struct Holds { r Resource<Buffer> }\nfunc tryit(p BorrowMut<mailbox.Producer>, h Holds) u32 !{memory.raw,memory.atomic} {\n'
                 '  let r = mailbox.push<Holds>(p, move(h))\n  match r { Ok(n) { return 1u32 } Err(e) { return e } }\n}\n')
        self.rejected('', b'E_LAYOUT', holds)
        # memory.atomic is not memory.raw: a function that declares only one of them cannot call the mailbox, directly or through another function
        for caps, helper in (('!{memory.atomic}', ''), ('!{memory.raw}', '')):
            with self.subTest(caps=caps):
                shutil.copy(STORAGE / 'mailbox.omni', self.dir / 'mailbox.omni')
                path = self.dir / 'authority.omni'
                path.write_text('module t\nimport mailbox "mailbox.omni"\nstruct Msg { seq u64, a u64 }\n'
                                'func put(p BorrowMut<mailbox.Producer>) u32 ' + caps + ' {\n  let r = mailbox.push<Msg>(p, Msg { seq: 1u64, a: 2u64 })\n  match r { Ok(n) { return 1u32 } Err(e) { return e } }\n}\n'
                                'func outer(p BorrowMut<mailbox.Producer>) u32 ' + caps + ' {\n  return put(p)\n}\nfunc main() u32 { return 0u32 }\n', encoding='utf-8')
                result = self.emit(path)
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertIn(b'E_CAPABILITY', result.stderr)


class TransferTests(X64Harness):
    """Row 13.7: what may cross between CPUs, derived from the structure of the whole type (the layout rule) and never from a name or a mark; and what the hosted task boundary keeps refusing."""

    TYPES = [
        # (type, declarations, accepted, code when refused)
        ('Plain', 'struct Plain { a u64, b u32 }\n', True, None),
        ('Nested', 'struct In { a u32 }\nstruct Nested { i In, b u64 }\n', True, None),
        ('Packed', 'packed struct Packed { a u8, b u32 }\n', True, None),
        ('Ext', 'extern struct Ext { a u32, b u64 }\n', True, None),
        ('heap.Heap', 'import heap "heap.omni"\n', True, None),                              # a sealed resource's inner record is plain data: it travels as bytes and stays inert
        ('Holds', 'struct Holds { r Resource<Buffer> }\n', False, b'E_LAYOUT'),
        ('Deep', 'struct Holds { r Resource<Buffer> }\nstruct Deep { x u32, h Holds }\n', False, b'E_LAYOUT'),
        ('Send', 'struct Send { r Resource<Buffer> }\n', False, b'E_LAYOUT'),                  # a name that sounds like a permission grants nothing
        ('Transferable', 'struct Transferable { r Resource<Buffer>, n u32 }\n', False, b'E_LAYOUT'),
        ('Opt', 'struct Opt { o Option<u32> }\n', False, b'E_LAYOUT'),
        ('Res', 'struct Res { o Result<u32,u32> }\n', False, b'E_LAYOUT'),
        ('Resource<Buffer>', '', False, b'E_LAYOUT'),
        ('Borrow<Buffer>', '', False, b'E_LAYOUT'),
        ('Text', '', False, b'E_LAYOUT'),
        ('EnumC', 'enum EnumC { A, B }\n', False, b'E_LAYOUT'),
        ('u32', '', False, b'E_LAYOUT'),                                                       # a scalar has no record layout: it is wrapped in a one-field record
        ('KeepB', 'struct KeepB { b Borrow<Buffer> }\n', False, b'E_TYPE'),                   # a loan inside a record is refused where the record is declared
    ]

    def stage(self):
        for name in ('mailbox.omni', 'heap.omni', 'ktask.omni'):
            shutil.copy(STORAGE / name, self.dir / name)

    def push_program(self, ty, decls):
        imports = ''.join(l for l in decls.splitlines(True) if l.startswith('import'))
        body = ''.join(l for l in decls.splitlines(True) if not l.startswith('import'))
        owning = ty in ('Holds', 'Deep', 'Send', 'Transferable', 'Res', 'Resource<Buffer>')
        arg = 'move(v)' if owning else 'v'
        path = self.dir / 'transfer.omni'
        path.write_text('module t\nimport rt "rt.omni"\nimport mailbox "mailbox.omni"\n' + imports + body
                        + 'func put(p BorrowMut<mailbox.Producer>, v %s) u32 !{memory.raw,memory.atomic} {\n  let r = mailbox.push<%s>(p, %s)\n  match r { Ok(n) { return 1u32 } Err(e) { return e } }\n}\n' % (ty, ty, arg)
                        + 'func main() u32 { return 0u32 }\n', encoding='utf-8')
        return path

    def test_a_type_crosses_the_queue_when_its_whole_structure_is_plain_and_not_otherwise(self):
        self.stage()
        for ty, decls, accepted, code in self.TYPES:
            with self.subTest(type=ty):
                result = self.emit(self.push_program(ty, decls))
                if accepted:
                    self.assertEqual(result.returncode, 0, result.stderr)
                else:
                    self.assertEqual(result.returncode, 2, result.stderr)
                    self.assertIn(code, result.stderr)

    def test_a_plain_value_is_copied_and_a_value_that_was_sent_can_be_sent_again(self):
        self.stage()
        path = self.dir / 'copy.omni'
        path.write_text('module t\nimport rt "rt.omni"\nimport mailbox "mailbox.omni"\nstruct Msg { a u64, b u32 }\n'
                        'func twice(p BorrowMut<mailbox.Producer>, v Msg) u32 !{memory.raw,memory.atomic} {\n  let a = mailbox.push<Msg>(p, v)\n  match a { Ok(x) { } Err(e) { return e } }\n'
                        '  let b = mailbox.push<Msg>(p, v)\n  match b { Ok(x) { return 1u32 } Err(e) { return e } }\n}\nfunc main() u32 { return 0u32 }\n', encoding='utf-8')
        self.assertEqual(self.emit(path).returncode, 0)

    def test_the_inert_record_of_a_sealed_resource_that_crosses_gives_the_receiver_no_authority(self):
        self.stage()
        path = self.dir / 'inert.omni'
        path.write_text('module t\nimport rt "rt.omni"\nimport mailbox "mailbox.omni"\nimport heap "heap.omni"\nimport ktask "ktask.omni"\n'
                        'func recv(c BorrowMut<mailbox.Consumer>, hp Borrow<heap.Heap>) u32 !{memory.raw,memory.atomic} {\n'
                        '  let m = mailbox.pop<ktask.Task>(c)\n  match m { Ok(t) {\n    let s = ktask.state(hp, borrow(t))\n    match s { Ok(x) { return x } Err(e) { return e } }\n'
                        '  } Err(e) { return e } }\n}\nfunc main() u32 { return 0u32 }\n', encoding='utf-8')
        result = self.emit(path)
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn(b'E_RESOURCE_ACCESS', result.stderr)      # the bytes arrive; the right to use the task does not

    def test_the_hosted_profile_has_no_atomic_authority_at_all(self):
        self.stage()
        path = self.dir / 'hosted.omni'
        path.write_text('module t\nimport mailbox "mailbox.omni"\nstruct Msg { a u64 }\nfunc main() u32 !{memory.raw,memory.atomic} {\n  let c = mailbox.create(6029312u64, 4u64, 8u64)\n'
                        '  match c { Ok(n) { return 1u32 } Err(e) { return e } }\n}\n', encoding='utf-8')
        result = proc(OMNI, 'build', path, '-o', self.dir / 'hosted', '--cache-dir', self.dir / 'cache')
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn(b'E_TARGET_PROFILE', result.stderr)

    def test_the_hosted_task_boundary_keeps_refusing_what_is_not_transferable(self):
        def check(expr, ok):
            path = self.dir / 'task.omni'
            path.write_text('module t\nfunc main() u32 !{memory.write} {\n  task_scope {\n    spawn child = %s;\n    let outcome = join(child);\n    match outcome { Ok(value) { return 1u32; } Err(code) { return code; } }\n  }\n}\n' % expr, encoding='utf-8')
            done = proc(OMNI, 'check', path)
            if ok:
                self.assertEqual(done.returncode, 0, (expr, done.stderr))
            else:
                self.assertEqual(done.returncode, 2, (expr, done.stderr))
                self.assertIn(b'E_TASK_TRANSFER', done.stderr, expr)
        check('40u32 + 2u32', True)
        check('"ab"', True)
        check('7u64', True)
        check('buffer.alloc(8u32)', False)                      # a Result that owns a Resource<Buffer>


if __name__ == '__main__':
    unittest.main()
