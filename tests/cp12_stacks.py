#!/usr/bin/env python3
"""CP-12 rows 12.5 and 12.6 (spec/FPU_SSE_STATE_CANDIDATE.md section 10): stack limits and what a stack holds.

12.5  A thread stack ends at a GUARD PAGE: a 4 KiB page of the 2 MiB mapping that the program splits with a page table written in Omni and leaves not present. A thread whose stack is
      exhausted touches it; the fault is taken on its own stack, which cannot hold the exception frame, so the gate uses a separate stack (IST 1 of a TSS the program builds in Omni). The handler
      is ordinary Omni code: it recognises the guard from CR2, and RECOVERS by pointing the (validated) frame at the thread trampoline on a fresh stack. The control maps the guard page: the same
      overflow then goes unnoticed - which is what the guard is for.
12.6  Sentinels. The callee-saved registers a cooperative switch must preserve and the unused part of a stack are checked: a thread fills rbx/rbp/r12-r15-like state through the compiler's
      own code path and the stack below its deepest use keeps the pattern painted before the thread ran, across switches and across timer interrupts (see StackSentinelTests).
"""
from __future__ import annotations
import unittest
from language_0_8_3_alpha8 import X64Harness

GDT = ('func gdt_install() u32 !{memory.raw,cpu.control} {\n'
       '  let n0 u32 = raw.store64(5570560u64, 0u64)\n'
       '  let n1 u32 = raw.store64(5570568u64, bit.or(bit.shl(11508224u64, 32u32), 65535u64))\n'
       '  let n2 u32 = raw.store64(5570576u64, bit.or(bit.shl(13603328u64, 32u32), 65535u64))\n'
       '  let tss_low u64 = bit.or(bit.or(103u64, bit.shl(86u64, 32u32)), bit.shl(137u64, 40u32))\n'
       '  let n5 u32 = raw.store64(5570600u64, tss_low)\n'
       '  let n6 u32 = raw.store64(5570608u64, 0u64)\n'
       '  let rsp0 u32 = raw.store64(5636096u64 + 4u64, 5177344u64)\n'
       '  let ist1 u32 = raw.store64(5636096u64 + 36u64, 5177344u64)\n'                      # TSS.IST1 = 0x4F0000
       '  let iopb u32 = raw.store32(5636096u64 + 100u64, 6815744u32)\n'
       '  let gdtr u32 = raw.store64(5570816u64, 55u64 + 5570560u64 * 65536u64)\n'
       '  let lg u32 = cpu.lgdt(5570816u32)\n  return cpu.ltr(40u32)\n}\n')

GATES = ('func gate(v u32, ist u64) u32 !{memory.raw} {\n'
         '  let off u64 = 2162688u64 + u64(v) * 16u64\n'
         '  let low u64 = bit.or(bit.or(bit.and(off, 65535u64), bit.shl(8u64, 16u32)), bit.shl(ist, 32u32))\n'
         '  let attr u64 = bit.shl(142u64, 40u32)\n'
         '  let high u64 = bit.shl(bit.and(bit.shr(off, 16u32), 65535u64), 48u32)\n'
         '  let a u32 = raw.store64(5439488u64 + u64(v) * 16u64, bit.or(bit.or(low, attr), high))\n'
         '  return raw.store64(5439488u64 + u64(v) * 16u64 + 8u64, bit.shr(off, 32u32))\n}\n'
         'func idt_install() u32 !{memory.raw,cpu.control} {\n'
         '  for v in 0u32..32u32 {\n    let g u32 = gate(v, 0u64)\n  }\n'
         '  let pf u32 = gate(14u32, 1u64)\n'
         '  let limit u32 = raw.store64(5374208u64, 32u64 * 16u64 - 1u64 + 5439488u64 * 65536u64)\n'
         '  return cpu.lidt(5374208u32)\n}\n')


def guard_fixture(guard_present: bool) -> str:
    entry = 6815747 if guard_present else 0       # the page table entry of the guard page: 0x680000 | present | writable, or not present
    return ('module t\nimport rt "rt.omni"\n' + GDT + GATES +
            # guard page = 0x680000..0x680FFF; the thread's stack starts 0x10 above it (0x681010) so its first call already needs the guard; the fresh stack top is 0x6C0000
            'func on_exception(frame u64) u32 !{io.print,memory.raw,port.io,cpu.control} {\n'
            '  let v u64 = raw.load64(frame)\n'
            '  if v == 14u64 {\n'
            '    let cr2 u64 = cpu.read_cr64(2u32)\n'
            '    let l1 u32 = raw.store64(5373952u64, cr2)\n    let l2 u32 = raw.store64(5373960u64, raw.load64(frame + 8u64))\n    let l3 u32 = raw.store64(5373968u64, frame)\n'
            '    if cr2 >= 6815744u64 && cr2 < 6819840u64 {\n'
            '      let m u32 = raw.store32(5374016u64, 2u32)\n'
            '      let r1 u32 = raw.store64(frame + 16u64, cpu.thread_trampoline())\n      let r2 u32 = raw.store64(frame + 40u64, 7077888u64)\n'
            '      return 0u32\n    }\n  }\n  return rt.finish(100u32 + u32(v))\n}\n'
            'func entry() u32 !{io.print,memory.raw,port.io,cpu.control} {\n'
            '  if raw.load32(5374016u64) == 2u32 {\n'
            '    print(raw.load64(5373952u64))\n    print(raw.load64(5373960u64))\n    print(raw.load64(5373968u64) / 4096u64)\n    print(222u32)\n    return rt.finish(0u32)\n  }\n'
            '  print(111u32)\n  return rt.finish(0u32)\n}\n'
            'func main() u32 !{io.print,memory.raw,port.io,cpu.control} {\n'
            '  let g u32 = gdt_install()\n  let i u32 = idt_install()\n'
            '  for k in 0u32..512u32 {\n    let e u32 = raw.store64(1146880u64 + u64(k) * 8u64, bit.or(6291456u64 + u64(k) * 4096u64, 3u64))\n  }\n'
            '  let guard u32 = raw.store64(1146880u64 + 128u64 * 8u64, %du64)\n'
            '  let pd u32 = raw.store64(1122328u64, 1146883u64)\n  let flush u32 = cpu.write_cr(3u32, 1114112u32)\n'
            '  let mode u32 = raw.store32(5374016u64, 1u32)\n'
            '  let tr u64 = cpu.thread_trampoline()\n  let a u32 = raw.store64(6819840u64, tr)\n  let b u32 = raw.store64(5505088u64 + 48u64, 6819840u64)\n'
            '  let y u64 = cpu.switch_context(5505024u64, 5505088u64)\n'
            '  return rt.finish(1u32)\n}\n' % entry)


class GuardPageTests(X64Harness):
    FLAGS = ('--thread-entry', 't.entry', '--exception-handler', 't.on_exception', '--exception-resume')

    def run_guest(self, guard_present):
        path = self.dir / 'guard.omni'
        path.write_text(guard_fixture(guard_present), encoding='utf-8')
        rc, serial = self.boot(self.build(path, emit_args=self.FLAGS))
        return rc, serial.split('\n')[:-1]

    def test_a_stack_that_runs_into_its_guard_page_is_caught_on_another_stack_and_recovered(self):
        rc, out = self.run_guest(False)
        # CR2 = 0x680FF8 (the `call` of the trampoline wanted to push its return address there), error code 2 (not present, write, supervisor), the frame lives in the IST page 0x4EF000,
        # and the thread entry then runs again on the fresh stack, so the program ends normally
        self.assertEqual((rc, out), (1, ['6819832', '2', '1263', '222']), out)

    def test_without_the_guard_the_same_overflow_goes_unnoticed(self):
        rc, out = self.run_guest(True)
        self.assertEqual((rc, out), (1, ['111']), out)


def sentinel_asm() -> str:
    """A test-owned routine that loads a DISTINCT pattern into every general register, every XMM register and the FS base, spins until a cell is set (timer interrupts arrive meanwhile),
    then reports which of them changed: bits 0-14 the general registers (rax rcx rdx rsi rdi r8-r11 rbx rbp r12-r15), bits 16-31 xmm0-15, bit 32 the FS base."""
    regs = ['rax', 'rcx', 'rdx', 'rsi', 'rdi', 'r8', 'r9', 'r10', 'r11', 'rbx', 'rbp', 'r12', 'r13', 'r14', 'r15']
    pat = lambda k: int.from_bytes(bytes([0x31 + 3 * k]) * 8, 'little')
    xlo = lambda i: int.from_bytes(bytes([0x70 + i]) * 8, 'little')
    xhi = lambda i: int.from_bytes(bytes([0xC0 + i]) * 8, 'little')
    out = ['        .text', '        .globl sentinel_run', 'sentinel_run:']
    out += ['        pushq %%%s' % r for r in ('rbx', 'rbp', 'r12', 'r13', 'r14', 'r15')]
    out += ['        movl $0xC0000100, %ecx', '        movl $0xFEEDFACE, %eax', '        movl $0x00C0FFEE, %edx', '        wrmsr']
    out += ['        movaps xmmtab+%d(%%rip), %%xmm%d' % (16 * i, i) for i in range(16)]
    out += ['        movabsq $%d, %%%s' % (pat(k), r) for k, r in enumerate(regs)]
    out += ['1:      pause', '        cmpq $0, 5374080', '        je 1b']
    out += ['        movq %%%s, %d' % (r, 5374464 + 8 * k) for k, r in enumerate(regs)]
    out += ['        movups %%xmm%d, %d' % (i, 5374592 + 16 * i) for i in range(16)]
    out += ['        movl $0xC0000100, %ecx', '        rdmsr', '        movl %eax, 5374848', '        movl %edx, 5374852']
    out += ['        xorl %eax, %eax']
    for k in range(15):
        out += ['        movabsq $%d, %%rcx' % pat(k), '        cmpq %%rcx, %d' % (5374464 + 8 * k), '        je 2%d' % (k + 1) + 'f' if False else '        je ok%d' % k,
                '        btsq $%d, %%rax' % k, 'ok%d:' % k]
    for i in range(16):
        out += ['        movabsq $%d, %%rcx' % xlo(i), '        cmpq %%rcx, %d' % (5374592 + 16 * i), '        jne bx%d' % i,
                '        movabsq $%d, %%rcx' % xhi(i), '        cmpq %%rcx, %d' % (5374592 + 16 * i + 8), '        je okx%d' % i, 'bx%d:' % i, '        btsq $%d, %%rax' % (16 + i), 'okx%d:' % i]
    out += ['        cmpl $0xFEEDFACE, 5374848', '        jne bfs', '        cmpl $0x00C0FFEE, 5374852', '        je okfs', 'bfs:', '        btsq $32, %rax', 'okfs:']
    out += ['        movq %rax, %r8', '        movl $0xC0000100, %ecx', '        xorl %eax, %eax', '        xorl %edx, %edx', '        wrmsr', '        movq %r8, %rax']
    out += ['        popq %%%s' % r for r in ('r15', 'r14', 'r13', 'r12', 'rbp', 'rbx')]
    out += ['        ret', '        .balign 16', 'xmmtab:']
    out += ['        .quad %d, %d' % (xlo(i), xhi(i)) for i in range(16)]
    return '\n'.join(out) + '\n'


class SentinelTests(X64Harness):
    """CP-12 row 12.6. The sentinel routine runs ON a thread stack painted beforehand, with the local APIC timer interrupting it (the handler is Omni code that overwrites registers on purpose).
    Oracle 1: after twenty interrupts nothing the routine had loaded changed (mask 0); without `--exception-save-fpu` the XMM sentinels do change (so the oracle can fail).
    Oracle 2: the stack the thread never used keeps its paint: the deepest write is within a bound (the interrupt frames of the profile are a few hundred bytes plus the handler's own frames),
    and not a single qword outside the top 16 KiB of the 128 KiB region was touched, whatever the number of interrupts."""
    FLAGS = ('--thread-entry', 't.entry', '--exception-handler', 't.on_exception', '--exception-resume', '--isr-count', '33', '--target-isa', 'sse2')

    FIXTURE = (
        'module t\nimport rt "rt.omni"\nimport idt "idt.omni"\n'
        'extern "sentinel_run" func sentinel_run() u64 !{ffi.call}\n'
        'func on_exception(frame u64) u32 !{memory.raw,port.io,cpu.control} {\n'
        '  if raw.load64(frame) == 32u64 {\n'
        '    let x f64 = f64(raw.load32(5373968u64))\n    var p f64 = x\n    var q f64 = x + 1.0f64\n    var r f64 = x * 2.0f64\n    var s f64 = x * 4.0f64\n'
        '    for k in 0u32..32u32 {\n      p = p * 1.0009765625f64\n      q = q + p\n      r = r - q * 0.5f64\n      s = s + r\n    }\n'
        '    let c u64 = raw.load64(5373952u64)\n'
        '    if p > 0.0f64 {\n      let a u32 = raw.store64(5373952u64, c + 1u64)\n    }\n'
        '    if s < 0.0f64 {\n      let b u32 = raw.store64(5373952u64, c + 1u64)\n    }\n'
        '    if raw.load64(5373952u64) >= 20u64 {\n      let stop u32 = raw.store64(5374080u64, 1u64)\n    }\n'
        '    return raw.store32(4276093104u64, 0u32)\n  }\n'
        '  return rt.finish(100u32 + u32(raw.load64(frame)))\n}\n'
        'func entry() u32 !{io.print,memory.raw,port.io,cpu.control,ffi.call} {\n'
        '  let on u32 = cpu.sti()\n  let mask u64 = sentinel_run()\n  let off u32 = cpu.cli()\n'
        '  let lvt u32 = raw.store32(4276093728u64, 65568u32)\n'
        '  let keep u32 = raw.store64(5374088u64, mask)\n'
        '  let back u64 = cpu.switch_context(5505088u64, 5505024u64)\n'
        '  return rt.finish(99u32)\n}\n'
        'func main() u32 !{io.print,memory.raw,port.io,cpu.control,ffi.call} {\n'
        '  let seed1 u32 = raw.store32(5373960u64, 1u32)\n  let seed3 u32 = raw.store32(5373968u64, 3u32)\n'
        '  let installed u32 = idt.install_count(33u32)\n'
        '  let pic1 u32 = port.out8(33u32, 255u32)\n  let pic2 u32 = port.out8(161u32, 255u32)\n'
        '  let svr u32 = raw.store32(4276093168u64, 511u32)\n  let div u32 = raw.store32(4276093952u64, 11u32)\n'
        # paint 0x6A0000..0x6C0000 (128 KiB) with a pattern the thread never writes
        '  for k in 0u32..16384u32 {\n    let paint u32 = raw.store64(6946816u64 + u64(k) * 8u64, 11574428690240078245u64)\n  }\n'
        '  let lvt u32 = raw.store32(4276093728u64, 131104u32)\n  let init u32 = raw.store32(4276093824u64, 100000u32)\n'
        '  let tr u64 = cpu.thread_trampoline()\n  let a u32 = raw.store64(7077872u64, tr)\n  let b u32 = raw.store64(5505088u64 + 48u64, 7077872u64)\n'
        '  let y u64 = cpu.switch_context(5505024u64, 5505088u64)\n'
        '  print(raw.load64(5374088u64))\n  print(raw.load64(5373952u64))\n'
        # the deepest write: the lowest qword of the region that no longer holds the paint; and the number of touched qwords below the top 16 KiB
        '  var lowest u64 = 7077888u64\n  var k u32 = 0u32\n'
        '  for k < 16384u32 {\n    if raw.load64(6946816u64 + u64(k) * 8u64) != 11574428690240078245u64 {\n      if lowest == 7077888u64 { lowest = 6946816u64 + u64(k) * 8u64 }\n    }\n    k = k + 1u32\n  }\n'
        '  print((7077888u64 - lowest) / 8u64)\n'
        '  var stray u32 = 0u32\n  var j u32 = 0u32\n'
        '  for j < 14336u32 {\n    if raw.load64(6946816u64 + u64(j) * 8u64) != 11574428690240078245u64 { stray = stray + 1u32 }\n    j = j + 1u32\n  }\n'
        '  print(stray)\n  return rt.finish(0u32)\n}\n')

    def build_with_asm(self, extra_flags=()):
        path = self.dir / 'sentinel.omni'
        path.write_text(self.FIXTURE, encoding='utf-8')
        emitted = self.emit(path, extra=self.FLAGS + tuple(extra_flags))
        self.assertEqual(emitted.returncode, 0, emitted.stderr)
        (self.dir / 'sentinel.S').write_text(sentinel_asm())
        self.sh('clang', *self.SSE_CFLAGS, '-c', 'prog.ll', '-o', 'prog.o')
        self.sh('as', '--64', 'sentinel.S', '-o', 'sentinel.o')
        self.sh('ld', '-m', 'elf_x86_64', '-nostdlib', '--gc-sections', '-T', 'payload.ld', 'prog.o', 'sentinel.o', '-o', 'payload.elf')
        self.sh('objcopy', '-O', 'binary', 'payload.elf', 'payload.bin')
        self.sh('as', '--32', '--defsym', 'AP_ENTRY=0', '--defsym', 'SSE=1', '-I', '.', 'boot64.S', '-o', 'boot.o')
        self.sh('ld', '-m', 'elf_i386', '-nostdlib', '-T', 'link32.ld', 'boot.o', '-o', 'boot.elf')
        return self.dir / 'boot.elf'

    def run_guest(self, extra_flags=()):
        rc, serial = self.boot(self.build_with_asm(extra_flags))
        return rc, [int(v) for v in serial.split('\n')[:-1]]

    def test_every_register_and_the_fs_base_survive_the_interrupts_and_the_unused_stack_keeps_its_paint(self):
        rc, out = self.run_guest(('--exception-save-fpu',))
        self.assertEqual(rc, 1, out)
        mask, interrupts, deepest, stray = out
        self.assertEqual(mask, 0, bin(mask))                      # nothing the routine loaded changed: GPR, XMM, FS base
        self.assertGreaterEqual(interrupts, 20)
        self.assertGreater(deepest, 0)                            # the thread did use some stack ...
        self.assertLess(deepest, 2048)                            # ... a few KiB at most (interrupt frame + FP image + handler frames), never the region
        self.assertEqual(stray, 0)                                # ... and nothing below the top 16 KiB was written

    def test_without_the_floating_point_option_the_xmm_sentinels_do_change_and_nothing_else_does(self):
        rc, out = self.run_guest()
        self.assertEqual(rc, 1, out)
        mask = out[0]
        self.assertEqual(mask & 0x7FFF, 0, bin(mask))             # the general registers still survive: the tail saves every caller-saved register and the handler keeps the callee-saved ones
        self.assertEqual(mask >> 32, 0, bin(mask))                # the FS base too
        self.assertNotEqual(mask & 0xFFFF0000, 0, bin(mask))      # but the handler's floating point overwrote XMM registers: the oracle can fail


if __name__ == '__main__':
    unittest.main()
