#!/usr/bin/env python3
"""CP-10 / MN-04 (spec/SIMD_BASELINE_CANDIDATE.md, examples/storage/simd.omni): the 128-bit vector baseline - arithmetic, bit operations, comparisons that produce MASKS, select, reductions, loads and stores.

A vector is a record of lanes (2, 4, 8 or 16 fields of one integer/float type, 128 bits) and a mask a record of `bool` lanes; the operations are the `simd.*` intrinsics. Evidence kinds:
MODEL     a Python oracle computes every expected lane (wrapping integers, IEEE floats on exactly representable values, unsigned and signed comparisons); the same generated program is run by the
          evaluator (lane by lane) and as a hosted native binary (LLVM vectors): all three must agree.
GUEST     the same program in a freestanding `--target-isa sse2` image under QEMU TCG, plus loads/stores, the aligned forms and their trap.
NEGATIVE  every wrong shape, type and capability is refused before any artifact; a general-register image and the i386 profile refuse the intrinsics; representation fences.
"""
from __future__ import annotations
import random
import shutil
import struct
import unittest
from cp02_borrowed_containers import ContainerCase
from language_0_8_3_alpha8 import ROOT, OMNI, proc, X64Harness

STORAGE = ROOT / 'examples' / 'storage'
RNG = random.Random(20261022)

TYPES = [('U8x16', 'u8', 16, 8, False, 'M8x16'), ('U16x8', 'u16', 8, 16, False, 'M16x8'), ('U32x4', 'u32', 4, 32, False, 'M32x4'), ('U64x2', 'u64', 2, 64, False, 'M64x2'),
         ('I8x16', 'i8', 16, 8, True, 'M8x16'), ('I16x8', 'i16', 8, 16, True, 'M16x8'), ('I32x4', 'i32', 4, 32, True, 'M32x4'), ('I64x2', 'i64', 2, 64, True, 'M64x2'),
         ('F32x4', 'f32', 4, 32, None, 'M32x4'), ('F64x2', 'f64', 2, 64, None, 'M64x2')]

DYADIC = [-8.0, -4.0, -2.0, -1.0, -0.5, -0.25, 0.25, 0.5, 1.0, 1.5, 2.0, 3.0, 4.0, 8.0]
DIVISORS = [-2.0, -0.5, 0.5, 1.0, 2.0, 4.0, 8.0]


def literal(value, lane, bits, signed):
    if signed is None:
        text = repr(float(abs(value))) + lane
        return ('-' + text) if (value < 0 or str(value).startswith('-')) else text
    if value < 0:
        return '-%d%s' % (-value, lane)
    return '%d%s' % (value, lane)


def int_values(bits, signed):
    top = (1 << bits) - 1
    pool = [0, 1, top, top - 1, 1 << (bits - 1), (1 << (bits - 1)) - 1, (1 << (bits - 1)) + 1]
    return pool + [RNG.getrandbits(bits) for _ in range(8)]


def to_signed(v, bits):
    return v - (1 << bits) if v >= (1 << (bits - 1)) else v


def lane_sets(lanes, bits, signed):
    """Four (a, b) pairs of lane lists, in the representation the oracle uses (unsigned patterns for integers, floats for floats)."""
    pairs = []
    for k in range(4):
        if signed is None:
            a = [RNG.choice(DYADIC) for _ in range(lanes)]
            b = [RNG.choice(DYADIC) for _ in range(lanes)]
            if k == 0:
                b[0] = a[0]
        else:
            pool = int_values(bits, signed)
            a = [RNG.choice(pool) for _ in range(lanes)]
            b = [RNG.choice(pool) for _ in range(lanes)]
            if k == 0:
                b[0] = a[0]
        pairs.append((a, b))
    return pairs


def vector_literal(name, lane, bits, signed, values):
    items = []
    for i, v in enumerate(values):
        shown = v if signed is None else (to_signed(v, bits) if signed else v)
        items.append('l%d: %s' % (i, literal(shown, lane, bits, signed)))
    return 'simd.%s { %s }' % (name, ', '.join(items))


def lanes_equal(var, lane, bits, signed, values):
    conds = []
    for i, v in enumerate(values):
        shown = v if signed is None else (to_signed(v, bits) if signed else v)
        conds.append('%s.l%d != %s' % (var, i, literal(shown, lane, bits, signed)))
    return ' || '.join(conds)


def function_for(index, spec, a, b, guest=False):
    name, lane, lanes, bits, signed, mask = spec
    top = (1 << bits) - 1
    V, M = 'simd.' + name, 'simd.' + mask
    if guest:
        # the operands go through memory (volatile stores and loads) so that the compiler cannot fold the case away: what runs is the SSE2 instruction, not a constant
        lines = ['func case_%d() u32 !{memory.raw} {' % index,
                 '  let a0 = %s' % vector_literal(name, lane, bits, signed, a), '  let b0 = %s' % vector_literal(name, lane, bits, signed, b),
                 '  let sa u32 = simd.store<%s>(5374464u64, a0)' % V, '  let sb u32 = simd.store<%s>(5374480u64, b0)' % V,
                 '  let a = simd.load<%s>(5374464u64)' % V, '  let b = simd.load<%s>(5374480u64)' % V]
    else:
        lines = ['func case_%d() u32 {' % index,
                 '  let a = %s' % vector_literal(name, lane, bits, signed, a),
                 '  let b = %s' % vector_literal(name, lane, bits, signed, b)]
    code = [0]

    def check(cond):
        code[0] += 1
        lines.append('  if %s { return %du32 }' % (cond, code[0]))

    def expect(var, values):
        check(lanes_equal(var, lane, bits, signed, values))

    real = signed is None
    # arithmetic
    for op, fn in (('add', lambda x, y: (x + y) if real else (x + y) & top), ('sub', lambda x, y: (x - y) if real else (x - y) & top), ('mul', lambda x, y: (x * y) if real else (x * y) & top)):
        lines.append('  let r_%s = simd.%s<%s>(a, b)' % (op, op, V))
        expect('r_%s' % op, [fn(x, y) for x, y in zip(a, b)])
    if real:
        divisor = [RNG.choice(DIVISORS) for _ in range(lanes)]
        lines.append('  let d = %s' % vector_literal(name, lane, bits, signed, divisor))
        lines.append('  let r_div = simd.div<%s>(a, d)' % V)
        expect('r_div', [x / y for x, y in zip(a, divisor)])
    else:
        for op, fn in (('and', lambda x, y: x & y), ('or', lambda x, y: x | y), ('xor', lambda x, y: x ^ y)):
            lines.append('  let r_%s = simd.%s<%s>(a, b)' % (op, op, V))
            expect('r_%s' % op, [fn(x, y) for x, y in zip(a, b)])
    # splat and reductions
    lines.append('  let sp = simd.splat<%s>(%s)' % (V, literal(a[0] if real else (to_signed(a[0], bits) if signed else a[0]), lane, bits, signed)))
    expect('sp', [a[0]] * lanes)
    if real:
        acc = a[0]
        for x in a[1:]:
            acc = acc + x
        total = acc
    else:
        total = sum(a) & top
    shown_total = total if real else (to_signed(total, bits) if signed else total)
    lines.append('  let red = simd.reduce_add<%s>(a)' % V)
    check('red != %s' % literal(shown_total, lane, bits, signed))
    # comparisons, masks, select
    keys = lambda v: v if real else (to_signed(v, bits) if signed else v)
    for op, fn in (('eq', lambda x, y: x == y), ('ne', lambda x, y: x != y), ('lt', lambda x, y: x < y), ('le', lambda x, y: x <= y), ('gt', lambda x, y: x > y), ('ge', lambda x, y: x >= y)):
        results = [fn(keys(x), keys(y)) for x, y in zip(a, b)]
        bitmask = sum(1 << i for i, r in enumerate(results) if r)
        lines.append('  let c_%s = simd.%s<%s, %s>(a, b)' % (op, op, V, 'simd.' + mask))
        check('simd.bitmask<%s>(c_%s) != %du32' % ('simd.' + mask, op, bitmask))
        check('simd.any<%s>(c_%s) != %s' % ('simd.' + mask, op, 'true' if bitmask else 'false'))
        check('simd.all<%s>(c_%s) != %s' % ('simd.' + mask, op, 'true' if bitmask == (1 << lanes) - 1 else 'false'))
        if op == 'lt':
            lines.append('  let pick = simd.select<%s, %s>(c_lt, a, b)' % (V, 'simd.' + mask))
            expect('pick', [x if r else y for x, y, r in zip(a, b, results)])
        if op == 'lt':
            lt_mask = bitmask
        if op == 'eq':
            eq_mask = bitmask
        if op == 'le':
            le_mask = bitmask
        if op == 'ge':
            ge_mask = bitmask
    # mask algebra over the two masks made above
    full = (1 << lanes) - 1
    lines.append('  let m_and = simd.mask_and<%s>(c_lt, c_eq)' % ('simd.' + mask))
    lines.append('  let m_or = simd.mask_or<%s>(c_lt, c_eq)' % ('simd.' + mask))
    lines.append('  let m_xor = simd.mask_xor<%s>(c_lt, c_eq)' % ('simd.' + mask))
    lines.append('  let m_not = simd.mask_not<%s>(c_lt)' % ('simd.' + mask))
    check('simd.bitmask<%s>(m_and) != %du32' % ('simd.' + mask, lt_mask & eq_mask))
    check('simd.bitmask<%s>(m_or) != %du32' % ('simd.' + mask, lt_mask | eq_mask))
    check('simd.bitmask<%s>(m_xor) != %du32' % ('simd.' + mask, lt_mask ^ eq_mask))
    check('simd.bitmask<%s>(m_not) != %du32' % ('simd.' + mask, full & ~lt_mask))
    # le and ge are both true on the equal lanes: the algebra of overlapping masks (and = eq, or = everything, xor = ne)
    lines.append('  let o_and = simd.mask_and<%s>(c_le, c_ge)' % ('simd.' + mask))
    lines.append('  let o_or = simd.mask_or<%s>(c_le, c_ge)' % ('simd.' + mask))
    lines.append('  let o_xor = simd.mask_xor<%s>(c_le, c_ge)' % ('simd.' + mask))
    check('simd.bitmask<%s>(o_and) != %du32' % ('simd.' + mask, le_mask & ge_mask))
    check('simd.bitmask<%s>(o_or) != %du32' % ('simd.' + mask, le_mask | ge_mask))
    check('simd.bitmask<%s>(o_xor) != %du32' % ('simd.' + mask, le_mask ^ ge_mask))
    lines += ['  return 0u32', '}']
    return '\n'.join(lines)


def build_program(guest=False):
    parts = ['module t', 'import simd "simd.omni"']
    if guest:
        parts.insert(1, 'import rt "rt.omni"')
    funcs, calls, index = [], [], 0
    for spec in TYPES:
        name, lane, lanes, bits, signed, mask = spec
        for a, b in lane_sets(lanes, bits, signed):
            index += 1
            funcs.append(function_for(index, spec, a, b, guest))
            calls.append('  if case_%d() != 0u32 { bad = bad + 1u32 }' % index)
    parts += funcs
    if guest:
        parts.append('func main() u32 !{io.print,memory.raw,port.io,cpu.control} {\n  var bad u32 = 0u32\n' + '\n'.join(calls) + '\n  print(bad)\n  return rt.finish(0u32)\n}')
    else:
        parts.append('func main() u32 {\n  var bad u32 = 0u32\n' + '\n'.join(calls) + '\n  if bad != 0u32 { return 1u32 }\n  return 42u32\n}')
    return '\n'.join(parts) + '\n', index


class SimdModelTests(ContainerCase):
    def setUp(self):
        super().setUp()
        shutil.copy(STORAGE / 'simd.omni', self.dir / 'simd.omni')

    def source(self, text, name='program.omni'):
        path = self.dir / name
        path.write_text(text, encoding='utf-8')
        return path

    def test_every_lane_of_every_operation_matches_the_oracle_in_the_evaluator_and_natively(self):
        program, cases = build_program()
        self.assertEqual(cases, 40)
        self.both(self.source(program))

    def test_nan_lanes_compare_like_ieee_and_masks_stay_separate_from_integers(self):
        self.both(self.source(
            'module t\nimport simd "simd.omni"\nfunc main() u32 {\n'
            '  let zero = simd.splat<simd.F32x4>(0.0f32)\n  let nan = simd.div<simd.F32x4>(zero, zero)\n  let one = simd.splat<simd.F32x4>(1.0f32)\n'
            '  if simd.bitmask<simd.M32x4>(simd.eq<simd.F32x4, simd.M32x4>(nan, nan)) != 0u32 { return 1u32 }\n'
            '  if simd.bitmask<simd.M32x4>(simd.ne<simd.F32x4, simd.M32x4>(nan, nan)) != 15u32 { return 2u32 }\n'
            '  if simd.any<simd.M32x4>(simd.lt<simd.F32x4, simd.M32x4>(nan, one)) { return 3u32 }\n'
            '  if simd.any<simd.M32x4>(simd.ge<simd.F32x4, simd.M32x4>(one, nan)) { return 4u32 }\n'
            '  let mixed = simd.select<simd.F32x4, simd.M32x4>(simd.ne<simd.F32x4, simd.M32x4>(nan, nan), one, zero)\n'
            '  if simd.reduce_add<simd.F32x4>(mixed) != 4.0f32 { return 5u32 }\n'
            '  return 42u32\n}\n'))

    def test_integer_arithmetic_wraps_per_lane_and_never_traps(self):
        self.both(self.source(
            'module t\nimport simd "simd.omni"\nfunc main() u32 {\n'
            '  let big = simd.splat<simd.I8x16>(127i8)\n  let one = simd.splat<simd.I8x16>(1i8)\n  let w = simd.add<simd.I8x16>(big, one)\n'
            '  if w.l0 != -128i8 { return 1u32 }\n  if w.l15 != -128i8 { return 2u32 }\n'
            '  let m = simd.splat<simd.U8x16>(255u8)\n  let p = simd.mul<simd.U8x16>(m, m)\n  if p.l7 != 1u8 { return 3u32 }\n'
            '  let z = simd.splat<simd.U64x2>(0u64)\n  let s = simd.sub<simd.U64x2>(z, simd.splat<simd.U64x2>(1u64))\n  if s.l1 != 18446744073709551615u64 { return 4u32 }\n'
            '  if simd.reduce_add<simd.U8x16>(m) != 240u8 { return 5u32 }\n'
            '  return 42u32\n}\n'))

    def test_bool_equality_means_the_same_in_the_evaluator_and_natively(self):
        # found by the mask oracle: the checker admits `bool == bool` and native code computes it, but the evaluator refused it (E_TYPE: tipo no entero)
        self.both(self.source(
            'module t\nfunc main() u32 {\n  let t = 1u32 == 1u32\n  let f = 2u32 == 3u32\n'
            '  if t == f { return 1u32 }\n  if !(t != f) { return 2u32 }\n  if f != (4u32 == 5u32) { return 3u32 }\n  if !(t == (6u32 == 6u32)) { return 4u32 }\n  return 42u32\n}\n'))

    def test_a_lane_is_a_field_so_extract_and_insert_need_no_intrinsic(self):
        self.both(self.source(
            'module t\nimport simd "simd.omni"\nfunc main() u32 {\n'
            '  let v = simd.U32x4 { l0: 10u32, l1: 20u32, l2: 30u32, l3: 40u32 }\n'
            '  let w = simd.U32x4 { l0: v.l0, l1: 99u32, l2: v.l2, l3: v.l3 }\n'
            '  let s = simd.add<simd.U32x4>(v, w)\n  if s.l1 != 119u32 { return 1u32 }\n  if s.l3 != 80u32 { return 2u32 }\n  return 42u32\n}\n'))


class SimdMemoryModelTests(ContainerCase):
    """Loads and stores over the evaluator's raw memory (the freestanding guest repeats them on real hardware)."""
    def setUp(self):
        super().setUp()
        shutil.copy(STORAGE / 'simd.omni', self.dir / 'simd.omni')

    def run_eval(self, body, expected=42):
        path = self.dir / 'mem.omni'
        path.write_text('module t\nimport simd "simd.omni"\nfunc main() u32 !{memory.raw} {\n' + body + '}\n', encoding='utf-8')
        done = proc(OMNI, 'eval', path)
        self.assertEqual(done.returncode, expected, done.stderr)
        return done

    def test_loads_read_lanes_in_little_endian_order_and_stores_write_exactly_the_vector(self):
        self.run_eval(
            '  let g1 u32 = raw.store32(4097u64 - 1u64 + 16u64, 3735928559u32)\n'
            '  let a u32 = raw.store64(4096u64, 578437695752307201u64)\n  let b u32 = raw.store64(4104u64, 1157159078456920585u64)\n'
            '  let v = simd.load<simd.U8x16>(4096u64)\n'
            '  if v.l0 != 1u8 { return 1u32 }\n  if v.l7 != 8u8 { return 2u32 }\n  if v.l8 != 9u8 { return 3u32 }\n  if v.l15 != 16u8 { return 4u32 }\n'
            '  let w = simd.load<simd.U32x4>(4097u64)\n  if w.l0 != 84148994u32 { return 5u32 }\n'               # unaligned: bytes 2..5 = 02 03 04 05 little endian
            '  let guard u32 = raw.store32(8208u64, 4294967295u32)\n'
            '  let doubled = simd.add<simd.U8x16>(v, v)\n  let s u32 = simd.store<simd.U8x16>(8192u64, doubled)\n'
            '  if raw.load32(8192u64) != 134611970u32 { return 6u32 }\n  if raw.load64(8200u64) != 2314318156913841170u64 { return 7u32 }\n'
            '  if raw.load32(8208u64) != 4294967295u32 { return 8u32 }\n'                                             # nothing past the vector was written
            '  return 42u32\n')

    def test_the_evaluator_refuses_a_null_address_and_a_misaligned_aligned_form(self):
        for body in ('  let v = simd.load<simd.U32x4>(0u64)\n  return 0u32\n', '  let v = simd.load_aligned<simd.U32x4>(4104u64)\n  return 0u32\n',
                     '  let s u32 = simd.store_aligned<simd.U32x4>(4104u64, simd.splat<simd.U32x4>(1u32))\n  return 0u32\n'):
            with self.subTest(body):
                done = self.run_eval(body, expected=2)
                self.assertIn(b'E_LAYOUT', done.stderr)
        self.run_eval('  let v = simd.load_aligned<simd.U32x4>(4112u64)\n  if v.l0 != 0u32 { return 1u32 }\n  return 42u32\n')


class SimdGuestTests(X64Harness):
    def setUp(self):
        super().setUp()
        shutil.copy(STORAGE / 'simd.omni', self.dir / 'simd.omni')

    def test_the_whole_oracle_runs_in_a_freestanding_sse2_image(self):
        program, _ = build_program(guest=True)
        path = self.dir / 'simd_guest.omni'
        path.write_text(program, encoding='utf-8')
        rc, serial = self.boot(self.build(path, emit_args=('--target-isa', 'sse2'), sse=True))
        self.assertEqual((rc, serial.split('\n')[:-1]), (1, ['0']), serial)         # no case disagreed with the oracle
        machine = self.sh('objdump', '-d', '--no-show-raw-insn', '-M', 'intel', 'payload.elf').stdout.decode()
        for instruction in ('paddb', 'paddw', 'paddd', 'paddq', 'psubb', 'pcmpeqd', 'pcmpgtd', 'pand', 'por', 'pxor'):
            self.assertIn(instruction, machine)                   # real SSE2 vector instructions were emitted

    def test_loads_stores_alignment_and_the_trap_in_the_guest(self):
        path = self.dir / 'simd_mem.omni'
        path.write_text(
            'module t\nimport rt "rt.omni"\nimport simd "simd.omni"\n'
            'func main() u32 !{io.print,memory.raw,port.io,cpu.control} {\n'
            '  let a u32 = raw.store64(5373952u64, 578437695752307201u64)\n  let b u32 = raw.store64(5373960u64, 1157159078456920585u64)\n'
            '  let v = simd.load_aligned<simd.U8x16>(5373952u64)\n  print(u32(v.l0) + u32(v.l15) * 256u32)\n'
            '  let w = simd.load<simd.U32x4>(5373953u64)\n  print(w.l0)\n'
            '  let doubled = simd.add<simd.U8x16>(v, v)\n  let s u32 = simd.store<simd.U8x16>(5374080u64, doubled)\n  print(raw.load32(5374080u64))\n'
            '  let t = simd.load_aligned<simd.U32x4>(5373960u64)\n  print(777u32)\n  return rt.finish(0u32)\n}\n', encoding='utf-8')
        rc, serial = self.boot(self.build(path, emit_args=('--target-isa', 'sse2'), sse=True))
        lines = serial.split('\n')[:-1]
        self.assertEqual(lines[:3], ['4097', '84148994', '134611970'], serial)         # lane 0 = 1, lane 15 = 16 (16 * 256 + 1), the unaligned load, the stored doubled vector
        self.assertEqual(lines[3:], ['TRAP 14'], serial)                              # the aligned form on an address that is not 16-aligned traps, and 777 never prints
        self.assertEqual(rc, (64 + 14) * 2 + 1, serial)                                 # the provider's trap exit value

    def test_address_zero_is_never_a_vector_and_every_lane_access_is_volatile(self):
        path = self.dir / 'simd_null.omni'
        path.write_text(
            'module t\nimport rt "rt.omni"\nimport simd "simd.omni"\n'
            'func main() u32 !{io.print,memory.raw,port.io,cpu.control} {\n'
            '  let a = simd.splat<simd.U8x16>(7u8)\n  let s1 u32 = simd.store<simd.U8x16>(5374080u64, a)\n  let s2 u32 = simd.store<simd.U8x16>(5374080u64, a)\n  print(1u32)\n'
            '  let v = simd.load<simd.U32x4>(0u64)\n  print(777u32)\n  return rt.finish(0u32)\n}\n', encoding='utf-8')
        emitted = self.emit(path, extra=('--target-isa', 'sse2'))
        self.assertEqual(emitted.returncode, 0, emitted.stderr)
        ir = (self.dir / 'prog.ll').read_text(encoding='utf-8')
        self.assertEqual(ir.count('store volatile i8'), 32)                           # two stores of 16 lanes: none can be merged or dropped by the optimizer
        self.assertNotRegex(ir, r'\n\s+store i8 ')
        rc, serial = self.boot(self.build(path, emit_args=('--target-isa', 'sse2'), sse=True))
        self.assertEqual((rc, serial.split('\n')[:-1]), ((64 + 14) * 2 + 1, ['1', 'TRAP 14']), serial)    # the null address traps (14) before any lane is read

    def test_a_general_register_image_and_the_i386_profile_refuse_the_intrinsics(self):
        path = self.dir / 'gpr.omni'
        path.write_text('module t\nimport rt "rt.omni"\nimport simd "simd.omni"\nfunc main() u32 !{port.io,cpu.control} {\n'
                        '  let a = simd.splat<simd.U32x4>(1u32)\n  let b = simd.add<simd.U32x4>(a, a)\n  return rt.finish(b.l0)\n}\n', encoding='utf-8')
        refused = self.emit(path)
        self.assertEqual(refused.returncode, 2, refused.stderr)
        self.assertIn(b'E_TARGET_PROFILE', refused.stderr)
        self.assertIn(b'--target-isa sse2', refused.stderr)
        self.assertFalse((self.dir / 'prog.ll').exists())
        self.assertEqual(self.emit(path, extra=('--target-isa', 'sse2')).returncode, 0)
        import os, subprocess
        (self.dir / 'boot.omni').write_text('module boot\npub func enter() u32 { return 0u32 }\n', encoding='utf-8')
        (self.dir / 'i386.omni').write_text('module t\nimport boot "boot.omni"\nimport simd "simd.omni"\nfunc main() u32 {\n  let a = simd.splat<simd.U32x4>(1u32)\n  return a.l0 + boot.enter()\n}\n', encoding='utf-8')
        i386 = subprocess.run([str(OMNI), 'emit-llvm', str(self.dir / 'i386.omni'), '--target-profile', 'baremetal-i386-boot', '--service-module', 'boot', '--entry-section', '.text.omni_entry', '--entry-address', '1048576',
                               '-o', str(self.dir / 'i386.ll')], capture_output=True, cwd=self.dir, env={**os.environ, 'OMNI_HOME': str(ROOT)}, timeout=60)
        self.assertEqual(i386.returncode, 2, i386.stderr)
        self.assertIn(b'E_TARGET_PROFILE', i386.stderr)


class EntryAlignmentTests(X64Harness):
    """`omni_boot_entry` is an ordinary function that never returns and the compiler assumes the SysV rule at its entry (rsp = 8 mod 16). The conformance loader honours it; a loader that jumps in
    with an aligned stack (`--defsym ALIGNED_ENTRY=1`) makes the first 16-byte stack slot of a vector spill fault with #GP: the contrast that shows why the rule is part of the profile contract."""
    PROGRAM = ('module t\nimport rt "rt.omni"\nimport simd "simd.omni"\n'
               'func main() u32 !{io.print,memory.raw,port.io,cpu.control} {\n'
               '  let a u32 = raw.store64(5373952u64, 578437695752307201u64)\n  let b u32 = raw.store64(5373960u64, 1157159078456920585u64)\n'
               '  let v = simd.load<simd.U8x16>(5373952u64)\n  print(u32(v.l0) + u32(v.l15) * 256u32)\n'
               '  let doubled = simd.add<simd.U8x16>(v, v)\n  print(1u32)\n  let s u32 = simd.store<simd.U8x16>(5374080u64, doubled)\n  print(2u32)\n  print(raw.load32(5374080u64))\n'
               '  return rt.finish(0u32)\n}\n')

    def build_with(self, defsyms):
        shutil.copy(STORAGE / 'simd.omni', self.dir / 'simd.omni')
        path = self.dir / 'entry.omni'
        path.write_text(self.PROGRAM, encoding='utf-8')
        emitted = self.emit(path, extra=('--target-isa', 'sse2'))
        self.assertEqual(emitted.returncode, 0, emitted.stderr)
        self.sh('clang', *self.SSE_CFLAGS, '-c', 'prog.ll', '-o', 'prog.o')
        self.sh('ld', '-m', 'elf_x86_64', '-nostdlib', '--gc-sections', '-T', 'payload.ld', 'prog.o', '-o', 'payload.elf')
        self.sh('objcopy', '-O', 'binary', 'payload.elf', 'payload.bin')
        self.sh('as', '--32', '--defsym', 'AP_ENTRY=0', '--defsym', 'SSE=1', *defsyms, '-I', '.', 'boot64.S', '-o', 'boot.o')
        self.sh('ld', '-m', 'elf_i386', '-nostdlib', '-T', 'link32.ld', 'boot.o', '-o', 'boot.elf')
        return self.dir / 'boot.elf'

    def test_an_image_entered_as_if_called_spills_vectors_and_one_entered_aligned_faults(self):
        rc, serial = self.boot(self.build_with(()))
        self.assertEqual((rc, serial.split('\n')[:-1]), (1, ['4097', '1', '2', '134611970']), serial)
        rc, serial = self.boot(self.build_with(('--defsym', 'ALIGNED_ENTRY=1')))
        self.assertEqual(serial.split('\n')[:-1], ['4097', '1'], serial)             # the store of the doubled vector faulted: nothing after it ran
        self.assertNotEqual(rc, 1)


class SimdCheckerTests(ContainerCase):
    def setUp(self):
        super().setUp()
        shutil.copy(STORAGE / 'simd.omni', self.dir / 'simd.omni')

    def check(self, text, name='bad.omni'):
        path = self.dir / name
        path.write_text('module t\nimport simd "simd.omni"\n' + text, encoding='utf-8')
        return proc(OMNI, 'check', path)

    def test_what_is_not_a_vector_or_not_a_mask_is_refused_with_the_reason(self):
        shapes = (
            'struct Three { l0 u32, l1 u32, l2 u32 }\n'
            'struct Narrow { l0 u32, l1 u32 }\n'
            'struct Mixed { l0 u32, l1 u16, l2 u16, l3 u32 }\n'
            'struct Text4 { l0 Text, l1 Text, l2 Text, l3 Text }\n'
            'struct Bools3 { l0 bool, l1 bool, l2 bool }\n'
            'struct Mask2 { l0 bool, l1 bool }\n')
        cases = [
            ('three lanes', 'func main() u32 {\n  let v = Three { l0: 1u32, l1: 2u32, l2: 3u32 }\n  let w = simd.add<Three>(v, v)\n  return 0u32\n}\n', b'E_SIMD', b'2, 4, 8 o 16'),
            ('not 128 bits', 'func main() u32 {\n  let v = Narrow { l0: 1u32, l1: 2u32 }\n  let w = simd.add<Narrow>(v, v)\n  return 0u32\n}\n', b'E_SIMD', b'128 bits'),
            ('mixed lanes', 'func main() u32 {\n  let v = Mixed { l0: 1u32, l1: 2u16, l2: 3u16, l3: 4u32 }\n  let w = simd.add<Mixed>(v, v)\n  return 0u32\n}\n', b'E_SIMD', b'mismo tipo'),
            ('text lanes', 'func main() u32 {\n  let v = Text4 { l0: "a", l1: "b", l2: "c", l3: "d" }\n  let w = simd.add<Text4>(v, v)\n  return 0u32\n}\n', b'E_SIMD', b'enteros'),
            ('a mask where a vector is needed', 'func main() u32 {\n  let m = Mask2 { l0: true, l1: false }\n  let w = simd.add<Mask2>(m, m)\n  return 0u32\n}\n', b'E_SIMD', b'mascara'),
            ('a vector where a mask is needed', 'func main() u32 {\n  let v = simd.splat<simd.U32x4>(1u32)\n  let b = simd.any<simd.U32x4>(v)\n  return 0u32\n}\n', b'E_SIMD', b'opera sobre una mascara'),
            ('a mask of another lane count', 'func main() u32 {\n  let v = simd.splat<simd.U32x4>(1u32)\n  let m = simd.eq<simd.U32x4, simd.M16x8>(v, v)\n  return 0u32\n}\n', b'E_SIMD', b'distinto numero'),
            ('a comparison without the mask type', 'func main() u32 {\n  let v = simd.splat<simd.U32x4>(1u32)\n  let m = simd.eq<simd.U32x4>(v, v)\n  return 0u32\n}\n', b'E_SIMD', b'<Vector,Mascara>'),
            ('the second type of a comparison is not a mask', 'func main() u32 {\n  let v = simd.splat<simd.U32x4>(1u32)\n  let m = simd.eq<simd.U32x4, simd.U32x4>(v, v)\n  return 0u32\n}\n', b'E_SIMD', b'debe ser una mascara'),
            ('division of integers', 'func main() u32 {\n  let v = simd.splat<simd.U32x4>(1u32)\n  let w = simd.div<simd.U32x4>(v, v)\n  return 0u32\n}\n', b'E_SIMD', b'f32/f64'),
            ('bit operation on floats', 'func main() u32 {\n  let v = simd.splat<simd.F32x4>(1.0f32)\n  let w = simd.and<simd.F32x4>(v, v)\n  return 0u32\n}\n', b'E_SIMD', b'enteros'),
            ('an unknown operation', 'func main() u32 {\n  let v = simd.splat<simd.U32x4>(1u32)\n  let w = simd.shuffle<simd.U32x4>(v, v)\n  return 0u32\n}\n', b'E_SIMD', b'desconocida'),
            ('two operands of different vector types', 'func main() u32 {\n  let v = simd.splat<simd.U32x4>(1u32)\n  let w = simd.splat<simd.I32x4>(1i32)\n  let s = simd.add<simd.U32x4>(v, w)\n  return 0u32\n}\n', b'E_TYPE', None),
            ('splat of the wrong lane type', 'func main() u32 {\n  let v = simd.splat<simd.U32x4>(1u64)\n  return 0u32\n}\n', b'E_TYPE', None),
            ('wrong arity', 'func main() u32 {\n  let v = simd.splat<simd.U32x4>(1u32)\n  let s = simd.add<simd.U32x4>(v)\n  return 0u32\n}\n', b'E_ARITY', None),
            ('a load without memory.raw', 'func main() u32 {\n  let v = simd.load<simd.U32x4>(4096u64)\n  return 0u32\n}\n', b'E_CAPABILITY', None),
            ('a store without memory.raw', 'func main() u32 {\n  let v u32 = simd.store<simd.U32x4>(4096u64, simd.splat<simd.U32x4>(1u32))\n  return 0u32\n}\n', b'E_CAPABILITY', None),
            ('a load at a non-u64 address', 'func main() u32 !{memory.raw} {\n  let v = simd.load<simd.U32x4>(4096u32)\n  return 0u32\n}\n', b'E_TYPE', None),
            ('a type argument that is not a struct', 'func main() u32 {\n  let v = simd.splat<u32>(1u32)\n  return 0u32\n}\n', b'E_SIMD', None),
        ]
        for label, body, code, why in cases:
            with self.subTest(label):
                done = self.check(shapes + body)
                self.assertEqual(done.returncode, 2, (label, done.stderr))
                self.assertIn(code, done.stderr, (label, done.stderr))
                if why:
                    self.assertIn(why, done.stderr, (label, done.stderr))

    def test_a_private_vector_type_of_another_module_is_not_usable(self):
        (self.dir / 'lib.omni').write_text('module lib\nstruct Hidden { l0 u32, l1 u32, l2 u32, l3 u32 }\npub func mk() u32 { return 0u32 }\n', encoding='utf-8')
        path = self.dir / 'priv.omni'
        path.write_text('module t\nimport lib "lib.omni"\nfunc main() u32 {\n  let v = simd.splat<lib.Hidden>(1u32)\n  return 0u32\n}\n'.replace('module t\n', 'module t\nimport simd "simd.omni"\n', 1), encoding='utf-8')
        done = proc(OMNI, 'check', path)
        self.assertEqual(done.returncode, 2, done.stderr)
        self.assertIn(b'E_VISIBILITY', done.stderr)

    def test_a_user_defined_record_of_the_right_shape_is_a_vector_too(self):
        path = self.dir / 'own.omni'
        path.write_text('module t\nstruct Quad { x u32, y u32, z u32, w u32 }\nstruct Flags { a bool, b bool, c bool, d bool }\n'
                        'func main() u32 {\n  let q = simd.splat<Quad>(3u32)\n  let r = simd.add<Quad>(q, q)\n  let m = simd.eq<Quad, Flags>(q, r)\n  if simd.any<Flags>(m) { return 1u32 }\n  if r.w != 6u32 { return 2u32 }\n  return 42u32\n}\n', encoding='utf-8')
        self.assertEqual(proc(OMNI, 'eval', path).returncode, 42)


class SimdRepresentationTests(ContainerCase):
    PROGRAM = ('module t\nimport simd "simd.omni"\nfunc main() u32 {\n  let a = simd.splat<simd.I32x4>(3i32)\n  let b = simd.splat<simd.I32x4>(5i32)\n'
               '  let m = simd.lt<simd.I32x4, simd.M32x4>(a, b)\n  let c = simd.select<simd.I32x4, simd.M32x4>(m, a, b)\n  return u32(c.l2) + 39u32\n}\n')

    def setUp(self):
        super().setUp()
        shutil.copy(STORAGE / 'simd.omni', self.dir / 'simd.omni')
        self.path = self.dir / 'rep.omni'
        self.path.write_text(self.PROGRAM, encoding='utf-8')

    def test_the_program_is_wave21_and_every_representation_round_trips_it(self):
        wave = proc(OMNI, 'wave', self.path)
        self.assertEqual(wave.returncode, 0, wave.stderr)
        self.assertTrue(wave.stdout.startswith(b'(omni-wave 21'), wave.stdout[:20])
        self.assertIn(b'simd.lt<simd.I32x4,simd.M32x4>', wave.stdout)
        owave = self.dir / 'rep.owave'
        owave.write_bytes(wave.stdout)
        self.assertEqual(proc(OMNI, 'eval', owave).returncode, 42)
        wire = self.dir / 'rep.owire'
        self.assertEqual(proc(OMNI, 'pack', self.path, '-o', wire).returncode, 0)
        self.assertEqual(proc(OMNI, 'eval', wire).returncode, 42)
        formatted = proc(OMNI, 'fmt', self.path)
        self.assertEqual(formatted.returncode, 0, formatted.stderr)
        self.assertIn(b'simd.lt<simd.I32x4,simd.M32x4>', formatted.stdout)
        again = self.dir / 'again.omni'
        again.write_bytes(formatted.stdout)
        self.assertEqual(proc(OMNI, 'eval', again).returncode, 42)
        self.assertEqual(proc(OMNI, 'fmt', again).stdout, formatted.stdout)

    def test_a_reader_older_than_wave21_refuses_it(self):
        wave = proc(OMNI, 'wave', self.path).stdout
        wire = self.dir / 'rep.owire'
        self.assertEqual(proc(OMNI, 'pack', self.path, '-o', wire).returncode, 0)
        for old in (18, 19, 20):
            relabelled = self.dir / ('as-wave%d.owave' % old)
            relabelled.write_bytes(wave.replace(b'(omni-wave 21', ('(omni-wave %d' % old).encode(), 1))
            refused = proc(OMNI, 'check', relabelled)
            self.assertEqual(refused.returncode, 2, (old, refused.stderr))
            self.assertIn(b'E_VERSION', refused.stderr)
            data = bytearray(wire.read_bytes()); data[4] = old
            older = self.dir / ('as-omc%d.owire' % old)
            older.write_bytes(bytes(data))
            self.assertEqual(proc(OMNI, 'check', older).returncode, 2, old)

    def test_the_machine_identity_of_the_program_says_it_uses_vectors(self):
        plain = self.dir / 'plain.omni'
        plain.write_text('module t\nfunc main() u32 { return 42u32 }\n', encoding='utf-8')
        self.assertNotEqual(proc(OMNI, 'hash', self.path).stdout, proc(OMNI, 'hash', plain).stdout)


if __name__ == '__main__':
    unittest.main()
