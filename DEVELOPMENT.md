<!--
SPDX-FileCopyrightText: 2026 Federico T. Begna
SPDX-License-Identifier: MIT OR Apache-2.0
-->

# Build and development

## Obtain sources

The repository is public. Clone it into any checkout location:

```sh
git clone https://github.com/sirfederick/omni-lang.git
cd omni-lang
```

All following relative paths start at this checkout root. A source export also works; Git is not a build prerequisite. The compiler and SDK build from this repository alone.

## Supported environment and dependencies

The exercised profile is Linux x86-64, with Ubuntu 24.04 directly or through WSL. Recorded baseline tools: GCC 13.3, Clang 18, Python 3.12, Node.js 18 and OpenSSL development headers/libcrypto. A separate validation report records Python 3.13 exercises for compiler build, first-use programs, SDK examples and the `tools` / `compiler` acceptance scopes. Treat those as additional exercised scopes, not a general support guarantee or a CI version matrix. Windows commands run the Linux toolchain through WSL; they do not produce Windows-native executables.

In Ubuntu (also inside WSL), prepare the compiler/runtime dependencies:

```sh
sudo apt-get update
sudo apt-get install -y git g++ clang python3 libssl-dev
```

For the Node SDK interface, also install:

```sh
sudo apt-get install -y nodejs libnode-dev
```

Python's SDK binding uses standard-library ctypes. No pip package is required. The C consumer additionally uses the system C compiler and public headers. Node/N-API headers are not required to run a first Omni program.

On Windows install Git for Windows, Python 3.11 or later for the launcher, and WSL with Ubuntu 24.04. Install GCC, Clang, OpenSSL and Node dependencies **inside Ubuntu**, not into the Windows Python environment. `OMNI_WSL_DISTRO` selects an existing distro; the default is `Ubuntu-24.04`.

## Linux / WSL

```sh
python3 -B tools/omni_dev.py env
python3 -B tools/omni_dev.py build --target compiler --jobs 2
python3 -B tools/omni_dev.py check examples/hola.omni
python3 -B tools/omni_dev.py run examples/hola.omni
```

For a checkout on a Windows-mounted filesystem, add `--allow-slow-fs` **before** the subcommand. No workspace move is required. The common CI command below handles the mounted workspace automatically.

The evaluator and native execution are distinct paths:

```sh
OMNI_HOME="$PWD" build/dev/omni eval examples/hola.omni
OMNI_HOME="$PWD" build/dev/omni build examples/hola.omni -o build/dev/hola
build/dev/hola
```

Each prints `Hola, Omni` then `720`, with exit 0. `result_minimo.omni` prints `100` then `El programa continua`, with exit 0. Some other examples intentionally return a computed value: `ranges.omni` returns 22 and `generics_iteration.omni` returns 42; their nonzero exit is part of the example oracle.

## PowerShell

From the checkout root:

```powershell
python -B tools/omni_dev.py --allow-slow-fs env
python -B tools/omni_dev.py --allow-slow-fs build --target compiler --jobs 2
python -B tools/omni_dev.py --allow-slow-fs check examples/hola.omni
python -B tools/omni_dev.py --allow-slow-fs run examples/hola.omni
```

The bridge resolves the checkout with `wslpath`; paths passed above are relative to that checkout. `python -B tools/check_local.py` and `python -B tools/run_sdk_examples.py` have the same Windows-to-WSL entry behavior.

## Tests and the CI command

```sh
bash tools/ci.sh
```

This is the same entry used by GitHub Actions. It checks source/spec consistency, tree/links/licenses, tooling regressions, a current compiler, evaluator/native first-use examples, loader/Node builds and the real SDK smoke including an extracted SDK. It stops on the first failure. Outputs stay in `build/`; it does not publish anything.

For faster causal checks:

```sh
python3 -B tools/check_local.py --scope tools
python3 -B tools/check_local.py --scope compiler
python3 -B tools/omni_dev.py test --group capabilities --report build/reports/capabilities.json
```

`tools` needs no Omni build. `compiler` adds the first-use tests. `all` (the default) also validates the SDK. [MATRIX](tests/MATRIX.json) offers additional behavior groups; do not run all historical/hardware groups for a documentation change. The runner requires a nonempty, non-skipped execution and coherent unittest summary. Explicit JSON probes have a separate contract and check count; they do not invent unittest cases.

## SDK and packages

Build the shared loader and addon through the same driver, then use the [SDK Quick Start](docs/sdk/QUICKSTART.md) or [public consumers](examples/host-sdk/README.md). An existing SDK smoke output is preserved; choose a fresh `OMNI_SDK_SMOKE_DIR` or use the common command, which chooses one for you.

## Build integrity and maintenance

Canonical source lists and Python builders remain the build authority. `build` reuses an artifact only if both inputs and output bytes match its stamp; `check/run/test` enforce that same rule. Missing, malformed or stale stamps require `build`. CMake is not currently a supported build entry.

For Python changes use four spaces, descriptive names and focused subprocess/unit fixtures. C/C++ changes retain local style and compiler warnings; avoid formatting unrelated units. [Compiler responsibilities](compiler/README.md) and [maintenance boundaries](docs/architecture/MAINTAINABILITY.md) identify where to work.

## Common errors

- `pass --allow-slow-fs`: place the flag before `env`, `build`, `check`, `run` or `test` on mounted WSL paths.
- `compiler missing, stale or output changed`: run the compiler build command; do not copy in an old binary or edit its stamp.
- Missing `openssl/evp.h` or `-lcrypto`: install `libssl-dev` inside Ubuntu.
- Missing `node_api.h`: install `libnode-dev`; this is a Node addon dependency.
- An SDK demo output already exists: choose a new `--output build/NAME`; existing evidence is not silently removed.

The latest recorded project disposition (2026-10-26) reports hosted Actions unavailable because of billing restrictions. Check the Actions page for current status. Workflow configuration, local PASS and a successful hosted Actions run are separate facts; no badge or local result asserts remote success.
