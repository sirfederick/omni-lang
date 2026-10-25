#!/usr/bin/env python3
"""CP-07 / MN-01 (spec/TARGET_INTROSPECTION_CANDIDATE.md): the program can ask what it is being compiled for, and the answer is a compile-time fact.

`target.pointer_width()`, `target.little_endian()`, `target.hosted()`, `target.arch_is("x86_64" | "i386")` and `target.has("sse2" | "avx2" | ...)` are folded to literals while the program is validated, from the
profile the compiler was given (--target-profile, --target-isa). They are not strings looked up at run time: the checked program contains the literal, so a branch on `target.has("avx2")` is decided
before the code is generated, and the program's identity (hash, Wave) says what it was checked against. A name that does not exist (a feature, an architecture, a member) is an error, never `false`.
"""
from __future__ import annotations
import os
import subprocess
import unittest
from cp02_borrowed_containers import ContainerCase
from language_0_8_3_alpha8 import ROOT, OMNI, proc, X64Harness

def facts(width, hosted, arch, other, sse):
    """Assertions about the target; `hosted` and `sse` are booleans (a comparison between booleans is not an Omni expression: the condition is the fact itself or its negation)."""
    return ('static_assert(target.pointer_width() == %su32, "pointer width")\n' % width +
            'static_assert(target.little_endian(), "little endian")\n' +
            ('static_assert(target.hosted(), "hosted")\n' if hosted else 'static_assert(!target.hosted(), "freestanding")\n') +
            'static_assert(target.arch_is("%s") && !target.arch_is("%s"), "architecture")\n' % (arch, other) +
            ('static_assert(target.has("sse2"), "sse2")\n' if sse else 'static_assert(!target.has("sse2"), "no sse2")\n') +
            'static_assert(!target.has("avx2"), "no avx2 is assumed by any profile")\n')


class TargetTests(ContainerCase):
    def source(self, text, name='program.omni'):
        # no library imports: a program that declares generics keeps its AUTHORING source (unfolded) in the representations, and these tests are about the folded program
        path = self.dir / name
        path.write_text('module t\n' + text, encoding='utf-8')
        return path

    def emit(self, path, *flags):
        out = self.dir / 'target.ll'
        out.unlink(missing_ok=True)
        return subprocess.run([str(OMNI), 'emit-llvm', str(path), *flags, '-o', str(out)], capture_output=True, cwd=self.dir, env={**os.environ, 'OMNI_HOME': str(ROOT)}, timeout=60)

    def test_a_hosted_program_sees_the_hosted_target(self):
        self.both(self.source(facts(64, True, 'x86_64', 'i386', True) + 'func main() u32 {\n  if target.has("avx2") { return 1u32 }\n  return 42u32\n}\n'))

    def test_every_profile_answers_for_itself(self):
        (self.dir / 'rt.omni').write_text((ROOT / 'tests' / 'x64' / 'rt.omni').read_text(), encoding='utf-8')
        cases = [
            ('x86_64 with general registers only', ['--target-profile', 'baremetal-x86_64', '--service-module', 'rt', '--entry-section', '.text.omni_entry'], facts(64, False, 'x86_64', 'i386', False)),
            ('x86_64 with SSE2', ['--target-profile', 'baremetal-x86_64', '--service-module', 'rt', '--entry-section', '.text.omni_entry', '--target-isa', 'sse2'], facts(64, False, 'x86_64', 'i386', True)),
        ]
        for label, flags, asserted in cases:
            with self.subTest(label):
                path = self.source('import rt "rt.omni"\n' + asserted + 'func main() u32 { return 0u32 }\n', 'target.omni')
                done = self.emit(path, *flags)
                self.assertEqual(done.returncode, 0, (label, done.stderr))
        # and a profile is refused when the program's own assumption does not hold for it
        wrong = self.source('import rt "rt.omni"\n' + facts(64, True, 'x86_64', 'i386', True) + 'func main() u32 { return 0u32 }\n', 'wrong.omni')
        done = self.emit(wrong, '--target-profile', 'baremetal-x86_64', '--service-module', 'rt', '--entry-section', '.text.omni_entry')
        self.assertEqual(done.returncode, 2, done.stderr)
        self.assertIn(b'E_STATIC_ASSERT', done.stderr)

    def test_the_32_bit_boot_profile_is_32_bit(self):
        (self.dir / 'boot.omni').write_text('module boot\npub func enter() u32 { return 0u32 }\n', encoding='utf-8')
        path = self.source(
            'import boot "boot.omni"\nstatic_assert(target.pointer_width() == 32u32, "32 bit")\nstatic_assert(target.arch_is("i386"), "i386")\nstatic_assert(!target.hosted(), "freestanding")\n'
            'static_assert(!target.has("sse2"), "no sse2 in the boot profile")\nfunc main() u32 { return boot.enter() }\n', 'i386.omni')
        done = self.emit(path, '--target-profile', 'baremetal-i386-boot', '--service-module', 'boot', '--entry-section', '.text.omni_entry', '--entry-address', '1048576')
        self.assertEqual(done.returncode, 0, done.stderr)
        # the same program for the host is refused: the assertions are about the target
        hosted = proc(OMNI, 'check', path)
        self.assertEqual(hosted.returncode, 2, hosted.stderr)
        self.assertIn(b'E_STATIC_ASSERT', hosted.stderr)

    def test_the_answer_is_part_of_the_checked_program(self):
        path = self.source('func width() u32 { return target.pointer_width() }\nfunc main() u32 { return width() }\n', 'width.omni')
        plain = self.source('func width() u32 { return 64u32 }\nfunc main() u32 { return width() }\n', 'plain.omni')
        self.assertEqual(proc(OMNI, 'hash', path).stdout, proc(OMNI, 'hash', plain).stdout)       # folded: it is exactly the literal (a program that declares generics also keeps its source as written)
        wave = proc(OMNI, 'wave', path)
        self.assertEqual(wave.returncode, 0, wave.stderr)
        self.assertNotIn(b'target.', wave.stdout)
        self.both(path, expected=64)

    def test_a_name_that_does_not_exist_is_an_error_not_false(self):
        cases = [
            ('a feature that does not exist', 'func main() u32 {\n  if target.has("avx9000") { return 1u32 }\n  return 0u32\n}\n'),
            ('an architecture that does not exist', 'func main() u32 {\n  if target.arch_is("arm64") { return 1u32 }\n  return 0u32\n}\n'),
            ('a member that does not exist', 'func main() u32 { return target.cache_line() }\n'),
            ('arguments where there are none', 'func main() u32 { return target.pointer_width(1u32) }\n'),
            ('a name that is not a literal', 'func main() u32 {\n  let n = "sse2"\n  if target.has(n) { return 1u32 }\n  return 0u32\n}\n'),
            ('no name at all', 'func main() u32 {\n  if target.has() { return 1u32 }\n  return 0u32\n}\n'),
        ]
        for label, text in cases:
            with self.subTest(label):
                path = self.source(text, 'bad.omni')
                checked = proc(OMNI, 'check', path)
                self.assertEqual(checked.returncode, 2, (label, checked.stderr))
                self.assertIn(b'E_TARGET', checked.stderr, (label, checked.stderr))


class TargetImageTests(X64Harness):
    def test_the_image_in_the_guest_agrees_with_what_the_compiler_folded(self):
        path = self.dir / 'where.omni'
        path.write_text('module t\nimport rt "rt.omni"\nstatic_assert(!target.hosted(), "freestanding")\n'
                        'func main() u32 !{io.print,port.io,cpu.control} {\n  print(target.pointer_width())\n  if target.has("sse2") { print(1u32) } else { print(0u32) }\n'
                        '  if target.little_endian() { print(1u32) } else { print(0u32) }\n  return rt.finish(0u32)\n}\n', encoding='utf-8')
        rc, serial = self.boot(self.build(path))
        self.assertEqual((rc, serial.split('\n')[:-1]), (1, ['64', '0', '1']), serial)
        # an image built for SSE2 says so (the harness's own SSE adapter enables the unit before any Omni code runs)
        rc, serial = self.boot(self.build(path, emit_args=('--target-isa', 'sse2'), sse=True))
        self.assertEqual((rc, serial.split('\n')[:-1]), (1, ['64', '1', '1']), serial)


if __name__ == '__main__':
    unittest.main()
