<!--
SPDX-FileCopyrightText: 2026 Federico T. Begna
SPDX-License-Identifier: MIT OR Apache-2.0
-->

# OVS/1

The canonical product identity has four decimal fields: stage.line.functional.community. The first three have no leading zeros except zero itself. Community zero is 00; one through nine are 01..09; ten and above use unpadded decimal. It is not SemVer.

0.1.0.00 is the planned initial integrated Language/SDK identity. The community field counts coherent admitted, integrated and verified external contributions, not commits, bots or founder preparation. A new functional base resets its community field with traceability; incompatible changes cannot be hidden in that field. No release/tag is created by assigning VERSION.

External package-version adaptation needs injective mapping and tested ordering. ABI, formats and omni.std versions are separate contracts.
