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
MATRIX = ROOT / "tests/corpus/a96/security_supply_chain_matrix.json"


class A96SecuritySupplyChainTests(unittest.TestCase):
    def test_matrix_and_causal_closure_report(self) -> None:
        matrix = json.loads(MATRIX.read_text(encoding="utf-8"))
        self.assertEqual([row["id"] for row in matrix["scenarios"]], [f"A96-S{i:02d}" for i in range(1, 11)])
        self.assertTrue(all(row.get("attack") and row.get("oracle") for row in matrix["scenarios"]))
        with tempfile.TemporaryDirectory(prefix="omni-a96-") as raw:
            directory = pathlib.Path(raw)
            report = directory / "report.json"
            inventory = directory / "inventory.json"
            result = subprocess.run([
                os.environ.get("PYTHON", "python3"), "-B", str(ROOT / "tools/a96_security_supply_chain.py"),
                "--compiler", str(OMNI), "--report", str(report), "--inventory", str(inventory),
            ], cwd=ROOT, capture_output=True, timeout=240,
               env={**os.environ, "OMNI_HOME": str(ROOT)})
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            data = json.loads(report.read_text(encoding="utf-8"))
            sbom = json.loads(inventory.read_text(encoding="utf-8"))
            self.assertEqual(data["status"], "PASS")
            self.assertEqual(len(data["scenarios"]), 10)
            self.assertLessEqual(data["elapsed_seconds"], data["hard_max_seconds"])
            self.assertEqual(sbom["status"], "PASS")
            self.assertEqual(sbom["component_count"], len(sbom["components"]))
            self.assertTrue(all(not pathlib.PurePosixPath(row["path"]).is_absolute() and ".." not in pathlib.PurePosixPath(row["path"]).parts for row in sbom["components"]))
            self.assertIn("not a signed SBOM", sbom["limitations"])
            if evidence := os.environ.get("OMNI_EVIDENCE_DIR"):
                target = pathlib.Path(evidence)
                target.mkdir(parents=True, exist_ok=True)
                (target / "a96_security_supply_chain_report.json").write_bytes(report.read_bytes())
                (target / "a96_component_inventory.json").write_bytes(inventory.read_bytes())


if __name__ == "__main__":
    unittest.main(verbosity=2)
