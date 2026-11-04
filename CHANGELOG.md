<!--
SPDX-FileCopyrightText: 2026 Federico T. Begna
SPDX-License-Identifier: MIT OR Apache-2.0
-->

# Changes

## Unreleased — 0.1.0.00 WIP

### Developer experience

- Public-facing setup, contribution, SDK and governance guidance is aligned with the repository's current public visibility.
- Recorded toolchain baselines and additional reported Python 3.13 validation scopes are distinguished from general compatibility guarantees; hosted CI availability is dated and separated from local acceptance.

- Source-tree checks accept normal Git checkouts, worktrees and source exports; native unit responsibilities remain consistent with the canonical list as the compiler grows.
- Test matrices reject empty, incoherent or entirely skipped suites and distinguish explicit JSON probes from unittest cases.
- Build and check/run/test use the same input/output integrity rule for compiler reuse.
- One local/CI acceptance command covers tooling regressions, first-use evaluator/native programs and integrated SDK smoke.
- Portable C/Node/Python examples include artifact/response preparation and are shipped in the provisional SDK archive.
- README, learning guides and capability evidence describe the existing language and SDK with reproducible commands and limits.

These are tooling, example and documentation changes. They do not introduce new language semantics, ABI identities or a published release. Existing language capabilities are described in [Capability Status](docs/language/CAPABILITY_STATUS.md).
