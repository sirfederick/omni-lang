#!/usr/bin/env python3
"""CP-15 (OSNMF projection) and CP-01 row 1.14 (ownership survives every representation).

The writer is the one authority for the version of a representation: what `omni wave` and `omni pack` emit is what the manifest and the build receipt must declare (`wire_profile`, `wave_writer`).
The projection into OSNMF is derived from the verified program, never from labels the user supplies, and ownership must not disappear when a program is serialised and read back."""
from __future__ import annotations
import json
import os
import pathlib
import re
import shutil
import tempfile
import unittest
from language_0_8_3_alpha8 import ROOT, OMNI, proc

STORAGE = ROOT / 'examples' / 'storage'


class Case(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix='omni-cp15-')
        self.dir = pathlib.Path(self.tmp.name)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def source(self, name: str, text: str) -> pathlib.Path:
        path = self.dir / (name + '.omni')
        path.write_text(text, encoding='utf-8')
        return path

    def ok(self, *args) -> bytes:
        done = proc(OMNI, *args)
        self.assertEqual(done.returncode, 0, (args, done.stderr))
        return done.stdout


# one program per version the writer can emit; the content, not a label, decides it
VERSIONED = {
    18: 'module t\nfunc main() u32 { return 7u32 }\n',
    19: 'module t\nfunc main() u32 !{memory.write} {\n  task_scope {\n    spawn child = 1u32;\n    let outcome = join(child);\n    match outcome { Ok(value) { return 1u32; } Err(code) { return code; } }\n  }\n}\n',
    20: 'module t\nfunc main() u32 !{fs.read} { let r = host.read("/etc/hostname", 4u32); match r { Ok(v) { return 0u32; } Err(code) { return code; } } }\n',
    21: 'module t\nopaque struct Id { v u64 }\nfunc make(n u64) Id { return Id { v: n } }\nfunc open(i Id) u64 { return i.v }\nfunc main() u32 { let i = make(5u64)\n  if open(i) == 5u64 { return 0u32 }\n  return 1u32 }\n',
    22: 'module t\nfunc id<T>(x T) T { return x }\nfunc main() u32 { return id<u32>(3u32) }\n',
}
# a second program for the versions that have several reasons to exist
PACKED_21 = 'module t\npacked struct P { a u8, b u32 }\nfunc main() u32 { return 0u32 }\n'


_LEAF = 'struct Leaf { buf Resource<Buffer>, tag u32 }\nstruct Owned { leaf Leaf, spare Resource<Buffer> }\n'
_SLOT = (_LEAF + 'func slot(make bool) Option<Owned> !{memory.write} {\n  if make {\n    let a = buffer.alloc(4u32)\n    match a {\n    Ok(x) {\n      let b = buffer.alloc(2u32)\n      match b {\n      Ok(y) {\n'
         '        let r = Owned { leaf: Leaf { buf: move(x), tag: 36u32 }, spare: move(y) }\n        return Some<Owned>(move(r))\n      } Err(code) { return None<Owned>() }\n      }\n    } Err(code) { return None<Owned>() }\n    }\n  }\n  return None<Owned>()\n}\n')
_FINISH = 'func finish(o Option<Owned>) u32 !{memory.read} {\n  match o { Some(r) { return r.leaf.tag + buffer.len(borrow(r.leaf.buf)) + buffer.len(borrow(r.spare)) } None { return 0u32 } }\n}\n'
_MAKE = ('func make() Array<Resource<Buffer>,3> !{memory.write} {\n  let a = buffer.alloc(4u32)\n  match a { Ok(x) {\n    let b = buffer.alloc(5u32)\n    match b { Ok(y) {\n      let c = buffer.alloc(6u32)\n'
         '      match c { Ok(z) { return array(move(x), move(y), move(z)) } Err(code) { return make() } }\n    } Err(code) { return make() } }\n  } Err(code) { return make() } }\n}\n')
_TOTAL = 'func total(a Array<Resource<Buffer>,3>) u32 !{memory.read} {\n  return buffer.len(borrow(a[0u32])) + buffer.len(borrow(a[1u32])) + buffer.len(borrow(a[2u32])) + array.len(a)\n}\n'

# one valid program per family of ownership that a representation has to carry: the sum with a pending record, an owning Array, an owning Tuple, a nominal resource
OWNERSHIP = {
    'option-record': 'module t\n' + _SLOT + _FINISH + 'func main() u32 !{memory.read,memory.write} {\n  let o = slot(true)\n  let fresh = slot(false)\n  let a = finish(o)\n  return a + finish(fresh)\n}\n',
    'array': 'module t\n' + _MAKE + _TOTAL + 'func main() u32 !{memory.read,memory.write} { let a = make()\n  let n = total(move(a))\n  return n }\n',
    'tuple': 'module t\nfunc main() u32 !{memory.read,memory.write} {\n  let a = buffer.alloc(3u32)\n  match a { Ok(b) {\n    let p = tuple(move(b), 4u32)\n    let (d, z) = move(p)\n    let n = buffer.len(borrow(d))\n    let r = buffer.release(move(d))\n    return n + z + r\n  } Err(code) { return code } }\n}\n',
    'nominal': 'module t\nstruct Tok { h u64 }\nfunc mint() Resource<Tok> { return resource.seal(Tok { h: 7u64 }) }\nfunc eat(t Resource<Tok>) u64 { let r = resource.unseal(move(t))\n  return r.h }\nfunc main() u32 { let t = mint()\n  let v = eat(move(t))\n  return 0u32 }\n',
    'collection': ('module t\nimport seq "seq.omni"\nstruct Tok { h u64 }\nfunc mint(n u64) Resource<Tok> { return resource.seal(Tok { h: n }) }\n'
                   'func eat(f Resource<Tok>) u64 { let r Tok = resource.unseal(move(f))\n  return r.h }\n'
                   'impl seq.Dispose for Tok { func dispose(x Resource<Tok>) u32 !{memory.write} { let r Tok = resource.unseal(move(x))\n  return 1u32 } }\n'
                   'func main() u32 !{memory.read,memory.write} {\n  let c = seq.new<Tok>(2u32)\n  match c { Ok(s) {\n'
                   '    let a = seq.push<Tok>(borrow_mut(s), mint(5u64))\n    match a { Ok(i) { } Err(back) { let z u64 = eat(move(back)) } }\n'
                   '    return seq.destroy<Tok>(move(s))\n  } Err(e) { return e } }\n}\n'),
}
SUPPORT = {'collection': ('seq.omni',)}   # files of examples/storage that a program imports


class WireProfileTests(Case):
    """The manifest and the build receipt name the version the writer emitted. Before this was repaired they said OMC18 for every program above Wave20."""

    def wire_version(self, path: pathlib.Path) -> int:
        blob = path.read_bytes()
        self.assertEqual(blob[:4], b'OMCX')
        return int.from_bytes(blob[4:8], 'little')

    def test_manifest_receipt_wave_and_wire_name_the_same_version(self):
        for index, (version, text) in enumerate(list(VERSIONED.items()) + [(21, PACKED_21)]):
            with self.subTest(version=version, program=text.splitlines()[1][:24]):
                tag = '%d_%d' % (version, index)
                src = self.source('p' + tag, text)
                wave = self.ok('wave', src)
                self.assertTrue(wave.startswith(b'(omni-wave %d' % version), wave[:20])
                packed = self.dir / ('p%s.owire' % tag)
                self.ok('pack', src, '-o', packed)
                self.assertEqual(self.wire_version(packed), version)
                manifest = json.loads(self.ok('manifest', src))
                self.assertEqual(manifest['wire_profile'], 'OMC%d' % version)
                out = self.dir / ('app' + tag)
                self.ok('build', src, '-o', out, '--no-cache')
                receipt = json.loads(pathlib.Path(str(out) + '.ometa.json').read_text())
                self.assertEqual((receipt['wave_writer'], receipt['wire_profile']), (version, 'OMC%d' % version))

    def test_the_programs_that_carry_ownership_declare_the_version_their_content_needs(self):
        expected = {'option-record': 21, 'array': 21, 'tuple': 21, 'nominal': 21, 'collection': 22}
        self.assertEqual(set(expected), set(OWNERSHIP))
        for name, version in expected.items():
            with self.subTest(program=name):
                for support in SUPPORT.get(name, ()):
                    shutil.copy(STORAGE / support, self.dir / support)
                src = self.source('own-' + name, OWNERSHIP[name])
                self.assertTrue(self.ok('wave', src).startswith(b'(omni-wave %d' % version))
                packed = self.dir / (name + '.owire')
                self.ok('pack', src, '-o', packed)
                self.assertEqual(self.wire_version(packed), version)
                self.assertEqual(json.loads(self.ok('manifest', src))['wire_profile'], 'OMC%d' % version)
                out = self.dir / ('own-app-' + name)
                self.ok('build', src, '-o', out, '--no-cache')
                receipt = json.loads(pathlib.Path(str(out) + '.ometa.json').read_text())
                self.assertEqual((receipt['wave_writer'], receipt['wire_profile']), (version, 'OMC%d' % version))

    def test_a_program_read_back_from_any_representation_gets_the_same_profile(self):
        for version in (21, 22):
            with self.subTest(version=version):
                src = self.source('rb%d' % version, VERSIONED[version])
                expected = json.loads(self.ok('manifest', src))
                wave = self.dir / ('rb%d.owave' % version)
                wave.write_bytes(self.ok('wave', src))
                wire = self.dir / ('rb%d.owire' % version)
                self.ok('pack', src, '-o', wire)
                onme = self.dir / ('rb%d.onme' % version)
                self.ok('onme', src, '-o', onme)
                for form in (wave, wire, onme):
                    got = json.loads(self.ok('manifest', form))
                    self.assertEqual(got['wire_profile'], 'OMC%d' % version, form.name)
                    self.assertEqual(got['program_content_id'], expected['program_content_id'], form.name)

    def test_the_libraries_of_the_sdk_that_use_generics_are_authoring_capsules(self):
        for name in ('heap.omni', 'rvec.omni', 'mailbox.omni'):
            with self.subTest(library=name):
                shutil.copy(STORAGE / name, self.dir / name)
                for dep in ('heap.omni',):
                    shutil.copy(STORAGE / dep, self.dir / dep)
                src = self.dir / name
                self.assertEqual(json.loads(self.ok('manifest', src))['wire_profile'], 'OMC22')
                packed = self.dir / (name + '.owire')
                self.ok('pack', src, '-o', packed)
                self.assertEqual(self.wire_version(packed), 22)

    def test_a_label_does_not_change_what_a_program_needs(self):
        """A header that names an older version than the content needs is refused where it is read, so no manifest or receipt can carry it; a version that does not exist is refused too."""
        src = self.source('relabel', VERSIONED[21])
        wave = self.ok('wave', src)
        for label, text in (('older', wave.replace(b'(omni-wave 21', b'(omni-wave 20', 1)), ('older-still', wave.replace(b'(omni-wave 21', b'(omni-wave 18', 1)),
                            ('unknown', wave.replace(b'(omni-wave 21', b'(omni-wave 99', 1)), ('not-a-version', wave.replace(b'(omni-wave 21', b'(omni-wave x', 1))):
            with self.subTest(label=label):
                forged = self.dir / 'forged.owave'
                forged.write_bytes(text)
                for command in ('manifest', 'check', 'pack', 'build'):
                    out = self.dir / ('forged-' + command)
                    done = proc(OMNI, command, forged, *([] if command in ('manifest', 'check') else ['-o', out]))
                    self.assertEqual(done.returncode, 2, (command, done.stderr))
                    self.assertRegex(done.stderr, rb'E_(VERSION|WAVE|PARSE|FORMAT)')
                    if command == 'manifest':
                        self.assertEqual(done.stdout, b'')                                       # no document with a profile on it
                    else:
                        self.assertFalse(out.exists(), command)
                    self.assertFalse(pathlib.Path(str(out) + '.ometa.json').exists(), command)  # and no receipt

    def test_a_wire_header_that_lies_about_its_version_is_refused(self):
        src = self.source('wirelie', VERSIONED[21])
        wire = self.dir / 'wirelie.owire'
        self.ok('pack', src, '-o', wire)
        blob = bytearray(wire.read_bytes())
        for label, version in (('older', 20), ('oldest', 18), ('future', 23), ('huge', 0xFFFFFFFF), ('zero', 0)):
            with self.subTest(label=label):
                forged = self.dir / 'forged.owire'
                bad = bytearray(blob)
                bad[4:8] = version.to_bytes(4, 'little')
                forged.write_bytes(bytes(bad))
                done = proc(OMNI, 'manifest', forged)
                self.assertNotEqual(done.returncode, 0, done.stdout[:80])
                self.assertEqual(done.stdout, b'')


M = 'func main() u32 { return 0u32 }\n'
# pairs of programs that differ in ONE semantic of 1.3 -> the identities of the nucleus that must tell them apart (and only those)
PAIRS = {
    'opaque struct': ('module t\nstruct Id { v u64 }\n' + M, 'module t\nopaque struct Id { v u64 }\n' + M, ('record', 'Id'), {'content_id', 'contract_id'}),
    'packed struct': ('module t\nstruct P { a u8, b u32 }\n' + M, 'module t\npacked struct P { a u8, b u32 }\n' + M, ('record', 'P'), {'content_id', 'contract_id'}),
    'extern struct (C layout contract)': ('module t\nstruct H { a u32, b u64 }\n' + M, 'module t\nextern struct H { a u32, b u64 }\n' + M, ('record', 'H'), {'content_id', 'contract_id'}),
    'exported symbol': ('module t\nfunc f(x u32) u32 { return x }\n' + M, 'module t\nexport "sym_f" func f(x u32) u32 { return x }\n' + M, ('function', 'f'), {'content_id', 'contract_id'}),
    'another exported symbol': ('module t\nexport "sym_a" func f(x u32) u32 { return x }\n' + M, 'module t\nexport "sym_b" func f(x u32) u32 { return x }\n' + M, ('function', 'f'), {'content_id', 'contract_id'}),
    'section (placement, not interface)': ('module t\nfunc f(x u32) u32 { return x }\n' + M, 'module t\nsection ".text.cold" func f(x u32) u32 { return x }\n' + M, ('function', 'f'), {'content_id'}),
    'noinline (placement, not interface)': ('module t\nfunc f(x u32) u32 { return x }\n' + M, 'module t\nnoinline func f(x u32) u32 { return x }\n' + M, ('function', 'f'), {'content_id'}),
    'borrowed vs owned parameter': ('module t\nfunc f(b Borrow<Buffer>) u32 { return 0u32 }\n' + M, 'module t\nfunc f(b Resource<Buffer>) u32 !{memory.write} { return buffer.release(move(b)) }\n' + M, ('function', 'f'), {'type_id', 'content_id', 'contract_id'}),
    'shared vs exclusive borrow': ('module t\nfunc f(b Borrow<Buffer>) u32 { return 0u32 }\n' + M, 'module t\nfunc f(b BorrowMut<Buffer>) u32 { return 0u32 }\n' + M, ('function', 'f'), {'type_id', 'content_id'}),
    'a required capability': ('module t\nfunc f(x u32) u32 { return x }\n' + M, 'module t\nfunc f(x u32) u32 !{memory.atomic} { let v u32 = atomic.load32(5308416u64, 4u32)\n  return x + v }\n' + M, ('function', 'f'), {'content_id', 'contract_id'}),
    'memory order of an atomic': ('module t\nfunc f(x u32) u32 !{memory.atomic} { let v u32 = atomic.load32(5308416u64, 1u32)\n  return x + v }\n' + M, 'module t\nfunc f(x u32) u32 !{memory.atomic} { let v u32 = atomic.load32(5308416u64, 4u32)\n  return x + v }\n' + M, ('function', 'f'), {'content_id'}),
    'owning Array vs owning Tuple': ('module t\nfunc f(a Array<Resource<Buffer>,2>) u32 { return 0u32 }\n' + M, 'module t\nfunc f(a Tuple<Resource<Buffer>,u32>) u32 { return 0u32 }\n' + M, ('function', 'f'), {'type_id', 'content_id'}),
    'length of an owning Array': ('module t\nfunc f(a Array<Resource<Buffer>,2>) u32 { return 0u32 }\n' + M, 'module t\nfunc f(a Array<Resource<Buffer>,3>) u32 { return 0u32 }\n' + M, ('function', 'f'), {'type_id', 'content_id'}),
    'signed vs unsigned': ('module t\nfunc f(a u32) u32 { return 0u32 }\n' + M, 'module t\nfunc f(a i32) u32 { return 0u32 }\n' + M, ('function', 'f'), {'type_id', 'content_id'}),
    'a CPU feature asked of the target': ('module t\nfunc f() bool { return target.has("sse2") }\n' + M, 'module t\nfunc f() bool { return target.has("avx2") }\n' + M, ('function', 'f'), {'content_id'}),
}


class ProjectionTests(Case):
    """15.2: the semantics of 1.3 reach OSNMF, from the verified program and through every representation."""

    def memory(self, path) -> bytes:
        return self.ok('memory', path)

    def forms(self, src: pathlib.Path) -> dict:
        wave = src.with_suffix('.owave')
        wave.write_bytes(self.ok('wave', src))
        wire = src.with_suffix('.owire')
        self.ok('pack', src, '-o', wire)
        onme = src.with_suffix('.onme')
        self.ok('onme', src, '-o', onme)
        return {'wave': wave, 'wire': wire, 'onme': onme}

    def test_every_valid_program_of_the_repository_projects_identically_through_every_representation(self):
        programs = []
        for sub in ('examples', 'tests/corpus', 'tests/x64'):
            programs += sorted((ROOT / sub).rglob('*.omni'))
        checked = 0
        libraries = 0
        for source in programs:
            if proc(OMNI, 'check', source).returncode != 0:
                continue                                              # a module that needs its consumer to be a program is not a program on its own
            checked += 1
            libraries += b'func main' not in source.read_bytes()
            with self.subTest(program=str(source.relative_to(ROOT))):
                direct = proc(OMNI, 'memory', source)
                self.assertEqual(direct.returncode, 0, direct.stderr)     # including the libraries written over generics: their signatures have a module-qualified identity
                work = pathlib.Path(tempfile.mkdtemp(prefix='rt-', dir=self.dir))
                forms = {}
                forms['wave'] = work / 'p.owave'
                forms['wave'].write_bytes(self.ok('wave', source))
                forms['wire'] = work / 'p.owire'
                self.ok('pack', source, '-o', forms['wire'])
                forms['onme'] = work / 'p.onme'
                self.ok('onme', source, '-o', forms['onme'])
                for name, form in forms.items():
                    self.assertEqual(self.memory(form), direct.stdout, name)
        self.assertGreaterEqual(checked, 80, 'the survey must stay meaningful')
        self.assertGreaterEqual(libraries, 10)                          # the SDK libraries (heap, rvec, seq, map, coop...) are part of it

    def test_one_semantic_changes_the_identity_it_belongs_to(self):
        for label, (control, variant, (kind, name), expected) in PAIRS.items():
            with self.subTest(semantic=label):
                stores = []
                for tag, text in (('c', control), ('v', variant)):
                    src = self.source('pair-%s-%s' % (abs(hash(label)) % 10**8, tag), text)
                    direct = self.memory(src)
                    for form, path in self.forms(src).items():
                        self.assertEqual(self.memory(path), direct, (label, tag, form))      # and every representation says the same
                    stores.append(json.loads(direct))
                found = []
                for store in stores:
                    nuclei = [n for n in store['nuclei'] if n['kind'] == kind and n['name'] == name]
                    self.assertEqual(len(nuclei), 1, (label, kind, name))
                    found.append(nuclei[0])
                differ = {k for k in ('type_id', 'content_id', 'contract_id') if found[0][k] != found[1][k]}
                self.assertEqual(differ, expected, label)

    def test_a_program_the_checker_refuses_has_no_projection(self):
        bad = self.source('bad', 'module t\nfunc main() u32 { return true }\n')
        omem = self.dir / 'never.omem'
        for args in (('memory', bad), ('graph', bad), ('summary', bad), ('pulse', bad), ('query', bad, '--kind', 'function'), ('trace', bad, '--entity', 'main'), ('impact', bad, '--entity', 'main'),
                     ('memory-pack', bad, '-o', omem), ('onme', bad, '-o', self.dir / 'never.onme')):
            with self.subTest(command=args[0]):
                done = proc(OMNI, *args)
                self.assertEqual(done.returncode, 2, done.stderr)
                self.assertEqual(done.stdout, b'')
        self.assertFalse(omem.exists())
        self.assertFalse((self.dir / 'never.onme').exists())

    def test_the_projection_is_derived_from_the_program_and_not_from_what_it_says_about_itself(self):
        text = ('module t\n// requires memory.atomic, granted, runtime-observed, compiler-authoritative\n'
                'func atomic_load32(x u32) u32 { return x }\nfunc memory_atomic() u32 !{io.print} { print("memory.atomic granted runtime-observed")\n  return 0u32 }\n'
                'func main() u32 !{io.print} { return atomic_load32(memory_atomic()) }\n')
        store = json.loads(self.memory(self.source('names', text)))
        self.assertEqual([n['name'] for n in store['nuclei'] if n['kind'] == 'capability'], ['io.print'])        # only what an operation needs
        blob = json.dumps(store)
        for word in ('runtime-observed', 'granted', 'memory.atomic'):
            self.assertNotIn(word, blob.replace('"memory_atomic"', ''), word)

    def test_a_declared_capability_that_nothing_requires_is_not_presented_as_required(self):
        src = self.source('excess', 'module t\nfunc f() u32 !{memory.atomic} { return 0u32 }\nfunc main() u32 { return f() }\n')
        report = {f['function']: f for f in json.loads(self.ok('capabilities', src))['functions']}
        self.assertEqual((report['t.f']['declared'], report['t.f']['required'], report['t.f']['excess']), (['memory.atomic'], [], ['memory.atomic']))
        store = json.loads(self.memory(src))
        by_id = {n['id']: n for n in store['nuclei']}
        f = [n for n in store['nuclei'] if n['kind'] == 'function' and n['name'] == 'f'][0]
        self.assertEqual(f['capabilities'], [])                                                                  # the same truth as `omni capabilities`
        self.assertEqual([n for n in store['nuclei'] if n['kind'] == 'capability'], [])
        self.assertEqual([s for s in store['synapses'] if s['relation'] == 'requires-capability'], [])
        # the declaration is not lost: it is part of the contract of the function
        plain = json.loads(self.memory(self.source('plain', 'module t\nfunc f() u32 { return 0u32 }\nfunc main() u32 { return f() }\n')))
        g = [n for n in plain['nuclei'] if n['kind'] == 'function' and n['name'] == 'f'][0]
        self.assertNotEqual(f['contract_id'], g['contract_id'])
        queried = json.loads(self.ok('query', src, '--capability', 'memory.atomic'))
        self.assertEqual([n for n in queried['nuclei'] if n['name'] == 'f'], [])
        self.assertTrue(by_id)

    def test_authority_is_assigned_by_domain_and_nothing_is_runtime_observed_without_an_observation(self):
        for name, text in OWNERSHIP.items():
            with self.subTest(program=name):
                src = self.stage(name, text)
                for n in json.loads(self.memory(src))['nuclei']:
                    if n['kind'] in ('function', 'record', 'type', 'enum'):
                        self.assertEqual(n['authority'].get('structural'), 'compiler-authoritative', n['name'])
                        self.assertEqual(n['authority'].get('semantic'), 'developer-declared', n['name'])
                    self.assertNotIn('runtime-observed', n['authority'].values(), n['name'])
                    if n['kind'] != 'capability':
                        self.assertNotIn('confidential', n['domains'], n['name'])       # only an authority over the machine is confidential, never a type, a record or a function

    def stage(self, name: str, text: str) -> pathlib.Path:
        for support in SUPPORT.get(name, ()):
            shutil.copy(STORAGE / support, self.dir / support)
        return self.source(name, text)

    def test_the_symbol_an_imported_function_names_is_part_of_its_contract(self):
        def contract(symbol):
            src = self.source('extern-' + symbol, 'module t\nextern "%s" func helper(x u64) u64 !{ffi.call}\nfunc main() u32 !{ffi.call} { let r u64 = helper(1u64)\n  return 0u32 }\n' % symbol)
            nuclei = [n for n in json.loads(self.ok('memory', src))['nuclei'] if n['kind'] == 'function' and n['name'] == 'helper']
            self.assertEqual(len(nuclei), 1)
            return nuclei[0]['contract_id']
        self.assertNotEqual(contract('c_a'), contract('c_b'))               # the same signature bound to another symbol is another contract


class SemanticDiffTests(Case):
    """AI-05 and AI-06 within CP-15: the difference between two versions of a program is the difference between their projections, and the effects graph is made of the requirements the compiler derived."""

    V1 = 'module t\nfunc a(x u32) u32 { return x }\nfunc b(x u32) u32 { return a(x) }\nfunc main() u32 { return b(1u32) }\n'
    ATOMIC = '!{memory.atomic} '

    VERSIONS = {
        'nothing changed': (V1, {'added': [], 'changed': [], 'removed': []}),
        'only formatting and a comment': ('module t\n// a comment\nfunc a(x u32) u32 {\n    return x\n}\n\nfunc b(x u32) u32 { return a(x) }\nfunc main() u32 { return b(1u32) }\n', {'added': [], 'changed': [], 'removed': []}),
        'the body of a': (V1.replace('return x }', 'return x + 1u32 }', 1), {'added': [], 'changed': [('function', 'a'), ('system', 't')], 'removed': []}),
        'a new function': (V1 + 'func c(x u32) u32 { return x }\n', {'added': [('function', 'c')], 'changed': [('system', 't')], 'removed': []}),
        'a removed function': ('module t\nfunc a(x u32) u32 { return x }\nfunc main() u32 { return a(1u32) }\n', {'added': [], 'changed': [('function', 'main'), ('system', 't')], 'removed': [('function', 'b')]}),
        'a capability that propagates up the calls': (V1.replace('func a(x u32) u32 { return x }', 'func a(x u32) u32 !{memory.atomic} { let v u32 = atomic.load32(5308416u64, 4u32)\n  return x + v }')
                                                       .replace('func b(x u32) u32 {', 'func b(x u32) u32 !{memory.atomic} {').replace('func main() u32 {', 'func main() u32 !{memory.atomic} {'),
                                                       {'added': [('capability', 'memory.atomic')], 'changed': [('function', 'a'), ('function', 'b'), ('function', 'main'), ('system', 't')], 'removed': []}),
    }

    def names(self, *programs):
        out = {}
        for src in programs:
            for n in json.loads(self.ok('memory', src))['nuclei']:
                out[n['id']] = (n['kind'], n['name'])
        return out

    def test_the_pulse_between_two_versions_names_exactly_what_changed(self):
        before = self.source('v1', self.V1)
        for label, (text, expected) in self.VERSIONS.items():
            with self.subTest(change=label):
                after = self.source('v2-%d' % abs(hash(label) % 10**8), text)
                pulse = json.loads(self.ok('pulse', after, '--against', before))
                names = self.names(before, after)
                got = {k: sorted(names[i] for i in v) for k, v in pulse['nuclei'].items()}
                self.assertEqual(got, expected)
                self.assertEqual(pulse['continuity'], 'CONTIGUOUS')
                self.assertEqual(pulse['resnapshot_required'], False)
                self.assertIs(pulse['delta_authoritative'], True)
                again = json.loads(self.ok('pulse', after, '--against', before))
                self.assertEqual(pulse, again)                                           # deterministic

    def test_the_effects_graph_is_made_of_the_requirements_the_compiler_derived(self):
        text = self.VERSIONS['a capability that propagates up the calls'][0]
        src = self.source('effects', text)
        graph = json.loads(self.ok('graph', src))
        names = {n['id']: (n['kind'], n['name']) for n in graph['nodes']}
        required = sorted((names[e['from']][1], names[e['to']][1]) for e in graph['edges'] if e['relation'] == 'requires-capability')
        report = {f['function']: f for f in json.loads(self.ok('capabilities', src))['functions']}
        expected = sorted((f.split('.')[-1], c) for f, v in report.items() for c in v['required'])
        self.assertEqual(required, expected)
        self.assertEqual(required, [('a', 'memory.atomic'), ('b', 'memory.atomic'), ('main', 'memory.atomic')])
        # a declaration that nothing requires adds no edge: the graph never says more than the compiler derived
        extra = self.source('declared', 'module t\nfunc f() u32 !{memory.atomic} { return 0u32 }\nfunc main() u32 { return f() }\n')
        self.assertEqual([e for e in json.loads(self.ok('graph', extra))['edges'] if e['relation'] == 'requires-capability'], [])

    def test_the_manifest_is_the_identity_of_the_verified_program(self):
        src = self.source('manifest', self.V1)
        manifest = json.loads(self.ok('manifest', src))
        import hashlib
        self.assertEqual(manifest['program_content_id'], 'sha256:' + hashlib.sha256(self.ok('wave', src)).hexdigest())
        spaced = self.source('manifest2', 'module t\n\n\nfunc a(x u32) u32 { return x }   // same program\nfunc b(x u32) u32 { return a(x) }\nfunc main() u32 { return b(1u32) }\n')
        self.assertEqual(json.loads(self.ok('manifest', spaced))['program_content_id'], manifest['program_content_id'])    # layout and comments are not identity
        other = self.source('manifest3', self.V1.replace('return b(1u32)', 'return b(2u32)'))
        self.assertNotEqual(json.loads(self.ok('manifest', other))['program_content_id'], manifest['program_content_id'])


class OpenTemplateProjectionTests(Case):
    """A generic template is open, but the nominal types its signature names are not: their identity is module-qualified, and until it was resolved here no library written over generics could be projected."""

    HEAD = 'module t\nstruct Box<T> { v T }\nstruct Id { v u64 }\nenum E<T> { A(T), B }\nenum Color { Red, Blue }\n'
    POSITIONS = {
        'a plain enum': 'func f<T>(x Color) u32 { return 0u32 }\n',
        'a generic struct as a parameter': 'func f<T>(b Box<T>) u32 { return 0u32 }\n',
        'a generic struct as the result': 'func f<T>(x T) Box<T> { return Box<T> { v: x } }\n',
        'a plain nominal as the result': 'func f<T>(x T) Id { return Id { v: 1u64 } }\n',
        'inside an Option': 'func f<T>(x T) Option<Box<T>> { return None<Box<T>>() }\n',
        'inside a borrow': 'func f<T>(x Borrow<Box<T>>) Borrow<Box<T>> { return x }\n',
        'a generic enum': 'func f<T>(x T) E<T> { return E.B() }\n',
        'a resource of a nominal': 'func f<T>(x Resource<Id>) u32 { return 0u32 }\n',
    }

    def test_every_position_of_a_template_signature_that_names_a_nominal_type_projects_the_same_through_every_representation(self):
        for index, (label, body) in enumerate(self.POSITIONS.items()):
            with self.subTest(position=label):
                src = self.source('pos%d' % index, self.HEAD + body + 'func main() u32 { return 0u32 }\n')
                self.assertEqual(proc(OMNI, 'check', src).returncode, 0)
                direct = self.ok('memory', src)
                wave = src.with_suffix('.owave')
                wave.write_bytes(self.ok('wave', src))
                wire = src.with_suffix('.owire')
                self.ok('pack', src, '-o', wire)
                onme = src.with_suffix('.onme')
                self.ok('onme', src, '-o', onme)
                for form in (wave, wire, onme):
                    self.assertEqual(self.ok('memory', form), direct, form.suffix)
                templates = [n for n in json.loads(direct)['nuclei'] if n['kind'] == 'function-template']
                self.assertEqual([n['name'] for n in templates], ['f'])

    def test_the_identity_of_a_template_signature_is_the_module_that_declares_the_type_and_not_the_alias_it_is_imported_under(self):
        (self.dir / 'a.omni').write_text('module a\npub struct Tok { h u64 }\n', encoding='utf-8')
        (self.dir / 'b.omni').write_text('module b\npub struct Tok { h u64 }\n', encoding='utf-8')

        def template_type(alias: str, lib: str, where: str) -> str:
            sig = {'result': 'func mk<T>(x T) %s.Tok { return %s.Tok { h: 1u64 } }\n' % (alias, alias),
                   'parameter': 'func mk<T>(x %s.Tok) u32 { return 0u32 }\n' % alias}[where]
            src = self.source('x-%s-%s-%s' % (alias, lib, where), 'module app\nimport %s "%s.omni"\n%sfunc main() u32 { return 0u32 }\n' % (alias, lib, sig))
            store = json.loads(self.ok('memory', src))
            return [n for n in store['nuclei'] if n['kind'] == 'function-template' and n['name'] == 'mk'][0]['type_id']

        for where in ('result', 'parameter'):
            with self.subTest(position=where):
                self.assertEqual(template_type('m', 'a', where), template_type('n', 'a', where))       # the same type under two spellings
                self.assertNotEqual(template_type('m', 'a', where), template_type('m', 'b', where))    # two types under the same spelling

    def test_two_imports_at_once_are_told_apart_by_their_alias(self):
        (self.dir / 'a.omni').write_text('module a\npub struct Tok { h u64 }\n', encoding='utf-8')
        (self.dir / 'b.omni').write_text('module b\npub struct Tok { h u64 }\n', encoding='utf-8')

        def templates(first: str, second: str):
            text = ('module app\nimport m "%s.omni"\nimport n "%s.omni"\nfunc fm<T>(x T) m.Tok { return m.Tok { h: 1u64 } }\nfunc fn_<T>(x T) n.Tok { return n.Tok { h: 1u64 } }\nfunc main() u32 { return 0u32 }\n' % (first, second))
            store = json.loads(self.ok('memory', self.source('dual-%s-%s' % (first, second), text)))
            return {n['name']: n['type_id'] for n in store['nuclei'] if n['kind'] == 'function-template'}

        straight, swapped = templates('a', 'b'), templates('b', 'a')
        self.assertEqual(straight['fm'], templates('a', 'a')['fm'])             # m is a in both: the same signature identity whatever the other alias says
        self.assertEqual(straight['fn_'], templates('b', 'b')['fn_'])           # n is b in both
        self.assertNotEqual(straight['fm'], swapped['fm'])                      # when m names the other module, the signature is another one
        self.assertNotEqual(straight['fn_'], swapped['fn_'])

    def test_a_template_keeps_the_capabilities_it_declares_and_a_function_only_the_ones_it_requires(self):
        src = self.source('caps', 'module t\nfunc g<T>(x T) T !{memory.raw} { return x }\nfunc h(x u32) u32 !{memory.raw} { return x }\nfunc main() u32 { return g<u32>(h(1u32)) }\n')
        store = json.loads(self.ok('memory', src))
        by = {(n['kind'], n['name']): n for n in store['nuclei'] if n['kind'] in ('function', 'function-template')}
        self.assertEqual(by[('function-template', 'g')]['capabilities'], ['memory.raw'])        # an open template is not analysed: its declaration is all that is known
        self.assertEqual(by[('function', 'h')]['capabilities'], [])                              # a function that was analysed requires nothing
        for (kind, name), n in by.items():
            self.assertNotEqual(n['contract_id'], '')
        self.assertTrue([k for k in by if k[1].startswith('g__')])                               # and the specialisation exists as a function of its own

    def test_a_name_that_is_a_generic_parameter_is_not_taken_for_a_nominal_type(self):
        src = self.source('shadow', 'module t\nstruct Id { v u64 }\nfunc keep<Id>(x Id) Id { return x }\nfunc main() u32 { return keep<u32>(3u32) }\n')
        done = proc(OMNI, 'check', src)
        if done.returncode == 0:                                   # when the language admits the shadowing, the projection must not give the parameter the identity of the record
            store = json.loads(self.ok('memory', src))
            template = [n for n in store['nuclei'] if n['kind'] == 'function-template'][0]
            record = [n for n in store['nuclei'] if n['kind'] == 'record' and n['name'] == 'Id'][0]
            self.assertNotEqual(template['type_id'], record['type_id'])

    def test_a_generic_parameter_is_not_taken_for_a_struct_that_has_its_name(self):
        # `T` is the generic parameter of the template whether or not the module also declares a struct `T`: the identity of the template does not depend on an unrelated declaration
        def template_nucleus(struct_name):
            src = self.source('shadow-' + struct_name, 'module m\nstruct %s { a u32 }\nfunc hold<T>(x Resource<T>) Resource<T> { return x }\nfunc main() u32 { return 0u32 }\n' % struct_name)
            nuclei = [n for n in json.loads(self.ok('memory', src))['nuclei'] if n['kind'] == 'function-template' and n['name'] == 'hold']
            self.assertEqual(len(nuclei), 1)
            return {k: nuclei[0][k] for k in ('id', 'content_id', 'contract_id', 'type_id')}
        self.assertEqual(template_nucleus('T'), template_nucleus('U'))


class TemplateSignatureTests(Case):
    """The types a generic template names in its signature exist when it is declared, as for any function. Before, a typo in a template nobody instantiates passed the checker and only the projection refused it."""

    HEAD = 'module t\nstruct Tok { h u64 }\n'
    MAIN = 'func main() u32 { return 0u32 }\n'
    REFUSED = {
        'an unknown type as a parameter': ('func f<T>(x Nonexistent) u32 { return 0u32 }\n', b'E_TYPE'),
        'an unknown generic type as a parameter': ('func f<T>(x Nonexistent<T>) u32 { return 0u32 }\n', b'E_TYPE'),
        'an unknown type as the result': ('func f<T>(x T) Nonexistent { return x }\n', b'E_TYPE'),
        'unknown inside an Option': ('func f<T>(x Option<Missng>) u32 { return 0u32 }\n', b'E_TYPE'),
        'unknown inside a Result': ('func f<T>(x Result<Missng,u32>) u32 { return 0u32 }\n', b'E_TYPE'),
        'unknown inside an Array': ('func f<T>(x Array<Missng,2>) u32 { return 0u32 }\n', b'E_TYPE'),
        'a resource of an unknown type': ('func f<T>(x Resource<Missng>) u32 { return 0u32 }\n', b'E_RESOURCE_TYPE'),
        'a shared borrow of an unknown type': ('func f<T>(x Borrow<Missng>) u32 { return 0u32 }\n', b'E_RESOURCE_TYPE'),
        'an exclusive borrow of an unknown type': ('func f<T>(x BorrowMut<Missng>) u32 { return 0u32 }\n', b'E_RESOURCE_TYPE'),
        'an alias that was not imported': ('func f<T>(x zz.Tok) u32 { return 0u32 }\n', b'E_TYPE'),
    }
    ACCEPTED = {
        'a declared struct': 'func f<T>(x Tok) u32 { return 0u32 }\n',
        'a resource of a declared struct': 'func f<T>(x Resource<Tok>) u32 { return 0u32 }\n',
        'Buffer': 'func f<T>(x Borrow<Buffer>, y Resource<Buffer>, z BorrowMut<Buffer>) u32 { return 0u32 }\n',
        'a generic parameter': 'func f<T>(x Resource<T>, y Borrow<T>) u32 { return 0u32 }\n',
        'a generic struct': 'struct Box<T> { v T }\nfunc f<T>(x Box<T>) Option<Box<T>> { return None<Box<T>>() }\n',
    }

    def test_a_template_that_names_something_that_does_not_exist_is_refused_where_it_is_declared(self):
        for label, (body, code) in self.REFUSED.items():
            with self.subTest(case=label):
                src = self.source('refused', self.HEAD + body + self.MAIN)
                done = proc(OMNI, 'check', src)
                self.assertEqual(done.returncode, 2, done.stderr)
                self.assertIn(code, done.stderr)
                self.assertEqual(proc(OMNI, 'memory', src).stdout, b'')
                self.assertNotEqual(proc(OMNI, 'pack', src, '-o', self.dir / 'never.owire').returncode, 0)
                self.assertFalse((self.dir / 'never.owire').exists())

    def test_the_same_names_in_a_template_that_exist_are_accepted(self):
        for label, body in self.ACCEPTED.items():
            with self.subTest(case=label):
                src = self.source('accepted', self.HEAD + body + self.MAIN)
                self.assertEqual(proc(OMNI, 'check', src).returncode, 0)
                self.ok('memory', src)

    def test_a_qualified_name_that_exists_in_the_imported_module_is_accepted_and_one_that_does_not_is_refused(self):
        (self.dir / 'lib.omni').write_text('module lib\npub struct Tok { h u64 }\n', encoding='utf-8')
        good = self.source('qual-good', 'module app\nimport m "lib.omni"\nfunc f<T>(x m.Tok) u32 { return 0u32 }\n' + self.MAIN)
        self.assertEqual(proc(OMNI, 'check', good).returncode, 0)
        bad = self.source('qual-bad', 'module app\nimport m "lib.omni"\nfunc f<T>(x m.Missing) u32 { return 0u32 }\n' + self.MAIN)
        done = proc(OMNI, 'check', bad)
        self.assertEqual(done.returncode, 2)
        self.assertIn(b'E_TYPE', done.stderr)


class HistoricalIdentityTests(Case):
    """Artifacts written by a certified compiler stay readable by the next one (the golden ONME files were written by the compiler of gate r18), and where the identity did not change the bytes are the same."""

    GOLDEN = ROOT / 'tests' / 'golden' / 'onme-core-1_3-r18'

    def manifest(self) -> dict:
        return json.loads((self.GOLDEN / 'MANIFEST.json').read_text(encoding='utf-8'))

    def test_the_golden_files_are_the_ones_the_certified_compiler_wrote(self):
        import hashlib
        manifest = self.manifest()
        self.assertEqual(manifest['written_by']['gate'], 'r18')
        for group in ('unchanged', 'qualified'):
            self.assertGreaterEqual(len(manifest[group]), 3)
            for rel, entry in manifest[group].items():
                data = (self.GOLDEN / entry['file']).read_bytes()
                self.assertEqual(hashlib.sha256(data).hexdigest(), entry['sha256'], rel)
                self.assertEqual(data[:5].decode(), entry['version'])

    def test_where_the_identity_did_not_change_the_new_compiler_reads_the_old_file_and_writes_the_same_bytes(self):
        for rel, entry in self.manifest()['unchanged'].items():
            with self.subTest(program=rel):
                golden = self.GOLDEN / entry['file']
                self.assertEqual(proc(OMNI, 'check', golden).returncode, 0)
                self.assertEqual(self.ok('memory', golden), self.ok('memory', ROOT / rel))
                again = self.dir / ('again-' + entry['file'])
                self.ok('onme', ROOT / rel, '-o', again)
                self.assertEqual(again.read_bytes(), golden.read_bytes())                 # ONME2 byte for byte

    def test_where_the_current_identity_is_qualified_the_old_file_is_still_read_and_the_new_one_is_onme3(self):
        for rel, entry in self.manifest()['qualified'].items():
            with self.subTest(program=rel):
                golden = self.GOLDEN / entry['file']
                self.assertEqual(entry['version'], 'ONME2')
                self.assertEqual(proc(OMNI, 'check', golden).returncode, 0)            # the ONME2 reader keeps the historical algorithm
                self.assertEqual(self.ok('memory', golden), self.ok('memory', ROOT / rel))
                fresh = self.dir / ('fresh-' + entry['file'])
                self.ok('onme', ROOT / rel, '-o', fresh)
                self.assertEqual(fresh.read_bytes()[:6], b'ONME3\n')                    # what has a new identity says so
                self.assertEqual(proc(OMNI, 'check', fresh).returncode, 0)
                self.assertEqual(self.ok('memory', fresh), self.ok('memory', golden))

    def test_what_the_certified_compilers_never_saw_says_so_with_onme3_and_what_they_did_see_stays_onme2(self):
        cases = {
            'extern struct': ('module t\nextern struct H { a u32, b u64 }\nfunc main() u32 { return 0u32 }\n', b'ONME3\n'),
            'an exported symbol': ('module t\nexport "sym_f" func f(x u32) u32 { return x }\nfunc main() u32 { return 0u32 }\n', b'ONME3\n'),
            'an imported symbol': ('module t\nextern "c_helper" func helper(x u64) u64 !{ffi.call}\nfunc main() u32 !{ffi.call} { let r u64 = helper(1u64)\n  return 0u32 }\n', b'ONME3\n'),
            'a plain program': ('module t\nfunc main() u32 { return 7u32 }\n', b'ONME2\n'),
            'a capability that is declared and used': ('module t\nfunc f() u32 !{memory.atomic} { let v u32 = atomic.load32(5308416u64, 4u32)\n  return v }\nfunc main() u32 !{memory.atomic} { return f() }\n', b'ONME2\n'),
        }
        for label, (text, header) in cases.items():
            with self.subTest(program=label):
                src = self.source('onme-' + label.replace(' ', '-'), text)
                out = self.dir / (src.name + '.onme')
                self.ok('onme', src, '-o', out)
                self.assertEqual(out.read_bytes()[:6], header)
                self.assertEqual(proc(OMNI, 'check', out).returncode, 0)
                self.assertEqual(self.ok('memory', out), self.ok('memory', src))

    def test_a_library_the_certified_compilers_could_not_project_is_written_as_onme3(self):
        for name in ('heap.omni', 'rvec.omni', 'mailbox.omni', 'seq.omni'):
            with self.subTest(library=name):
                shutil.copy(STORAGE / name, self.dir / name)
                shutil.copy(STORAGE / 'heap.omni', self.dir / 'heap.omni')
                out = self.dir / (name + '.onme')
                self.ok('onme', self.dir / name, '-o', out)
                self.assertEqual(out.read_bytes()[:6], b'ONME3\n')
                self.assertEqual(proc(OMNI, 'check', out).returncode, 0)


# An interposed allocator that counts the calls to malloc, calloc and realloc and writes the total at exit. It uses glibc's own entry points, so it needs no dlsym (which allocates while it resolves).
COUNTER_C = r'''
#include <stdio.h>
#include <stdlib.h>
extern void* __libc_malloc(size_t);
extern void* __libc_calloc(size_t, size_t);
extern void* __libc_realloc(void*, size_t);
static unsigned long long calls;
void* malloc(size_t n) { __atomic_fetch_add(&calls, 1, __ATOMIC_RELAXED); return __libc_malloc(n); }
void* calloc(size_t a, size_t b) { __atomic_fetch_add(&calls, 1, __ATOMIC_RELAXED); return __libc_calloc(a, b); }
void* realloc(void* p, size_t n) { __atomic_fetch_add(&calls, 1, __ATOMIC_RELAXED); return __libc_realloc(p, n); }
__attribute__((destructor)) static void report(void) {
    const char* path = getenv("ALLOC_COUNT_FILE");
    if (!path) return;
    FILE* out = fopen(path, "w");
    if (out) { fprintf(out, "%llu\n", calls); fclose(out); }
}
'''


class CostTests(Case):
    """15.5: the cost of the projection grows with the size of the input and not faster, and nothing is allocated per byte. The measure is the number of allocations (an interposed malloc), which is exact and repeatable;
    times and peak memory are measured by the same method and recorded in the receipt, but a wall clock is not a test. The budgets are the measured costs with 25 % of margin: they are a guard against a regression, not a promise."""

    BUDGET_PER_MODULE = {'check': 11500, 'pack': 11500, 'memory': 80000, 'graph': 67000, 'onme': 200000}      # a module of 120 functions, 60 structs of 4 fields and 20 generic templates
    BUDGET_PER_FIELD = {'check': 8, 'memory': 37}
    FIXED = 25000                                                                                              # what a program of no size costs, per command

    @classmethod
    def setUpClass(cls):
        cls.tool = tempfile.TemporaryDirectory(prefix='omni-count-')
        source = pathlib.Path(cls.tool.name) / 'counter.c'
        source.write_text(COUNTER_C)
        cc = shutil.which('gcc') or shutil.which('cc')
        assert cc, 'a C compiler is needed to build the allocation counter (the compiler itself is built with one)'
        cls.lib = pathlib.Path(cls.tool.name) / 'counter.so'
        done = __import__('subprocess').run([cc, '-shared', '-fPIC', '-O1', '-o', str(cls.lib), str(source), '-ldl'], capture_output=True)
        assert done.returncode == 0, done.stderr

    @classmethod
    def tearDownClass(cls):
        cls.tool.cleanup()

    def allocations(self, command: str, src: pathlib.Path) -> int:
        import subprocess
        counted = self.dir / 'count.txt'
        counted.unlink(missing_ok=True)
        out = self.dir / 'out.bin'
        out.unlink(missing_ok=True)
        args = [command, src] + (['-o', out] if command in ('pack', 'onme') else [])
        done = subprocess.run([str(OMNI), *map(str, args)], capture_output=True, timeout=300,
                              env={**os.environ, 'OMNI_HOME': str(ROOT), 'LD_PRELOAD': str(self.lib), 'ALLOC_COUNT_FILE': str(counted)})
        self.assertEqual(done.returncode, 0, (command, done.stderr[:200]))
        return int(counted.read_text().split()[0])

    @staticmethod
    def module_text(i: int) -> str:
        text = 'module m%d\n' % i
        text += ''.join('pub struct S%d { a u32, b u64, c u8, d u32 }\n' % k for k in range(60))
        text += 'pub func q0(x u32) u32 { return x }\n' + ''.join('pub func q%d(x u32) u32 { return q%d(x) }\n' % (k, k - 1) for k in range(1, 120))
        return text + ''.join('pub func g%d<T>(x T) T { return x }\n' % k for k in range(20))

    def project(self, modules: int) -> pathlib.Path:
        work = self.dir / ('proj%d' % modules)
        work.mkdir()
        for i in range(modules):
            (work / ('m%d.omni' % i)).write_text(self.module_text(i), encoding='utf-8')
        main = work / 'p.omni'
        main.write_text('module app\n' + ''.join('import m%d "m%d.omni"\n' % (i, i) for i in range(modules)) + 'func main() u32 { return m0.q119(1u32) }\n', encoding='utf-8')
        return main

    def test_the_cost_grows_linearly_with_the_number_of_modules_and_stays_in_its_budget(self):
        sizes = (8, 16, 32)
        projects = {n: self.project(n) for n in sizes}
        for command, per_module in self.BUDGET_PER_MODULE.items():
            with self.subTest(command=command):
                counts = {n: self.allocations(command, projects[n]) for n in sizes}
                for small, large in ((8, 16), (16, 32)):
                    self.assertLessEqual(counts[large] / counts[small], 2.15, (command, counts))          # twice the input, not more than about twice the allocations
                for n in sizes:
                    self.assertLessEqual(counts[n], per_module * n + self.FIXED, (command, n, counts[n]))

    def test_a_valid_project_of_many_modules_reads_back_from_every_representation_to_the_same_program(self):
        """The invariant of the block: what Omni can check and serialise it can read back, from Particle, Wave, Wire and ONME, with the same semantics, inside the documented limits of each format."""
        src = self.project(64)
        self.assertEqual(proc(OMNI, 'check', src, timeout=120).returncode, 0)
        projection = self.ok('memory', src)
        manifest = json.loads(self.ok('manifest', src))
        forms = {}
        forms['wave'] = self.dir / 'many.owave'
        forms['wave'].write_bytes(self.ok('wave', src))
        forms['wire'] = self.dir / 'many.owire'
        self.ok('pack', src, '-o', forms['wire'])
        forms['onme'] = self.dir / 'many.onme'
        self.ok('onme', src, '-o', forms['onme'])
        self.assertGreater(forms['wave'].stat().st_size, 1024 * 1024)                     # larger than a source file may be: a representation is bound as a representation
        for name, path in forms.items():
            with self.subTest(form=name):
                self.assertEqual(proc(OMNI, 'check', path, timeout=120).returncode, 0)
                self.assertEqual(self.ok('memory', path), projection)
                self.assertEqual(json.loads(self.ok('manifest', path))['program_content_id'], manifest['program_content_id'])
                self.assertEqual(json.loads(self.ok('manifest', path))['wire_profile'], 'OMC22')

    def test_the_cost_per_field_is_constant_and_nothing_is_allocated_per_byte(self):
        def structs(fields: int) -> pathlib.Path:
            body = ''.join('struct R%d { %s }\n' % (i, ', '.join('x%d u32' % k for k in range(fields))) for i in range(100))
            return self.source('fields%d' % fields, 'module t\n' + body + 'func main() u32 { return 0u32 }\n')

        few, many = structs(8), structs(48)
        for command, budget in self.BUDGET_PER_FIELD.items():
            with self.subTest(command=command):
                extra = self.allocations(command, many) - self.allocations(command, few)
                self.assertLessEqual(extra / (40 * 100), budget, (command, extra))                          # per extra field
                self.assertGreater(extra, 0)

        def literal(n: int) -> pathlib.Path:
            return self.source('literal%d' % n, 'module t\nfunc main() u32 !{io.print} {\n  print("%s")\n  return 0u32\n}\n' % ('x' * n))

        short, long = literal(256), literal(4096)
        # 3840 more bytes of literal: the readers and the projection allocate nothing for them, and ONME (which writes the text as a stream) one allocation for every ~27 bytes, never one per byte
        for command, per_byte in (('check', 0.01), ('memory', 0.01), ('pack', 0.01), ('onme', 0.05)):
            with self.subTest(command=command, literal=True):
                self.assertLessEqual(abs(self.allocations(command, long) - self.allocations(command, short)), per_byte * 3840)


class GenericCallDisambiguationTests(Case):
    """`a < b` is a comparison unless the `<` opens type arguments that close before the statement ends. The parser used to pair a `<` with the `>` of a LATER comparison followed by `(`, so valid programs were refused,
    and so was the printed source of the SDK libraries when it came back from a Wave."""

    def run_program(self, name: str, text: str):
        src = self.source(name, text)
        checked = proc(OMNI, 'check', src)
        self.assertEqual(checked.returncode, 0, (name, checked.stderr))
        evaluated = proc(OMNI, 'eval', src)
        wave = self.dir / (name + '.owave')
        wave.write_bytes(self.ok('wave', src))
        again = proc(OMNI, 'eval', wave)                          # the printed form is read back to the same program
        self.assertEqual(proc(OMNI, 'check', wave).returncode, 0, (name, 'wave'))
        self.assertEqual(again.returncode, evaluated.returncode, name)
        return evaluated.returncode

    def test_a_comparison_is_not_paired_with_a_later_greater_than_followed_by_a_parenthesis(self):
        self.assertEqual(self.run_program('later', 'module t\nfunc f(size u64, base u64) u32 {\n  if size < 64u64 { return 1u32 }\n  if size > (base - 1u64) { return 2u32 }\n  return 0u32\n}\nfunc main() u32 { return f(100u64, 5u64) }\n'), 2)
        self.assertEqual(self.run_program('same-expression', 'module t\nfunc f(a u64, b u64) u32 { if a < b && b > (a + 1u64) { return 7u32 }\n  return 0u32 }\nfunc main() u32 { return f(1u64, 5u64) }\n'), 7)
        self.assertEqual(self.run_program('chain', 'module t\nfunc f(a u64, b u64, c u64) u32 { if a < b { if b > (c + 0u64) { return 3u32 } }\n  return 0u32 }\nfunc main() u32 { return f(1u64, 5u64, 2u64) }\n'), 3)

    def test_genuine_generic_calls_and_initialisers_still_parse_after_comparisons(self):
        text = ('module t\nstruct Box<T> { v T }\nfunc id<T>(x T) T { return x }\nfunc pair<A, B>(a A, b B) A { return a }\n'
                'func f(x u32, y u32) u32 {\n  if x < y { return id<u32>(3u32) }\n  let b = Box<u32> { v: 4u32 }\n  if x > (y + 0u32) { return pair<u32, Box<u32>>(5u32, b) }\n  return b.v\n}\n'
                'func main() u32 { return f(1u32, 2u32) }\n')
        self.assertEqual(self.run_program('generic', text), 3)
        self.assertEqual(self.run_program('generic-else', text.replace('f(1u32, 2u32)', 'f(9u32, 2u32)')), 5)
        nested = ('module t\nfunc id<T>(x T) T { return x }\nfunc main() u32 {\n  let o = id<Option<Option<u32>>>(Some<Option<u32>>(Some<u32>(4u32)))\n'
                  '  match o { Some(i) { match i { Some(v) { return v } None { return 1u32 } } } None { return 2u32 } }\n}\n')
        self.assertEqual(self.run_program('nested', nested), 4)

    def test_type_arguments_may_be_qualified_numeric_or_have_underscores_and_a_string_means_a_comparison(self):
        (self.dir / 'lib.omni').write_text('module lib\npub struct My_Tok { v u32 }\npub func id<T>(x T) T { return x }\n', encoding='utf-8')
        text = ('module app\nimport lib "lib.omni"\nfunc main() u32 {\n  let a = lib.id<lib.My_Tok>(lib.My_Tok { v: 3u32 })\n  let b = lib.id<Array<u32,3>>(array(1u32, 2u32, 3u32))\n'
                '  if a.v < 5u32 { return b[0u32] + 1u32 }\n  if a.v > (b[1u32] + 0u32) { return 9u32 }\n  return 0u32\n}\n')
        self.assertEqual(self.run_program('qualified', text), 2)
        # a string cannot be a type argument: `a < "m"` is a comparison (refused by the checker for Text), not the start of `a<...>(`
        refused = self.source('string', 'module t\nfunc f(a Text, b u32, c u32) u32 {\n  if a < "m" { return 1u32 }\n  if b > (c) { return 2u32 }\n  return 0u32\n}\nfunc main() u32 { return 0u32 }\n')
        done = proc(OMNI, 'check', refused)
        self.assertEqual(done.returncode, 2)
        self.assertIn(b'E_TYPE', done.stderr)
        self.assertNotIn(b'E_PARSE', done.stderr)

    def test_the_printed_source_of_every_sdk_library_is_read_back(self):
        for source in sorted(STORAGE.glob('*.omni')):
            with self.subTest(library=source.name):
                if proc(OMNI, 'check', source).returncode != 0:
                    continue
                wave = self.dir / (source.name + '.owave')
                wave.write_bytes(self.ok('wave', source))
                done = proc(OMNI, 'check', wave)
                self.assertEqual(done.returncode, 0, done.stderr)

    def test_a_string_between_a_less_than_and_a_greater_than_is_not_type_arguments(self):
        # `a < "," > (a)`: a string can never be a type argument, so the line is two comparisons and is refused by the type checker, not taken for a generic call
        src = self.source('string-in-angles', 'module t\nfunc main() u32 {\n  let a u32 = 1u32\n  if a < "," > (a) { return 1u32 }\n  return 0u32\n}\n')
        done = proc(OMNI, 'check', src)
        self.assertEqual(done.returncode, 2, done.stderr)
        self.assertIn(b'E_TYPE', done.stderr)

    def test_a_type_argument_may_be_a_name_that_starts_with_an_underscore(self):
        # the lookahead judges a token by its first character: a name that starts with `_` must be accepted as a type argument
        src = self.source('underscore-argument', 'module t\nstruct _node { a u32 }\nfunc id<T>(x T) T { return x }\nfunc main() u32 {\n  let r _node = id<_node>(_node { a: 7u32 })\n  return r.a\n}\n')
        self.assertEqual(proc(OMNI, 'check', src).returncode, 0)
        self.assertEqual(proc(OMNI, 'eval', src).returncode, 7)


AUDIT = {'OMNI_RESOURCE_AUDIT': '1'}


def audited(path):
    """Runs a program under the resource audit: (exit value, acquired, released, live, violations)."""
    import os
    import subprocess
    done = subprocess.run([str(OMNI), 'eval', str(path)], capture_output=True, timeout=30, env={**os.environ, 'OMNI_HOME': str(ROOT), **AUDIT})
    text = done.stderr.decode(errors='replace')
    summary = [line for line in text.splitlines() if line.startswith('audit summary')]
    numbers = dict(part.split('=') for part in summary[-1].split()[2:]) if summary else {}
    violations = [code for code in ('E_RESOURCE_DOUBLE_RELEASE', 'E_RESOURCE_STALE_USE', 'E_SLOT_OCCUPIED', 'E_RESOURCE_HANDLE') if code in text]
    return done.returncode, int(numbers.get('acquired', -1)), int(numbers.get('released', -1)), int(numbers.get('live', -1)), violations


class OwnershipSurvivesRepresentationsTests(Case):
    """15.3 and CP-01 row 1.14: Copy, move, borrow, cleanup and pending obligations do not disappear when a program is serialised, and a forged representation cannot make them disappear."""

    def stage(self, name: str) -> pathlib.Path:
        for support in SUPPORT.get(name, ()):
            shutil.copy(STORAGE / support, self.dir / support)
        return self.source(name, OWNERSHIP[name])

    def forms(self, src: pathlib.Path) -> dict:
        out = {'particle': src}
        out['wave'] = src.with_suffix('.owave')
        out['wave'].write_bytes(self.ok('wave', src))
        out['wire'] = src.with_suffix('.owire')
        self.ok('pack', src, '-o', out['wire'])
        out['onme'] = src.with_suffix('.onme')
        self.ok('onme', src, '-o', out['onme'])
        return out

    def test_a_valid_program_means_the_same_in_every_representation(self):
        for name in OWNERSHIP:
            with self.subTest(program=name):
                src = self.stage(name)
                forms = self.forms(src)
                reference = audited(src)
                self.assertEqual(reference[4], [], reference)
                self.assertGreaterEqual(reference[1], 0, 'the audit must report what it acquired')
                self.assertEqual((reference[1], reference[3]), (reference[2], 0), reference)         # everything acquired was released
                projection = self.ok('memory', src)
                for form, path in forms.items():
                    self.assertEqual(audited(path), reference, form)                                      # same exit value, same acquisitions and releases
                    self.assertEqual(self.ok('memory', path), projection, form)
                    native = self.dir / ('native-' + name + '-' + form)
                    self.ok('build', path, '-o', native, '--no-cache')
                    self.assertEqual(proc(native).returncode, reference[0], form)

    def forgeries(self, wave: bytes):
        """Every way a Wave text can be made to forget an obligation: a move that is not written, an explicit copy-like value, a move turned into a borrow, a binding that stops being fixed."""
        cases = []
        for m in re.finditer(rb'\(call move ', wave):
            i, depth, j = m.end(), 1, m.end()
            while depth and j < len(wave):
                depth += (wave[j:j + 1] == b'(') - (wave[j:j + 1] == b')')
                j += 1
            cases.append(('unwrap-move', wave[:m.start()] + wave[i:j - 1] + wave[j:]))
            cases.append(('move-to-borrow', wave[:m.start()] + b'(call borrow ' + wave[i:]))
            cases.append(('move-to-unknown', wave[:m.start()] + b'(call forged_move ' + wave[i:]))
        return cases

    def test_a_wave_that_forgets_an_obligation_is_refused_by_every_reader(self):
        total = 0
        for name in ('option-record', 'array', 'tuple', 'nominal'):
            with self.subTest(program=name):
                wave = self.ok('wave', self.stage(name))
                cases = self.forgeries(wave)
                self.assertGreaterEqual(len(cases), 2, name)
                for index, (kind, text) in enumerate(cases):
                    forged = self.dir / ('forged-%s-%d.owave' % (name, index))
                    forged.write_bytes(text)
                    outputs = {'pack': self.dir / ('o%d.owire' % index), 'onme': self.dir / ('o%d.onme' % index), 'build': self.dir / ('o%d.bin' % index)}
                    verdicts = {'check': proc(OMNI, 'check', forged).returncode, 'memory': proc(OMNI, 'memory', forged),
                                'manifest': proc(OMNI, 'manifest', forged)}
                    for command, out in outputs.items():
                        verdicts[command] = proc(OMNI, command, forged, '-o', out)
                    codes = {v if isinstance(v, int) else v.returncode for v in verdicts.values()}
                    self.assertEqual(codes, {2}, (name, kind, index, [(k, v if isinstance(v, int) else v.returncode) for k, v in verdicts.items()]))   # nobody accepts it
                    self.assertEqual(verdicts['memory'].stdout, b'')
                    self.assertEqual(verdicts['manifest'].stdout, b'')
                    for out in outputs.values():
                        self.assertFalse(out.exists(), (name, kind, out.name))                              # and nothing is left behind
                    self.assertRegex(verdicts['pack'].stderr, rb'^E_[A-Z_]+:', (name, kind))             # a stable, registered kind of diagnostic
                    total += 1
        self.assertGreaterEqual(total, 16)

    @staticmethod
    def positions(size: int, stride: int):
        head, tail = list(range(0, min(size, 24))), list(range(max(24, size - 40), size))
        return sorted(set(head + list(range(24, max(24, size - 40), stride)) + tail))

    def test_a_forged_wire_or_onme_never_splits_the_readers_and_never_leaves_an_output(self):
        full = os.environ.get('OMNI_FULL_FORGERY') == '1'
        for name in OWNERSHIP:
            src = self.stage(name)
            for form, command in (('owire', 'pack'), ('onme', 'onme')):
                artifact = self.dir / ('%s.%s' % (name, form))
                self.ok(command, src, '-o', artifact)
                blob = artifact.read_bytes()
                stride = 1 if full else max(1, len(blob) // (60 if form == 'owire' else 16))
                accepted = rejected = 0
                for pos in self.positions(len(blob), stride):
                    for delta in (0x01, 0x80):
                        bad = bytearray(blob)
                        bad[pos] ^= delta
                        forged = self.dir / ('forged.' + form)
                        forged.write_bytes(bytes(bad))
                        repacked = self.dir / 'repacked.owire'
                        repacked.unlink(missing_ok=True)
                        checked = proc(OMNI, 'check', forged).returncode
                        memory = proc(OMNI, 'memory', forged)
                        packed = proc(OMNI, 'pack', forged, '-o', repacked).returncode
                        manifest = proc(OMNI, 'manifest', forged)
                        codes = {checked, memory.returncode, packed, manifest.returncode}
                        where = (name, form, pos, delta)
                        if codes == {0}:
                            accepted += 1
                            # an accepted artifact is a valid program: it is projected, re-serialised and read back to the same thing, and it does not break the resource audit
                            again = proc(OMNI, 'memory', repacked)
                            self.assertEqual((again.returncode, again.stdout), (0, memory.stdout), where)
                            run = audited(forged)
                            self.assertEqual(run[4], [], where)
                            if run[1] >= 0:                                    # a program that never acquires prints no summary
                                self.assertEqual((run[1], run[3]), (run[2], 0), where)
                        else:
                            self.assertNotIn(0, codes, ('readers disagree', where, sorted(codes)))
                            self.assertEqual((memory.stdout, manifest.stdout), (b'', b''), where)
                            self.assertFalse(repacked.exists(), where)
                            rejected += 1
                self.assertGreater(accepted + rejected, 20, (name, form))


class QueryTraceImpactTests(Case):
    """15.4: query, trace, impact, the graph and the summary say the same thing about the same program, with bounds, and none of them hands out authority."""

    CHAIN = ('module t\nfunc low(x u32) u32 !{memory.atomic} { let v u32 = atomic.load32(5308416u64, 4u32)\n  return x + v }\n'
             'func mid(x u32) u32 !{memory.atomic} { return low(x) }\nfunc main() u32 !{memory.atomic} { return mid(1u32) }\n')

    def store(self, name: str = 'chain', text: str = CHAIN) -> pathlib.Path:
        src = self.source(name, text)
        self.ok('memory-pack', src, '-o', self.dir / (name + '.omem'))
        return src

    @staticmethod
    def stable(document: dict) -> dict:
        """What a persisted-index read reports about itself is not part of the answer."""
        return {k: v for k, v in document.items() if k not in ('source', 'full_store_parsed', 'full_store_hashed', 'store_bytes_read', 'index_bytes_read', 'commit_bytes_read')}

    def test_the_source_form_and_the_persisted_form_give_the_same_answer(self):
        src = self.store()
        omem = self.dir / 'chain.omem'
        for entity in ('mid', 'low', 'main', 'u32'):
            for (live, persisted) in ((('query', src, '--entity', entity), ('memory-query', omem, '--entity', entity)),
                                      (('trace', src, '--entity', entity), ('memory-trace', omem, '--entity', entity)),
                                      (('impact', src, '--entity', entity), ('memory-impact', omem, '--entity', entity))):
                with self.subTest(entity=entity, command=live[0]):
                    a, b = json.loads(self.ok(*live)), json.loads(self.ok(*persisted))
                    self.assertEqual(self.stable(a), self.stable(b))
                    self.assertEqual(a['source_files_scanned'], 0)
                    self.assertIs(b['full_store_parsed'], False)
        for kind in ('function', 'capability', 'module', 'type'):
            a, b = json.loads(self.ok('query', src, '--kind', kind)), json.loads(self.ok('memory-query', omem, '--kind', kind))
            self.assertEqual(self.stable(a), self.stable(b), kind)
        a, b = json.loads(self.ok('query', src, '--capability', 'memory.atomic')), json.loads(self.ok('memory-query', omem, '--capability', 'memory.atomic'))
        self.assertEqual(self.stable(a), self.stable(b))
        self.assertEqual(sorted(n['name'] for n in a['nuclei'] if n['kind'] == 'function'), ['low', 'main', 'mid'])

    def test_the_graph_the_summary_and_the_store_name_the_same_identities_and_edges(self):
        for name, text in list(OWNERSHIP.items()) + [('chain', self.CHAIN)]:
            with self.subTest(program=name):
                src = self.source(name, text) if name == 'chain' else Case.source(self, name, text)
                for support in SUPPORT.get(name, ()):
                    shutil.copy(STORAGE / support, self.dir / support)
                store = json.loads(self.ok('memory', src))
                graph = json.loads(self.ok('graph', src))
                summary = json.loads(self.ok('summary', src))
                ids = {n['id'] for n in store['nuclei']}
                self.assertEqual({n['id'] for n in graph['nodes']}, ids)
                self.assertEqual({(e['from'], e['to'], e['relation']) for e in graph['edges']}, {(s['from'], s['to'], s['relation']) for s in store['synapses']})
                self.assertEqual((summary['nuclei'], summary['synapses']), (len(store['nuclei']), len(store['synapses'])))
                self.assertEqual((graph['epoch'], graph['system_root']), (store['epoch']['id'], store['epoch']['system_root']))
                for edge in graph['edges']:
                    self.assertIn(edge['from'], ids)
                    self.assertIn(edge['to'], ids)                                                           # an edge never points outside the program
                for n in store['nuclei']:
                    self.assertTrue(n['provenance_ref'].startswith('sha256:'), n['name'])                    # every nucleus says where it comes from

    def test_the_answers_are_deterministic(self):
        src = self.store()
        for args in (('query', src, '--entity', 'mid'), ('trace', src, '--entity', 'mid'), ('impact', src, '--entity', 'low'), ('graph', src), ('summary', src), ('memory', src)):
            self.assertEqual(self.ok(*args), self.ok(*args), args[0])

    def test_no_report_grants_authority_and_the_capabilities_it_names_are_the_required_ones(self):
        src = self.store()
        omem = self.dir / 'chain.omem'
        reports = [('memory', src), ('graph', src), ('summary', src), ('pulse', src), ('capabilities', src), ('query', src, '--kind', 'function'), ('trace', src, '--entity', 'main'),
                   ('impact', src, '--entity', 'main'), ('memory-summary', omem), ('memory-query', omem, '--capability', 'memory.atomic'), ('memory-trace', omem, '--entity', 'main'),
                   ('memory-impact', omem, '--entity', 'main')]
        for args in reports:
            with self.subTest(command=args[0]):
                text = self.ok(*args).decode()
                self.assertNotIn('granted', text)                      # nothing is granted unless a grant was observed, and nothing here observes one
                self.assertNotIn('runtime-observed', text)
        report = {f['function']: f for f in json.loads(self.ok('capabilities', src))['functions']}
        store = json.loads(self.ok('memory', src))
        for n in store['nuclei']:
            if n['kind'] == 'function':
                self.assertEqual(n['capabilities'], report['t.' + n['name']]['required'], n['name'])    # the store and the compiler agree on what is required
        named = sorted(n['name'] for n in store['nuclei'] if n['kind'] == 'capability')
        self.assertEqual(named, sorted({c for f in report.values() for c in f['required']}))

    def test_the_bounds_are_real_and_hostile_selectors_are_answered_without_side_effects(self):
        src = self.store()
        for depth, code in (('0', 0), ('16', 0), ('17', 2), ('99', 2), ('-1', 2), ('x', 2), ('', 2)):
            done = proc(OMNI, 'trace', src, '--entity', 'main', '--depth', depth)
            self.assertEqual(done.returncode, code, (depth, done.stderr))
            if code == 0:
                limits = json.loads(done.stdout)['limits']
                self.assertEqual(limits['requested_depth'], int(depth))
                self.assertLessEqual(limits['requested_depth'], limits['max_depth'])
            else:
                self.assertEqual(done.stdout, b'')
                self.assertRegex(done.stderr, rb'E_(QUERY|CLI)')
        shallow = json.loads(self.ok('trace', src, '--entity', 'main', '--depth', '0'))
        deep = json.loads(self.ok('trace', src, '--entity', 'main', '--depth', '16'))
        self.assertLessEqual(len(shallow['nuclei']), len(deep['nuclei']))
        sentinel = self.dir / 'passwd'
        sentinel.write_text('root:x:0:0')
        for selector in ('../passwd', str(sentinel), '$(touch /tmp/omni-injected)', '"; drop', 'ñ‮', '*', 'main\n', 'A' * 100000):
            for mode in ('--entity', '--kind', '--capability', '--calls'):
                done = proc(OMNI, 'query', src, mode, selector)
                self.assertEqual(done.returncode, 0, (mode, selector[:20], done.stderr))
                document = json.loads(done.stdout)                      # always a well-formed answer, never a crash
                self.assertEqual(document['source_files_scanned'], 0)
                self.assertLess(len(done.stdout), 8 * len(selector) + 4096, 'the answer must not amplify the selector')
                if selector in ('../passwd', str(sentinel), '*'):
                    self.assertEqual(document['nuclei'], [])            # a path or a wildcard is a name that matches nothing, not a file or a pattern
        self.assertFalse(pathlib.Path('/tmp/omni-injected').exists())
        self.assertEqual(sentinel.read_text(), 'root:x:0:0')

    def test_nothing_outside_the_program_or_its_literals_is_in_any_answer(self):
        (self.dir / 'dep.omni').write_text('module dep\npub func d() u32 { return 1u32 }\n', encoding='utf-8')
        (self.dir / 'unrelated.omni').write_text('module unrelated\npub func secret_fn() u32 { return 9u32 }\n', encoding='utf-8')
        app = self.source('app', 'module app\nimport dep "dep.omni"\nfunc main() u32 !{io.print} { print("SECRET_LITERAL_hunter2")\n  return dep.d() }\n')
        omem = self.dir / 'app.omem'
        self.ok('memory-pack', app, '-o', omem)
        store = json.loads(self.ok('memory', app))
        self.assertEqual(sorted(n['name'] for n in store['nuclei'] if n['kind'] == 'module'), ['app', 'dep'])
        outputs = [self.ok(*a) for a in (('memory', app), ('graph', app), ('summary', app), ('pulse', app), ('query', app, '--kind', 'function'), ('trace', app, '--entity', 'main'),
                                         ('impact', app, '--entity', 'main'), ('memory-summary', omem), ('memory-query', omem, '--kind', 'module'))]
        outputs += [path.read_bytes() for path in self.dir.glob('app.omem*')]
        for blob in outputs:
            self.assertNotIn(b'hunter2', blob)
            self.assertNotIn(b'secret_fn', blob)
            self.assertNotIn(b'unrelated', blob)


if __name__ == '__main__':
    unittest.main()
