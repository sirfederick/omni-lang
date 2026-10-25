> Distribution status: WIP / NOT_RELEASED. Technical version labels describe independent contracts, not public release certification.

# Package lock source identity — 1.0 convergence repair

**Status:** `FROZEN_FOR_IMPLEMENTATION`

**Motivating finding:** `IR-C03` / `RFC-0073`

## Scope

This is a bounded supply-chain and reproducibility repair to the offline
package resolver. It does not add source syntax, runtime effects, authority,
representations, a registry, or a application subsystem/provider API.

`omni.lock/1` defined a package source-tree hash by recursively including
almost every regular file below a package root. Consequently an ignored local
secret, Python cache, editor artifact or other non-semantic file could make an
otherwise clean package appear tampered. A lock is an integrity commitment to
declared package source, not an accidental commitment to local workstation
state.

## Lock schemas and migration

New `omni package lock PACKAGE_ROOT --offline` output uses `omni.lock/2`.
`omni.lock/2` is not byte-compatible with `omni.lock/1`; migration is explicit
by running `package lock`. `package check` accepts an unchanged valid
`omni.lock/1` only as a legacy reader. It never rewrites, upgrades or repairs a
lock during `check`.

The legacy reader computes the legacy commitment only to validate the exact
legacy bytes. It does not make `omni.lock/1` the source-identity rule for new
locks. A changed legacy package fails `E_PACKAGE_LOCK`; the caller chooses
whether to migrate with the explicit `lock` command.

## v2 source identity

For every selected package, a v2 commitment is the ordered pair:

```text
(manifest_sha256, semantic_source_sha256)
```

`manifest_sha256` is the SHA-256 of the exact UTF-8 `omni.package.json` bytes.
`semantic_source_sha256` is SHA-256 over lexicographically sorted entries:

```text
src/<relative>.omni + "\n" + SHA-256(file bytes) + "\n"
```

Only regular `.omni` files beneath the physical `src/` directory participate.
The declared entry MUST be a regular `.omni` file under `src/`; an entry that
escapes `src/`, is absolute, contains a parent traversal, or is not `.omni`
fails `E_PACKAGE_PATH` before source hashing.

Non-semantic files — including `.env`, cache files, Python bytecode, editor
metadata, logs, evidence and documentation — do not participate in a v2
source commitment. They cannot repair a lock, grant authority, be fetched, or
be executed by the resolver.

Any symbolic link encountered in the selected `src/` tree fails
`E_PACKAGE_PATH`, including a link that would otherwise have a non-`.omni`
name. The resolver remains local and offline; symlink, workspace-boundary,
manifest, dependency, cycle and lock-drift rules from
`PACKAGES_STDLIB_0_8_4.md` remain fail-closed.

## Dynamic and authority semantics

Package resolution remains a build-time, no-effect operation. It creates no
runtime value, allocation, resource, borrow, capability, authority or ambient
environment read. `manifest_sha256`, `semantic_source_sha256`, a package name,
or an identity never authenticate a publisher or confer authority.

## Diagnostics and negative semantics

- changing a participating `.omni` file after locking → `E_PACKAGE_LOCK`;
- adding or changing root `.env`, cache, documentation or non-Omni source
  artifacts after a v2 lock → check remains valid;
- a symlink in `src/`, unsafe entry, missing entry or legacy/new lock mismatch
  → fail closed with the existing package diagnostic family;
- `check` MUST NOT regenerate a v1 or v2 lock to obtain PASS.

## Evaluator/native and representation compatibility

The resolver produces the same closure and lock result for evaluator and
native invocation because it is a shared host build boundary. No Particle,
AST, Wave, Wire, ONME, OSM, ABI or writer version changes. Source programs are
unchanged. v1 locks remain readable solely for explicit compatibility; v2 is
the writer for the final convergence subject.

## Required evidence

1. deterministic repeated v2 lock bytes;
2. semantic `.omni` mutation causes v2 drift;
3. root `.env`, nested cache and documentation changes do not cause v2 drift;
4. a symlink within `src/` rejects before hashing;
5. an existing v1 lock validates only unchanged legacy content and is never
   rewritten by `check`;
6. explicit v2 migration remains offline and deterministic.

## Deferred

Git-aware source selection, remote registries, publisher signatures,
ignore-file execution semantics, scripts, native dependencies and any
provider-specific package policy are out of scope.
