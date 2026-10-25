#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import os
import pathlib
import subprocess
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
OMNI = pathlib.Path(os.environ.get("OMNI_TEST_BIN", ROOT / "bin/linux-x86_64/omni"))


class A89HardeningTests(unittest.TestCase):
    def test_hardening_git_command_translates_windows_linked_worktree_for_wsl(self) -> None:
        spec = importlib.util.spec_from_file_location("a89_hardening", ROOT / "tools" / "a89_hardening.py")
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader if spec else None)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory(prefix="omni-a89-gitdir-") as raw:
            repo = pathlib.Path(raw)
            (repo / ".git").write_text(
                "gitdir: C:\\work\\fixture\\.git\\worktrees\\linked\n", encoding="utf-8"
            )
            command = module.git_command(repo, "rev-parse", "HEAD")
            if os.name == "nt":
                self.assertIn("--git-dir=C:/work/fixture/.git/worktrees/linked", command)
            else:
                self.assertIn("--git-dir=/mnt/c/work/fixture/.git/worktrees/linked", command)
            self.assertIn(f"--work-tree={repo}", command)

    def test_bounded_hardening_report_is_honest_and_complete(self) -> None:
        with tempfile.TemporaryDirectory(prefix="omni-a89-test-") as raw:
            report_path = pathlib.Path(raw) / "report.json"
            result = subprocess.run(
                ["python3", "-B", str(ROOT / "tools" / "a89_hardening.py"),
                 "--compiler", str(OMNI), "--report", str(report_path),
                 "--duration-seconds", "0.25"],
                cwd=ROOT, text=True, capture_output=True, timeout=60,
                env={**os.environ, "OMNI_HOME": str(ROOT)},
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            report = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertEqual(report["schema"], "omni.release-hardening/1")
            self.assertEqual(report["status"], "PASS")
            self.assertEqual(report["language_version"], (ROOT / "VERSION").read_text(encoding="utf-8").strip())
            self.assertEqual(report["target_probe"]["target_id"], "linux-x86_64-gnu")
            self.assertEqual(len(report["corpus"]["cases"]), 6)
            self.assertGreaterEqual(report["stress"]["observed_seconds"], 0.25)
            self.assertTrue(report["stress"]["cache_repair"])
            self.assertEqual(report["stress"]["evaluator_native"], "PASS")
            self.assertIn("not-prolonged-soak", report["stress"]["kind"])
            self.assertEqual(report["remote_ci"]["state"], "NOT_RUN")
            self.assertGreaterEqual(len(report["dependency_inventory"]["translation_units"]), 16)

    def test_future_wire_and_unknown_target_remain_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory(prefix="omni-a89-negative-") as raw:
            wire = pathlib.Path(raw) / "future.owire"
            wire.write_bytes(b"OMCX" + (23).to_bytes(4, "little"))
            future = subprocess.run([str(OMNI), "check", str(wire)], capture_output=True)
            unknown = subprocess.run([str(OMNI), "target", "unknown", "--json"], capture_output=True)
            self.assertEqual(future.returncode, 2)
            self.assertIn(b"E_VERSION", future.stderr)
            self.assertEqual(unknown.returncode, 2)
            self.assertIn(b"E_CLI", unknown.stderr)


if __name__ == "__main__":
    unittest.main()
