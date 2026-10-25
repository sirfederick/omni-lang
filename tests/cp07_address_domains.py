#!/usr/bin/env python3
"""CP-07 rows 7.6 and 7.4 (spec/ADDRESS_DOMAINS_CANDIDATE.md, examples/storage/addr.omni): address domains with restricted constructors, and the address model reported apart
from the real access.

MODEL (hosted evaluator): what a Phys, a Virt and a Bus are, what builds one, what converts one into another and what no operation can do (truncate, wrap, mix domains).
ACCESS (QEMU guest, x86-64): the same library reaches real memory through a Virt above 4 GiB and the CPU reports the full 64-bit address of the fault. The two are separate tests
because they prove different things: the first that the model is closed, the second that the full-width address reaches the machine.
"""
from __future__ import annotations
import shutil
import unittest
from cp02_borrowed_containers import ContainerCase
from language_0_8_3_alpha8 import ROOT, OMNI, proc, X64Harness

STORAGE = ROOT / 'examples' / 'storage'


class DomainCase(ContainerCase):
    def setUp(self):
        super().setUp()
        shutil.copy(STORAGE / 'addr.omni', self.dir / 'addr.omni')
        shutil.copy(STORAGE / 'addr_access.omni', self.dir / 'addr_access.omni')

    def source(self, text, name='program.omni'):
        # the access module holds raw memory, which a hosted native binary refuses wherever it is linked: only the programs that use it import it
        return super().source('import addr "addr.omni"\n' + ('import acc "addr_access.omni"\n' if 'acc.' in text else '') + text, name)


class AddressModelTests(DomainCase):
    def test_what_each_domain_admits_at_its_edges(self):
        # (value, outcome) pairs written from the architecture, not from the library: a physical address is below 2^52; a canonical virtual address has bits 63..47 equal
        self.both(self.source(
            'func ph(v u64) u32 {\n  let r = addr.phys(v)\n  match r { Ok(a) { return 0u32 } Err(e) { return e } }\n}\n'
            'func vi(v u64) u32 {\n  let r = addr.virt(v)\n  match r { Ok(a) { return 0u32 } Err(e) { return e } }\n}\n'
            'func main() u32 {\n  var code u32 = 0u32\n'
            '  if ph(0u64) != 0u32 { code = 1u32 }\n  if ph(4294967296u64) != 0u32 { code = 2u32 }\n  if ph(4503599627370495u64) != 0u32 { code = 3u32 }\n'
            '  if ph(4503599627370496u64) != 1u32 { code = 4u32 }\n  if ph(18446744073709551615u64) != 1u32 { code = 5u32 }\n'
            '  if vi(0u64) != 0u32 { code = 6u32 }\n  if vi(140737488355327u64) != 0u32 { code = 7u32 }\n'          # 0x00007FFF_FFFFFFFF: last of the lower half
            '  if vi(140737488355328u64) != 2u32 { code = 8u32 }\n'                                            # 0x00008000_00000000: first of the hole
            '  if vi(18446603336221196287u64) != 2u32 { code = 9u32 }\n'                                       # 0xFFFF7FFF_FFFFFFFF: last of the hole
            '  if vi(18446603336221196288u64) != 0u32 { code = 10u32 }\n'                                      # 0xFFFF8000_00000000: first of the upper half
            '  if vi(18446744073709551615u64) != 0u32 { code = 11u32 }\n'
            '  let w = addr.phys_within(1073741824u64, 1073741824u64)\n  match w { Ok(a) { code = 12u32 } Err(e) { if e != 1u32 { code = 13u32 } } }\n'
            '  let w2 = addr.phys_within(1073741823u64, 1073741824u64)\n  match w2 { Ok(a) { } Err(e) { code = 14u32 } }\n'
            '  if code != 0u32 { return code }\n  return 42u32\n}\n'))

    def test_the_full_64_bits_survive_and_arithmetic_never_wraps(self):
        self.both(self.source(
            'func main() u32 {\n  var code u32 = 0u32\n'
            '  let p = addr.phys(4503599627370495u64)\n'
            '  match p { Ok(a) {\n    if addr.phys_value(a) != 4503599627370495u64 { code = 1u32 }\n'
            '    let up = addr.phys_add(a, 1u64)\n    match up { Ok(b) { code = 2u32 } Err(e) { if e != 3u32 { code = 3u32 } } }\n'
            '    let huge = addr.phys_add(a, 18446744073709551615u64)\n    match huge { Ok(b) { code = 4u32 } Err(e) { if e != 3u32 { code = 5u32 } } }\n'
            '  } Err(e) { code = 6u32 } }\n'
            '  let v = addr.virt(18446744073709551615u64)\n'
            '  match v { Ok(a) {\n    let wrap = addr.virt_add(a, 1u64)\n    match wrap { Ok(b) { code = 7u32 } Err(e) { if e != 3u32 { code = 8u32 } } }\n'
            '  } Err(e) { code = 9u32 } }\n'
            '  let v2 = addr.virt(140737488355327u64)\n'
            '  match v2 { Ok(a) {\n    let into_hole = addr.virt_add(a, 1u64)\n    match into_hole { Ok(b) { code = 10u32 } Err(e) { if e != 3u32 { code = 11u32 } } }\n'
            '    let fine = addr.virt_add(a, 0u64)\n    match fine { Ok(b) { if addr.virt_value(b) != 140737488355327u64 { code = 12u32 } } Err(e) { code = 13u32 } }\n'
            '  } Err(e) { code = 14u32 } }\n'
            '  if code != 0u32 { return code }\n  return 42u32\n}\n'))

    def test_a_translation_is_a_policy_the_program_names_and_it_is_never_implicit(self):
        # Identity1G is the identity map of the first GiB; the program writes its own translation for a mapping of its own; a type that is not a Translate is refused
        self.both(self.source(
            'struct Shifted { tag u32 }\nimpl addr.Translate for Shifted {\n  func to_phys(a addr.Virt) Result<addr.Phys,u32> {\n'
            '    let r = addr.phys(addr.virt_value(a) - 4096u64)\n    return r\n  }\n}\n'
            'func main() u32 {\n  var code u32 = 0u32\n'
            '  let v = addr.virt(8192u64)\n'
            '  match v { Ok(a) {\n'
            '    let id = addr.translate<addr.Identity1G>(a)\n    match id { Ok(p) { if addr.phys_value(p) != 8192u64 { code = 1u32 } } Err(e) { code = 2u32 } }\n'
            '    let sh = addr.translate<Shifted>(a)\n    match sh { Ok(p) { if addr.phys_value(p) != 4096u64 { code = 3u32 } } Err(e) { code = 4u32 } }\n'
            '  } Err(e) { code = 5u32 } }\n'
            '  let high = addr.virt(1073741824u64)\n'
            '  match high { Ok(a) {\n    let out = addr.translate<addr.Identity1G>(a)\n    match out { Ok(p) { code = 6u32 } Err(e) { if e != 4u32 { code = 7u32 } } }\n'
            '  } Err(e) { code = 8u32 } }\n'
            '  if code != 0u32 { return code }\n  return 42u32\n}\n'))

    def test_the_evaluator_reaches_memory_above_4_gib_through_a_virtual_address(self):
        self.both_eval(self.source(
            'func main() u32 !{memory.raw} {\n  var code u32 = 0u32\n  let v = addr.virt(4294971392u64)\n'
            '  match v { Ok(a) {\n    let w u32 = acc.write32(a, 3735928559u32)\n    if acc.read32(a) != 3735928559u32 { code = 1u32 }\n'
            '    let w2 u32 = acc.write64(a, 1311768467294899695u64)\n    if acc.read64(a) != 1311768467294899695u64 { code = 2u32 }\n'
            # the low 32 bits of that address would be 0x1000: the high part decides where it lives
            '    let low = addr.virt(4096u64)\n    match low { Ok(b) { let z u32 = acc.write32(b, 7u32)\n      if acc.read32(a) == 7u32 { code = 3u32 } } Err(e) { code = 4u32 } }\n'
            '  } Err(e) { code = 5u32 } }\n  if code != 0u32 { return code }\n  return 42u32\n}\n'))

    def both_eval(self, path, expected=42):
        # a hosted native binary refuses raw memory (E_TARGET_PROFILE); the evaluator runs it, and QEMU runs the same library below
        evaluated = proc(OMNI, 'eval', path, timeout=180)
        self.assertEqual(evaluated.returncode, expected, evaluated.stderr)
        built = proc(OMNI, 'build', path, '-o', self.dir / 'never-native', '--cache-dir', self.dir / 'cache', timeout=180)
        self.assertEqual(built.returncode, 2, built.stderr)
        self.assertIn(b'E_TARGET_PROFILE', built.stderr)

    def test_what_must_not_compile(self):
        cases = [
            ('a physical address written as a literal', 'func main() u32 {\n  let p addr.Phys = addr.Phys { v: 5u64 }\n  return 0u32\n}\n', b'E_OPAQUE'),
            ('the number inside an address read outside the module',
             'func main() u32 {\n  let r = addr.phys(5u64)\n  match r { Ok(p) { let n u64 = p.v\n    return 0u32 } Err(e) { return 1u32 } }\n}\n', b'E_OPAQUE'),
            ('a virtual address where a physical one is expected',
             'func need(p addr.Phys) u64 { return addr.phys_value(p) }\nfunc main() u32 {\n  let r = addr.virt(5u64)\n  match r { Ok(a) { let n u64 = need(a)\n    return 0u32 } Err(e) { return 1u32 } }\n}\n', b'E_TYPE'),
            ('a plain integer where an address is expected', 'func main() u32 {\n  let n u64 = addr.phys_value(5u64)\n  return 0u32\n}\n', b'E_TYPE'),
            ('a bus address used as a virtual one',
             'func main() u32 !{memory.raw} {\n  let r = addr.bus(5u64)\n  match r { Ok(b) { let n u32 = acc.read32(b)\n    return 0u32 } Err(e) { return 1u32 } }\n}\n', b'E_TYPE'),
            ('a translation by a type that is not a Translate',
             'struct Nope { tag u32 }\nfunc main() u32 {\n  let r = addr.virt(5u64)\n  match r { Ok(a) { let p = addr.translate<Nope>(a)\n    return 0u32 } Err(e) { return 1u32 } }\n}\n', b'E_GENERIC_CONSTRAINT'),
            ('raw memory without the capability',
             'func main() u32 {\n  let r = addr.virt(5u64)\n  match r { Ok(a) { let n u32 = acc.read32(a)\n    return 0u32 } Err(e) { return 1u32 } }\n}\n', b'E_CAPABILITY'),
        ]
        for label, program, code in cases:
            with self.subTest(label):
                self.rejected(program, code)


class OpaqueRepresentationTests(ContainerCase):
    """`opaque struct` is new semantics: Wave21/OMC21 only, carried by the struct form, kept by every representation and by the formatter."""
    PROGRAM = ('opaque struct Id { v u64 }\nfunc make(n u64) Id { return Id { v: n } }\nfunc open(i Id) u64 { return i.v }\n'
               'func main() u32 {\n  if open(make(42u64)) != 42u64 { return 1u32 }\n  return 42u32\n}\n')

    def program(self):
        path = self.dir / 'opaque.omni'
        path.write_text('module t\n' + self.PROGRAM, encoding='utf-8')
        return path

    def test_an_opaque_program_is_wave21_and_omc21_and_every_reader_runs_it(self):
        path = self.program()
        wave = proc(OMNI, 'wave', path)
        self.assertEqual(wave.returncode, 0, wave.stderr)
        self.assertTrue(wave.stdout.startswith(b'(omni-wave 21'), wave.stdout[:20])
        self.assertIn(b'(opaque)', wave.stdout)
        wire = self.dir / 'opaque.owire'
        self.assertEqual(proc(OMNI, 'pack', path, '-o', wire).returncode, 0)
        self.assertEqual(wire.read_bytes()[:8], b'OMCX\x15\x00\x00\x00')
        owave = self.dir / 'opaque.owave'
        owave.write_bytes(wave.stdout)
        for artifact in (path, owave, wire):
            self.assertEqual(proc(OMNI, 'eval', artifact, timeout=180).returncode, 42, artifact.name)
        formatted = proc(OMNI, 'fmt', path)
        self.assertEqual(formatted.returncode, 0, formatted.stderr)
        self.assertIn(b'opaque struct Id', formatted.stdout)

    def test_relabelling_it_as_an_older_version_or_damaging_its_marker_is_rejected(self):
        path = self.program()
        wave = proc(OMNI, 'wave', path).stdout
        wire = self.dir / 'opaque.owire'
        self.assertEqual(proc(OMNI, 'pack', path, '-o', wire).returncode, 0)
        for old in (18, 19, 20):
            relabelled = self.dir / ('as-wave%d.owave' % old)
            relabelled.write_bytes(wave.replace(b'(omni-wave 21', ('(omni-wave %d' % old).encode(), 1))
            result = proc(OMNI, 'check', relabelled)
            self.assertEqual(result.returncode, 2, (old, result.stderr))
            self.assertIn(b'E_VERSION', result.stderr)
            raw = bytearray(wire.read_bytes())
            raw[4] = old
            older = self.dir / ('as-omc%d.owire' % old)
            older.write_bytes(bytes(raw))
            result = proc(OMNI, 'check', older)
            self.assertEqual(result.returncode, 2, (old, result.stderr))
            self.assertIn(b'E_VERSION', result.stderr)
        damaged = self.dir / 'damaged.owave'
        damaged.write_bytes(wave.replace(b'(opaque)', b'(opaquex)', 1))
        result = proc(OMNI, 'check', damaged)
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn(b'E_WAVE', result.stderr)
        # a wire whose struct flags carry an unknown bit
        raw = bytearray(wire.read_bytes())
        at = raw.find(b'Id') + 2
        self.assertGreater(at, 2)
        raw[at] = 0x17      # public + packed + opaque + an unknown bit (bit 8 is `extern`, the bits above it are unknown)
        bad = self.dir / 'badflags.owire'
        bad.write_bytes(bytes(raw))
        result = proc(OMNI, 'check', bad)
        self.assertEqual(result.returncode, 2, result.stderr)

    def test_the_marker_is_part_of_the_identity_of_the_record(self):
        # the same record with and without `opaque` is a different thing for the semantic projection; one without it keeps the identity it always had
        a, b = self.dir / 'plain.omni', self.dir / 'opaque.omni'
        a.write_text('module t\n' + self.PROGRAM.replace('opaque struct', 'struct'), encoding='utf-8')
        b.write_text('module t\n' + self.PROGRAM, encoding='utf-8')
        wa, wb = proc(OMNI, 'wave', a).stdout, proc(OMNI, 'wave', b).stdout
        self.assertTrue(wa.startswith(b'(omni-wave 18'), wa[:20])      # a program that does not use it keeps its label
        self.assertNotEqual(wa, wb)


class LayoutFormatsTests(ContainerCase):
    """CP-07 row 7.5: a reader that does not know the layout surface rejects it, in every format that can carry it.

    One program uses every construct of the layout surface: `packed struct`, `opaque struct`, `layout.size/align/offset/identity` and typed raw access. Wave and Wire carry a version
    label; ONME is content-addressed (a hash root, no label) and the semantic projection (OSNMF) is derived from the checked program. For each: the current reader accepts and runs
    or checks it, every older label is `E_VERSION`, a damaged form is refused, and the projection is the same through every representation."""
    SURFACE = ('packed struct P { a u8, b u32 }\nopaque struct Id { v u64 }\nstruct Plain { a u8, b u32 }\n'
               'func mk(n u64) Id { return Id { v: n } }\nfunc open(i Id) u64 { return i.v }\n'
               'func main() u32 !{memory.raw,io.print} {\n  print(layout.size<P>())\n  print(layout.align<Plain>())\n  print(layout.offset<Plain>(b))\n'
               '  print(layout.identity<P>(0u32))\n  return 7u32\n}\n')

    def program(self, text=None):
        path = self.dir / 'surface.omni'
        path.write_text('module t\n' + (text or self.SURFACE), encoding='utf-8')
        return path

    def test_every_format_carries_the_layout_surface_and_only_a_reader_that_knows_it_accepts_it(self):
        path = self.program()
        wave = proc(OMNI, 'wave', path)
        self.assertEqual(wave.returncode, 0, wave.stderr)
        self.assertTrue(wave.stdout.startswith(b'(omni-wave 21'))
        for marker in (b'(packed)', b'(opaque)', b'layout.size<t.P>', b'layout.offset<t.Plain>', b'layout.identity<t.P>'):
            self.assertIn(marker, wave.stdout)
        wire = self.dir / 'surface.owire'
        self.assertEqual(proc(OMNI, 'pack', path, '-o', wire).returncode, 0)
        self.assertEqual(wire.read_bytes()[:8], b'OMCX\x15\x00\x00\x00')
        owave = self.dir / 'surface.owave'
        owave.write_bytes(wave.stdout)
        onme = self.dir / 'surface.onme'
        self.assertEqual(proc(OMNI, 'onme', path, '-o', onme).returncode, 0)
        for artifact in (path, owave, wire, onme):
            self.assertEqual(proc(OMNI, 'check', artifact).returncode, 0, artifact.name)
        self.assertEqual(proc(OMNI, 'wave', owave).stdout, wave.stdout)
        formatted = proc(OMNI, 'fmt', path).stdout
        for text in (b'packed struct P', b'opaque struct Id', b'layout.identity<t.P>('):
            self.assertIn(text, formatted)
        # every older label over this semantics is a version error, never a silent reinterpretation
        for old in (18, 19, 20):
            relabelled = self.dir / ('old%d.owave' % old)
            relabelled.write_bytes(wave.stdout.replace(b'(omni-wave 21', ('(omni-wave %d' % old).encode(), 1))
            result = proc(OMNI, 'check', relabelled)
            self.assertEqual(result.returncode, 2, (old, result.stderr))
            self.assertIn(b'E_VERSION', result.stderr)
            raw = bytearray(wire.read_bytes())
            raw[4] = old
            older = self.dir / ('old%d.owire' % old)
            older.write_bytes(bytes(raw))
            result = proc(OMNI, 'check', older)
            self.assertEqual(result.returncode, 2, (old, result.stderr))
            self.assertIn(b'E_VERSION', result.stderr)
        # a damaged wire and a damaged ONME are refused; the projection is the same through every representation
        damaged = bytearray(wire.read_bytes())
        damaged[-1] ^= 0xFF
        broken = self.dir / 'broken.owire'
        broken.write_bytes(bytes(damaged[:-3]))
        self.assertEqual(proc(OMNI, 'check', broken).returncode, 2)
        torn = bytearray(onme.read_bytes())
        torn[10] ^= 0x01
        broken_onme = self.dir / 'broken.onme'
        broken_onme.write_bytes(bytes(torn))
        self.assertEqual(proc(OMNI, 'check', broken_onme).returncode, 2)
        store = proc(OMNI, 'memory', path)
        self.assertEqual(store.returncode, 0, store.stderr)
        for derived in (wire, owave, onme):
            self.assertEqual(proc(OMNI, 'memory', derived).stdout, store.stdout, derived.name)

    def test_each_construct_alone_is_new_semantics(self):
        cases = [
            ('a packed record', 'packed struct P { a u8, b u32 }\nfunc main() u32 { return 7u32 }\n'),
            ('an opaque record', 'opaque struct Id { v u64 }\nfunc main() u32 { return 7u32 }\n'),
            ('a layout query', 'struct S { a u32 }\nfunc main() u32 !{io.print} {\n  print(layout.size<S>())\n  return 7u32\n}\n'),
            ('a layout identity', 'struct S { a u32 }\nfunc main() u32 !{io.print} {\n  print(layout.identity<S>(1u32))\n  return 7u32\n}\n'),
        ]
        for label, source in cases:
            with self.subTest(label):
                path = self.program(source)
                wave = proc(OMNI, 'wave', path)
                self.assertEqual(wave.returncode, 0, wave.stderr)
                self.assertTrue(wave.stdout.startswith(b'(omni-wave 21'), (label, wave.stdout[:20]))
                relabelled = self.dir / 'alone.owave'
                relabelled.write_bytes(wave.stdout.replace(b'(omni-wave 21', b'(omni-wave 20', 1))
                result = proc(OMNI, 'check', relabelled)
                self.assertEqual(result.returncode, 2, (label, result.stderr))
                self.assertIn(b'E_VERSION', result.stderr)


class AddressAccessTests(X64Harness):
    """The full-width address reaches the machine. QEMU TCG, one vCPU: this is access evidence for the library, not a claim about real hardware."""
    def setUp(self):
        super().setUp()
        shutil.copy(STORAGE / 'addr.omni', self.dir / 'addr.omni')
        shutil.copy(STORAGE / 'addr_access.omni', self.dir / 'addr_access.omni')

    def lines(self, serial):
        return serial.split('\n')[:-1]

    HEAD = ('module t\nimport rt "rt.omni"\nimport idt "idt.omni"\nimport addr "addr.omni"\nimport acc "addr_access.omni"\n'
            'func on_exception(frame u64) u32 !{io.print,memory.raw,port.io,cpu.control} {\n  print(raw.load64(frame))\n  print(cpu.read_cr64(2u32))\n  return rt.finish(100u32)\n}\n')

    def test_a_read_through_a_virtual_address_above_4_gib_faults_at_that_exact_address(self):
        path = self.dir / 'addr_high.omni'
        path.write_text(self.HEAD +
            'func main() u32 !{io.print,memory.raw,port.io,cpu.control} {\n  let installed u32 = idt.install()\n'
            # the non-canonical address never reaches the machine: the constructor says 2 first
            '  let hole = addr.virt(140737488355328u64)\n  match hole { Ok(a) { print(111u32) } Err(e) { print(e) } }\n'
            '  let v = addr.virt(4294971392u64)\n  match v { Ok(a) { let x u32 = acc.read32(a)\n    print(999u32) } Err(e) { print(1000u32 + e) } }\n'
            '  return rt.finish(0u32)\n}\n', encoding='utf-8')
        rc, serial = self.boot(self.build(path, emit_args=('--exception-handler', 't.on_exception')))
        self.assertEqual((rc, self.lines(serial)), ((100 << 1) | 1, ['2', '14', '4294971392']), serial)

    def test_a_write_and_a_read_through_a_virtual_address_in_the_mapped_memory_agree(self):
        path = self.dir / 'addr_low.omni'
        path.write_text(self.HEAD +
            'func main() u32 !{io.print,memory.raw,port.io,cpu.control} {\n  let installed u32 = idt.install()\n'
            '  let v = addr.virt(6029312u64)\n  match v { Ok(a) {\n    let w u32 = acc.write32(a, 3735928559u32)\n    print(acc.read32(a))\n'
            '    let w2 u32 = acc.write64(a, 1311768467294899695u64)\n    print(acc.read64(a))\n    print(acc.read32(a))\n  } Err(e) { print(1000u32 + e) } }\n'
            '  return rt.finish(0u32)\n}\n', encoding='utf-8')
        rc, serial = self.boot(self.build(path, emit_args=('--exception-handler', 't.on_exception')))
        self.assertEqual((rc, self.lines(serial)), (1, ['3735928559', '1311768467294899695', '2427178479']), serial)   # the low half of 0x123456789ABCDEF


if __name__ == '__main__':
    unittest.main()
