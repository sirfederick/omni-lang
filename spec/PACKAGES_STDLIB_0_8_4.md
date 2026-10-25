> Distribution status: WIP / NOT_RELEASED. Technical version labels describe independent contracts, not public release certification.

# Packages and minimum standard library — 0.8.4

**Status:** `FROZEN_FOR_IMPLEMENTATION`

## Scope and identity

A84 adds a deterministic local/offline package resolver and a versioned minimum standard library at the host build boundary. Package metadata is not executable Omni source.

A package identity is `(origin, name, version, module_path)`. `origin` is `stdlib` or a normalized workspace-relative local path. A checksum proves selected bytes only; it never proves publisher identity, authority or a capability and never permits script execution.

The supported profile has no registry, network fetch, install/build scripts, environment expansion, native plugin, async, I/O, FFI or ambient authority.

## Manifest, source boundary and lock

Every package root has UTF-8 `omni.package.json`, with no duplicate JSON object keys or unknown top-level keys:

```json
{"schema":"omni.package/1","name":"example.app","version":"0.1.0","entry":"src/main.omni","dependencies":{"stdlib":{"path":"../../stdlib","version":"0.8.4-alpha.8"}}}
```

Names are lowercase ASCII dot-separated segments. Versions are `major.minor.patch` with optional prerelease. Entry and dependency paths must be relative and non-empty. After lexical normalization they must resolve to regular files/roots within the invoking package workspace; absolute paths, workspace escape and symbolic-link crossing are rejected. A relative `..` is therefore valid only when it remains within that workspace.

The existing `import alias "relative.omni";` grammar is unchanged and can resolve only within the selected package `src/` tree. It cannot traverse into dependencies. The resolver builds a closure before the existing parser runs; cross-package source import syntax is deferred instead of receiving an implicit search path.

`omni.lock.json` schema `omni.lock/1` is retained only as a legacy reader
contract. New source identity and writer semantics are frozen by
`PACKAGE_LOCK_SOURCE_IDENTITY_1_0.md`: `omni.lock/2` commits the manifest
separately and commits only regular `.omni` files under the selected `src/`
tree. It never incorporates workstation-local non-source artifacts. An
unchanged v1 lock remains readable; migration to v2 is explicit through
`omni package lock`, never implicit during `check`.

## Resolver contract

`omni package check PACKAGE_ROOT [--offline]` emits `omni.package-resolution/1`, including a deterministic topological closure, identity, manifest hash, source hash and `lock_verified: true`. `omni package lock PACKAGE_ROOT` may replace the root lock only from a local fully resolved closure; it never fetches or executes a dependency. `--offline` is mandatory for the release gate and asserts no network, registry, environment source substitution or undeclared cache lookup; the default is also local-only in A84.

Dependency keys and identities sort by raw UTF-8 byte order. Cycles reject. Multiple identities with identical `(origin, name, version)` but a different hash, or duplicate package names at one consumer edge, are ambiguous. Manifest, source, dependency edge and lock entry must agree exactly.

Resolution contributes no runtime value, allocation, resource, borrow, capability, authority or effect. Failure performs no partial compilation, lock update, cache mutation or execution. A resolved closure is immutable for an invocation, and evaluator and native backend receive the same closure.

## Minimum standard library

`stdlib/` is a regular package with identity `(stdlib, omni.std, VERSION, module_path)`. A84 contains only explicit Result/Option helpers, already-proved iteration helpers, Text/Bytes utilities retaining the A81 Unicode boundary, and deterministic pure utilities. It may not add hidden allocator, OS, clock, random, network, filesystem, process, async or authority behavior.

## Fail-closed diagnostics

| Condition | Required diagnostic |
| --- | --- |
| Malformed, duplicate-key or unknown-field manifest/lock | `E_PACKAGE_MANIFEST` |
| Unsafe, absolute, escaping or symlink-crossing path | `E_PACKAGE_PATH` |
| Missing dependency, version failure, conflicting identity or ambiguity | `E_PACKAGE_RESOLVE` |
| Cycle | `E_PACKAGE_CYCLE` |
| Manifest/source/dependency mismatch or lock drift | `E_PACKAGE_LOCK` |
| Registry, network, script, plugin or environment substitution | `E_PACKAGE_OFFLINE` |
| Source import escaping its package or implicitly reaching dependency | `E_IMPORT_PATH` |

There is no fallback search path, unlocked source selection, lock regeneration in `check`, warning-only integrity state or automatic installation.

## Compatibility and evidence

Metadata is external build input, not Particle, AST, Wave, Wire, ONME, OSM2, OSMI2 or OCAP payload. Writer remains Wave18/OMC18. Unknown manifest/lock schema fails closed. Source with no manifest keeps existing single-file/bundle behavior.

Required evidence is clean/offline resolution, byte-identical repeated lock output, a stdlib consumer, evaluator/native differential, and negative fixtures for every diagnostic above, including tampered source, same-name/different-hash ambiguity, cycle, traversal, symlink escape and dependency traversal.

## Deferred

Remote registries, signed publishers, mirrors/revocation, feature flags, semver ranges, scripts, native dependencies, cross-package source imports, dynamic collections needing a proved allocator, async and hosted effects are deferred.
