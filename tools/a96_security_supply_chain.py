#!/usr/bin/env python3
"""A96 causal security closure and deterministic component inventory."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys
import time


ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT
MAX_FILE_BYTES = 8 * 1024 * 1024
MAX_TOTAL_BYTES = 128 * 1024 * 1024


def git_command(*args: str) -> list[str]:
    marker = REPO / ".git"
    if marker.is_file():
        value = marker.read_text(encoding="utf-8").strip()
        if value.startswith("gitdir:"):
            gitdir = value.split(":", 1)[1].strip().replace("\\", "/")
            windows = re.fullmatch(r"([A-Za-z]):/(.*)", gitdir)
            if windows and sys.platform != "win32":
                gitdir = f"/mnt/{windows.group(1).lower()}/{windows.group(2)}"
            return ["git", f"--git-dir={gitdir}", f"--work-tree={REPO}", *args]
    return ["git", "-C", str(REPO), *args]


def execute(argv: list[str], *, timeout: int = 180) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(argv, cwd=ROOT, text=True, capture_output=True,
                            env={**os.environ, "OMNI_HOME": str(ROOT)}, timeout=timeout)
    if result.returncode != 0:
        raise RuntimeError(f"command failed ({result.returncode}): {' '.join(argv)}\n{result.stdout}{result.stderr}")
    if len(result.stdout) + len(result.stderr) > 256 * 1024:
        raise RuntimeError("security gate command output exceeded bound")
    if "skipped" in (result.stdout + result.stderr).lower():
        raise RuntimeError(f"required security scenario was skipped: {' '.join(argv)}")
    return result


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def role(relative: str) -> str:
    first = PurePosixPath(relative).parts[0]
    return {
        "src": "COMPILER_SOURCE", "runtime": "RUNTIME_SOURCE", "spec": "NORMATIVE_SPEC",
        "tests": "TEST_FIXTURE", "tools": "BUILD_OR_VERIFICATION_TOOL",
        "stdlib": "STANDARD_LIBRARY", "docs": "ACTIVE_DOCUMENTATION",
        "examples": "EXAMPLE",
    }.get(first, "ROOT_METADATA")


def tracked_components() -> tuple[list[dict[str, object]], list[str]]:
    listed = execute(git_command("ls-files", "--", ".")).stdout.splitlines()
    components: list[dict[str, object]] = []
    secret_findings: list[str] = []
    total = 0
    patterns = (
        re.compile("sk" + r"-[A-Za-z0-9_-]{20,}"),
        re.compile("AK" + r"IA[0-9A-Z]{16}"),
        re.compile("-----BEGIN " + r"(?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    )
    seen: set[str] = set()
    for repository_path in listed:
        prefix = ""
        if not repository_path.startswith(prefix):
            raise RuntimeError(f"inventory path escaped active Core: {repository_path}")
        relative = repository_path[len(prefix):]
        posix = PurePosixPath(relative)
        if not relative or posix.is_absolute() or ".." in posix.parts or relative in seen:
            raise RuntimeError(f"unsafe or duplicate inventory path: {relative}")
        seen.add(relative)
        path = ROOT.joinpath(*posix.parts)
        if not path.is_file() or path.is_symlink():
            raise RuntimeError(f"tracked component is absent, non-regular or symlinked: {relative}")
        size = path.stat().st_size
        total += size
        if size > MAX_FILE_BYTES or total > MAX_TOTAL_BYTES:
            raise RuntimeError("component inventory exceeds governed size bound")
        component = {"path": relative, "role": role(relative), "bytes": size, "sha256": digest(path)}
        components.append(component)
        if size <= 1024 * 1024:
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                text = ""
            if any(pattern.search(text) for pattern in patterns):
                secret_findings.append(relative)
    components.sort(key=lambda item: str(item["path"]))
    return components, secret_findings


def selector(file: str, test: str) -> list[str]:
    return [sys.executable, "-B", str(ROOT / "tests" / file), test, "-v"]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--compiler", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--inventory", type=Path, required=True)
    args = parser.parse_args()
    compiler = args.compiler.resolve()
    if not compiler.is_file() or compiler.is_symlink():
        raise SystemExit("compiler must be a regular non-symlink file")
    os.environ["OMNI_TEST_BIN"] = str(compiler)

    start = time.monotonic()
    cases = [
        ("A96-S01", selector("security_regressions_alpha6.py", "CrossTrackHardeningTests.test_unknown_capability_particle_wave_wire_all_fail_closed"), "authority/capability"),
        ("A96-S02", selector("security_regressions_alpha6.py", "CrossTrackHardeningTests.test_semantic_downgrade_matrix_wave_and_wire_fails_closed"), "representation downgrade"),
        ("A96-S03", selector("language_0_8_4_alpha8.py", "A84PackageResolverTests.test_tampered_source_is_lock_drift"), "package lock drift"),
        ("A96-S04", selector("language_0_8_4_alpha8.py", "A84PackageResolverTests.test_manifest_unknown_and_unsafe_dependency_fail_closed"), "package path/manifest"),
        ("A96-S05", selector("language_0_8_6_alpha8.py", "A86HostPolicyTests.test_authority_decision_checks_scope_limit_expiry_and_generation"), "host authority freshness"),
        ("A96-S06", selector("language_0_9_3.py", "A93RuntimeHardeningTests.test_stale_and_cross_subject_proposals_never_publish"), "proposal replay/subject"),
        ("A96-S07", selector("language_0_9_4.py", "A94SystemicDurabilityTests.test_index_and_commit_tampering_fail_closed"), "durable tamper"),
        ("A96-S08", selector("security_regressions_alpha6.py", "CrossTrackHardeningTests.test_build_receipt_binds_exact_provenance"), "build provenance"),
    ]
    scenarios = []
    for identifier, command, attack in cases:
        execute(command)
        scenarios.append({"id": identifier, "attack": attack, "status": "PASS", "exit_code": 0})

    components, secret_findings = tracked_components()
    if secret_findings:
        raise RuntimeError(f"secret-shaped tracked content found: {secret_findings}")
    source_sha = execute(git_command("rev-parse", "HEAD")).stdout.strip()
    inventory = {
        "schema": "omni.component-inventory/1",
        "status": "PASS",
        "subject": f"omni-language@{source_sha}",
        "scope": "tracked active Core source; integrity inventory, not publisher authentication",
        "compiler_sha256": digest(compiler),
        "component_count": len(components),
        "aggregate_bytes": sum(int(item["bytes"]) for item in components),
        "components": components,
        "limitations": ["not a signed SBOM", "no remote registry claim", "hash integrity is not publisher identity"],
    }
    args.inventory.parent.mkdir(parents=True, exist_ok=True)
    args.inventory.write_text(json.dumps(inventory, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    scenarios.append({"id": "A96-S09", "attack": "unbound distribution component", "status": "PASS", "component_count": len(components)})
    scenarios.append({"id": "A96-S10", "attack": "tracked secret/bearer material", "status": "PASS", "findings": 0})

    report = {
        "schema": "omni.a96-security-supply-chain-report/1",
        "version": (ROOT / "VERSION").read_text(encoding="utf-8").strip(),
        "status": "PASS",
        "source_sha": source_sha,
        "compiler_sha256": digest(compiler),
        "elapsed_seconds": round(time.monotonic() - start, 6),
        "hard_max_seconds": 1200,
        "inventory_path": args.inventory.name,
        "inventory_sha256": digest(args.inventory),
        "scenarios": scenarios,
        "claims_not_made": ["publisher authentication", "remote provider security", "application tenant isolation", "application product security"],
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": "PASS", "scenarios": len(scenarios), "components": len(components), "elapsed_seconds": report["elapsed_seconds"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
