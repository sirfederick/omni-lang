#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import os
import pathlib
import subprocess
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
MATRIX = ROOT / "tests/corpus/a95/interop_profile_matrix.json"


class A95InteropProfileTests(unittest.TestCase):
    observed: dict[str, dict[str, object]] = {}

    @classmethod
    def tearDownClass(cls) -> None:
        matrix = json.loads(MATRIX.read_text(encoding="utf-8"))
        scenarios = [
            {
                **row,
                "status": "PASS" if row["id"] in cls.observed else "NOT_RUN",
                "observed": cls.observed.get(row["id"]),
            }
            for row in matrix["scenarios"]
        ]
        report = {
            "schema": "omni.a95-interop-profile-report/1",
            "version": "0.9.5",
            "seed": matrix["seed"],
            "matrix_sha256": hashlib.sha256(MATRIX.read_bytes()).hexdigest(),
            "status": "PASS" if all(row["status"] == "PASS" for row in scenarios) else "FAIL",
            "scenarios": scenarios,
        }
        if evidence := os.environ.get("OMNI_EVIDENCE_DIR"):
            target = pathlib.Path(evidence) / "a95_interop_profile_report.json"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    def record(self, scenario: str, **details: object) -> None:
        self.observed[scenario] = details

    def run_selector(self, relative: str, selector: str, *, require_no_skip: bool = True) -> None:
        env = {**os.environ, "OMNI_HOME": str(ROOT), "PYTHONDONTWRITEBYTECODE": "1"}
        result = subprocess.run(
            [sys.executable, "-B", str(ROOT / relative), selector, "-v"],
            cwd=ROOT,
            env=env,
            capture_output=True,
            timeout=120,
        )
        output = result.stdout + result.stderr
        self.assertEqual(result.returncode, 0, output.decode("utf-8", errors="replace"))
        if require_no_skip:
            self.assertNotIn(b"skipped", output.lower(), output.decode("utf-8", errors="replace"))

    def test_authority_contract_is_not_source_constructible(self) -> None:
        self.run_selector(
            "tests/language_0_8_6_alpha8.py",
            "A86HostPolicyTests.test_host_authority_is_not_a_source_type",
        )
        self.run_selector(
            "tests/language_0_8_6_alpha8.py",
            "A86HostPolicyTests.test_process_adapter_is_dual_gated_and_evaluator_native_match",
        )
        self.record("A95-I01", result="E_TYPE/E_CAPABILITY")

    def test_real_python_process_boundary(self) -> None:
        self.run_selector(
            "tests/language_0_8_6_alpha8.py",
            "A86HostPolicyTests.test_process_adapter_is_dual_gated_and_evaluator_native_match",
        )
        self.record("A95-I02", runtime="python", boundary="real-process")

    def test_real_node_process_boundary(self) -> None:
        self.run_selector(
            "tests/language_0_8_6_alpha8.py",
            "A86HostPolicyTests.test_node_process_fixture_uses_the_same_provider_neutral_protocol",
        )
        self.record("A95-I03", runtime="node", boundary="real-process")

    def test_real_tcp_boundary(self) -> None:
        self.run_selector(
            "tests/language_0_8_6_alpha8.py",
            "A86HostPolicyTests.test_tcp_exchange_is_local_bounded_and_matches_native",
        )
        self.record("A95-I04", boundary="real-local-tcp", parity="PASS")

    def test_tcp_faults_remain_typed(self) -> None:
        self.run_selector(
            "tests/language_0_8_6_alpha8.py",
            "A86HostPolicyTests.test_tcp_timeout_oversize_mismatch_and_refusal_fail_closed",
        )
        self.record("A95-I05", refusal=4, overflow=5, timeout=10)

    def test_real_copy_ffi_boundary(self) -> None:
        self.run_selector(
            "tests/language_0_8_6_alpha8.py",
            "A86HostPolicyTests.test_fixed_ffi_is_copy_only_dual_gated_and_matches_native",
        )
        self.record("A95-I06", boundary="real-shared-library", abi=1)

    def test_ffi_faults_fail_closed(self) -> None:
        self.run_selector(
            "tests/language_0_8_6_alpha8.py",
            "A86HostPolicyTests.test_fixed_ffi_mismatch_overflow_throw_and_crash_fail_closed",
        )
        self.record("A95-I07", overflow=5, foreign=9, crash=9)

    def test_provider_neutral_loopback_and_outage(self) -> None:
        self.run_selector(
            "tests/language_0_7_alpha7.py",
            "Alpha7LivingSystemTests.test_cognitive_projection_is_read_only",
        )
        self.run_selector(
            "tests/language_0_7_alpha7.py",
            "Alpha7LivingSystemTests.test_cognitive_provider_outage_does_not_stop_runtime",
        )
        self.record("A95-I08", loopback="advisory", external_provider_claim=False)

    def test_unknown_outcome_requires_reconciliation(self) -> None:
        self.run_selector(
            "tests/language_0_9_3.py",
            "A93RuntimeHardeningTests.test_uncertain_outcome_requires_reconciliation_not_automatic_retry",
        )
        self.record("A95-I09", outcome="UNKNOWN_OUTCOME", hidden_retry=False)

    def test_evidence_taxonomy_forbids_false_provider_pass(self) -> None:
        matrix = json.loads(MATRIX.read_text(encoding="utf-8"))
        rows = matrix["scenarios"]
        loopback = next(row for row in rows if row["id"] == "A95-I08")
        self.assertEqual(loopback["evidence_class"], "LOOPBACK_AND_OFFLINE")
        self.assertNotIn("LIVE_PROVIDER", loopback["evidence_class"])
        self.assertFalse(any(
            row["evidence_class"] in {"LOOPBACK_AND_OFFLINE", "MOCK"}
            and "live provider" in row["claim"].lower()
            for row in rows
        ))
        self.record("A95-I10", false_pass_forbidden=True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
