#!/usr/bin/env python3
"""Not-yet-run C3 acceptance design for already approved AI-07/component outputs."""
from __future__ import annotations
import json
import os
import pathlib
import subprocess
import shutil
import tempfile
import unittest
from language_0_8_3_alpha8 import ROOT, OMNI
from cp07_target import facts as asserted_facts
from cp15_projection import OWNERSHIP, SUPPORT


def run(*args):
    return subprocess.run([str(OMNI), *map(str, args)], capture_output=True,
                          env={**os.environ, 'OMNI_HOME': str(ROOT)}, timeout=90)


class SemanticExports(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='omni-cp17-exports-')
        self.addCleanup(self.temp.cleanup)
        self.directory = pathlib.Path(self.temp.name)

    def source(self, text):
        path = self.directory / 'main.omni'
        path.write_text(text, encoding='utf-8')
        return path

    def ok(self, *args):
        done = run(*args)
        self.assertEqual(done.returncode, 0, done.stderr.decode(errors='replace'))
        return json.loads(done.stdout)

    def test_target_context_uses_the_compiler_facts_that_static_assert_checks(self):
        for target, isa, width, hosted, sse2 in (
                ('linux-x86_64-gnu', None, 64, True, True),
                ('baremetal-x86_64', 'gpr', 64, False, False),
                ('baremetal-x86_64', 'sse2', 64, False, True),
                ('baremetal-i386-boot', None, 32, False, False)):
            with self.subTest(target=target, isa=isa):
                options = ['--target-isa', isa] if isa else []
                context = self.ok('context', '--target', target, '--for', 'llm', *options)
                self.assertEqual(context['schema'], 'omni.target-context/1')
                facts = context['facts']
                self.assertEqual(facts['pointer_width'], width)
                self.assertEqual(facts['hosted'], hosted)
                self.assertEqual('sse2' in facts['features'], sse2)
                self.assertTrue(facts['little_endian'])
                self.assertEqual(context['sdk_version'], '0.1.0.00')
                self.assertFalse(context['grants_authority'])
                self.assertTrue(context['normative_references'])
                self.assertTrue(context['intrinsic_families'])
                arch = 'i386' if width == 32 else 'x86_64'
                other = 'x86_64' if width == 32 else 'i386'
                source = self.source('module t\n' + asserted_facts(width, hosted, arch, other, sse2) +
                                     'func main() u32 { return 42u32 }\n')
                profile = [] if hosted else ['--target-profile', target]
                done = run('component' if profile else 'check', source, *profile, *options)
                self.assertEqual(done.returncode, 0, done.stderr)

    def test_context_does_not_promote_experimental_targets_or_accept_an_unknown_option(self):
        for options in (
                ['--target', 'windows-x86_64-msvc'],
                ['--target', 'linux-aarch64-gnu'],
                ['--target', 'made-up'],
                ['--target', 'baremetal-x86_64', '--target-isa', 'avx2'],
                ['--target', 'baremetal-x86_64', '--grant', 'cpu.control']):
            done = run('context', *options, '--for', 'llm')
            self.assertEqual(done.returncode, 2, (options, done.stderr))
            self.assertEqual(done.stdout, b'')

    def test_component_reuses_the_osnmf_subject_and_function_identity(self):
        source = self.source('module t\nstruct Header { value u32 }\n'
            'pub func identity<T>(x T) T { return x }\n'
            'export "c_add" func plus(x u64, y u64) u64 { return x + y }\n'
            'func main() u32 { return 42u32 }\n')
        component = self.ok('component', source)
        manifest = self.ok('manifest', source)
        memory = self.ok('memory', source)
        self.assertEqual(component['schema'], 'omni.component-contract/1')
        self.assertEqual(component['program_content_id'], manifest['program_content_id'])
        self.assertFalse(component['grants_authority'])
        modules = {module['name']: module for module in component['modules']}
        self.assertEqual(set(modules), {'t'})
        nuclei = {row['name']: row for row in memory['nuclei']
                  if row['kind'] == 'function' and row['module'] == 't'}
        functions = {row['name']: row for row in modules['t']['functions']}
        for name in ('plus', 'main'):
            self.assertEqual(functions[name]['function_id'], nuclei[name]['id'])
            self.assertEqual(functions[name]['contract_id'], nuclei[name]['contract_id'])
        self.assertEqual(functions['plus']['linkage']['export_name'], 'c_add')
        self.assertEqual(functions['plus']['abi']['calling_convention'], 'sysv-x86_64-integer-v1')
        for extension, command in (('owave', 'wave'), ('owire', 'pack'), ('onme', 'onme')):
            path = self.directory / ('program.' + extension)
            if command == 'wave':
                done = run(command, source)
                self.assertEqual(done.returncode, 0, done.stderr)
                path.write_bytes(done.stdout)
            else:
                done = run(command, source, '-o', path)
                self.assertEqual(done.returncode, 0, done.stderr)
            self.assertEqual(self.ok('component', path), component, extension)

    def test_component_refuses_invalid_input_before_emitting_metadata(self):
        source = self.source('module t\nfunc main() u32 { return missing() }\n')
        checked = run('check', source, '--diagnostic-format', 'json')
        described = run('component', source, '--diagnostic-format', 'json')
        self.assertEqual(checked.returncode, 2, checked.stderr)
        self.assertEqual(described.returncode, 2, described.stderr)
        self.assertEqual(described.stdout, b'')
        self.assertEqual(json.loads(described.stderr)['code'], json.loads(checked.stderr)['code'])
        self.assertEqual(list(self.directory.iterdir()), [source])

    def test_the_existing_ownership_fixtures_keep_their_subject_and_descriptor_in_all_forms(self):
        for name, text in OWNERSHIP.items():
            with self.subTest(fixture=name):
                folder = self.directory / name
                folder.mkdir()
                for support in SUPPORT.get(name, []):
                    shutil.copyfile(ROOT / 'examples/storage' / support, folder / support)
                source = folder / 'main.omni'
                source.write_text(text)
                reference = self.ok('component', source)
                memory = self.ok('memory', source)
                known = {row['id']: row for row in memory['nuclei']}
                for module in reference['modules']:
                    self.assertIn(module['id'], known)
                    for function in module['functions']:
                        self.assertEqual(function['contract_id'], known[function['function_id']]['contract_id'])
                        self.assertEqual(function['granted_capabilities'], [])
                for extension, command in (('owave', 'wave'), ('owire', 'pack'), ('onme', 'onme')):
                    artifact = folder / ('program.' + extension)
                    if command == 'wave':
                        done = run(command, source)
                        self.assertEqual(done.returncode, 0, done.stderr)
                        artifact.write_bytes(done.stdout)
                    else:
                        done = run(command, source, '-o', artifact)
                        self.assertEqual(done.returncode, 0, done.stderr)
                    self.assertEqual(self.ok('component', artifact), reference, (name, extension))

    def test_context_transports_the_actual_normative_bytes_without_granting_capabilities(self):
        import hashlib
        context = self.ok('context', '--target', 'baremetal-x86_64', '--for', 'llm')
        self.assertEqual(context['capability_registry'], self.ok('capability', 'registry'))
        self.assertEqual(context['granted_capabilities'], [])
        for contract in context['normative_references']:
            content = (ROOT / contract['path']).read_bytes()
            self.assertEqual(contract['content'].encode('utf-8'), content)
            self.assertEqual(contract['sha256'], hashlib.sha256(content).hexdigest())

    def test_installed_context_refuses_a_contract_that_drifted_from_its_inventory(self):
        import hashlib
        context = self.ok('context', '--target', 'linux-x86_64-gnu', '--for', 'llm')
        sdk = self.directory / 'sdk'
        (sdk / 'metadata').mkdir(parents=True)
        components = []
        for contract in context['normative_references']:
            path = sdk / contract['path']
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(contract['content'].encode('utf-8'))
            components.append({'path': contract['path'], 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()})
        inventory = sdk / 'metadata/omni-sdk.json'
        inventory.write_text(json.dumps({'schema': 'omni.sdk-distribution/1', 'components': components}))
        env = {**os.environ, 'OMNI_HOME': str(sdk)}
        argv = [str(OMNI), 'context', '--target', 'linux-x86_64-gnu', '--for', 'llm']
        positive = subprocess.run(argv, capture_output=True, env=env, timeout=30)
        self.assertEqual(positive.returncode, 0, positive.stderr)
        path = sdk / components[0]['path']
        original = path.read_bytes()
        path.write_bytes(original + b'\nmodified contract\n')
        drifted = subprocess.run(argv, capture_output=True, env=env, timeout=30)
        self.assertEqual(drifted.returncode, 2, drifted.stderr)
        self.assertEqual(drifted.stdout, b'')
        self.assertIn(b'E_PACKAGE_LOCK', drifted.stderr)
        path.write_bytes(original)
        inventory.write_text(json.dumps({'schema': 'omni.sdk-distribution/1', 'components': components[1:]}))
        unindexed = subprocess.run(argv, capture_output=True, env=env, timeout=30)
        self.assertEqual(unindexed.returncode, 2, unindexed.stderr)
        self.assertEqual(unindexed.stdout, b'')
        self.assertIn(b'E_PACKAGE_MANIFEST', unindexed.stderr)
        inventory.write_text(json.dumps({'schema': 'omni.sdk-distribution/1', 'components': components}))
        path.unlink()
        outside = self.directory / 'outside-contract.md'
        outside.write_bytes(original)
        path.symlink_to(outside)
        linked = subprocess.run(argv, capture_output=True, env=env, timeout=30)
        self.assertEqual(linked.returncode, 2, linked.stderr)
        self.assertEqual(linked.stdout, b'')
        self.assertIn(b'E_PACKAGE_PATH', linked.stderr)

    def test_declared_effects_are_not_required_effects_or_runtime_grants(self):
        source = self.source('module t\nfunc unused() u32 !{io.print} { return 1u32 }\n'
                             'func main() u32 { return 42u32 }\n')
        component = self.ok('component', source)
        function, = [row for row in component['modules'][0]['functions'] if row['name'] == 'unused']
        self.assertEqual(function['declared_capabilities'], ['io.print'])
        self.assertEqual(function['required_capabilities'], [])
        self.assertEqual(function['granted_capabilities'], [])

    def test_the_C_symbol_binding_is_part_of_the_distinct_ABI_identity(self):
        identities = []
        for symbol in ('first', 'second'):
            source = self.source('module t\nexport "' + symbol + '" func plus(x u64) u64 { return x }\n'
                                 'func main() u32 { return 42u32 }\n')
            component = self.ok('component', source)
            function, = [row for row in component['modules'][0]['functions'] if row['name'] == 'plus']
            identities.append(function['abi']['abi_id'])
            self.assertNotEqual(function['abi']['abi_id'], function['contract_id'])
        self.assertNotEqual(identities[0], identities[1])

    def test_component_record_layout_matches_the_existing_layout_contract(self):
        source = self.source('module t\nextern struct Header { tag u8, value u64 }\n'
            'static_assert(layout.size<Header>() == 16u64, "size")\n'
            'static_assert(layout.offset<Header>(value) == 8u64, "offset")\n'
            'func main() u32 { return 42u32 }\n')
        component = self.ok('component', source)
        header, = component['modules'][0]['records']
        self.assertEqual(header['native_layout'], {'size_bytes': 16, 'alignment_bytes': 8, 'field_offsets': [0, 8]})


if __name__ == '__main__':
    unittest.main()
