#!/usr/bin/env python3
"""CP-16.3: ONE checker for every way a program reaches the compiler.

A program that the checker refuses must be refused with THE SAME diagnostic whether it arrives as Particle text, as a Wave22 or Wire22 authoring capsule or as an ONME whose commitment is valid; by every command
(analysis, projection, writers, build); through flags, target profiles, the build cache and imports; and a refusal must publish nothing: no stdout, no output file, no cache entry. A parser that decides on its
own, or a command that skips the checker, would show here as a program that is accepted, a different code, or an artifact that exists."""
from __future__ import annotations
import hashlib
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest
from language_0_8_3_alpha8 import ROOT, OMNI

ENV = {**os.environ, 'OMNI_HOME': str(ROOT)}
BAD = {
    'E_TYPE': 'module t\nfunc main() u32 { let a u32 = 1u32 + "x"\n  return a }\n',
    'E_CAPABILITY': 'module t\nfunc main() u32 !pure { print("x")\n  return 0u32 }\n',
    'E_RESOURCE_MOVED': ('module t\nfunc eat(b Resource<Buffer>) u32 !{memory.write} { return 0u32 }\nfunc main() u32 !{memory.read,memory.write} {\n  let a = buffer.alloc(4u32)\n'
                         '  match a { Ok(b) { let x = eat(move(b))\n    let y = eat(move(b))\n    return x + y } Err(c) { return c } }\n}\n'),
    'E_CALL': 'module t\nfunc main() u32 { return absent() }\n',
}
GENERIC = 'module t\nfunc id<T>(x T) T { return x }\nfunc main() u32 { return id<u32>(3u32) }\n'
CODES = {"omni-wave": 'W', "entry": 'E', "module": 'M', "imports": 'I', "func": 'F', "visibility": 'V', "private": 'p', "public": 'P', "params": 'A', "result": 'R', "effects": 'X', "pure": '0',
         "block": 'B', "return": 'r', "let": 'l', "var": 'v', "set": 's', "call": 'c', "ref": 'f', "binary": 'b', "if": 'i', "while": 'w', "for-each": 'e', "struct": 'S', "fields": 'D', "enum": 'N',
         "variants": 'Z', "u8": '1', "u16": '2', "u32": '3', "u64": '4', "i8": '5', "i16": '6', "i32": '7', "i64": '8', "bool": 't', "Text": 'T', "Bytes": 'Y'}


def run(*args, env=None, timeout=120):
    return subprocess.run([str(x) for x in args], capture_output=True, env=env or ENV, timeout=timeout)


def code_of(done) -> str:
    return done.stderr.split(b':')[0].decode(errors='replace')


def capsule_wave(source: str) -> bytes:
    parts = [source[i:i + 4000] for i in range(0, len(source), 4000)]
    quoted = ' '.join('"' + p.replace('\\', '\\\\').replace('"', '\\"').replace('\n', '\\n') + '"' for p in parts)
    return ('(omni-wave 22 (authoring-source ' + quoted + '))\n').encode()


def capsule_wire(source: str) -> bytes:
    body = source.encode()
    return b'OMCX' + (22).to_bytes(4, 'little') + len(body).to_bytes(4, 'little') + body


def tokenize(text: str):
    out, i = [], 0
    while i < len(text):
        c = text[i]
        if c.isspace():
            i += 1
        elif c in '()':
            out.append((False, c)); i += 1
        elif c == '"':
            j, escaped = i + 1, False
            while j < len(text):
                z = text[j]
                if escaped:
                    escaped = False
                elif z == '\\':
                    escaped = True
                elif z == '"':
                    j += 1
                    break
                j += 1
            out.append((True, text[i:j])); i = j
        else:
            j = i
            while j < len(text) and not text[j].isspace() and text[j] not in '()':
                j += 1
            out.append((False, text[i:j])); i = j
    return out


def onme_file(wave_text: str, exec_root: str, author_root: str, version: str = '3') -> bytes:
    """An ONME with a VALID commitment: the integrity check passes and only the checker can refuse what it carries."""
    body = ''
    for quoted, token in tokenize(wave_text):
        if not quoted and token in ('(', ')'):
            body += token
        elif not quoted and token in CODES:
            body += '!' + CODES[token]
        else:
            body += ('Q' if quoted else 'A') + str(len(token.encode())) + ':' + token
    body += '\n'
    commit = 'sha256:' + hashlib.sha256(('omni.onme-envelope/' + version + '\n' + exec_root + '\n' + author_root + '\n' + body).encode()).hexdigest()
    return ('ONME' + version + '\nR' + exec_root + '\nP' + author_root + '\nC' + commit + '\n' + body).encode()


class Case(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='omni-cp16-')
        self.dir = pathlib.Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def roots(self):
        """The roots a real ONME of a valid program carries; they are only labels for the forged files."""
        g = self.dir / 'roots.omni'
        g.write_text(GENERIC)
        real = self.dir / 'roots.onme'
        if not real.exists():
            self.assertEqual(run(OMNI, 'onme', g, '-o', real).returncode, 0)
        lines = real.read_bytes().split(b'\n')
        return lines[1][1:].decode(), lines[2][1:].decode(), real

    def artifacts(self, source: str, tag: str):
        exec_root, author_root, _ = self.roots()
        files = {}
        files['particle'] = self.dir / (tag + '.omni'); files['particle'].write_text(source)
        files['wave22'] = self.dir / (tag + '.owave'); files['wave22'].write_bytes(capsule_wave(source))
        files['wire22'] = self.dir / (tag + '.owire'); files['wire22'].write_bytes(capsule_wire(source))
        files['onme'] = self.dir / (tag + '.onme'); files['onme'].write_bytes(onme_file(capsule_wave(source).decode(), exec_root, author_root))
        return files


class OneCheckerTests(Case):
    def test_decoded_representation_locations_are_not_reported_as_original_source_spans(self):
        for kind, path in self.artifacts(BAD['E_TYPE'], 'synthetic-span').items():
            with self.subTest(representation=kind):
                done = run(OMNI, 'check', path, '--diagnostic-format', 'json')
                self.assertEqual(done.returncode, 2)
                diagnostic = json.loads(done.stderr)
                self.assertEqual(diagnostic['code'], 'E_TYPE')
                if kind == 'particle':
                    self.assertIsNotNone(diagnostic['span'])
                else:
                    self.assertIsNone(diagnostic['span'])

    def test_binding_metadata_cannot_bypass_the_checker(self):
        for expected, source in BAD.items():
            for kind, path in self.artifacts(source, expected.lower()).items():
                with self.subTest(code=expected, representation=kind):
                    done = run(OMNI, 'check', path, '--bindings-json', '--diagnostic-format', 'json')
                    self.assertEqual(done.returncode, 2)
                    self.assertEqual(json.loads(done.stderr)['code'], expected)
                    self.assertEqual(done.stdout, b'')

    def test_the_writer_of_this_test_is_the_writer_of_the_compiler(self):
        # positive control: without it a "refused" below could be the integrity check refusing a badly written file
        g = self.dir / 'g.omni'
        g.write_text(GENERIC)
        exec_root, author_root, real = self.roots()
        version = real.read_bytes()[4:5].decode()
        self.assertEqual(onme_file(run(OMNI, 'wave', g).stdout.decode(), exec_root, author_root, version), real.read_bytes())
        valid = self.dir / 'valid.onme'
        valid.write_bytes(real.read_bytes())
        self.assertEqual(run(OMNI, 'check', valid).returncode, 0)

    def test_the_same_invalid_program_gets_the_same_diagnostic_from_every_representation(self):
        for expected, source in BAD.items():
            files = self.artifacts(source, expected.lower())
            for kind, path in files.items():
                with self.subTest(code=expected, representation=kind):
                    done = run(OMNI, 'check', path)
                    self.assertEqual(done.returncode, 2, done.stderr[-200:])
                    self.assertEqual(code_of(done), expected, done.stderr[-200:])

    COMMANDS = (('check',), ('manifest',), ('memory',), ('graph',), ('hash',), ('inspect',), ('eval',), ('wave',), ('onme-stats',), ('pack', '-o'), ('onme', '-o'), ('memory-pack', '-o'),
                ('emit-llvm', '-o'), ('build', '-o'), ('run',))

    def test_no_command_computes_publishes_or_writes_anything_for_an_invalid_program(self):
        for expected, source in BAD.items():
            files = self.artifacts(source, expected.lower())
            for kind, path in files.items():
                for index, command in enumerate(self.COMMANDS):
                    with self.subTest(code=expected, representation=kind, command=command[0]):
                        out = self.dir / ('never-%s-%s-%d' % (expected.lower(), kind, index))
                        args = [command[0], path] + ([command[1], out] if len(command) > 1 else [])
                        done = run(OMNI, *args)
                        self.assertEqual(done.returncode, 2, (command, done.stderr[-200:]))
                        self.assertEqual(code_of(done), expected, (command, done.stderr[-200:]))
                        self.assertEqual(done.stdout, b'', command)
                        self.assertFalse(out.exists(), command)
                        self.assertFalse(pathlib.Path(str(out) + '.ometa.json').exists(), command)


class FlagsProfilesCacheAndImportsTests(Case):
    BAD_SOURCE = BAD['E_TYPE']

    def test_an_invalid_host_entry_is_refused_by_the_same_checker(self):
        # Exercise the semantic path with its real loader/toolchain preflight.
        # Reuse only identical source/toolchain inputs and verified retained bytes.
        digest = hashlib.sha256(b'omni.cp16-host-loader/1\n')
        inputs = [p for folder in ('src', 'runtime') for p in sorted((ROOT / folder).glob('*')) if p.is_file()]
        inputs += [ROOT / 'tools/build_invocation_loader.py', ROOT / 'tools/core_sources.txt']
        for path in inputs:
            digest.update(path.relative_to(ROOT).as_posix().encode() + b'\0' + path.read_bytes())
        for variable, default in (('CXX', 'c++'), ('CC', 'clang')):
            compiler = pathlib.Path(shutil.which(os.environ.get(variable, default)) or '/missing-tool').resolve()
            self.assertTrue(compiler.is_file(), str(compiler))
            digest.update(str(compiler).encode() + hashlib.sha256(compiler.read_bytes()).digest())
        installed = pathlib.Path.home() / '.cache' / 'omni-cp16-host-loader' / digest.hexdigest()
        metadata = installed / 'files.json'
        runtime = installed / 'runtime'
        if not metadata.exists():
            runtime.mkdir(parents=True, exist_ok=True)
            built = subprocess.run([sys.executable, str(ROOT / 'tools/build_invocation_loader.py'), '--output',
                                    str(runtime / 'libomni_invocation_v1.so'), '--jobs', '1'], cwd=ROOT,
                                   capture_output=True, timeout=1200, env=ENV)
            self.assertEqual(built.returncode, 0, built.stderr[-2000:])
            files = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in runtime.iterdir() if path.is_file()}
            metadata.write_text(json.dumps(files, sort_keys=True))
        expected = json.loads(metadata.read_text())
        self.assertEqual({path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in runtime.iterdir() if path.is_file()}, expected)
        self.assertEqual(set(expected), {'libomni_invocation_v1.so', 'omni_invocation_build_id.txt', 'omni_invocation_backend_sha256.txt'})
        root = self.dir / 'hostpkg'
        (root / 'src').mkdir(parents=True)
        (root / 'src' / 'main.omni').write_text(self.BAD_SOURCE)
        (root / 'omni.package.json').write_text(json.dumps({'schema': 'omni.package/1', 'name': 'hostbad', 'version': '0.1.0', 'entry': 'src/main.omni'}))
        locked = run(OMNI, 'package', 'lock', root, '--offline')
        self.assertEqual(locked.returncode, 0, locked.stderr)
        output = self.dir / 'never.so'
        done = run(OMNI, 'build', root, '--host-entry', 'src/main.omni:main', '--offline', '-o', output,
                   env={**ENV, 'OMNI_HOME': str(installed)})
        self.assertEqual(done.returncode, 2, done.stderr)
        self.assertEqual(code_of(done), 'E_TYPE', done.stderr)
        self.assertFalse(output.exists())
        self.assertFalse(pathlib.Path(str(output) + '.ometa.json').exists())
        self.assertFalse(pathlib.Path(str(output) + '.omireceipt.json').exists())

    def test_flags_and_diagnostic_formats_do_not_change_what_is_refused(self):
        src = self.dir / 'bad.omni'
        src.write_text(self.BAD_SOURCE)
        for flags in ((), ('--deny-excess-capabilities',), ('--diagnostic-format', 'text'), ('--diagnostic-format', 'json')):
            with self.subTest(flags=flags):
                done = run(OMNI, 'check', src, *flags)
                self.assertEqual(done.returncode, 2, done.stderr[-200:])
                if flags[-1:] == ('json',):
                    diagnostic = json.loads(done.stderr)
                    self.assertEqual((diagnostic['schema'], diagnostic['code']), ('omni.diagnostic/1', 'E_TYPE'))
                else:
                    self.assertEqual(code_of(done), 'E_TYPE')

    def test_a_target_profile_does_not_reach_the_backend_with_an_invalid_program(self):
        src = self.dir / 'bad.omni'
        src.write_text(self.BAD_SOURCE)
        for index, flags in enumerate((('--target-profile', 'baremetal-i386-boot', '--service-module', 't', '--entry-section', '.text.omni_entry', '--entry-address', '1048576'), ())):
            with self.subTest(flags=flags):
                out = self.dir / ('profile-%d.ll' % index)
                done = run(OMNI, 'emit-llvm', src, '-o', out, *flags)
                self.assertEqual(done.returncode, 2, done.stderr[-200:])
                self.assertEqual(code_of(done), 'E_TYPE')
                self.assertFalse(out.exists())

    def test_an_invalid_program_neither_uses_nor_adds_an_entry_of_the_build_cache(self):
        cache = self.dir / 'cache'
        good = self.dir / 'good.omni'
        good.write_text('module t\nfunc main() u32 { return 7u32 }\n')
        built = run(OMNI, 'build', good, '-o', self.dir / 'good-app', '--cache-dir', cache, timeout=300)
        if built.returncode != 0:
            self.skipTest('no native toolchain to build with: %s' % built.stderr[-120:])
        before = sorted(str(p.relative_to(cache)) for p in cache.rglob('*'))
        self.assertTrue(before)
        bad = self.dir / 'bad.omni'
        bad.write_text(self.BAD_SOURCE)
        for command in ('build', 'run'):
            with self.subTest(command=command):
                out = self.dir / 'never-app'
                args = [command, bad] + (['-o', out] if command == 'build' else []) + ['--cache-dir', cache]
                done = run(OMNI, *args)
                self.assertEqual(done.returncode, 2, done.stderr[-200:])
                self.assertEqual(code_of(done), 'E_TYPE')
                self.assertFalse(out.exists())
                self.assertEqual(sorted(str(p.relative_to(cache)) for p in cache.rglob('*')), before)

    def test_an_invalid_module_cannot_be_hidden_behind_an_import(self):
        (self.dir / 'inner.omni').write_text('module inner\npub func f() u32 { let a u32 = 1u32 + "x"\n  return a }\n')
        app = self.dir / 'app.omni'
        app.write_text('module app\nimport inner "inner.omni"\nfunc main() u32 { return inner.f() }\n')
        for args in (('check', app), ('manifest', app), ('wave', app), ('pack', app, '-o', self.dir / 'never.owire'), ('build', app, '-o', self.dir / 'never-app')):
            with self.subTest(command=args[0]):
                done = run(OMNI, *args)
                self.assertEqual(done.returncode, 2, done.stderr[-200:])
                self.assertEqual(code_of(done), 'E_TYPE')
                self.assertIn(b'inner.omni', done.stderr)                  # the refusal names the module that is wrong
                self.assertEqual(done.stdout, b'')
        self.assertFalse((self.dir / 'never.owire').exists())
        self.assertFalse((self.dir / 'never-app').exists())

    def test_a_package_is_resolved_not_checked_and_its_invalid_entry_is_still_refused_by_the_checker(self):
        # `package lock/check` are a resolver (names, versions, digests: schema omni.package-resolution/1): they make no claim about the validity of the program and publish none.
        # The entry of the package is a program like any other: the checker refuses it when it is checked or built, and nothing is written.
        root = self.dir / 'pkg'
        (root / 'src').mkdir(parents=True)
        entry = root / 'src' / 'main.omni'
        entry.write_text(self.BAD_SOURCE)
        (root / 'omni.package.json').write_text(json.dumps({'schema': 'omni.package/1', 'name': 'bad', 'version': '0.1.0', 'entry': 'src/main.omni'}))
        locked = run(OMNI, 'package', 'lock', root, '--offline')
        self.assertEqual(locked.returncode, 0, locked.stderr[-200:])
        self.assertEqual(json.loads(locked.stdout)['schema'], 'omni.package-resolution/1')
        for args in (('check', entry), ('build', entry, '-o', self.dir / 'never-pkg-app'), ('pack', entry, '-o', self.dir / 'never-pkg.owire')):
            with self.subTest(command=args[0]):
                done = run(OMNI, *args)
                self.assertEqual(done.returncode, 2, done.stderr[-200:])
                self.assertEqual(code_of(done), 'E_TYPE')
        self.assertFalse((self.dir / 'never-pkg-app').exists())
        self.assertFalse((self.dir / 'never-pkg.owire').exists())


if __name__ == '__main__':
    unittest.main()
