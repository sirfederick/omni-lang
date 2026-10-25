<!--
SPDX-FileCopyrightText: 2026 Federico T. Begna
SPDX-License-Identifier: MIT OR Apache-2.0

Editorial text approved by the founder and DT.
Text-only header derived from the owner-provided SVG, at the founder's request.
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

## Contents

- [Your first Omni program](#your-first-omni-program)
- [Build and run](#build-and-run)
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

The exercised native development environment is **Linux x86-64**, including **Ubuntu 24.04 under WSL**. The recorded toolchain uses GCC 13 with C++20 support, Clang 18 for native programs, Python 3.12, and OpenSSL development headers/libcrypto. Node.js and N-API headers are additional dependencies for the Node binding.

From the source-tree root in **PowerShell**:

```powershell
python -B tools/omni_dev.py --allow-slow-fs env
python -B tools/omni_dev.py --allow-slow-fs build --target compiler --jobs 2
python -B tools/omni_dev.py --allow-slow-fs check examples/hola.omni
python -B tools/omni_dev.py --allow-slow-fs run examples/hola.omni
```

The entry point forwards Windows commands to the same workspace through WSL. `--allow-slow-fs` accepts the Windows-mounted filesystem explicitly. On Linux, use `python3` in place of `python`.

To produce and execute a persistent native binary, from **Linux/WSL** at the project root:

```sh
OMNI_HOME="$PWD" build/dev/omni build examples/hola.omni -o build/dev/hola
build/dev/hola
```

The initial integrated distribution is being prepared as **`0.1.0.00`**. No published release or package-manager installation is available. See the [Development Guide](DEVELOPMENT.md) for the canonical build, environment selection, test groups, and troubleshooting.

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

Verification applies to the stated behavior and development profile. The technical catalog connects each area to its contract, example or probe, test, and known limits.

| Exercised area | Example or consumer | Evidence boundary |
| --- | --- | --- |
| Functions, recursion, and conditionals | [`hola.omni`](examples/hola.omni) | Check, native build, run, and exact output |
| Explicit error handling | [`result_minimo.omni`](examples/result_minimo.omni) | Executed `Result` branches and continuation |
| Integers, records, tuples, arrays, `Option`, and enums | [Compatibility adapter](tests/current_compatibility.py) | Current compatibility cases; historical publication checks separated |
| Generic resources | [Resource tests](tests/cp01_generic_resources.py) | Executed generic-resource assertions; broader ownership coverage remains separate |
| Packages and standard-library resolution | [Package tests](tests/cp05_packages.py) | Offline resolution, locks, and extracted-SDK stdlib consumption |
| Hosted files and structured tasks | [Application examples](examples/applications/) | Exact file output and two recovery generations with explicit policy setup |
| Wave/Wire, ONME, and OSNMF | [Projection tests](tests/cp15_projection.py) | Executed representation, compatibility, and semantic-identity assertions |
| C, Node.js, and Python SDK interfaces | [Host probes](tests/host_invocation_h02/) | Real C invocation; Node/Python encoding and decoding of a real runtime response |

**Implemented areas awaiting dedicated verification** include floats, full Unicode/range/view coverage, broader borrowing and container suites, LSP/tooling, dynamic storage, and target-specific hardware/SIMD behavior. Their available sources and tests do not imply a PASS.

**Candidate and deferred work** includes advanced SIMD operations, scoped raw-block syntax, pending-place replacement rules, remote package infrastructure, and broader foreign-ABI mapping. These are documented proposals or scope boundaries; adoption and scheduling require separate decisions.

See [Capability Status](docs/language/CAPABILITY_STATUS.md) for the detailed distinctions, [Implementation Surface](docs/language/IMPLEMENTATION_SURFACE.md) for CLI discovery, and the [Specification Index](spec/INDEX.md) for contract authority. File counts and candidate counts are not feature counts.

## Development status

**Work in progress · Not released.** The recorded local technical baseline comprises **246 functional tests** and **7 verifier tests**, with **0 skips**, consolidated from actual executions and causal follow-up runs. These results describe local evidence, not independent release certification or a single new full-matrix execution.

The exercised profile is Linux x86-64/Ubuntu WSL. Other host platforms, full sanitizer and hardware campaigns, complete binding coverage, and independent distribution reproducibility remain outside that baseline. Remote CI has not run, and no external CI is configured.

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
