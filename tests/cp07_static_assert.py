#!/usr/bin/env python3
"""CP-07 / MN-15 + MN-10 (spec/STATIC_ASSERT_CANDIDATE.md): `static_assert(condition, "why")` decides a property of the program while it is compiled.

The condition is an ordinary expression of a function that declares NO capability, so it is pure by construction: it can read constants, call other pure functions of the program and ask the layout
(`layout.size<T>()`, `layout.align<T>()`, `layout.offset<T>(field)`), but it cannot print, touch memory or use authority - the checker already refuses that. It is evaluated by the evaluator under
its fuel and depth limits; a false condition, or one that cannot be decided (overflow, division by zero, recursion without end), refuses the program with E_STATIC_ASSERT and the author's message.
A static assertion is a property of the source: it leaves no trace in the program (no representation learns a form, the program has the same hash with or without it).
"""
from __future__ import annotations
import unittest
from cp02_borrowed_containers import ContainerCase
from language_0_8_3_alpha8 import OMNI, proc


class StaticAssertTests(ContainerCase):
    def test_true_assertions_over_layout_constants_and_pure_functions_compile_and_run(self):
        self.both(self.source(
            'struct Desc { a u32, b u64 }\nstruct Pair { x u16, y u16 }\nconst LIMIT u32 = 16u32\nconst SLOTS Array<u32,3> = array(1u32,2u32,3u32)\n'
            'func twice(x u32) u32 { return x * 2u32 }\nfunc fact(n u32) u32 {\n  if n <= 1u32 { return 1u32 }\n  return n * fact(n - 1u32)\n}\n'
            'static_assert(layout.size<Desc>() == 16u64, "the descriptor is 16 bytes")\n'
            'static_assert(layout.align<Desc>() == 8u64, "the descriptor is 8-aligned")\n'
            'static_assert(layout.offset<Desc>(b) == 8u64, "b is at offset 8")\n'
            'static_assert(layout.size<Pair>() == 4u64 && layout.align<Pair>() == 2u64, "a pair is 4 bytes")\n'
            'static_assert(LIMIT == 16u32 && twice(8u32) == LIMIT, "constants and pure functions")\n'
            'static_assert(fact(5u32) == 120u32, "a recursive pure function")\n'
            'static_assert(SLOTS[2u32] == 3u32, "an element of a constant table")\n'
            'func main() u32 {\n  return 42u32\n}\n'))

    def test_a_false_assertion_refuses_the_program_with_its_message_and_place(self):
        path = self.source('struct Desc { a u32, b u64 }\nstatic_assert(layout.size<Desc>() == 12u64, "the descriptor must be 12 bytes")\nfunc main() u32 { return 42u32 }\n')
        checked = proc(OMNI, 'check', path)
        self.assertEqual(checked.returncode, 2, checked.stderr)
        self.assertIn(b'E_STATIC_ASSERT', checked.stderr)
        self.assertIn(b'the descriptor must be 12 bytes', checked.stderr)
        self.assertIn(b'program.omni:5:1', checked.stderr)         # the line of the assertion (the module line and two imports precede the struct)
        for command in ('eval', 'wave', 'manifest', 'hash'):
            with self.subTest(command):
                refused = proc(OMNI, command, path)
                self.assertEqual(refused.returncode, 2, (command, refused.stderr))
                self.assertIn(b'E_STATIC_ASSERT', refused.stderr)

    def test_an_assertion_that_cannot_be_decided_is_refused_not_ignored(self):
        cases = [
            ('overflow', 'func big() u32 { return 4000000000u32 + 4000000000u32 }\nstatic_assert(big() > 0u32, "overflow")\n'),
            ('division by zero', 'func zero() u32 { return 0u32 }\nstatic_assert(10u32 / zero() == 1u32, "zero")\n'),
            ('recursion without end', 'func forever(n u32) u32 { return forever(n + 1u32) }\nstatic_assert(forever(0u32) == 0u32, "forever")\n'),
            ('a loop that does not end', 'func spin() u32 {\n  var i u32 = 0u32\n  for i < 4000000000u32 { i = i + 1u32 }\n  return i\n}\nstatic_assert(spin() == 0u32, "spin")\n'),
        ]
        for label, text in cases:
            with self.subTest(label):
                path = self.source(text + 'func main() u32 { return 0u32 }\n', 'undecided.omni')
                checked = proc(OMNI, 'check', path)
                self.assertEqual(checked.returncode, 2, (label, checked.stderr))
                self.assertIn(b'E_STATIC_ASSERT', checked.stderr, label)

    def test_the_condition_has_no_authority_and_nothing_else_is_accepted(self):
        cases = [
            ('printing', 'func loud() u32 !{io.print} {\n  print(1u32)\n  return 1u32\n}\nstatic_assert(loud() == 1u32, "m")\n', b'E_CAPABILITY'),
            ('raw memory', 'static_assert(raw.load32(4096u64) == 0u32, "m")\n', b'E_CAPABILITY'),
            ('not a bool', 'static_assert(1u32, "m")\n', b'E_TYPE'),
            ('no message', 'static_assert(true)\n', None),
            ('a message that is not a string', 'static_assert(true, 5u32)\n', b'E_STATIC_ASSERT'),
            ('exported', 'pub static_assert(true, "m")\n', b'E_STATIC_ASSERT'),
            ('an unknown name', 'static_assert(nothing == 1u32, "m")\n', None),
            ('a private function of another module', 'static_assert(lib.hidden() == 1u32, "m")\n', b'E_VISIBILITY'),
        ]
        (self.dir / 'lib.omni').write_text('module lib\nfunc hidden() u32 { return 1u32 }\npub func shown() u32 { return 1u32 }\n', encoding='utf-8')
        for label, text, code in cases:
            with self.subTest(label):
                path = self.source('import lib "lib.omni"\n' + text + 'func main() u32 { return 0u32 }\n', 'authority.omni')
                checked = proc(OMNI, 'check', path)
                self.assertEqual(checked.returncode, 2, (label, checked.stderr))
                if code:
                    self.assertIn(code, checked.stderr, (label, checked.stderr))

    def test_an_assertion_in_an_imported_module_guards_the_program_that_imports_it(self):
        (self.dir / 'lib.omni').write_text('module lib\nstruct Header { tag u32, len u32 }\nfunc private_size() u64 { return layout.size<Header>() }\n'
                                           'static_assert(private_size() == 8u64, "the header is 8 bytes")\npub func ok() u32 { return 1u32 }\n', encoding='utf-8')
        self.both(self.source('import lib "lib.omni"\nfunc main() u32 { return 41u32 + lib.ok() }\n'))
        (self.dir / 'lib.omni').write_text('module lib\nstruct Header { tag u32, len u32 }\nstatic_assert(layout.size<Header>() == 16u64, "the header grew")\npub func ok() u32 { return 1u32 }\n', encoding='utf-8')
        path = self.source('import lib "lib.omni"\nfunc main() u32 { return lib.ok() }\n', 'importer.omni')
        checked = proc(OMNI, 'check', path)
        self.assertEqual(checked.returncode, 2, checked.stderr)
        self.assertIn(b'the header grew', checked.stderr)

    def test_an_assertion_leaves_no_trace_in_the_program(self):
        plain = self.dir / 'plain.omni'
        plain.write_text('module t\nstruct Desc { a u32, b u64 }\nfunc main() u32 { return 42u32 }\n', encoding='utf-8')
        asserted = self.dir / 'asserted.omni'
        asserted.write_text('module t\nstruct Desc { a u32, b u64 }\nstatic_assert(layout.size<Desc>() == 16u64, "16")\nfunc main() u32 { return 42u32 }\n', encoding='utf-8')
        for command in ('hash', 'wave', 'capabilities'):
            with self.subTest(command):
                a, b = proc(OMNI, command, plain), proc(OMNI, command, asserted)
                self.assertEqual((a.returncode, b.returncode), (0, 0), (a.stderr, b.stderr))
                self.assertEqual(a.stdout, b.stdout)

    def test_the_formatter_keeps_the_assertion_and_its_message(self):
        path = self.dir / 'fmt.omni'
        path.write_text('module t\nstruct Desc { a u32, b u64 }\nstatic_assert(layout.size<Desc>() == 16u64,   "sixteen \\"bytes\\"")\nfunc main() u32 { return 42u32 }\n', encoding='utf-8')
        formatted = proc(OMNI, 'fmt', path)
        self.assertEqual(formatted.returncode, 0, formatted.stderr)
        text = formatted.stdout.decode()
        # the canonical form: qualified type, parenthesised comparison, the message exactly as written
        self.assertIn('static_assert((layout.size<t.Desc>() == 16u64), "sixteen \\"bytes\\"")', text)
        again = self.dir / 'fmt2.omni'
        again.write_text(text, encoding='utf-8')
        self.assertEqual(proc(OMNI, 'fmt', again).stdout.decode(), text)       # idempotent
        self.assertEqual(proc(OMNI, 'check', again).returncode, 0)             # and what it prints is still the same program
        again.write_text(text.replace('16u64', '8u64'), encoding='utf-8')
        self.assertIn(b'sixteen', proc(OMNI, 'check', again).stderr)           # ... with the same assertion in force


if __name__ == '__main__':
    unittest.main()
