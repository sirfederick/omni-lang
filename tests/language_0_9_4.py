#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import os
import pathlib
import subprocess
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
OMNI = pathlib.Path(os.environ.get("OMNI_TEST_BIN", ROOT / "bin/linux-x86_64/omni"))
MATRIX = ROOT / "tests/corpus/a94/systemic_durability_matrix.json"


def proc(*args: object, env: dict[str, str] | None = None, timeout: int = 30) -> subprocess.CompletedProcess[bytes]:
    merged = {**os.environ, "OMNI_HOME": str(ROOT), **(env or {})}
    return subprocess.run([str(arg) for arg in args], capture_output=True, env=merged, timeout=timeout)


class A94SystemicDurabilityTests(unittest.TestCase):
    observed: dict[str, dict[str, object]] = {}

    @classmethod
    def tearDownClass(cls) -> None:
        matrix = json.loads(MATRIX.read_text(encoding="utf-8"))
        scenarios = [{**row, "status": "PASS" if row["id"] in cls.observed else "NOT_RUN",
                      "observed": cls.observed.get(row["id"])} for row in matrix["scenarios"]]
        report = {
            "schema": "omni.a94-systemic-durability-report/1",
            "version": "0.9.4",
            "seed": matrix["seed"],
            "matrix_sha256": hashlib.sha256(MATRIX.read_bytes()).hexdigest(),
            "status": "PASS" if all(row["status"] == "PASS" for row in scenarios) else "FAIL",
            "scenarios": scenarios,
        }
        if evidence := os.environ.get("OMNI_EVIDENCE_DIR"):
            target = pathlib.Path(evidence) / "a94_systemic_durability_report.json"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="omni-a94-")
        self.dir = pathlib.Path(self.temp.name)
        self.source = self.dir / "system.omni"
        self.source.write_text(
            "module a94\nstruct Product { id u32 }\n"
            "func helper() u32 { return 7u32 }\nfunc main() u32 { return helper() }\n",
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    def record(self, scenario: str, **details: object) -> None:
        self.observed[scenario] = details

    def pack(self, name: str = "state.omem") -> pathlib.Path:
        store = self.dir / name
        result = proc(OMNI, "memory-pack", self.source, "-o", store)
        self.assertEqual(result.returncode, 0, result.stderr)
        return store

    def query(self, store: pathlib.Path) -> subprocess.CompletedProcess[bytes]:
        return proc(OMNI, "memory-query", store, "--entity", "main")

    def test_commit_binding_and_measured_locality(self) -> None:
        store = self.pack()
        commit = pathlib.Path(str(store) + ".commit")
        self.assertTrue(commit.read_text(encoding="utf-8").startswith("OSMC1\n"))
        result = self.query(store)
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertFalse(data["full_store_hashed"])
        self.assertLess(data["store_bytes_read"], store.stat().st_size)
        self.assertEqual(data["index_bytes_read"], pathlib.Path(str(store) + ".idx").stat().st_size)
        self.assertGreater(data["commit_bytes_read"], 0)
        self.record("A94-D01", commit_schema="OSMC1")
        self.record("A94-D02", store_bytes_read=data["store_bytes_read"], store_bytes=store.stat().st_size)

    def test_legacy_fallback_hashes_full_store(self) -> None:
        store = self.pack("legacy.omem")
        pathlib.Path(str(store) + ".commit").unlink()
        result = self.query(store)
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertTrue(data["full_store_hashed"])
        self.assertEqual(data["store_bytes_read"], store.stat().st_size)
        self.record("A94-D03", full_store_hashed=True)

    def test_index_and_commit_tampering_fail_closed(self) -> None:
        index_store = self.pack("index-tamper.omem")
        index = pathlib.Path(str(index_store) + ".idx")
        changed = bytearray(index.read_bytes()); changed[-3] ^= 1; index.write_bytes(changed)
        bad_index = self.query(index_store)
        self.assertEqual(bad_index.returncode, 2)
        self.assertIn(b"E_OSNMF", bad_index.stderr)
        self.record("A94-D04", diagnostic="E_OSNMF")

        commit_store = self.pack("commit-tamper.omem")
        commit = pathlib.Path(str(commit_store) + ".commit")
        changed = bytearray(commit.read_bytes()); changed[-3] ^= 1; commit.write_bytes(changed)
        bad_commit = self.query(commit_store)
        self.assertEqual(bad_commit.returncode, 2)
        self.assertIn(b"E_DURABILITY", bad_commit.stderr)
        self.record("A94-D05", diagnostic="E_DURABILITY")

    def test_every_publication_phase_recovers_exactly(self) -> None:
        for phase in ("after_transaction", "after_store", "after_index", "after_commit"):
            store = self.dir / f"crash-{phase}.omem"
            crash = proc(OMNI, "memory-pack", self.source, "-o", store,
                         env={"OMNI_TEST_OSNMF_PUBLISH_FAULT": phase})
            self.assertEqual(crash.returncode, 86, (phase, crash.stderr))
            self.assertTrue(pathlib.Path(str(store) + ".txn").exists())
            recovered = self.query(store)
            self.assertEqual(recovered.returncode, 0, (phase, recovered.stderr))
            self.assertFalse(pathlib.Path(str(store) + ".txn").exists())
            self.assertFalse(list(self.dir.glob(store.name + ".omni-publish-*")))
        self.record("A94-D06", injected_phases=4)

    def test_mismatched_transaction_and_symlink_fail_closed(self) -> None:
        store = self.dir / "broken.omem"
        crash = proc(OMNI, "memory-pack", self.source, "-o", store,
                     env={"OMNI_TEST_OSNMF_PUBLISH_FAULT": "after_store"})
        self.assertEqual(crash.returncode, 86)
        staged = list(self.dir.glob(store.name + ".omni-publish-*.index"))
        self.assertEqual(len(staged), 1)
        staged[0].write_bytes(b"not-the-index")
        rejected = self.query(store)
        self.assertEqual(rejected.returncode, 2)
        self.assertIn(b"E_DURABILITY", rejected.stderr)
        self.record("A94-D07", diagnostic="E_DURABILITY")

        linked = self.pack("linked.omem")
        commit = pathlib.Path(str(linked) + ".commit")
        real = self.dir / "saved.commit"; commit.replace(real); commit.symlink_to(real)
        rejected = self.query(linked)
        self.assertEqual(rejected.returncode, 2)
        self.assertIn(b"E_DURABILITY", rejected.stderr)
        self.record("A94-D08", diagnostic="E_DURABILITY")

    def test_pulse_gap_duplicate_and_regression(self) -> None:
        one, two, three = (self.dir / f"epoch-{n}.omem" for n in (1, 2, 3))
        self.assertEqual(proc(OMNI, "observe", self.source, "-o", one).returncode, 0)
        self.assertEqual(proc(OMNI, "observe", self.source, "--against", one, "-o", two).returncode, 0)
        self.assertEqual(proc(OMNI, "observe", self.source, "--against", two, "-o", three).returncode, 0)
        gap = proc(OMNI, "memory-pulse", three, "--against", one)
        self.assertEqual(gap.returncode, 0, gap.stderr)
        data = json.loads(gap.stdout)
        self.assertEqual(data["continuity"], "GAP_REQUIRES_RESNAPSHOT")
        self.assertTrue(data["resnapshot_required"])
        self.assertFalse(data["delta_authoritative"])
        self.assertNotIn("nuclei", data)
        self.record("A94-D09", continuity=data["continuity"])
        duplicate = json.loads(proc(OMNI, "memory-pulse", one, "--against", one).stdout)
        self.assertEqual(duplicate["continuity"], "DUPLICATE")
        regression = proc(OMNI, "memory-pulse", one, "--against", three)
        self.assertEqual(regression.returncode, 2)
        self.assertIn(b"E_EPOCH", regression.stderr)
        self.record("A94-D10", duplicate="DUPLICATE", regression="E_EPOCH")

    def test_durable_override_restart_is_not_logical_scale(self) -> None:
        result = proc(OMNI, "synapse-scale", self.source, "--entity", "Product",
                      "--instances", "1000000", "--overrides", "257")
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertEqual(data["logical_instances"], 1_000_000)
        self.assertEqual(data["durable_override_records_verified"], 257)
        self.assertTrue(data["restart_roundtrip_verified"])
        self.assertFalse(data["full_population_materialized"])
        corrupt = proc(OMNI, "synapse-scale", self.source, "--entity", "Product",
                       "--instances", "1000", "--overrides", "17",
                       env={"OMNI_TEST_OSDO_FAULT": "truncate"})
        self.assertEqual(corrupt.returncode, 2)
        self.assertIn(b"E_DURABILITY", corrupt.stderr)
        self.record("A94-D11", durable_records=257, restart=True, truncation="E_DURABILITY")
        self.record("A94-D12", logical=1_000_000, durable=257)


if __name__ == "__main__":
    unittest.main(verbosity=2)
