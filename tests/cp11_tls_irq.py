#!/usr/bin/env python3
"""CP-11 row 11.6 (spec/TLS_AND_PERCPU_CANDIDATE.md, THREAD_LOCAL_CANDIDATE.md): a context switch keeps the identity and the base of the thread-local block, also when an interrupt arrives between.

tests/x64/tls_threads.omni is run with a periodic local-APIC timer enabled while two threads alternate 20000 times. The handler (ordinary Omni code) reads the FS base MSR, checks it is the base of one of the
two blocks, and counts the interrupt IN the block of the thread it interrupted with `tls.store64` (an interrupt that arrives before the scheduler installed any base is counted apart): a wrong or lost base
would make that access a block fault (trap 13), a base of the other thread would credit the other thread's counter. The oracle: every thread still reads its own value 20000/20000 times, no interrupt saw a foreign base, and the two per-thread counters add up to the total.
"""
from __future__ import annotations
import unittest
from language_0_8_3_alpha8 import X64Harness


class TlsInterruptTests(X64Harness):
    FLAGS = ('--thread-entry', 't.worker', '--exception-handler', 't.on_exception', '--exception-resume', '--isr-count', '33')

    HANDLER = (
        'func on_exception(frame u64) u32 !{memory.tls,memory.raw,port.io,cpu.control} {\n'
        '  if raw.load64(frame) == 32u64 {\n'
        '    let base u64 = bit.or(u64(cpu.rdmsr(3221225728u32, 0u32)), bit.shl(u64(cpu.rdmsr(3221225728u32, 1u32)), 32u32))\n'
        '    if base == 0u64 {\n      let before u32 = raw.store64(5373976u64, raw.load64(5373976u64) + 1u64)\n    } else {\n'
        '      if base != 5767168u64 {\n        if base != 5771264u64 {\n          let bad u32 = raw.store64(5373960u64, raw.load64(5373960u64) + 1u64)\n        }\n      }\n'
        '      if base == 5767168u64 || base == 5771264u64 {\n        let mine u64 = tls.load64(32u64)\n        let w u32 = tls.store64(32u64, mine + 1u64)\n      }\n    }\n'
        '    let total u32 = raw.store64(5373952u64, raw.load64(5373952u64) + 1u64)\n'
        '    return raw.store32(4276093104u64, 0u32)\n  }\n'
        '  return rt.finish(100u32 + u32(raw.load64(frame)))\n}\n\n')

    def fixture(self):
        text = (self.X64 / 'tls_threads.omni').read_text(encoding='utf-8')
        text = text.replace('import rt "rt.omni"\n', 'import rt "rt.omni"\nimport idt "idt.omni"\n', 1)
        text = text.replace('func worker()', self.HANDLER + 'func worker()', 1)
        for old, new in (('for i in 0u32..1000u32 {', 'for i in 0u32..20000u32 {'), ('let want u32 = me * 1000u32 + i', 'let want u32 = me * 100000u32 + i'),
                         ('for r in 0u32..1001u32 {', 'for r in 0u32..20001u32 {')):
            assert text.count(old) == 1, old
            text = text.replace(old, new)
        # counters of the interrupts in the blocks, interrupts on from the first switch
        old_loop = '  for r in 0u32..20001u32 {'
        text = text.replace(old_loop,
                            '  let c1 u32 = raw.store64(5767168u64 + 32u64, 0u64)\n  let c2 u32 = raw.store64(5771264u64 + 32u64, 0u64)\n'
                            '  let installed u32 = idt.install_count(33u32)\n  let pic1 u32 = port.out8(33u32, 255u32)\n  let pic2 u32 = port.out8(161u32, 255u32)\n'
                            '  let svr u32 = raw.store32(4276093168u64, 511u32)\n  let div u32 = raw.store32(4276093952u64, 11u32)\n'
                            '  let lvt u32 = raw.store32(4276093728u64, 131104u32)\n  let init u32 = raw.store32(4276093824u64, 20000u32)\n'
                            '  let on u32 = cpu.sti()\n' + old_loop)
        start = text.index('  print(raw.load32(5511168u64))')
        end = text.index('  return rt.finish(0u32)', start)
        text = (text[:start] + '  let off u32 = cpu.cli()\n  let mask u32 = raw.store32(4276093728u64, 65568u32)\n'
                '  print(raw.load32(5511184u64))\n  print(raw.load32(5511216u64))\n'                      # reads that matched, thread 1 and 2
                '  print(raw.load64(5373952u64))\n  print(raw.load64(5373960u64))\n'                      # interrupts, interrupts that saw a foreign base
                '  print(raw.load64(5767168u64 + 32u64))\n  print(raw.load64(5771264u64 + 32u64))\n  print(raw.load64(5373976u64))\n' + text[end:])
        path = self.dir / 'tls_irq.omni'
        path.write_text(text, encoding='utf-8')
        return path

    def test_the_block_base_survives_interrupts_between_switches(self):
        rc, serial = self.boot(self.build(self.fixture(), emit_args=self.FLAGS))
        out = [int(v) for v in serial.split('\n')[:-1]]
        self.assertEqual(rc, 1, serial)
        ok1, ok2, total, bad, c1, c2, before = out
        self.assertEqual((ok1, ok2), (20000, 20000), out)         # every thread read its own value every time
        self.assertGreaterEqual(total, 50, out)                   # many interrupts arrived while the threads alternated
        self.assertEqual(bad, 0, out)                             # none found a base that is not one of the two blocks
        self.assertEqual(c1 + c2 + before, total, out)            # each was counted in exactly one block (or arrived before the first block was installed) ...
        self.assertGreater(c1, 0); self.assertGreater(c2, 0)      # ... of the thread that was running


class TlsInitReentryTests(X64Harness):
    """CP-11 row 11.7: `tls.init` cannot fail half way and can be re-entered. A thread re-initialises its own block 30000 times (each a `rep movsq` the CPU may interrupt) while a timer interrupt
    handler initialises ANOTHER block with the same builtin; both blocks end exactly as the template says, no trap, and the interrupted copy resumed correctly.
    The other halves of the row are already specified and tested elsewhere: a torn-down or never-initialised block, a second teardown, a size field too small, a misaligned or null base (trap 13),
    and the borrow of a thread-local that does not compile (`A83X64ThreadLocalTests`); a variable is a name, not a value, so no reference into a block can outlive it."""
    FLAGS = ('--exception-handler', 't.on_exception', '--exception-resume', '--isr-count', '33')
    SOURCE = (
        'module t\nimport rt "rt.omni"\nimport idt "idt.omni"\n'
        'thread_local counter u64 = 7u64\nthread_local flag u8 = 3u8\n'
        'func set_fs(base u64) u32 !{cpu.control} {\n  return cpu.wrmsr(3221225728u32, u32(bit.and(base, 4294967295u64)), u32(bit.shr(base, 32u32)))\n}\n'
        'func on_exception(frame u64) u32 !{memory.tls,memory.raw,port.io,cpu.control} {\n'
        '  if raw.load64(frame) == 32u64 {\n'
        '    let n u64 = tls.init(5771264u64)\n'                                                    # the OTHER block (0x581000), while the interrupted thread may be inside its own tls.init
        '    let total u32 = raw.store64(5373952u64, raw.load64(5373952u64) + 1u64)\n'
        '    return raw.store32(4276093104u64, 0u32)\n  }\n'
        '  return rt.finish(100u32 + u32(raw.load64(frame)))\n}\n'
        'func main() u32 !{io.print,memory.tls,memory.raw,port.io,cpu.control} {\n'
        '  let poison1 u32 = raw.store64(5767168u64, 12297829382473034410u64)\n  let poison2 u32 = raw.store64(5771264u64, 12297829382473034410u64)\n'
        '  let fs u32 = set_fs(5767168u64)\n'
        '  let installed u32 = idt.install_count(33u32)\n  let pic1 u32 = port.out8(33u32, 255u32)\n  let pic2 u32 = port.out8(161u32, 255u32)\n'
        '  let svr u32 = raw.store32(4276093168u64, 511u32)\n  let div u32 = raw.store32(4276093952u64, 11u32)\n'
        '  let lvt u32 = raw.store32(4276093728u64, 131104u32)\n  let init u32 = raw.store32(4276093824u64, 20000u32)\n'
        '  let on u32 = cpu.sti()\n'
        '  var good u32 = 0u32\n  var i u32 = 0u32\n'
        '  for i < 30000u32 {\n    let size u64 = tls.init(5767168u64)\n    let dirty u32 = tls.set(counter, 99u64)\n    let again u64 = tls.init(5767168u64)\n'
        '    if tls.get(counter) == 7u64 {\n      if tls.get(flag) == 3u8 { good = good + 1u32 }\n    }\n    i = i + 1u32\n  }\n'
        '  let off u32 = cpu.cli()\n  let mask u32 = raw.store32(4276093728u64, 65568u32)\n'
        '  print(good)\n  print(raw.load64(5373952u64))\n  print(tls.block_size())\n'
        '  print(raw.load64(5771264u64 + 16u64))\n  print(raw.load32(5771264u64 + 24u64))\n  print(raw.load64(5771264u64 + 8u64))\n'
        '  return rt.finish(0u32)\n}\n')

    def test_an_initialisation_interrupted_and_re_entered_leaves_both_blocks_exactly_as_the_template(self):
        path = self.dir / 'tls_reentry.omni'
        path.write_text(self.SOURCE, encoding='utf-8')
        rc, serial = self.boot(self.build(path, emit_args=self.FLAGS))
        out = [int(v) for v in serial.split('\n')[:-1]]
        self.assertEqual(rc, 1, serial)
        good, interrupts, size, counter, flag, header_size = out
        self.assertEqual(good, 30000, out)             # the thread saw the template after every one of its initialisations
        self.assertGreaterEqual(interrupts, 20, out)   # the handler initialised the other block many times, some of them in the middle of the thread's own copy
        self.assertEqual((counter, flag, header_size), (7, 3, size), out)   # the other block: template values and the size in its header


if __name__ == '__main__':
    unittest.main()
