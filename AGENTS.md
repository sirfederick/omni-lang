<!--
SPDX-FileCopyrightText: 2026 Federico T. Begna
SPDX-License-Identifier: MIT OR Apache-2.0
-->

# Engineering instructions

Omni is a programming language with an integrated SDK. Its compiler implementation is C++20 under compiler/src; runtime code is C; Omni programs and stdlib sources use .omni.

Read DEVELOPMENT.md and spec/README.md. Keep implementation, ABI and representations consistent. Do not change independent protocol/stdlib versions when changing product identity. Preserve regression fixtures and copyright notices. Use the canonical Python build scripts through tools/omni_dev.py; Git is not required for development.

Use focal positive/negative tests for the affected contract. Do not claim a platform, capability or remote CI PASS without its actual oracle. Keep generated outputs in build/ or dist/. Never add secrets, local paths, private source identifiers or execution reports to public files. Local execution mandates and evidence in docs/prompts are excluded from publication.

The root editorial README and FEATURES catalog require founder/DT review. No Git initialization, commit, new remote or publication is authorized during technical reconstruction. This instruction does not grant authority to merge, release or change visibility.
