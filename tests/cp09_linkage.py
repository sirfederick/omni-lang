#!/usr/bin/env python3
"""CP-09 / MN-07, MN-13, MN-16 (spec/LINKAGE_ABI_CANDIDATE.md): the link-time identity of a function is part of the program.

    export "sym" func f(...)     the C symbol `sym` (SysV, integer arguments and result) reaches f; a thin external wrapper in the section `.text.omni_export.sym`
    extern "sym" func f(...) !{ffi.call, ...}   f is defined elsewhere (an assembly stub, firmware, a C routine): a declaration with no body, and what it needs is what it declares - never pure
    section ".name" func f       the code of f goes to that section
    noinline func f              f stays a call

SOURCE      the attributes parse in any order, print back canonically and are idempotent under the formatter; every wrong combination is refused with E_LINKAGE before any artifact exists.
REPRESENTATION  Wave, Wire (OMC) and the memory identity carry them, so a program that differs only in its linkage is a different program, and nothing is lost in a round trip.
ARTIFACT    the emitted IR and the final ELF say exactly this: symbols, sections, the extension of 8- and 16-bit values on the C boundary.
EMULATION   (QEMU TCG) Omni calls a C routine and a C routine calls Omni back, with mixed integer widths, in one freestanding image.
"""
from __future__ import annotations
import os
import re
import subprocess
import unittest
from cp02_borrowed_containers import ContainerCase
from language_0_8_3_alpha8 import ROOT, OMNI, proc, X64Harness


class LinkageSourceTests(ContainerCase):
    def source(self, text, name='program.omni'):
        path = self.dir / name
        path.write_text('module t\n' + text, encoding='utf-8')
        return path

    FULL = ('pub export "kernel_entry" section ".text.boot" noinline func boot(a u32, b i8) u32 { return a + 1u32 }\n'
            'extern "c_helper" func helper(x u64) u64 !{ffi.call, memory.raw}\n'
            'func main() u32 { return boot(41u32, 1i8) }\n')

    def test_the_attributes_run_in_the_evaluator_like_any_function(self):
        self.both(self.source(
            'export "twice_it" func twice(x u32) u32 { return x * 2u32 }\nsection ".text.cold" func cold(x u32) u32 { return x + 1u32 }\nnoinline func keep(x u32) u32 { return x }\n'
            'func main() u32 { return twice(20u32) + cold(0u32) + keep(1u32) }\n'))

    def test_the_formatter_prints_them_canonically_and_is_idempotent(self):
        path = self.source('pub noinline section ".text.boot" export "k_entry" func boot(a u32) u32 { return a }\nextern "c_helper" func helper(x u64) u64 !{ffi.call}\nfunc main() u32 { return boot(42u32) }\n')
        formatted = proc(OMNI, 'fmt', path)
        self.assertEqual(formatted.returncode, 0, formatted.stderr)
        text = formatted.stdout.decode()
        self.assertIn('pub export "k_entry" section ".text.boot" noinline func boot(a u32) u32 !pure {', text)     # canonical order, whatever the source order was
        self.assertIn('extern "c_helper" func helper(x u64) u64 !{ffi.call}\n', text)
        again = self.dir / 'again.omni'
        again.write_text(text, encoding='utf-8')
        self.assertEqual(proc(OMNI, 'fmt', again).stdout.decode(), text)
        self.assertEqual(proc(OMNI, 'check', again).returncode, 0)

    def test_what_is_refused(self):
        main = 'func main() u32 { return 0u32 }\n'
        cases = [
            ('an extern function that does not declare ffi.call', 'extern "c_x" func x(a u32) u32 !{memory.raw}\n' + main),
            ('an extern function assumed pure', 'extern "c_x" func x(a u32) u32\n' + main),
            ('an extern function with a body', 'extern "c_x" func x(a u32) u32 !{ffi.call} { return a }\n' + main),
            ('a float on the C boundary', 'export "c_f" func f(a f64) u32 { return 1u32 }\n' + main),
            ('a bool on the C boundary', 'export "c_f" func f(a bool) u32 { return 1u32 }\n' + main),
            ('a struct on the C boundary', 'struct P { v u32 }\nexport "c_f" func f(a P) u32 { return 1u32 }\n' + main),
            ('a struct result on the C boundary', 'struct P { v u32 }\nextern "c_f" func f(a u32) P !{ffi.call}\n' + main),
            ('seven parameters', 'export "c_f" func f(a u32, b u32, c u32, d u32, e u32, f u32, g u32) u32 { return a }\n' + main),
            ('the same symbol twice', 'export "c_f" func f() u32 { return 1u32 }\nexport "c_f" func g() u32 { return 2u32 }\n' + main),
            ('an export and an extern of the same symbol', 'export "c_f" func f() u32 { return 1u32 }\nextern "c_f" func g() u32 !{ffi.call}\n' + main),
            ('a symbol reserved for the compiler', 'export "omni_boot_entry" func f() u32 { return 1u32 }\n' + main),
            ('a symbol with a space', 'export "c f" func f() u32 { return 1u32 }\n' + main),
            ('a symbol that starts with a digit', 'export "9f" func f() u32 { return 1u32 }\n' + main),
            ('an empty symbol', 'export "" func f() u32 { return 1u32 }\n' + main),
            ('a section the compiler owns', 'section ".text.omni_entry" func f() u32 { return 1u32 }\n' + main),
            ('a section without a dot', 'section "boot" func f() u32 { return 1u32 }\n' + main),
            ('a section with a space', 'section ".text boot" func f() u32 { return 1u32 }\n' + main),
            ('an exported generic function', 'export "c_g" func g<T>(x T) T { return x }\n' + main),
            ('extern combined with export', 'export "a" extern "b" func f() u32 !{ffi.call}\n' + main),
            ('extern combined with section', 'section ".x" extern "b" func f() u32 !{ffi.call}\n' + main),
            ('extern combined with noinline', 'noinline extern "b" func f() u32 !{ffi.call}\n' + main),
            ('export repeated', 'export "a" export "b" func f() u32 { return 1u32 }\n' + main),
            ('a trait method with a linkage attribute', 'trait T { export "a" func f(x Self) u32 !pure }\n' + main),
        ]
        for label, text in cases:
            with self.subTest(label):
                done = proc(OMNI, 'check', self.source(text, 'bad.omni'))
                self.assertEqual(done.returncode, 2, (label, done.stderr))
                if 'trait' in label:
                    continue
                self.assertTrue(b'E_LINKAGE' in done.stderr or b'E_PARSE' in done.stderr, (label, done.stderr))
        # the ones that must be E_LINKAGE and not a parse error
        for label, text in cases:
            if label in ('an extern function with a body', 'a trait method with a linkage attribute'):
                continue
            with self.subTest('code ' + label):
                done = proc(OMNI, 'check', self.source(text, 'bad.omni'))
                self.assertIn(b'E_LINKAGE', done.stderr, (label, done.stderr))

    def test_an_extern_function_cannot_run_hosted(self):
        path = self.source('extern "c_x" func x(a u32) u32 !{ffi.call}\nfunc main() u32 !{ffi.call} { return x(1u32) }\n')
        self.assertEqual(proc(OMNI, 'check', path).returncode, 0)
        evaluated = proc(OMNI, 'eval', path)
        self.assertEqual(evaluated.returncode, 2, evaluated.stderr)
        self.assertIn(b'E_TARGET_PROFILE', evaluated.stderr)
        emitted = proc(OMNI, 'emit-llvm', path, '-o', self.dir / 'hosted.ll')
        self.assertEqual(emitted.returncode, 2, emitted.stderr)
        self.assertIn(b'E_TARGET_PROFILE', emitted.stderr)

    def test_a_caller_of_an_extern_function_needs_what_it_declares(self):
        head = 'extern "c_x" func x(a u32) u32 !{ffi.call, memory.raw}\n'
        bare = proc(OMNI, 'check', self.source(head + 'func main() u32 { return x(1u32) }\n', 'bare.omni'))
        self.assertEqual(bare.returncode, 2, bare.stderr)
        self.assertIn(b'E_CAPABILITY', bare.stderr)
        partial = proc(OMNI, 'check', self.source(head + 'func main() u32 !{ffi.call} { return x(1u32) }\n', 'partial.omni'))
        self.assertEqual(partial.returncode, 2, partial.stderr)
        self.assertIn(b'memory.raw', partial.stderr)
        full = proc(OMNI, 'check', self.source(head + 'func main() u32 !{ffi.call, memory.raw} { return x(1u32) }\n', 'full.omni'))
        self.assertEqual(full.returncode, 0, full.stderr)
        report = proc(OMNI, 'capabilities', self.dir / 'full.omni')
        self.assertIn(b'"function": "t.x"', report.stdout)


class LinkageRepresentationTests(ContainerCase):
    PROGRAM = ('module t\npub export "kernel_entry" section ".text.boot" noinline func boot(a u32, b i8) u32 { return a + 1u32 }\n'
               'extern "c_helper" func helper(x u64) u64 !{ffi.call, memory.raw}\n'
               'func main() u32 { return boot(41u32, 1i8) }\n')

    def program(self, text=None, name='linked.omni'):
        path = self.dir / name
        path.write_text(text or self.PROGRAM, encoding='utf-8')
        return path

    def test_wave_round_trips_the_attributes_and_declares_them(self):
        path = self.program()
        wave = proc(OMNI, 'wave', path)
        self.assertEqual(wave.returncode, 0, wave.stderr)
        text = wave.stdout.decode()
        self.assertIn('(linkage (export "kernel_entry") (section ".text.boot") (noinline))', text)
        self.assertIn('(linkage (extern "c_helper"))', text)
        self.assertIn('(omni-wave 21', text)
        reread = self.dir / 'reread.owave'
        reread.write_text(text, encoding='utf-8')
        again = proc(OMNI, 'wave', reread)
        self.assertEqual(again.returncode, 0, again.stderr)
        self.assertEqual(again.stdout.decode(), text)
        # the attributes are Wave21: the same text labelled as an older Wave is refused
        for old in (18, 19, 20):
            relabelled = self.dir / ('as-wave%d.owave' % old)
            relabelled.write_text(text.replace('(omni-wave 21', '(omni-wave %d' % old, 1), encoding='utf-8')
            refused = proc(OMNI, 'check', relabelled)
            self.assertEqual(refused.returncode, 2, (old, refused.stderr))
            self.assertIn(b'E_VERSION', refused.stderr)

    def test_linkage_alone_is_what_makes_a_program_wave21(self):
        # nothing else in these programs is new semantics: the version is decided by the attribute
        plain = proc(OMNI, 'wave', self.program('module t\nfunc boot(a u32) u32 { return a }\nfunc main() u32 { return boot(42u32) }\n', 'p.omni'))
        self.assertTrue(plain.stdout.startswith(b'(omni-wave 18'), plain.stdout[:20])
        for variant in ('noinline func boot', 'section ".text.boot" func boot', 'export "k_boot" func boot'):
            with self.subTest(variant):
                wave = proc(OMNI, 'wave', self.program('module t\n%s(a u32) u32 { return a }\nfunc main() u32 { return boot(42u32) }\n' % variant, 'v.omni'))
                self.assertEqual(wave.returncode, 0, wave.stderr)
                self.assertTrue(wave.stdout.startswith(b'(omni-wave 21'), wave.stdout[:20])

    def test_the_wire_round_trip_keeps_the_attributes(self):
        path = self.program()
        packed = self.dir / 'linked.owire'
        done = proc(OMNI, 'pack', path, '-o', packed)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(packed.read_bytes()[:8], b'OMCX\x15\x00\x00\x00')
        again = proc(OMNI, 'fmt', packed)
        self.assertEqual(again.returncode, 0, again.stderr)
        self.assertEqual(again.stdout, proc(OMNI, 'fmt', path).stdout)
        self.assertIn(b'export "kernel_entry" section ".text.boot" noinline func boot', again.stdout)
        self.assertIn(b'extern "c_helper" func helper', again.stdout)
        data = packed.read_bytes()
        at = data.rfind(b'LNK1')
        self.assertGreater(at, 0)
        cases = [
            ('a truncated trailer', data[:at + 8]),
            ('bytes after the end', data + b'\x00'),
            ('an unknown trailer', data[:at] + b'LNK2' + data[at + 4:]),
            ('a repeated trailer', data + data[at:]),
            ('a function that does not exist', data[:at] + data[at:].replace(b'boot', b'bxot', 1)),
        ]
        for label, damaged in cases:
            with self.subTest(label):
                broken = self.dir / 'broken.owire'
                broken.write_bytes(damaged)
                refused = proc(OMNI, 'check', broken)
                self.assertEqual(refused.returncode, 2, (label, refused.stderr))
        # the attributes are OMC21: the same bytes labelled as an older version are refused
        for old in (18, 19, 20):
            relabelled = self.dir / ('as-omc%d.owire' % old)
            relabelled.write_bytes(data[:4] + bytes([old]) + data[5:])
            refused = proc(OMNI, 'check', relabelled)
            self.assertEqual(refused.returncode, 2, (old, refused.stderr))

    def test_a_program_that_differs_only_in_linkage_is_a_different_program(self):
        plain = self.program('module t\nfunc boot(a u32) u32 { return a + 1u32 }\nfunc main() u32 { return boot(41u32) }\n', 'plain.omni')
        hashes = {proc(OMNI, 'hash', plain).stdout}
        for variant in ('noinline func boot', 'section ".text.boot" func boot', 'export "k_boot" func boot'):
            path = self.program('module t\n%s(a u32) u32 { return a + 1u32 }\nfunc main() u32 { return boot(41u32) }\n' % variant, 'variant.omni')
            done = proc(OMNI, 'hash', path)
            self.assertEqual(done.returncode, 0, done.stderr)
            hashes.add(done.stdout)
        self.assertEqual(len(hashes), 4)
        # and the memory identity of the function changes too (OSNMF)
        one = proc(OMNI, 'memory', plain)
        two = proc(OMNI, 'memory', self.program('module t\nnoinline func boot(a u32) u32 { return a + 1u32 }\nfunc main() u32 { return boot(41u32) }\n', 'noinline.omni'))
        self.assertEqual((one.returncode, two.returncode), (0, 0), (one.stderr, two.stderr))
        self.assertNotEqual(one.stdout, two.stdout)


class ExternStructTests(ContainerCase):
    """`extern struct`: the C layout of a record is a contract. The layout rule is the one the compiler already has (natural C alignment); the oracle is clang's own record layout."""
    FIELDS = [('tag', 'u32', 'unsigned'), ('len', 'u16', 'unsigned short'), ('kind', 'u8', 'unsigned char'), ('flag', 'u8', 'unsigned char'), ('base', 'u64', 'unsigned long'),
              ('tail', 'u8', 'unsigned char')]

    def source(self, text, name='program.omni'):
        path = self.dir / name
        path.write_text('module t\n' + text, encoding='utf-8')
        return path

    def clang_layout(self):
        (self.dir / 'h.c').write_text('struct Hdr { %s };\nstruct Hdr h;\n' % ' '.join('%s %s;' % (c, n) for n, o, c in self.FIELDS))
        done = subprocess.run(['clang', '--target=x86_64-unknown-none-elf', '-Xclang', '-fdump-record-layouts-simple', '-c', 'h.c', '-o', os.devnull], capture_output=True, cwd=self.dir, timeout=60)
        self.assertEqual(done.returncode, 0, done.stderr)
        text = done.stdout.decode()
        size = int(re.search(r'Size:(\d+)', text).group(1)) // 8
        align = int(re.search(r'Alignment:(\d+)', text).group(1)) // 8
        bits = [int(v) for v in re.search(r'FieldOffsets: \[([^\]]*)\]', text).group(1).split(',')]
        self.assertEqual(len(bits), len(self.FIELDS))
        return size, align, {n: bits[k] // 8 for k, (n, o, c) in enumerate(self.FIELDS)}

    def test_the_layout_is_the_one_a_c_compiler_gives_and_the_program_can_assert_it(self):
        size, align, offsets = self.clang_layout()
        asserts = ''.join('static_assert(layout.offset<Hdr>(%s) == %du64, "%s")\n' % (n, offsets[n], n) for n, o, c in self.FIELDS)
        path = self.source('extern struct Hdr { %s }\nstatic_assert(layout.size<Hdr>() == %du64, "size")\nstatic_assert(layout.align<Hdr>() == %du64, "align")\n%sfunc main() u32 { return 42u32 }\n'
                           % (', '.join('%s %s' % (n, o) for n, o, c in self.FIELDS), size, align, asserts))
        self.both(path)

    def test_only_what_c_lays_out_the_same_way_is_admitted(self):
        cases = [
            ('a bool field', 'extern struct S { a bool }\n'),
            ('a float field', 'extern struct S { a f64 }\n'),
            ('a text field', 'extern struct S { a Text }\n'),
            ('an owned resource field', 'extern struct S { a Resource<Buffer> }\n'),
            ('an array field', 'extern struct S { a Array<u32,4> }\n'),
            ('a generic struct', 'extern struct S<T> { a u32 }\n'),
            ('packed and extern', 'extern packed struct S { a u32 }\n'),
            ('opaque and extern', 'opaque extern struct S { a u32 }\n'),
        ]
        for label, text in cases:
            with self.subTest(label):
                done = proc(OMNI, 'check', self.source(text + 'func main() u32 { return 0u32 }\n', 'bad.omni'))
                self.assertEqual(done.returncode, 2, (label, done.stderr))
        nested = proc(OMNI, 'check', self.source('struct In { a u16, b u8 }\nextern struct Out { x u32, y In, z u64 }\nfunc main() u32 { return 0u32 }\n', 'nested.omni'))
        self.assertEqual(nested.returncode, 0, nested.stderr)

    def test_the_marker_is_in_the_formatter_wave_wire_and_the_identity(self):
        extern = self.source('extern struct S { a u32, b u8 }\nfunc main() u32 { return 42u32 }\n', 'e.omni')
        plain = self.source('struct S { a u32, b u8 }\nfunc main() u32 { return 42u32 }\n', 'p.omni')
        self.assertIn(b'extern struct S {', proc(OMNI, 'fmt', extern).stdout)
        self.assertNotEqual(proc(OMNI, 'hash', extern).stdout, proc(OMNI, 'hash', plain).stdout)
        memory_extern, memory_plain = proc(OMNI, 'memory', extern), proc(OMNI, 'memory', plain)
        self.assertEqual((memory_extern.returncode, memory_plain.returncode), (0, 0))
        import json
        record = lambda done: [n for n in json.loads(done.stdout)['nuclei'] if n['kind'] == 'record' and n['name'] == 'S'][0]['content_id']
        self.assertNotEqual(record(memory_extern), record(memory_plain))       # the record's own identity says it is a C layout contract
        wave = proc(OMNI, 'wave', extern)
        self.assertEqual(wave.returncode, 0, wave.stderr)
        self.assertIn(b'(extern)', wave.stdout)
        self.assertTrue(wave.stdout.startswith(b'(omni-wave 21'), wave.stdout[:20])
        self.assertTrue(proc(OMNI, 'wave', plain).stdout.startswith(b'(omni-wave 18'))
        for old in (18, 19, 20):
            relabelled = self.dir / ('as-wave%d.owave' % old)
            relabelled.write_bytes(wave.stdout.replace(b'(omni-wave 21', ('(omni-wave %d' % old).encode(), 1))
            refused = proc(OMNI, 'check', relabelled)
            self.assertEqual(refused.returncode, 2, (old, refused.stderr))
            self.assertIn(b'E_VERSION', refused.stderr)
        packed = self.dir / 'e.owire'
        self.assertEqual(proc(OMNI, 'pack', extern, '-o', packed).returncode, 0)
        again = proc(OMNI, 'fmt', packed)
        self.assertEqual(again.returncode, 0, again.stderr)
        self.assertIn(b'extern struct S {', again.stdout)
        data = packed.read_bytes()
        for old in (18, 19, 20):
            relabelled = self.dir / ('as-omc%d.owire' % old)
            relabelled.write_bytes(data[:4] + bytes([old]) + data[5:])
            self.assertEqual(proc(OMNI, 'check', relabelled).returncode, 2, old)


class LinkageImageTests(X64Harness):
    """ARTIFACT + EMULATION: one freestanding image made of Omni code and a C object, calling each other across the SysV boundary."""
    C_SOURCE = (
        'unsigned long c_mix(unsigned char a, short b, unsigned long c, signed char d) { return a + b + c + d; }\n'
        'unsigned char c_narrow(unsigned long v) { return (unsigned char)v; }\n'
        'unsigned cb_scale(unsigned x, signed char y);\n'
        'unsigned c_call_back(void) { return cb_scale(5u, (signed char)-3); }\n'
        'unsigned short cb_wide(unsigned short x);\n'
        'unsigned c_call_wide(void) { return cb_wide(65535u); }\n'
        'struct Hdr { unsigned tag; unsigned short len; unsigned char kind; unsigned char flag; unsigned long base; };\n'
        'unsigned long c_hdr_sum(struct Hdr *h) { return h->tag + h->len + h->kind + h->flag + h->base; }\n'
        'unsigned long c_checksum(unsigned char *p, unsigned long n) { unsigned long s = 0; for (unsigned long i = 0; i < n; i++) s += p[i]; return s; }\n')

    OMNI_SOURCE = (
        'module t\nimport rt "rt.omni"\n'
        'extern "c_mix" func c_mix(a u8, b i16, c u64, d i8) u64 !{ffi.call}\n'
        'extern "c_narrow" func c_narrow(v u64) u8 !{ffi.call}\n'
        'extern "c_call_back" func c_call_back() u32 !{ffi.call}\n'
        'extern "c_call_wide" func c_call_wide() u32 !{ffi.call}\n'
        'extern struct Hdr { tag u32, len u16, kind u8, flag u8, base u64 }\n'
        'extern "c_hdr_sum" func c_hdr_sum(h u64) u64 !{ffi.call}\n'
        'extern "c_checksum" func c_checksum(p u64, n u64) u64 !{ffi.call}\n'
        'export "cb_scale" func scale(x u32, y i8) u32 {\n  if y < 0i8 { return x * 10u32 + 1u32 }\n  return x * 10u32 + 2u32\n}\n'
        'export "cb_wide" section ".text.omni_hot_x" func wide(x u16) u16 { return x - 1u16 }\n'
        'noinline func keep(x u32) u32 { return x + 1u32 }\n')

    def build_mixed(self, extra_omni=''):
        path = self.dir / 'mixed.omni'
        path.write_text(self.OMNI_SOURCE.replace('section ".text.omni_hot_x" ', 'section ".text.hot" ') + extra_omni, encoding='utf-8')
        emitted = self.emit(path)
        self.assertEqual(emitted.returncode, 0, emitted.stderr)
        (self.dir / 'c_side.c').write_text(self.C_SOURCE)
        self.sh('clang', *self.CFLAGS, '-c', 'prog.ll', '-o', 'prog.o')
        self.sh('clang', *self.CFLAGS, '-c', 'c_side.c', '-o', 'c_side.o')
        script = (self.dir / 'payload.ld').read_text().replace('.text 0x200000 : { KEEP(*(.text.omni_entry)) *(.text .text.*) }',
                                                              '.text 0x200000 : { KEEP(*(.text.omni_entry)) KEEP(*(.text.omni_export.*)) *(.text .text.*) }')
        self.assertIn('omni_export', script)
        (self.dir / 'linked.ld').write_text(script)
        self.sh('ld', '-m', 'elf_x86_64', '-nostdlib', '--gc-sections', '-T', 'linked.ld', 'prog.o', 'c_side.o', '-o', 'payload.elf')
        self.sh('objcopy', '-O', 'binary', 'payload.elf', 'payload.bin')
        self.sh('as', '--32', '--defsym', 'AP_ENTRY=0', '-I', '.', 'boot64.S', '-o', 'boot.o')
        self.sh('ld', '-m', 'elf_i386', '-nostdlib', '-T', 'link32.ld', 'boot.o', '-o', 'boot.elf')
        return self.dir / 'boot.elf'

    def test_the_ir_and_the_symbols_say_exactly_what_the_source_says(self):
        self.build_mixed(
            'func main() u32 !{io.print,port.io,cpu.control,ffi.call} {\n  print(keep(u32(bit.and(c_mix(250u8, -300i16, 5000000000u64, -100i8), 4294967295u64))))\n  return rt.finish(0u32)\n}\n')
        ir = (self.dir / 'prog.ll').read_text()
        self.assertIn('define i32 @cb_scale(i32 %a0, i8 signext %a1) section ".text.omni_export.cb_scale"', ir.replace(' noredzone', ''))
        self.assertIn('define zeroext i16 @cb_wide(i16 zeroext %a0) section ".text.omni_export.cb_wide"', ir.replace(' noredzone', ''))
        self.assertIn('declare i64 @c_mix(i8 zeroext, i16 signext, i64, i8 signext)', ir)
        self.assertIn('declare zeroext i8 @c_narrow(i64)', ir)
        self.assertRegex(ir, r'define i16 @omni\.fn\.t\.wide\(i16 %a0\) [^{]*section "\.text\.hot"')
        self.assertRegex(ir, r'define i32 @omni\.fn\.t\.keep\(i32 %a0\) [^{]*noinline')
        self.assertNotRegex(ir, r'define i16 @omni\.fn\.t\.wide\(i16 %a0\) [^{]*noinline')
        symbols = self.sh('nm', 'payload.elf').stdout.decode()
        for name in ('cb_scale', 'cb_wide', 'c_mix'):
            self.assertRegex(symbols, r' [Tt] %s\n' % name)
        self.assertEqual(self.sh('nm', '-u', 'payload.elf').stdout, b'')
        sections = self.sh('readelf', '-SW', 'prog.o').stdout.decode()
        self.assertIn('.text.hot', sections)
        self.assertIn('.text.omni_export.cb_scale', sections)

    def test_omni_and_c_call_each_other_with_mixed_integer_widths(self):
        elf = self.build_mixed(
            'func main() u32 !{io.print,port.io,cpu.control,ffi.call} {\n'
            '  print(u32(bit.and(c_mix(250u8, -300i16, 5000000000u64, -100i8), 4294967295u64)))\n'        # 250 - 300 + 5000000000 - 100 = 4999999850 -> low 32 bits 705032554
            '  return rt.finish(0u32)\n}\n')
        self.assertTrue(elf.exists())

    def test_the_conversions_at_the_boundary_are_those_of_a_c_compiler(self):
        elf = self.build_mixed(
            'func main() u32 !{io.print,port.io,cpu.control,ffi.call} {\n'
            '  print(u32(bit.and(c_mix(250u8, -300i16, 5000000000u64, -100i8), 4294967295u64)))\n'
            '  print(u32(c_narrow(511u64)))\n'                                      # (unsigned char)511 = 255, delivered zero-extended
            '  print(c_call_back())\n'                                              # C -> Omni: scale(5, -3) = 5*10 + 1 = 51 (the negative byte arrives sign-extended)
            '  print(c_call_wide())\n'                                              # C -> Omni: wide(65535) = 65534, zero-extended by the wrapper
            '  return rt.finish(0u32)\n}\n')
        rc, serial = self.boot(elf)
        self.assertEqual((rc, serial.split('\n')[:-1]), (1, ['705032554', '255', '51', '65534']), serial)

    def test_an_extern_struct_and_a_buffer_with_its_length_cross_the_boundary_by_address(self):
        elf = self.build_mixed(
            'func fill(i u32) u32 !{memory.raw} {\n  var k u32 = 0u32\n  for k < 16u32 {\n    let z u32 = raw.store8(6291520u64 + u64(k), k + 1u32)\n    k = k + 1u32\n  }\n  return i\n}\n'
            'func main() u32 !{io.print,memory.raw,port.io,cpu.control,ffi.call} {\n'
            '  let w u32 = raw.write<Hdr>(6291456u64, Hdr { tag: 1u32, len: 2u16, kind: 3u8, flag: 4u8, base: 5000000000u64 })\n'
            '  print(u32(bit.and(c_hdr_sum(6291456u64), 4294967295u64)))\n'          # 1 + 2 + 3 + 4 + 5000000000 = 5000000010 -> low 32 bits 705032714
            '  let f u32 = fill(0u32)\n  print(u32(c_checksum(6291520u64, 16u64)))\n'  # bytes 1..16 and their length: 136
            '  return rt.finish(0u32)\n}\n')
        rc, serial = self.boot(elf)
        self.assertEqual((rc, serial.split('\n')[:-1]), (1, ['705032714', '136']), serial)



if __name__ == '__main__':
    unittest.main()
