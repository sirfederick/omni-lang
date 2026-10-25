<!--
SPDX-FileCopyrightText: 2026 Federico T. Begna
SPDX-License-Identifier: MIT OR Apache-2.0
-->

# Development tools

| Command/tool | Purpose |
|---|---|
| omni_dev.py env/build/check/run/test | Canonical no-Git entry, Windows→WSL or Linux |
| build_compiler.py | 21 compiler units, C++20 |
| build_invocation_loader.py | Shared units, two SDK units and C runtime; hashed input identity |
| build_host_sdk_node.py | N-API addon against public ABI |
| run_test_matrix.py | Behavioral groups, tests/skips/failures/timeouts |
| check_spec_sync.py | Preserved general structural consistency checks |
| verify_tree.py | Filesystem, links, privacy, license and no-Git checks |
| run_sdk_smoke.py | Real ABI/bindings and provisional installation probes |
| run_app_examples.py | Instantiate and run autonomous application examples |
| omni_sdk_package.py / doctor.py / codegen.py | Provisional SDK package, validation and bindings |
| omni_lsp.py | Language-service framing and workspace tooling |

Other retained tools are focal test utilities, not a claim that all certification campaigns ran. Exact-commit gates, private attestation and publication workflows are not precommit commands. [Development](../DEVELOPMENT.md) defines the commands and environment. CMake is deferred until its graph is shown equivalent to the canonical scripts.
