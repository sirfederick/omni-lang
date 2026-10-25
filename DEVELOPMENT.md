<!--
SPDX-FileCopyrightText: 2026 Federico T. Begna
SPDX-License-Identifier: MIT OR Apache-2.0
-->

# Build and development

The current native profile is Linux x86-64 through Ubuntu WSL. The compiler uses C++20, the native runtime C, and native programs are lowered to textual LLVM IR and compiled by system Clang. Dependencies observed: GCC 13, Clang 18, Python 3.12, OpenSSL headers/libcrypto, Node 18 and N-API headers. Other hosts are not certified by this checkout.

From the project root in PowerShell (OMNI_WSL_DISTRO defaults to Ubuntu-24.04):

```powershell
python tools/omni_dev.py --allow-slow-fs env
python tools/omni_dev.py --allow-slow-fs build --target compiler --jobs 2
python tools/omni_dev.py --allow-slow-fs check examples/hola.omni
python tools/omni_dev.py --allow-slow-fs run examples/hola.omni
python tools/omni_dev.py --allow-slow-fs build --target loader --jobs 2
python tools/omni_dev.py --allow-slow-fs build --target node
python tools/omni_dev.py --allow-slow-fs test --group core --group generic_resources13 --group packages13 --group sdk13 --group compatibility --group projection13
```

From Linux/WSL, use python3 instead of python. The entry point forwards Windows execution to the same existing workspace using wslpath; it never clones or initializes Git. --allow-slow-fs explicitly accepts the mounted filesystem. Outputs and input stamps live under build/dev. A missing/stale compiler is reported rather than silently testing old sources. build skips a component only when its recorded inputs and output hash agree.

Canonical low-level build scripts: tools/build_compiler.py (21 units), tools/build_invocation_loader.py (20 shared units, two additional SDK units and C runtime), and tools/build_host_sdk_node.py (public N-API addon). Their source lists and identity hashing are the authority. CMAKE=DEFERRED_WITH_REASON: introducing another source/build graph during the port would require an additional equivalence campaign; the working canonical driver is retained. No placeholder CMake project is shipped.

Structural checks, without Git:

```powershell
python tools/check_spec_sync.py
python tools/verify_tree.py
```

See [coverage](tests/SPEC_SYNC_COVERAGE.json), [test discovery](tests/README.md), [examples](examples/README.md), [SDK](docs/sdk/QUICKSTART.md), and [specification precedence](spec/README.md). A successful structural scan does not mean semantic tests ran. MATRIX reports tests, failures, skips and timeout per executable; zero tests is not acceptance.

Troubleshooting: missing c++/clang is a host dependency; missing openssl/evp.h or -lcrypto requires development headers/libraries; node_api.h is required only for the addon. Select a different installed WSL distro using OMNI_WSL_DISTRO if necessary. Do not install a new OS or move the founder's checkout as a workaround. Fork/privileged CI and publication are not configured. CI_REMOTE=BLOCKED_ACCOUNT; CI_EXTERNAL=NOT_CONFIGURED.
