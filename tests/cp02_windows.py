#!/usr/bin/env python3
"""CP-02 rows 2.5 and 2.6 (spec/WINDOWS_CANDIDATE.md, examples/storage/window.omni): dynamic windows over a buffer, with bounds checked on every use, and splitting
into disjoint sub-windows that is proved by arithmetic and by the bytes. Evaluator and native must agree.
"""
from __future__ import annotations
import shutil
import unittest
from cp02_borrowed_containers import ContainerCase
from cp06_callable_registry import RegCase
from language_0_8_3_alpha8 import ROOT, OMNI, proc

STORAGE = ROOT / 'examples' / 'storage'


class WinCase(ContainerCase):
    def setUp(self):
        super().setUp()
        shutil.copy(STORAGE / 'window.omni', self.dir / 'window.omni')

    def source(self, text, name='program.omni'):
        return super().source('import window "window.omni"\n' + text, name)

    # a buffer of `n` bytes, byte i holds i + 1, handed to `body` as `b`
    def with_buffer(self, n, body, helpers=''):
        return self.source(helpers +
            'func main() u32 !{memory.read,memory.write} {\n  let a = buffer.alloc(%du32)\n  match a { Ok(b) {\n    var code u32 = 0u32\n    var fillpos u32 = 0u32\n'
            '    for fillpos < %du32 {\n      let w = buffer.write_u8(borrow_mut(b), fillpos, fillpos + 1u32)\n      match w { Ok(d) { } Err(e) { code = 99u32 } }\n      fillpos = fillpos + 1u32\n    }\n%s\n'
            '    let z u32 = buffer.release(move(b))\n    if code != 0u32 { return code }\n    return 42u32\n  } Err(e) { return e } }\n}\n' % (n, n, body))


class WindowTests(WinCase):
    def test_a_split_gives_two_windows_that_do_not_share_a_byte_and_cover_the_whole(self):
        # for every length 0..10 and every cut: writing 100 through the left and 200 through the right leaves exactly `at` bytes of 100 followed by the rest of 200
        self.both(self.source(
            'func check(n u32, at u32) u32 !{memory.read,memory.write} {\n  let a = buffer.alloc(n)\n  match a { Ok(b) {\n    var code u32 = 0u32\n'
            '    let sp = window.split(window.whole(borrow(b)), at)\n'
            '    match sp { Ok(p) {\n      let l = window.fill(borrow_mut(b), p.left, 100u32)\n      match l { Ok(k) { if k != at { code = 1u32 } } Err(e) { code = 2u32 } }\n'
            '      let r = window.fill(borrow_mut(b), p.right, 200u32)\n      match r { Ok(k) { if k != n - at { code = 3u32 } } Err(e) { code = 4u32 } }\n'
            '      if window.overlap(p.left, p.right) { code = 5u32 }\n      if p.left.off + p.left.len != p.right.off { code = 6u32 }\n    } Err(e) { code = 7u32 } }\n'
            '    var i u32 = 0u32\n    for i < n {\n      let g = buffer.read_u8(borrow(b), i)\n'
            '      match g { Ok(v) { if i < at { if v != 100u32 { code = 8u32 } } else { if v != 200u32 { code = 9u32 } } } Err(e) { code = 10u32 } }\n      i = i + 1u32\n    }\n'
            '    let z u32 = buffer.release(move(b))\n    return code\n  } Err(e) { return 90u32 + e } }\n}\n'
            'func main() u32 !{memory.read,memory.write} {\n  var n u32 = 0u32\n  for n <= 10u32 {\n    var at u32 = 0u32\n    for at <= n {\n      let c u32 = check(n, at)\n      if c != 0u32 { return c + 100u32 * n + 1000u32 * at }\n      at = at + 1u32\n    }\n    n = n + 1u32\n  }\n'
            '  var big u32 = 0u32\n  let past = window.split(window.Window { off: 0u32, len: 4u32 }, 5u32)\n  match past { Ok(p) { big = 1u32 } Err(e) { if e != 5u32 { big = 2u32 } } }\n'
            '  if big != 0u32 { return 200u32 + big }\n  return 42u32\n}\n'))

    def test_a_sub_window_of_a_window_lands_on_the_right_absolute_bytes(self):
        self.both(self.with_buffer(12,
            '    let top = window.whole(borrow(b))\n    let s1 = window.sub(top, 4u32, 6u32)\n'
            '    match s1 { Ok(w1) {\n      let s2 = window.sub(w1, 2u32, 3u32)\n'
            '      match s2 { Ok(w2) {\n        if w2.off != 6u32 { code = 1u32 }\n        if w2.len != 3u32 { code = 2u32 }\n'
            '        let p = window.put(borrow_mut(b), w2, 1u32, 250u32)\n        match p { Ok(d) { } Err(e) { code = 3u32 } }\n'
            '        let g = buffer.read_u8(borrow(b), 7u32)\n        match g { Ok(v) { if v != 250u32 { code = 4u32 } } Err(e) { code = 5u32 } }\n'
            '        let g2 = buffer.read_u8(borrow(b), 6u32)\n        match g2 { Ok(v) { if v != 7u32 { code = 6u32 } } Err(e) { code = 7u32 } }\n'
            # a window of 6 bytes cannot give a 3-byte window at offset 4
            '        let bad = window.sub(w1, 4u32, 3u32)\n        match bad { Ok(x) { code = 8u32 } Err(e) { if e != 5u32 { code = 9u32 } } }\n'
            '        let past = window.sub(w1, 7u32, 0u32)\n        match past { Ok(x) { code = 12u32 } Err(e) { if e != 5u32 { code = 13u32 } } }\n'
            '        let edge = window.sub(w1, 6u32, 0u32)\n        match edge { Ok(x) { if x.len != 0u32 { code = 14u32 } } Err(e) { code = 15u32 } }\n'
            '      } Err(e) { code = 10u32 } }\n    } Err(e) { code = 11u32 } }'))

    def test_an_index_outside_the_window_is_refused_even_when_the_buffer_has_the_byte(self):
        self.both(self.with_buffer(10,
            '    let w window.Window = window.Window { off: 2u32, len: 3u32 }\n'
            '    let a1 = window.get(borrow(b), w, 2u32)\n    match a1 { Ok(v) { if v != 5u32 { code = 1u32 } } Err(e) { code = 2u32 } }\n'
            '    let a2 = window.get(borrow(b), w, 3u32)\n    match a2 { Ok(v) { code = 3u32 } Err(e) { if e != 2u32 { code = 4u32 } } }\n'
            '    let p = window.put(borrow_mut(b), w, 3u32, 77u32)\n    match p { Ok(d) { code = 5u32 } Err(e) { if e != 2u32 { code = 6u32 } } }\n'
            '    let g = buffer.read_u8(borrow(b), 5u32)\n    match g { Ok(v) { if v != 6u32 { code = 7u32 } } Err(e) { code = 8u32 } }'))

    def test_a_window_that_does_not_fit_the_buffer_touches_nothing(self):
        # forged windows: past the end, with an offset that would overflow, and larger than the buffer it is used on
        self.both(self.with_buffer(8,
            '    var k u32 = 0u32\n    var bad0 window.Window = window.Window { off: 6u32, len: 4u32 }\n    var bad1 window.Window = window.Window { off: 4294967295u32, len: 2u32 }\n'
            '    var bad2 window.Window = window.Window { off: 0u32, len: 9u32 }\n    var bad3 window.Window = window.Window { off: 9u32, len: 0u32 }\n'
            '    for k < 4u32 {\n      var w window.Window = bad0\n      if k == 1u32 { w = bad1 }\n      if k == 2u32 { w = bad2 }\n      if k == 3u32 { w = bad3 }\n'
            '      if window.fits(borrow(b), w) { code = 10u32 + k }\n'
            '      let g = window.get(borrow(b), w, 0u32)\n      match g { Ok(v) { code = 20u32 + k } Err(e) { if e != 1u32 { code = 30u32 + k } } }\n'
            '      let p = window.put(borrow_mut(b), w, 0u32, 99u32)\n      match p { Ok(d) { code = 40u32 + k } Err(e) { if e != 1u32 { code = 50u32 + k } } }\n'
            '      let f = window.fill(borrow_mut(b), w, 99u32)\n      match f { Ok(d) { code = 60u32 + k } Err(e) { if e != 1u32 { code = 70u32 + k } } }\n'
            '      k = k + 1u32\n    }\n'
            '    var i u32 = 0u32\n    for i < 8u32 {\n      let g = buffer.read_u8(borrow(b), i)\n      match g { Ok(v) { if v != i + 1u32 { code = 80u32 } } Err(e) { code = 81u32 } }\n      i = i + 1u32\n    }'))

    def test_the_same_window_on_a_smaller_buffer_is_refused(self):
        self.both(self.source(
            'func main() u32 !{memory.read,memory.write} {\n  let a = buffer.alloc(16u32)\n'
            '  match a { Ok(big) {\n    let c = buffer.alloc(4u32)\n    match c { Ok(small) {\n'
            '      var code u32 = 0u32\n      let w window.Window = window.whole(borrow(big))\n'
            '      if !window.fits(borrow(big), w) { code = 1u32 }\n      if window.fits(borrow(small), w) { code = 2u32 }\n'
            '      let g = window.get(borrow(small), w, 0u32)\n      match g { Ok(v) { code = 3u32 } Err(e) { if e != 1u32 { code = 4u32 } } }\n'
            # a buffer that grew accepts the windows of the smaller one
            '      let old window.Window = window.whole(borrow(small))\n      let up = buffer.grow(borrow_mut(small), 16u32)\n      match up { Ok(n) { } Err(e) { code = 5u32 } }\n'
            '      if !window.fits(borrow(small), old) { code = 6u32 }\n      if !window.fits(borrow(small), w) { code = 7u32 }\n'
            '      let z u32 = buffer.release(move(big))\n      let z2 u32 = buffer.release(move(small))\n      if code != 0u32 { return code }\n      return 42u32\n'
            '    } Err(e) { let z u32 = buffer.release(move(big))\n      return 91u32 } }\n  } Err(e) { return 90u32 } }\n}\n'))

    def test_copy_checks_that_the_windows_are_disjoint_and_of_the_same_length(self):
        self.both(self.with_buffer(12,
            '    let src window.Window = window.Window { off: 0u32, len: 4u32 }\n'
            # overlapping by one byte, identical, one inside the other: all refused with 3 and the buffer unchanged
            '    let o1 = window.copy(borrow_mut(b), src, window.Window { off: 3u32, len: 4u32 })\n    match o1 { Ok(n) { code = 1u32 } Err(e) { if e != 3u32 { code = 2u32 } } }\n'
            '    let o2 = window.copy(borrow_mut(b), src, src)\n    match o2 { Ok(n) { code = 3u32 } Err(e) { if e != 3u32 { code = 4u32 } } }\n'
            '    let o3 = window.copy(borrow_mut(b), window.Window { off: 0u32, len: 8u32 }, window.Window { off: 2u32, len: 8u32 })\n    match o3 { Ok(n) { code = 5u32 } Err(e) { if e != 3u32 { code = 6u32 } } }\n'
            '    let l1 = window.copy(borrow_mut(b), src, window.Window { off: 8u32, len: 3u32 })\n    match l1 { Ok(n) { code = 7u32 } Err(e) { if e != 4u32 { code = 8u32 } } }\n'
            '    let g0 = buffer.read_u8(borrow(b), 3u32)\n    match g0 { Ok(v) { if v != 4u32 { code = 9u32 } } Err(e) { code = 10u32 } }\n'
            # a destination that sticks out of the buffer: refused up front, so not even the bytes that would have fitted are written
            '    let out = window.copy(borrow_mut(b), src, window.Window { off: 10u32, len: 4u32 })\n    match out { Ok(n) { code = 17u32 } Err(e) { if e != 1u32 { code = 18u32 } } }\n'
            '    let h0 = buffer.read_u8(borrow(b), 10u32)\n    match h0 { Ok(v) { if v != 11u32 { code = 19u32 } } Err(e) { code = 20u32 } }\n'
            '    let h1 = buffer.read_u8(borrow(b), 11u32)\n    match h1 { Ok(v) { if v != 12u32 { code = 21u32 } } Err(e) { code = 22u32 } }\n'
            # touching windows do not overlap: bytes 1..4 land on 4..7 (src [0,4) and dst [4,8))
            '    let ok = window.copy(borrow_mut(b), src, window.Window { off: 4u32, len: 4u32 })\n    match ok { Ok(n) { if n != 4u32 { code = 11u32 } } Err(e) { code = 12u32 } }\n'
            '    var i u32 = 0u32\n    for i < 4u32 {\n      let g = buffer.read_u8(borrow(b), 4u32 + i)\n      match g { Ok(v) { if v != i + 1u32 { code = 13u32 } } Err(e) { code = 14u32 } }\n      i = i + 1u32\n    }\n'
            '    let g8 = buffer.read_u8(borrow(b), 8u32)\n    match g8 { Ok(v) { if v != 9u32 { code = 15u32 } } Err(e) { code = 16u32 } }'))

    def test_the_arithmetic_of_a_window_agrees_with_the_bytes_for_every_offset_and_length(self):
        # for a buffer of 8 bytes holding 1..8 and EVERY (off, len, i) up to 10: `fits` says exactly off + len <= 8, and a read inside the window gives the byte off + i + 1
        self.both(self.with_buffer(8,
            '    var off u32 = 0u32\n    for off <= 10u32 {\n      var len u32 = 0u32\n      for len <= 10u32 {\n        let w window.Window = window.Window { off: off, len: len }\n'
            '        var expect bool = false\n        if off <= 8u32 { if len <= 8u32 - off { expect = true } }\n'
            '        if window.fits(borrow(b), w) { if !expect { code = 1u32 } } else { if expect { code = 1u32 } }\n'
            '        var i u32 = 0u32\n        for i <= 10u32 {\n          let g = window.get(borrow(b), w, i)\n'
            '          match g {\n            Ok(v) { if !expect { code = 2u32 }\n              if i >= len { code = 3u32 }\n              if v != off + i + 1u32 { code = 4u32 } }\n'
            '            Err(e) { if expect { if i < len { code = 5u32 } }\n              if !expect { if e != 1u32 { code = 6u32 } }\n              if expect { if i >= len { if e != 2u32 { code = 7u32 } } } }\n          }\n          i = i + 1u32\n        }\n'
            '        len = len + 1u32\n      }\n      off = off + 1u32\n    }'))

    def test_what_must_not_compile(self):
        cases = [
            ('writing through a shared borrow of the buffer',
             'func main() u32 !{memory.read,memory.write} {\n  let a = buffer.alloc(4u32)\n  match a { Ok(b) {\n    let p = window.put(borrow(b), window.Window { off: 0u32, len: 2u32 }, 0u32, 1u32)\n'
             '    let z u32 = buffer.release(move(b))\n    return z\n  } Err(e) { return e } }\n}\n', b'E_TYPE'),
            ('a buffer grown while it is being read through a window',
             'func main() u32 !{memory.read,memory.write} {\n  let a = buffer.alloc(4u32)\n  match a { Ok(b) {\n    let r = buffer.read_u8(borrow(b), 0u32)\n    let up = buffer.grow(borrow_mut(b), 8u32)\n'
             '    match r { Ok(v) { } Err(e) { } }\n    match up { Ok(n) { } Err(e) { } }\n    let z u32 = buffer.release(move(b))\n    return z\n  } Err(e) { return e } }\n}\n', None),
            ('a window used as a buffer',
             'func main() u32 !{memory.read} {\n  let w window.Window = window.Window { off: 0u32, len: 2u32 }\n  let n u32 = buffer.len(borrow(w))\n  return n\n}\n', None),
        ]
        for label, program, code in cases:
            with self.subTest(label):
                path = self.source(program, 'bad.omni')
                if code is None:
                    # these are not errors of the window: the second is accepted (the read ended before the growth), the third is refused by the borrow rules
                    if 'grow' in program:
                        checked = proc(OMNI, 'check', path)
                        self.assertEqual(checked.returncode, 0, checked.stderr)
                    else:
                        checked = proc(OMNI, 'check', path)
                        self.assertEqual(checked.returncode, 2, checked.stderr)
                else:
                    self.rejected(program, code)


if __name__ == '__main__':
    unittest.main()
