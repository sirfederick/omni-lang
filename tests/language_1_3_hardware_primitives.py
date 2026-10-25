#!/usr/bin/env python3
"""Core 1.3.0.0 hardware primitives: port.in16 / port.in32 / port.out16 and cpu.enter_ring3_interruptible.

Contracts: spec/TARGET_BAREMETAL_PROFILE_CANDIDATE.md (port width contract) and spec/ENTER_RING3_INTERRUPTIBLE_CANDIDATE.md.
Fixtures: tests/x64/portio_wide.omni and tests/x64/ring3_irq.omni (Core-owned, QEMU TCG, one vCPU). Only generalizable language fixtures are included.
OMNI_BASELINE_BIN (optional) points to a compiler built from the parent commit and enables the byte-identical-IR differential.
"""
from __future__ import annotations

import os
import pathlib
import re
import shutil
import subprocess
import tempfile
import unittest

import language_0_8_3_alpha8 as base

ROOT = base.ROOT
OMNI = base.OMNI
BASELINE = os.environ.get('OMNI_BASELINE_BIN')
PCI_ID = (0x1237 << 16) | 0x8086          # i440FX host bridge, bus 0 device 0 function 0 offset 0
NEW_PORT_OPS = ('port.in16', 'port.in32', 'port.out16')
SUM_3M = 3000000 * 2999999 // 2


def run_omni(*args: object, binary: pathlib.Path | str | None = None, timeout: int = 60) -> subprocess.CompletedProcess:
    return subprocess.run([str(binary or OMNI), *[str(a) for a in args]], capture_output=True, timeout=timeout,
                          env={**os.environ, 'OMNI_HOME': str(ROOT)})


def relink_image(harness: base.X64Harness, ll: str) -> pathlib.Path:
    """Re-run the build steps after `emit` on a (mutated) LLVM text; the harness keeps its own build() for the normal path."""
    (harness.dir / 'prog.ll').write_text(ll)
    harness.sh('clang', *harness.CFLAGS, '-c', 'prog.ll', '-o', 'prog.o')
    harness.sh('ld', '-m', 'elf_x86_64', '-nostdlib', '--gc-sections', '-T', 'payload.ld', 'prog.o', '-o', 'payload.elf')
    harness.sh('objcopy', '-O', 'binary', 'payload.elf', 'payload.bin')
    harness.sh('as', '--32', '--defsym', 'AP_ENTRY=0', '-I', '.', 'boot64.S', '-o', 'boot.o')
    harness.sh('ld', '-m', 'elf_i386', '-nostdlib', '-T', 'link32.ld', 'boot.o', '-o', 'boot.elf')
    return harness.dir / 'boot.elf'


class Workdir(unittest.TestCase):
    """Shared temporary directory + source helper (no tests of its own)."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix='omni-a13-hw-')
        self.dir = pathlib.Path(self.tmp.name)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def source(self, text: str, name: str = 'p.omni') -> pathlib.Path:
        path = self.dir / name
        path.write_text(text, encoding='utf-8')
        return path

    def main_with(self, caps: str, body: str, name: str = 'p.omni') -> pathlib.Path:
        return self.source('module t\nfunc main() u32 ' + caps + ' {\n' + body + '}\n', name)


class A13PortWideCheckerTests(Workdir):
    """Typing rules of the three new port operations are those of port.in8 / port.out8 (capability, arity, u32 operands, u32 result)."""

    def test_all_six_widths_are_accepted_with_the_capability(self) -> None:
        body = ('  let a u32 = port.in8(1u32)\n  let b u32 = port.in16(1u32)\n  let c u32 = port.in32(1u32)\n'
                '  let d u32 = port.out8(1u32, 2u32)\n  let e u32 = port.out16(1u32, 2u32)\n  let f u32 = port.out32(1u32, 2u32)\n  return 0u32\n')
        result = run_omni('check', self.main_with('!{port.io}', body))
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_missing_capability_is_refused_for_every_new_operation(self) -> None:
        for call in ('port.in16(1u32)', 'port.in32(1u32)', 'port.out16(1u32, 2u32)'):
            with self.subTest(call=call):
                result = run_omni('check', self.main_with('', '  let v u32 = ' + call + '\n  return 0u32\n'))
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertIn(b'E_CAPABILITY', result.stderr)

    def test_arity_and_operand_types_are_enforced(self) -> None:
        cases = (('port.in16()', b'E_ARITY'), ('port.in32(1u32, 2u32)', b'E_ARITY'), ('port.out16(1u32)', b'E_ARITY'),
                 ('port.out16(1u32, 2u32, 3u32)', b'E_ARITY'), ('port.in16(1u64)', b'E_TYPE'), ('port.in32(true)', b'E_TYPE'),
                 ('port.out16(1u64, 2u32)', b'E_TYPE'), ('port.out16(1u32, 2u64)', b'E_TYPE'))
        for call, code in cases:
            with self.subTest(call=call):
                result = run_omni('check', self.main_with('!{port.io}', '  let v u32 = ' + call + '\n  return 0u32\n'))
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertIn(code, result.stderr)

    def test_result_type_is_u32_not_a_narrower_or_wider_integer(self) -> None:
        for op, wrong in (('port.in16(1u32)', 'u16'), ('port.in16(1u32)', 'u64'), ('port.in32(1u32)', 'u64')):
            with self.subTest(op=op, declared=wrong):
                result = run_omni('check', self.main_with('!{port.io}', '  let v ' + wrong + ' = ' + op + '\n  return 0u32\n'))
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertIn(b'E_TYPE', result.stderr)

    def test_a_caller_without_the_capability_is_refused_transitively(self) -> None:
        source = self.source('module t\nfunc rd() u32 !{port.io} { return port.in32(3324u32) }\nfunc main() u32 { return rd() }\n')
        result = run_omni('check', source)
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn(b'E_CAPABILITY', result.stderr)


class A13PortWideEvaluatorTests(Workdir):
    """Evaluator model: an idle bus reads all ones at the access width; writes are recorded (value truncated to the port width)."""

    def test_idle_bus_reads_all_ones_at_each_width(self) -> None:
        source = self.main_with('!{io.print,port.io}', '  print(port.in8(1u32))\n  print(port.in16(1u32))\n  print(port.in32(1u32))\n  return 0u32\n')
        result = run_omni('eval', source)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.decode().split(), ['255', '65535', '4294967295'])

    def test_out16_is_recorded_with_its_low_16_bits_only(self) -> None:
        # serial bytes written to port 0x3F8 are reported by the evaluator when the program halts
        body = ('  let a u32 = port.out16(1016u32, 11534401u32)\n'      # 0x00B00041: low 16 bits 0x0041 -> 'A'
                '  let b u32 = port.out16(1016u32, 66u32)\n  let c u32 = port.out32(244u32, 1u32)\n  return cpu.halt()\n')
        result = run_omni('eval', self.main_with('!{port.io,cpu.control}', body))
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn(b'E_TARGET_HALT', result.stderr)
        self.assertIn(b'AB', result.stderr)


class A13PortWideLoweringTests(base.X64Harness):
    """IR of the three operations (baremetal-x86_64 and baremetal-i386-boot), their refusal when hosted, and that nothing else changes."""

    PROGRAM = ('func main() u32 !{port.io,cpu.control} {\n'
               '  let s u32 = port.out32(3320u32, 2147483648u32)\n  let a u32 = port.in32(3324u32)\n  let b u32 = port.in16(3326u32)\n'
               '  let w u32 = port.out16(1016u32, 11273482u32)\n  let c u32 = port.in8(3324u32)\n  return a + b + c\n}\n')

    def ir(self) -> str:
        path = self.dir / 'wide.omni'
        path.write_text('module t\nimport rt "rt.omni"\n' + self.PROGRAM, encoding='utf-8')
        result = self.emit(path, out='wide.ll')
        self.assertEqual(result.returncode, 0, result.stderr)
        return (self.dir / 'wide.ll').read_text()

    def test_each_operation_is_one_exact_width_volatile_instruction_in_program_order(self) -> None:
        text = self.ir()
        body = re.search(r'define [^\n]*@omni\.fn\.t\.main\(.*?^\}', text, re.S | re.M).group(0)
        asm = re.findall(r'asm sideeffect "(in[bwl]|out[bwl]) [^"]*", "([^"]*)"\(([^)]*)\)', body)
        self.assertEqual([a[0] for a in asm], ['outl', 'inl', 'inw', 'outw', 'inb'], asm)
        self.assertEqual({a[0]: a[1] for a in asm}['inw'], '={ax},{dx},~{memory}')
        self.assertEqual({a[0]: a[1] for a in asm}['inl'], '={eax},{dx},~{memory}')
        self.assertEqual({a[0]: a[1] for a in asm}['outw'], '{ax},{dx},~{memory}')
        self.assertIn('call i16 asm sideeffect "inw %dx, %ax"', body)
        self.assertIn('call i32 asm sideeffect "inl %dx, %eax"', body)
        self.assertIn('call void asm sideeffect "outw %ax, %dx"', body)
        # inw yields i16 and is zero-extended (never sign-extended); the port and the out16 value are truncated to 16 bits
        self.assertRegex(body, r'= call i16 asm sideeffect "inw[^\n]*\n\s+%\w+ = zext i16 %\w+ to i32')
        self.assertNotIn('sext', body)
        self.assertGreaterEqual(len(re.findall(r'trunc i32 [^\n]* to i16', body)), 4)
        # no byte/word fallback for the wide operations: exactly one inb (the explicit in8) and no outb
        self.assertEqual(len(re.findall(r'"inb ', body)), 1)
        self.assertEqual(len(re.findall(r'"outb ', body)), 0)

    def test_the_wide_operations_exist_in_the_i386_boot_profile_too(self) -> None:
        path = self.dir / 'boot.omni'
        path.write_text('module boot\n' + self.PROGRAM, encoding='utf-8')
        result = subprocess.run([str(OMNI), 'emit-llvm', str(path), '--target-profile', 'baremetal-i386-boot', '--service-module', 'boot',
                                 '--entry-section', '.text.omni_entry', '--entry-address', '1048576', '--entry-stack', '2097152',
                                 '-o', str(self.dir / 'boot.ll')], capture_output=True, env={**os.environ, 'OMNI_HOME': str(ROOT)}, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr)
        text = (self.dir / 'boot.ll').read_text()
        for needle in ('asm sideeffect "inl %dx, %eax"', 'asm sideeffect "inw %dx, %ax"', 'asm sideeffect "outw %ax, %dx"'):
            self.assertIn(needle, text)

    def test_hosted_emit_and_build_refuse_the_new_operations(self) -> None:
        for call in ('port.in16(1u32)', 'port.in32(1u32)', 'port.out16(1u32, 2u32)'):
            with self.subTest(call=call):
                path = self.dir / 'hosted.omni'
                path.write_text('module t\nfunc main() u32 !{port.io} {\n  let v u32 = ' + call + '\n  return 0u32\n}\n', encoding='utf-8')
                built = run_omni('build', path, '-o', self.dir / 'hosted', '--cache-dir', self.dir / 'cache')
                self.assertEqual(built.returncode, 2, built.stderr)
                self.assertIn(b'E_TARGET_PROFILE', built.stderr)
                self.assertFalse((self.dir / 'hosted').exists())
                emitted = run_omni('emit-llvm', path, '-o', self.dir / 'hosted.ll')
                self.assertEqual(emitted.returncode, 2, emitted.stderr)
                self.assertIn(b'E_TARGET_PROFILE', emitted.stderr)

    def test_wave_fence_selects_wave21_for_the_new_names(self) -> None:
        for call in ('port.in16(1u32)', 'port.in32(1u32)', 'port.out16(1u32, 2u32)'):
            with self.subTest(call=call):
                path = self.dir / 'fence.omni'
                path.write_text('module t\nfunc main() u32 !{port.io} {\n  let v u32 = ' + call + '\n  return 0u32\n}\n', encoding='utf-8')
                wave = run_omni('wave', path)
                self.assertEqual(wave.returncode, 0, wave.stderr)
                self.assertTrue(wave.stdout.decode().startswith('(omni-wave 21'), wave.stdout[:40])

    @unittest.skipUnless(BASELINE, 'needs OMNI_BASELINE_BIN (compiler of the parent commit)')
    def test_programs_that_use_neither_feature_produce_byte_identical_ir(self) -> None:
        compared = 0
        for name in sorted(p.name for p in self.X64.glob('*.omni')):
            if name in ('portio_wide.omni', 'ring3_irq.omni', 'rt.omni', 'idt.omni', 'tls_lib.omni', 'spin.omni', 'spin_pack.omni', 'epoch.omni', 'epoch_smp.omni'):
                continue          # fixtures that need extra options or modules, and the new ones
            outputs = []
            for binary in (OMNI, BASELINE):
                out = self.dir / ('diff_' + ('new' if binary == OMNI else 'old') + '.ll')
                out.unlink(missing_ok=True)
                result = subprocess.run([str(binary), 'emit-llvm', str(self.dir / name), '--target-profile', 'baremetal-x86_64', '--service-module', 'rt',
                                         '--entry-section', '.text.omni_entry', '-o', str(out)], capture_output=True, cwd=self.dir,
                                        env={**os.environ, 'OMNI_HOME': str(ROOT)}, timeout=60)
                outputs.append((result.returncode, out.read_bytes() if out.exists() else result.stderr))
            self.assertEqual(outputs[0], outputs[1], name)
            compared += 1
        self.assertGreaterEqual(compared, 8)


@unittest.skipUnless(shutil.which('qemu-system-i386') and shutil.which('clang') and shutil.which('ld'), 'needs qemu-system-i386, clang and ld')
class A13PortWideI386QemuTests(Workdir):
    """The same PCI register read at 32 and 16 bits from an Omni program running in 32-bit protected mode (profile baremetal-i386-boot)."""

    def test_wide_port_operations_run_in_32_bit_protected_mode(self) -> None:
        boot = base.A83BaremetalBootSmokeTests
        path = self.source('module boot\nfunc main() u32 !{port.io,cpu.control} {\n'
                           '  let s u32 = port.out32(3320u32, 2147483648u32)\n'
                           '  let id u32 = port.in32(3324u32)\n  let lo u32 = port.in16(3324u32)\n  let hi u32 = port.in16(3326u32)\n'
                           '  if id == %du32 && lo == %du32 && hi == %du32 {\n'
                           '    let a u32 = port.out8(1016u32, 79u32)\n    let b u32 = port.out8(1016u32, 75u32)\n    let c u32 = port.out8(1016u32, 10u32)\n'
                           '  }\n  let d u32 = port.out32(244u32, 1u32)\n  return cpu.halt()\n}\n' % (PCI_ID, PCI_ID & 0xFFFF, PCI_ID >> 16), 'boot.omni')
        emitted = run_omni('emit-llvm', path, '--target-profile', 'baremetal-i386-boot', '--service-module', 'boot', '--entry-section', '.text.omni_entry',
                           '--entry-address', '1048576', '--entry-stack', '2097152', '-o', self.dir / 'boot.ll')
        self.assertEqual(emitted.returncode, 0, emitted.stderr)
        (self.dir / 'link.ld').write_text(boot.LINKER, encoding='utf-8')
        for cmd in (['clang', '-target', 'i386-unknown-none-elf', *boot.CFLAGS, '-nostdlib', '-c', 'boot.ll', '-o', 'boot.o'],
                    ['ld', '-m', 'elf_i386', '-nostdlib', '-T', 'link.ld', 'boot.o', '-o', 'boot.elf']):
            result = subprocess.run(cmd, capture_output=True, cwd=self.dir)
            self.assertEqual(result.returncode, 0, result.stderr)
        run = subprocess.run(['qemu-system-i386', '-kernel', str(self.dir / 'boot.elf'), '-display', 'none', '-serial', 'stdio', '-no-reboot',
                              '-device', 'isa-debug-exit,iobase=0xf4,iosize=0x04', '-m', '64'], capture_output=True, timeout=60)
        self.assertEqual(run.stdout, b'OK\n', run.stderr)          # printed only if inl and both inw reads matched the device
        self.assertEqual(run.returncode, 3)


class A13PortWideQemuTests(base.X64Harness):
    """The fixture of the contract: three widths of the same PCI register, the idle bus, and the UART pair written by one outw."""

    def test_widths_are_observable_and_exact_under_qemu(self) -> None:
        elf = self.build(self.dir / 'portio_wide.omni')
        rc, serial = self.boot(elf)
        lines = serial.split('\n')
        self.assertEqual(rc, 1, serial)                                   # rt.finish(0) -> isa-debug-exit 0 -> status 1
        self.assertEqual(lines[:4], [str(PCI_ID), str(PCI_ID & 0xFFFF), str(PCI_ID >> 16), str(PCI_ID & 0xFF)], lines)
        self.assertEqual(lines[4:7], ['255', '65535', '4294967295'], lines)   # idle bus: all ones at each width
        # out16(0x00AB050A): transmit byte 0x0A (the blank line), IER = 0x05 (high byte), FCR untouched (IIR = 1, not 0xC1)
        self.assertEqual(lines[7:10], ['', '5', '1'], lines)

    def mutant_output(self, old: str, new: str) -> list[str]:
        self.assertEqual(self.emit(self.dir / 'portio_wide.omni').returncode, 0)
        original = (self.dir / 'prog.ll').read_text()
        text = original.replace(old, new)
        self.assertNotEqual(text, original)
        rc, serial = self.boot(relink_image(self, text))
        return serial.split('\n')

    def test_mutant_out16_lowered_to_a_one_byte_write_is_rejected(self) -> None:
        # instruction text only; the register constraint still names AX/AL. IER (high byte of the 16-bit value) is then never written.
        lines = self.mutant_output('"outw %ax, %dx"', '"outb %al, %dx"')
        self.assertNotEqual(lines[7:10], ['', '5', '1'], lines)

    def test_mutant_in32_lowered_to_a_16_bit_read_is_rejected(self) -> None:
        # eax still holds 0x80000000 from the preceding out32, so the upper half cannot match the device's answer
        lines = self.mutant_output('"inl %dx, %eax"', '"inw %dx, %ax"')
        self.assertNotEqual(lines[0], str(PCI_ID), lines)


class A13X64Ring3Base(base.X64Harness):
    """Common pieces for the CPL3 + timer fixture (no tests of its own)."""

    RING3_IRQ = ('--ring3-support', '--thread-entry', 'rt.user_irq', '--exception-handler', 't.on_exception', '--exception-resume',
                 '--isr-count', '33', '--isr-extra-vector', '48')
    # CPL3 workloads. They live in the provider module (service code: no accounting hooks that touch supervisor-only memory).
    USER_IRQ = '''
pub func user_irq() u32 !{cpu.syscall,cpu.control,memory.raw} {
  let mode u32 = raw.load32(3997696u64)
  if mode == 11u32 {
    var acc u64 = 0u64
    for i in 0u32..3000000u32 {
      acc = acc + u64(i)
    }
    let x u64 = cpu.trap3(48u32, 2u64, acc, 0u64)
  }
  if mode == 12u32 {
    let f u64 = cpu.read_flags()
    let x u64 = cpu.trap3(48u32, 2u64, bit.and(f, 12800u64), 0u64)
  }
  if mode == 13u32 {
    let c u32 = cpu.cli()
  }
  return 0u32
}
'''

    def setUp(self) -> None:
        super().setUp()
        rt = (self.dir / 'rt.omni').read_text()
        self.assertNotIn('user_irq', rt)
        (self.dir / 'rt.omni').write_text(rt + self.USER_IRQ)       # the repository's rt.omni stays byte-identical

    def build_ring3(self, source: pathlib.Path) -> pathlib.Path:
        return self.build(source, emit_args=self.RING3_IRQ)

    def relink(self, ll: str) -> pathlib.Path:
        return relink_image(self, ll)

    def results(self, serial: str) -> list[int]:
        return [int(x) for x in serial.split('\n') if x != '']


class A13EnterRing3InterruptibleCheckerTests(A13X64Ring3Base):
    """Typing, capability, profile and hosted rules (same as cpu.enter_ring3) and the shape of the emitted stub."""

    def prog(self, body: str, caps: str = '!{cpu.control}') -> pathlib.Path:
        return self.source_file('module t\nimport rt "rt.omni"\nfunc main() u32 ' + caps + ' {\n' + body + '  return 0u32\n}\n')

    def source_file(self, text: str) -> pathlib.Path:
        path = self.dir / 'p.omni'
        path.write_text(text, encoding='utf-8')
        return path

    def test_accepted_with_ring3_support_on_baremetal_x86_64(self) -> None:
        path = self.prog('  let r u64 = cpu.enter_ring3_interruptible(1u64, 2u64, 3u64)\n')
        result = self.emit(path, extra=('--ring3-support',))
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_refusals(self) -> None:
        cases = (('missing --ring3-support', 'cpu.enter_ring3_interruptible(1u64, 2u64, 3u64)', '!{cpu.control}', (), b'E_TARGET_PROFILE'),
                 ('missing capability', 'cpu.enter_ring3_interruptible(1u64, 2u64, 3u64)', '!{port.io}', ('--ring3-support',), b'E_CAPABILITY'),
                 ('arity 2', 'cpu.enter_ring3_interruptible(1u64, 2u64)', '!{cpu.control}', ('--ring3-support',), b'E_ARITY'),
                 ('arity 4', 'cpu.enter_ring3_interruptible(1u64, 2u64, 3u64, 4u64)', '!{cpu.control}', ('--ring3-support',), b'E_ARITY'),
                 ('operand u32', 'cpu.enter_ring3_interruptible(1u32, 2u64, 3u64)', '!{cpu.control}', ('--ring3-support',), b'E_TYPE'),
                 ('operand bool', 'cpu.enter_ring3_interruptible(1u64, true, 3u64)', '!{cpu.control}', ('--ring3-support',), b'E_TYPE'),
                 ('result is u64 not u32', None, '!{cpu.control}', ('--ring3-support',), b'E_TYPE'))
        for label, call, caps, extra, code in cases:
            with self.subTest(case=label):
                body = '  let r u64 = ' + call + '\n' if call else '  let r u32 = cpu.enter_ring3_interruptible(1u64, 2u64, 3u64)\n'
                result = self.emit(self.prog(body, caps), extra=extra)
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertIn(code, result.stderr)

    def test_hosted_and_i386_are_refused(self) -> None:
        path = self.prog('  let r u64 = cpu.enter_ring3_interruptible(1u64, 2u64, 3u64)\n')
        hosted = run_omni('build', path, '-o', self.dir / 'hosted', '--cache-dir', self.dir / 'cache')
        self.assertEqual(hosted.returncode, 2, hosted.stderr)
        self.assertIn(b'E_TARGET_PROFILE', hosted.stderr)
        i386 = subprocess.run([str(OMNI), 'emit-llvm', str(path), '--target-profile', 'baremetal-i386-boot', '--service-module', 'rt',
                               '--entry-section', '.text.omni_entry', '--ring3-support', '-o', str(self.dir / 'i386.ll')],
                              capture_output=True, cwd=self.dir, env={**os.environ, 'OMNI_HOME': str(ROOT)}, timeout=60)
        self.assertEqual(i386.returncode, 2, i386.stderr)

    def test_the_stub_is_the_byte_for_byte_twin_of_enter_ring3_except_rflags(self) -> None:
        path = self.prog('  let a u64 = cpu.enter_ring3(1u64, 2u64, 3u64)\n  let b u64 = cpu.enter_ring3_interruptible(1u64, 2u64, 3u64)\n')
        self.assertEqual(self.emit(path, extra=('--ring3-support',)).returncode, 0)
        text = (self.dir / 'prog.ll').read_text()
        plain = re.search(r'module asm "\.text\\0A\.globl omni_enter_ring3\\0Aomni_enter_ring3:.*?\\0Airetq\\0A', text, re.S).group(0)
        interruptible = re.search(r'module asm "\.text\\0A\.globl omni_enter_ring3_interruptible\\0Aomni_enter_ring3_interruptible:.*?\\0Airetq\\0A', text, re.S).group(0)
        normalized = interruptible.replace('omni_enter_ring3_interruptible', 'omni_enter_ring3').replace('pushq $514', 'pushq $2')
        self.assertEqual(plain, normalized)
        self.assertEqual(interruptible.count('pushq $514'), 1)
        self.assertEqual(plain.count('pushq $2\\0A'), 1)
        self.assertIn('declare i64 @omni_enter_ring3_interruptible(i64, i64, i64)', text)
        self.assertIn('call i64 @omni_enter_ring3_interruptible(i64 1, i64 2, i64 3)', text)

    def test_the_stub_is_absent_from_programs_that_do_not_use_the_primitive(self) -> None:
        path = self.prog('  let a u64 = cpu.enter_ring3(1u64, 2u64, 3u64)\n')
        self.assertEqual(self.emit(path, extra=('--ring3-support',)).returncode, 0)
        self.assertNotIn('interruptible', (self.dir / 'prog.ll').read_text())

    def test_wave_fence_covers_the_new_name(self) -> None:
        path = self.dir / 'fence.omni'
        path.write_text('module t\nfunc main() u32 !{cpu.control} {\n  let r u64 = cpu.enter_ring3_interruptible(1u64, 2u64, 3u64)\n  return 0u32\n}\n', encoding='utf-8')
        wave = run_omni('wave', path)
        self.assertEqual(wave.returncode, 0, wave.stderr)
        self.assertTrue(wave.stdout.decode().startswith('(omni-wave 21'))


class A13EnterRing3InterruptibleQemuTests(A13X64Ring3Base):
    """The same CPL3 workload under both entries: only the interruptible one is preempted, and nothing is lost when it is."""

    def run_fixture(self, mutate=None) -> tuple[int, list[str]]:
        elf = self.build_ring3(self.dir / 'ring3_irq.omni')
        if mutate:
            elf = self.relink(mutate((self.dir / 'prog.ll').read_text()))
        rc, serial = self.boot(elf)
        return rc, serial.split('\n')

    def test_interruptible_entry_is_preempted_by_the_timer_and_the_plain_entry_is_not(self) -> None:
        rc, lines = self.run_fixture()
        self.assertEqual(rc, 1, lines)
        total, irqs, bad_cs, total2, irqs2, flags_i, flags_p, cli_session, vector, live = lines[:10]
        self.assertEqual(int(total), SUM_3M)                    # exact result: user context intact across every interrupt
        self.assertGreater(int(irqs), 0)                        # the timer really interrupted CPL3
        self.assertEqual(int(bad_cs), 0)                        # every interrupt arrived from CS = 0x23 (CPL3)
        self.assertEqual(int(total2), SUM_3M)                   # plain entry: same result ...
        self.assertEqual(int(irqs2), 0)                         # ... and never interrupted (IF = 0)
        self.assertEqual(int(flags_i), 0x200)                   # user-visible RFLAGS: IF = 1, IOPL = 0
        self.assertEqual(int(flags_p), 0)                       # plain entry: IF = 0
        self.assertEqual(int(cli_session), 1000 + 13)           # user `cli` raises #GP and ends the session safely
        self.assertEqual(int(vector), 13)
        self.assertEqual(int(live), 123456789 * 3 + 1)          # ring-0 state survives every cpu.leave_ring3

    def test_mutant_without_if_is_rejected(self) -> None:
        rc, lines = self.run_fixture(lambda ll: ll.replace('pushq $514', 'pushq $2'))
        self.assertEqual(int(lines[1]), 0, lines)               # interruptibility lost: the fixture's IRQ oracle sees it
        self.assertEqual(int(lines[5]), 0, lines)

    def test_mutant_with_iopl3_is_rejected(self) -> None:
        rc, lines = self.run_fixture(lambda ll: ll.replace('pushq $514', 'pushq $12802'))
        self.assertEqual(int(lines[5]), 0x3200 | 0x200, lines)   # containment lost: user sees IOPL = 3
        self.assertNotEqual(int(lines[5]), 0x200)


if __name__ == '__main__':
    unittest.main()
