#!/usr/bin/env python3
"""CP-10 rows 10.5 and 10.6 (spec/FPU_SSE_STATE_CANDIDATE.md sections 8 and 9, examples/storage/cpustate.omni): the CPU state an image relies on is discovered, not assumed, and survives a privileged transition.

10.6  `cpu.cpuid_sub(leaf, subleaf, reg)` and `cpustate.omni`: the features (FXSR, SSE2, XSAVE, AVX), the XSAVE area (mask of supported components, size for the enabled ones and for all of
      them, size/offset of each component) and the MXCSR_MASK of the FXSAVE area. Two CPUs under QEMU TCG: the default one (no XSAVE) and `-cpu max` (XSAVE and AVX): the oracle is the
      architecture (Intel SDM vol. 1 13.4: the enabled area is 512 + 64 bytes with only x87 enabled; the AVX component is 256 bytes at offset 576), not the library.
"""
from __future__ import annotations
import shutil
import subprocess
import unittest
from language_0_8_3_alpha8 import ROOT, OMNI, proc, X64Harness

STORAGE = ROOT / 'examples' / 'storage'


class QemuCpuHarness(X64Harness):
    def setUp(self):
        super().setUp()
        shutil.copy(STORAGE / 'cpustate.omni', self.dir / 'cpustate.omni')

    def boot_cpu(self, elf, cpu):
        run = subprocess.run(['qemu-system-x86_64', '-cpu', cpu, '-smp', '1', '-kernel', str(elf), '-display', 'none', '-serial', 'stdio', '-no-reboot',
                              '-device', 'isa-debug-exit,iobase=0xf4,iosize=0x04', '-m', '64'], capture_output=True, timeout=120)
        return run.returncode, run.stdout.decode().split('\n')[:-1]


class CpuDiscoveryTests(QemuCpuHarness):
    PROGRAM = ('module t\nimport rt "rt.omni"\nimport cpustate "cpustate.omni"\n'
               'func flag(b bool) u32 { if b { return 1u32 } return 0u32 }\n'
               'func main() u32 !{io.print,memory.raw,port.io,cpu.control} {\n'
               '  print(flag(cpustate.has_fxsr()))\n  print(flag(cpustate.has_sse2()))\n  print(flag(cpustate.has_xsave()))\n  print(flag(cpustate.has_avx()))\n  print(flag(cpustate.isa_covered()))\n'
               '  print(u32(bit.and(cpustate.xsave_mask(), 4294967295u64)))\n'
               '  print(cpustate.xsave_size_enabled())\n  print(cpustate.xsave_size_max())\n'
               '  print(cpustate.component_size(2u32))\n  print(cpustate.component_offset(2u32))\n'
               '  let mask u32 = cpustate.mxcsr_mask(5373952u64)\n  print(mask)\n'
               '  print(flag(cpustate.mxcsr_valid(8064u32, mask)))\n  print(flag(cpustate.mxcsr_valid(4294967295u32, mask)))\n'
               '  print(cpustate.fxsave_size())\n  print(cpustate.fxsave_align())\n'
               '  return rt.finish(0u32)\n}\n')

    def run_on(self, cpu):
        path = self.dir / 'discover.omni'
        path.write_text(self.PROGRAM, encoding='utf-8')
        elf = self.build(path, emit_args=('--target-isa', 'sse2'), sse=True)
        rc, out = self.boot_cpu(elf, cpu)
        self.assertEqual(rc, 1, out)
        self.assertEqual(len(out), 15, out)
        keys = ('fxsr', 'sse2', 'xsave', 'avx', 'covered', 'xsave_mask', 'size_enabled', 'size_max', 'avx_size', 'avx_offset', 'mxcsr_mask', 'default_valid', 'all_ones_valid', 'fxsave_size', 'fxsave_align')
        return dict(zip(keys, (int(v) for v in out)))

    def test_a_cpu_without_xsave_reports_no_extended_area_and_the_image_isa_is_covered(self):
        got = self.run_on('qemu64')
        self.assertEqual((got['fxsr'], got['sse2'], got['covered']), (1, 1, 1))
        self.assertEqual((got['xsave'], got['avx']), (0, 0))
        self.assertEqual((got['xsave_mask'], got['size_enabled'], got['size_max'], got['avx_size'], got['avx_offset']), (0, 0, 0, 0, 0))
        self.assertEqual((got['fxsave_size'], got['fxsave_align']), (512, 16))
        self.assertEqual(got['mxcsr_mask'] & 0x1F80, 0x1F80)               # the reset MXCSR (0x1F80) is something the CPU lets software set
        self.assertEqual((got['default_valid'], got['all_ones_valid']), (1, 0))   # ... and a value with every bit set is not

    def test_a_cpu_with_xsave_reports_the_area_it_needs_and_the_components_it_supports(self):
        got = self.run_on('max')
        self.assertEqual((got['fxsr'], got['sse2'], got['covered'], got['xsave']), (1, 1, 1, 1))
        self.assertEqual(got['xsave_mask'] & 3, 3)                       # x87 and SSE are always supported together with XSAVE
        self.assertEqual(got['size_enabled'], 512 + 64)                  # XCR0 = 1 at reset: only x87 enabled -> legacy area + header
        self.assertGreaterEqual(got['size_max'], got['size_enabled'])
        if got['avx']:
            self.assertEqual(got['xsave_mask'] & 4, 4)
            self.assertEqual((got['avx_size'], got['avx_offset']), (256, 576))
            self.assertGreaterEqual(got['size_max'], 576 + 256)


class FeatureBitsTests(QemuCpuHarness):
    """Each feature bit is read from its own bit of its own register: QEMU can switch ONE feature off, so a bit read from the wrong place or from the wrong register shows. The program only reads CPUID, so a CPU
    model without FXSR or SSE2 can still run it."""
    PROGRAM = ('module t\nimport rt "rt.omni"\nimport cpustate "cpustate.omni"\n'
               'func flag(b bool) u32 { if b { return 1u32 } return 0u32 }\n'
               'func main() u32 !{io.print,port.io,cpu.control} {\n'
               '  print(flag(cpustate.has_fxsr()))\n  print(flag(cpustate.has_sse2()))\n  print(flag(cpustate.has_xsave()))\n  print(flag(cpustate.has_avx()))\n  print(flag(cpustate.isa_covered()))\n'
               '  return rt.finish(0u32)\n}\n')

    def features(self, cpu):
        path = self.dir / 'bits.omni'
        path.write_text(self.PROGRAM, encoding='utf-8')
        rc, out = self.boot_cpu(self.build(path, emit_args=('--target-isa', 'sse2'), sse=True), cpu)      # the image is sse2 but only reads CPUID: no SSE state instruction is executed
        self.assertEqual(rc, 1, out)
        return [int(v) for v in out]

    def test_one_feature_off_at_a_time(self):
        self.assertEqual(self.features('max'), [1, 1, 1, 1, 1])                       # fxsr sse2 xsave avx covered
        self.assertEqual(self.features('qemu64,-fxsr'), [0, 1, 0, 0, 0])             # no FXSR: SSE2 is still reported, the ISA is not covered (the state area is missing)
        self.assertEqual(self.features('qemu64,-sse2'), [1, 0, 0, 0, 0])             # no SSE2: FXSR is still reported, the ISA is not covered
        self.assertEqual(self.features('max,-avx'), [1, 1, 1, 0, 1])                 # no AVX: XSAVE is still reported
        no_xsave = self.features('max,-xsave')                                         # no XSAVE: the legacy features stay (QEMU still reports the AVX bit itself)
        self.assertEqual((no_xsave[0], no_xsave[1], no_xsave[2], no_xsave[4]), (1, 1, 0, 1))


class MxcsrMaskTests(unittest.TestCase):
    def test_the_default_applies_only_when_the_area_reports_zero_and_a_value_is_legal_only_inside_the_mask(self):
        import tempfile, pathlib
        with tempfile.TemporaryDirectory(prefix='omni-cp10-') as tmp:
            d = pathlib.Path(tmp)
            text = (STORAGE / 'cpustate.omni').read_text(encoding='utf-8')
            # only the pure functions are exercised: the module is loaded whole, so the CPU-dependent ones are present but never called
            (d / 'cpustate.omni').write_text(text, encoding='utf-8')
            prog = d / 'p.omni'
            prog.write_text('module t\nimport cpustate "cpustate.omni"\nfunc main() u32 {\n'
                            '  if cpustate.mask_or_default(0u32) != 65471u32 { return 1u32 }\n  if cpustate.mask_or_default(65535u32) != 65535u32 { return 2u32 }\n  if cpustate.mask_or_default(1u32) != 1u32 { return 3u32 }\n'
                            '  if !cpustate.mxcsr_valid(8064u32, 65471u32) { return 4u32 }\n  if cpustate.mxcsr_valid(64u32, 65471u32) { return 5u32 }\n'
                            '  if cpustate.mxcsr_valid(65536u32, 65535u32) { return 6u32 }\n  if !cpustate.mxcsr_valid(0u32, 0u32) { return 7u32 }\n'
                            '  if cpustate.fxsave_size() != 512u32 { return 8u32 }\n  if cpustate.fxsave_align() != 16u32 { return 9u32 }\n  if cpustate.xsave_header_bytes() != 64u32 { return 10u32 }\n'
                            '  return 42u32\n}\n', encoding='utf-8')
            done = proc(OMNI, 'eval', prog)
            self.assertEqual(done.returncode, 42, done.stderr)


class CpuidSubTests(X64Harness):
    """The intrinsic itself: what the checker accepts and what the target and the evaluator refuse."""
    def emit_text(self, body, caps='!{cpu.control}', *flags, plain=False):
        path = self.dir / 'cpuid.omni'
        tail = '  return 0u32' if plain else '  return rt.finish(0u32)'     # `plain`: nothing but the intrinsic can ask for a capability
        path.write_text('module t\nimport rt "rt.omni"\nfunc main() u32 %s {\n%s%s\n}\n' % (caps, body, tail), encoding='utf-8')
        return self.emit(path, extra=flags)

    def test_the_subleaf_is_a_value_and_the_register_is_a_literal(self):
        ok = self.emit_text('  let a u32 = cpu.cpuid_sub(13u32, 1u32, 1u32)\n', '!{cpu.control,port.io}')
        self.assertEqual(ok.returncode, 0, ok.stderr)
        text = (self.dir / 'prog.ll').read_text()
        self.assertIn('asm sideeffect "cpuid", "={ax},={bx},={cx},={dx},{ax},{cx},~{memory}"(i32 13, i32 1)', text)
        cases = [
            ('a register out of range', '  let a u32 = cpu.cpuid_sub(13u32, 0u32, 4u32)\n', '!{cpu.control,port.io}', b'E_TARGET_PROFILE'),
            ('a register that is not a literal', '  let r u32 = 1u32\n  let a u32 = cpu.cpuid_sub(13u32, 0u32, r)\n', '!{cpu.control,port.io}', b'E_TARGET_PROFILE'),
            ('two arguments', '  let a u32 = cpu.cpuid_sub(13u32, 0u32)\n', '!{cpu.control,port.io}', b'E_ARITY'),
            ('a sub-leaf that is not a u32', '  let a u32 = cpu.cpuid_sub(13u32, 0u64, 1u32)\n', '!{cpu.control,port.io}', b'E_TYPE'),
            ('no capability', '  let a u32 = cpu.cpuid_sub(13u32, 0u32, 1u32)\n', '!{port.io}', b'E_CAPABILITY'),
        ]
        for label, body, caps, code in cases:
            with self.subTest(label):
                done = self.emit_text(body, caps, plain=(label == 'no capability'))
                self.assertEqual(done.returncode, 2, (label, done.stderr))
                self.assertIn(code, done.stderr, (label, done.stderr))

    def test_the_evaluator_and_a_hosted_build_refuse_it(self):
        path = self.dir / 'hosted.omni'
        path.write_text('module t\nfunc main() u32 !{cpu.control} {\n  let a u32 = cpu.cpuid_sub(13u32, 0u32, 1u32)\n  return 0u32\n}\n', encoding='utf-8')
        self.assertEqual(proc(OMNI, 'check', path).returncode, 0)
        evaluated = proc(OMNI, 'eval', path)
        self.assertEqual(evaluated.returncode, 2, evaluated.stderr)
        self.assertIn(b'E_TARGET_PROFILE', evaluated.stderr)
        emitted = proc(OMNI, 'emit-llvm', path, '-o', self.dir / 'hosted.ll')
        self.assertEqual(emitted.returncode, 2, emitted.stderr)
        self.assertIn(b'E_TARGET_PROFILE', emitted.stderr)

    def test_a_program_that_uses_it_is_wave21(self):
        path = self.dir / 'w.omni'
        path.write_text('module t\nfunc main() u32 !{cpu.control} {\n  let a u32 = cpu.cpuid_sub(13u32, 0u32, 1u32)\n  return 0u32\n}\n', encoding='utf-8')
        wave = proc(OMNI, 'wave', path)
        self.assertEqual(wave.returncode, 0, wave.stderr)
        self.assertTrue(wave.stdout.startswith(b'(omni-wave 21'), wave.stdout[:20])
        old = self.dir / 'as18.owave'
        old.write_bytes(wave.stdout.replace(b'(omni-wave 21', b'(omni-wave 18', 1))
        refused = proc(OMNI, 'check', old)
        self.assertEqual(refused.returncode, 2, refused.stderr)
        self.assertIn(b'E_VERSION', refused.stderr)


class PrivilegedTransitionTests(X64Harness):
    """CP-10 row 10.5: the x87/SSE control state a context set before a privileged transition (CPL3 -> CPL0 -> CPL3) is the one it finds afterwards, and a new context starts clean.

    The ring-0 side is tests/x64/ring3.omni with one more service: the user (provider function `user_main`, mode 4) sets MXCSR to round-up (0x5F80), asks ring 0 for service 3 and reads MXCSR
    again; the ring-0 handler records the MXCSR it saw and then sets its OWN rounding mode (round-down, 0x3F80), as any handler that does floating point would. With `--exception-save-fpu` the
    resumable tail saves and restores the interrupted state, so the user finds 0x5F80; the same program without the option finds 0x3F80: the handler's mode leaked into the interrupted context.
    Mode 5 is a NEW user session after that: ring 0 restores a clean FXSAVE image first, and the user finds the reset MXCSR (0x1F80), not what the previous session left."""
    RING3 = ('--ring3-support', '--thread-entry', 'rt.user_main', '--exception-handler', 't.on_exception', '--exception-resume', '--isr-extra-vector', '48', '--target-isa', 'sse2')

    def fixture(self):
        text = (self.X64 / 'ring3.omni').read_text(encoding='utf-8')
        old = "    if raw.load64(frame - 8u64) == 1u64 {"
        assert text.count(old) == 1
        text = text.replace(old, "    if raw.load64(frame - 8u64) == 3u64 {\n      let seen u32 = raw.store64(5373976u64, u64(cpu.read_mxcsr()))\n      let own u32 = cpu.write_mxcsr(16256u32)\n      return 0u32\n    }\n" + old)
        main_old = text[text.index("func main()"):]
        main_new = ('func clean(area u64) u32 !{memory.raw,cpu.control} {\n  let a u32 = raw.store32(area, 895u32)\n  let b u32 = raw.store32(area + 24u64, 8064u32)\n  return cpu.fxrstor(area)\n}\n\n'
                    'func main() u32 !{io.print,memory.raw,port.io,cpu.control} {\n'
                    '  let g u32 = gdt_install()\n  let i u32 = idt.install_service(48u32)\n'
                    '  let pd u32 = raw.store64(1122312u64, 2097287u64)\n  let flush u32 = cpu.write_cr(3u32, 1114112u32)\n'
                    '  print(session(4u32))\n  print(raw.load64(5373976u64))\n'
                    '  let c u32 = clean(5509120u64)\n  print(session(5u32))\n'
                    '  return rt.finish(0u32)\n}\n')
        (self.dir / 'ring3_fp.omni').write_text(text.replace(main_old, main_new), encoding='utf-8')
        rt = (self.X64 / 'rt.omni').read_text(encoding='utf-8')
        old_user = "  if mode == 2u32 {\n    let v u32 = raw.load32(5242880u64)"
        assert rt.count(old_user) == 1
        rt = rt.replace(old_user, "  if mode == 4u32 {\n    let w u32 = cpu.write_mxcsr(24448u32)\n    let r u64 = cpu.trap3(48u32, 3u64, 0u64, 0u64)\n    let seen u32 = cpu.read_mxcsr()\n    let x u64 = cpu.trap3(48u32, 2u64, u64(seen), 0u64)\n  }\n"
                        "  if mode == 5u32 {\n    let seen u32 = cpu.read_mxcsr()\n    let x u64 = cpu.trap3(48u32, 2u64, u64(seen), 0u64)\n  }\n" + old_user)
        (self.dir / 'rt.omni').write_text(rt, encoding='utf-8')
        return self.dir / 'ring3_fp.omni'

    def run_guest(self, extra=()):
        elf = self.build(self.fixture(), emit_args=self.RING3 + tuple(extra), sse=True)
        rc, serial = self.boot(elf)
        return rc, serial.split('\n')[:-1]

    def test_the_state_a_context_set_survives_a_ring_transition_only_with_the_save_option(self):
        rc, out = self.run_guest(('--exception-save-fpu',))
        # session 4: the user finds 0x5F80 (24448) after the service call; ring 0 had seen 0x5F80 on entry; session 5 (clean image restored by ring 0): the reset MXCSR 0x1F80 (8064)
        self.assertEqual((rc, out), (1, ['24448', '24448', '8064']), out)

    def test_without_the_option_the_handlers_rounding_mode_leaks_into_the_interrupted_context(self):
        rc, out = self.run_guest()
        self.assertEqual((rc, out[:2]), (1, ['16256', '24448']), out)      # the user finds 0x3F80, the handler's mode; ring 0 still saw the user's 0x5F80 on entry


if __name__ == '__main__':
    unittest.main()
