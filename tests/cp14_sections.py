#!/usr/bin/env python3
"""CP-14 rows 14.4 - 14.6 (guards, critical sections, retirement): what the profile REALLY forbids inside a critical section, how that propagates, and what retirement and
reentrancy do on two vCPUs.

The restriction of a section is the trait `critical.Section`: its method declares the only capabilities the body may use, the checker enforces that at the impl (E_TRAIT_EFFECT) and
through every call below it (E_CAPABILITY: a function needs the capabilities of the operations it performs and of everything it calls, `omni capabilities` reports both sets).
The tests are organised by capability (every capability of the registry has a stated disposition) and by path (direct, nested, imported, generic, trait)."""
from __future__ import annotations
import json
import re
import shutil
import unittest
from language_0_8_3_alpha8 import ROOT, OMNI, proc, X64Harness

STORAGE = ROOT / 'examples' / 'storage'
CORPUS = ROOT / 'tests' / 'corpus' / 'cp14'

ALLOC = ('    let a Result<Resource<Buffer>,u32> = buffer.alloc(8u32)\n    match a { Ok(b) { return buffer.len(borrow(b)) } Err(code) { return code } }\n')
READ = ('    let a Result<Resource<Buffer>,u32> = buffer.alloc(8u32)\n    match a { Ok(b) {\n      let rd = buffer.read_u32le(borrow(b), 0u32)\n'
        '      match rd { Ok(v) { return v } Err(c) { return c } }\n    } Err(code) { return code } }\n')

# capability -> (capabilities the operation needs, the statements that perform it and return a u32), or None when no operation of the language needs the capability
OPERATIONS = {
    'memory.raw': ('memory.raw', '    return raw.load32(4096u64)\n'),
    'memory.atomic': ('memory.atomic', '    return atomic.load32(4096u64, 4u32)\n'),
    'io.print': ('io.print', '    print(1u32)\n    return 0u32\n'),
    'fs.read': ('fs.read', '    let r = file.read_text("a")\n    match r { Ok(v) { return 0u32 } Err(c) { return c } }\n'),
    'fs.write': ('fs.write', '    let r = file.write_text("a", "b")\n    match r { Ok(v) { return 0u32 } Err(c) { return c } }\n'),
    'memory.write': ('memory.write', ALLOC),
    'memory.read': ('memory.write,memory.read', READ),                   # a buffer is only reachable by allocating one
    'memory.tls': ('memory.tls', '    return tls.load32(0u64)\n'),
    'memory.pcpu': ('memory.pcpu', '    return pcpu.load32(0u64)\n'),
    'port.io': ('port.io', '    return port.in8(96u32)\n'),
    'cpu.control': ('cpu.control', '    return cpu.cpuid(1u32, 1u32)\n'),
    'cpu.syscall': ('cpu.syscall', '    let v u64 = cpu.trap3(40u32, 0u64, 0u64, 0u64)\n    return 0u32\n'),
    'net.connect': ('net.connect', '    let o = host.tcp("h", bytes.from_text("x"), 1u32, 1u32)\n    match o { Ok(b) { return 0u32 } Err(c) { return c } }\n'),
    'process.spawn': ('process.spawn', '    let o = host.process("p", bytes.from_text("x"), 1u32, 1u32)\n    match o { Ok(b) { return 0u32 } Err(c) { return c } }\n'),
    'ffi.call': ('ffi.call', '    let o = host.ffi("l", bytes.from_text("x"), 1u32)\n    match o { Ok(b) { return 0u32 } Err(c) { return c } }\n'),
}
# Disposition of EVERY capability of the registry for the body of a critical section.
ALLOWED = {'memory.raw': 'plain cells: the work a lock exists for', 'memory.atomic': 'atomics: the lock and its data'}
FORBIDDEN = {
    'io.print': 'output can block on a device and is hosted I/O',
    'fs.read': 'host file system', 'fs.write': 'host file system',
    'data.read': 'host data store (no operation of the language needs it yet)', 'data.write': 'host data store (no operation of the language needs it yet)',
    'memory.read': 'host buffers and the allocator behind them (can block, can fail late)',
    'memory.write': 'allocation: the host allocator is not available inside a section',
    'memory.tls': 'thread-local state belongs to a context that a section must not leave',
    'memory.pcpu': 'per-CPU state is only valid while the context stays; the section runner owns that promise',
    'port.io': 'device access can wait on hardware', 'cpu.control': 'halt, interrupt enable, context switch, anything that can leave the CPU',
    'cpu.syscall': 'a gate into another privilege level', 'net.connect': 'network', 'net.listen': 'network (no operation of the language needs it yet)',
    'process.spawn': 'process creation', 'ffi.call': 'foreign code has no effect contract', 'external.egress': 'leaves the machine (no operation of the language needs it yet)',
    'secret.use': 'secrets are not for critical sections (no operation of the language needs it yet)',
}
NO_OPERATION = sorted(set(ALLOWED) | set(FORBIDDEN) - set(OPERATIONS))


def registry(testcase):
    done = proc(OMNI, 'capability', 'registry')
    testcase.assertEqual(done.returncode, 0, done.stderr)
    return {c['id'] for c in json.loads(done.stdout.decode())['capabilities']}


class SectionContractTests(X64Harness):
    """Rows 14.4 / 14.5: the restriction of a section, capability by capability and path by path."""

    HEAD = 'module t\nimport rt "rt.omni"\nimport critical "critical.omni"\n'
    MAIN = 'func main() u32 !{memory.raw,memory.atomic,port.io,cpu.control} {\n  let r u32 = critical.irq_off<S>(0u64)\n  return rt.finish(r)\n}\n'

    def stage(self):
        shutil.copy(STORAGE / 'critical.omni', self.dir / 'critical.omni')

    def program(self, caps, body, decls='', imports=''):
        path = self.dir / 'section.omni'
        path.write_text(self.HEAD + imports + decls + 'struct S { a u32 }\nimpl critical.Section for S {\n  func run(arg u64) u32 %s{\n%s  }\n}\n' % (('!{%s} ' % caps) if caps else '', body) + self.MAIN, encoding='utf-8')
        return path

    def check(self, path):
        return proc(OMNI, 'check', path)

    def paths(self, caps, op):
        """The ways a section body can reach the operation `op` (which needs `caps`)."""
        low = 'func low() u32 !{%s} {\n%s}\n' % (caps, op)
        return {
            'in the body itself': ('', op, ''),
            'direct call': (low, '    return low()\n', ''),
            'nested three deep': (low + 'func mid() u32 !{%s} {\n  return low()\n}\nfunc top() u32 !{%s} {\n  return mid()\n}\n' % (caps, caps), '    return top()\n', ''),
            'generic function': ('func gen<T>(x u32) u32 !{%s} {\n%s}\n' % (caps, op), '    return gen<S>(1u32)\n', ''),
            'imported module': ('', '    return lowmod.low()\n', 'import lowmod "lowmod.omni"\n'),
            'another trait': ('trait Other {\n  func go(x u32) u32 !{%s}\n}\nstruct T2 { b u32 }\nimpl Other for T2 {\n  func go(x u32) u32 !{%s} {\n%s  }\n}\n' % (caps, caps, op), '    return Other.go<T2>(1u32)\n', ''),
        }

    def test_every_capability_of_the_registry_has_a_disposition(self):
        self.assertEqual(registry(self), set(ALLOWED) | set(FORBIDDEN))      # a capability added later fails here until someone decides
        self.assertEqual(set(OPERATIONS) - set(ALLOWED) - set(FORBIDDEN), set())

    def test_a_section_that_declares_a_forbidden_capability_is_refused_at_its_impl(self):
        self.stage()
        for cap in FORBIDDEN:
            with self.subTest(capability=cap):
                done = self.check(self.program(cap, '    return 0u32\n'))
                self.assertEqual(done.returncode, 2, (cap, done.stderr))
                self.assertIn(b'E_TRAIT_EFFECT', done.stderr, (cap, done.stderr))

    def test_a_section_that_declares_the_allowed_capabilities_is_accepted_and_instantiated(self):
        self.stage()
        for caps in ('memory.raw', 'memory.atomic', 'memory.raw,memory.atomic', ''):
            with self.subTest(capabilities=caps):
                path = self.program(caps, '    return 0u32\n')
                self.assertEqual(self.check(path).returncode, 0)
                emitted = self.emit(path)
                self.assertEqual(emitted.returncode, 0, emitted.stderr)

    def test_the_operation_of_a_forbidden_capability_is_refused_whatever_the_path(self):
        self.stage()
        for cap in FORBIDDEN:
            if cap not in OPERATIONS:
                continue
            caps, op = OPERATIONS[cap]
            (self.dir / 'lowmod.omni').write_text('module lowmod\npub func low() u32 !{%s} {\n%s}\n' % (caps, op), encoding='utf-8')
            for label, (decls, body, imports) in self.paths(caps, op).items():
                with self.subTest(capability=cap, path=label):
                    done = self.check(self.program('memory.raw,memory.atomic', body, decls, imports))
                    self.assertEqual(done.returncode, 2, (cap, label, done.stderr))
                    self.assertIn(b'E_CAPABILITY', done.stderr, (cap, label, done.stderr))

    def test_the_same_paths_compile_when_what_they_reach_is_allowed(self):
        self.stage()
        for cap in ALLOWED:
            caps, op = OPERATIONS[cap]
            (self.dir / 'lowmod.omni').write_text('module lowmod\npub func low() u32 !{%s} {\n%s}\n' % (caps, op), encoding='utf-8')
            for label, (decls, body, imports) in self.paths(caps, op).items():
                with self.subTest(capability=cap, path=label):
                    path = self.program('memory.raw,memory.atomic', body, decls, imports)
                    self.assertEqual(self.check(path).returncode, 0, (cap, label))
                    self.assertEqual(self.emit(path).returncode, 0, (cap, label))

    def test_what_a_section_requires_is_reported_and_stays_inside_the_trait(self):
        self.stage()
        path = self.program('memory.raw,memory.atomic', '    let a u32 = raw.load32(4096u64)\n    return atomic.fetch_add32(4104u64, a, 4u32)\n')
        done = proc(OMNI, 'capabilities', path)
        self.assertEqual(done.returncode, 0, done.stderr)
        report = {f['function']: f for f in json.loads(done.stdout)['functions']}
        run = [f for k, f in report.items() if k.startswith('t.run__impl')]
        self.assertTrue(run, sorted(report))
        for f in run:
            self.assertLessEqual(set(f['required']), set(ALLOWED), f)

    def test_a_registered_callable_fired_inside_a_section_is_held_to_the_effects_of_its_handler(self):
        # `fire` needs memory.raw and memory.atomic and the Handler trait limits `call` to memory.raw, so a callback fired inside a section brings in nothing the section may not use; a handler that tries is refused where it is written
        self.stage()
        shutil.copy(ROOT / 'tests' / 'x64' / 'cbreg.omni', self.dir / 'cbreg.omni')
        shutil.copy(ROOT / 'tests' / 'x64' / 'epoch.omni', self.dir / 'epoch.omni')
        imports = 'import cbreg "cbreg.omni"\n'
        handler = ('struct H { k u32 }\nimpl cbreg.Handler for H {\n  func call(h H, x u32) u32 !{%s} {\n%s    return h.k + x\n  }\n'
                   '  func dispose(h H) u32 !{memory.atomic} {\n    return 0u32\n  }\n}\n')
        fired = '    let r = cbreg.fire<H>(4096u64, arg, 1u32)\n    match r { Ok(v) { return v } Err(c) { return c } }\n'
        path = self.program('memory.raw,memory.atomic', fired, handler % ('memory.raw', ''), imports)
        done = self.check(path)
        self.assertEqual(done.returncode, 0, done.stderr)
        emitted = self.emit(path)
        self.assertEqual(emitted.returncode, 0, emitted.stderr)
        report = {f['function']: f for f in json.loads(proc(OMNI, 'capabilities', path).stdout)['functions']}
        for f in [f for k, f in report.items() if k.startswith('t.run__impl')]:
            self.assertLessEqual(set(f['required']), set(ALLOWED), f)           # what the section requires, with the callback inside, stays inside the trait
        for cap, op in (('io.print', '    print(x)\n'), ('port.io', '    let p u32 = port.out8(1016u32, 1u32)\n'), ('cpu.control', '    let c u32 = cpu.cli()\n')):
            with self.subTest(handler_capability=cap):
                done = self.check(self.program('memory.raw,memory.atomic', fired, handler % ('memory.raw,' + cap, op), imports))
                self.assertEqual(done.returncode, 2, (cap, done.stderr))
                self.assertIn(b'E_TRAIT_EFFECT', done.stderr, (cap, done.stderr))

    def test_a_section_cannot_open_another_one_nor_wait_for_a_grace_period(self):
        self.stage()
        shutil.copy(ROOT / 'tests' / 'x64' / 'epoch.omni', self.dir / 'epoch.omni')
        # nesting an interrupt-off section needs cpu.control
        done = self.check(self.program('memory.raw,memory.atomic', '    return critical.irq_off<S>(arg)\n'))
        self.assertEqual(done.returncode, 2, done.stderr)
        self.assertIn(b'E_CAPABILITY', done.stderr)
        # waiting for readers to leave (epoch.wait) needs port.io and cpu.control: a section cannot retire anything
        done = self.check(self.program('memory.raw,memory.atomic', '    return epoch.wait(arg, 1u32, 10u32)\n', imports='import epoch "epoch.omni"\n'))
        self.assertEqual(done.returncode, 2, done.stderr)
        self.assertIn(b'E_CAPABILITY', done.stderr)
        # reading and publishing an epoch (enter, exit, advance) are atomics only: a section may take part in the protocol as a reader
        ok = self.program('memory.raw,memory.atomic', '    return epoch.advance(arg)\n', imports='import epoch "epoch.omni"\n')
        self.assertEqual(self.check(ok).returncode, 0)


SINGLE_TRANSCRIPT = [
    '1', '1001', '1', '0', '1',                # interrupts enabled on entry: the section runs, interrupts are enabled again, the lock is free, the body ran once
    '0', '1002', '0',                          # disabled on entry: still disabled afterwards (a runner never enables what it did not disable)
    '3', '1',                                  # irq_off from enabled: result, enabled again
    '4', '0',                                  # irq_off from disabled: result, still disabled
    '17', '1', '1', '4',                       # a held lock: 17, interrupts as they were, the foreign lock untouched, the body never ran
]


class SectionRuntimeTests(X64Harness):
    """Rows 14.4 / 14.6, the runners of critical.omni in the image: interrupt state, lock, two CPUs, and the order of the instructions."""

    def stage(self, program, *extra):
        shutil.copy(STORAGE / 'critical.omni', self.dir / 'critical.omni')
        shutil.copy(CORPUS / program, self.dir / program)
        return self.dir / program

    def test_the_runners_restore_the_interrupt_state_they_found_and_report_a_lock_they_cannot_take(self):
        rc, serial = self.boot(self.build(self.stage('section_single.omni')))
        self.assertEqual(serial.split('\n')[:-1], SINGLE_TRANSCRIPT, serial)
        self.assertEqual(rc, 1)

    def test_two_cpus_through_the_locked_runner_never_lose_an_update_and_without_it_they_do(self):
        elf = self.build(self.stage('section_smp.omni'), ap_main=True)
        for attempt in range(2):
            rc, serial = self.boot(elf, smp=2)
            # locked total exact, the control loses updates, no CPU failed to take the lock, the lock is free at the end
            self.assertEqual((rc, serial.split('\n')[:-1]), (1, ['60000', '1', '0', '0']), (attempt, serial))

    def test_interrupts_go_off_before_the_lock_is_taken_and_come_back_after_it_is_given_back(self):
        self.build(self.stage('section_single.omni'))
        ir = (self.dir / 'prog.ll').read_text(encoding='utf-8')
        m = re.search(r'define [^\n@]*@omni\.fn\.critical\.locked[^\n]*\{\n(.*?)^\}', ir, re.S | re.M)
        self.assertTrue(m)
        body = m.group(1)
        at = lambda needle: [m2.start() for m2 in re.finditer(re.escape(needle), body)]
        self.assertEqual(len(at('asm sideeffect "cli"')), 1)
        self.assertEqual(len(at('asm sideeffect "pushfq')), 1)
        cas = at('cmpxchg volatile')
        self.assertEqual(len(cas), 1)
        self.assertLess(at('asm sideeffect "pushfq')[0], at('asm sideeffect "cli"')[0])      # the state is read before it is changed
        self.assertLess(at('asm sideeffect "cli"')[0], cas[0])                                # interrupts off, then the lock
        sti = at('asm sideeffect "sti"')
        self.assertEqual(len(sti), 2)                                                          # restored on the failure path and on the success path
        release = [m2.start() for m2 in re.finditer(r'store atomic volatile i32 0, [^\n]* release', body)]
        self.assertEqual(len(release), 1)
        self.assertLess(cas[0], release[0])
        self.assertLess(release[0], sti[1])                                                    # the lock is given back before interrupts are enabled again
        self.assertRegex(body, r'cmpxchg volatile .* acq_rel acquire')                        # taking the lock: acq_rel, failure acquire

    def test_the_lock_loop_leaves_as_soon_as_the_lock_is_taken_and_does_not_keep_interrupts_off_for_the_remaining_tries(self):
        # With the lock held, another compare-and-swap of the same cell fails and changes nothing, so a loop that kept going would leave the state alone but would keep this CPU with interrupts off for
        # up to `attempts` more tries: the latency of the section would depend on `attempts`. That is a difference of behaviour that no outcome shows and a timing test must not be used to see, so the
        # exit is checked in the code: the path that records the lock as taken goes straight to the block where the loop ends (the one that reads that record), not back into the loop.
        self.build(self.stage('section_single.omni'))
        ir = (self.dir / 'prog.ll').read_text(encoding='utf-8')
        m = re.search(r'define [^\n@]*@omni\.fn\.critical\.locked[^\n]*\{\n(.*?)^\}', ir, re.S | re.M)
        self.assertTrue(m)
        body = m.group(1)
        tick = r'(?:\s+call void @omni_tick\(\)\n)*'
        taken = re.search(r'store i1 true, ptr (%%v\d+)\n%s\s+br label %%(b\d+)\n' % tick, body)
        self.assertTrue(taken, 'the path that takes the lock must end in a direct branch')
        end = re.search(r'^%s:\n%s\s+(%%t\d+) = load i1, ptr %s\n%s\s+%%t\d+ = icmp eq i1 \1, false' % (taken.group(2), tick, re.escape(taken.group(1)), tick), body, re.M)
        self.assertTrue(end, 'that branch must go to the end of the loop, where the record of the lock is read')
        header = re.search(r'br i1 %%t\d+, label %%b\d+, label %%%s\n' % taken.group(2), body)
        self.assertTrue(header, 'the loop condition leaves to the same block')


class InterruptSectionTests(X64Harness):
    """Row 14.4, preemption: while a section runs interrupts are off on this CPU, so nothing preempts it (and with no context switch available inside, the context cannot migrate)."""

    IRQ = ('--exception-handler', 't.on_exception', '--exception-resume', '--isr-count', '33')

    def test_a_timer_interrupt_never_lands_inside_a_section_and_does_land_in_the_same_code_outside_one(self):
        shutil.copy(STORAGE / 'critical.omni', self.dir / 'critical.omni')
        shutil.copy(CORPUS / 'section_irq.omni', self.dir / 'section_irq.omni')
        rc, serial = self.boot(self.build(self.dir / 'section_irq.omni', emit_args=self.IRQ))
        # [the bare body is interrupted] [irq_off: 0 interrupts] [locked: 0 interrupts] [the bare body is interrupted again]
        self.assertEqual((rc, serial.split('\n')[:-1]), (1, ['1', '0', '0', '1']), serial)

    def test_irq_off_disables_interrupts_before_the_body_and_enables_them_only_if_they_were_enabled(self):
        shutil.copy(STORAGE / 'critical.omni', self.dir / 'critical.omni')
        shutil.copy(CORPUS / 'section_single.omni', self.dir / 'section_single.omni')
        self.build(self.dir / 'section_single.omni')
        ir = (self.dir / 'prog.ll').read_text(encoding='utf-8')
        body = re.search(r'define [^\n@]*@omni\.fn\.critical\.irq_off[^\n]*\{\n(.*?)^\}', ir, re.S | re.M).group(1)
        order = [m.group(0) for m in re.finditer(r'asm sideeffect "(pushfq|cli|sti)|call i32 @omni\.fn\.t\.run__impl', body)]
        self.assertEqual([o.split('"')[-1] if '"' in o else 'run' for o in order], ['pushfq', 'cli', 'run', 'sti'], order)


EPOCH_HORIZON = ['1', '4294967295', '4294967295', '0', '0', '4294967295', '0', '0', '0', '1', '2', '2']


class EpochHorizonTests(X64Harness):
    """Adenda 009A EPOCH-01: the epoch counter does not wrap, and a refused advance changes nothing."""

    def run_variant(self, number):
        shutil.copy(CORPUS / 'epoch_horizon.omni', self.dir / 'epoch_horizon.omni')
        text = (self.dir / 'epoch_horizon.omni').read_text(encoding='utf-8')
        old = 'func variant() u32 { return 1u32 }'
        self.assertIn(old, text)
        path = self.dir / 'horizon.omni'
        path.write_text(text.replace(old, 'func variant() u32 { return %du32 }' % number), encoding='utf-8')
        rc, serial = self.boot(self.build(path))
        return rc, serial.split('\n')[:-1]

    def test_the_last_allowed_advance_then_the_refusals_leave_the_cell_as_it_was(self):
        rc, lines = self.run_variant(2)
        self.assertEqual((rc, lines), (1, EPOCH_HORIZON + ['4294967295', '1']))     # MAX-1 -> MAX allowed; at MAX and at 0 advance answers 0 and the cell is unchanged; 1 -> 2

    def test_a_reader_active_at_the_last_epochs_is_waited_for_and_never_taken_for_quiescent(self):
        rc, lines = self.run_variant(1)
        self.assertEqual((rc, lines), ((95 << 1) | 1, EPOCH_HORIZON + ['4294967294', '4294967295']))    # published MAX-1 < target MAX: bounded deadlock, not a retirement

    def test_an_exhausted_epoch_ends_the_guest_instead_of_calling_every_reader_quiescent(self):
        rc, lines = self.run_variant(3)
        self.assertEqual((rc, lines), ((96 << 1) | 1, EPOCH_HORIZON + ['0', '4294967295', '4294967295']))   # advance answered 0, the cell is still MAX, the reader's slot is still MAX

    def test_a_cell_wrapped_from_outside_is_refused_too(self):
        rc, lines = self.run_variant(4)
        self.assertEqual((rc, lines), ((96 << 1) | 1, EPOCH_HORIZON + ['0', '0', '0']))       # the wrapped cell (0), the slot a reader then publishes (0, "quiescent"), advance 0: exit 96

    def test_a_retirement_checks_the_epoch_before_it_unpublishes_anything(self):
        # the exit status cannot tell: wait ends the guest with 96 for a refused advance anyway. What the early check protects is that nothing was touched, which shows in the order
        for program, name in (('cb_generation.omni', 'retire'), ('cb_inflight.omni', 'retire_all')):
            with self.subTest(function=name):
                shutil.copy(CORPUS / program, self.dir / program)
                self.assertEqual(self.emit(self.dir / program).returncode, 0)
                ir = (self.dir / 'prog.ll').read_text(encoding='utf-8')
                m = re.search(r'define [^\n@]*@omni\.fn\.cbreg\.%s__g[^\n]*\{\n(.*?)^\}' % name, ir, re.S | re.M)
                self.assertTrue(m, name)
                body = m.group(1)
                first_store = body.find('store atomic volatile')
                check = body.find('omni.fn.epoch.can_advance')
                self.assertGreaterEqual(check, 0)
                self.assertLess(check, first_store)              # refused BEFORE the slot is unpublished, the epoch advanced or the environment disposed
                self.assertLess(check, body.find('omni.fn.epoch.advance'))
                # and the refusal is the answer 0 of can_advance, ending the guest with 96 before the first unpublishing store: a condition that can never hold leaves the same exit status (wait ends with 96 too) but unpublishes first
                answer = re.search(r'(%t\d+) = call i32 @omni\.fn\.epoch\.can_advance\([^)]*\)', body)
                self.assertTrue(answer)
                refusal = re.search(r'icmp eq i32 %s, 0\n' % re.escape(answer.group(1)), body)
                self.assertTrue(refusal, 'the refusal must compare the answer of can_advance with 0')
                ends = body.find('call i32 @omni.fn.rt.finish(i32 96)', refusal.end())
                self.assertGreaterEqual(ends, 0)
                self.assertLess(ends, first_store)


class CallbackGenerationTests(X64Harness):
    """Adenda 009A CBREG-01: a generation is never reused; the horizon is a visible limit of the slot."""

    def run_variant(self, number):
        shutil.copy(CORPUS / 'cb_generation.omni', self.dir / 'cb_generation.omni')
        text = (self.dir / 'cb_generation.omni').read_text(encoding='utf-8')
        old = 'func variant() u32 { return 1u32 }'
        self.assertIn(old, text)
        path = self.dir / 'generation.omni'
        path.write_text(text.replace(old, 'func variant() u32 { return %du32 }' % number), encoding='utf-8')
        rc, serial = self.boot(self.build(path))
        return rc, serial.split('\n')[:-1]

    def test_a_token_from_before_the_horizon_is_refused_and_the_slot_is_then_closed_not_wrapped(self):
        rc, lines = self.run_variant(1)
        # A (16777214) works; B (16777215) reuses the slot and A's token is refused as stale (1002); B works and retires; both tokens are refused afterwards (1001);
        # each environment was disposed once; the slot has no generation left (0) and the next registration ends the guest with exit value 93 instead of wrapping to 1
        self.assertEqual((rc, lines), ((93 << 1) | 1, ['16777214', '101', '16777215', '1002', '201', '1001', '1001', '2', '0']))

    def test_the_token_of_the_first_occupation_is_refused_after_its_retirement(self):
        rc, lines = self.run_variant(3)
        self.assertEqual((rc, lines), (1, ['1', '1001']))

    def test_a_retirement_with_an_exhausted_epoch_is_refused_before_it_touches_the_registration(self):
        for variant in (2, 4):                                    # retire, and retire_all (the one that waits for every reader)
            rc, lines = self.run_variant(variant)
            self.assertEqual((rc, lines), ((96 << 1) | 1, ['101']), variant)


class Quiescence3Tests(X64Harness):
    """Row 14.6: a grace period proves exactly what it scanned. Three vCPUs: one writer, two readers."""

    def run_mode(self, mode):
        shutil.copy(CORPUS / 'epoch3_smp.omni', self.dir / 'epoch3_smp.omni')
        text = (self.dir / 'epoch3_smp.omni').read_text(encoding='utf-8')
        old = 'func mode() u32 { return 0u32 }'
        self.assertIn(old, text)
        (self.dir / 'epoch3.omni').write_text(text.replace(old, 'func mode() u32 { return %du32 }' % mode), encoding='utf-8')
        rc, serial = self.boot(self.build(self.dir / 'epoch3.omni', ap_main=True), smp=3)
        self.assertEqual(rc, 1, serial)
        return [int(x) for x in serial.split('\n')[:-1]]

    def test_a_wait_over_every_reader_slot_never_lets_either_reader_see_a_retired_buffer(self):
        for attempt in range(2):
            self.assertEqual(self.run_mode(0), [0, 0, 1, 1], attempt)         # no poison seen by CPU 1 or CPU 2; both served more than 1000 sections

    def test_a_wait_over_a_partial_list_protects_only_the_readers_it_scanned(self):
        bad1, bad2, served1, served2 = self.run_mode(1)
        self.assertEqual(bad1, 0)                                             # the reader that was waited for is safe
        self.assertGreater(bad2, 0)                                           # the one that was not, sees the poisoned buffer
        self.assertEqual((served1, served2), (1, 1))


class CallbackRetirementTests(X64Harness):
    """Row 14.6: retirement of a callable with calls in flight on two reader CPUs, stale tokens, and what a callable cannot do."""

    EXPECTED = ['0', '0', '1', '1', '1', '1500', '0']     # no reader saw poison; both served >100 calls; retirements overlapped an in-flight call; 1500 environments disposed exactly once; slot idle

    def stage(self, mutate=None):
        shutil.copy(CORPUS / 'cb_inflight.omni', self.dir / 'cb_inflight.omni')
        if mutate:
            library = (self.dir / 'cbreg.omni').read_text(encoding='utf-8')
            needle, replacement = mutate
            self.assertIn(needle, library)
            (self.dir / 'cbreg.omni').write_text(library.replace(needle, replacement), encoding='utf-8')
        return self.build(self.dir / 'cb_inflight.omni', ap_main=True)

    def test_a_call_in_flight_at_the_moment_of_retirement_finishes_on_a_live_environment(self):
        elf = self.stage()
        for attempt in range(2):
            rc, serial = self.boot(elf, smp=3)
            self.assertEqual((rc, serial.split('\n')[:-1]), (1, self.EXPECTED), (attempt, serial))

    def detected(self, rc, serial):
        """The control is detected when the guest reports bad calls or dies: a call that outlives its environment dereferences the poisoned cell address and faults (the image has no IDT,
        so a fault is a triple fault and QEMU exits without the debug-exit status)."""
        lines = [int(x) for x in serial.split('\n')[:-1]]
        if rc != 1 or len(lines) < 2:
            return True, (0, 0)
        return (lines[0] + lines[1]) > 0, (lines[0], lines[1])

    def test_without_the_wait_a_call_in_flight_reads_the_poisoned_environment(self):
        elf = self.stage(('  let w u32 = epoch.wait_all(first, count, stride, e, attempts)\n', ''))
        for attempt in range(3):
            rc, serial = self.boot(elf, smp=3)
            self.assertTrue(self.detected(rc, serial)[0], (attempt, rc, serial))

    def test_a_wait_that_leaves_one_reader_out_lets_that_reader_read_the_poisoned_environment(self):
        elf = self.stage(('epoch.wait_all(first, count, stride, e, attempts)', 'epoch.wait(first + stride, e, attempts)'))
        for attempt in range(3):
            rc, serial = self.boot(elf, smp=3)
            hit, bad = self.detected(rc, serial)
            self.assertTrue(hit, (attempt, rc, serial))
            if rc == 1:
                self.assertEqual(bad[0], 0, (attempt, serial))      # the reader that was waited for never saw poison

    def test_a_callable_cannot_fire_register_or_retire_anything(self):
        shutil.copy(ROOT / 'tests' / 'x64' / 'cbreg.omni', self.dir / 'cbreg.omni')
        head = 'module t\nimport rt "rt.omni"\nimport epoch "epoch.omni"\nimport cbreg "cbreg.omni"\nstruct Inner { a u32 }\nimpl cbreg.Handler for Inner {\n  func call(h Inner, x u32) u32 !{memory.raw} { return x }\n  func dispose(h Inner) u32 !{memory.atomic} { return 0u32 }\n}\nstruct Outer { b u32 }\n'
        cases = {
            'fire inside a call (it reads the slot with atomics)': ('  func call(h Outer, x u32) u32 !{memory.raw} {\n    let r Result<u32,u32> = cbreg.fire<Inner>(4096u64, 0u64, x)\n    match r { Ok(v) { return v } Err(c) { return c } }\n  }\n', b'E_CAPABILITY'),
            'fire inside a call, with the atomics declared': ('  func call(h Outer, x u32) u32 !{memory.raw,memory.atomic} {\n    let r Result<u32,u32> = cbreg.fire<Inner>(4096u64, 0u64, x)\n    match r { Ok(v) { return v } Err(c) { return c } }\n  }\n', b'E_TRAIT_EFFECT'),
            'retire inside a call': ('  func call(h Outer, x u32) u32 !{memory.raw,memory.atomic,port.io,cpu.control} {\n    return epoch.wait(4096u64, 1u32, 1u32)\n  }\n', b'E_TRAIT_EFFECT'),
        }
        for label, (call, code) in cases.items():
            with self.subTest(case=label):
                path = self.dir / 'reentrant.omni'
                path.write_text(head + 'impl cbreg.Handler for Outer {\n' + call + '  func dispose(h Outer) u32 !{memory.atomic} { return 0u32 }\n}\nfunc main() u32 { return 0u32 }\n', encoding='utf-8')
                result = self.emit(path)
                self.assertEqual(result.returncode, 2, (label, result.stderr))
                self.assertIn(code, result.stderr, (label, result.stderr))


class InterruptPriorityTests(X64Harness):
    """Row 14.6: an interrupt is a higher priority context on the same CPU. A handler that retires against the reader it interrupted can never succeed, and says so."""

    IRQ = ('--exception-handler', 't.on_exception', '--exception-resume', '--isr-count', '33')

    def variant(self, mode):
        text = (CORPUS / 'irq_retire.omni').read_text(encoding='utf-8')
        old = 'func mode() u32 { return 0u32 }'
        self.assertIn(old, text)
        path = self.dir / ('irq_retire_%d.omni' % mode)
        path.write_text(text.replace(old, 'func mode() u32 { return %du32 }' % mode), encoding='utf-8')
        return path

    def test_a_handler_that_retires_against_the_reader_it_interrupted_is_reported_as_a_deadlock(self):
        rc, serial = self.boot(self.build(self.variant(0), emit_args=self.IRQ))
        self.assertEqual(rc, (95 << 1) | 1, (rc, serial))     # exit value 95: bounded wait, never an endless spin and never a reclaim under the reader
        self.assertEqual(serial, '')                           # the reader's section never finished: nothing was printed after it

    def test_the_same_retirement_succeeds_when_the_interrupted_code_is_not_a_reader(self):
        rc, serial = self.boot(self.build(self.variant(1), emit_args=self.IRQ))
        self.assertEqual((rc, serial.split('\n')[:-1]), (1, ['1', '1']), serial)


if __name__ == '__main__':
    unittest.main()
