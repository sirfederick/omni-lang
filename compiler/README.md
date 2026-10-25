<!--
SPDX-FileCopyrightText: 2026 Federico T. Begna
SPDX-License-Identifier: MIT OR Apache-2.0
-->

# Compiler implementation

The compiler implements Omni in C++20. Source programs and the minimal standard library use `.omni`. Start with [DEVELOPMENT](../DEVELOPMENT.md), then locate a responsibility below.

| Responsibility | Entry | Useful tests |
| --- | --- | --- |
| CLI, evaluator dispatch, build/run | [main.cpp](src/main.cpp) | [first use](../tests/cli_smoke.py) |
| Particle lexer/parser and AST | [particle.cpp](src/particle.cpp), [omni.hpp](src/omni.hpp) | [core compatibility](../tests/core_compat_current.py) |
| Import and package resolution | [modules.cpp](src/modules.cpp), [packages.cpp](src/packages.cpp) | [package imports](../tests/cp05_packages.py) |
| Types, loans, ownership, effects | [check.cpp](src/check.cpp), [capabilities.cpp](src/capabilities.cpp) | [generic resources](../tests/cp01_generic_resources.py), [capability examples](../tests/capability_smoke.py) |
| Evaluator | [check.cpp](src/check.cpp), dispatched by main.cpp | [evaluator/native examples](../tests/capability_smoke.py) |
| Native LLVM lowering | [llvm.cpp](src/llvm.cpp) | [native first use](../tests/cli_smoke.py) |
| Wave/Wire readers and writers | [formats.cpp](src/formats.cpp) | [projection](../tests/cp15_projection.py) |
| ONME / OSNMF | [onme.cpp](src/onme.cpp), [osnmf.cpp](src/osnmf.cpp) | [projection](../tests/cp15_projection.py) |
| Loader, public SDK and schema | host_invocation_*.cpp, host_sdk_*.cpp | [host probes](../tests/host_invocation_h02/) |
| Native runtime and public ABI | [runtime](../runtime/), [public header](../include/omni/omni_host_sdk_v1.h) | [SDK consumers](../examples/host-sdk/README.md) |

`tools/core_sources.txt` is the canonical executable unit list. The loader shares those units except `main.cpp`; `SDK_ONLY_SOURCES` in [its builder](../tools/build_invocation_loader.py) adds loader-exclusive units. Update these declarations when adding a real unit. The tree verifier checks responsibility/coverage and duplicates without freezing a permanent file count.

Parsing/resolution/checking precede evaluator or LLVM/Clang execution. Representations are separate supported surfaces; native compilation need not traverse every projection. [Pipeline](../docs/architecture/COMPILER_PIPELINE.md) and [version identities](../docs/architecture/VERSION_IDENTITIES.md) explain the boundaries. Inspect the affected executable tests before changing a type, format or ABI contract. Large existing implementation files require focal changes, not unrelated formatting.
