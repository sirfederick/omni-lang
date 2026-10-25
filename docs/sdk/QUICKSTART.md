<!--
SPDX-FileCopyrightText: 2026 Federico T. Begna
SPDX-License-Identifier: MIT OR Apache-2.0
-->

# Integrated SDK development

The public C header is [omni_host_sdk_v1.h](../../include/omni/omni_host_sdk_v1.h). The loader links the shared compiler implementation and C runtime. Node uses a native N-API addon; Python uses ctypes over the same public ABI. The bindings encode/decode through that ABI; they do not introduce a second serialization implementation.

From the root:

```powershell
python tools/omni_dev.py --allow-slow-fs build --target loader --jobs 2
python tools/omni_dev.py --allow-slow-fs build --target node
```

The tests/host_invocation_h02 probes require a prepared dist, real host artifacts and their receipts. Run the source-tree integration driver from Linux after the builds:

```sh
python3 -B tools/run_sdk_smoke.py
```

It prepares the fixture, builds actual entry artifacts, exercises the public C ABI, produces a real runtime response before the Node/Python decode probes, and tests an extracted package with SDK doctor, portable stdlib resolution and a C consumer. Each process and oracle is recorded under build/sdk-smoke (report.json and per-probe logs). A loader build alone is not invocation evidence.

The first package is provisional. Local archive determinism is not independent cold-build reproducibility, and isolation from unrelated producer directories is distinct from universal platform certification. ABI/representations retain [independent versions](../architecture/VERSION_IDENTITIES.md).

See [SDK example](../../examples/host-sdk/src/echo.omni), [test navigation](../../tests/README.md) and [architecture](../architecture/OVERVIEW.md).
