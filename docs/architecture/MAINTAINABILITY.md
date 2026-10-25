<!--
SPDX-FileCopyrightText: 2026 Federico T. Begna
SPDX-License-Identifier: MIT OR Apache-2.0
-->

# Observed maintenance boundaries

check.cpp combines substantial checking and evaluator logic; osnmf.cpp, main.cpp and the N-API wrapper contain dense expressions. Use the [responsibility map](../../compiler/README.md) and focal regressions before editing these areas. Separate helpers when an actual change benefits from a clearer responsibility, and retain surrounding style in untouched code. File size alone does not justify a new architecture or a mass-formatting campaign.

The structural coverage map is [SPEC_SYNC_COVERAGE.json](../../tests/SPEC_SYNC_COVERAGE.json). Static token checks detect correspondence; executable positive/negative suites remain necessary. Historical certificate/roadmap checks explicitly marked nonportable are not counted as passed controls.
