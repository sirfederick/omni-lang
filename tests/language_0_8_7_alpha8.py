#!/usr/bin/env python3
from __future__ import annotations

import json
import hashlib
import os
import pathlib
import subprocess
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
OMNI = pathlib.Path(os.environ.get("OMNI_TEST_BIN", ROOT / "bin/linux-x86_64/omni"))


def proc(*args: object) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        [str(arg) for arg in args],
        capture_output=True,
        timeout=20,
        env={**os.environ, "OMNI_HOME": str(ROOT)},
    )


def frame(message: dict[str, object]) -> bytes:
    body = json.dumps(message, separators=(",", ":")).encode("utf-8")
    return f"Content-Length: {len(body)}\r\n\r\n".encode("ascii") + body


def frames(data: bytes) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    while data:
        header, data = data.split(b"\r\n\r\n", 1)
        length_line = next(line for line in header.split(b"\r\n")
                           if line.lower().startswith(b"content-length:"))
        length = int(length_line.split(b":", 1)[1].strip())
        body, data = data[:length], data[length:]
        result.append(json.loads(body))
    return result


class A87DiagnosticsFormatterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="omni-a87-")
        self.dir = pathlib.Path(self.tmp.name)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def source(self, text: str, name: str = "program.omni") -> pathlib.Path:
        path = self.dir / name
        path.write_text(text, encoding="utf-8", newline="")
        return path

    def test_machine_diagnostic_matches_text_code_and_span(self) -> None:
        source = self.source("module broken\nfunc main() u32 {\n  return missing;\n}\n")
        machine = proc(OMNI, "check", source, "--diagnostic-format", "json")
        text = proc(OMNI, "check", source)
        self.assertEqual(machine.returncode, 2)
        self.assertEqual(text.returncode, 2)
        diagnostic = json.loads(machine.stderr)
        self.assertEqual(diagnostic["schema"], "omni.diagnostic/1")
        self.assertEqual(diagnostic["code"], "E_UNDEFINED")
        self.assertEqual(diagnostic["span"]["line"], 3)
        self.assertGreater(diagnostic["span"]["column"], 0)
        self.assertEqual(diagnostic["span"]["coordinate"], "unicode-scalar-1-based")
        self.assertTrue(diagnostic["source_uri"].startswith("file:///"))
        rendered = text.stderr.decode("utf-8")
        self.assertIn("E_UNDEFINED", rendered)
        self.assertIn(":3:", rendered)

    def test_diagnostic_without_location_uses_null_span(self) -> None:
        source = self.source("module ok\nfunc main() u32 { return 0; }\n")
        result = proc(OMNI, "check", source, "--deny-excess-capabilities",
                      "--diagnostic-format", "json", "--unknown")
        self.assertEqual(result.returncode, 2)
        diagnostic = json.loads(result.stderr)
        self.assertEqual(diagnostic["code"], "E_CLI")
        self.assertIsNone(diagnostic["span"])

    def test_formatter_is_idempotent_and_semantics_preserving(self) -> None:
        source = self.source("module   t\nfunc main() u32 {return 7u32;}\n")
        first = proc(OMNI, "fmt", source)
        self.assertEqual(first.returncode, 0, first.stderr)
        formatted = self.source(first.stdout.decode("utf-8"), "formatted.omni")
        second = proc(OMNI, "fmt", formatted)
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertEqual(second.stdout, first.stdout)
        original_result = proc(OMNI, "eval", source)
        formatted_result = proc(OMNI, "eval", formatted)
        self.assertEqual(original_result.returncode, formatted_result.returncode)
        self.assertEqual(original_result.stdout, formatted_result.stdout)

    def test_check_and_atomic_write_contract(self) -> None:
        source = self.source("module   t\nfunc main() u32 {return 0;}\n")
        dirty = proc(OMNI, "fmt", source, "--check")
        self.assertEqual(dirty.returncode, 2)
        self.assertIn(b"E_FORMAT", dirty.stderr)
        written = proc(OMNI, "fmt", source, "--write")
        self.assertEqual(written.returncode, 0, written.stderr)
        clean = proc(OMNI, "fmt", source, "--check")
        self.assertEqual(clean.returncode, 0, clean.stderr)
        self.assertEqual(source.read_bytes(), proc(OMNI, "fmt", source).stdout)

    def test_parse_failure_never_mutates_source(self) -> None:
        source = self.source("module broken\nfunc main(\n")
        before = source.read_bytes()
        result = proc(OMNI, "fmt", source, "--write")
        self.assertEqual(result.returncode, 2)
        self.assertEqual(source.read_bytes(), before)

    def test_symlink_write_fails_closed(self) -> None:
        target = self.source("module t\nfunc main() u32 { return 0; }\n", "target.omni")
        link = self.dir / "link.omni"
        link.symlink_to(target)
        before = target.read_bytes()
        result = proc(OMNI, "fmt", link, "--write")
        self.assertEqual(result.returncode, 2)
        self.assertIn(b"E_FILE", result.stderr)
        self.assertEqual(target.read_bytes(), before)

    def test_bounded_lsp_lifecycle_navigation_and_rename(self) -> None:
        source = self.source("""module t

func helper(value u32) u32 !pure {
    return value;
}

func main() u32 !pure {
    return helper(7);
}
""")
        uri = source.resolve().as_uri()
        messages = [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            {"jsonrpc": "2.0", "method": "initialized", "params": {}},
            {"jsonrpc": "2.0", "method": "textDocument/didOpen", "params": {
                "textDocument": {"uri": uri, "languageId": "omni", "version": 1,
                                 "text": source.read_text(encoding="utf-8")}}},
            {"jsonrpc": "2.0", "id": 2, "method": "textDocument/completion", "params": {
                "textDocument": {"uri": uri}, "position": {"line": 7, "character": 12}}},
            {"jsonrpc": "2.0", "id": 3, "method": "textDocument/hover", "params": {
                "textDocument": {"uri": uri}, "position": {"line": 7, "character": 12}}},
            {"jsonrpc": "2.0", "id": 4, "method": "textDocument/definition", "params": {
                "textDocument": {"uri": uri}, "position": {"line": 7, "character": 12}}},
            {"jsonrpc": "2.0", "id": 5, "method": "textDocument/references", "params": {
                "textDocument": {"uri": uri}, "position": {"line": 7, "character": 12}}},
            {"jsonrpc": "2.0", "id": 6, "method": "textDocument/rename", "params": {
                "textDocument": {"uri": uri}, "position": {"line": 7, "character": 12},
                "newName": "renamed"}},
            {"jsonrpc": "2.0", "method": "textDocument/didChange", "params": {
                "textDocument": {"uri": uri, "version": 1},
                "contentChanges": [{"text": source.read_text(encoding="utf-8")}]}},
            {"jsonrpc": "2.0", "id": 7, "method": "shutdown", "params": {}},
            {"jsonrpc": "2.0", "method": "exit", "params": {}},
        ]
        result = subprocess.run(
            [str(OMNI), "lsp", "--workspace", str(self.dir)],
            input=b"".join(frame(item) for item in messages), capture_output=True,
            timeout=20, env={**os.environ, "OMNI_HOME": str(ROOT)},
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        output = frames(result.stdout)
        by_id = {item["id"]: item for item in output if "id" in item}
        self.assertEqual(by_id[1]["result"]["capabilities"]["positionEncoding"], "utf-16")
        self.assertTrue(any(item["label"] == "helper" for item in by_id[2]["result"]["items"]))
        self.assertIn("Omni symbol", by_id[3]["result"]["contents"]["value"])
        self.assertEqual(len(by_id[4]["result"]), 1)
        self.assertGreaterEqual(len(by_id[5]["result"]), 2)
        edits = by_id[6]["result"]["documentChanges"]
        self.assertEqual(edits[0]["textDocument"], {"uri": uri, "version": 1})
        self.assertGreaterEqual(len(edits[0]["edits"]), 2)
        published = [item for item in output if item.get("method") == "textDocument/publishDiagnostics"]
        self.assertEqual(published[0]["params"]["diagnostics"], [])
        logs = [item for item in output if item.get("method") == "window/logMessage"]
        self.assertTrue(any("stale document version" in item["params"]["message"] for item in logs))

    def test_lsp_rejects_oversized_frame(self) -> None:
        result = subprocess.run(
            [str(OMNI), "lsp", "--workspace", str(self.dir)],
            input=b"Content-Length: 1048577\r\n\r\n", capture_output=True,
            timeout=20, env={**os.environ, "OMNI_HOME": str(ROOT)},
        )
        self.assertEqual(result.returncode, 2)

    def test_build_receipt_cache_equivalence_and_causal_invalidation(self) -> None:
        dependency = self.source(
            "module dep\npub func value() u32 !pure { return 1; }\n", "dep.omni")
        source = self.source(
            "module app\nimport dep \"dep.omni\"\n"
            "func main() u32 !pure { return dep.value(); }\n")
        cache = self.dir / "cache"

        def build(name: str, *extra: str) -> tuple[pathlib.Path, dict[str, object], bytes]:
            output = self.dir / name
            result = proc(OMNI, "build", source, "-o", output, "--cache-dir", cache, *extra)
            self.assertEqual(result.returncode, 0, result.stderr)
            receipt = json.loads(pathlib.Path(str(output) + ".ometa.json").read_text(encoding="utf-8"))
            return output, receipt, output.read_bytes()

        first_path, first, first_bytes = build("first")
        source_map = json.loads(pathlib.Path(str(first_path) + ".omap.json").read_text(encoding="utf-8"))
        self.assertEqual(source_map["schema"], "omni.source-map/1")
        self.assertEqual(source_map["artifact_sha256"], hashlib.sha256(first_bytes).hexdigest())
        self.assertTrue(any(region["name"] == "main" for region in source_map["regions"]))
        _, second, second_bytes = build("second")
        self.assertFalse(first["cache_hit"])
        self.assertTrue(second["cache_hit"])
        self.assertEqual(first["build_key"], second["build_key"])
        self.assertEqual(first_bytes, second_bytes)
        self.assertEqual(first["artifact_sha256"], hashlib.sha256(first_bytes).hexdigest())
        self.assertTrue(all(not pathlib.Path(item["path"]).is_absolute()
                            for item in first["provenance"]["source_files"]))
        self.assertNotIn(str(self.dir), json.dumps(first))

        key = str(second["build_key"]).removeprefix("sha256:")
        cached = cache / "build-v1" / key / "app"
        damaged = bytearray(cached.read_bytes())
        damaged[len(damaged) // 2] ^= 0x01
        cached.write_bytes(damaged)
        _, repaired, repaired_bytes = build("repaired")
        self.assertFalse(repaired["cache_hit"])
        self.assertEqual(repaired_bytes, first_bytes)

        _, optimized, _ = build("optimized", "--opt", "2")
        self.assertFalse(optimized["cache_hit"])
        self.assertNotEqual(optimized["build_key"], first["build_key"])

        dependency.write_text(
            "module dep\npub func value() u32 !pure { return 2; }\n",
            encoding="utf-8", newline="")
        _, changed, changed_bytes = build("changed")
        self.assertFalse(changed["cache_hit"])
        self.assertNotEqual(changed["build_key"], first["build_key"])
        self.assertNotEqual(changed_bytes, first_bytes)
        self.assertTrue(first_path.is_file())

    def test_native_profile_and_function_coverage_are_artifact_bound_and_redacted(self) -> None:
        source = self.source("""module observed
func helper(value u32) u32 !pure { return value; }
func main() u32 !io {
    print("TOP_SECRET_PAYLOAD");
    return helper(7);
}
""")
        profile_result = proc(OMNI, "profile", source)
        self.assertEqual(profile_result.returncode, 0, profile_result.stderr)
        self.assertNotIn(b"TOP_SECRET_PAYLOAD", profile_result.stdout)
        profile = json.loads(profile_result.stdout)
        self.assertEqual(profile["schema"], "omni.native-profile/1")
        self.assertEqual(profile["exit_code"], 7)
        self.assertGreater(profile["captured_output_bytes"], 0)
        self.assertFalse(profile["payload_recorded"])
        self.assertEqual(len(profile["artifact_sha256"]), 64)
        self.assertGreater(profile["wall_nanoseconds"], 0)

        coverage_result = proc(OMNI, "coverage", source)
        self.assertEqual(coverage_result.returncode, 0, coverage_result.stderr)
        self.assertNotIn(b"TOP_SECRET_PAYLOAD", coverage_result.stdout)
        coverage = json.loads(coverage_result.stdout)
        self.assertEqual(coverage["schema"], "omni.native-coverage/1")
        self.assertEqual(coverage["granularity"], "function-entry")
        self.assertEqual(coverage["visited_regions"], 2)
        self.assertEqual(coverage["total_regions"], 2)
        self.assertEqual({region["name"] for region in coverage["regions"]}, {"helper", "main"})
        self.assertFalse(coverage["payload_recorded"])

    def test_systemic_inspection_reports_roots_edge_classes_and_limits(self) -> None:
        source = self.source("""module inspectable
func helper(value u32) u32 !pure { return value; }
func main() u32 !pure { return helper(3); }
""")
        summary_result = proc(OMNI, "summary", source)
        self.assertEqual(summary_result.returncode, 0, summary_result.stderr)
        summary = json.loads(summary_result.stdout)
        self.assertTrue(summary["epoch"].startswith("sha256:"))
        self.assertTrue(summary["system_root"].startswith("sha256:"))

        query = json.loads(proc(OMNI, "query", source, "--entity", "helper").stdout)
        self.assertEqual(query["system_root"], summary["system_root"])
        self.assertTrue(query["unknown_edges_conservative"])
        self.assertTrue(all(edge["edge_class"] in {"static", "observed", "inferred", "unknown"}
                            for edge in query["edges"]))

        trace = json.loads(proc(OMNI, "trace", source, "--entity", "helper", "--depth", "2").stdout)
        self.assertEqual(trace["epoch"], summary["epoch"])
        self.assertEqual(trace["limits"]["requested_depth"], 2)
        self.assertEqual(trace["limits"]["max_depth"], 16)
        self.assertIn("truncated", trace["limits"])
        self.assertTrue(all("edge_class" in edge for edge in trace["edges"]))

        impact = json.loads(proc(OMNI, "impact", source, "--entity", "helper").stdout)
        self.assertEqual(impact["system_root"], summary["system_root"])
        self.assertTrue(impact["unknown_edges_conservative"])
        self.assertIn("unknown_edge_count", impact)

        store = self.dir / "snapshot.omem"
        packed = proc(OMNI, "memory-pack", source, "-o", store)
        self.assertEqual(packed.returncode, 0, packed.stderr)
        persisted_query = json.loads(proc(OMNI, "memory-query", store, "--entity", "helper").stdout)
        persisted_trace = json.loads(proc(OMNI, "memory-trace", store, "--entity", "helper",
                                          "--depth", "2").stdout)
        persisted_impact = json.loads(proc(OMNI, "memory-impact", store, "--entity", "helper").stdout)
        for report in (persisted_query, persisted_trace, persisted_impact):
            self.assertEqual(report["epoch"], summary["epoch"])
            self.assertEqual(report["system_root"], summary["system_root"])
            self.assertTrue(report["unknown_edges_conservative"])

    def test_doctor_json_is_actionable_and_path_redacted(self) -> None:
        result = proc(OMNI, "doctor", "--json")
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["schema"], "omni.doctor/1")
        self.assertEqual(report["status"], "PASS")
        self.assertEqual(report["runtime"]["status"], "PASS")
        self.assertEqual(report["backend"]["status"], "PASS")
        self.assertEqual(report["python_lsp"]["status"], "PASS")
        self.assertNotIn(str(ROOT), result.stdout.decode("utf-8"))
        self.assertNotIn("HOME", result.stdout.decode("utf-8"))


class A87LspDiagnosticsParityTests(unittest.TestCase):
    """OMNI-CORE-DX-DIAGNOSTIC-FABRIC-001 slice 3: LSP diagnoses the same workspace snapshot as the CLI."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="omni-a87-lsp-")
        self.dir = pathlib.Path(self.tmp.name).resolve()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def write(self, name: str, text: str) -> pathlib.Path:
        path = self.dir / name
        path.write_text(text, encoding="utf-8", newline="")
        return path

    def diagnostics(self, name: str) -> list[dict[str, object]]:
        path = self.dir / name
        uri = path.as_uri()
        messages = [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            {"jsonrpc": "2.0", "method": "initialized", "params": {}},
            {"jsonrpc": "2.0", "method": "textDocument/didOpen", "params": {
                "textDocument": {"uri": uri, "languageId": "omni", "version": 1,
                                 "text": path.read_text(encoding="utf-8")}}},
            {"jsonrpc": "2.0", "id": 2, "method": "shutdown", "params": {}},
            {"jsonrpc": "2.0", "method": "exit", "params": {}},
        ]
        result = subprocess.run(
            [str(OMNI), "lsp", "--workspace", str(self.dir)],
            input=b"".join(frame(item) for item in messages), capture_output=True,
            timeout=30, env={**os.environ, "OMNI_HOME": str(ROOT)},
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        published = [item for item in frames(result.stdout)
                     if item.get("method") == "textDocument/publishDiagnostics"]
        self.assertEqual(len(published), 1)
        return published[0]["params"]["diagnostics"]  # type: ignore[index,return-value]

    def test_valid_relative_import_is_not_reported(self) -> None:
        self.write("lib.omni", "module lib\npub func one() u32 !pure { return 1u32 }\n")
        app = self.write("app.omni", 'module app\nimport l "lib.omni"\nfunc main() u32 !pure { return l.one() }\n')
        self.assertEqual(proc(OMNI, "check", app).returncode, 0)
        self.assertEqual(self.diagnostics("app.omni"), [])

    def test_error_in_an_imported_file_is_not_given_the_importers_span(self) -> None:
        self.write("lib.omni", "module lib\npub func one() u32 !pure { return true }\n")
        self.write("app.omni", 'module app\nimport l "lib.omni"\nfunc main() u32 !pure { return l.one() }\n')
        found = self.diagnostics("app.omni")
        self.assertEqual([item["code"] for item in found], ["E_TYPE"])
        self.assertTrue(str(found[0]["message"]).startswith("lib.omni: "))
        self.assertEqual(found[0]["range"]["start"], {"line": 0, "character": 0})  # type: ignore[index]

    def test_related_locations_become_related_information(self) -> None:
        body = ("module t\nfunc main() u32 !{memory.read,memory.write} {\n  let first Result<Resource<Buffer>,u32> = buffer.alloc(2u32)\n"
                "  match first {\n    Ok(buf) {\n      let reader = borrow(buf)\n      let r = buffer.release(move(buf))\n"
                "      return buffer.len(reader) + r\n    }\n    Err(code) { return code }\n  }\n}\n")
        self.write("conflict.omni", body)
        found = self.diagnostics("conflict.omni")
        self.assertEqual([item["code"] for item in found], ["E_BORROW_CONFLICT"])
        info = found[0]["relatedInformation"]
        self.assertEqual(len(info), 1)
        self.assertEqual(info[0]["location"]["uri"], (self.dir / "conflict.omni").as_uri())
        self.assertIn("prestamo", info[0]["message"])
        self.assertEqual(info[0]["location"]["range"]["start"]["line"], body.split("\n").index("      let reader = borrow(buf)"))
        plain = self.write("plain.omni", "module p\nfunc main() u32 { return true }\n")
        self.assertNotIn("relatedInformation", self.diagnostics("plain.omni")[0])

    def test_range_start_uses_utf16_code_units_for_astral_characters(self) -> None:
        text = 'module u\nfunc main() u32 {\n  let s = "\U0001F600\U0001F600" let x u32 = true\n  return 0u32 }\n'
        path = self.write("uni.omni", text)
        machine = json.loads(proc(OMNI, "check", path, "--diagnostic-format", "json").stderr)
        self.assertEqual(machine["span"]["coordinate"], "unicode-scalar-1-based")
        line = text.split("\n")[machine["span"]["line"] - 1]
        expected = len(line[:machine["span"]["column"] - 1].encode("utf-16-le")) // 2
        self.assertNotEqual(expected, machine["span"]["column"] - 1)
        found = self.diagnostics("uni.omni")
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["code"], machine["code"])
        self.assertEqual(found[0]["range"]["start"],  # type: ignore[index]
                         {"line": machine["span"]["line"] - 1, "character": expected})


if __name__ == "__main__":
    unittest.main()
