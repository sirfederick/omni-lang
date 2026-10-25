#!/usr/bin/env python3
"""Falsify package-lock dependence on non-semantic workstation state.

This is deliberately a two-root harness.  A caller supplies one root on a
Windows-backed filesystem and another on the native Linux filesystem, then
uses the same candidate compiler to materialize locks independently.  It
never copies a lock from one root to the other.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def run(compiler: Path, *args: str, expected: int = 0) -> subprocess.CompletedProcess[bytes]:
    completed = subprocess.run([str(compiler), *args], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if completed.returncode != expected:
        raise RuntimeError(
            f"command returned {completed.returncode}, expected {expected}: {' '.join(args)}; "
            f"stderr={completed.stderr.decode('utf-8', 'replace')[-1000:]}"
        )
    return completed


def prepare(root: Path) -> None:
    if root.exists():
        raise RuntimeError(f"refusing to reuse existing portability root: {root}")
    (root / "src" / "__pycache__").mkdir(parents=True)
    (root / "docs").mkdir()
    (root / ".vscode").mkdir()
    # Exact manifest bytes are part of the v2 identity.
    (root / "omni.package.json").write_bytes(
        b'{"schema":"omni.package/1","name":"ir-c03.portability","version":"0.1.0","entry":"src/main.omni"}\n'
    )
    (root / "src" / "main.omni").write_bytes(b"module ir_c03\nfunc main() u32 { return 7u32 }\n")
    # These files deliberately model unrelated local state.  Their contents
    # must not be copied into the lock identity.
    (root / ".env").write_bytes(b"LOCAL_ONLY=not-semantic\n")
    (root / "src" / "__pycache__" / "helper.pyc").write_bytes(b"not-omni-bytecode")
    (root / "docs" / "local-note.md").write_bytes(b"documentation is not source\n")
    (root / ".vscode" / "cache.json").write_bytes(b"{\"editor\":\"local\"}\n")


def materialize(compiler: Path, root: Path) -> dict[str, str]:
    run(compiler, "package", "lock", str(root), "--offline")
    lock = (root / "omni.lock.json").read_bytes()
    result = run(compiler, "package", "check", str(root), "--offline")
    resolution = json.loads(result.stdout)
    parsed = json.loads(lock)
    if parsed.get("schema") != "omni.lock/2" or resolution.get("lock_schema") != "omni.lock/2":
        raise RuntimeError("candidate did not materialize and verify omni.lock/2")
    package = parsed.get("packages", [{}])[0]
    return {
        "lock_sha256": sha256(lock),
        "manifest_sha256": str(package.get("manifest_sha256", "")),
        "semantic_source_sha256": str(package.get("source_sha256", "")),
    }


def mutation_negative(compiler: Path, root: Path, before: dict[str, str]) -> dict[str, str]:
    (root / "src" / "main.omni").write_bytes(b"module ir_c03\nfunc main() u32 { return 8u32 }\n")
    rejected = run(compiler, "package", "check", str(root), "--offline", expected=2)
    if b"E_PACKAGE_LOCK" not in rejected.stderr:
        raise RuntimeError("semantic source mutation did not fail E_PACKAGE_LOCK")
    after = materialize(compiler, root)
    if after["semantic_source_sha256"] == before["semantic_source_sha256"]:
        raise RuntimeError("semantic source mutation did not change v2 source identity")
    return after


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--compiler", type=Path, required=True)
    parser.add_argument("--windows-root", type=Path, required=True)
    parser.add_argument("--linux-root", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    compiler = args.compiler.resolve()
    if not compiler.is_file() or compiler.is_symlink():
        raise SystemExit("compiler must be a regular non-symlink file")
    try:
        prepare(args.windows_root)
        prepare(args.linux_root)
        windows = materialize(compiler, args.windows_root)
        linux = materialize(compiler, args.linux_root)
        if windows != linux:
            raise RuntimeError("same semantic source produced different v2 lock identity across roots")
        windows_mutation = mutation_negative(compiler, args.windows_root, windows)
        linux_mutation = mutation_negative(compiler, args.linux_root, linux)
        if windows_mutation != linux_mutation:
            raise RuntimeError("mutated semantic source produced different v2 identity across roots")
        report = {
            "schema": "omni.ir-c03-portability/1",
            "status": "PASS",
            "compiler_sha256": sha256(compiler.read_bytes()),
            "lock_schema": "omni.lock/2",
            "non_semantic_inputs": [".env", "src/__pycache__/helper.pyc", "docs/local-note.md", ".vscode/cache.json"],
            "same_semantic_source": windows,
            "mutated_semantic_source": windows_mutation,
            "semantic_mutation_check": "E_PACKAGE_LOCK",
        }
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(json.dumps(report, sort_keys=True))
        return 0
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
        print(f"IR-C03 PORTABILITY FAIL: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
