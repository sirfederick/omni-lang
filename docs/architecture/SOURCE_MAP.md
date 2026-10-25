<!--
SPDX-FileCopyrightText: 2026 Federico T. Begna
SPDX-License-Identifier: MIT OR Apache-2.0
-->

# Implementation relocation map

Paths below are relative component roles, not links to an external producer.

| Former component path | Current path | Responsibility |
|---|---|---|
| src/*.cpp, src/*.hpp | compiler/src/ | All 23 C++ units and eight internal headers |
| runtime/ | runtime/ | C runtime and invocation codec |
| include/omni/ | include/omni/ | Public C ABI |
| bindings/ | bindings/ | Node/Python wrappers |
| stdlib/ | stdlib/ | Independent minimal Omni package |
| tools/core_sources.txt | tools/core_sources.txt | 21 relocated compiler entries |
| reference/compat/ | reference/compat/ | Immutable general compatibility fixtures only |
| tests/, examples/ | tests/, examples/ | General behavioral regressions and usable inputs |

No Git history, external application tree, prior release receipts or opaque archive bundles are part of this product. Detailed source hashes and selection decisions remain private. Includes, build identity inputs, packaging and tests were adapted to compiler/src without splitting or duplicating shared code.
