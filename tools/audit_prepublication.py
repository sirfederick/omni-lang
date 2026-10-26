#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Federico T. Begna
# SPDX-License-Identifier: MIT OR Apache-2.0
"""Read-only confidentiality preflight for a FULL private Git clone.

Usage (after git fetch --all --tags --prune and installing Gitleaks):
  python3 tools/audit_prepublication.py --output-dir ../omni-private-audit

Reports are PRIVATE and must remain outside the source checkout.
A clean scan never authorizes publication; rights and GitHub metadata need review.
"""
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

SENSITIVE_NAME = re.compile(
    r"(^|/)(\.env($|\.)|\.ssh($|/)|\.aws($|/)|id_(rsa|ed25519)($|\.)|"
    r"[^/]*\.(pem|p12|pfx|key|sqlite|db|bak|dump|zip|7z|tar|tgz)$|"
    r"[^/]*(secret|credential|private.key|password|backup)[^/]*)$", re.I)


def git(root, *args):
    p = subprocess.run(["git", "-C", str(root), *args], text=True,
                       capture_output=True, encoding="utf-8", errors="replace")
    if p.returncode:
        raise RuntimeError("Git preflight failed; check the checkout locally")
    return p.stdout.strip()


def audit(root, output):
    root = Path(git(root, "rev-parse", "--show-toplevel")).resolve()
    if output == root or root in output.parents:
        raise RuntimeError("Output must be OUTSIDE the Git repository")
    if git(root, "rev-parse", "--is-shallow-repository") != "false":
        raise RuntimeError("BLOCKED: shallow clone cannot certify history")
    if not shutil.which("gitleaks"):
        raise RuntimeError("BLOCKED: install and verify Gitleaks first")
    refs = git(root, "for-each-ref", "--format=%(refname)").splitlines()
    if not refs:
        raise RuntimeError("BLOCKED: no local refs to audit")
    output.mkdir(parents=True, exist_ok=True)
    os.chmod(output, 0o700)
    secret_report = output / "gitleaks-redacted.json"
    report_path = output / "prepublication-audit.json"
    if secret_report.exists() or report_path.exists():
        raise RuntimeError("BLOCKED: output already contains audit reports; use a fresh directory")
    command = ["gitleaks", "git", "--no-banner", "--redact=100", "--log-opts=--all",
               "--report-format", "json", "--report-path", str(secret_report), str(root)]
    p = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if p.returncode not in (0, 1):
        raise RuntimeError("BLOCKED: Gitleaks failed; inspect local tool installation")
    try:
        findings = json.loads(secret_report.read_text(encoding="utf-8"))
    except (ValueError, OSError) as exc:
        raise RuntimeError("BLOCKED: missing or invalid secret scan report") from exc
    if not isinstance(findings, list) or bool(findings) != (p.returncode == 1):
        raise RuntimeError("BLOCKED: secret scan status/report mismatch")
    paths = set(filter(None, git(root, "log", "--all", "--name-only", "--format=").splitlines()))
    suspect = sorted(path for path in paths if SENSITIVE_NAME.search(path))
    blocked = bool(findings or suspect)
    report = {
        "schema": "omni.prepublication-audit/1", "head": git(root, "rev-parse", "HEAD"),
        "ref_count": len(refs), "commit_count": int(git(root, "rev-list", "--all", "--count")),
        "history_path_count": len(paths), "suspect_history_paths": suspect,
        "secret_scan": {"status": "FINDINGS" if findings else "NO_PATTERNS_DETECTED",
                        "finding_count": len(findings), "redacted_report": secret_report.name},
        "github_issues_pr_actions_review": "NOT_RUN_BY_THIS_SCRIPT",
        "rights_review": "PENDING", "visibility_change": "NOT_AUTHORIZED",
        "result": "BLOCKED_TRIAGE" if blocked else "MANUAL_REVIEW_REQUIRED",
        "note": "Only locally fetched refs; check GitHub remote branches, PR refs and attachments separately."
    }
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    os.chmod(report_path, 0o600)
    if secret_report.exists():
        os.chmod(secret_report, 0o600)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", type=Path, default=Path.cwd())
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    try:
        report = audit(args.repository.resolve(), args.output_dir.resolve())
    except (OSError, RuntimeError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(json.dumps({k: report[k] for k in ("head", "ref_count", "commit_count", "secret_scan", "result")}, indent=2))
    return 1 if report["result"] == "BLOCKED_TRIAGE" else 0


if __name__ == "__main__":
    sys.exit(main())
