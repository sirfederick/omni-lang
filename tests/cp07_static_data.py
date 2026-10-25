#!/usr/bin/env python3
"""CP-07 row 7.7 (spec/STATIC_DATA_CANDIDATE.md): constants and static data, sections, bss and the policy for globals.

MODEL (hosted): `const NAME Type = literal | array(literals)` is immutable static data: scalars and arrays, indexed and iterated like any value, shared across modules when `pub`, never
assignable, and nothing else is accepted as its initializer. The program is the same in the evaluator and native.
IMAGE (QEMU x86-64 guest, inspected with readelf/objdump): the table reaches the machine, it lives in read-only data, and the image has no section that needs initialisation at start:
no `.data`, no `.bss`, no relocations table, no constructors. A mutable global is not an ambient datum: it is a `thread_local` (its template is part of the TLS substrate) or memory the program owns;
so there is no bss to zero and no global that bypasses the effect system.
"""
from __future__ import annotations
import re
import shutil
import subprocess
import unittest
from cp02_borrowed_containers import ContainerCase
from language_0_8_3_alpha8 import ROOT, OMNI, proc, X64Harness


class ConstantCase(ContainerCase):
    LIB = ('module kc\npub const LIMIT u32 = 40u32\npub const TABLE Array<u32,4> = array(10u32,20u32,30u32,40u32)\nconst SECRET u32 = 5u32\n'
           'pub const NEG i16 = -5i16\npub const FLAG bool = true\npub func secret() u32 { return SECRET }\n')

    def setUp(self):
        super().setUp()
        (self.dir / 'kc.omni').write_text(self.LIB, encoding='utf-8')

    def source(self, text, name='program.omni'):
        return super().source('import kc "kc.omni"\n' + text, name)


class ConstantTests(ConstantCase):
    def test_scalars_and_arrays_are_values_in_the_evaluator_and_natively(self):
        self.both(self.source(
            'const BASE u64 = 1000u64\nconst ODDS Array<u8,3> = array(1u8,3u8,5u8)\n'
            'func pick(i u32) u32 { return kc.TABLE[i] }\n'
            'func main() u32 {\n  var sum u32 = 0u32\n  for x in kc.TABLE { sum = sum + x }\n  var i u32 = 0u32\n'
            '  for i < 4u32 {\n    sum = sum + pick(i)\n    i = i + 1u32\n  }\n'
            '  if sum != 200u32 { return 1u32 }\n  if kc.LIMIT != 40u32 { return 2u32 }\n  if BASE != 1000u64 { return 3u32 }\n  if kc.NEG != -5i16 { return 4u32 }\n'
            '  if ODDS[2u32] != 5u8 { return 5u32 }\n  if kc.secret() != 5u32 { return 6u32 }\n  if !kc.FLAG { return 7u32 }\n'
            '  var total u32 = 0u32\n  for o in ODDS { total = total + u32(o) }\n  if total != 9u32 { return 8u32 }\n  return 42u32\n}\n'))

    def test_a_local_name_wins_over_a_constant_of_the_same_name(self):
        self.both(self.source(
            'const N u32 = 7u32\nfunc shadow(N u32) u32 { return N + 1u32 }\n'
            'func main() u32 {\n  let M u32 = N\n  let r u32 = shadow(100u32)\n  if r != 101u32 { return 1u32 }\n  if M != 7u32 { return 2u32 }\n  return 42u32\n}\n'))

    def test_a_constant_is_available_in_generic_code_and_in_a_trait_impl(self):
        self.both(self.source(
            'const STEP u32 = 3u32\nstruct Tag { v u32 }\ntrait Scale { func scaled(x Self) u32 !pure }\n'
            'impl Scale for Tag { func scaled(x Tag) u32 { return x.v * STEP } }\n'
            'func twice<T>(x T) u32 { return STEP + STEP }\n'
            'func main() u32 {\n  if twice<u32>(1u32) != 6u32 { return 1u32 }\n  if Scale.scaled<Tag>(Tag { v: 4u32 }) != 12u32 { return 2u32 }\n  return 42u32\n}\n'))

    def test_a_scalar_constant_may_be_computed_from_constants_pure_functions_layouts_and_the_target(self):
        # MN-10: limited compile-time evaluation. The expression is pure by construction (a constant declares no capability) and is decided when the program is checked.
        self.both(self.source(
            'struct Desc { a u32, b u64 }\nconst PAGE u64 = 4096u64\nconst PAGE_MASK u64 = PAGE - 1u64\nconst RING u32 = 8u32 * 4u32\nconst WORDS u32 = RING / 4u32\n'
            'func align_up(v u64, a u64) u64 { return (v + a - 1u64) / a * a }\nconst TWO_PAGES u64 = align_up(PAGE + 1u64, PAGE)\nconst DESC_BYTES u64 = layout.size<Desc>()\n'
            'const WIDE bool = target.pointer_width() == 64u32\nconst MASKED u32 = bit.and(255u32, 15u32)\nconst NEGATIVE i16 = -5i16\nconst CHAINED u64 = TWO_PAGES + DESC_BYTES\n'
            'static_assert(PAGE_MASK == 4095u64 && TWO_PAGES == 8192u64, "constants fold")\nstatic_assert(kc.LIMIT == 40u32, "imported constants")\n'
            'func main() u32 {\n  if PAGE_MASK != 4095u64 { return 1u32 }\n  if RING != 32u32 || WORDS != 8u32 { return 2u32 }\n  if TWO_PAGES != 8192u64 { return 3u32 }\n'
            '  if DESC_BYTES != 16u64 { return 4u32 }\n  if !WIDE { return 5u32 }\n  if MASKED != 15u32 { return 6u32 }\n  if NEGATIVE != -5i16 { return 7u32 }\n  if CHAINED != 8208u64 { return 8u32 }\n  return 42u32\n}\n'))

    def test_what_is_refused(self):
        cases = [
            ('a private constant of another module', 'func main() u32 { return kc.SECRET }\n', b'E_VISIBILITY'),
            ('an assignment to a constant', 'const A u32 = 5u32\nfunc main() u32 {\n  A = 6u32\n  return 0u32\n}\n', b'E_UNDEFINED'),
            ('a table that is computed', 'func f() Array<u32,2> { return array(1u32, 2u32) }\nconst A Array<u32,2> = f()\nfunc main() u32 { return A[0u32] }\n', b'E_CONST'),
            ('a scalar constant that needs an effect', 'func f() u32 !{io.print} {\n  print(1u32)\n  return 3u32\n}\nconst A u32 = f()\nfunc main() u32 !{io.print} { return A }\n', b'E_CAPABILITY'),
            ('a scalar constant that overflows', 'const A u32 = 4000000000u32 + 4000000000u32\nfunc main() u32 { return 0u32 }\n', b'E_CONST'),
            ('a scalar constant that divides by zero', 'const Z u32 = 0u32\nconst A u32 = 10u32 / Z\nfunc main() u32 { return 0u32 }\n', b'E_CONST'),
            ('constants that define each other', 'const A u32 = B\nconst B u32 = A\nfunc main() u32 { return A }\n', b'E_CONST'),
            ('an array with a computed element', 'const A Array<u32,2> = array(1u32, 2u32 + 1u32)\nfunc main() u32 { return A[0u32] }\n', b'E_CONST'),
            ('an empty array', 'const A Array<u32,1> = array()\nfunc main() u32 { return 0u32 }\n', b'E_CONST'),
            ('a literal of another type', 'const A u32 = 5u64\nfunc main() u32 { return A }\n', b'E_TYPE'),
            ('an array of the wrong length', 'const A Array<u32,3> = array(1u32, 2u32)\nfunc main() u32 { return A[0u32] }\n', b'E_TYPE'),
            ('the same name as a function', 'const A u32 = 5u32\nfunc A() u32 { return 1u32 }\nfunc main() u32 { return 0u32 }\n', b'E_DUPLICATE'),
            ('a borrow of a constant', 'const A u32 = 5u32\nfunc main() u32 {\n  let r = borrow(A)\n  return 0u32\n}\n', None),
        ]
        for label, program, code in cases:
            with self.subTest(label):
                path = self.source(program, 'bad.omni')
                checked = proc(OMNI, 'check', path)
                self.assertEqual(checked.returncode, 2, (label, checked.stderr))
                if code:
                    self.assertIn(code, checked.stderr, (label, checked.stderr))

    def test_the_representations_carry_calls_and_the_formatter_keeps_the_constant(self):
        # a checked program has only calls: no representation learns a form, and a program that uses constants keeps the label of what it otherwise uses
        path = self.dir / 'k.omni'
        path.write_text('module t\nconst T Array<u32,3> = array(1u32,2u32,3u32)\nfunc main() u32 { return T[1u32] + 40u32 }\n', encoding='utf-8')
        wave = proc(OMNI, 'wave', path)
        self.assertEqual(wave.returncode, 0, wave.stderr)
        self.assertTrue(wave.stdout.startswith(b'(omni-wave 18'), wave.stdout[:20])
        self.assertNotIn(b'const', wave.stdout)
        wire = self.dir / 'k.owire'
        self.assertEqual(proc(OMNI, 'pack', path, '-o', wire).returncode, 0)
        owave = self.dir / 'k.owave'
        owave.write_bytes(wave.stdout)
        for artifact in (path, owave, wire):
            self.assertEqual(proc(OMNI, 'eval', artifact).returncode, 42, artifact.name)
        formatted = proc(OMNI, 'fmt', path)
        self.assertEqual(formatted.returncode, 0, formatted.stderr)
        self.assertIn(b'const T Array<u32,3> = array(1, 2, 3);', formatted.stdout)
        refmt = self.dir / 'refmt.omni'
        refmt.write_bytes(formatted.stdout)
        self.assertEqual(proc(OMNI, 'eval', refmt).returncode, 42)       # the formatted source still means the same


class StaticImageTests(X64Harness):
    """The table reaches the machine and the image needs nothing initialised at start. QEMU TCG, one vCPU."""
    TABLE = ('module t\nimport rt "rt.omni"\nconst PRIMES Array<u32,8> = array(2u32,3u32,5u32,7u32,11u32,13u32,17u32,19u32)\nconst MAGIC u64 = 3735928559u64\n'
             'func at(i u32) u32 { return PRIMES[i % 8u32] }\n'
             'func main() u32 !{io.print,memory.raw,port.io,cpu.control} {\n  var i u32 = 0u32\n'
             # the indices are written to memory and read back with volatile loads: the lookups cannot be folded into constants
             '  for i < 8u32 {\n    let w u32 = raw.store32(6291456u64 + u64(i) * 4u64, 7u32 - i)\n    i = i + 1u32\n  }\n'
             '  var sum u32 = 0u32\n  var weighted u32 = 0u32\n  i = 0u32\n  for i < 8u32 {\n    let idx u32 = raw.load32(6291456u64 + u64(i) * 4u64)\n    sum = sum + at(idx)\n    weighted = weighted + at(idx) * (i + 1u32)\n    i = i + 1u32\n  }\n'
             '  print(sum)\n  print(weighted)\n  print(MAGIC)\n  return rt.finish(0u32)\n}\n')

    def lines(self, serial):
        return serial.split('\n')[:-1]

    def test_the_table_is_read_by_the_guest_and_lives_in_read_only_data(self):
        path = self.dir / 'static.omni'
        path.write_text(self.TABLE, encoding='utf-8')
        rc, serial = self.boot(self.build(path))
        self.assertEqual((rc, self.lines(serial)), (1, ['77', '238', '3735928559']), serial)
        # the lookups cannot have been folded (the indices come from volatile memory), so the values the guest printed came out of the data the image carries; where the optimizer put it
        # (read-only data, or immediates in the code) is its choice - what the language promises is that the data is not writable, which the next lines check
        header = self.sh('readelf', '-lW', 'payload.elf').stdout.decode()
        self.assertNotRegex(header, r'LOAD[^\n]* RW ')      # no writable segment: the table cannot be changed by the program

    def test_the_image_has_no_section_that_needs_initialising_at_start(self):
        path = self.dir / 'static.omni'
        path.write_text(self.TABLE, encoding='utf-8')
        self.build(path)
        sections = self.sh('readelf', '-SW', 'payload.elf').stdout.decode()
        names = set(re.findall(r'\]\s+(\.[\w.$]+)\s', sections))
        for forbidden in ('.bss', '.data', '.got', '.got.plt', '.plt', '.init_array', '.fini_array', '.ctors', '.dtors', '.dynamic', '.interp', '.rela.dyn', '.rela.plt'):
            self.assertNotIn(forbidden, {n for n in names if n == forbidden or n.startswith(forbidden + '.')}, sections)
        # every loadable segment is file-backed in full: nothing is left for a loader to zero
        headers = self.sh('readelf', '-lW', 'payload.elf').stdout.decode()
        for m in re.finditer(r'LOAD\s+0x[0-9a-f]+\s+0x[0-9a-f]+\s+0x[0-9a-f]+\s+(0x[0-9a-f]+)\s+(0x[0-9a-f]+)', headers):
            self.assertEqual(int(m.group(1), 16), int(m.group(2), 16), headers)     # FileSiz == MemSiz


if __name__ == '__main__':
    unittest.main()
