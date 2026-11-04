<!--
SPDX-FileCopyrightText: 2026 Federico T. Begna
SPDX-License-Identifier: MIT OR Apache-2.0

Text-only identity derived from the owner-provided SVG.
-->

```text
  ######   #######                                                                       #####
 ###  ### ###  ####              ###########                                             #####
 ###  ### ###  ####            ##############                                              #
 ###  ### ###  ####           ######    ######
 ###  ### ###  ####           ######     ######   ####  #####   #####    ####   #####    #####
 ####     #   ####            #####      ######   ####################   #############   #####
   ######   ####              #####      ######   #####  #####   #####   #####   #####   #####
        #####                 #####      ######   ####   #####   #####   #####   #####   #####
  ######   # ####             #####      ######   ####   #####   #####   #####   #####   #####
 ###   ## ##   ###            #####      ######   ####   #####   #####   #####   #####   #####
 ###  ### ###  ####           ######     ######   ####   #####   #####   #####   #####   #####
 ###  ### ###  ####           ######     #####    ####   #####   #####   #####   #####   #####
 ###  ### ###  ####            ###############    ####   #####   #####   #####   #####   #####
 ######## ########              ############      ####   #####   #####   #####   #####   #####
    ##      ####                                  ####    ####    ####   #####    ####   #####
```

<h1 align="center">Omni Language</h1>

<p align="center">
  A programming language for native computing, structured semantics,<br>
  and human–machine development.
</p>

<p align="center">
  <strong>0.1.0.00</strong> · Work in progress · Not released
</p>

<p align="center">
  <a href="docs/getting-started/QUICKSTART.md">Get started</a> ·
  <a href="docs/language/CAPABILITY_STATUS.md">Capabilities</a> ·
  <a href="examples/README.md">Examples</a> ·
  <a href="DEVELOPMENT.md">Development</a> ·
  <a href="CONTRIBUTING.md">Contribute</a>
</p>

Omni is a general-purpose programming language designed around explicit semantics, controlled capabilities, native execution, and structured representations of computational meaning. Its aim is to make programs understandable to people and inspectable by tools through defined language contracts.

Programs are written in **`.omni`**, using **Particle**, the human-readable source surface. The current compiler is implemented in **C++20**, the native runtime in **C**, and the integrated SDK provides interfaces for **C, Node.js, and Python**. The standard library includes Omni source code.

Today the tree contains runnable native programs, bounded file-processing and recovery examples, typed host-entry consumers, and tools for exploring structured programs and semantic memory. The catalog below explains which parts are implemented, what was exercised and where each boundary remains.

## Contents

- [Your first Omni program](#your-first-omni-program)
- [Build and run](#build-and-run)
- [Use the integrated SDK](#use-the-integrated-sdk)
- [Architecture and representations](#architecture-and-representations)
- [Compiler, runtime, library, and SDK](#compiler-runtime-library-and-sdk)
- [Capabilities and evidence](#capabilities-and-evidence)
- [Development status](#development-status)
- [Project structure](#project-structure)
- [Documentation](#documentation)
- [Contributing and governance](#contributing-and-governance)
- [License](#license)

## Your first Omni program

The following is the source of [`examples/hola.omni`](examples/hola.omni):

```text
module demo

func factorial(n u32) u32 !pure {
    if n <= 1 {
        return 1
    } else {
        return n * factorial(n - 1)
    }
}

func main() u32 !io {
    print("Hola, Omni")
    print(factorial(6))
    return 0
}
```

Output:

```text
Hola, Omni
720
```

The program returns exit code `0`. `u32` is an unsigned 32-bit integer; `!pure` declares a pure function, while `!io` declares the capability boundary used by the entry point.

For a second executable example, [`result_minimo.omni`](examples/result_minimo.omni) handles a `Result` explicitly and continues after the error branch. Explore the [example index](examples/README.md) for each source's setup and verification status.

## Build and run

The repository is public. Clone it into any checkout location:

```sh
git clone https://github.com/sirfederick/omni-lang.git
cd omni-lang
```

The exercised native development environment is **Linux x86-64**, including **Ubuntu 24.04 under WSL**. The recorded baseline uses GCC 13.3 with C++20 support, Clang 18 for native programs, Python 3.12, Node.js 18 for the Node binding, and OpenSSL development headers/libcrypto. Node.js and N-API headers are additional dependencies for the Node binding. A separate validation report also records Python 3.13 exercises covering compiler build, first-use programs, SDK examples, and the `tools` / `compiler` acceptance scopes. This is additional execution evidence for those scopes, not a general compatibility guarantee or a replacement for the recorded Python 3.12 baseline.

Install the base tools **inside Ubuntu**, including when using WSL:

```sh
sudo apt-get update
sudo apt-get install -y git g++ clang python3 libssl-dev
```

On Windows, install Git for Windows, Python 3.11 or later for the launcher, and WSL with Ubuntu 24.04. The compilers and Linux libraries above belong inside Ubuntu. Node is not required for a first Omni program.

From the source-tree root in **Linux / WSL**:

```sh
python3 -B tools/omni_dev.py env
python3 -B tools/omni_dev.py build --target compiler --jobs 2
python3 -B tools/omni_dev.py check examples/hola.omni
python3 -B tools/omni_dev.py run examples/hola.omni
```

From the source-tree root in **PowerShell**:

```powershell
python -B tools/omni_dev.py --allow-slow-fs env
python -B tools/omni_dev.py --allow-slow-fs build --target compiler --jobs 2
python -B tools/omni_dev.py --allow-slow-fs check examples/hola.omni
python -B tools/omni_dev.py --allow-slow-fs run examples/hola.omni
```

The entry point forwards Windows commands through WSL; this is not Windows-native code generation. `OMNI_WSL_DISTRO` selects an existing distro (default `Ubuntu-24.04`). For a Windows-mounted checkout, including from a WSL shell, insert `--allow-slow-fs` before the driver subcommand.

To produce and execute a persistent native binary, from **Linux/WSL** at the project root:

```sh
OMNI_HOME="$PWD" build/dev/omni eval examples/hola.omni
OMNI_HOME="$PWD" build/dev/omni build examples/hola.omni -o build/dev/hola
build/dev/hola
```

The initial integrated distribution is **`0.1.0.00` WIP**. No release download or package-manager installation is published. A missing/stale/changed compiler requires rerunning `build`; missing `openssl/evp.h` requires `libssl-dev` inside Ubuntu. See [Development](DEVELOPMENT.md) for diagnostics and [Learn Omni](docs/language/README.md) for a progressive introduction.

## Use the integrated SDK

The SDK exchanges typed values with admitted compiled Omni host entries through the public ABI. The [C example](examples/host-sdk/consumer.c) performs a real `echo_u8(255)` invocation. [Node](examples/host-sdk/consumer.mjs) uses N-API and [Python](examples/host-sdk/consumer.py) uses ctypes to encode a request and decode the actual response produced by C/runtime. Those bindings do not expose arbitrary direct function invocation.

For Node, install the additional dependencies **inside Ubuntu**; Python ctypes uses the standard library:

```sh
sudo apt-get install -y nodejs libnode-dev
```

With the compiler built, **Linux / WSL**, from the checkout root:

```sh
python3 -B tools/omni_dev.py build --target loader --jobs 2
python3 -B tools/omni_dev.py build --target node
python3 -B tools/run_sdk_examples.py --output build/sdk-readme-linux
```

**PowerShell**, from that same checkout root:

```powershell
python -B tools/omni_dev.py --allow-slow-fs build --target loader --jobs 2
python -B tools/omni_dev.py --allow-slow-fs build --target node
python -B tools/run_sdk_examples.py --output build/sdk-readme-powershell
```

The example entry also bridges to WSL. It prepares the offline lock, host artifact and metadata, compiles the C consumer and saves its real response before running Node/Python. No private evidence directory or hand-written OMI1 codec is required. Generated data stays under the chosen `build/` output; choose a fresh name when repeating a demonstration.

The three final consumer lines are:

```text
C: echo_u8(255) = 255 (real invocation)
Node: encoded 255; decoded runtime response = 255
Python: encoded 255; decoded runtime response = 255
```

Each consumer exits 0. Read the [small consumers and Omni entry](examples/host-sdk/README.md) and [SDK Quick Start](docs/sdk/QUICKSTART.md) for API limits and commands to generate, extract and validate a local SDK archive. The archive also carries these examples and their driver so it can be consumed without the producer checkout. No npm, pip, winget or Windows-native SDK package is advertised.

## Architecture and representations

Omni gives source, structured representations, and semantic memory distinct responsibilities:

| Surface | Responsibility | Contract |
| --- | --- | --- |
| **Particle** · `.omni` | Human-readable source syntax, parsed and semantically checked by the compiler | [Grammar](spec/particle.ebnf) |
| **Wave** · `.owave` | Structured textual program representation with versioned compatibility rules | [Wave / Wire](spec/IR_WAVE_WIRE_0_2.md) |
| **Wire** · `.owire` | Binary program representation with explicit reader/writer version boundaries | [Wave / Wire](spec/IR_WAVE_WIRE_0_2.md) |
| **ONME** · `.onme` | Semantic program projection with identity and integrity contracts | [ONME](spec/ONME_0_7.md) |
| **OSNMF** | Semantic-memory structures, identities, relationships, and observations | [OSNMF](spec/OSNMF_0_7.md) |

```text
Particle source → parsing, resolution, and semantic checking
                  ├─ evaluator
                  ├─ LLVM IR → Clang + C runtime → native executable
                  └─ structured and semantic representations
```

Native compilation does not require a sequential passage through every representation. ONME is a semantic projection; OSNMF identities and metadata do not grant runtime authority. Read the [compiler pipeline](docs/architecture/COMPILER_PIPELINE.md) and [specification precedence](spec/README.md) for the precise boundaries.

## Compiler, runtime, library, and SDK

| Component | Implementation and role |
| --- | --- |
| **Compiler** | C++20 under [`compiler/src/`](compiler/src/): parsing, semantic checking, representations, evaluation, and native lowering |
| **Runtime** | C under [`runtime/`](runtime/): native program support and invocation codec |
| **Standard library** | Minimal Omni library under [`stdlib/`](stdlib/), including `src/prelude.omni` |
| **Integrated SDK** | Public C ABI in [`include/omni/`](include/omni/), shared loader/backend sources, [Node N-API](bindings/node/) and [Python ctypes](bindings/python/) bindings |

The SDK shares implementation with the compiler and runtime. Its sources remain in those components and the public interface directories. See [SDK Quick Start](docs/sdk/QUICKSTART.md) for build and integration workflows.

The product identity is `0.1.0.00`. ABI, representation, and package versions are independent: the current `omni.std` package retains `0.8.4-alpha.8`. See [Version Identities](docs/architecture/VERSION_IDENTITIES.md).

## Capabilities and evidence

The table separates **implementation** from **verification** and explains practical use. Each family links to its implementation entry, authentic example, reproducible test and limits in the detailed catalog. A passing example does not certify an entire family.

| Family and practical use | Implementation | Verification scope | Example |
| --- | --- | --- | --- |
| **[Functions and flow](docs/language/CAPABILITY_STATUS.md#functions-and-flow)** — Compute typed recursive functions and branch on values. | Implemented | First-use evaluator/native oracles | [examples/hola.omni](examples/hola.omni) |
| **[Numeric types and conversions](docs/language/CAPABILITY_STATUS.md#numeric-types-and-conversions)** — Use fixed-width integers, checked casts, wrapping/saturating arithmetic and f32/f64. | Implemented | Numeric/float examples in evaluator and native execution | [examples/numeric.omni](examples/numeric.omni) |
| **[Records tuples and arrays](docs/language/CAPABILITY_STATUS.md#records-tuples-and-arrays)** — Represent checked records, heterogeneous tuples and fixed-size arrays. | Implemented subset | Product example evaluator/native oracles | [examples/product_types.omni](examples/product_types.omni) |
| **[Option Result enums and matching](docs/language/CAPABILITY_STATUS.md#option-result-enums-and-matching)** — Handle missing/error alternatives, including an Err branch that continues execution. | Implemented | First-use and Option/enum example oracles | [examples/result_minimo.omni](examples/result_minimo.omni) |
| **[Generics and traits](docs/language/CAPABILITY_STATUS.md#generics-and-traits)** — Specialize explicit type arguments and statically checked trait implementations. | Implemented static subset | Generic example evaluator/native; broader trait methods not rerun here | [examples/generics_iteration.omni](examples/generics_iteration.omni) |
| **[Ownership loans views and resources](docs/language/CAPABILITY_STATUS.md#ownership-loans-views-and-resources)** — Borrow a buffer exclusively, release it and inspect bounded read-only views. | Implemented subset | Borrow/view examples evaluator/native; broader owning containers separate | [examples/borrow_mut.omni](examples/borrow_mut.omni) |
| **[Effects and capabilities](docs/language/CAPABILITY_STATUS.md#effects-and-capabilities)** — Declare required effects and reject I/O in a pure function before execution. | Implemented | Positive evaluator/native and semantic E_CAPABILITY rejection | [tests/fixtures/dx/io_allowed.omni](tests/fixtures/dx/io_allowed.omni) |
| **[Unicode text and iteration](docs/language/CAPABILITY_STATUS.md#unicode-text-and-iteration)** — Distinguish UTF-8 byte/scalar counts and iterate bounded ranges/views. | Implemented subset | Unicode/range examples evaluator/native | [examples/unicode_text.omni](examples/unicode_text.omni) |
| **[Tasks and concurrency](docs/language/CAPABILITY_STATUS.md#tasks-and-concurrency)** — Spawn/join scoped tasks and persist recovery generations. | Implemented bounded subset | Existing native application evidence; full concurrency suite not rerun here | [examples/applications/recovery-service/src/main.omni](examples/applications/recovery-service/src/main.omni) |
| **[Files and permissions](docs/language/CAPABILITY_STATUS.md#files-and-permissions)** — Read bounded input and write checked output under explicit filesystem grants. | Implemented hosted subset | Existing exact-output native application evidence | [examples/applications/data-cli/src/main.omni](examples/applications/data-cli/src/main.omni) |
| **[Modules packages and stdlib](docs/language/CAPABILITY_STATUS.md#modules-packages-and-stdlib)** — Resolve declared imports/dependencies and generate/check offline locks. | Implemented offline subset | Package evidence and real extracted-SDK stdlib consumption | [examples/a84_package_consumer/src/main.omni](examples/a84_package_consumer/src/main.omni) |
| **[Evaluator and native compilation](docs/language/CAPABILITY_STATUS.md#evaluator-and-native-compilation)** — Evaluate checked programs or emit LLVM IR and build with Clang and the C runtime. | Implemented Linux profile | Exact first-use evaluator/native output and exit oracles | [examples/hola.omni](examples/hola.omni) |
| **[Wave Wire ONME and OSNMF](docs/language/CAPABILITY_STATUS.md#wave-wire-onme-and-osnmf)** — Read/write structured programs and project/query semantic identities and memory. | Implemented versioned surfaces | Accepted projection/compatibility evidence retained; not rerun wholesale here | [examples/hola.owave](examples/hola.owave) |
| **[C Node and Python SDK](docs/language/CAPABILITY_STATUS.md#c-node-and-python-sdk)** — Embed admitted host entries and exchange values through the public ABI and codecs. | Implemented bounded ABI and codecs | C invokes; Node/Python encode and decode a real runtime response | [examples/host-sdk/consumer.c](examples/host-sdk/consumer.c) |
| **[Development tools](docs/language/CAPABILITY_STATUS.md#development-tools)** — Check/format code, inspect diagnostics, export context and use the existing LSP implementation. | Implemented subset | Tooling regressions; full LSP/admission suites not rerun here | [docs/language/IMPLEMENTATION_SURFACE.md](docs/language/IMPLEMENTATION_SURFACE.md) |
| **[SIMD](docs/language/CAPABILITY_STATUS.md#simd)** — Use supported 128-bit lane records and masks with explicit profile fences. | Implemented target-bound subset | Not executed in this revision; dedicated tests indexed | [examples/storage/simd.omni](examples/storage/simd.omni) |
| **[Dynamic storage](docs/language/CAPABILITY_STATUS.md#dynamic-storage)** — Build resource-based heaps, arenas, vectors and related containers. | Implemented library subset | Not executed in this revision; dedicated tests indexed | [examples/storage/vec.omni](examples/storage/vec.omni) |
| **[Hardware profiles](docs/language/CAPABILITY_STATUS.md#hardware-profiles)** — Express checked raw-memory, layout, CPU and port operations in explicit freestanding profiles. | Implemented experimental subsets | Not executed in this revision; target/QEMU suites indexed | [tests/x64/README.md](tests/x64/README.md) |

**Proposed/deferred scope** includes advanced SIMD operations, scoped raw-block syntax, pending-place replacement, remote package infrastructure and broader foreign-ABI mapping. These are not adopted merely because a candidate document exists. Read [candidate status](docs/language/CAPABILITY_STATUS.md#candidate-extensions-and-adoption-status) and [deferred work](docs/language/CAPABILITY_STATUS.md#documented-future-work-not-current-functionality).

## Development status

**Work in progress · Not released.** Use the same acceptance command locally and in the Linux CI workflow:

```sh
bash tools/ci.sh
```

From PowerShell use `python -B tools/check_local.py`. Tooling-only feedback is available with `--scope tools`; `--scope compiler` adds first-use evaluator/native tests, and the default also exercises the SDK. Each stops on failure and reports effective cases. [MATRIX](tests/MATRIX.json) offers additional targeted groups; the historical functional baseline does not replace current reproducible commands.

The exercised profile is Linux x86-64/Ubuntu WSL. Other host platforms, full sanitizer/hardware campaigns, complete binding coverage and independent toolchain reproducibility remain separate work. Workflow configuration, local PASS and successful hosted Actions execution are different facts. The latest recorded project disposition (2026-10-26) reports that hosted Actions was unavailable because of billing restrictions; check the repository's Actions page for current status. No badge or local result is presented as a remote PASS.

Recent [Unreleased improvements](CHANGELOG.md) concern the tree checker, nonempty test runner, binary-integrity validation, shared CI entry and usable SDK examples. They do not introduce new language semantics or announce a release.

The [test guide](tests/README.md) and [matrix](tests/MATRIX.json) describe the suites and their prerequisites. Some contracts remain candidates or `NEEDS_REVIEW`; the [capability catalog](docs/language/CAPABILITY_STATUS.md) records those boundaries.

## Project structure

```text
omni-lang/
├── compiler/src/        C++20 compiler and shared SDK implementation
├── runtime/             Native C runtime and invocation codec
├── stdlib/              Standard library, including .omni source
├── include/omni/        Public C ABI
├── bindings/            Node.js and Python bindings
├── examples/            Programs, application fixtures, and library examples
├── spec/                Grammar, semantics, representations, and ABI contracts
├── tests/               Functional, compatibility, SDK, and verifier tests
├── tools/               Build, development, language-service, and SDK tools
├── docs/                Guides, architecture, language, SDK, and governance
└── reference/           Compatibility fixtures and retained test corpus
```

## Documentation

| Start here | Reference |
| --- | --- |
| Write and run a first program | [Quick Start](docs/getting-started/QUICKSTART.md) |
| Build and work on the implementation | [Development Guide](DEVELOPMENT.md) · [Compiler Guide](compiler/README.md) |
| Understand the architecture | [Overview](docs/architecture/OVERVIEW.md) · [Pipeline](docs/architecture/COMPILER_PIPELINE.md) |
| Explore language behavior | [Language Guide](docs/language/README.md) · [Examples](examples/README.md) |
| Inspect capability evidence | [Capability Status](docs/language/CAPABILITY_STATUS.md) |
| Read normative contracts | [Specification Authority](spec/README.md) · [Specification Index](spec/INDEX.md) |
| Integrate a host application | [SDK Quick Start](docs/sdk/QUICKSTART.md) |
| Discover tests and tools | [Tests](tests/README.md) · [Tools](tools/README.md) |

## Contributing and governance

Start with [Contributing](CONTRIBUTING.md): build the project, run a relevant example and test, and preserve the contracts affected by a change. Contributions use DCO sign-off and retain applicable source attribution.

Federico T. Begna is the founder and initial maintainer. [Governance](GOVERNANCE.md) defines review and admission authority; [OVS](docs/governance/OVS-1.md) and [OFHS](docs/governance/OFHS-1.md) document the project's versioning and source-organization conventions.

Read the [Code of Conduct](CODE_OF_CONDUCT.md) and [Security Policy](SECURITY.md). Release and publication decisions require their own approval and evidence.

## License

Eligible Omni Language sources are intended for distribution under **MIT OR Apache-2.0**. See [LICENSE-MIT](LICENSE-MIT), [LICENSE-APACHE](LICENSE-APACHE), and [Third-Party Notices](THIRD_PARTY_NOTICES.md) for attribution and dependency boundaries. Publication remains subject to source-attribution and third-party licensing review.
