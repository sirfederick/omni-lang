> Distribution status: WIP / NOT_RELEASED. Technical version labels describe independent contracts, not public release certification.

# Omni Memory & Authority 0.8

**Target:** `0.8.0-alpha.8`  
**Status:** normative Memory & Authority architecture contract. The Alpha.8 executable conformance subset closes at generic ownership state + root shared/exclusive Loans; later sections explicitly marked Alpha.9 define the continuation contract rather than claiming Alpha.8 implementation.

## 1. Constitutional invariants

1. Value, Resource, storage ownership and Authority are distinct.
2. Safe code cannot use a value after its ownership has moved.
3. Safe code cannot drop/move an origin while a conflicting Loan is live.
4. Overlapping Places admit either shared readers or one exclusive mutable borrower.
5. A Borrow contains no portable raw-address authority.
6. Cleanup of a live owned/resource obligation occurs exactly once.
7. Allocation failure is recoverable by default.
8. Unsafe code cannot mint runtime authority.
9. Runtime authority cannot be inferred from TypeID, layout, OSNMF identity or ownership.
10. AI/cognitive components receive no special exemption from these rules.

Canonical shorthand:

```text
Value != Resource != Authority
Borrow != pointer
Identity != authority
Unsafe != authority
```

These are semantic separations, not slogans: no transition between the right-hand domains exists without an explicit checked operation/protocol.

## 2. Core semantic entities

```text
Place
  storage path known to the checker

Origin
  symbolic storage identity underlying a Loan

Loan
  (origin, place, kind, region)

BorrowKind
  Shared | Exclusive

OwnershipState
  Uninitialized
  Live
  Moved
  Dropped

DropObligation
  value/resource that must be discharged exactly once
```

The implementation may optimize these structures but must preserve their semantics.

## 3. Copy vs move

Type properties determine whether duplication is legal.

### Copy values

A Copy value can be duplicated without invalidating the source.

### Move values

A noncopyable/move value has one active owner.

Initial Alpha.8 transfer syntax generalizes the existing operation:

```omni
let next T = move(current)
```

After the move, use of `current` is rejected until a permitted reinitialization.

Copyability is a property of the complete concrete type. A product containing a move-only field is not implicitly Copy.

## 4. Borrows

### Shared

```text
Borrow<T>
```

permits read-only access. Multiple shared Loans over overlapping Places may coexist.

### Exclusive

```text
BorrowMut<T>
```

permits mutation and excludes every other overlapping Loan for its region.

### Origin access while borrowed

- while a shared Loan is live: origin mutation/move/drop is rejected;
- while an exclusive Loan is live: direct origin access that conflicts with the Loan is rejected;
- after the region ends: origin access resumes if it remains Live.

## 5. Region inference

A region is compiler dataflow, not necessarily a lexical block.

For the current A8.2b executable slice:

- regions are intra-function;
- immutable local loan bindings created directly by `borrow(origin)` / `borrow_mut(origin)` are admitted;
- last use may end a local loan before lexical scope end;
- the current implementation computes that early end at **statement granularity** by future-use analysis;
- outer loans remain conservatively live while a nested control-flow statement is being checked;
- borrow parameters are admitted;
- returned borrows, aggregate-stored/captured borrows and local alias/reborrow construction remain rejected until their origin relationships are explicitly represented.

This is a safe non-lexical-lifetime foundation, not yet the more complete region/reborrow model transferred to Alpha.9 A9.0. No hidden runtime reference counting is required to implement regions.

## 6. Place overlap

A8.2b materializes **root Places** first: every persistent Resource loan is bound to an Origin/root Place and overlap is exact by root identity.

Alpha.9 A9.0 extends this to field-sensitive struct Places:

```text
x.left
x.right
```

which may then be proven disjoint. Until Alpha.9 A9.0 implements that extension, field/element projections do not weaken Alpha.8 root-level exclusivity.

Dynamic array indices remain conservatively overlapping the aggregate until a separately proven index/slice disjointness rule exists.

## 7. Reborrow

**Alpha.9 A9.0 continuation; not implemented by Alpha.8.**

A shorter Loan may derive from an existing Loan if it does not increase authority:

- shared → shared is allowed;
- exclusive → shared is allowed for a shorter region while exclusive mutation is suspended as required;
- exclusive → exclusive is allowed as an exclusive reborrow;
- shared → exclusive is forbidden.

## 8. Owned<T> and heap

`Owned<T>` is unique ownership of dynamic storage containing a `T`.

Portable allocation is allocator-explicit:

```text
allocate(allocator, value)
    -> Result<Owned<T>, AllocError>
```

Exact Particle surface is an Alpha.9 A9.0 design/implementation responsibility, but these safety semantics remain normative for the eventual feature:

- no implicit duplicate owner;
- allocator identity is not value authority;
- OOM is typed recoverable failure by default;
- Owned destruction recursively discharges contained Drop obligations.

## 9. Deterministic cleanup

The compiler inserts destruction on every supported control-flow exit for a still-live Drop obligation.

An explicit `defer` facility may sequence cleanup work, but cannot make a moved/dropped value live again.

Cleanup ordering is deterministic and specified before user-defined Drop hooks become general.

## 10. Unsafe boundary

Raw pointers, unchecked memory views and unsafe FFI operations are outside ordinary safe semantics.

Alpha.9 A9.0 requires a lexically visible unsafe boundary before exposing those operations. Alpha.8 exposes no general unsafe/raw-pointer language surface.

Unsafe suppresses a proof obligation only for operations explicitly classified unsafe. It does not suppress:

- capability checks;
- runtime authority checks;
- systemic artifact integrity checks.

## 11. Runtime Authority

The target authority model is dual-gated:

```text
compile-time capability requirement
        +
runtime scoped Authority value
        ↓
sensitive operation
```

An Authority value has at minimum:

- capability kind;
- scope/selector;
- issuer/provenance;
- generation/revocation identity where the host profile supports it.

Authority values are not serializable into ordinary Wire as ambient permission unless a separate secure envelope contract explicitly allows it.

## 12. OSNMF integration

Structural Memory may record:

- copy/move/drop properties;
- function ownership conventions;
- borrow relationships in analyzable IR;
- allocator requirements;
- authority requirements.

OSNMF must not persist process raw addresses as identity.

Operational Memory may record aggregate allocation pressure and authority failures under policy, without making observations authoritative.

## 13. Representation fencing

A8.2 introduced executable `BorrowMut<T>` / `borrow_mut(...)` semantics and therefore advanced the executable schema to **Wave12 / OMC12**. A8.2b keeps that schema and additionally classifies local storage of `borrow(...)` / `borrow_mut(...)` as Wave12/OMC12 semantics.

Wave11 / OMC11 remain historical readers/fixtures. They may continue to admit the historical temporary shared-borrow use, but MUST reject persistent local loans and every other Alpha.8-only semantic form rather than reinterpret them.

Any later executable form that cannot be represented without ambiguity MUST again advance the executable schema atomically with:

- writer;
- reader;
- compatibility fixture;
- downgrade-negative tests;
- ONME mapping;
- spec update.

## 14. Historical scheduling note and deferred work

`MEMORY_LIFECYCLE_0_8_3.md` and `ADR-0068-a83-memory-lifecycle-scope.md`
supersede the historical Alpha.9 scheduling labels in sections 6–10 for their
explicit A83 subset. They do not broaden any other deferred semantic.

- general borrow return/origin parameters;
- shared/reference-counted ownership;
- cycle collection;
- async suspension carrying borrows;
- closure capture lifetimes;
- raw-pointer arithmetic;
- general FFI;
- concurrent Send/Sync-like rules;
- mutable Slice until exclusive borrowing is certified;
- general `Owned<T>`, raw/unsafe and runtime Authority remain deferred pending a
  later versioned contract.
