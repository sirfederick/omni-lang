#!/usr/bin/env python3
"""CP-07 / MN-12 (spec/ENDIAN_UNALIGNED_CANDIDATE.md, examples/storage/endian.omni and endian_mem.omni): byte order is explicit and memory access never assumes alignment.

PURE (evaluator, native and compile time): swap/to_be/from_be/to_le/from_le for 16, 32 and 64 bits, checked against Python's `int.to_bytes` over edge and pseudo-random values, and usable in a
static_assert (they are pure functions of the program).
MEMORY (evaluator model and QEMU guest): loads and stores at ANY address, in either byte order, writing exactly N bytes (the neighbours are untouched); a range that leaves the canonical address
space is refused and touches nothing.
"""
from __future__ import annotations
import random
import shutil
import unittest
from cp02_borrowed_containers import ContainerCase
from language_0_8_3_alpha8 import ROOT, OMNI, proc, X64Harness

STORAGE = ROOT / 'examples' / 'storage'
RNG = random.Random(20261022)


def values(bits):
    edge = [0, 1, 2, (1 << bits) - 1, (1 << (bits - 1)), (1 << (bits - 1)) - 1, 0x0102030405060708 & ((1 << bits) - 1), 0xA5A5A5A5A5A5A5A5 & ((1 << bits) - 1)]
    return edge + [RNG.getrandbits(bits) for _ in range(24)]


def swapped(x, bits):
    return int.from_bytes(x.to_bytes(bits // 8, 'little'), 'big')


class PureCase(ContainerCase):
    def setUp(self):
        super().setUp()
        shutil.copy(STORAGE / 'endian.omni', self.dir / 'endian.omni')

    def source(self, text, name='program.omni'):
        path = self.dir / name
        path.write_text('module t\nimport endian "endian.omni"\n' + text, encoding='utf-8')
        return path


class EndianPureTests(PureCase):
    def test_every_conversion_matches_python_over_edge_and_random_values(self):
        body = []
        n = 0
        for bits in (16, 32, 64):
            for x in values(bits):
                n += 1
                s = swapped(x, bits)
                lit = lambda v: '%du%d' % (v, bits)
                body.append('  if endian.swap%d(%s) != %s { return %du32 }' % (bits, lit(x), lit(s), 1 + n % 40))
                body.append('  if endian.to_be%d(%s) != %s || endian.from_be%d(%s) != %s { return %du32 }' % (bits, lit(x), lit(s), bits, lit(s), lit(x), 1 + n % 40))
                body.append('  if endian.to_le%d(%s) != %s || endian.from_le%d(%s) != %s { return %du32 }' % (bits, lit(x), lit(x), bits, lit(x), lit(x), 1 + n % 40))
                body.append('  if endian.swap%d(endian.swap%d(%s)) != %s { return %du32 }' % (bits, bits, lit(x), lit(x), 1 + n % 40))
        self.both(self.source('func main() u32 {\n' + '\n'.join(body) + '\n  return 42u32\n}\n'))

    def test_they_are_pure_functions_so_a_static_assertion_can_use_them(self):
        self.both(self.source(
            'static_assert(endian.swap32(16909060u32) == 67305985u32, "0x01020304 swaps to 0x04030201")\n'
            'static_assert(endian.to_be16(4660u16) == 13330u16, "0x1234 as big endian on a little endian target")\n'
            'static_assert(endian.to_le64(81985529216486895u64) == 81985529216486895u64, "little endian is the identity here")\n'
            'func main() u32 { return 42u32 }\n'))

    def test_the_conversion_follows_the_byte_order_of_the_target(self):
        # the branch is decided while the program is checked: the same source on a little-endian target has no swap in to_le
        path = self.source('func main() u32 { return endian.to_le32(1u32) + endian.to_be32(1u32) }\n')
        done = proc(OMNI, 'check', path)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.both(path, expected=(1 + 16777216) & 255)        # exit status is the value modulo 256


class MemoryCase(ContainerCase):
    def setUp(self):
        super().setUp()
        for name in ('addr', 'endian_mem'):
            shutil.copy(STORAGE / (name + '.omni'), self.dir / (name + '.omni'))

    def source(self, text, name='program.omni'):
        path = self.dir / name
        path.write_text('module t\nimport addr "addr.omni"\nimport em "endian_mem.omni"\n' + text, encoding='utf-8')
        return path

    HELPERS = ('func at(v u64) addr.Virt !{memory.raw} {\n  let r = addr.virt(v)\n  match r { Ok(a) { return a } Err(code) { let z u32 = raw.store8(0u64, 0u32)\n    return at(v) } }\n}\n')


class EndianMemoryTests(MemoryCase):
    BASE = 4194304 + 1      # odd on purpose: nothing here is aligned

    def run_eval(self, text):
        done = proc(OMNI, 'eval', self.source(text), timeout=180)
        self.assertEqual(done.returncode, 42, done.stderr)

    def test_loads_and_stores_work_at_any_address_in_both_orders_and_touch_only_their_bytes(self):
        lines = []
        for k in range(13):
            lines.append('  let z%d u32 = raw.store8(%du64, %du32)' % (k, self.BASE - 1 + k, 0xEE))     # a guard byte on each side of the field
        base = self.BASE
        lines += [
            '  let a = at(%du64)' % base,
            '  let s1 = em.store_le32(a, 2864434397u32)' ,                                    # 0xAABBCCDD
            '  match s1 { Ok(d) { } Err(e) { return 1u32 } }',
            '  if raw.load8(%du64) != 221u32 || raw.load8(%du64) != 204u32 || raw.load8(%du64) != 187u32 || raw.load8(%du64) != 170u32 { return 2u32 }' % (base, base + 1, base + 2, base + 3),
            '  if raw.load8(%du64) != 238u32 || raw.load8(%du64) != 238u32 { return 3u32 }' % (base - 1, base + 4),
            '  let l1 = em.load_le32(a)', '  match l1 { Ok(v) { if v != 2864434397u32 { return 4u32 } } Err(e) { return 5u32 } }',
            '  let b1 = em.load_be32(a)', '  match b1 { Ok(v) { if v != 3721182122u32 { return 6u32 } } Err(e) { return 7u32 } }',        # 0xDDCCBBAA
            '  let s2 = em.store_be32(a, 2864434397u32)', '  match s2 { Ok(d) { } Err(e) { return 8u32 } }',
            '  if raw.load8(%du64) != 170u32 || raw.load8(%du64) != 221u32 { return 9u32 }' % (base, base + 3),
            '  let s3 = em.store_le64(a, 1311768467463790320u64)', '  match s3 { Ok(d) { } Err(e) { return 10u32 } }',             # 0x123456789ABCDEF0
            '  let l3 = em.load_le64(a)', '  match l3 { Ok(v) { if v != 1311768467463790320u64 { return 11u32 } } Err(e) { return 12u32 } }',
            '  let b3 = em.load_be64(a)', '  match b3 { Ok(v) { if v != 17356517385562371090u64 { return 13u32 } } Err(e) { return 14u32 } }',   # 0xF0DEBC9A78563412
            '  if raw.load8(%du64) != 238u32 || raw.load8(%du64) != 238u32 { return 15u32 }' % (base - 1, base + 8),
            '  let s4 = em.store_be16(a, 4660u16)', '  match s4 { Ok(d) { } Err(e) { return 16u32 } }',
            '  let l4 = em.load_le16(a)', '  match l4 { Ok(v) { if v != 13330u16 { return 17u32 } } Err(e) { return 18u32 } }',            # bytes 12 34 -> le16 0x3412
            '  let b4 = em.load_be16(a)', '  match b4 { Ok(v) { if v != 4660u16 { return 19u32 } } Err(e) { return 20u32 } }',
            '  if raw.load8(%du64) != 188u32 || raw.load8(%du64) != 86u32 { return 21u32 }' % (base + 2, base + 5),   # the 16-bit store wrote two bytes: the 64-bit store's bytes 0xBC and 0x56 are still there
        ]
        self.run_eval(self.HELPERS + 'func main() u32 !{memory.raw} {\n' + '\n'.join(lines) + '\n  return 42u32\n}\n')

    def test_a_range_that_leaves_the_address_space_is_refused_and_touches_nothing(self):
        top = 140737488355328 - 2          # the last two canonical addresses of the lower half: a 4-byte access would enter the hole
        lines = [
            '  let a = at(%du64)' % top,
            '  let l = em.load_le32(a)', '  match l { Ok(v) { return 1u32 } Err(e) { if e != 3u32 { return 2u32 } } }',
            '  let s = em.store_be32(a, 1u32)', '  match s { Ok(v) { return 3u32 } Err(e) { if e != 3u32 { return 4u32 } } }',
            '  let ok = em.load_le16(a)', '  match ok { Ok(v) { } Err(e) { return 5u32 } }',
            '  let a3 = at(%du64)' % (top - 1),                       # the last byte of a 4-byte access would be the first address of the hole
            '  let l3 = em.load_le32(a3)', '  match l3 { Ok(v) { return 8u32 } Err(e) { if e != 3u32 { return 9u32 } } }',
            '  let a4 = at(%du64)' % (top - 2),                       # ... and one address lower the whole access is canonical
            '  let l4 = em.load_le32(a4)', '  match l4 { Ok(v) { } Err(e) { return 10u32 } }',
            '  let hi = at(18446744073709551614u64)',
            '  let w = em.store_le64(hi, 1u64)', '  match w { Ok(v) { return 6u32 } Err(e) { if e != 3u32 { return 7u32 } } }',
        ]
        self.run_eval(self.HELPERS + 'func main() u32 !{memory.raw} {\n' + '\n'.join(lines) + '\n  return 42u32\n}\n')


class EndianImageTests(X64Harness):
    def test_the_guest_gets_the_same_bytes_at_unaligned_addresses(self):
        for name in ('addr', 'endian', 'endian_mem'):
            shutil.copy(STORAGE / (name + '.omni'), self.dir / (name + '.omni'))
        path = self.dir / 'endian_guest.omni'
        path.write_text(
            'module t\nimport rt "rt.omni"\nimport addr "addr.omni"\nimport endian "endian.omni"\nimport em "endian_mem.omni"\n'
            'func show32(v Result<u32,u32>) u32 !{io.print} {\n  match v { Ok(x) { print(x) } Err(e) { print(900u32 + e) } }\n  return 0u32\n}\n'
            'func main() u32 !{io.print,memory.raw,port.io,cpu.control} {\n'
            '  let base = addr.virt(6291457u64)\n'                                           # 0x600001: odd
            '  match base { Ok(a) {\n'
            '    let s = em.store_le32(a, 2864434397u32)\n    match s { Ok(d) { } Err(e) { print(900u32 + e) } }\n'
            '    let z u32 = show32(em.load_le32(a))\n    let y u32 = show32(em.load_be32(a))\n'
            '    print(raw.load8(6291457u64))\n    print(raw.load8(6291460u64))\n'
            '    print(endian.to_be32(2864434397u32))\n'
            '  } Err(e) { print(800u32 + e) } }\n'
            '  return rt.finish(0u32)\n}\n', encoding='utf-8')
        rc, serial = self.boot(self.build(path))
        self.assertEqual((rc, serial.split('\n')[:-1]), (1, ['2864434397', '3721182122', '221', '170', '3721182122']), serial)


if __name__ == '__main__':
    unittest.main()
