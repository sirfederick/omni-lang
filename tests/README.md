<!--
SPDX-FileCopyrightText: 2026 Federico T. Begna
SPDX-License-Identifier: MIT OR Apache-2.0
-->

# Behavioral test navigation

| Behavior | MATRIX groups / actual suites |
|---|---|
| Syntax/types/control flow and native/evaluator behavior | core, compatibility; core_compat_current.py |
| Ownership, generic resources and package imports | generic_resources13, packages13 |
| Representations, semantic identity and projections | compatibility, projection13 |
| SDK packaging/semantic exports | sdk13 |
| Host C ABI, loader, Node/Python | host_invocation_h02; tools/run_sdk_smoke.py |
| Authority, errors and malformed inputs | security, adversarial13 and domain-specific negatives |
| Native hardware profiles | x64/ fixtures; execution requires the corresponding host/emulator and is not inferred |

Current names with version/step labels are preserved to avoid breaking fixtures. [MATRIX.json](MATRIX.json) is executable discovery; NOT_PORTABLE entries explain excluded private-history or obsolete Git-workflow tests. No case is called PASS because it was skipped. The [structural coverage map](SPEC_SYNC_COVERAGE.json) accounts for original check groups and their current implementations or explicit exclusions.

Run focal groups through [the canonical entry](../DEVELOPMENT.md). Reports distinguish process status, counts, skips and timeout. Native SDK probes require fixture preparation and a real response before binding decode. Full conformance, sanitizer and target campaigns are separate from this source-port validation.

Compatibility uses [the current adapter](current_compatibility.py); [coverage](COMPATIBILITY_COVERAGE.json) identifies four nonportable historical publication/research checks and three adapted structural checks. Original test sources remain as adapter inputs, not independent default suites. Groups a89/a96/a97 retain postcommit audit dependencies and cannot run without Git; this is not a precommit PASS. The structural group injects faults into the actual verifier in memory and asserts rejection without changing real sources.
