#!/usr/bin/env python3
"""CP-08 / MN-05 (spec/REGISTER_FIELDS_CANDIDATE.md, examples/storage/bitfield.omni and field.omni): typed bit fields of a register.

PURE   mask / get / put over register values, checked against Python for many (shift, width) pairs, edge values and random values; a layout is asserted at compile time with static_assert
       (`fits`, `disjoint`), so a field that falls outside its register or overlaps another does not compile. Hosted native, evaluator and compile time agree.
MODEL  (evaluator over a RAM region): `update` changes ONE field and keeps every other bit; `clear` of a write-1-to-clear register stores exactly the field mask; a value that does not fit the
       field is refused and nothing is written.
TYPES  a field of a register is reachable only through what the register allows (E_GENERIC_CONSTRAINT otherwise).
EMULATION  (QEMU TCG): the local APIC's task-priority register: a priority class and a sub-class, changed independently.
"""
from __future__ import annotations
import random
import shutil
import unittest
from cp02_borrowed_containers import ContainerCase
from cp08_mmio import RamCase, reg, RAM, STORAGE
from language_0_8_3_alpha8 import OMNI, proc, X64Harness

RNG = random.Random(20261022)


def field(name, shift, width):
    return ('struct %s { tag u32 }\nimpl bitfield.Field for %s {\n  func shift() u32 { return %du32 }\n  func width() u32 { return %du32 }\n}\n' % (name, name, shift, width))


class PureCase(ContainerCase):
    def setUp(self):
        super().setUp()
        shutil.copy(STORAGE / 'bitfield.omni', self.dir / 'bitfield.omni')

    def source(self, text, name='program.omni'):
        path = self.dir / name
        path.write_text('module t\nimport bitfield "bitfield.omni"\n' + text, encoding='utf-8')
        return path


class FieldPureTests(PureCase):
    PAIRS = [(0, 1), (31, 1), (0, 32), (1, 3), (4, 4), (8, 8), (16, 16), (7, 17), (0, 8), (24, 8), (3, 1), (32, 32), (0, 64), (20, 44), (63, 1)]

    def test_mask_get_and_put_match_python(self):
        text = ''
        calls = []
        n = 0
        for i, (shift, width) in enumerate(self.PAIRS):
            text += field('F%d' % i, shift, width)
            mask = ((1 << width) - 1) << shift
            for k, v in enumerate([0, (1 << 64) - 1, 0xA5A5A5A5A5A5A5A5] + [RNG.getrandbits(64) for _ in range(4)]):
                n += 1
                got = (v & mask) >> shift
                body = ['  if bitfield.mask<F%d>() != %du64 { return 1u32 }' % (i, mask), '  if bitfield.get<F%d>(%du64) != %du64 { return 2u32 }' % (i, v, got)]
                for j, x in enumerate(sorted({0, (1 << width) - 1, RNG.getrandbits(width)})):
                    expected = (v & ~mask & ((1 << 64) - 1)) | (x << shift)
                    body.append('  let p%d = bitfield.put<F%d>(%du64, %du64)\n  match p%d { Ok(r) { if r != %du64 { return 3u32 } } Err(e) { return 4u32 } }' % (j, i, v, x, j, expected))
                text += 'func check_%d() u32 {\n%s\n  return 0u32\n}\n' % (n, '\n'.join(body))
                calls.append('  if check_%d() != 0u32 { return %du32 }' % (n, 1 + n % 40))
            text += 'func limits_%d() u32 {\n  if bitfield.limit<F%d>() != %du64 { return 1u32 }\n' % (i, i, (1 << width) - 1)
            if width < 64:
                text += ('  let big = bitfield.put<F%d>(0u64, %du64)\n  match big { Ok(r) { return 2u32 } Err(e) { if e != 1u32 { return 3u32 } } }\n' % (i, 1 << width))
            text += '  return 0u32\n}\n'
            calls.append('  if limits_%d() != 0u32 { return %du32 }' % (i, 41 + i % 3))
        self.both(self.source(text + 'func main() u32 {\n' + '\n'.join(calls) + '\n  return 42u32\n}\n'))

    def test_the_layout_of_a_register_is_checked_when_the_program_is_compiled(self):
        layout = (field('Enable', 0, 1) + field('Mode', 1, 3) + field('Irq', 7, 1) + field('Size', 16, 16) +
                  'static_assert(bitfield.fits<Enable>(32u32) && bitfield.fits<Mode>(32u32) && bitfield.fits<Irq>(32u32) && bitfield.fits<Size>(32u32), "all fields lie inside the 32-bit register")\n'
                  'static_assert(bitfield.disjoint<Enable, Mode>() && bitfield.disjoint<Mode, Irq>() && bitfield.disjoint<Irq, Size>() && bitfield.disjoint<Enable, Size>(), "no two fields share a bit")\n'
                  'static_assert(bitfield.mask<Size>() == 4294901760u64, "size is the upper half")\n')
        self.both(self.source(layout + 'func main() u32 { return 42u32 }\n'))
        bad = [
            ('a field beyond its register', field('Wide', 28, 8) + 'static_assert(bitfield.fits<Wide>(32u32), "wide fits")\n'),
            ('a field of zero width', field('Empty', 3, 0) + 'static_assert(bitfield.fits<Empty>(32u32), "empty fits")\n'),
            ('two fields that overlap', field('A', 0, 4) + field('B', 3, 4) + 'static_assert(bitfield.disjoint<A, B>(), "A and B are disjoint")\n'),
            ('a field that starts outside the register', field('Late', 40, 2) + 'static_assert(bitfield.fits<Late>(32u32), "late fits")\n'),
            ('a field one bit past the end', field('Over', 28, 5) + 'static_assert(bitfield.fits<Over>(32u32), "over fits")\n'),
            ('a register wider than 64 bits', field('Top', 60, 5) + 'static_assert(bitfield.fits<Top>(65u32), "65 bits")\n'),
            ('a register of no bits', field('One', 0, 1) + 'static_assert(bitfield.fits<One>(0u32), "0 bits")\n'),
        ]
        for label, text in bad:
            with self.subTest(label):
                checked = proc(OMNI, 'check', self.source(text + 'func main() u32 { return 0u32 }\n', 'layout.omni'))
                self.assertEqual(checked.returncode, 2, (label, checked.stderr))
                self.assertIn(b'E_STATIC_ASSERT', checked.stderr, label)

    def test_the_edges_of_a_valid_field_are_valid(self):
        self.both(self.source(
            field('Last', 31, 1) + field('Whole', 0, 32) + field('Top', 63, 1) + field('Everything', 0, 64) +
            'static_assert(bitfield.fits<Last>(32u32) && bitfield.fits<Whole>(32u32), "the edges of 32 bits")\n'
            'static_assert(bitfield.fits<Top>(64u32) && bitfield.fits<Everything>(64u32), "the edges of 64 bits")\n'
            'func main() u32 { return 42u32 }\n'))

    def test_an_invalid_field_changes_nothing_at_run_time(self):
        self.both(self.source(
            field('Wide', 60, 8) + 'func main() u32 {\n  if bitfield.mask<Wide>() != 0u64 { return 1u32 }\n  if bitfield.get<Wide>(4294967295u64) != 0u64 { return 2u32 }\n'
            '  let p = bitfield.put<Wide>(77u64, 1u64)\n  match p { Ok(r) { return 3u32 } Err(e) { if e != 2u32 { return 4u32 } } }\n  return 42u32\n}\n'))


class FieldCase(RamCase):
    def setUp(self):
        super().setUp()
        shutil.copy(STORAGE / 'bitfield.omni', self.dir / 'bitfield.omni')
        shutil.copy(STORAGE / 'field.omni', self.dir / 'field.omni')

    def source(self, text, name='program.omni'):
        return super().source('import bitfield "bitfield.omni"\nimport field "field.omni"\n' + text, name)


class FieldModelTests(FieldCase):
    REGS = (RAM + reg('Ctl', 0, 4, 'Readable', 'Writable', 'ReadWrite') + reg('Sts', 4, 4, 'Readable', 'W1C') + reg('Cmd', 8, 4, 'Writable') +
            field('Enable', 0, 1) + field('Mode', 1, 3) + field('Irq', 7, 1) + field('Size', 16, 16) + field('Fault', 2, 2))

    def run_model(self, body):
        self.run_eval(self.REGS + 'func main() u32 !{memory.raw} {\n  var code u32 = 0u32\n  let mp = mmio.map<Ram>()\n  match mp { Ok(m) {\n' + body +
                      '    let u = mmio.unmap<Ram>(move(m))\n  } Err(e) { code = 99u32 } }\n  if code != 0u32 { return code }\n  return 42u32\n}\n')

    def test_update_changes_one_field_and_keeps_every_other_bit_and_read_sees_it(self):
        reserved = 0xFF70          # bits 4-6 and 8-15 belong to no field: they must survive every update
        size = 0xABCD
        self.run_model(
            '    let w = mmio.write<Ram,Ctl>(borrow_mut(m), %du64)\n    match w { Ok(d) { } Err(e) { code = 1u32 } }\n' % reserved +
            '    let a = field.update<Ram,Ctl,Mode>(borrow_mut(m), 5u64)\n    match a { Ok(old) { if old != %du64 { code = 2u32 } } Err(e) { code = 3u32 } }\n' % reserved +
            '    let b = field.update<Ram,Ctl,Size>(borrow_mut(m), %du64)\n    match b { Ok(old) { if old != %du64 { code = 4u32 } } Err(e) { code = 5u32 } }\n' % (size, reserved | 10) +
            '    let c = field.update<Ram,Ctl,Enable>(borrow_mut(m), 1u64)\n    match c { Ok(old) { } Err(e) { code = 6u32 } }\n'
            '    let whole = mmio.read<Ram,Ctl>(borrow(m))\n    match whole { Ok(v) { if v != %du64 { code = 7u32 } } Err(e) { code = 8u32 } }\n' % ((size << 16) | reserved | 11) +
            '    let mode = field.read<Ram,Ctl,Mode>(borrow(m))\n    match mode { Ok(v) { if v != 5u64 { code = 9u32 } } Err(e) { code = 10u32 } }\n'
            '    let sz = field.read<Ram,Ctl,Size>(borrow(m))\n    match sz { Ok(v) { if v != %du64 { code = 11u32 } } Err(e) { code = 12u32 } }\n' % size +
            '    let off = field.update<Ram,Ctl,Mode>(borrow_mut(m), 0u64)\n    match off { Ok(old) { } Err(e) { code = 13u32 } }\n'
            '    let after = mmio.read<Ram,Ctl>(borrow(m))\n    match after { Ok(v) { if v != %du64 { code = 14u32 } } Err(e) { code = 15u32 } }\n' % ((size << 16) | reserved | 1))

    def test_a_value_that_does_not_fit_the_field_is_refused_and_nothing_is_written(self):
        self.run_model(
            '    let w = mmio.write<Ram,Ctl>(borrow_mut(m), 255u64)\n    match w { Ok(d) { } Err(e) { code = 1u32 } }\n'
            '    let big = field.update<Ram,Ctl,Mode>(borrow_mut(m), 8u64)\n    match big { Ok(old) { code = 2u32 } Err(e) { if e != 1u32 { code = 3u32 } } }\n'
            '    let after = mmio.read<Ram,Ctl>(borrow(m))\n    match after { Ok(v) { if v != 255u64 { code = 4u32 } } Err(e) { code = 5u32 } }\n')

    def test_clearing_a_field_of_a_write_one_to_clear_register_is_one_store_of_the_mask(self):
        self.run_model(
            # RAM has no side effects: what is stored stays. A clear that read-modified-wrote would leave the old bits in memory; one store of the mask leaves exactly the mask.
            '    let seed = mmio.clear<Ram,Sts>(borrow_mut(m), 4294967295u64)\n    match seed { Ok(d) { } Err(e) { code = 1u32 } }\n'
            '    let c = field.clear<Ram,Sts,Fault>(borrow_mut(m))\n    match c { Ok(d) { } Err(e) { code = 2u32 } }\n'
            '    let raw_value = mmio.read<Ram,Sts>(borrow(m))\n    match raw_value { Ok(v) { if v != 12u64 { code = 3u32 } } Err(e) { code = 4u32 } }\n')

    def test_what_the_register_does_not_allow_is_not_reachable_through_its_fields(self):
        head = self.REGS + 'func main() u32 !{memory.raw} {\n  let mp = mmio.map<Ram>()\n  match mp { Ok(m) {\n'
        tail = '    let u = mmio.unmap<Ram>(move(m))\n  } Err(e) { return e } }\n  return 0u32\n}\n'
        cases = [
            ('reading a field of a write-only register', '    let r = field.read<Ram,Cmd,Mode>(borrow(m))\n    match r { Ok(v) { } Err(e) { } }\n', b'E_GENERIC_CONSTRAINT'),
            ('updating a field of a register that cannot be changed in place', '    let r = field.update<Ram,Sts,Mode>(borrow_mut(m), 1u64)\n    match r { Ok(v) { } Err(e) { } }\n', b'E_GENERIC_CONSTRAINT'),
            ('clearing a field of a register that is not write-1-to-clear', '    let r = field.clear<Ram,Ctl,Mode>(borrow_mut(m))\n    match r { Ok(v) { } Err(e) { } }\n', b'E_GENERIC_CONSTRAINT'),
            ('a type that is not a field', '    let r = field.read<Ram,Ctl,Ram>(borrow(m))\n    match r { Ok(v) { } Err(e) { } }\n', b'E_GENERIC_CONSTRAINT'),
            ('updating through a plain lend', '    let r = field.update<Ram,Ctl,Mode>(borrow(m), 1u64)\n    match r { Ok(v) { } Err(e) { } }\n', None),
        ]
        for label, body, code in cases:
            with self.subTest(label):
                path = self.source(head + body + tail, 'bad.omni')
                checked = proc(OMNI, 'check', path)
                self.assertEqual(checked.returncode, 2, (label, checked.stderr))
                if code:
                    self.assertIn(code, checked.stderr, (label, checked.stderr))


class FieldDeviceTests(X64Harness):
    def setUp(self):
        super().setUp()
        for name in ('addr', 'mmio', 'bitfield', 'field'):
            shutil.copy(STORAGE / (name + '.omni'), self.dir / (name + '.omni'))

    def test_the_apic_task_priority_register_is_changed_one_field_at_a_time(self):
        path = self.dir / 'tpr.omni'
        path.write_text(
            'module t\nimport rt "rt.omni"\nimport mmio "mmio.omni"\nimport bitfield "bitfield.omni"\nimport field "field.omni"\n'
            'struct Lapic { tag u32 }\nimpl mmio.Region for Lapic {\n  func base() u64 { return 4276092928u64 }\n  func size() u64 { return 4096u64 }\n}\n' +
            reg('Tpr', 128, 4, 'Readable', 'ReadWrite') + field('Class', 4, 4) + field('Sub', 0, 4) +
            'static_assert(bitfield.fits<Class>(8u32) && bitfield.fits<Sub>(8u32) && bitfield.disjoint<Class, Sub>(), "the task priority is eight bits: class and sub-class")\n'
            'func main() u32 !{io.print,memory.raw,port.io,cpu.control} {\n  let mp = mmio.map<Lapic>()\n  match mp { Ok(m) {\n'
            '    let a = field.update<Lapic,Tpr,Class>(borrow_mut(m), 5u64)\n    match a { Ok(old) { print(old) } Err(e) { print(900u32 + e) } }\n'
            '    let b = field.update<Lapic,Tpr,Sub>(borrow_mut(m), 3u64)\n    match b { Ok(old) { print(old) } Err(e) { print(900u32 + e) } }\n'
            '    let whole = mmio.read<Lapic,Tpr>(borrow(m))\n    match whole { Ok(v) { print(v) } Err(e) { print(900u32 + e) } }\n'
            '    let c = field.read<Lapic,Tpr,Class>(borrow(m))\n    match c { Ok(v) { print(v) } Err(e) { print(900u32 + e) } }\n'
            '    let s = field.read<Lapic,Tpr,Sub>(borrow(m))\n    match s { Ok(v) { print(v) } Err(e) { print(900u32 + e) } }\n'
            '    let over = field.update<Lapic,Tpr,Class>(borrow_mut(m), 16u64)\n    match over { Ok(old) { print(902u32) } Err(e) { print(e) } }\n'
            '    let u = mmio.unmap<Lapic>(move(m))\n  } Err(e) { print(800u32 + e) } }\n  return rt.finish(0u32)\n}\n', encoding='utf-8')
        rc, serial = self.boot(self.build(path))
        self.assertEqual((rc, serial.split('\n')[:-1]), (1, ['0', '80', '83', '5', '3', '1']), serial)


if __name__ == '__main__':
    unittest.main()
