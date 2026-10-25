#!/usr/bin/env python3
"""CP-12 row 12.4 (spec/FPU_SSE_STATE_CANDIDATE.md section 10): the frame a handler returns is never trusted.

The resumable exception tail (--exception-resume) is the only code that executes `iretq` for Omni. After the handler returns 0 it checks the frame it is about to resume, against what the hardware
pushed when the exception was taken:  bit 0 CS changed | bit 1 RIP not canonical | bit 2 RFLAGS without its reserved bit, with NT, or with another IOPL | bit 3 RSP not canonical (CPL0) or not
in the lower half (CPL3).  A frame that fails is not resumed: the handler is called once more with vector 256 and the report in the error-code slot, and the tail then stops the CPU.

GUEST (QEMU TCG, kernel frames): a page fault is taken and handled (the page is mapped) and the handler then damages ONE field of the frame; the oracle is the report the handler receives and
that no instruction after the fault ever ran. The control (no damage) resumes and re-executes the faulting instruction.
GUEST (QEMU TCG, user frames): a service call from CPL3 whose handler tries to raise the privilege of the frame it returns (CS 0x08) or to point the user stack at kernel space.
The same cases run with `--exception-save-fpu` (the second tail).
"""
from __future__ import annotations
import unittest
from language_0_8_3_alpha8 import X64Harness


def kernel_fixture(damage: str) -> str:
    return ('module t\nimport rt "rt.omni"\nimport idt "idt.omni"\n'
            'func on_exception(frame u64) u32 !{io.print,memory.raw,port.io,cpu.control} {\n'
            '  let v u64 = raw.load64(frame)\n'
            '  if v == 256u64 {\n    print(raw.load64(frame + 8u64))\n    return rt.finish(0u32)\n  }\n'
            '  if v == 14u64 {\n'
            '    let f u32 = raw.store64(1130496u64, 6291587u64)\n    let g u32 = raw.store64(1118224u64, 1130499u64)\n    let h u32 = cpu.write_cr(3u32, 1114112u32)\n'
            + damage +
            '    return 0u32\n  }\n  return rt.finish(100u32 + u32(v))\n}\n'
            'func main() u32 !{io.print,memory.raw,port.io,cpu.control} {\n'
            '  let magic u32 = raw.store32(6291456u64, 42u32)\n  let installed u32 = idt.install()\n'
            '  let seen u32 = raw.load32(2147483648u64)\n  print(seen)\n  print(777u32)\n  return rt.finish(0u32)\n}\n')


DAMAGE = {
    'none': ('', None),
    'cs': ('    let d u32 = raw.store64(frame + 24u64, 16u64)\n', 1),
    'rip': ('    let d u32 = raw.store64(frame + 16u64, 140737488355328u64)\n', 2),                          # 2^47: bit 47 set, bits 63..48 clear: not canonical
    'rflags reserved bit': ('    let d u32 = raw.store64(frame + 32u64, 0u64)\n', 4),
    'rflags nested task': ('    let d u32 = raw.store64(frame + 32u64, bit.or(raw.load64(frame + 32u64), 16384u64))\n', 4),
    'rflags iopl': ('    let d u32 = raw.store64(frame + 32u64, bit.or(raw.load64(frame + 32u64), 12288u64))\n', 4),
    'rflags iopl low bit': ('    let d u32 = raw.store64(frame + 32u64, bit.or(raw.load64(frame + 32u64), 4096u64))\n', 4),
    'rflags iopl high bit': ('    let d u32 = raw.store64(frame + 32u64, bit.or(raw.load64(frame + 32u64), 8192u64))\n', 4),
    'rsp': ('    let d u32 = raw.store64(frame + 40u64, 140737488355328u64)\n', 8),
    'cs and rip': ('    let d u32 = raw.store64(frame + 24u64, 16u64)\n    let e u32 = raw.store64(frame + 16u64, 140737488355328u64)\n', 3),
}


class KernelFrameTests(X64Harness):
    TAIL = ('--exception-handler', 't.on_exception', '--exception-resume')

    def run_case(self, damage, extra=(), sse=False):
        path = self.dir / 'frames.omni'
        path.write_text(kernel_fixture(DAMAGE[damage][0]), encoding='utf-8')
        elf = self.build(path, emit_args=self.TAIL + tuple(extra), sse=sse)
        rc, serial = self.boot(elf)
        return rc, serial.split('\n')[:-1]

    def check_all(self, extra=(), sse=False):
        rc, out = self.run_case('none', extra, sse)
        self.assertEqual((rc, out), (1, ['42', '777']), out)                  # a sound frame is resumed and the faulting load is re-executed
        for name, (_, mask) in DAMAGE.items():
            if mask is None:
                continue
            with self.subTest(name):
                rc, out = self.run_case(name, extra, sse)
                self.assertEqual((rc, out), (1, [str(mask)]), (name, out))        # the report; nothing after the fault ran (no 42, no 777)

    def test_a_damaged_frame_is_not_resumed_and_the_handler_is_told_which_field(self):
        self.check_all()

    def test_the_same_holds_for_the_tail_that_also_restores_the_floating_point_state(self):
        self.check_all(('--target-isa', 'sse2', '--exception-save-fpu'), sse=True)

    def test_a_pointer_to_the_frame_of_an_earlier_entry_cannot_make_the_next_resume_unsound(self):
        # Both faults are taken from main at the same stack depth, so the frame of the first entry and the frame of the second are the SAME memory: a handler that kept the first pointer
        # and writes through it during the second entry damages the live frame. The tail judges the frame it is about to resume, not the one it was given: the second entry is refused.
        path = self.dir / 'stale.omni'
        text = kernel_fixture('')
        text = text.replace("    return 0u32\n  }\n  return rt.finish(100u32 + u32(v))",
                            "    let old u64 = raw.load64(5373952u64)\n    let keep u32 = raw.store64(5373952u64, frame)\n"
                            "    if old != 0u64 {\n      let d u32 = raw.store64(old + 24u64, 16u64)\n    }\n    return 0u32\n  }\n  return rt.finish(100u32 + u32(v))")
        text = text.replace("  let seen u32 = raw.load32(2147483648u64)\n  print(seen)\n",
                            "  let seen u32 = raw.load32(2147483648u64)\n  print(seen)\n"
                            "  let unmap u32 = raw.store64(1130496u64, 0u64)\n  let flush u32 = cpu.write_cr(3u32, 1114112u32)\n"
                            "  let again u32 = raw.load32(2147483648u64)\n  print(again)\n")
        path.write_text(text, encoding='utf-8')
        elf = self.build(path, emit_args=self.TAIL)
        rc, serial = self.boot(elf)
        self.assertEqual((rc, serial.split('\n')[:-1]), (1, ['42', '1']), serial)


    def test_a_handler_that_answers_the_refusal_with_resume_is_not_obeyed(self):
        # the second call (vector 256) is a report, not a question: whatever it returns, the tail stops the CPU - the damaged frame is never executed
        import subprocess
        path = self.dir / 'refusal.omni'
        text = kernel_fixture(DAMAGE['cs'][0]).replace("    print(raw.load64(frame + 8u64))\n    return rt.finish(0u32)\n", "    print(raw.load64(frame + 8u64))\n    return 0u32\n")
        path.write_text(text, encoding='utf-8')
        elf = self.build(path, emit_args=self.TAIL)
        try:
            run = subprocess.run(['qemu-system-x86_64', '-kernel', str(elf), '-display', 'none', '-serial', 'stdio', '-no-reboot', '-device', 'isa-debug-exit,iobase=0xf4,iosize=0x04', '-m', '64'],
                                 capture_output=True, timeout=6)
            self.fail('the CPU was expected to stop in cli; hlt, the guest ended with %s: %r' % (run.returncode, run.stdout))
        except subprocess.TimeoutExpired as halted:
            self.assertEqual((halted.stdout or b'').decode().split('\n')[:-1], ['1'])     # the report, and then silence: no 42, no 777


class EntryRflagsTests(X64Harness):
    """The comparison of RFLAGS is against what the hardware pushed, not against a constant: with IOPL = 3 at entry (a test-owned routine raises it at CPL0), a handler that leaves it is resumed and one that
    lowers it - or raises nothing but changes another privileged bit - is refused with report 4."""
    TAIL = ('--exception-handler', 't.on_exception', '--exception-resume')
    ASM = '        .text\n        .globl raise_iopl\nraise_iopl:\n        pushfq\n        orq $0x3000, (%rsp)\n        popfq\n        xorl %eax, %eax\n        ret\n'

    def run_case(self, damage):
        text = kernel_fixture(damage)
        text = text.replace('import idt "idt.omni"\n', 'import idt "idt.omni"\nextern "raise_iopl" func raise_iopl() u64 !{ffi.call}\n', 1)
        text = text.replace('func main() u32 !{io.print,memory.raw,port.io,cpu.control} {', 'func main() u32 !{io.print,memory.raw,port.io,cpu.control,ffi.call} {', 1)
        text = text.replace('  let installed u32 = idt.install()\n', '  let installed u32 = idt.install()\n  let raised u64 = raise_iopl()\n', 1)
        (self.dir / 'iopl.omni').write_text(text, encoding='utf-8')
        emitted = self.emit(self.dir / 'iopl.omni', extra=self.TAIL)
        self.assertEqual(emitted.returncode, 0, emitted.stderr)
        (self.dir / 'raise.S').write_text(self.ASM)
        self.sh('clang', *self.CFLAGS, '-c', 'prog.ll', '-o', 'prog.o')
        self.sh('as', '--64', 'raise.S', '-o', 'raise.o')
        self.sh('ld', '-m', 'elf_x86_64', '-nostdlib', '--gc-sections', '-T', 'payload.ld', 'prog.o', 'raise.o', '-o', 'payload.elf')
        self.sh('objcopy', '-O', 'binary', 'payload.elf', 'payload.bin')
        self.sh('as', '--32', '--defsym', 'AP_ENTRY=0', '-I', '.', 'boot64.S', '-o', 'boot.o')
        self.sh('ld', '-m', 'elf_i386', '-nostdlib', '-T', 'link32.ld', 'boot.o', '-o', 'boot.elf')
        rc, serial = self.boot(self.dir / 'boot.elf')
        return rc, serial.split('\n')[:-1]

    def test_an_entry_with_iopl_three_is_resumed_when_the_handler_keeps_it_and_refused_when_it_is_lowered(self):
        self.assertEqual(self.run_case(''), (1, ['42', '777']))
        lowered = "    let d u32 = raw.store64(frame + 32u64, bit.and(raw.load64(frame + 32u64), 18446744073709539327u64))\n"      # clears bits 12 and 13
        self.assertEqual(self.run_case(lowered), (1, ['4']))


class UserFrameTests(X64Harness):
    RING3 = ('--ring3-support', '--thread-entry', 'rt.user_main', '--exception-handler', 't.on_exception', '--exception-resume', '--isr-extra-vector', '48')

    def fixture(self, damage):
        text = (self.X64 / 'ring3.omni').read_text(encoding='utf-8')
        old = "    if raw.load64(frame - 8u64) == 1u64 {"
        assert text.count(old) == 1
        text = text.replace(old, "    if raw.load64(frame - 8u64) == 1u64 {\n" + damage)
        head = "func on_exception(frame u64) u32 !{memory.raw,port.io,cpu.control} {\n  let v u64 = raw.load64(frame)\n"
        assert text.count(head) == 1
        text = text.replace(head, head.replace("!{memory.raw,port.io,cpu.control}", "!{io.print,memory.raw,port.io,cpu.control}") +
                            "  if v == 256u64 {\n    print(raw.load64(frame + 8u64))\n    return rt.finish(0u32)\n  }\n")
        (self.dir / 'ring3_frames.omni').write_text(text, encoding='utf-8')
        return self.dir / 'ring3_frames.omni'

    def run_case(self, damage, extra=(), sse=False):
        elf = self.build(self.fixture(damage), emit_args=self.RING3 + tuple(extra), sse=sse)
        rc, serial = self.boot(elf)
        return rc, serial.split('\n')[:-1]

    def test_a_user_session_whose_frame_is_raised_to_ring_zero_or_given_a_kernel_stack_is_never_resumed(self):
        # session 1 is the sound one of ring3.omni: 42 / 48 / 35, then the other two sessions
        rc, out = self.run_case('')
        self.assertEqual(out[:3], ['42', '48', '35'], out)
        cases = [('user code segment replaced by the kernel one', "      let d u32 = raw.store64(frame + 24u64, 8u64)\n", '1'),
                 ('user stack pointed at kernel space', "      let d u32 = raw.store64(frame + 40u64, 18446603336221196288u64)\n", '8'),
                 ('user stack pointed at a non-canonical address', "      let d u32 = raw.store64(frame + 40u64, 140737488355328u64)\n", '8'),
                 ('both', "      let d u32 = raw.store64(frame + 24u64, 8u64)\n      let e u32 = raw.store64(frame + 40u64, 18446603336221196288u64)\n", '9')]
        for label, damage, mask in cases:
            with self.subTest(label):
                rc, out = self.run_case(damage)
                self.assertEqual((rc, out), (1, [mask]), (label, out))

    def test_the_same_with_the_tail_that_restores_the_floating_point_state(self):
        rc, out = self.run_case("      let d u32 = raw.store64(frame + 24u64, 8u64)\n", ('--target-isa', 'sse2', '--exception-save-fpu'), sse=True)
        self.assertEqual((rc, out), (1, ['1']), out)


if __name__ == '__main__':
    unittest.main()
