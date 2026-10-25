#!/usr/bin/env python3
"""A97 bounded causal operations, maintenance and measurement gate."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT
MATRIX = ROOT / "tests/corpus/a97/operations_maintenance_matrix.json"
MAX_OUTPUT_BYTES = 256 * 1024
MAX_NORMAL_WALL_SECONDS = 1_200
ALLOWED_LABELS = {"operation", "phase", "target_profile"}


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def run(argv: list[str | Path], *, cwd: Path, timeout: int = 60) -> tuple[subprocess.CompletedProcess[bytes], float]:
    start = time.monotonic()
    result = subprocess.run(
        [str(item) for item in argv], cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        timeout=timeout, env={**os.environ, "OMNI_HOME": str(ROOT), "PYTHONDONTWRITEBYTECODE": "1"},
    )
    elapsed = time.monotonic() - start
    if len(result.stdout) + len(result.stderr) > MAX_OUTPUT_BYTES:
        raise RuntimeError(f"operation output exceeded bound: {' '.join(map(str, argv))}")
    return result, elapsed


def require(result: subprocess.CompletedProcess[bytes], label: str) -> None:
    if result.returncode:
        raise RuntimeError(f"{label} failed ({result.returncode}): {result.stdout.decode(errors='replace')}{result.stderr.decode(errors='replace')}")


def percentile(values: list[float], numerator: int, denominator: int) -> float:
    if not values:
        raise ValueError("empty measurement sample")
    ordered = sorted(values)
    index = (len(ordered) - 1) * numerator // denominator
    return round(ordered[index], 6)


def scenario(rows: list[dict[str, Any]], identifier: str, **details: Any) -> dict[str, Any]:
    row = next(item for item in rows if item["id"] == identifier)
    return {"id": identifier, "layer": row["layer"], "boundary": row["boundary"], "oracle": row["oracle"], "status": "PASS", **details}


def command_samples(compiler: Path, source: Path) -> list[float]:
    values: list[float] = []
    for _ in range(3):
        result, elapsed = run([compiler, "summary", source], cwd=ROOT)
        require(result, "summary measurement")
        json.loads(result.stdout)
        values.append(elapsed)
    return values


def local_package_rollback(compiler: Path, directory: Path) -> dict[str, Any]:
    package = directory / "package"
    source = package / "src"
    source.mkdir(parents=True)
    manifest = {
        "schema": "omni.package/1", "name": "a97.local", "version": "0.1.0", "entry": "src/main.omni",
    }
    (package / "omni.package.json").write_text(json.dumps(manifest), encoding="utf-8")
    program = "module a97_local\nfunc main() u32 { return 7u32 }\n"
    entry = source / "main.omni"
    entry.write_text(program, encoding="utf-8")
    locked, _ = run([compiler, "package", "lock", package, "--offline"], cwd=ROOT)
    require(locked, "package lock")
    lock = package / "omni.lock.json"
    original_lock = lock.read_bytes()
    checked, _ = run([compiler, "package", "check", package, "--offline"], cwd=ROOT)
    require(checked, "package initial check")
    entry.write_text(program.replace("7u32", "8u32"), encoding="utf-8")
    drift, _ = run([compiler, "package", "check", package, "--offline"], cwd=ROOT)
    if drift.returncode == 0 or b"E_PACKAGE_LOCK" not in drift.stderr:
        raise RuntimeError("package update did not fail closed on lock drift")
    entry.write_text(program, encoding="utf-8")
    lock.write_bytes(original_lock)
    restored, _ = run([compiler, "package", "check", package, "--offline"], cwd=ROOT)
    require(restored, "package rollback check")
    return {"lock_sha256": digest(lock), "drift_returncode": drift.returncode, "offline": True}


def targeted_regression(file: str, test: str, compiler: Path) -> None:
    result, _ = run([sys.executable, "-B", ROOT / "tests" / file, test, "-v"], cwd=ROOT, timeout=90)
    require(result, test)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--compiler", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--max-report-bytes", type=int, default=128 * 1024)
    args = parser.parse_args()
    if args.max_report_bytes < 4096 or args.max_report_bytes > MAX_OUTPUT_BYTES:
        raise SystemExit("invalid bounded report budget")
    compiler = args.compiler.resolve()
    if not compiler.is_file() or compiler.is_symlink():
        raise SystemExit("compiler must be a regular non-symlink file")
    matrix = json.loads(MATRIX.read_text(encoding="utf-8"))
    rows = matrix.get("scenarios")
    if not isinstance(rows, list) or matrix.get("hard_max_seconds") != MAX_NORMAL_WALL_SECONDS:
        raise SystemExit("invalid A97 operational matrix")
    if {"operation", "phase", "target_profile"} != ALLOWED_LABELS:
        raise SystemExit("unbounded metric labels")
    started = time.monotonic()
    results: list[dict[str, Any]] = []
    results.append(scenario(rows, "A97-O01", labels=sorted(ALLOWED_LABELS), report_budget_bytes=args.max_report_bytes))
    with tempfile.TemporaryDirectory(prefix="omni-a97-") as raw:
        work = Path(raw)
        source = work / "measurement.omni"
        source.write_text("module a97\nfunc main() u32 { return 17u32 }\n", encoding="utf-8")
        cold = command_samples(compiler, source)
        warm = command_samples(compiler, source)
        results.append(scenario(rows, "A97-O02", measurements={
            "unit": "seconds", "denominator": "one compiler summary invocation", "repetitions": 3,
            "cold": {"p50": percentile(cold, 50, 100), "p95": percentile(cold, 95, 100)},
            "warm": {"p50": percentile(warm, 50, 100), "p95": percentile(warm, 95, 100)},
        }))
        staged = work / "clean-stage" / "bin" / "omni"
        staged.parent.mkdir(parents=True)
        shutil.copy2(compiler, staged)
        version, _ = run([staged, "--version"], cwd=work)
        require(version, "staged version")
        if version.stdout.decode().strip().split()[-1] != (ROOT / "VERSION").read_text(encoding="utf-8").strip():
            raise RuntimeError("staged binary version differs from active candidate")
        doctor, _ = run([staged, "doctor", "--json"], cwd=work)
        require(doctor, "staged doctor")
        doctor_json = json.loads(doctor.stdout)
        results.append(scenario(rows, "A97-O03", staged_binary_sha256=digest(staged), doctor_schema=doctor_json.get("schema")))
        diagnostics, _ = run([compiler, "diagnostics"], cwd=ROOT)
        require(diagnostics, "diagnostics")
        profile, _ = run([compiler, "profile", source], cwd=ROOT)
        require(profile, "profile")
        profile_json = json.loads(profile.stdout)
        results.append(scenario(rows, "A97-O04", diagnostics_schema=json.loads(diagnostics.stdout).get("schema"), profile_schema=profile_json.get("schema"), profile_payload_recorded=profile_json.get("payload_recorded")))
        results.append(scenario(rows, "A97-O05", **local_package_rollback(compiler, work)))
        targeted_regression("language_0_9_3.py", "A93RuntimeHardeningTests.test_real_process_lost_and_malformed_ack_have_terminal_cleanup", compiler)
        results.append(scenario(rows, "A97-O06", regression="real process lost/malformed acknowledgement terminal cleanup"))
        targeted_regression("language_0_9_4.py", "A94SystemicDurabilityTests.test_every_publication_phase_recovers_exactly", compiler)
        results.append(scenario(rows, "A97-O07", regression="publication phase recovery"))
    elapsed = round(time.monotonic() - started, 6)
    if elapsed > MAX_NORMAL_WALL_SECONDS:
        raise RuntimeError("A97 gate exceeded normal wall-clock maximum")
    report = {
        "schema": "omni.a97-operations-maintenance-report/1",
        "version": (ROOT / "VERSION").read_text(encoding="utf-8").strip(),
        "status": "PASS", "source_sha": subprocess.check_output(["git", "-C", str(REPO), "rev-parse", "HEAD"], text=True).strip(),
        "compiler_sha256": digest(compiler), "matrix_sha256": digest(MATRIX), "seed": matrix["seed"],
        "hard_max_seconds": MAX_NORMAL_WALL_SECONDS, "elapsed_seconds": elapsed,
        "claim_boundary": matrix["claim_boundary"], "metric_label_keys": sorted(ALLOWED_LABELS),
        "scenarios": results,
        "claims_not_made": ["portable benchmark", "SLO", "external provider integration", "application tenant isolation", "production deployment"],
    }
    payload = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if len(payload.encode("utf-8")) > args.max_report_bytes:
        raise RuntimeError("operation report exceeds declared budget")
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(payload, encoding="utf-8")
    print(json.dumps({"status": "PASS", "scenarios": len(results), "elapsed_seconds": elapsed}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
