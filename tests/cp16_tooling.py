#!/usr/bin/env python3
"""Discriminating CP-16 snapshot, binding, admission and proposal regressions."""
from __future__ import annotations

import importlib.util
import hashlib
import io
import contextlib
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
from language_0_8_3_alpha8 import ROOT, OMNI

spec = importlib.util.spec_from_file_location("cp16_lsp", ROOT / "tools/omni_lsp.py")
assert spec and spec.loader
lsp = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = lsp
spec.loader.exec_module(lsp)
mutation_spec = importlib.util.spec_from_file_location("cp16_mutation", ROOT / "tools/mutation_harness.py")
assert mutation_spec and mutation_spec.loader
mutation = importlib.util.module_from_spec(mutation_spec)
mutation_spec.loader.exec_module(mutation)


def run(*args):
    return subprocess.run([str(OMNI), *map(str, args)], capture_output=True, timeout=120,
                          env={**os.environ, "OMNI_HOME": str(ROOT)})


class Case(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="omni-cp16-tooling-")
        self.dir = pathlib.Path(self.tmp.name).resolve()
        self.output = io.BytesIO()
        self.server = lsp.Server(OMNI, self.dir, self.output)

    def tearDown(self):
        self.tmp.cleanup()

    def source(self, name, text, opened=True):
        path = self.dir / name
        path.write_text(text, encoding="utf-8")
        if opened:
            doc = lsp.Document(path.as_uri(), path, text, 7)
            self.server.documents[doc.uri] = doc
        return path

    def request(self, method, path, needle, **extra):
        doc = self.server.documents[path.as_uri()]
        start = doc.text.index(needle)
        pos = lsp.location(doc.uri, doc.text, start, start + 1)["range"]["start"]
        self.output.seek(0)
        self.output.truncate()
        self.server.handle({"jsonrpc": "2.0", "id": 1, "method": "textDocument/" + method,
                            "params": {"textDocument": {"uri": doc.uri}, "position": pos, **extra}})
        return json.loads(self.output.getvalue().split(b"\r\n\r\n", 1)[1])


class CheckedBindingsTests(Case):
    def test_a_locked_dependency_is_checked_from_the_real_package_snapshot(self):
        library, application = self.dir / 'lib', self.dir / 'app'
        for root, name in ((library, 'acme.lib'), (application, 'acme.app')):
            (root / 'src').mkdir(parents=True)
            manifest = {'schema': 'omni.package/1', 'name': name, 'version': '1.0.0', 'entry': 'src/main.omni'}
            if root == application:
                manifest['dependencies'] = {'acme.lib': {'path': '../lib', 'version': '1.0.0'}}
            (root / 'omni.package.json').write_text(json.dumps(manifest))
        (library / 'src/main.omni').write_text('module lib\npub func value() u32 { return 7u32 }\n')
        source = self.source('app/src/main.omni', 'module app\nimport lib "@acme.lib/main.omni"\nfunc main() u32 { return lib.value() }\n')
        self.assertEqual(run('package', 'lock', application, '--offline').returncode, 0)
        self.assertEqual(run('check', source).returncode, 0)
        original = {path: path.read_bytes() for path in self.dir.rglob('*.json')}
        self.assertEqual(self.server.diagnostics(self.server.documents[source.as_uri()]), [])
        reply = self.request('definition', source, 'value()')
        self.assertNotIn('error', reply)
        self.assertEqual(reply['result'][0]['uri'], (library / 'src/main.omni').as_uri())
        self.assertEqual({path: path.read_bytes() for path in self.dir.rglob('*.json')}, original)

    def test_metadata_change_during_rename_invalidates_the_snapshot(self):
        path = self.source('race-meta.omni', 'module t\nfunc f(value u32) u32 { return value }\n')
        metadata = self.dir / 'omni.lock.json'
        metadata.write_text('{"sentinel": 0}\n')
        checked = self.server.checked_bindings
        calls = []

        def raced(texts):
            result = checked(texts)
            calls.append(None)
            if len(calls) == 2:
                metadata.write_text('{"sentinel": 1}\n')
            return result

        with mock.patch.object(self.server, 'checked_bindings', side_effect=raced):
            reply = self.request('rename', path, 'value u32', newName='renamed')
        self.assertEqual(len(calls), 2)
        self.assertIn('workspace changed', reply['error']['message'])

    def test_installed_lsp_uses_its_sdk_root_and_sdk_version(self):
        sdk, workspace = self.dir / 'installed', self.dir / 'consumer'
        (sdk / 'bin').mkdir(parents=True)
        (sdk / 'tools').mkdir()
        workspace.mkdir()
        shutil.copy2(OMNI, sdk / 'bin/omni')
        shutil.copy2(ROOT / 'VERSION', sdk / 'VERSION')
        shutil.copy2(ROOT / 'tools/omni_lsp.py', sdk / 'tools/omni_lsp.py')
        std_path = pathlib.Path('packages/stdlib-á')
        std_root = sdk / std_path
        shutil.copytree(ROOT / 'stdlib', std_root)
        std_version = json.loads((std_root / 'omni.package.json').read_text())['version']
        (sdk / 'metadata').mkdir()
        (sdk / 'metadata/omni-sdk.json').write_text(json.dumps({
            'schema': 'omni.sdk-distribution/1', 'version': (ROOT / 'VERSION').read_text().strip(),
            'enterprise_complete': False, 'component_count': 1,
            'components': [{'path': (std_path / 'omni.package.json').as_posix(),
                            'sha256': hashlib.sha256((std_root / 'omni.package.json').read_bytes()).hexdigest()}]}))
        module_spec = importlib.util.spec_from_file_location('cp16_installed_lsp', sdk / 'tools/omni_lsp.py')
        module = importlib.util.module_from_spec(module_spec)
        sys.modules[module_spec.name] = module
        module_spec.loader.exec_module(module)
        output = io.BytesIO()
        server = module.Server(sdk / 'bin/omni', workspace, output)
        server.handle({'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {}})
        reply = json.loads(output.getvalue().split(b'\r\n\r\n', 1)[1])
        self.assertEqual(reply['result']['serverInfo']['version'], (ROOT / 'VERSION').read_text().strip())
        (workspace / 'src').mkdir()
        source = workspace / 'src/main.omni'
        text = ('module t\nimport std "@omni.std/prelude.omni"\n'
                'func main() u32 { let r = std.ok_u32(42u32)\n'
                'match r { Ok(v) { return v } Err(e) { return e } } }\n')
        source.write_text(text)
        (workspace / 'omni.package.json').write_text(json.dumps({
            'schema': 'omni.package/1', 'name': 'consumer.std', 'version': '1.0.0',
            'entry': 'src/main.omni', 'dependencies': {
                'omni.std': {'path': '../development-only-stdlib', 'version': std_version}}}))
        locked = subprocess.run([str(sdk / 'bin/omni'), 'package', 'lock', str(workspace), '--offline'],
                                capture_output=True, timeout=30, env={**os.environ, 'OMNI_HOME': str(sdk)})
        self.assertEqual(locked.returncode, 0, locked.stderr)
        document = module.Document(source.as_uri(), source, text, 1)
        server.documents[document.uri] = document
        invoke = subprocess.run
        with mock.patch.dict(os.environ, {'OMNI_HOME': '/unavailable/development/tree'}):
            with mock.patch.object(module.subprocess, 'run', wraps=invoke) as observed:
                self.assertEqual(server.diagnostics(document), [])
                self.assertEqual(observed.call_args.kwargs['env']['OMNI_HOME'], str(sdk))
        # A new declared local stdlib takes precedence in the real workspace.
        # The snapshot must not silently omit it and fall back to the old SDK.
        shutil.copytree(ROOT / 'stdlib', self.dir / 'development-only-stdlib')
        with self.assertRaises(module.ProtocolError):
            server.diagnostics(document)

    def test_malformed_rpc_objects_return_errors_and_preserve_the_snapshot(self):
        path = self.source("rpc.omni", 'module t\nfunc f() u32 { return 1u32 }\n')
        original = self.server.documents[path.as_uri()].text
        cases = [("rename", {"textDocument": [], "position": {"line": 1, "character": 5}}),
                 ("rename", {"textDocument": {"uri": path.as_uri()}, "position": None}),
                 ("references", {"textDocument": {"uri": path.as_uri()}, "position": {"line": 1, "character": 5}, "context": None})]
        for method, params in cases:
            with self.subTest(method=method, params=params):
                self.output.seek(0)
                self.output.truncate()
                self.assertTrue(self.server.handle({"jsonrpc": "2.0", "id": 1, "method": "textDocument/" + method, "params": params}))
                reply = json.loads(self.output.getvalue().split(b"\r\n\r\n", 1)[1])
                self.assertIn("error", reply)
                self.assertEqual(self.server.documents[path.as_uri()].text, original)

    def test_rename_does_not_capture_a_constant_as_an_existing_local(self):
        path = self.source("capture.omni", 'module t\nconst value u32 = 1u32\nfunc main() u32 { let other = 2u32\n return value + other }\n')
        self.assertEqual(run("check", path).returncode, 0)
        self.assertIn("error", self.request("rename", path, "value u32", newName="other"))

    def test_a_workspace_change_during_analysis_invalidates_the_proposal(self):
        path = self.source("race.omni", 'module t\nfunc f(value u32) u32 { return value }\n')
        original = self.server.checked_bindings
        calls = []

        def checked(texts):
            result = original(texts)
            calls.append(None)
            if len(calls) == 2:
                self.server.documents[path.as_uri()].text += "\n"
            return result

        with mock.patch.object(self.server, "checked_bindings", side_effect=checked):
            self.assertIn("error", self.request("rename", path, "value u32", newName="renamed"))

    def test_missing_compiler_cannot_fall_back_to_spelling(self):
        path = self.source("missing.omni", 'module t\nfunc f() u32 { return 1u32 }\n')
        self.server.compiler = self.dir / "unavailable-compiler"
        self.assertIn("error", self.request("rename", path, "f()", newName="g"))
    def test_homonyms_comments_and_strings_do_not_become_references(self):
        path = self.source("t.omni", 'module t\nfunc first(value u32) u32 { return value }\n'
                           'func other(value u32) u32 { let text = "value"\n // value\n return value }\n')
        result = self.request("rename", path, "value u32", newName="renamed")["result"]
        edits = result["documentChanges"]
        self.assertEqual(len(edits), 1)
        self.assertEqual(edits[0]["textDocument"], {"uri": path.as_uri(), "version": 7})
        self.assertEqual(len(edits[0]["edits"]), 2)
        self.assertEqual({edit["range"]["start"]["line"] for edit in edits[0]["edits"]}, {1})
        self.assertIn('first(value u32)', path.read_text())

    def test_local_declaration_and_assignment_use_the_actual_function_binding(self):
        path = self.source("local.omni", 'module t\nfunc first() u32 { var item u32 = 1u32\n item = item + 1u32\n return item }\n'
                           'func other() u32 { let item u32 = 9u32\n return item }\n')
        result = self.request("references", path, "item =")
        self.assertNotIn("error", result)
        self.assertEqual(len(result["result"]), 4)
        self.assertEqual({r["range"]["start"]["line"] for r in result["result"]}, {1, 2, 3})

    def test_imported_function_rename_does_not_touch_a_local_homonym(self):
        lib = self.source("lib.omni", 'module lib\npub func helper() u32 { return 5u32 }\n')
        app = self.source("app.omni", 'module app\nimport l "lib.omni"\n'
                          'func helper() u32 { return 9u32 }\nfunc main() u32 { return l.helper() + helper() }\n')
        reply = self.request("definition", app, "helper() +")
        self.assertEqual(reply["result"][0]["uri"], lib.as_uri())
        result = self.request("rename", app, "helper() +", newName="renamed")["result"]
        changes = {entry["textDocument"]["uri"]: entry["edits"] for entry in result["documentChanges"]}
        self.assertEqual({uri: len(edits) for uri, edits in changes.items()}, {lib.as_uri(): 1, app.as_uri(): 1})

    def test_unsaved_imported_buffer_is_the_checked_snapshot(self):
        lib = self.source("lib.omni", 'module lib\npub func old() u32 { return 5u32 }\n')
        self.server.documents[lib.as_uri()].text = 'module lib\npub func fresh() u32 { return 5u32 }\n'
        app = self.source("app.omni", 'module app\nimport l "lib.omni"\nfunc main() u32 { return l.fresh() }\n')
        reply = self.request("definition", app, "fresh()")
        self.assertEqual(reply["result"][0]["uri"], lib.as_uri())
        self.assertIn("func old", lib.read_text())

    def test_rename_refuses_conflicts_and_reserved_identifiers(self):
        path = self.source("t.omni", 'module t\nfunc f(value u32, other u32) u32 { return value + other }\n')
        for name in ("other", "return", "a.b", "é"):
            with self.subTest(name=name):
                self.assertIn("error", self.request("rename", path, "value u32", newName=name))

    def test_utf16_ranges_follow_astral_text_on_the_same_line(self):
        path = self.source("u.omni", 'module u\nfunc f(value u32) u32 { let s = "😀😀"\n return value }\n')
        # Put an astral string and the reference on one line, as accepted by Particle.
        self.server.documents[path.as_uri()].text = 'module u\nfunc f(value u32) u32 { let s = "😀😀"; return value }\n'
        result = self.request("references", path, "value }")["result"]
        text = self.server.documents[path.as_uri()].text
        expected = lsp.location(path.as_uri(), text, text.index("value }"), text.index("value }") + 5)
        self.assertIn(expected, result)

    def test_incomplete_mapping_and_invalid_workspace_refuse_rename(self):
        path = self.source("generic.omni", 'module t\nfunc id<T>(x T) T { return x }\nfunc main() u32 { return id<u32>(3u32) }\n')
        self.assertIn("error", self.request("rename", path, "main()", newName="start"))
        self.source("bad.omni", 'module bad\nfunc f() u32 { return missing }\n')
        simple = self.source("simple.omni", 'module simple\nfunc f() u32 { return 1u32 }\n')
        self.assertIn("error", self.request("rename", simple, "f()", newName="ok"))

    def test_stale_and_ranged_changes_leave_the_last_snapshot_unchanged(self):
        path = self.source("v.omni", 'module v\nfunc f() u32 { return 1u32 }\n')
        doc = self.server.documents[path.as_uri()]
        original = doc.text
        for version, change in ((7, {"text": "bad"}), (8, {"text": "bad", "range": {}})):
            self.server.handle({"jsonrpc": "2.0", "method": "textDocument/didChange", "params": {
                "textDocument": {"uri": doc.uri, "version": version}, "contentChanges": [change]}})
            self.assertEqual((doc.text, doc.version), (original, 7))

    def test_surrogate_interior_and_workspace_truncation_fail_closed(self):
        with self.assertRaises(lsp.ProtocolError):
            lsp.lsp_character_to_index("😀", 1)
        path = self.source("x.omni", 'module x\nfunc f() u32 { return 1u32 }\n')
        original = lsp.MAX_FILES
        try:
            lsp.MAX_FILES = 0
            self.assertIn("error", self.request("rename", path, "f()", newName="g"))
        finally:
            lsp.MAX_FILES = original


class AdmissionAndFixitTests(Case):
    def test_capability_context_identifies_the_declaration_without_granting_authority(self):
        text = 'module t\nfunc main() u32 { print(1u32)\n return 0u32 }\n'
        path = self.source('capability-context.omni', text)
        rejected = run('check', path, '--diagnostic-format', 'json')
        self.assertEqual(rejected.returncode, 2)
        diagnostic = json.loads(rejected.stderr)
        self.assertEqual(diagnostic['code'], 'E_CAPABILITY')
        self.assertEqual(diagnostic['symbol'], 't.main')
        self.assertEqual(diagnostic['required_capability'], 'io.print')
        self.assertEqual(diagnostic['constraint'], 'declared_effect_covers_operation')
        self.assertEqual(diagnostic['required_fix_classes'], ['declare_required_effect_or_remove_operation'])
        self.assertIsNone(diagnostic['owner'])
        self.assertIsNone(diagnostic['place'])
        self.assertIsNone(diagnostic['active_loan'])
        admitted = run('admit', path)
        self.assertEqual(admitted.returncode, 2)
        self.assertEqual(path.read_text(), text)
        valid = self.source('capability-valid.omni', text.replace('main() u32 {', 'main() u32 !{io.print} {'))
        memory = json.loads(run('memory', valid).stdout)
        symbol, = [item for item in memory['nuclei'] if item['kind'] == 'function' and item['name'] == 'main']
        self.assertEqual(diagnostic['symbol_id'], symbol['id'])
        # Measured from the immutable pre-context compiler 7c95bfef (r20).
        self.assertEqual(symbol['id'], 'sha256:951a915e22e5620d82586d7f132d134af0b989548599b9207631c67f3e27a966')

    def test_moved_owner_context_is_the_checked_place_and_keeps_the_original_error(self):
        text = ('module t\nstruct Token { h u64 }\n'
                'func consume(x Resource<Token>) u32 { let value = resource.unseal(move(x))\n return 0u32 }\n'
                'func twice(x Resource<Token>) u32 { let first = consume(move(x))\n return consume(move(x)) }\n'
                'func main() u32 { return 0u32 }\n')
        path = self.source('moved-context.omni', text)
        rejected = run('check', path, '--diagnostic-format', 'json')
        self.assertEqual(rejected.returncode, 2)
        diagnostic = json.loads(rejected.stderr)
        self.assertEqual(diagnostic['code'], 'E_RESOURCE_MOVED')
        self.assertEqual(diagnostic['symbol'], 't.twice')
        self.assertEqual(diagnostic['owner'], 'x')
        self.assertGreaterEqual(diagnostic['place']['root_binding'], 0)
        self.assertEqual(diagnostic['place']['projections'], [])
        self.assertIsNone(diagnostic['active_loan'])
        self.assertEqual(diagnostic['constraint'], 'resource_is_live')
        self.assertEqual(diagnostic['required_fix_classes'], ['use_live_owner'])
        self.assertEqual(diagnostic['related'][0]['role'], 'moved-here')
        valid = self.source('moved-valid.omni', text.replace('return consume(move(x))', 'return first'))
        memory = json.loads(run('memory', valid).stdout)
        symbol, = [item for item in memory['nuclei'] if item['kind'] == 'function' and item['name'] == 'twice']
        self.assertEqual(diagnostic['symbol_id'], symbol['id'])

    def test_related_unicode_coordinates_name_the_real_loan(self):
        text = ('module t\nfunc main() u32 !{memory.read,memory.write} {\n'
                ' let result = buffer.alloc(2u32)\n match result { Ok(buf) {\n'
                ' let text = "😀😀"; let reader = borrow(buf)\n'
                ' let released = buffer.release(move(buf))\n'
                ' return buffer.len(reader) + released\n } Err(code) { return code } }\n}\n')
        path = self.source("unicode-related.omni", text)
        diagnostic = json.loads(run("check", path, "--diagnostic-format", "json").stderr)
        self.assertEqual(diagnostic["code"], "E_BORROW_CONFLICT")
        self.assertEqual(diagnostic['owner'], 'buf')
        self.assertEqual(diagnostic['symbol'], 't.main')
        self.assertEqual(diagnostic['active_loan']['kind'], 'shared')
        self.assertEqual(diagnostic['active_loan']['origin_binding'], diagnostic['place']['root_binding'])
        self.assertNotEqual(diagnostic['active_loan']['binding'], diagnostic['place']['root_binding'])
        self.assertEqual(diagnostic['constraint'], 'no_overlapping_exclusive_loan')
        self.assertEqual(diagnostic['required_fix_classes'], ['end_conflicting_loan_or_change_access'])
        related = diagnostic["related"][0]["span"]
        line = text.splitlines()[related["line"] - 1]
        self.assertEqual(related["column"], line.index("let reader") + 1)

    def test_primary_unicode_coordinates_name_the_real_token(self):
        text = 'module t\nfunc f(value u32) u32 { let s = "😀😀"; return valu }\n'
        path = self.source("unicode-primary.omni", text)
        done = run("check", path, "--diagnostic-format", "json")
        self.assertEqual(done.returncode, 2)
        diagnostic = json.loads(done.stderr)
        line = text.splitlines()[1]
        self.assertEqual(diagnostic["span"]["column"], line.index("valu }") + 1)
        plain = run("check", path).stderr.decode()
        self.assertIn(":2:%d:" % (line.index("valu }") + 1), plain)
        found = self.server.diagnostics(self.server.documents[path.as_uri()])[0]
        start = text.index("valu }")
        self.assertEqual(found["range"]["start"], lsp.location(path.as_uri(), text, start, start + 4)["range"]["start"])

    def test_admission_agrees_with_the_checker_and_does_not_execute(self):
        path = self.source("good.omni", 'module t\nfunc main() u32 !{io.print} { print("MUST_NOT_EXECUTE")\n return 42u32 }\n')
        before = path.read_bytes()
        result = run("admit", path)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), {"schema": "omni.admission/1", "verdict": "YES", "diagnostic": None})
        self.assertNotIn(b"MUST_NOT_EXECUTE", result.stdout)
        self.assertEqual(path.read_bytes(), before)
        for suffix, command in (("owave", "wave"), ("owire", "pack"), ("onme", "onme")):
            artifact = self.dir / ("good." + suffix)
            encoded = run(command, path, *(["-o", artifact] if command != "wave" else []))
            self.assertEqual(encoded.returncode, 0, encoded.stderr)
            if command == "wave":
                artifact.write_bytes(encoded.stdout)
            self.assertEqual(json.loads(run("admit", artifact).stdout)["verdict"], "YES")
        bad = self.source("bad.omni", 'module bad\nfunc main() u32 { return true }\n')
        refused = run("admit", bad)
        checker = run("check", bad, "--diagnostic-format", "json")
        self.assertEqual(refused.returncode, checker.returncode)
        self.assertEqual(json.loads(refused.stdout)["diagnostic"], json.loads(checker.stderr))
        self.assertEqual(json.loads(refused.stdout)["verdict"], "NO")

    def test_a_fixit_is_an_exact_proposal_never_autoapplied(self):
        path = self.source("typo.omni", 'module t\nfunc main() u32 { let value = 7u32\n return valu }\n')
        before = path.read_bytes()
        done = run("check", path, "--diagnostic-format", "json")
        self.assertEqual(done.returncode, 2)
        diagnostic = json.loads(done.stderr)
        self.assertEqual(diagnostic["code"], "E_UNDEFINED")
        fix = diagnostic["fixits"][0]
        self.assertEqual((fix["expected"], fix["replacement"]), ("valu", "value"))
        self.assertEqual(fix["coordinate"], "utf8-byte-1-based")
        self.assertEqual(path.read_bytes(), before)
        lines = before.splitlines(keepends=True)
        offset = sum(map(len, lines[:fix["line"] - 1])) + fix["column"] - 1
        self.assertEqual(before[offset:offset + len(fix["expected"])], b"valu")
        path.write_bytes(before[:offset] + fix["replacement"].encode() + before[offset + len(fix["expected"]):])
        self.assertEqual(run("check", path).returncode, 0)

    def test_ambiguous_spelling_emits_only_the_primary_diagnostic(self):
        path = self.source("ambiguous.omni", 'module t\nfunc main() u32 { let hat = 1u32\n let cat = 2u32\n return bat }\n')
        done = run("check", path, "--diagnostic-format", "json")
        diagnostic = json.loads(done.stderr)
        self.assertEqual(diagnostic["code"], "E_UNDEFINED")
        self.assertNotIn("fixits", diagnostic)

    def test_lsp_quickfix_is_versioned_and_context_cannot_manufacture_an_edit(self):
        path = self.source("typo.omni", 'module t\nfunc f(value u32) u32 { return valu }\n')
        before = path.read_bytes()
        result = self.request("codeAction", path, "valu }", context={"diagnostics": [{"data": {"fixits": [{"newText": "ATTACK"}]}}]})
        self.assertNotIn("error", result)
        self.assertEqual(len(result["result"]), 1)
        edit = result["result"][0]["edit"]["documentChanges"][0]
        self.assertEqual(edit["textDocument"], {"uri": path.as_uri(), "version": 7})
        self.assertEqual(edit["edits"][0]["newText"], "value")
        self.assertEqual(path.read_bytes(), before)

    def test_binding_snapshot_is_observational_and_preserves_program_identity(self):
        path = self.source("identity.omni", 'module t\nfunc f(value u32) u32 { return value }\n')
        before = run("manifest", path)
        indexed = run("check", path, "--bindings-json")
        self.assertEqual(indexed.returncode, 0, indexed.stderr)
        self.assertEqual(json.loads(indexed.stdout)["schema"], "omni.bindings/1")
        self.assertEqual(run("manifest", path).stdout, before.stdout)

    def test_rejection_preserves_an_existing_output_and_receipt(self):
        path = self.source("bad.omni", 'module t\nfunc main() u32 { return true }\n')
        for command in ("build", "pack", "onme", "emit-llvm"):
            with self.subTest(command=command):
                out = self.dir / "existing.bin"
                receipt = self.dir / "existing.bin.ometa.json"
                out.write_bytes(b"PREVIOUS_VALID_ARTIFACT")
                receipt.write_bytes(b"PREVIOUS_RECEIPT")
                done = run(command, path, "-o", out, "--force")
                self.assertEqual(done.returncode, 2)
                self.assertEqual(out.read_bytes(), b"PREVIOUS_VALID_ARTIFACT")
                self.assertEqual(receipt.read_bytes(), b"PREVIOUS_RECEIPT")


class MutationBaselineTests(Case):
    def test_every_unique_test_selection_must_pass_the_unmutated_compiler(self):
        mutants = [{"tests": ["tests/a.py", "A"]}, {"tests": ["tests/a.py", "A"]}, {"tests": ["tests/b.py"]}]
        red = subprocess.CompletedProcess([], 1, "", "FAILED baseline")
        with mock.patch.object(mutation.subprocess, "run", return_value=red) as invoke:
            result = mutation.verify_baseline(self.dir, OMNI, mutants, 10)
        self.assertEqual(result["result"], "FAIL")
        self.assertEqual(invoke.call_count, 2)
        self.assertEqual(len(result["suites"]), 2)

    def test_a_red_baseline_prevents_any_mutant_from_starting(self):
        source = self.dir / "mutants.json"
        source.write_text(json.dumps([{"name": "test mutant", "tests": ["tests/a.py"]}]))
        args = type("Args", (), {"specs": [source], "report": self.dir / "report.json", "parallel": 1,
                                "only": [], "object_cache": self.dir / "cache", "timeout": 10,
                                "baseline_jobs": 1, "mutant_jobs": 1})()
        with mock.patch.object(mutation.argparse.ArgumentParser, "parse_args", return_value=args), \
             mock.patch.object(mutation, "copy_tree"), \
             mock.patch.object(mutation, "build", return_value=(True, "")), \
             mock.patch.object(mutation, "verify_baseline", return_value={"result": "FAIL", "suites": []}), \
             mock.patch.object(mutation, "run_one") as run_mutant, \
             contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(mutation.main(), 2)
        run_mutant.assert_not_called()
        self.assertEqual(json.loads(args.report.with_suffix(".baseline.json").read_text())["result"], "FAIL")
        self.assertFalse(args.report.exists())


if __name__ == "__main__":
    unittest.main()
