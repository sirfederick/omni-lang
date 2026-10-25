> Distribution status: WIP / NOT_RELEASED. Technical version labels describe independent contracts, not public release certification.

# Omni package versioning policy

**Status:** `NORMATIVE`
**Versioning model:** `INDEPENDENT_COMPONENT_VERSIONING`

## 1. Scope

This policy governs version identity for Omni packages. It separates package
identity from product, representation, schema, and ABI identity. It does not
change language semantics, runtime semantics, a package release, or any
historical release receipt.

## 2. Independent version domains

The following version domains are independent:

| Domain | Examples | Compatibility authority |
| --- | --- | --- |
| `PRODUCT_VERSION` | Omni Language Core `1.1.0.0`; application subsystem `1.1.0-alpha.3` | Exact product release authority, its tag, receipt, and supported contracts |
| `PACKAGE_VERSION` | `omni.std` `0.8.4-alpha.8` | Exact package identity and package contract |
| `REPRESENTATION_VERSION` | Wave20, OMC20, ONME2, OSM2, OSMI2 | Representation reader/writer compatibility rules |
| `SCHEMA_VERSION` | `omni.package/1`, `omni.lock/1`, `omni.lock/2` | The declared schema's parser and compatibility rules |
| `ABI_VERSION` | `omni.module-invoke/1`, OMI1 | The ABI contract and its negotiated/declared identity |

A number in one domain has no ordering or compatibility meaning in another.
In particular, `Core 1.1.0.0 > omni.std 0.8.4-alpha.8` is not a valid
compatibility predicate. It does not establish a downgrade, an old runtime, or
an incompatible package.

## 3. Package identity and compatibility

A package identity is:

```text
(origin, name, version, module_path)
```

A selected identity is bound by the applicable manifest hash, source commitment,
lock schema, dependency edge, and declared package contract. Compatibility is
decided by those exact commitments and the supported schemas/contracts. Numeric
resemblance to a parent product release is never a substitute.

Package identities and their hashes identify selected bytes and contracts. They
do not authenticate a publisher, grant authority, or create a capability.

## 4. Package release semantics

`PACKAGE_VERSION` uses `major.minor.patch` with an optional prerelease suffix.
Within this package domain:

- **MAJOR** marks an incompatible public package-contract change.
- **MINOR** marks a backward-compatible public capability/API addition.
- **PATCH** marks a backward-compatible correction without an incompatible
  contract change.
- **PRERELEASE** marks a package release that has not been granted stable
  contract status.

This policy does not require product releases to use the same numbering scheme.

A Core or application subsystem product release does not automatically change any package
version. `OMNI_STD_LOCKSTEP_WITH_CORE=NO` and `CONSUMER_LOCKSTEP_WITH_CORE=NO`
refer to release numbers. A package version changes only through an explicit
package release decision.

A prerelease-to-stable transition changes package identity even when source
bytes are otherwise identical. It therefore requires its own promotion gates;
it is never a cosmetic parent-product bump.

## 5. Consumer consequences

A new package identity requires, as applicable:

1. manifest and lock regeneration;
2. offline package-resolution verification;
3. consumer compatibility verification;
4. package receipt and tag/identity handling where package release governance
   requires them; and
5. a new consumer product release when a certified consumer source changes.

A consumer may retain an existing package identity while a parent product
advances, provided its exact package commitments and supported contracts remain
valid.

## 6. Lock hash domains

`omni.lock/1` and `omni.lock/2` use different source-identity algorithms.
Their `source_sha256` values are not expected to compare equal.

- `omni.lock/1` is a legacy reader commitment over its historical package-file
  selection.
- `omni.lock/2` separately commits the manifest and computes
  `semantic_source_sha256` from sorted regular `.omni` files under `src/`, as
  frozen by `PACKAGE_LOCK_SOURCE_IDENTITY_1_0.md`.

For a source tree readable by both schemas, equivalence means each algorithm
validates its own declared commitment against the same selected source. Equality
of the two digest strings is an invalid test model.

## 7. Current `omni.std` disposition

The currently verified `omni.std` identity is
`(local:. / normalized consumer origin, omni.std, 0.8.4-alpha.8,
src/prelude.omni)` under `omni.package/1`. Core `1.1.0.0` did not alter its
stdlib source or manifest from A84. The first stable package target is `1.0.0`;
its promotion remains an explicit, open, non-blocking package program.

The alpha application subsystem `1.1.0-alpha.3` first-party distribution profile may use the
current alpha-labelled package identity. A future stable/GA application subsystem release may
not silently inherit it: it requires an explicit package-versioning disposition
and the applicable promotion or accepted alternative recorded in release
authority.

## 8. Prohibitions

No resolver, receipt, test, or consumer may:

- infer package compatibility from cross-domain numeric comparison;
- silently bump `omni.std` because Core or application subsystem changed version;
- treat a manifest, lock, or hash as authority; or
- relabel a prerelease package as stable without an explicit package release.