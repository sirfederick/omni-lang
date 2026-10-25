#!/usr/bin/env python3
"""CP-07 row 7.4: a cast outside the range of its target is refused, for EVERY pair of integer widths and signs.

The conversion `D(x)` of an integer `x` of type S to the integer type D keeps the value or fails with E_CAST_RANGE: it never truncates, wraps or reinterprets. For the 56 ordered
pairs of {u8,u16,u32,u64,i8,i16,i32,i64}: a value at the edge of the common range converts (evaluator and native agree), and the value just outside it is the typed
failure E_CAST_RANGE (the evaluator reports it, the native image stops with the same code). The values come from the types themselves, not from a list written by hand.
"""
from __future__ import annotations
import unittest
from cp02_borrowed_containers import ContainerCase
from language_0_8_3_alpha8 import OMNI, proc

TYPES = ['u8', 'u16', 'u32', 'u64', 'i8', 'i16', 'i32', 'i64']


def bits(t):
    return int(t[1:])


def lo(t):
    return 0 if t[0] == 'u' else -(1 << (bits(t) - 1))


def hi(t):
    return (1 << bits(t)) - 1 if t[0] == 'u' else (1 << (bits(t) - 1)) - 1


def lit(v, t):
    """A literal of type t with value v, written with the language's own syntax (there is no negative literal: 0 minus the magnitude, in two steps for the minimum)."""
    if v >= 0:
        return '%d%s' % (v, t)
    m = -v
    if m == 1:
        return '(0%s - 1%s)' % (t, t)
    return '((0%s - %d%s) - 1%s)' % (t, m - 1, t, t)


class CastMatrixTests(ContainerCase):
    def test_every_pair_converts_inside_the_common_range_and_fails_outside_it(self):
        in_range, out_range = [], []
        for s in TYPES:
            for d in TYPES:
                if s == d:
                    continue
                common_hi, common_lo = min(hi(s), hi(d)), max(lo(s), lo(d))
                in_range.append((s, d, common_hi))
                in_range.append((s, d, common_lo))
                if hi(s) > hi(d):
                    out_range.append((s, d, hi(d) + 1))
                if lo(s) < lo(d):
                    out_range.append((s, d, lo(d) - 1))
        self.assertGreater(len(in_range), 100)
        self.assertGreater(len(out_range), 40)
        # one program checks every in-range edge: a wrong value makes it return the number of the case
        body = ''.join('func c%d(x %s) %s { return %s(x) }\n' % (i, s, d, d) for i, (s, d, v) in enumerate(in_range))
        main = 'func main() u32 {\n' + ''.join('  if c%d(%s) != %s { return %du32 }\n' % (i, lit(v, s), lit(v, d), 100 + i) for i, (s, d, v) in enumerate(in_range)) + '  return 42u32\n}\n'
        path = self.dir / 'in_range.omni'
        path.write_text('module t\n' + body + main, encoding='utf-8')
        self.both(path)

        for i, (s, d, v) in enumerate(out_range):
            with self.subTest('%s -> %s at %d' % (s, d, v)):
                path = self.dir / ('out%d.omni' % i)
                path.write_text('module t\nfunc c(x %s) %s { return %s(x) }\nfunc main() u32 {\n  let r %s = c(%s)\n  return 42u32\n}\n' % (s, d, d, d, lit(v, s)), encoding='utf-8')
                evaluated = proc(OMNI, 'eval', path, timeout=120)
                self.assertEqual(evaluated.returncode, 2, evaluated.stderr)
                self.assertIn(b'E_CAST_RANGE', evaluated.stderr)
                native = self.dir / ('out%d-native' % i)
                built = self.build_native(path, native)
                self.assertEqual(built.returncode, 0, built.stderr)
                executed = proc(native, timeout=120)
                self.assertEqual(executed.returncode, 70, executed.stderr)
                self.assertIn(b'E_CAST_RANGE', executed.stderr)


if __name__ == '__main__':
    unittest.main()
