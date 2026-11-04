<!--
SPDX-FileCopyrightText: 2026 Federico T. Begna
SPDX-License-Identifier: MIT OR Apache-2.0
-->

# Integrated SDK: build, consume and extract

Product identity: **0.1.0.00 WIP / NOT_RELEASED**. Clone the [public repository](https://github.com/sirfederick/omni-lang) and prepare [the exercised Linux/WSL toolchain](../../DEVELOPMENT.md). No release download or npm/pip/winget package is published.

## Interfaces and their actual scope

| Interface | Example operation | Observable result | Boundary |
| --- | --- | --- | --- |
| [C](../../examples/host-sdk/consumer.c) | Encode input 255 using SDK values, invoke `echo_u8` through the invocation ABI, read and decode the result | `C: echo_u8(255) = 255 (real invocation)` | Public C handles and admitted OMI1 types; not arbitrary foreign symbols |
| [Node N-API](../../examples/host-sdk/consumer.mjs) | Encode 255 and decode the response produced by the C/runtime call | `Node: encoded 255; decoded runtime response = 255` | BigInt handles; this binding example does not directly invoke arbitrary Omni functions |
| [Python ctypes](../../examples/host-sdk/consumer.py) | Encode 255 and decode the same real response through the public wrapper | `Python: encoded 255; decoded runtime response = 255` | Standard-library ctypes; same codec/invocation boundary as above |

The [Omni entry](../../examples/host-sdk/src/echo.omni), [public SDK header](../../include/omni/omni_host_sdk_v1.h) and [invocation header](../../runtime/omni_invocation_v1.h) show the contracts. The C consumer uses both APIs and optionally saves the real response. No example implements an OMI1 codec. Float values, live resources/loans, and other unsupported signatures remain subject to [the ABI's admitted type list](../../spec/HOST_INVOCATION_ABI_1_1.md).

## Linux / WSL source build

All commands start at the checkout root. Ubuntu dependencies:

```sh
sudo apt-get update
sudo apt-get install -y git g++ clang python3 libssl-dev nodejs libnode-dev
python3 -B tools/omni_dev.py env
python3 -B tools/omni_dev.py build --target compiler --jobs 2
python3 -B tools/omni_dev.py build --target loader --jobs 2
python3 -B tools/omni_dev.py build --target node
python3 -B tools/run_sdk_examples.py --output build/sdk-guide-linux
```

For a mounted WSL checkout, insert `--allow-slow-fs` before each driver subcommand. Python needs no pip dependency; C needs the system C compiler and public headers; Node additionally requires `node_api.h` from `libnode-dev`. The recorded baseline is GCC 13.3, Clang 18, Python 3.12 and Node.js 18. A separate validation report records Python 3.13 exercises in selected compiler, first-use, SDK and acceptance scopes; this does not establish general Python 3.13 support.

## PowerShell source build

Install Git/Python on Windows and Ubuntu 24.04 in WSL. Install all Linux dependencies from the previous block **inside Ubuntu**, then run from the Windows checkout root:

```powershell
python -B tools/omni_dev.py --allow-slow-fs env
python -B tools/omni_dev.py --allow-slow-fs build --target compiler --jobs 2
python -B tools/omni_dev.py --allow-slow-fs build --target loader --jobs 2
python -B tools/omni_dev.py --allow-slow-fs build --target node
python -B tools/run_sdk_examples.py --output build/sdk-guide-powershell
```

Both entry scripts use `wslpath` and the existing `OMNI_WSL_DISTRO` bridge (default Ubuntu-24.04). A Windows-native Python process never attempts to load the Linux `.so`. Relative paths start at the checkout; its absolute location is not an SDK requirement.

## What preparation does

`run_sdk_examples.py` copies the public example package into the chosen output, generates its offline lock, builds the admitted host entry and its receipt, compiles C against the real loader, and runs it. C saves the response used by Node/Python. It then verifies each consumer's exit 0 and expected text. All artifacts, logs and `report.json` stay under that output. Choose a fresh `--output build/NAME` on subsequent runs; existing evidence is not removed.

Expected final consumer lines:

```text
C: echo_u8(255) = 255 (real invocation)
Node: encoded 255; decoded runtime response = 255
Python: encoded 255; decoded runtime response = 255
```

See [the complete consumer sources](../../examples/host-sdk/README.md). The source-tree integration smoke additionally covers schema/handle behavior and an extracted installation:

```sh
OMNI_SDK_SMOKE_DIR=build/sdk-guide-smoke python3 -B tools/run_sdk_smoke.py
```

This path must also be fresh. `bash tools/ci.sh` performs this acceptance with a unique output directory and current build artifacts.

## Create and consume a provisional local archive

These Linux/WSL commands create a local archive; they do not publish a package or release:

```sh
python3 -B tools/omni_sdk_package.py --compiler build/dev/omni --runtime build/dev/runtime/libomni_invocation_v1.so --node build/dev/node/omni_host_sdk.node --output build/omni-sdk-local.tar.gz
mkdir -p build/sdk-installed
tar -xzf build/omni-sdk-local.tar.gz -C build/sdk-installed
export OMNI_HOME="$PWD/build/sdk-installed/omni-sdk-v0.1.0.00-linux-x86_64-gnu"
"$OMNI_HOME/bin/omni" sdk doctor
python3 -B "$OMNI_HOME/tools/run_sdk_examples.py" --output "$PWD/build/sdk-installed-example"
```

Doctor must report `status: PASS`; all three consumers must print the results above and exit 0. The archive includes compiler, runtime, public headers, bindings, stdlib, example sources and their standalone driver. The installed driver resolves all product inputs inside that installation, so a separate consumer directory does not need the producer checkout. It still needs the documented Linux toolchain and system libraries.

From PowerShell, open WSL at the same checkout before those shell commands:

```powershell
$linuxRoot = (wsl -d Ubuntu-24.04 --exec wslpath -a (Get-Location).Path).Trim()
wsl -d Ubuntu-24.04 --cd $linuxRoot
```

Use a fresh consumer output. Do not treat local archive determinism as reproducibility across independent toolchains. [Version identities](../architecture/VERSION_IDENTITIES.md) keep the product, `omni.std`, OMI1 and public ABI versions separate.
