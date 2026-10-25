#!/usr/bin/env python3
"""A89 bounded malformed-input, recovery and dependency-inventory gate."""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import sys
import tempfile
import time


ROOT = Path(__file__).resolve().parents[1]


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git_command(repo: Path, *args: str) -> list[str]:
    """Address Git through a Windows-linked worktree when executing in WSL."""
    marker = repo / ".git"
    if marker.is_file():
        value = marker.read_text(encoding="utf-8").strip()
        if value.startswith("gitdir:"):
            gitdir = value.split(":", 1)[1].strip().replace("\\", "/")
            windows = re.fullmatch(r"([A-Za-z]):/(.*)", gitdir)
            if windows and sys.platform != "win32":
                gitdir = f"/mnt/{windows.group(1).lower()}/{windows.group(2)}"
            return ["git", f"--git-dir={gitdir}", f"--work-tree={repo}", *args]
    return ["git", "-C", str(repo), *args]


def execute(argv: list[str], *, expected: set[int] = {0}, timeout: int = 20) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(argv, cwd=ROOT, text=True, capture_output=True,
                            check=False, timeout=timeout,
                            env={**os.environ, "OMNI_HOME": str(ROOT)})
    if result.returncode not in expected:
        raise RuntimeError(
            f"unexpected exit {result.returncode}, expected {sorted(expected)}: "
            f"{' '.join(argv)}\n{result.stdout}{result.stderr}"
        )
    if len(result.stdout) + len(result.stderr) > 65536:
        raise RuntimeError("command output exceeded the A89 evidence bound")
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--compiler", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--duration-seconds", type=float, default=2.0)
    args = parser.parse_args()
    compiler = args.compiler.resolve()
    if not compiler.is_file() or compiler.is_symlink():
        raise SystemExit("compiler must be a regular non-symlink file")
    if not 0.1 <= args.duration_seconds <= 1200:
        raise SystemExit("prerelease duration must be within 0.1..1200 seconds")

    manifest_path = ROOT / "tests" / "corpus" / "a89" / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema") != "omni.malformed-corpus/1":
        raise RuntimeError("unsupported malformed corpus schema")

    source_files = [
        line.strip() for line in (ROOT / "tools" / "core_sources.txt").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    inventory = []
    for relative in source_files:
        path = ROOT / relative
        if not path.is_file():
            raise RuntimeError(f"inventory source missing: {relative}")
        inventory.append({"path": relative, "sha256": digest(path)})

    target = json.loads(execute([str(compiler), "target", "probe", "--json"]).stdout)
    compiler_version = execute([str(compiler), "--version"]).stdout.strip()
    backend = execute([os.environ.get("OMNI_CLANG", "clang"), "--version"]).stdout.splitlines()[0]
    malformed_results: list[dict[str, object]] = []

    start = time.monotonic()
    iterations = 0
    cache_repair_verified = False
    with tempfile.TemporaryDirectory(prefix="omni-a89-") as raw:
        temporary = Path(raw)
        for item in manifest["cases"]:
            payload = base64.b64decode(item["base64"], validate=True)
            if hashlib.sha256(payload).hexdigest() != item["sha256"]:
                raise RuntimeError(f"corpus hash mismatch: {item['id']}")
            sample = temporary / f"{item['id']}{item['extension']}"
            sample.write_bytes(payload)
            result = execute([str(compiler), "check", str(sample)], expected={2}, timeout=5)
            diagnostic = item["expected_diagnostic"]
            if diagnostic not in result.stderr and diagnostic not in result.stdout:
                raise RuntimeError(
                    f"{item['id']} did not produce {diagnostic}: "
                    f"stdout={result.stdout!r} stderr={result.stderr!r}"
                )
            malformed_results.append({"id": item["id"], "sha256": item["sha256"],
                                      "diagnostic": diagnostic, "exit_code": result.returncode})

        source = temporary / "recovery.omni"
        source.write_text("module recovery\nfunc main() u32 !pure { return 23u32; }\n",
                          encoding="utf-8", newline="")
        cache = temporary / "cache"
        reference_hash = ""
        while iterations == 0 or time.monotonic() - start < args.duration_seconds:
            first = temporary / f"clean-{iterations}"
            second = temporary / f"cached-{iterations}"
            execute([str(compiler), "build", str(source), "-o", str(first), "--no-cache"])
            execute([str(compiler), "build", str(source), "-o", str(second), "--cache-dir", str(cache)])
            current = digest(first)
            if digest(second) != current:
                raise RuntimeError("clean/cached artifact divergence")
            if reference_hash and current != reference_hash:
                raise RuntimeError("artifact changed during stable-input stress")
            reference_hash = current
            evaluated = execute([str(compiler), "eval", str(source)], expected={23})
            native = execute([str(second)], expected={23})
            if evaluated.stdout != native.stdout:
                raise RuntimeError("evaluator/native output divergence")
            if not cache_repair_verified:
                entries = list((cache / "build-v1").glob("*/app"))
                if len(entries) != 1:
                    raise RuntimeError("expected one cache entry for repair gate")
                damaged = bytearray(entries[0].read_bytes())
                damaged[len(damaged) // 2] ^= 1
                entries[0].write_bytes(damaged)
                repaired = temporary / "repaired"
                execute([str(compiler), "build", str(source), "-o", str(repaired), "--cache-dir", str(cache)])
                if digest(repaired) != reference_hash:
                    raise RuntimeError("corrupt cache was not repaired causally")
                cache_repair_verified = True
            iterations += 1

    elapsed = time.monotonic() - start
    if elapsed < args.duration_seconds:
        raise RuntimeError("bounded stress ended before requested duration")
    repo = ROOT
    source_sha = execute(git_command(repo, "rev-parse", "HEAD")).stdout.strip()
    stdlib = ROOT / "stdlib"
    report = {
        "schema": "omni.release-hardening/1",
        "status": "PASS",
        "language_version": (ROOT / "VERSION").read_text(encoding="utf-8").strip(),
        "source_sha": source_sha,
        "compiler_sha256": digest(compiler),
        "compiler_version": compiler_version,
        "backend_identity": backend,
        "python_version": platform.python_version(),
        "platform": platform.platform(),
        "target_probe": target,
        "corpus": {"manifest_sha256": digest(manifest_path), "cases": malformed_results},
        "dependency_inventory": {
            "kind": "source-and-local-dependency-inventory-not-signed-sbom",
            "translation_units": inventory,
            "stdlib_manifest_sha256": digest(stdlib / "omni.package.json"),
            "stdlib_lock_sha256": digest(stdlib / "omni.lock.json"),
        },
        "stress": {
            "kind": "bounded-recovery-stress-not-prolonged-soak",
            "requested_seconds": args.duration_seconds,
            "observed_seconds": elapsed,
            "iterations": iterations,
            "artifact_sha256": reference_hash,
            "cache_repair": cache_repair_verified,
            "evaluator_native": "PASS",
        },
        "remote_ci": {"state": "NOT_RUN", "blocker": "BLOCKED_BILLING"},
        "limitations": ["finite corpus", "finite stress duration", "hashes are not signatures",
                        "no power-loss, disk-full, OOM-kill or multi-host failover claim"],
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": "PASS", "iterations": iterations,
                      "observed_seconds": elapsed, "report": str(args.report)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
