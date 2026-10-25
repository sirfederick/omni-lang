> Distribution status: WIP / NOT_RELEASED. Technical version labels describe independent contracts, not public release certification.

# Omni Type Identity — canonical semantic TypeID

**Current tooling schema:** `omni.type-descriptor/2`  
**Canonical TypeID domain:** `omni.type/1`  
**Historical tooling schema:** `omni.type-descriptor/1`  
**Status:** Alpha.8 reconciliation of the inherited type-descriptor seam with Alpha.7.1 OSNMF identity.

## 1. One semantic type, one TypeID

Omni requires one canonical answer to:

> what semantic type is this?

That answer must be independent of a C++ enum ordinal, LLVM/native layout, process address, source/import alias, and whether the caller is CLI tooling or OSNMF.

The canonical TypeID is:

```text
canonical_material = canonicalTypeIdentity(resolved_type)

TypeID =
  "sha256:" +
  SHA256(
    "omni.type/1"
    + "\n"
    + canonical_material
  )
```

The exact same implementation function, `semanticTypeId(...)`, is consumed by `omni type describe` and OSNMF type nuclei. No subsystem may mint a different current identifier and call it `type_id`.

## 2. Canonical identity material

Examples:

```text
u32
Borrow<Buffer>
BorrowMut<Buffer>
Array<u32,4>
Tuple<u8,u32,bool>
record:inventory.User
enum:catalog.Status
```

Display spelling and canonical identity are separate for nominal types:

```text
display name       = User
canonical identity = record:inventory.User
```

A context-free spelling such as `User` cannot mint a persistent nominal TypeID because its module-qualified identity is unresolved. CLI `type describe/layout` therefore fails closed for unresolved nominal types.

## 3. Tooling descriptor v2

`omni type describe` emits `omni.type-descriptor/2`.

Example:

```json
{
  "schema": "omni.type-descriptor/2",
  "name": "BorrowMut<Buffer>",
  "kind": "borrowed-resource-mutable",
  "ownership": "borrowed-exclusive-mutable",
  "portable_address": false,
  "type_identity_domain": "omni.type/1",
  "canonical_identity_material": "BorrowMut<Buffer>",
  "type_id": "sha256:...",
  "legacy_descriptor_schema": "omni.type-descriptor/1",
  "legacy_descriptor_identity_material": "type|BorrowMut<Buffer>",
  "legacy_descriptor_id": "sha256:..."
}
```

Integer width/signedness/arithmetic metadata remains explicit. That metadata describes integer semantics, while the current `type_id` uses the same `omni.type/1` domain as OSNMF.

## 4. Migration from descriptor/1

Alpha.2 tooling derived a descriptor-local hash from material such as:

```text
integer|i64|bits=64|...
type|Array<u32,4>
```

Alpha.7.1 later established the module-safe `omni.type/1` TypeID inside OSNMF. Both values were historically surfaced as `type_id`, which violated the one-semantic-type/one-TypeID rule.

Alpha.8 repairs this without rewriting persisted Alpha.7.1 identity:

- **OSNMF `omni.type/1` IDs remain unchanged**;
- descriptor v2 `type_id` adopts that canonical OSNMF ID;
- the old descriptor hash is preserved as `legacy_descriptor_id`;
- `legacy_descriptor_identity_material` records exactly what descriptor v1 hashed.

`legacy_descriptor_id` is migration metadata, not a second current TypeID.

## 5. Identity is not representation

```text
type_id   = semantic type identity
layout_id = representation identity under a versioned layout schema
```

A layout match is not object identity, ownership or authority. TypeID itself is not an allocation identity.

## 6. Borrow / ownership identity

Borrow classes are distinct semantic types:

```text
Borrow<Buffer>    != BorrowMut<Buffer>
shared TypeID     != exclusive TypeID
```

Their tooling descriptors remain explicitly non-addressable:

```text
Borrow<T>
  ownership        = borrowed-shared-readonly
  portable_address = false

BorrowMut<T>
  ownership        = borrowed-exclusive-mutable
  portable_address = false

Resource<T>
  ownership        = owned-resource-opaque
  portable_address = false
```

## 7. Systemic-memory seam

OSNMF may associate resolved entities with TypeID, ContentID, ContractID, provenance and lineage. None grants object ownership, allocation reachability, capability, runtime Authority or borrow lifetime.

```text
semantic Type ─── TypeID
                  │
runtime object ─── Object/Resource identity
                  │
authority ──────── explicit Authority/capability protocol
```

These domains remain orthogonal.

## 8. Historical systemic seam compatibility

The Alpha.2 contract remains true under descriptor v2:

- `type_id` **does not grant authority**;
- `type_id` **does not identify a runtime object**;
- `type_id` **does not imply persistence**.

`SisNervCent` remains the signalling/observation plane. It may observe or route references to semantic TypeID, but it cannot reinterpret TypeID as ownership, object identity, capability or authorization.

## 8. Security invariants

- same resolved semantic type → same TypeID across CLI and OSNMF;
- different canonical types → different identity material;
- unresolved nominal identity fails closed;
- TypeID is not ObjectID or ResourceID;
- TypeID is not allocation address;
- TypeID is not capability or Authority;
- TypeID does not prove truth/provenance/persistence by itself;
- descriptor exposes no raw process pointer.

The v2 reconciliation is a tooling/identity-surface repair. It does not change Wave12/OMC12, OSM2/OSMI2 or ONME2 schemas.
