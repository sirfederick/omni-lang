#!/usr/bin/env python3
from __future__ import annotations

import os
import json
import pathlib
import subprocess
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
OMNI = pathlib.Path(os.environ.get("OMNI_TEST_BIN", ROOT / "bin/linux-x86_64/omni"))


def proc(*args: object) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        [str(arg) for arg in args], capture_output=True, timeout=30,
        env={**os.environ, "OMNI_HOME": str(ROOT)},
    )


class A92SemanticConformanceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="omni-a92-")
        self.dir = pathlib.Path(self.tmp.name)
        self.input = self.dir / "input"
        self.output = self.dir / "output"
        self.outside = self.dir / "outside"
        self.input.mkdir()
        self.output.mkdir()
        self.outside.mkdir()
        self.policy = self.dir / "policy.ohp"
        self.policy.write_text(
            "OHP1\n"
            "generation|1\n"
            "not_after_tick|1000\n"
            f"grant|fs.read|{self.input.as_posix()}|4096\n"
            f"grant|fs.write|{self.output.as_posix()}|4096\n",
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def source(self, path: pathlib.Path, operation: str = "read", name: str = "program.omni") -> pathlib.Path:
        source = self.dir / name
        if operation == "read":
            body = (
                f'let result = host.read("{path.as_posix()}", 64u32); '
                "match result { Ok(data) { return bytes.len(data); } Err(code) { return code; } }"
            )
            effect = "fs.read"
        elif operation == "read-zero":
            body = (
                f'let result = host.read("{path.as_posix()}", 0u32); '
                "match result { Ok(data) { return bytes.len(data); } Err(code) { return code; } }"
            )
            effect = "fs.read"
        elif operation == "read-over":
            body = (
                f'let result = host.read("{path.as_posix()}", 1048577u32); '
                "match result { Ok(data) { return bytes.len(data); } Err(code) { return code; } }"
            )
            effect = "fs.read"
        elif operation == "legacy-read":
            body = (
                f'let result = file.read_text("{path.as_posix()}"); '
                "match result { Ok(data) { return text.len(data); } Err(code) { return code; } }"
            )
            effect = "fs.read"
        else:
            body = (
                f'let result = host.write("{path.as_posix()}", bytes.from_text("abc")); '
                "match result { Ok(size) { return size; } Err(code) { return code; } }"
            )
            effect = "fs.write"
        source.write_text(
            f"module a92 func main() u32 !{{{effect}}} {{ {body} }}\n", encoding="utf-8"
        )
        return source

    def pair(self, source: pathlib.Path, policy: pathlib.Path | None = None) -> tuple[int, int]:
        eval_args: list[object] = [OMNI, "eval", source]
        if policy is not None:
            eval_args.extend(["--host-policy", policy])
        evaluated = proc(*eval_args)
        self.assertLessEqual(evaluated.returncode, 10, evaluated.stderr)
        native = self.dir / f"{source.stem}-native"
        built = proc(OMNI, "build", source, "-o", native, "--no-cache")
        self.assertEqual(built.returncode, 0, built.stderr)
        native_args: list[object] = [native]
        if policy is not None:
            native_args.extend(["--omni-host-policy", policy])
        executed = proc(*native_args)
        return evaluated.returncode, executed.returncode

    def test_authorized_missing_final_and_intermediate_are_not_found(self) -> None:
        for index, missing in enumerate((self.input / "missing.bin", self.input / "a" / "b" / "missing.bin")):
            with self.subTest(path=missing):
                self.assertEqual(self.pair(self.source(missing, name=f"missing-{index}.omni"), self.policy), (3, 3))

    def test_absent_grant_and_outside_path_are_denied(self) -> None:
        inside = self.source(self.input / "missing.bin", name="no-grant.omni")
        self.assertEqual(self.pair(inside), (1, 1))
        outside = self.source(self.outside / "missing.bin", name="outside.omni")
        self.assertEqual(self.pair(outside, self.policy), (1, 1))

    def test_symlink_parent_escape_is_denied(self) -> None:
        link = self.input / "escaped"
        try:
            link.symlink_to(self.outside, target_is_directory=True)
        except OSError as error:
            self.skipTest(f"symlink unavailable: {error}")
        source = self.source(link / "missing.bin", name="symlink-escape.omni")
        self.assertEqual(self.pair(source, self.policy), (1, 1))

    def test_existing_read_and_absent_write_match(self) -> None:
        payload = self.input / "payload.bin"
        payload.write_bytes(b"omni-a92")
        self.assertEqual(self.pair(self.source(payload, name="existing.omni"), self.policy), (8, 8))

        eval_target = self.output / "eval.bin"
        native_target = self.output / "native.bin"
        eval_source = self.source(eval_target, operation="write", name="write-eval.omni")
        self.assertEqual(proc(OMNI, "eval", eval_source, "--host-policy", self.policy).returncode, 3)
        native_source = self.source(native_target, operation="write", name="write-native.omni")
        native = self.dir / "write-native"
        self.assertEqual(proc(OMNI, "build", native_source, "-o", native, "--no-cache").returncode, 0)
        self.assertEqual(proc(native, "--omni-host-policy", self.policy).returncode, 3)
        self.assertEqual(eval_target.read_bytes(), native_target.read_bytes())

    def test_invalid_bound_precedes_filesystem_effect(self) -> None:
        source = self.source(self.input / "missing.bin", operation="read-zero", name="zero.omni")
        self.assertEqual(self.pair(source, self.policy), (2, 2))

    def test_legacy_read_uses_the_same_missing_path_authority_order(self) -> None:
        source = self.source(self.input / "legacy-missing.txt", operation="legacy-read", name="legacy.omni")
        self.assertEqual(self.pair(source, self.policy), (3, 3))

    def test_representation_versions_remain_wave20_omc20(self) -> None:
        source = self.source(self.input / "missing.bin", name="representation.omni")
        wave = proc(OMNI, "wave", source)
        self.assertEqual(wave.returncode, 0, wave.stderr)
        self.assertTrue(wave.stdout.startswith(b"(omni-wave 20"))
        wire = self.dir / "representation.owire"
        self.assertEqual(proc(OMNI, "pack", source, "-o", wire).returncode, 0)
        self.assertEqual(wire.read_bytes()[:8], b"OMCX\x14\x00\x00\x00")

    def test_machine_readable_golden_error_vectors(self) -> None:
        corpus = json.loads(
            (ROOT / "tests" / "corpus" / "a92" / "host_path_error_vectors.json").read_text(encoding="utf-8")
        )
        self.assertEqual(corpus["schema"], "omni.semantic-conformance-vectors/1")
        payload = self.input / "existing.bin"
        payload.write_bytes(b"golden")
        link = self.input / "golden-escape"
        symlink_available = True
        try:
            link.symlink_to(self.outside, target_is_directory=True)
        except OSError:
            symlink_available = False
        paths = {
            "missing_final": self.input / "golden-missing.bin",
            "missing_intermediate": self.input / "missing" / "middle" / "golden.bin",
            "outside": self.outside / "golden-missing.bin",
            "traversal": self.input / ".." / "outside" / "golden-missing.bin",
            "symlink_escape": link / "golden-missing.bin",
            "existing": payload,
            "legacy_missing": self.input / "legacy-golden-missing.txt",
            "write_missing_parent": self.output / "missing" / "golden.bin",
        }
        for vector in corpus["cases"]:
            if vector["path"] == "symlink_escape" and not symlink_available:
                continue
            with self.subTest(vector=vector["id"]):
                source = self.source(
                    paths[vector["path"]], operation=vector["operation"], name=f"golden-{vector['id']}.omni"
                )
                policy = self.policy if vector["policy"] else None
                expected = int(vector["expected"])
                self.assertEqual(self.pair(source, policy), (expected, expected))


if __name__ == "__main__":
    unittest.main()
