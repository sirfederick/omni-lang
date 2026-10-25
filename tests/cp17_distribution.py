#!/usr/bin/env python3
"""Causal distribution regressions. Stub packaging is never installed SDK acceptance."""
from __future__ import annotations
import ast
import contextlib
import hashlib
import importlib.util
import io
import json
import pathlib
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest import mock
from language_0_8_3_alpha8 import ROOT, OMNI


def tool(name):
    spec = importlib.util.spec_from_file_location('cp17_' + name, ROOT / 'tools' / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class LoaderIdentityTests(unittest.TestCase):
    def test_shared_headers_and_the_unit_list_change_the_actual_identity_input_hash(self):
        loader = tool('build_invocation_loader')
        with tempfile.TemporaryDirectory(prefix='omni-loader-inputs-') as temporary:
            root = pathlib.Path(temporary)
            paths = ['compiler/src/a.cpp', 'runtime/a.c', 'compiler/src/omni.hpp', 'compiler/src/sdk_tooling.hpp',
                     'runtime/codec.h', 'include/omni/public.h',
                     'tools/core_sources.txt', 'tools/build_invocation_loader.py']
            for name in paths:
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text('original ' + name)
            with mock.patch.object(loader, 'ROOT', root):
                def identity():
                    value = hashlib.sha256(b'fixture-source-domain\n')
                    loader.hash_identity_inputs(value, loader.identity_inputs([root / paths[0]], [root / paths[1]]))
                    return value.hexdigest()
                original = identity()
                for name in paths[2:]:
                    with self.subTest(name=name):
                        path = root / name
                        before = path.read_bytes()
                        path.write_bytes(before + b' changed')
                        self.assertNotEqual(identity(), original, name)
                        path.write_bytes(before)
                        self.assertEqual(identity(), original)


class ConsumerPackageTests(unittest.TestCase):
    def test_lsp_imports_only_the_python_standard_library(self):
        syntax = ast.parse((ROOT / 'tools/omni_lsp.py').read_text())
        names = set()
        for node in ast.walk(syntax):
            if isinstance(node, ast.Import):
                names.update(alias.name.split('.')[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                self.assertEqual(node.level, 0)
                names.add(node.module.split('.')[0])
        self.assertFalse(names - sys.stdlib_module_names, names - sys.stdlib_module_names)

    def test_candidate_archive_contains_advertised_tools_and_their_verified_bytes(self):
        packager = tool('omni_sdk_package')
        with tempfile.TemporaryDirectory(prefix='omni-cp17-package-') as temporary:
            directory = pathlib.Path(temporary)
            runtime = directory / 'runtime/libomni_invocation_v1.so'
            runtime.parent.mkdir()
            runtime.write_bytes(b'PACKAGING STRUCTURE ONLY; NOT A RUNTIME')
            for name in ('omni_invocation_build_id.txt', 'omni_invocation_backend_sha256.txt'):
                (runtime.parent / name).write_text('0' * 64 + '\n')
            addon = directory / 'addon.node'
            addon.write_bytes(b'PACKAGING STRUCTURE ONLY; NOT AN ADDON')
            provenance = directory / 'provenance.json'
            provenance.write_text(json.dumps({'source_sha': 'a' * 40, 'source_status': 'COMMITTED_CLEAN',
                'compiler_sha256': digest(OMNI), 'runtime_sha256': digest(runtime), 'node_sha256': digest(addon)}))
            output = directory / 'candidate.tar.gz'
            argv = ['omni_sdk_package.py', '--compiler', str(OMNI), '--runtime', str(runtime),
                    '--node', str(addon), '--candidate-source-sha', 'a' * 40,
                    '--provenance', str(provenance), '--output', str(output)]
            with mock.patch.object(sys, 'argv', argv), contextlib.redirect_stdout(io.StringIO()):
                packager.main()
            with tarfile.open(output) as archive:
                members = {member.name.split('/', 1)[1]: member for member in archive.getmembers()}
                inventory = json.load(archive.extractfile(members['metadata/omni-sdk.json']))
                indexed = {row['path']: row['sha256'] for row in inventory['components']}
                for name in ('VERSION', 'tools/omni_lsp.py', 'tools/omni_sdk_doctor.py', 'tools/run_sdk_examples.py',
                             'spec/CORE_1_3_0_0_PUBLIC_DELTA_CANDIDATE.json',
                             'spec/CP17_SDK_INTEGRATION_CANDIDATE.md'):
                    with self.subTest(component=name):
                        content = archive.extractfile(members[name]).read()
                        self.assertEqual(hashlib.sha256(content).hexdigest(), indexed[name])
                        self.assertEqual(content, (ROOT / name).read_bytes())
                for producer in ('tools/build_compiler.py', 'tools/build_sdk_candidate.py', 'compiler/src/main.cpp'):
                    self.assertNotIn(producer, members)

    def test_doctor_refuses_required_assets_present_but_absent_from_the_inventory(self):
        with tempfile.TemporaryDirectory(prefix='omni-cp17-inventory-') as temporary:
            sdk = pathlib.Path(temporary)
            compiler = sdk / 'bin/omni'
            compiler.parent.mkdir()
            shutil.copyfile(OMNI, compiler)
            compiler.chmod(0o755)
            manifest = sdk / 'packages/stdlib/omni.package.json'
            manifest.parent.mkdir(parents=True)
            manifest.write_text(json.dumps({'schema': 'omni.package/1', 'name': 'omni.std', 'version': '9.7.3'}))
            for name in ('runtime/libomni_invocation_v1.so', 'include/omni/omni_host_sdk_v1.h',
                         'lib/libomni_host_sdk_v1.so', 'node/omni_host_sdk.node',
                         'python/omni_host_sdk.py', 'tools/omni_sdk_codegen.py',
                         'tools/omni_lsp.py', 'VERSION', 'spec/CORE_1_3_0_0_PUBLIC_DELTA_CANDIDATE.json'):
                path = sdk / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text('unindexed structural fixture; never executed')
            (sdk / 'metadata').mkdir()
            (sdk / 'metadata/omni-sdk.json').write_text(json.dumps({
                'schema': 'omni.sdk-distribution/1', 'version': '0.1.0.00',
                'components': [{'path': path.relative_to(sdk).as_posix(), 'sha256': digest(path)}
                               for path in (compiler, manifest)]}))
            done = subprocess.run([sys.executable, '-B', str(ROOT / 'tools/omni_sdk_doctor.py'),
                                   '--sdk-root', str(sdk)], capture_output=True, timeout=30)
            self.assertEqual(done.returncode, 1, done.stderr)
            data = json.loads(done.stdout)
            self.assertEqual(data['status'], 'FAIL')
            self.assertIn({'component': 'runtime', 'status': 'FAIL'}, data['checks'])
            self.assertIn({'component': 'lsp', 'status': 'FAIL'}, data['checks'])


if __name__ == '__main__':
    unittest.main()
