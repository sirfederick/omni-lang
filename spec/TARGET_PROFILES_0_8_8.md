> Distribution status: WIP / NOT_RELEASED. Technical version labels describe independent contracts, not public release certification.

# Omni Target Profiles — 0.8.8

**Status:** `FROZEN_FOR_IMPLEMENTATION`
**Language version:** `0.8.8-alpha.8`
**Authority:** normative A88 target-profile contract

## 1. Scope

A88 makes platform support an explicit, machine-readable and falsifiable
contract. It does not add language semantics or a representation version.
Wave20 / OMC20 remains the latest writer.

## 2. Frozen target matrix

| Target ID | State | Required execution |
| --- | --- | --- |
| `linux-x86_64-gnu` | `SUPPORTED` | compiler, evaluator, native runtime, stdlib/package resolver and application subsystem adapters execute on a Linux x86-64 kernel |
| `windows-x86_64-msvc` | `EXPERIMENTAL_NOT_RUN` | native Windows compiler/runtime execution; WSL is not evidence |
| `linux-aarch64-gnu` | `EXPERIMENTAL_NOT_RUN` | native or admitted emulated execution; cross-compile alone is insufficient |
| `macos-aarch64` | `EXPERIMENTAL_NOT_RUN` | native macOS execution |

This release certifies only the listed `SUPPORTED` profile. The current Linux
runner is WSL2 and is disclosed as virtualized; generated ELF programs execute
on its Linux kernel. It is not evidence for Windows-native behavior. Missing
toolchains/runners remain `NOT_RUN`, never PASS, and are not silently removed
from the matrix.

## 3. Target identity

`omni target list --json` reports stable target IDs and state.
`omni target probe --json` reports host OS, architecture, ABI, byte order,
pointer width, compiler/runtime identity and whether the host matches a
supported target. Build receipts and source maps bind the selected target ID.
Unknown target IDs fail closed.

Target identity, a triple, layout metadata or a successful probe never grants
runtime authority.

## 4. Supported-profile invariants

The `linux-x86_64-gnu` gate executes and records:

- compiler rebuild and the accumulated evaluator/native matrix;
- little-endian fixed-width layout and the `omni_ffi_v1` copy ABI;
- UTF-8/Unicode paths, separator normalization and symlink escape rejection;
- file permissions, process exit/signal, deadline and monotonic-time behavior;
- atomic local rename plus flush behavior, with no unsupported power-loss claim;
- package resolution/offline lock identity and cache portability rules;
- real Node/Python application subsystem hosted adapters under exact executable grants;
- target-tagged build receipts, source maps, profile and coverage artifacts.

Results include OS/kernel, architecture, libc, compiler, Node/Python versions,
commands, exit codes and exact source SHA. Platform-specific code is isolated
behind the existing runtime/tool boundary and must preserve common language
semantics and typed errors.

## 5. Compatibility

A88 changes tooling metadata only. Existing Particle, Wave, Wire, ONME, OSM,
OSMI and OCAP artifacts retain their certified semantics. Tool consumers must
tolerate additive optional target fields. Downgrade cannot relabel an
unexecuted target as supported.

## 6. Required gates

The supported target requires positive, negative, malformed, evaluator/native,
sanitizer, reproducibility and package-integrity evidence. application subsystem receives a
target-profile smoke after Core certification. Experimental targets remain
visible with their exact `NOT_RUN` reason.

## 7. Deferred

Windows-native, AArch64 and macOS execution remain experimental until their
toolchains and runners execute the same mandatory profile. A88 does not claim
mobile/web targets, universal binaries, remote runners, signing, production
sandboxing or cross-platform byte identity where the artifact format differs.
