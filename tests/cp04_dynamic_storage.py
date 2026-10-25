#!/usr/bin/env python3
"""CP-04: allocator and typed dynamic storage (spec/DYNAMIC_STORAGE_CANDIDATE.md).

Core adds two primitives, buffer.grow and buffer.zero; the allocator, the vector and the arena are Omni libraries
(examples/storage) built on them. Every positive program runs in the evaluator and as a native executable and must agree.
The corpus programs repeat their cycle more than 1024 times, so a leaked or double-released buffer exhausts the runtime table.
"""
from __future__ import annotations
import os
import pathlib
import shutil
import tempfile
import unittest
from language_0_8_3_alpha8 import ROOT, OMNI, proc, X64Harness

STORAGE = ROOT / 'examples' / 'storage'
CORPUS = ROOT / 'tests' / 'corpus' / 'cp04'
LIBRARIES = ('vec_u32.omni', 'arena.omni', 'region.omni')
PROGRAMS = ('vec_growth.omni', 'vec_limits.omni', 'arena_layout.omni', 'arena_lifecycle.omni', 'arena_budget.omni')


class StorageCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='omni-cp04-')
        self.dir = pathlib.Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def source(self, text, name='program.omni'):
        path = self.dir / name
        path.write_text('module t\n' + text, encoding='utf-8')
        return path

    def both(self, path, expected=42):
        evaluated = proc(OMNI, 'eval', path, timeout=180)
        self.assertEqual(evaluated.returncode, expected, evaluated.stderr)
        native = self.dir / (path.name + '-native')
        native.unlink(missing_ok=True)
        built = proc(OMNI, 'build', path, '-o', native, '--cache-dir', self.dir / 'cache', timeout=180)
        self.assertEqual(built.returncode, 0, built.stderr)
        executed = proc(native, timeout=180)
        self.assertEqual(executed.returncode, expected, executed.stderr)

    def rejected(self, text, code):
        path = self.source(text, 'bad.omni')
        checked = proc(OMNI, 'check', path)
        self.assertEqual(checked.returncode, 2, checked.stderr)
        self.assertIn(code, checked.stderr)
        output = self.dir / 'never'
        built = proc(OMNI, 'build', path, '-o', output, '--cache-dir', self.dir / 'cache')
        self.assertEqual(built.returncode, 2, built.stderr)
        self.assertFalse(output.exists())


class GrowZeroPrimitiveTests(StorageCase):
    MAIN = 'func main() u32 !{memory.read,memory.write} {\n'
    ONE = 'func v(r Result<u32,u32>) u32 { match r { Ok(n) { return n } Err(e) { return 1000u32 + e } } }\n'

    def wrap(self, body):
        return (self.ONE + self.MAIN + '  let a = buffer.alloc(4u32)\n  match a { Ok(b) {\n' + body +
                '    let rel = buffer.release(move(b))\n    return 42u32\n  } Err(e) { return e } }\n}\n')

    def test_growth_preserves_contents_zero_fills_and_reports_each_refusal(self):
        self.both(self.source(self.wrap(
            '    if v(buffer.write_u32le(borrow_mut(b), 0u32, 305419896u32)) != 1u32 { return 1u32 }\n'
            '    if v(buffer.grow(borrow_mut(b), 16u32)) != 16u32 { return 2u32 }\n'
            '    if buffer.len(borrow(b)) != 16u32 { return 3u32 }\n'
            '    if v(buffer.read_u32le(borrow(b), 0u32)) != 305419896u32 { return 4u32 }\n'
            '    if v(buffer.read_u32le(borrow(b), 12u32)) != 0u32 { return 5u32 }\n'
            '    if v(buffer.grow(borrow_mut(b), 16u32)) != 16u32 { return 6u32 }\n'          # same length is a no-op success
            '    if v(buffer.grow(borrow_mut(b), 8u32)) != 1004u32 { return 7u32 }\n'           # shrinking is refused
            '    if buffer.len(borrow(b)) != 16u32 { return 8u32 }\n'
            '    if v(buffer.grow(borrow_mut(b), 1048577u32)) != 1001u32 { return 9u32 }\n'     # above the 1 MiB per-buffer limit
            '    if buffer.len(borrow(b)) != 16u32 { return 10u32 }\n'
            '    if v(buffer.grow(borrow_mut(b), 4294967295u32)) != 1001u32 { return 11u32 }\n'
            '    if v(buffer.read_u32le(borrow(b), 0u32)) != 305419896u32 { return 12u32 }\n'
            '    if v(buffer.grow(borrow_mut(b), 1048576u32)) != 1048576u32 { return 13u32 }\n'
            '    if v(buffer.read_u32le(borrow(b), 1048572u32)) != 0u32 { return 14u32 }\n'
            '    if v(buffer.read_u32le(borrow(b), 0u32)) != 305419896u32 { return 15u32 }\n')))

    def test_growing_an_empty_buffer_and_zero_length_ranges(self):
        self.both(self.source(
            self.ONE + self.MAIN + '  let a = buffer.alloc(0u32)\n  match a { Ok(b) {\n'
            '    if v(buffer.zero(borrow_mut(b), 0u32, 0u32)) != 1u32 { return 1u32 }\n'
            '    if v(buffer.zero(borrow_mut(b), 0u32, 1u32)) != 1001u32 { return 2u32 }\n'
            '    if v(buffer.grow(borrow_mut(b), 8u32)) != 8u32 { return 3u32 }\n'
            '    if v(buffer.zero(borrow_mut(b), 8u32, 0u32)) != 1u32 { return 4u32 }\n'
            '    if v(buffer.zero(borrow_mut(b), 9u32, 0u32)) != 1001u32 { return 5u32 }\n'
            '    let rel = buffer.release(move(b))\n    return 42u32\n  } Err(e) { return e } }\n}\n'))

    def test_zero_clears_exactly_the_range_and_refuses_out_of_range_without_effect(self):
        self.both(self.source(self.wrap(
            '    if v(buffer.grow(borrow_mut(b), 16u32)) != 16u32 { return 1u32 }\n'
            '    if v(buffer.write_u64le(borrow_mut(b), 0u32, 18446744073709551615u64)) != 1u32 { return 2u32 }\n'
            '    if v(buffer.write_u64le(borrow_mut(b), 8u32, 18446744073709551615u64)) != 1u32 { return 3u32 }\n'
            '    if v(buffer.zero(borrow_mut(b), 4u32, 8u32)) != 1u32 { return 4u32 }\n'
            '    if v(buffer.read_u32le(borrow(b), 0u32)) != 4294967295u32 { return 5u32 }\n'
            '    if v(buffer.read_u32le(borrow(b), 4u32)) != 0u32 { return 6u32 }\n'
            '    if v(buffer.read_u32le(borrow(b), 8u32)) != 0u32 { return 7u32 }\n'
            '    if v(buffer.read_u32le(borrow(b), 12u32)) != 4294967295u32 { return 8u32 }\n'
            '    if v(buffer.zero(borrow_mut(b), 12u32, 5u32)) != 1001u32 { return 9u32 }\n'     # one byte too far: no byte changes
            '    if v(buffer.read_u32le(borrow(b), 12u32)) != 4294967295u32 { return 10u32 }\n'
            '    if v(buffer.zero(borrow_mut(b), 4294967295u32, 2u32)) != 1001u32 { return 11u32 }\n'   # offset + len would wrap
            '    if v(buffer.zero(borrow_mut(b), 1u32, 4294967295u32)) != 1001u32 { return 12u32 }\n'
            '    if v(buffer.read_u32le(borrow(b), 0u32)) != 4294967295u32 { return 13u32 }\n')))

    def test_growth_and_zero_obey_the_borrow_law(self):
        pre = ('func lend(b Borrow<Buffer>) Borrow<Buffer> !{memory.read} { return b }\n'
               'func main() u32 !{memory.read,memory.write} {\n  let a = buffer.alloc(4u32)\n  match a { Ok(b) {\n')
        post = '  } Err(e) { return e } }\n}\n'
        for name, body, code in (
            ('shared borrow live across growth',
             '    let r = borrow(b)\n    let g = buffer.grow(borrow_mut(b), 8u32)\n    match g { Ok(n) { return buffer.len(r) } Err(e) { return e } }\n', b'E_BORROW_CONFLICT'),
            ('returned borrow live across growth',
             '    let r = lend(borrow(b))\n    let g = buffer.grow(borrow_mut(b), 8u32)\n    match g { Ok(n) { return buffer.len(r) } Err(e) { return e } }\n', b'E_BORROW_CONFLICT'),
            ('shared borrow live across zero',
             '    let r = borrow(b)\n    let g = buffer.zero(borrow_mut(b), 0u32, 4u32)\n    match g { Ok(n) { return buffer.len(r) } Err(e) { return e } }\n', b'E_BORROW_CONFLICT'),
            ('mutable borrow live across growth',
             '    let r = borrow_mut(b)\n    let g = buffer.grow(borrow_mut(b), 8u32)\n    match g { Ok(n) { return buffer.len(r) } Err(e) { return e } }\n', b'E_BORROW_CONFLICT'),
            ('growth through a shared borrow',
             '    let g = buffer.grow(borrow(b), 8u32)\n    match g { Ok(n) { return n } Err(e) { return e } }\n', b'E_TYPE'),
            ('zero through a shared borrow',
             '    let g = buffer.zero(borrow(b), 0u32, 1u32)\n    match g { Ok(n) { return n } Err(e) { return e } }\n', b'E_TYPE'),
            ('growth after the owner moved',
             '    let rel = buffer.release(move(b))\n    let g = buffer.grow(borrow_mut(b), 8u32)\n    match g { Ok(n) { return n } Err(e) { return e } }\n', b'E_RESOURCE_MOVED'),
            ('growth outcome ignored',
             '    let g = buffer.grow(borrow_mut(b), 8u32)\n    let rel = buffer.release(move(b))\n    return 0u32\n', b'E_RESULT_UNHANDLED'),
            ('length of the wrong width',
             '    let g = buffer.grow(borrow_mut(b), 8u64)\n    match g { Ok(n) { return n } Err(e) { return e } }\n', b'E_TYPE'),
            ('growth of something that is not a buffer',
             '    let g = buffer.grow(8u32, 8u32)\n    match g { Ok(n) { return n } Err(e) { return e } }\n', b'E_TYPE'),
            ('growth arity', '    let g = buffer.grow(borrow_mut(b))\n    match g { Ok(n) { return n } Err(e) { return e } }\n', b'E_ARITY'),
            ('zero arity', '    let g = buffer.zero(borrow_mut(b), 0u32)\n    match g { Ok(n) { return n } Err(e) { return e } }\n', b'E_ARITY'),
        ):
            with self.subTest(name=name):
                self.rejected(pre + body + post, code)

    def test_every_exit_of_a_grown_buffer_releases_it(self):
        # return, break and continue without an explicit release, 1200 times each: the 1024-slot table is exhausted by any leak
        self.both(self.source(
            'func grown(mode u32) u32 !{memory.read,memory.write} {\n  let a = buffer.alloc(4u32)\n  match a { Ok(b) {\n'
            '    let g = buffer.grow(borrow_mut(b), 64u32)\n    match g { Ok(n) { if mode == 1u32 { return n } } Err(e) { return e } }\n'
            '    let z = buffer.zero(borrow_mut(b), 0u32, 64u32)\n    match z { Ok(n) { return n + 100u32 } Err(e) { return e } }\n'
            '  } Err(e) { return e } }\n}\n'
            'func main() u32 !{memory.read,memory.write} { var i u32 = 0u32; var seen u32 = 0u32\n'
            '  for i < 3600u32 {\n    i = i + 1u32\n    let m u32 = i - (i / 3u32) * 3u32\n'
            '    if m == 0u32 { if grown(1u32) != 64u32 { return 1u32 } continue }\n'
            '    if m == 1u32 { if grown(0u32) != 101u32 { return 2u32 } seen = seen + 1u32 }\n'
            '    if m == 2u32 { if grown(1u32) != 64u32 { return 3u32 } if i > 3500u32 { break } }\n  }\n'
            '  let probe = buffer.alloc(8u32)\n  match probe { Ok(p) { return buffer.len(borrow(p)) + 34u32 } Err(e) { return e } } }\n'))

    def test_grown_bytes_are_zero_even_when_the_memory_was_recycled(self):
        # 64 KiB blocks are recycled by the host allocator without going back to the OS, so a grow that does not clear its new bytes would
        # show the pattern written into the previous (released) buffer.
        self.both(self.source(
            'func dirty() u32 !{memory.read,memory.write} {\n  let a = buffer.alloc(65536u32)\n  match a { Ok(b) {\n'
            '    var k u32 = 1u32\n    for k < 16u32 {\n      let w = buffer.write_u32le(borrow_mut(b), k * 4096u32, 4294967295u32)\n'
            '      match w { Ok(n) { } Err(e) { return e } }\n      k = k + 1u32\n    }\n    return 0u32\n  } Err(e) { return e } }\n}\n'
            'func probe() u32 !{memory.read,memory.write} {\n  let a = buffer.alloc(4u32)\n  match a { Ok(b) {\n'
            '    let g = buffer.grow(borrow_mut(b), 65536u32)\n    match g { Ok(n) { } Err(e) { return 1000u32 + e } }\n'
            '    var k u32 = 1u32\n    var bad u32 = 0u32\n    for k < 16u32 {\n      let r = buffer.read_u32le(borrow(b), k * 4096u32)\n'
            '      match r { Ok(x) { if x != 0u32 { bad = bad + 1u32 } } Err(e) { return 2000u32 + e } }\n      k = k + 1u32\n    }\n'
            '    return bad\n  } Err(e) { return e } }\n}\n'
            'func main() u32 !{memory.read,memory.write} { var i u32 = 0u32\n'
            '  for i < 20u32 {\n    if dirty() != 0u32 { return 1u32 }\n    if probe() != 0u32 { return 2u32 }\n    i = i + 1u32\n  }\n  return 42u32 }\n'))

    def test_runtime_entry_points_are_declared_only_by_programs_that_call_them(self):
        # a program that does not use the primitives must produce the bytes the previous compiler produced: no extra declaration in its IR
        def emitted(name, body):
            path = self.source(body, name + '.omni')
            out = self.dir / (name + '.ll')
            done = proc(OMNI, 'emit-llvm', path, '-o', out)
            self.assertEqual(done.returncode, 0, done.stderr)
            return out.read_text(encoding='utf-8')
        plain = emitted('plain', 'func main() u32 { return 7u32 }\n')
        self.assertNotIn('omni_buffer_grow', plain)
        self.assertNotIn('omni_buffer_zero', plain)
        grow = emitted('grow', self.wrap('    let g = buffer.grow(borrow_mut(b), 8u32)\n    match g { Ok(n) { } Err(e) { return e } }\n'))
        self.assertEqual(grow.count('declare i32 @omni_buffer_grow('), 1)
        self.assertNotIn('omni_buffer_zero', grow)
        zero = emitted('zero', self.wrap('    let z = buffer.zero(borrow_mut(b), 0u32, 1u32)\n    match z { Ok(n) { } Err(e) { return e } }\n'))
        self.assertEqual(zero.count('declare i32 @omni_buffer_zero('), 1)
        self.assertNotIn('omni_buffer_grow', zero)

    def test_growth_and_zero_need_the_write_capability(self):
        self.rejected('func f(b BorrowMut<Buffer>) u32 !{memory.read} {\n  let g = buffer.grow(b, 8u32)\n  match g { Ok(n) { return n } Err(e) { return e } }\n}\n'
                      'func main() u32 { return 0u32 }\n', b'E_CAPABILITY')
        self.rejected('func f(b BorrowMut<Buffer>) u32 !{memory.read} {\n  let g = buffer.zero(b, 0u32, 1u32)\n  match g { Ok(n) { return n } Err(e) { return e } }\n}\n'
                      'func main() u32 { return 0u32 }\n', b'E_CAPABILITY')

    def test_target_profiles_refuse_the_hosted_allocator_primitives(self):
        shutil.copy(ROOT / 'tests' / 'x64' / 'rt.omni', self.dir / 'rt.omni')
        for name, call in (('grow', 'buffer.grow(b, 8u32)'), ('zero', 'buffer.zero(b, 0u32, 1u32)')):
            path = self.dir / f'{name}.omni'
            path.write_text('module t\nimport rt "rt.omni"\nfunc f(b BorrowMut<Buffer>) u32 !{memory.read,memory.write} {\n  let g = ' + call +
                            '\n  match g { Ok(n) { return n } Err(e) { return e } }\n}\n'
                            'func main() u32 !{port.io,cpu.control} { return rt.finish(0u32) }\n', encoding='utf-8')
            result = proc(OMNI, 'emit-llvm', path, '--target-profile', 'baremetal-x86_64', '--service-module', 'rt', '--entry-section', '.text.omni_entry',
                          '-o', self.dir / f'{name}.ll')
            with self.subTest(name=name):
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(b'E_TARGET_PROFILE', result.stderr)
                self.assertFalse((self.dir / f'{name}.ll').exists())

    def test_programs_with_the_primitives_cannot_be_relabelled_as_older_representations(self):
        path = self.source(self.wrap('    let g = buffer.grow(borrow_mut(b), 8u32)\n    match g { Ok(n) { } Err(e) { return e } }\n'))
        wave = proc(OMNI, 'wave', path)
        self.assertEqual(wave.returncode, 0, wave.stderr)
        self.assertTrue(wave.stdout.startswith(b'(omni-wave 21'))
        old = self.dir / 'old.owave'
        old.write_bytes(wave.stdout.replace(b'(omni-wave 21', b'(omni-wave 20', 1))
        result = proc(OMNI, 'check', old)
        self.assertEqual(result.returncode, 2)
        self.assertIn(b'E_VERSION', result.stderr)
        wire = self.dir / 'new.owire'
        self.assertEqual(proc(OMNI, 'pack', path, '-o', wire).returncode, 0)
        raw = bytearray(wire.read_bytes())
        raw[4] = 20
        older = self.dir / 'old.owire'
        older.write_bytes(bytes(raw))
        result = proc(OMNI, 'check', older)
        self.assertEqual(result.returncode, 2)
        self.assertIn(b'E_VERSION', result.stderr)

    def test_programs_with_the_primitives_round_trip_through_every_representation(self):
        path = self.source(self.wrap(
            '    let g = buffer.grow(borrow_mut(b), 16u32)\n    match g { Ok(n) { } Err(e) { return e } }\n'
            '    let z = buffer.zero(borrow_mut(b), 0u32, 4u32)\n    match z { Ok(n) { } Err(e) { return e } }\n'))
        wave = proc(OMNI, 'wave', path)
        self.assertEqual(wave.returncode, 0)
        owave = self.dir / 'rt.owave'
        owave.write_bytes(wave.stdout)
        self.assertEqual(proc(OMNI, 'wave', owave).stdout, wave.stdout)
        wire = self.dir / 'rt.owire'
        self.assertEqual(proc(OMNI, 'pack', path, '-o', wire).returncode, 0)
        self.assertEqual(proc(OMNI, 'wave', wire).stdout, wave.stdout)
        rewire = self.dir / 'rt2.owire'
        self.assertEqual(proc(OMNI, 'pack', owave, '-o', rewire).returncode, 0)
        self.assertEqual(rewire.read_bytes(), wire.read_bytes())
        onme = self.dir / 'rt.onme'
        self.assertEqual(proc(OMNI, 'onme', path, '-o', onme).returncode, 0)
        self.assertEqual(proc(OMNI, 'wave', onme).stdout, wave.stdout)
        for artifact in (path, owave, wire, onme):
            self.assertEqual(proc(OMNI, 'eval', artifact).returncode, 42, artifact.name)


class StorageLibraryTests(StorageCase):
    def stage(self, program):
        for name in LIBRARIES:
            shutil.copy(STORAGE / name, self.dir / name)
        target = self.dir / program
        shutil.copy(CORPUS / program, target)
        return target

    def test_the_library_programs_agree_in_the_evaluator_and_natively(self):
        for program in PROGRAMS:
            with self.subTest(program=program):
                self.both(self.stage(program))

    def test_the_library_programs_survive_the_binary_representation(self):
        program = self.stage('arena_layout.omni')
        wire = self.dir / 'arena_layout.owire'
        self.assertEqual(proc(OMNI, 'pack', program, '-o', wire).returncode, 0)
        self.assertEqual(proc(OMNI, 'eval', wire).returncode, 42)

    def test_a_vector_cannot_grow_while_a_borrow_of_its_storage_is_live(self):
        for name in LIBRARIES:
            shutil.copy(STORAGE / name, self.dir / name)
        pre = ('import vec "vec_u32.omni"\nimport arena "arena.omni"\n'
               'func main() u32 !{memory.read,memory.write} {\n  let a = vec.new_buffer(2u32)\n  match a { Ok(b) {\n')
        post = '  } Err(e) { return e } }\n}\n'
        self.rejected(pre + '    let r = borrow(b)\n    let p = vec.push(borrow_mut(b), 2u32, 9u32)\n'
                      '    match p { Ok(n) { return buffer.len(r) } Err(e) { return e } }\n' + post, b'E_BORROW_CONFLICT')
        self.rejected(pre + '    let r = borrow(b)\n    let g = arena.alloc(borrow_mut(b), arena.new_state(), 64u32, 8u32)\n'
                      '    match g { Ok(x) { return buffer.len(r) } Err(e) { return e } }\n' + post, b'E_BORROW_CONFLICT')

    def test_a_vector_buffer_is_owned_exactly_once(self):
        for name in LIBRARIES:
            shutil.copy(STORAGE / name, self.dir / name)
        pre = 'import vec "vec_u32.omni"\nfunc main() u32 !{memory.read,memory.write} {\n  let a = vec.new_buffer(2u32)\n'
        self.rejected(pre + '  match a { Ok(b) { let rel = buffer.release(move(b))\n    let again = buffer.release(move(b))\n    return again } Err(e) { return e } }\n}\n',
                      b'E_RESOURCE_MOVED')


REGION_TRANSCRIPT = ['5', '5', '5', '6',                                  # A: bad ranges
                     '32', '40', '64', '72', '64', '4000',                # B: offsets follow size and alignment of Small, Wide, Pk, Wide; used; remaining
                     '0', '1099511627781', '9', '1', '1099511627781',     # C: Wide round trip and its bytes
                     '0', '200', '4000000000', '65535', '200', '4000000000',   # C: packed Pk round trip, read back at an unaligned address
                     '96', '7', '1006', '1006', '64', '96', '1001', '4064',    # D: empty block, wrap guards, exact fit, typed out-of-memory, state kept
                     '0', '77', '7',                                      # D: last element, one past it
                     '0', '2', '4', '0', '32', '24',                      # E: reset, new epoch, stale block, zeroed bytes, range starts over
                     '56', '1001', '5', '0', '4096',                      # F: fill to the limit, refuse, shrink refused, extend, allocate again
                     '8', '4', '4', '4',                                  # G: misaligned, out of range, wrong-epoch and over-long (forged count) handles
                     '1010', '10', '4097',                                # H: damaged header, then restored
                     '4066', '0', '0', '0']                               # I: teardown returns the bytes in use and scrubs header and data


class RegionLibraryTests(StorageCase):
    """The raw-memory region allocator (examples/storage/region.omni): checker-level laws, then the evaluator transcript."""
    PRE = 'import region "region.omni"\nstruct Small { a u8 }\nstruct Wide { a u8, d u64, e u8 }\n'

    def stage(self):
        shutil.copy(STORAGE / 'region.omni', self.dir / 'region.omni')

    def test_the_region_is_an_affine_resource_that_is_torn_down_exactly_once(self):
        self.stage()
        pre = self.PRE + 'func main() u32 !{memory.raw} {\n  let c = region.create(8388608u64, 4096u64)\n  match c { Ok(reg) {\n'
        post = '  } Err(e) { return e } }\n}\n'
        for name, body, code in (
            ('never destroyed', '    return 0u32\n', b'E_RESOURCE_UNCONSUMED'),
            ('destroyed twice', '    let a u64 = region.destroy(move(reg))\n    let b u64 = region.destroy(move(reg))\n    return 0u32\n', b'E_RESOURCE_MOVED'),
            ('used after destroy',
             '    let a u64 = region.destroy(move(reg))\n    let s = region.alloc<Small>(borrow_mut(reg))\n    match s { Ok(x) { return 1u32 } Err(e) { return e } }\n', b'E_RESOURCE_MOVED'),
            ('copied', '    let twin = reg\n    let a u64 = region.destroy(move(twin))\n    return 0u32\n', b'E_RESOURCE_ACCESS'),
            ('allocation through a shared borrow',
             '    let s = region.alloc<Small>(borrow(reg))\n    match s { Ok(x) { return 1u32 } Err(e) { return e } }\n', b'E_TYPE'),
            ('allocation outcome ignored',
             '    let s = region.alloc<Small>(borrow_mut(reg))\n    let a u64 = region.destroy(move(reg))\n    return 0u32\n', b'E_RESULT_UNHANDLED'),
            ('a scalar has no layout',
             '    let s = region.alloc<u32>(borrow_mut(reg))\n    match s { Ok(x) { } Err(e) { } }\n    let a u64 = region.destroy(move(reg))\n    return 0u32\n', b'E_LAYOUT'),
        ):
            with self.subTest(name=name):
                self.rejected(pre + body + post, code)

    def test_a_slot_cannot_be_used_as_a_different_type(self):
        self.stage()
        self.rejected(self.PRE + 'func main() u32 !{memory.raw} {\n  let c = region.create(8388608u64, 4096u64)\n  match c { Ok(reg) {\n'
                      '    let s = region.alloc<Small>(borrow_mut(reg))\n    match s { Ok(x) {\n'
                      '      let w = region.store<Wide>(borrow(reg), x, Wide { a: 0u8, d: 0u64, e: 0u8 })\n      match w { Ok(n) { } Err(e) { } }\n'
                      '    } Err(e) { } }\n    let a u64 = region.destroy(move(reg))\n    return 0u32\n  } Err(e) { return e } }\n}\n', b'E_TYPE')

    def test_the_evaluator_transcript_matches_the_hand_derived_one(self):
        self.stage()
        shutil.copy(ROOT / 'tests' / 'x64' / 'rt.omni', self.dir / 'rt.omni')
        text = (CORPUS / 'region_conformance.omni').read_text(encoding='utf-8')
        self.assertIn('return rt.finish(0u32)', text)
        program = self.dir / 'region_eval.omni'
        program.write_text(text.replace('return rt.finish(0u32)', 'return 0u32'), encoding='utf-8')
        done = proc(OMNI, 'eval', program, timeout=120)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(done.stdout.decode().split('\n')[:-1], REGION_TRANSCRIPT)


class RegionFreestandingTests(X64Harness):
    """The same program as a freestanding x86-64 image under QEMU: its serial transcript equals the evaluator's."""

    def test_the_region_allocator_runs_natively_with_the_same_transcript(self):
        shutil.copy(STORAGE / 'region.omni', self.dir / 'region.omni')
        shutil.copy(CORPUS / 'region_conformance.omni', self.dir / 'region_conformance.omni')
        elf = self.build(self.dir / 'region_conformance.omni')
        rc, serial = self.boot(elf)
        self.assertEqual(serial.split('\n')[:-1], REGION_TRANSCRIPT, serial)
        self.assertEqual(rc, 1)                                                 # isa-debug-exit value 0 -> status 1: rt.finish(0)
        self.assertEqual(self.sh('nm', '-u', 'payload.elf').stdout, b'')        # no undefined reference: no libc, no hidden allocator


HEAP_TRANSCRIPT = [
    '5', '5', '5', '6', '99',                                                  # A: bad ranges, the smallest range
    '80', '112', '144', '192', '144', '4', '816', '16', '32',                  # B: payload offsets, carved, live, remaining, block sizes
    '0', '1', '2', '3', '2', '0', '9', '7',                                    # C: W24 round trip, its middle word, element 4 of 5 bytes, one past it
    '0', '1', '16', '0', '0', '112', '0',                                      # D: free, one free block of 16, tag and link zero, reuse of the same address
    '0', '0', '1', '48', '0', '0', '80', '48', '0',                            # E: two frees merge into 48, absorbed head zero, a 24-byte request takes all 48
    '0', '80', '16', '1', '16', '112', '0',                                    # E: free again, split 16 + 16, the rest is reused first
    '0', '112', '848', '0', '0', '192', '4',                                   # F: the last block retreats the carved area; same address, stale old handle
    '0', '1', '0', '1', '64', '0', '0', '0', '0', '0',                         # G: merge with the successor, then with the predecessor (64 bytes), interior zero
    '0', '0', '32', '1',                                                       # G: the merged block touches the end: carved retreats, one block live
    '4', '4', '0', '0', '80', '4', '4',                                        # H: double free, use after free, release, reuse of the address, stale handle
    '8', '4', '4', '11', '6', '4', '11', '0', '0',                             # H: forged descriptors never reach memory (one byte more than the block has: 11), the genuine one works
    '1001', '1006', '1006', '928', '112', '0', '1001', '0', '928',             # I: out of memory, wrap guards, exact fit, exhausted, release
    '112', '0', '0', '0', '112', '4', '0',                                     # J: store 1,2,3; same block with room; zero tail
    '144', '5', '3', '0', '4', '1',                                            # J: moved block keeps elements, stale old, one free block
    '144', '1007', '1001', '1004', '1',                                        # J: same count is the same block; shrink refused; out of memory keeps the block; stale; element kept
    '1010', '10', '10', '0', '1012', '112',                                    # K: damaged header, damaged free list, healed
    '3', '3', '5714309578822403397', '0', '0',                                 # L: live, teardown reports live blocks, header holds the retired mark only, carved area zero
    '2', '112', '1008', '1004', '1004', '1011', '1006', '0', '1004', '80', '3', '3',   # M: descriptor_at: serial recovered, unaligned, outside, wrong count, free block, reuse
    '0', '4', '4', '4',                                                        # M: a copy of a descriptor is revoked by the free of the other
    '0', '0', '80', '0', '4', '4',                                             # N: a stale descriptor inside a live block stays stale even when the block holds its serial
    '0', '0', '2', '9445552', '80', '0', '2', '32', '9445552', '112', '176', '240',    # N2: split keeps the links; the block taken from the list is zero
    '0', '0', '2', '240', '2', '32',                                           # N2: a small free block in front of a large one, the large one is split
    '0', '0', '2', '0', '1', '64', '0', '0', '0',                              # N3: merge with the predecessor at the end of the carved area unlinks it
    '1006', '1006', '6840399175121563660', '1009', '0', '1009',                # P: wrapping sizes, the last serial, the exhausted counter
    '0', '0', '2', '32', '0', '0', '0', '0', '0', '0', '0', '2', '0',          # K2: self, backward, below-the-first-payload, unaligned and beyond-the-area links: reported, never followed; repaired
    '1012', '0', '0', '1012', '12', '0', '12', '4', '1004', '8',               # K2: odd and oversized heads, live head damage, live counter zero, descriptors at the end
    '0', '0', '2', '0', '2', '64', '176', '0', '0',                            # N4: a merge with the successor takes over its link and zeroes the absorbed head
    '0', '5', '0', '0', '1888', '1', '80', '4', '176', '272', '1001',          # Q: the range only grows; free list and serial counter survive; the new space is usable
    '1', '1', '4', '4', '4', '4', '1004', '0', '0', '1', '1',            # R: a descriptor of another heap is refused in both directions, whatever its offset and serial
    '2', '5714309578822403397', '2', '0', '0', '0', '0', '80', '3', '4', '4', '0', '1',   # S: the range keeps its last serial; descriptors of the earlier heap are stale
    '9', '6840399175121563660', '1',                                           # S: retired range with spent serials refused, one serial left, a range that was never a heap starts again
    '0', '0', '0', '0', '1099511627775', '0', '32', '1', '0',               # T: dirty range: blocks come zeroed; fill reaches no neighbour or head
    '0', '0', '18446744073709551615', '160', '18446744073709551615', '0', '0', '1', '1',   # T: release zeroes, the move keeps elements, leak report, the words around the range survive
    '0', '0', '0', '0',                                                        # U: a damaged heap is given back without a leak report and without a retired mark
]

RVEC_TRANSCRIPT = [
    '0', '0', '80',                                                            # A: empty vector: length, capacity, carved
    '1', '4', '4', '4', '5', '8', '9', '16', '10', '16',                       # B: length and capacity after pushes 1, 4, 5, 9, 10
    '1', '64', '208', '55', '1007',                                            # B: merged free block, carved, sum of 1..10, one past the end
    '0', '99', '7', '10', '9', '10', '55',                                     # C: set, get, set out of range, pop, length, push, get
    '13', '1', '2', '3', '4', '4294967296', '7', '3', '9', '0',                # C: Pair vector: pop empty, pushes, capacity, elements, destroy
    '2', '0', '0', '0', '0', '0',                                              # D: two blocks live, destroy, none live, none free, carved zero, heap teardown
    '1001', '4', '4', '0', '40', '2', '0',                                     # E: the push that cannot grow changes nothing
    '1', '0', '0', '0',                                                        # F: refused whole, the metadata block is given back
    '1', '2', '2', '3', '12', '1', '2', '1006', '1001', '0', '2', '12', '2',   # G: reserve in place, by moving, overflow, out of memory changes nothing
    '80', '0', '0', '1004', '1004', '1004', '4', '1', '1',                     # H: blocks released behind the vector's back: typed errors, destroy reports 4, leak report
    '80', '1', '1', '48', '1',                                                 # I: not even the metadata block fits: nothing taken
]


class HeapLibraryTests(StorageCase):
    """The freestanding heap and the vector over it (examples/storage/heap.omni, rvec.omni): checker-level laws, then the evaluator transcripts."""
    PRE = ('import heap "heap.omni"\nimport rvec "rvec.omni"\nstruct Small { a u8 }\nstruct Wide { a u8, d u64, e u8 }\nstruct Holds { r Resource<Buffer> }\n'
           'func both(a BorrowMut<heap.Heap>, b BorrowMut<heap.Heap>) u32 { return 0u32 }\n')

    def stage(self):
        for name in ('heap.omni', 'rvec.omni'):
            shutil.copy(STORAGE / name, self.dir / name)
        shutil.copy(ROOT / 'tests' / 'x64' / 'rt.omni', self.dir / 'rt.omni')

    def main(self, body):
        return (self.PRE + 'func main() u32 !{memory.raw} {\n  let c = heap.create(8388608u64, 4096u64)\n  match c { Ok(hp) {\n'
                + body + '  } Err(e) { return e } }\n}\n')

    def test_the_heap_is_an_affine_resource_that_is_torn_down_exactly_once(self):
        self.stage()
        for name, body, code in (
            ('never destroyed', '    return 0u32\n', b'E_RESOURCE_UNCONSUMED'),
            ('destroyed twice', '    let a u64 = heap.destroy(move(hp))\n    let b u64 = heap.destroy(move(hp))\n    return 0u32\n', b'E_RESOURCE_MOVED'),
            ('used after destroy',
             '    let a u64 = heap.destroy(move(hp))\n    let s = heap.alloc<Small>(borrow_mut(hp))\n    match s { Ok(x) { return 1u32 } Err(e) { return e } }\n', b'E_RESOURCE_MOVED'),
            ('copied', '    let twin = hp\n    let a u64 = heap.destroy(move(twin))\n    return 0u32\n', b'E_RESOURCE_ACCESS'),
            ('allocation through a shared borrow',
             '    let s = heap.alloc<Small>(borrow(hp))\n    match s { Ok(x) { return 1u32 } Err(e) { return e } }\n', b'E_TYPE'),
            ('release through a shared borrow',
             '    let s = heap.alloc<Small>(borrow_mut(hp))\n    match s { Ok(x) { let f = heap.free<Small>(borrow(hp), x)\n      match f { Ok(n) { return 0u32 } Err(e) { return e } } } Err(e) { return e } }\n', b'E_TYPE'),
            ('allocation outcome ignored',
             '    let s = heap.alloc<Small>(borrow_mut(hp))\n    let a u64 = heap.destroy(move(hp))\n    return 0u32\n', b'E_RESULT_UNHANDLED'),
            ('a scalar has no layout',
             '    let s = heap.alloc<u32>(borrow_mut(hp))\n    match s { Ok(x) { } Err(e) { } }\n    let a u64 = heap.destroy(move(hp))\n    return 0u32\n', b'E_LAYOUT'),
        ):
            with self.subTest(name=name):
                self.rejected(self.main(body), code)

    def test_a_block_cannot_be_used_as_a_different_type(self):
        self.stage()
        self.rejected(self.main('    let s = heap.alloc<Small>(borrow_mut(hp))\n    match s { Ok(x) {\n'
                                '      let w = heap.store<Wide>(borrow(hp), x, Wide { a: 0u8, d: 0u64, e: 0u8 })\n      match w { Ok(n) { } Err(e) { } }\n'
                                '    } Err(e) { } }\n    let a u64 = heap.destroy(move(hp))\n    return 0u32\n'), b'E_TYPE')

    def test_a_vector_is_an_affine_resource_that_is_given_back_exactly_once(self):
        self.stage()
        new = '    let nv = rvec.new<Small>(borrow_mut(hp), 2u64)\n    match nv { Ok(v) {\n'
        end = '    } Err(e) { return e } }\n    let a u64 = heap.destroy(move(hp))\n    return 0u32\n'
        for name, body, code in (
            ('never destroyed', '      return 0u32\n', b'E_RESOURCE_UNCONSUMED'),
            ('destroyed twice', '      let a u32 = rvec.destroy<Small>(borrow_mut(hp), move(v))\n      let b u32 = rvec.destroy<Small>(borrow_mut(hp), move(v))\n      return 0u32\n', b'E_RESOURCE_MOVED'),
            ('used after destroy',
             '      let a u32 = rvec.destroy<Small>(borrow_mut(hp), move(v))\n      let n u64 = rvec.len<Small>(borrow(hp), borrow(v))\n      return 0u32\n', b'E_RESOURCE_MOVED'),
            ('push through a shared borrow of the heap',
             '      let p = rvec.push<Small>(borrow(hp), borrow(v), Small { a: 1u8 })\n      let a u32 = rvec.destroy<Small>(borrow_mut(hp), move(v))\n      return 0u32\n', b'E_TYPE'),
            ('push of another element type',
             '      let p = rvec.push<Small>(borrow_mut(hp), borrow(v), Wide { a: 0u8, d: 0u64, e: 0u8 })\n      let a u32 = rvec.destroy<Small>(borrow_mut(hp), move(v))\n      return 0u32\n', b'E_TYPE'),
            ('push outcome ignored',
             '      let p = rvec.push<Small>(borrow_mut(hp), borrow(v), Small { a: 1u8 })\n      let a u32 = rvec.destroy<Small>(borrow_mut(hp), move(v))\n      return 0u32\n', b'E_RESULT_UNHANDLED'),
        ):
            with self.subTest(name=name):
                self.rejected(self.main(new + body + end), code)

    def test_a_range_that_ends_at_the_last_address_is_legal_and_one_more_byte_is_not(self):
        # the evaluator keeps raw memory as plain records, so the top of the address space can be exercised here (a guest image cannot touch it)
        self.stage()
        text = ('import heap "heap.omni"\nstruct S8 { v u64 }\nfunc main() u32 !{memory.raw} {\n  let c = heap.create(18446744073709551360u64, SIZEu64)\n  match c { Ok(hp) {\n'
                '    let a = heap.alloc<S8>(borrow_mut(hp))\n    var r u32 = 7u32\n    match a { Ok(b) {\n      let w = heap.store<S8>(borrow(hp), b, S8 { v: 5u64 })\n'
                '      match w { Ok(n) { r = 0u32 } Err(e) { r = e } }\n      let f = heap.free<S8>(borrow_mut(hp), b)\n      match f { Ok(n) { } Err(e) { r = e } } } Err(e) { r = e } }\n'
                '    let d u64 = heap.destroy(move(hp))\n    return r\n  } Err(e) { return e } }\n}\n')
        for size, expected in (('255', 0), ('256', 6)):
            with self.subTest(size=size):
                path = self.dir / ('top%s.omni' % size)
                path.write_text('module t\n' + text.replace('SIZE', size), encoding='utf-8')
                done = proc(OMNI, 'eval', path, timeout=120)
                self.assertEqual(done.returncode, expected, done.stderr)

    def test_the_owner_of_the_range_cannot_be_forged_opened_or_split(self):
        # a Heap or an RVec built from numbers is a plain value: no borrow, no call and no teardown accepts it, and only the declaring module opens the resource
        self.stage()
        new = '    let nv = rvec.new<Small>(borrow_mut(hp), 2u64)\n    match nv { Ok(v) {\n'
        end = '    } Err(e) { return e } }\n    let a u64 = heap.destroy(move(hp))\n    return 0u32\n'
        for name, body, code in (
            ('a heap from a number cannot be borrowed',
             '    let fake = heap.Heap { h: 8388608u64 }\n    let s = heap.alloc<Small>(borrow_mut(fake))\n    match s { Ok(x) { return 1u32 } Err(e) { return e } }\n    let a u64 = heap.destroy(move(hp))\n    return 0u32\n',
             b'E_RESOURCE_ACCESS'),
            ('a heap from a number cannot be torn down',
             '    let fake = heap.Heap { h: 8388608u64 }\n    let z u64 = heap.destroy(move(fake))\n    let a u64 = heap.destroy(move(hp))\n    return 0u32\n', b'E_RESOURCE_ACCESS'),
            ('a vector from a number cannot be borrowed',
             new + '      let fake = rvec.RVec<Small> { m: 8388688u64 }\n      let n u64 = rvec.len<Small>(borrow(hp), borrow(fake))\n      let a u32 = rvec.destroy<Small>(borrow_mut(hp), move(v))\n      return 0u32\n' + end,
             b'E_RESOURCE_ACCESS'),
            ('the heap resource cannot be opened outside its module',
             '    let inner heap.Heap = resource.peek(borrow(hp))\n    let a u64 = heap.destroy(move(hp))\n    return 0u32\n', b'E_RESOURCE_PRIVATE'),
            ('the vector resource cannot be opened outside its module',
             new + '      let inner rvec.RVec<Small> = resource.unseal(move(v))\n      return 0u32\n' + end, b'E_RESOURCE_PRIVATE'),
            ('the heap cannot be sealed outside its module',
             '    let twin = resource.seal(heap.Heap { h: 8388608u64 })\n    let a u64 = heap.destroy(move(hp))\n    return 0u32\n', b'E_RESOURCE_PRIVATE'),
        ):
            with self.subTest(name=name):
                self.rejected(self.main(body), code)

    def test_borrows_and_moves_keep_the_heap_and_the_vector_alive_for_their_users(self):
        self.stage()
        new = '    let nv = rvec.new<Small>(borrow_mut(hp), 2u64)\n    match nv { Ok(v) {\n'
        end = '    } Err(e) { return e } }\n    let a u64 = heap.destroy(move(hp))\n    return 0u32\n'
        for name, body, code in (
            ('the heap is torn down while it is lent',
             '    let r = borrow(hp)\n    let a u64 = heap.destroy(move(hp))\n    let n u64 = heap.free_blocks(r)\n    return 0u32\n', b'E_BORROW_CONFLICT'),
            ('two exclusive loans of the heap in one call', '    let x u32 = both(borrow_mut(hp), borrow_mut(hp))\n    let a u64 = heap.destroy(move(hp))\n    return x\n', b'E_BORROW_CONFLICT'),
            ('the vector is given back while it is lent',
             new + '      let b = borrow(v)\n      let a u32 = rvec.destroy<Small>(borrow_mut(hp), move(v))\n      let n u64 = rvec.len<Small>(borrow(hp), b)\n      return 0u32\n' + end, b'E_BORROW_CONFLICT'),
            ('an element that owns a resource has no layout (the collections are plain-only)',
             '    let s = heap.alloc<Holds>(borrow_mut(hp))\n    match s { Ok(x) { } Err(e) { } }\n    let a u64 = heap.destroy(move(hp))\n    return 0u32\n', b'E_LAYOUT'),
            ('a vector of elements that own a resource has no layout',
             '    let h = rvec.new<Holds>(borrow_mut(hp), 1u64)\n    match h { Ok(x) { let q u32 = rvec.destroy<Holds>(borrow_mut(hp), move(x)) } Err(e) { } }\n    let a u64 = heap.destroy(move(hp))\n    return 0u32\n', b'E_LAYOUT'),
        ):
            with self.subTest(name=name):
                self.rejected(self.main(body), code)

    def evaluate(self, program):
        text = (CORPUS / program).read_text(encoding='utf-8')
        self.assertIn('return rt.finish(0u32)', text)
        path = self.dir / (program + '-eval.omni')
        path.write_text(text.replace('return rt.finish(0u32)', 'return 0u32'), encoding='utf-8')
        done = proc(OMNI, 'eval', path, timeout=300)
        self.assertEqual(done.returncode, 0, done.stderr)
        return done.stdout.decode().split('\n')[:-1]

    def test_the_evaluator_transcripts_match_the_hand_derived_ones(self):
        self.stage()
        self.assertEqual(self.evaluate('heap_conformance.omni'), HEAP_TRANSCRIPT)
        self.assertEqual(self.evaluate('rvec_conformance.omni'), RVEC_TRANSCRIPT)


class HeapFreestandingTests(X64Harness):
    """The same programs as freestanding x86-64 images under QEMU: no host buffer, no libc, and the serial transcript equals the evaluator's."""

    def run_image(self, program, transcript):
        for name in ('heap.omni', 'rvec.omni'):
            shutil.copy(STORAGE / name, self.dir / name)
        shutil.copy(CORPUS / program, self.dir / program)
        elf = self.build(self.dir / program)
        rc, serial = self.boot(elf)
        self.assertEqual(serial.split('\n')[:-1], transcript, serial)
        self.assertEqual(rc, 1)
        self.assertEqual(self.sh('nm', '-u', 'payload.elf').stdout, b'')

    def test_the_heap_runs_natively_with_the_same_transcript(self):
        self.run_image('heap_conformance.omni', HEAP_TRANSCRIPT)

    def test_the_vector_over_the_heap_runs_natively_with_the_same_transcript(self):
        self.run_image('rvec_conformance.omni', RVEC_TRANSCRIPT)


KTASK_TRANSCRIPT = [
    '20', '20', '20', '6', '20', '99', '0', '0',                               # A: arguments out of range (an 8-aligned stack too), wrapping stack, the highest priority is accepted, nothing left behind
    '7', '0', '10', '2097152', '2113536', '7', '0',                            # B: the fields through the API; the record in the first heap block (id, state)
    '7000010',                                                                 # C: lent for reading to a function of another module
    '1021', '0', '1021', '5', '12', '2', '1000000000022', '3', '1000000000006', '12', '18446744073709551615', '1000000000006', '2', '1000000000022', '1',   # D: the last tick fits, the next one wraps;  new->running refused, new->ready, ready->blocked refused, lent for changing, charge, blocked, charge refused, overflow
    '1020', '1020', '10', '99', '2097152', '255', '2', '1021', '1021', '4', '7004255',   # D: priority range, the stack survives, dead is final
    '1', '0', '0', '0', '0',                                                   # E: one block while the task lives, destroy, nothing left, record zero
    '0', '1', '0', '1001001', '2000002', '0', '0', '0', '0', '0',              # F: two tasks do not see each other and go back in any order
    '0', '1004', '1004', '1000000000004', '4', '0',                            # G: record released behind the owner's back: typed errors, destroy reports 4
    '99', '6', '18446744073709551615', '0', '0',                               # H: the top of the address space ends a stack, one byte more is refused
    '80', '1', '1', '64', '1',                                                 # I: out of memory is typed and changes nothing
]


class KtaskLibraryTests(StorageCase):
    """CP-02 row 2.3b (examples/storage/ktask.omni): a kernel aggregate of several fields lent by API, over the freestanding heap."""
    PRE = ('import heap "heap.omni"\nimport ktask "ktask.omni"\n'
           'func both(a BorrowMut<ktask.Task>, b BorrowMut<ktask.Task>) u32 { return 0u32 }\n'
           'func reads(hp Borrow<heap.Heap>, t Borrow<ktask.Task>) u32 !{memory.raw} {\n  let s = ktask.state(hp, t)\n  match s { Ok(x) { return x } Err(e) { return e } }\n}\n'
           'func leak(hp BorrowMut<heap.Heap>) Borrow<ktask.Task> !{memory.raw} {\n  let n = ktask.create(hp, 1u64, 1u32, 4096u64, 4096u64)\n'
           '  match n { Ok(t) { return borrow(t) } Err(e) { return e } }\n}\n'
           'struct Keep { t Borrow<ktask.Task> }\n')

    def stage(self):
        for name in ('heap.omni', 'ktask.omni'):
            shutil.copy(STORAGE / name, self.dir / name)
        shutil.copy(ROOT / 'tests' / 'x64' / 'rt.omni', self.dir / 'rt.omni')

    def main(self, body):
        return (self.PRE.replace('func leak(hp BorrowMut<heap.Heap>) Borrow<ktask.Task> !{memory.raw} {\n  let n = ktask.create(hp, 1u64, 1u32, 4096u64, 4096u64)\n'
                                 '  match n { Ok(t) { return borrow(t) } Err(e) { return e } }\n}\n', '')
                .replace('struct Keep { t Borrow<ktask.Task> }\n', '')
                + 'func main() u32 !{memory.raw} {\n  let c = heap.create(8388608u64, 4096u64)\n  match c { Ok(hp) {\n'
                  '    let n = ktask.create(borrow_mut(hp), 1u64, 1u32, 4096u64, 4096u64)\n    match n { Ok(t) {\n'
                + body + '    } Err(e) { let z u64 = heap.destroy(move(hp))\n      return e } }\n    let y u64 = heap.destroy(move(hp))\n    return 0u32\n  } Err(e) { return e } }\n}\n')

    def test_a_valid_program_lends_the_task_for_reading_and_for_changing(self):
        self.stage()
        path = self.dir / 'ok.omni'
        path.write_text('module t\n' + self.main('      let a u32 = reads(borrow(hp), borrow(t))\n      let b = ktask.transition(borrow(hp), borrow_mut(t), 1u32)\n'
                                                  '      match b { Ok(p) { } Err(e) { } }\n      let d u32 = ktask.destroy(borrow_mut(hp), move(t))\n'), encoding='utf-8')
        checked = proc(OMNI, 'check', path)
        self.assertEqual(checked.returncode, 0, checked.stderr)

    def test_the_aggregate_cannot_be_reached_forged_or_split_outside_its_module(self):
        self.stage()
        d = '      let d u32 = ktask.destroy(borrow_mut(hp), move(t))\n'
        for name, body, code in (
            ('the record cannot be opened', '      let inner ktask.Task = resource.peek(borrow(t))\n' + d, b'E_RESOURCE_PRIVATE'),
            ('the record cannot be taken out', '      let inner ktask.Task = resource.unseal(move(t))\n', b'E_RESOURCE_PRIVATE'),
            ('a task cannot be sealed from a number', '      let twin = resource.seal(ktask.Task { m: 8388688u64 })\n' + d, b'E_RESOURCE_PRIVATE'),
            ('a task built from a number cannot be lent', '      let fake = ktask.Task { m: 8388688u64 }\n      let a u32 = reads(borrow(hp), borrow(fake))\n' + d, b'E_RESOURCE_ACCESS'),
            ('a task built from a number cannot be given back', '      let fake = ktask.Task { m: 8388688u64 }\n      let q u32 = ktask.destroy(borrow_mut(hp), move(fake))\n' + d, b'E_RESOURCE_ACCESS'),
            ('a field cannot be read or written through the resource', '      let x u32 = t.state\n' + d, b'E_TYPE'),
            ('the task is never given back', '      let a u32 = reads(borrow(hp), borrow(t))\n', b'E_RESOURCE_UNCONSUMED'),
            ('the task is used after it was given back', d + '      let a u32 = reads(borrow(hp), borrow(t))\n', b'E_RESOURCE_MOVED'),
            ('the task is given back twice', d + d, b'E_RESOURCE_MOVED'),
            ('the task is copied', '      let twin = t\n      let e u32 = ktask.destroy(borrow_mut(hp), move(twin))\n', b'E_RESOURCE_ACCESS'),
        ):
            with self.subTest(name=name):
                self.rejected(self.main(body), code)

    def test_loans_of_the_aggregate_obey_the_law_of_the_checker(self):
        self.stage()
        d = '      let d u32 = ktask.destroy(borrow_mut(hp), move(t))\n'
        for name, body, code in (
            ('two changes at once', '      let x u32 = both(borrow_mut(t), borrow_mut(t))\n' + d, b'E_BORROW_CONFLICT'),
            ('a change while a read is lent',
             '      let r = borrow(t)\n      let p = ktask.transition(borrow(hp), borrow_mut(t), 1u32)\n      match p { Ok(q) { } Err(e) { } }\n      let a u32 = reads(borrow(hp), r)\n' + d, b'E_BORROW_CONFLICT'),
            ('the task is given back while it is lent', '      let r = borrow(t)\n' + d + '      let a u32 = reads(borrow(hp), r)\n', b'E_BORROW_CONFLICT'),
            ('a change through a shared loan', '      let p = ktask.transition(borrow(hp), borrow(t), 1u32)\n      match p { Ok(q) { } Err(e) { } }\n' + d, b'E_TYPE'),
        ):
            with self.subTest(name=name):
                self.rejected(self.main(body), code)

    def test_a_loan_cannot_outlive_its_owner_or_be_kept(self):
        self.stage()
        keep = 'struct Keep { t Borrow<ktask.Task> }\n'
        for name, pre, code in (('a loan of a task that dies with the function is returned', self.PRE.replace(keep, ''), b'E_BORROW_ESCAPE'),
                                ('a loan is stored in a record', self.PRE[:self.PRE.index('func leak')] + keep, b'E_TYPE')):
            with self.subTest(name=name):
                path = self.dir / 'leak.omni'
                path.write_text('module t\n' + pre + 'func main() u32 { return 0u32 }\n', encoding='utf-8')
                checked = proc(OMNI, 'check', path)
                self.assertEqual(checked.returncode, 2, checked.stderr)
                self.assertIn(code, checked.stderr)

    def test_the_evaluator_transcript_matches_the_hand_derived_one(self):
        self.stage()
        text = (CORPUS / 'ktask_conformance.omni').read_text(encoding='utf-8')
        path = self.dir / 'ktask_eval.omni'
        path.write_text(text.replace('return rt.finish(0u32)', 'return 0u32'), encoding='utf-8')
        done = proc(OMNI, 'eval', path, timeout=300)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(done.stdout.decode().split('\n')[:-1], KTASK_TRANSCRIPT)


class KtaskFreestandingTests(X64Harness):
    """The same program as a freestanding x86-64 image under QEMU: the lent aggregate needs no host and its transcript equals the evaluator's."""

    def test_the_task_runs_natively_with_the_same_transcript(self):
        for name in ('heap.omni', 'ktask.omni'):
            shutil.copy(STORAGE / name, self.dir / name)
        shutil.copy(CORPUS / 'ktask_conformance.omni', self.dir / 'ktask_conformance.omni')
        elf = self.build(self.dir / 'ktask_conformance.omni')
        rc, serial = self.boot(elf)
        self.assertEqual(serial.split('\n')[:-1], KTASK_TRANSCRIPT, serial)
        self.assertEqual(rc, 1)
        self.assertEqual(self.sh('nm', '-u', 'payload.elf').stdout, b'')


if __name__ == '__main__':
    unittest.main()
