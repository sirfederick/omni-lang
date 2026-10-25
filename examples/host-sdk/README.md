<!--
SPDX-FileCopyrightText: 2026 Federico T. Begna
SPDX-License-Identifier: MIT OR Apache-2.0
-->

# Public SDK consumers

The Omni [echo_u8 entry](src/echo.omni) returns its `u8` argument. [consumer.c](consumer.c) constructs public SDK values, encodes a request, invokes the module through the public invocation ABI, decodes 255 and saves the real response when requested. It does not implement a codec.

[consumer.mjs](consumer.mjs) uses the Node addon and BigInt handles to encode 255 and decode that response. [consumer.py](consumer.py) uses the Python ctypes binding for the same codec operation. They do not claim direct arbitrary invocation: C/runtime prepares the response.

After the compiler, loader and addon builds, run at the checkout root:

```sh
python3 -B tools/run_sdk_examples.py --output build/sdk-example
```

In PowerShell, `python -B tools/run_sdk_examples.py --output build/sdk-example` forwards to WSL. The output directory must be fresh. This prepares the lock, artifact/metadata, C executable and response; all logs and `report.json` stay in the selected output.

Expected consumer lines, with exit 0:

```text
C: echo_u8(255) = 255 (real invocation)
Node: encoded 255; decoded runtime response = 255
Python: encoded 255; decoded runtime response = 255
```

The [SDK guide](../../docs/sdk/QUICKSTART.md) covers dependencies and local extraction. This scalar example does not certify all recursive types, lifetimes, authorities or platforms.
