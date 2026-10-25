<!--
SPDX-FileCopyrightText: 2026 Federico T. Begna
SPDX-License-Identifier: MIT OR Apache-2.0
-->

# Compiler pipeline

The implemented source path is Particle text → parser/AST → module/package resolution and semantic checking → selected execution/projection backend. The evaluator executes checked semantics; the native backend emits LLVM IR and invokes Clang with the C runtime. These are distinct execution paths and require parity tests.

| Responsibility | Actual implementation |
|---|---|
| CLI/driver and build dispatch | compiler/src/main.cpp |
| Particle lexer/parser and introspection | compiler/src/particle.cpp |
| Types, loans, ownership, effects, capabilities | compiler/src/check.cpp and capabilities.cpp |
| Evaluator and checked execution | Evaluator / evaluate / evaluateValue in compiler/src/check.cpp; dispatched by main.cpp |
| Modules and package/stdlib resolution | compiler/src/modules.cpp and packages.cpp |
| Wave/Wire serialization and fences | compiler/src/formats.cpp |
| LLVM IR/native lowering | compiler/src/llvm.cpp |
| ONME semantic projection | compiler/src/onme.cpp |
| OSNMF memory/index identities | compiler/src/osnmf.cpp |
| Host ABI/loader | compiler/src/host_invocation_*.cpp and host_sdk_*.cpp |
| Native runtime/codec | runtime/*.c |

Wave/Wire are structured representations. ONME is a semantic projection, not a machine ISA or a separate language. OSNMF persists semantic identities and observations; identities, hashes and metadata never grant authority. Native compilation does not require a linear traversal through every projection.

[Normative contracts](../../spec/README.md) define the boundaries; [tests](../../tests/README.md) delimit observed behavior.
