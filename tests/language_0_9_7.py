#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
OMNI = pathlib.Path(os.environ.get("OMNI_TEST_BIN", ROOT / "bin/linux-x86_64/omni"))
MATRIX = ROOT / "tests/corpus/a97/operations_maintenance_matrix.json"


class A97OperationsMaintenanceTests(unittest.TestCase):
    def test_causal_operational_matrix(self) -> None:
        matrix = json.loads(MATRIX.read_text(encoding="utf-8"))
        self.assertEqual(matrix["hard_max_seconds"], 1200)
        self.assertEqual([row["id"] for row in matrix["scenarios"]], [f"A97-O{i:02d}" for i in range(1, 8)])
        self.assertTrue(all(row.get("layer") and row.get("boundary") and row.get("oracle") for row in matrix["scenarios"]))
        with tempfile.TemporaryDirectory(prefix="omni-a97-test-") as raw:
            report = pathlib.Path(raw) / "report.json"
            result = subprocess.run([
                sys.executable, "-B", str(ROOT / "tools/a97_operations_maintenance.py"),
                "--compiler", str(OMNI), "--report", str(report),
            ], cwd=ROOT, capture_output=True, timeout=180,
               env={**os.environ, "OMNI_HOME": str(ROOT), "PYTHONDONTWRITEBYTECODE": "1"})
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            data = json.loads(report.read_text(encoding="utf-8"))
            self.assertEqual(data["status"], "PASS")
            self.assertEqual(data["hard_max_seconds"], 1200)
            self.assertLessEqual(data["elapsed_seconds"], data["hard_max_seconds"])
            self.assertEqual(len(data["scenarios"]), 7)
            self.assertIn("not an SLO", data["claim_boundary"])
            self.assertFalse(data["scenarios"][3]["profile_payload_recorded"])
            if evidence := os.environ.get("OMNI_EVIDENCE_DIR"):
                target = pathlib.Path(evidence)
                target.mkdir(parents=True, exist_ok=True)
                (target / "a97_operations_maintenance_report.json").write_bytes(report.read_bytes())

    def test_invalid_report_budget_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory(prefix="omni-a97-budget-") as raw:
            result = subprocess.run([
                sys.executable, "-B", str(ROOT / "tools/a97_operations_maintenance.py"),
                "--compiler", str(OMNI), "--report", str(pathlib.Path(raw) / "report.json"), "--max-report-bytes", "1",
            ], cwd=ROOT, capture_output=True, timeout=30,
               env={**os.environ, "OMNI_HOME": str(ROOT), "PYTHONDONTWRITEBYTECODE": "1"})
            self.assertNotEqual(result.returncode, 0)
            self.assertIn(b"invalid bounded report budget", result.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
