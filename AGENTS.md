<!--
SPDX-FileCopyrightText: 2026 Federico T. Begna
SPDX-License-Identifier: MIT OR Apache-2.0
-->

# Working on Omni

Omni programs use `.omni`. The compiler is C++20 in `compiler/src/`, the runtime is C in `runtime/`, and the SDK shares that implementation through `include/` and `bindings/`.

Read [development](DEVELOPMENT.md), [contributing](CONTRIBUTING.md), and [specification authority](spec/README.md). Work on the current tree; preserve unrelated changes. The canonical build entry is `tools/omni_dev.py`; `python3 -B tools/check_local.py` is the shared local/CI acceptance command. Use `--scope tools` for tooling-only feedback and the affected MATRIX groups for behavior changes. Report failures, skips and environment limits accurately.

Keep ABI, format and stdlib versions independent of product version. Preserve compatibility fixtures and rights notices. Register new compiler units in `tools/core_sources.txt`; SDK-only units are declared by `SDK_ONLY_SOURCES` in the loader builder. Do not duplicate the compiler into a second SDK tree.

README, guides and tests are ordinary maintained project files. Use four-space Python indentation, descriptive functions and short causal tests; follow surrounding C/C++ style for necessary changes. Avoid mass formatting of unrelated implementation or golden fixtures. Do not alter language semantics or a compatibility oracle as an incidental documentation fix.

Keep generated outputs under ignored `build/`. Operational mandates belong in private control outside the product; neither legacy prompt-folder spelling is publishable. Never add credentials or private application data. Normal branch/commit workflows are allowed within the task's authorization. Merging, releasing, changing visibility and deploying remain maintainer decisions. This phase does not authorize work on the website or writes to other projects.
