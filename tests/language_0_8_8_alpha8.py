#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import pathlib
import subprocess
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
OMNI = pathlib.Path(os.environ.get("OMNI_TEST_BIN", ROOT / "bin/linux-x86_64/omni"))


def proc(*args: object, timeout: int = 30) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        [str(arg) for arg in args], capture_output=True, timeout=timeout,
        env={**os.environ, "OMNI_HOME": str(ROOT)},
    )


class A88TargetProfileTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="omni-a88-")
        self.directory = pathlib.Path(self.tmp.name)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def source(self, name: str = "program.omni") -> pathlib.Path:
        path = self.directory / name
        path.write_text("module target_test\nfunc main() u32 !pure { return 23u32; }\n",
                        encoding="utf-8", newline="")
        return path

    def test_target_matrix_keeps_supported_and_unexecuted_profiles_visible(self) -> None:
        result = proc(OMNI, "target", "list", "--json")
        self.assertEqual(result.returncode, 0, result.stderr)
        matrix = json.loads(result.stdout)
        self.assertEqual(matrix["schema"], "omni.target-matrix/1")
        self.assertEqual(matrix["language_version"], (ROOT / "VERSION").read_text(encoding="utf-8").strip())
        states = {item["id"]: item["state"] for item in matrix["targets"]}
        self.assertEqual(states["linux-x86_64-gnu"], "SUPPORTED")
        for target in ("windows-x86_64-msvc", "linux-aarch64-gnu", "macos-aarch64"):
            self.assertEqual(states[target], "EXPERIMENTAL_NOT_RUN")
        self.assertNotIn("PASS", set(states.values()))

    def test_target_probe_matches_certified_host_contract(self) -> None:
        result = proc(OMNI, "target", "probe", "--json")
        self.assertEqual(result.returncode, 0, result.stderr)
        probe = json.loads(result.stdout)
        self.assertEqual(probe["schema"], "omni.target-probe/1")
        self.assertEqual(probe["target_id"], "linux-x86_64-gnu")
        self.assertEqual(probe["os"], "linux")
        self.assertEqual(probe["architecture"], "x86_64")
        self.assertEqual(probe["abi"], "gnu")
        self.assertEqual(probe["byte_order"], "little")
        self.assertEqual(probe["pointer_bits"], 64)
        self.assertTrue(probe["supported"])
        self.assertTrue(probe["kernel"])

    def test_target_cli_fails_closed(self) -> None:
        for args in (("target", "unknown", "--json"), ("target", "list"),
                     ("target", "list", "--text")):
            result = proc(OMNI, *args)
            self.assertEqual(result.returncode, 2)
            self.assertIn(b"E_CLI", result.stderr)

    def test_receipt_source_map_profile_and_coverage_bind_target(self) -> None:
        source = self.source()
        output = self.directory / "application"
        build = proc(OMNI, "build", source, "-o", output, "--no-cache")
        self.assertEqual(build.returncode, 0, build.stderr)
        receipt = json.loads(pathlib.Path(str(output) + ".ometa.json").read_text(encoding="utf-8"))
        source_map = json.loads(pathlib.Path(str(output) + ".omap.json").read_text(encoding="utf-8"))
        self.assertEqual(receipt["target_id"], "linux-x86_64-gnu")
        self.assertEqual(receipt["target"], "linux-x86_64-gnu")
        self.assertEqual(source_map["target_id"], "linux-x86_64-gnu")
        profile = json.loads(proc(OMNI, "profile", source).stdout)
        coverage = json.loads(proc(OMNI, "coverage", source).stdout)
        self.assertEqual(profile["target_id"], "linux-x86_64-gnu")
        self.assertEqual(coverage["target_id"], "linux-x86_64-gnu")

    def test_unicode_source_path_preserves_evaluator_native_parity(self) -> None:
        source = self.source("数据-ñ-프로그램.omni")
        evaluated = proc(OMNI, "eval", source)
        native = proc(OMNI, "run", source, "--no-cache")
        self.assertEqual(evaluated.returncode, 23, evaluated.stderr)
        self.assertEqual(native.returncode, 23, native.stderr)
        self.assertEqual(evaluated.stdout, native.stdout)

    def test_executable_permissions_are_explicit(self) -> None:
        source = self.source()
        output = self.directory / "permission-app"
        build = proc(OMNI, "build", source, "-o", output, "--no-cache")
        self.assertEqual(build.returncode, 0, build.stderr)
        self.assertTrue(os.access(output, os.X_OK))
        original = output.stat().st_mode
        output.chmod(original & ~0o111)
        self.assertFalse(os.access(output, os.X_OK))


if __name__ == "__main__":
    unittest.main()
