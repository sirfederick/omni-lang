<!--
SPDX-FileCopyrightText: 2026 Federico T. Begna
SPDX-License-Identifier: MIT OR Apache-2.0
-->

# Observed maintenance boundaries

The relocation preserves existing implementation units. check.cpp is large; osnmf.cpp, main.cpp and the N-API wrapper contain dense expressions. These are reviewability concerns, not evidence of a semantic failure. Future changes should separate responsibilities only when a measured change and focal regressions justify it. No formatting campaign, replacement checker or speculative compiler architecture is part of this port.

The structural coverage map is [SPEC_SYNC_COVERAGE.json](../../tests/SPEC_SYNC_COVERAGE.json). Static token checks detect correspondence; executable positive/negative suites remain necessary. Historical certificate/roadmap checks explicitly marked nonportable are not counted as passed controls.
