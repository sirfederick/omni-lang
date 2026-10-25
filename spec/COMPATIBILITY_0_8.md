> Distribution status: WIP / NOT_RELEASED. Technical version labels describe independent contracts, not public release certification.

# Omni 0.8 Compatibility Contract — Alpha.8 Development

**Target:** `0.8.0-alpha.8`  
**Released base:** `0.7.0-alpha.7.1`

## Source compatibility

Alpha.8 starts by admitting every valid Alpha.7.1 program unless that program relied on behavior explicitly documented as undefined/tooling-only.

New ownership rules MUST NOT silently reinterpret existing Copy values as move-only.

The restricted Alpha.7.1 `Resource<Buffer>`, `Borrow<Buffer>` and `View<T>` behavior remains valid until an explicit migration spec replaces a restriction with a more general rule.

## Representation compatibility

Current A8.2 representation:

```text
Wave writer   = 12
Wire writer   = OMC12
legacy reader = Wave/OMC 1..11
OSM writer    = OSM2
OSMI writer   = OSMI2
ONME writer   = ONME2
OCAP          = OCAP1
```

The bump to Wave12/OMC12 was triggered by executable `BorrowMut<T>` / `borrow_mut(...)` semantics and now also fences A8.2b **persistent local loan storage**. Historical Wave11/OMC11 may still represent the already-supported temporary shared `borrow(resource)` use; they MUST reject a local `let/var` whose initializer materializes `borrow(...)` / `borrow_mut(...)` as a persistent loan.

Authentic Wave11/OMC11 fixtures remain compatibility gates. Historical readers are never permitted to infer newer ownership/borrow/unsafe semantics.

## Identity compatibility

Canonical nominal identity introduced by Alpha.7.1 remains authoritative.

Alpha.8 adds ownership/lifecycle properties to type contracts without making:

```text
TypeID == owner
TypeID == allocation
TypeID == Authority
```

## Systemic compatibility

OSNMF remains AI-independent. Ownership/loan metadata added to Structural Memory is descriptive/compiler-authoritative memory; it does not expose raw addresses or mint runtime Authority.

## Migration rule

A stricter safety rule may reject a program only when the previous behavior cannot be proven safe under an already-documented invariant or when the new feature is explicitly fenced by the Alpha.8 representation/spec contract.

No silent schema reinterpretation is permitted.
