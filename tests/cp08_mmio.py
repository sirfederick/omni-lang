#!/usr/bin/env python3
"""CP-08 rows 8.2, 8.4 and 8.5 (spec/MMIO_PORTS_CANDIDATE.md, examples/storage/mmio.omni): typed registers and ports with the permissions the device declares.

Three kinds of evidence, kept apart as the contract asks:
  MODEL      the evaluator over plain memory (a RAM region standing in for a device): the permissions, the widths, the ranges and the lifetime of a mapping. RAM has no side effects, so it
             cannot show that a device reacts; it can show exactly what the library stores and loads.
  ARTIFACT   the code that is emitted: a write-only or W1C operation reaches no load at all (no accidental read-modify-write), a plain read reaches no store.
  EMULATION  QEMU TCG as the device: the local APIC page (memory-mapped registers: read-only, read-write, write-only) and the 16550 UART (ports: read-write, and a read-CLEAR register - the
             interrupt identification register - whose second read differs from its first). This is an emulated device, not hardware.
"""
from __future__ import annotations
import re
import shutil
import unittest
from cp02_borrowed_containers import ContainerCase
from language_0_8_3_alpha8 import ROOT, OMNI, proc, X64Harness

STORAGE = ROOT / 'examples' / 'storage'

RAM = ('struct Ram { tag u32 }\nimpl mmio.Region for Ram {\n  func base() u64 { return 4194304u64 }\n  func size() u64 { return 256u64 }\n}\n')


def reg(name, off, width, *kinds):
    """A register type: `off` is the offset in the region for a memory-mapped register and the port number for a port register (the traits named Port...)."""
    out = 'struct %s { tag u32 }\n' % name
    for k in kinds:
        method = 'port' if k.startswith('Port') else 'offset'
        out += 'impl mmio.%s for %s {\n  func %s() u32 { return %du32 }\n  func width() u32 { return %du32 }\n}\n' % (k, name, method, off, width)
    return out


class RamCase(ContainerCase):
    def setUp(self):
        super().setUp()
        shutil.copy(STORAGE / 'addr.omni', self.dir / 'addr.omni')
        shutil.copy(STORAGE / 'mmio.omni', self.dir / 'mmio.omni')

    def source(self, text, name='program.omni'):
        return super().source('import mmio "mmio.omni"\n' + text, name)

    def run_eval(self, text, name='program.omni', expected=42):
        path = self.source(text, name)
        done = proc(OMNI, 'eval', path, timeout=180)
        self.assertEqual(done.returncode, expected, done.stderr)


class RegisterModelTests(RamCase):
    def test_every_width_stores_and_loads_exactly_its_bytes_and_its_neighbours_are_untouched(self):
        regs = (reg('R8', 0, 1, 'Readable', 'Writable') + reg('R16', 2, 2, 'Readable', 'Writable') + reg('R32', 4, 4, 'Readable', 'Writable') + reg('R64', 8, 8, 'Readable', 'Writable')
                + reg('Guard', 16, 8, 'Readable', 'Writable'))
        self.run_eval(RAM + regs +
            'func rd(m Borrow<mmio.Mapping<Ram>>) u64 !{memory.raw} {\n  let g = mmio.read<Ram,Guard>(m)\n  match g { Ok(v) { return v } Err(e) { return 4000000000u64 } }\n}\n'
            'func main() u32 !{memory.raw} {\n  var code u32 = 0u32\n  let mp = mmio.map<Ram>()\n  match mp { Ok(m) {\n'
            '    let g0 = mmio.write<Ram,Guard>(borrow_mut(m), 1311768467294899695u64)\n    match g0 { Ok(d) { } Err(e) { code = 1u32 } }\n'
            '    let a = mmio.write<Ram,R8>(borrow_mut(m), 171u64)\n    match a { Ok(d) { } Err(e) { code = 2u32 } }\n'
            '    let b = mmio.write<Ram,R16>(borrow_mut(m), 43981u64)\n    match b { Ok(d) { } Err(e) { code = 3u32 } }\n'
            '    let c = mmio.write<Ram,R32>(borrow_mut(m), 3735928559u64)\n    match c { Ok(d) { } Err(e) { code = 4u32 } }\n'
            '    let d = mmio.write<Ram,R64>(borrow_mut(m), 18364758544493064720u64)\n    match d { Ok(x) { } Err(e) { code = 5u32 } }\n'
            '    let v8 = mmio.read<Ram,R8>(borrow(m))\n    match v8 { Ok(v) { if v != 171u64 { code = 6u32 } } Err(e) { code = 7u32 } }\n'
            '    let v16 = mmio.read<Ram,R16>(borrow(m))\n    match v16 { Ok(v) { if v != 43981u64 { code = 8u32 } } Err(e) { code = 9u32 } }\n'
            '    let v32 = mmio.read<Ram,R32>(borrow(m))\n    match v32 { Ok(v) { if v != 3735928559u64 { code = 10u32 } } Err(e) { code = 11u32 } }\n'
            '    let v64 = mmio.read<Ram,R64>(borrow(m))\n    match v64 { Ok(v) { if v != 18364758544493064720u64 { code = 12u32 } } Err(e) { code = 13u32 } }\n'
            # the register after them was not touched by any of the narrower stores
            '    if rd(borrow(m)) != 1311768467294899695u64 { code = 14u32 }\n'
            '    let u = mmio.unmap<Ram>(move(m))\n  } Err(e) { code = 15u32 } }\n  if code != 0u32 { return code }\n  return 42u32\n}\n')

    def test_a_w1c_register_gets_exactly_the_mask_and_the_explicit_modify_is_the_only_read_modify_write(self):
        regs = reg('Flags', 8, 4, 'W1C', 'Readable') + reg('Ctl', 16, 4, 'ReadWrite', 'Readable', 'Writable')
        self.run_eval(RAM + regs +
            'func main() u32 !{memory.raw} {\n  var code u32 = 0u32\n  let mp = mmio.map<Ram>()\n  match mp { Ok(m) {\n'
            # RAM has no device behind it, so what `clear` stored is what we read back: the mask, not old-and-not-mask, not old-or-mask
            '    let c = mmio.clear<Ram,Flags>(borrow_mut(m), 4u64)\n    match c { Ok(d) { } Err(e) { code = 1u32 } }\n'
            '    let f = mmio.read<Ram,Flags>(borrow(m))\n    match f { Ok(v) { if v != 4u64 { code = 2u32 } } Err(e) { code = 3u32 } }\n'
            '    let c2 = mmio.clear<Ram,Flags>(borrow_mut(m), 1u64)\n    match c2 { Ok(d) { } Err(e) { code = 4u32 } }\n'
            '    let f2 = mmio.read<Ram,Flags>(borrow(m))\n    match f2 { Ok(v) { if v != 1u64 { code = 5u32 } } Err(e) { code = 6u32 } }\n'
            # modify does read, change, store: clear bits 0-3 of 0xAB, set 0x30
            '    let w = mmio.write<Ram,Ctl>(borrow_mut(m), 171u64)\n    match w { Ok(d) { } Err(e) { code = 7u32 } }\n'
            '    let mo = mmio.modify<Ram,Ctl>(borrow_mut(m), 15u64, 48u64)\n    match mo { Ok(old) { if old != 171u64 { code = 8u32 } } Err(e) { code = 9u32 } }\n'
            '    let r = mmio.read<Ram,Ctl>(borrow(m))\n    match r { Ok(v) { if v != 176u64 { code = 10u32 } } Err(e) { code = 11u32 } }\n'
            '    let u = mmio.unmap<Ram>(move(m))\n  } Err(e) { code = 12u32 } }\n  if code != 0u32 { return code }\n  return 42u32\n}\n')

    def test_a_register_that_does_not_fit_is_not_aligned_has_no_width_or_holds_a_bigger_value_is_refused_without_touching_memory(self):
        regs = (reg('Past', 256, 8, 'Readable', 'Writable') + reg('Last', 252, 4, 'Readable', 'Writable') + reg('Odd', 2, 4, 'Readable') + reg('Three', 0, 3, 'Readable')
                + reg('Byte', 0, 1, 'Readable', 'Writable') + reg('Far', 4294967292, 4, 'Readable'))
        self.run_eval(RAM + regs +
            'func main() u32 !{memory.raw} {\n  var code u32 = 0u32\n  let mp = mmio.map<Ram>()\n  match mp { Ok(m) {\n'
            '    let p = mmio.read<Ram,Past>(borrow(m))\n    match p { Ok(v) { code = 1u32 } Err(e) { if e != 1u32 { code = 2u32 } } }\n'
            '    let pw = mmio.write<Ram,Past>(borrow_mut(m), 1u64)\n    match pw { Ok(d) { code = 3u32 } Err(e) { if e != 1u32 { code = 4u32 } } }\n'
            '    let l = mmio.write<Ram,Last>(borrow_mut(m), 305419896u64)\n    match l { Ok(d) { } Err(e) { code = 5u32 } }\n'
            '    let lr = mmio.read<Ram,Last>(borrow(m))\n    match lr { Ok(v) { if v != 305419896u64 { code = 6u32 } } Err(e) { code = 7u32 } }\n'
            '    let o = mmio.read<Ram,Odd>(borrow(m))\n    match o { Ok(v) { code = 8u32 } Err(e) { if e != 2u32 { code = 9u32 } } }\n'
            '    let t = mmio.read<Ram,Three>(borrow(m))\n    match t { Ok(v) { code = 10u32 } Err(e) { if e != 3u32 { code = 11u32 } } }\n'
            '    let big = mmio.write<Ram,Byte>(borrow_mut(m), 256u64)\n    match big { Ok(d) { code = 12u32 } Err(e) { if e != 4u32 { code = 13u32 } } }\n'
            '    let ok = mmio.write<Ram,Byte>(borrow_mut(m), 255u64)\n    match ok { Ok(d) { } Err(e) { code = 14u32 } }\n'
            '    let far = mmio.read<Ram,Far>(borrow(m))\n    match far { Ok(v) { code = 15u32 } Err(e) { if e != 1u32 { code = 16u32 } } }\n'
            # after every refusal the mapping still works: the error is recoverable and nothing was damaged
            '    let again = mmio.read<Ram,Last>(borrow(m))\n    match again { Ok(v) { if v != 305419896u64 { code = 17u32 } } Err(e) { code = 18u32 } }\n'
            '    let u = mmio.unmap<Ram>(move(m))\n  } Err(e) { code = 19u32 } }\n  if code != 0u32 { return code }\n  return 42u32\n}\n')

    def test_a_region_that_cannot_be_mapped_says_why(self):
        regions = [('empty', 4194304, 0, 5), ('wrapping', 18446744073709551600, 32, 6), ('into the non-canonical hole', 140737488355328, 4096, 7),
                   ('ending in the hole', 140737488351232, 8192, 7), ('fine', 4194304, 4096, 0), ('ending at the very last address', 18446744073709551608, 8, 0), ('one byte past the very last address', 18446744073709551609, 8, 6)]
        body = ''
        for i, (label, base, size, code) in enumerate(regions):
            body += ('struct G%d { tag u32 }\nimpl mmio.Region for G%d {\n  func base() u64 { return %du64 }\n  func size() u64 { return %du64 }\n}\n' % (i, i, base, size))
        main = 'func main() u32 !{memory.raw} {\n  var code u32 = 0u32\n'
        for i, (label, base, size, code) in enumerate(regions):
            main += ('  let r%d = mmio.map<G%d>()\n  match r%d { Ok(m) { let u%d = mmio.unmap<G%d>(move(m))\n    if %du32 != 0u32 { code = %du32 } } Err(e) { if e != %du32 { code = %du32 } } }\n'
                     % (i, i, i, i, i, code, 10 + i, code, 20 + i))
        self.run_eval(body + main + '  if code != 0u32 { return code }\n  return 42u32\n}\n')

    def test_what_the_device_does_not_allow_does_not_compile(self):
        regs = (reg('Wo', 0, 4, 'Writable') + reg('Ro', 4, 4, 'Readable') + reg('Rc', 8, 4, 'ReadClear') + reg('Fl', 12, 4, 'W1C') + reg('Rw', 16, 4, 'ReadWrite')
                + reg('PortRo', 1016, 1, 'PortReadable') + reg('PortRc', 1018, 1, 'PortReadClear'))
        head = RAM + regs
        cases = [
            ('reading a write-only register', 'let r = mmio.read<Ram,Wo>(borrow(m))\n'),
            ('writing a read-only register', 'let r = mmio.write<Ram,Ro>(borrow_mut(m), 1u64)\n'),
            ('a plain read of a read-clear register', 'let r = mmio.read<Ram,Rc>(borrow(m))\n'),
            ('writing a read-clear register', 'let r = mmio.write<Ram,Rc>(borrow_mut(m), 1u64)\n'),
            ('writing a W1C register as a value', 'let r = mmio.write<Ram,Fl>(borrow_mut(m), 1u64)\n'),
            ('clearing a register that is not W1C', 'let r = mmio.clear<Ram,Rw>(borrow_mut(m), 1u64)\n'),
            ('modifying a read-only register', 'let r = mmio.modify<Ram,Ro>(borrow_mut(m), 1u64, 2u64)\n'),
            ('modifying a W1C register', 'let r = mmio.modify<Ram,Fl>(borrow_mut(m), 1u64, 2u64)\n'),
            ('writing through a shared lend', 'let r = mmio.write<Ram,Rw>(borrow(m), 1u64)\n'),
            ('writing a port that is read-only', 'let r = mmio.port_write<PortRo>(1u32)\n'),
            ('a plain read of a read-clear port', 'let r = mmio.port_read<PortRc>()\n'),
        ]
        for label, op in cases:
            with self.subTest(label):
                program = head + 'func main() u32 !{memory.raw,port.io} {\n  let mp = mmio.map<Ram>()\n  match mp { Ok(m) {\n    ' + op + '    let u = mmio.unmap<Ram>(move(m))\n    return 0u32\n  } Err(e) { return e } }\n}\n'
                path = self.source(program, 'bad.omni')
                checked = proc(OMNI, 'check', path)
                self.assertEqual(checked.returncode, 2, (label, checked.stderr))
                self.assertTrue(b'E_GENERIC_CONSTRAINT' in checked.stderr or b'E_TYPE' in checked.stderr, (label, checked.stderr))

    def test_a_mapping_is_a_resource_that_ends_with_its_owner(self):
        cases = [
            ('using the mapping after it was unmapped',
             RAM + reg('R', 0, 4, 'Readable') + 'func main() u32 !{memory.raw} {\n  let mp = mmio.map<Ram>()\n  match mp { Ok(m) {\n    let u = mmio.unmap<Ram>(move(m))\n'
             '    let r = mmio.read<Ram,R>(borrow(m))\n    return 0u32\n  } Err(e) { return e } }\n}\n', b'E_RESOURCE_MOVED'),
            ('forgetting to unmap',
             RAM + reg('R', 0, 4, 'Readable') + 'func main() u32 !{memory.raw} {\n  let mp = mmio.map<Ram>()\n  match mp { Ok(m) {\n    let r = mmio.read<Ram,R>(borrow(m))\n'
             '    match r { Ok(v) { } Err(e) { } }\n    return 0u32\n  } Err(e) { return e } }\n}\n', b'E_RESOURCE_UNCONSUMED'),
            ('unmapping twice',
             RAM + 'func main() u32 !{memory.raw} {\n  let mp = mmio.map<Ram>()\n  match mp { Ok(m) {\n    let a = mmio.unmap<Ram>(move(m))\n    let b = mmio.unmap<Ram>(move(m))\n    return 0u32\n  } Err(e) { return e } }\n}\n', b'E_RESOURCE_MOVED'),
            ('unmapping while a register is being read through the lend',
             RAM + reg('R', 0, 4, 'Readable') + 'func main() u32 !{memory.raw} {\n  let mp = mmio.map<Ram>()\n  match mp { Ok(m) {\n    let keep = borrow(m)\n'
             '    let u = mmio.unmap<Ram>(move(m))\n    let r = mmio.read<Ram,R>(keep)\n    return 0u32\n  } Err(e) { return e } }\n}\n', b'E_BORROW_CONFLICT'),
            ('reading a register without the raw-memory capability (mapping alone touches no memory, so it needs none)',
             RAM + reg('R', 0, 4, 'Readable') + 'func main() u32 {\n  let mp = mmio.map<Ram>()\n  match mp { Ok(m) {\n    let r = mmio.read<Ram,R>(borrow(m))\n    match r { Ok(v) { } Err(e) { } }\n    let u = mmio.unmap<Ram>(move(m))\n    return 0u32\n  } Err(e) { return e } }\n}\n', b'E_CAPABILITY'),
        ]
        for label, program, code in cases:
            with self.subTest(label):
                path = self.source(program, 'bad.omni')
                checked = proc(OMNI, 'check', path)
                self.assertEqual(checked.returncode, 2, (label, checked.stderr))
                self.assertIn(code, checked.stderr, (label, checked.stderr))


class RegisterArtifactTests(X64Harness):
    """ARTIFACT evidence: the permissions are in the emitted code. Reachability is computed on the LLVM IR the compiler produced."""
    def setUp(self):
        super().setUp()
        shutil.copy(STORAGE / 'addr.omni', self.dir / 'addr.omni')
        shutil.copy(STORAGE / 'mmio.omni', self.dir / 'mmio.omni')

    PROGRAM = ('module t\nimport rt "rt.omni"\nimport mmio "mmio.omni"\n' + RAM +
               reg('Wo', 0, 4, 'Writable') + reg('Ro', 4, 4, 'Readable') + reg('Fl', 12, 4, 'W1C') + reg('Rw', 16, 4, 'ReadWrite') +
               'func do_write(m BorrowMut<mmio.Mapping<Ram>>) u32 !{memory.raw} {\n  let r = mmio.write<Ram,Wo>(m, 1u64)\n  match r { Ok(v) { return v } Err(e) { return e } }\n}\n'
               'func do_clear(m BorrowMut<mmio.Mapping<Ram>>) u32 !{memory.raw} {\n  let r = mmio.clear<Ram,Fl>(m, 4u64)\n  match r { Ok(v) { return v } Err(e) { return e } }\n}\n'
               'func do_read(m Borrow<mmio.Mapping<Ram>>) u64 !{memory.raw} {\n  let r = mmio.read<Ram,Ro>(m)\n  match r { Ok(v) { return v } Err(e) { return 0u64 } }\n}\n'
               'func do_modify(m BorrowMut<mmio.Mapping<Ram>>) u32 !{memory.raw} {\n  let r = mmio.modify<Ram,Rw>(m, 1u64, 2u64)\n  match r { Ok(v) { return 1u32 } Err(e) { return e } }\n}\n'
               'func main() u32 !{io.print,memory.raw,port.io,cpu.control} {\n  let mp = mmio.map<Ram>()\n  match mp { Ok(m) {\n'
               '    let a u32 = do_write(borrow_mut(m))\n    let b u32 = do_clear(borrow_mut(m))\n    let c u64 = do_read(borrow(m))\n    let d u32 = do_modify(borrow_mut(m))\n'
               '    let u = mmio.unmap<Ram>(move(m))\n  } Err(e) { print(e) } }\n  return rt.finish(0u32)\n}\n')

    def reach(self, ir, root):
        names = self.reachable(ir, 'omni.fn.t.' + root)
        return {n for n in names if n.startswith('omni.fn.mmio.')}

    def test_write_only_and_w1c_operations_reach_no_load_and_a_read_reaches_no_store(self):
        path = self.dir / 'regs.omni'
        path.write_text(self.PROGRAM, encoding='utf-8')
        emitted = self.emit(path)
        self.assertEqual(emitted.returncode, 0, emitted.stderr)
        ir = (self.dir / 'prog.ll').read_text()
        write, clear, read, modify = (self.reach(ir, n) for n in ('do_write', 'do_clear', 'do_read', 'do_modify'))
        has = lambda names, word: any(('.' + word) in n.rsplit('omni.fn.mmio', 1)[-1] for n in names)
        self.assertTrue(has(write, 'store'), write)
        self.assertFalse(has(write, 'load'), write)             # a write-only register is never read
        self.assertTrue(has(clear, 'store'), clear)
        self.assertFalse(has(clear, 'load'), clear)             # W1C: one store of the mask, no read-modify-write
        self.assertTrue(has(read, 'load'), read)
        self.assertFalse(has(read, 'store'), read)              # a plain read stores nothing
        self.assertTrue(has(modify, 'load') and has(modify, 'store'), modify)   # the explicit one is the only one with both


class EmulatedDeviceTests(X64Harness):
    """EMULATION evidence: QEMU's local APIC page and 16550 UART as the devices behind the registers."""
    def setUp(self):
        super().setUp()
        shutil.copy(STORAGE / 'addr.omni', self.dir / 'addr.omni')
        shutil.copy(STORAGE / 'mmio.omni', self.dir / 'mmio.omni')

    def lines(self, serial):
        return serial.split('\n')[:-1]

    HEAD = ('module t\nimport rt "rt.omni"\nimport mmio "mmio.omni"\n'
            'struct Lapic { tag u32 }\nimpl mmio.Region for Lapic {\n  func base() u64 { return 4276092928u64 }\n  func size() u64 { return 4096u64 }\n}\n' +
            reg('ApicId', 32, 4, 'Readable') + reg('Version', 48, 4, 'Readable') + reg('Tpr', 128, 4, 'Readable', 'Writable', 'ReadWrite') + reg('Eoi', 176, 4, 'Writable') +
            reg('Odd', 130, 4, 'Readable') + reg('Past', 4096, 4, 'Readable') +
            reg('Ier', 1017, 1, 'PortWritable') + reg('Iir', 1018, 1, 'PortReadClear') + reg('Scr', 1023, 1, 'PortReadable', 'PortWritable'))

    def test_the_apic_registers_follow_their_permissions_and_an_error_does_not_damage_the_mapping(self):
        path = self.dir / 'apic.omni'
        path.write_text(self.HEAD +
            'func main() u32 !{io.print,memory.raw,port.io,cpu.control} {\n  let mp = mmio.map<Lapic>()\n  match mp { Ok(m) {\n'
            '    let id = mmio.read<Lapic,ApicId>(borrow(m))\n    match id { Ok(v) { print(v) } Err(e) { print(900u32 + e) } }\n'
            '    let ver = mmio.read<Lapic,Version>(borrow(m))\n    match ver { Ok(v) { print(v) } Err(e) { print(900u32 + e) } }\n'
            '    let w = mmio.write<Lapic,Tpr>(borrow_mut(m), 90u64)\n    match w { Ok(d) { } Err(e) { print(900u32 + e) } }\n'
            '    let t = mmio.read<Lapic,Tpr>(borrow(m))\n    match t { Ok(v) { print(v) } Err(e) { print(900u32 + e) } }\n'
            '    let mo = mmio.modify<Lapic,Tpr>(borrow_mut(m), 15u64, 1u64)\n    match mo { Ok(old) { print(old) } Err(e) { print(900u32 + e) } }\n'
            '    let t2 = mmio.read<Lapic,Tpr>(borrow(m))\n    match t2 { Ok(v) { print(v) } Err(e) { print(900u32 + e) } }\n'
            '    let eoi = mmio.write<Lapic,Eoi>(borrow_mut(m), 0u64)\n    match eoi { Ok(d) { print(0u32) } Err(e) { print(900u32 + e) } }\n'
            '    let odd = mmio.read<Lapic,Odd>(borrow(m))\n    match odd { Ok(v) { print(901u32) } Err(e) { print(e) } }\n'
            '    let past = mmio.read<Lapic,Past>(borrow(m))\n    match past { Ok(v) { print(902u32) } Err(e) { print(e) } }\n'
            '    let again = mmio.read<Lapic,Tpr>(borrow(m))\n    match again { Ok(v) { print(v) } Err(e) { print(900u32 + e) } }\n'
            '    let u = mmio.unmap<Lapic>(move(m))\n  } Err(e) { print(800u32 + e) } }\n  return rt.finish(0u32)\n}\n', encoding='utf-8')
        rc, serial = self.boot(self.build(path))
        out = self.lines(serial)
        self.assertEqual(rc, 1, serial)
        self.assertEqual(out[0], '0', serial)                                   # the boot processor
        self.assertEqual(int(out[1]) & 0xFF, 0x14, serial)                       # the architectural version of the xAPIC in QEMU
        self.assertEqual(out[2:], ['90', '90', '81', '0', '2', '1', '81'], serial)   # modify: old 0x5A, then (0x5A and not 0xF) or 1 = 0x51

    def test_a_serial_port_scratch_register_round_trips_and_a_read_clear_register_differs_on_its_second_read(self):
        path = self.dir / 'uart.omni'
        path.write_text(self.HEAD +
            'func low(v u32) u32 { return bit.and(v, 15u32) }\n'
            'func main() u32 !{io.print,memory.raw,port.io,cpu.control} {\n'
            '  let a = mmio.port_write<Scr>(165u32)\n  match a { Ok(d) { } Err(e) { print(900u32 + e) } }\n'
            '  let b = mmio.port_read<Scr>()\n  match b { Ok(v) { print(v) } Err(e) { print(900u32 + e) } }\n'
            # the interrupt-identification register is read-CLEAR: with the transmit-empty interrupt enabled the first read reports it and the read itself clears it
            '  let off = mmio.port_write<Ier>(0u32)\n  match off { Ok(d) { } Err(e) { print(900u32 + e) } }\n'
            '  let on = mmio.port_write<Ier>(2u32)\n  match on { Ok(d) { } Err(e) { print(900u32 + e) } }\n'
            '  var one u32 = 900u32\n  var two u32 = 900u32\n'
            '  let first = mmio.port_read_clear<Iir>()\n  match first { Ok(v) { one = low(v) } Err(e) { one = 900u32 + e } }\n'
            '  let second = mmio.port_read_clear<Iir>()\n  match second { Ok(v) { two = low(v) } Err(e) { two = 900u32 + e } }\n'
            '  print(one)\n  print(two)\n'
            '  let back = mmio.port_write<Ier>(0u32)\n  match back { Ok(d) { } Err(e) { print(900u32 + e) } }\n'
            '  let big = mmio.port_write<Scr>(256u32)\n  match big { Ok(d) { print(902u32) } Err(e) { print(e) } }\n'
            '  return rt.finish(0u32)\n}\n', encoding='utf-8')
        rc, serial = self.boot(self.build(path))
        self.assertEqual((rc, self.lines(serial)), (1, ['165', '2', '1', '4']), serial)

    def test_a_port_that_does_not_exist_or_is_not_aligned_to_its_width_is_refused(self):
        path = self.dir / 'ports.omni'
        path.write_text('module t\nimport rt "rt.omni"\nimport mmio "mmio.omni"\n' +
            reg('Beyond', 65536, 1, 'PortWritable') + reg('Last', 65535, 1, 'PortWritable') + reg('Odd16', 1019, 2, 'PortWritable') + reg('Even16', 1018, 2, 'PortWritable') +
            reg('Odd32', 1022, 4, 'PortWritable') + reg('Scratch', 1023, 1, 'PortReadable', 'PortWritable') +
            'func main() u32 !{io.print,memory.raw,port.io,cpu.control} {\n'
            '  let a = mmio.port_write<Beyond>(1u32)\n  match a { Ok(d) { print(902u32) } Err(e) { print(e) } }\n'
            '  let b = mmio.port_write<Odd16>(1u32)\n  match b { Ok(d) { print(902u32) } Err(e) { print(e) } }\n'
            '  let c = mmio.port_write<Odd32>(1u32)\n  match c { Ok(d) { print(902u32) } Err(e) { print(e) } }\n'
            '  let d = mmio.port_write<Scratch>(256u32)\n  match d { Ok(x) { print(902u32) } Err(e) { print(e) } }\n'
            '  return rt.finish(0u32)\n}\n', encoding='utf-8')
        rc, serial = self.boot(self.build(path))
        self.assertEqual((rc, self.lines(serial)), (1, ['8', '8', '8', '4']), serial)


if __name__ == '__main__':
    unittest.main()
