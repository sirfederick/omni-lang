<!--
SPDX-FileCopyrightText: 2026 Federico T. Begna
SPDX-License-Identifier: MIT OR Apache-2.0
-->

# Development tools

| Command/tool | Purpose |
|---|---|
| check_local.py / ci.sh | Same local/CI acceptance; tools, compiler or full SDK scope; first failure propagates |
| omni_dev.py env/build/check/run/test | Canonical no-Git entry, Windows→WSL or Linux |
| build_compiler.py | Canonical compiler unit list, C++20 |
| build_invocation_loader.py | Shared units, two SDK units and C runtime; hashed input identity |
| build_host_sdk_node.py | N-API addon against public ABI |
| run_test_matrix.py | Behavioral groups, tests/skips/failures/timeouts |
| check_spec_sync.py | Preserved general structural consistency checks |
| verify_tree.py | Filesystem, links, privacy, license and no-Git checks |
| run_sdk_smoke.py | Real ABI/bindings and provisional installation probes |
| run_sdk_examples.py | Public C invocation and Node/Python codec examples; Windows bridge or standalone extracted SDK |
| run_app_examples.py | Instantiate and run autonomous application examples |
| omni_sdk_package.py / doctor.py / codegen.py | Provisional SDK package, validation and bindings |
| omni_lsp.py | Language-service framing and workspace tooling |

Other retained tools are focal test utilities, not a claim that all campaigns ran. [Development](../DEVELOPMENT.md) defines commands and dependencies. The canonical Python builders remain the supported build authority; CMake is not a supported entry. Clones, worktrees and source exports are accepted by the tree checker. Private operational mandates and historical one-shot scripts are not dependencies of these tools.
