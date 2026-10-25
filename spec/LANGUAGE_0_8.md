> Distribution status: WIP / NOT_RELEASED. Technical version labels describe independent contracts, not public release certification.

# Omni Language 0.8 — Enterprise Memory & Authority Foundation

**Target:** `0.8.0-alpha.8`  
**Status:** historical Alpha.8 language boundary, derived from certified `0.7.0-alpha.7.1`; this status is not an active execution roadmap.

Alpha.8 does not add a new cognitive layer. Its purpose is to establish the first language-wide generic ownership and shared/exclusive Loan foundation beneath the Living Computational System architecture.

Alpha.8 is an **enterprise foundation**, not the complete general-purpose enterprise language.

## Inherited unchanged

- Particle plus Wave12 / OMC12 current executable representation; Wave/OMC 1..11 remain historical compatibility readers;
- fixed-width integer semantics;
- ADTs and exhaustive match;
- Tuple / Array;
- read-only View;
- generic functions / constraints / UFCS / Array-View iteration;
- OSNMF, OSM2/OSMI2, ONME2, Neural Epoch/Pulse;
- OCAP and proposal governance;
- AI-independent deterministic execution.

## Alpha.8 executable surface

### Generic ownership authority

- generic `OwnershipLedger` replaces Buffer-specific state authority;
- Copy / Move / Resource ownership classes;
- Uninitialized / Live / Moved / Dropped state model;
- supported branch/loop/Result/Option ownership-flow checks;
- live Resource obligations checked across supported return/scope exits;
- ordinary Copy values remain non-linearized.

### Root Loan graph

- shared `Borrow<T>`;
- exclusive `BorrowMut<T>`;
- `borrow_mut(...)`;
- persistent immutable local loans created directly by `borrow` / `borrow_mut`;
- root `Place` + `Origin` + `Loan` + `Region` records;
- shared/exclusive overlap checking at root identity;
- move/drop conflict detection while a Loan remains live;
- statement-level last-use retirement;
- conservative nested-control-flow lifetime;
- borrow diagnostics and fail-closed unsupported alias/reborrow paths.

## Representation

```text
Wave writer = 12
Wire writer = OMC12
legacy executable readers = 1..11
OSM = OSM2
OSMI = OSMI2
ONME = ONME2
OCAP = OCAP1
```

Persistent local Alpha.8 loans may not be smuggled through Wave11/OMC11. Historical temporary shared-borrow behavior remains compatible where explicitly specified.

## Explicit Alpha.8 boundaries

The following are **not** executable Alpha.8 semantics:

- field-sensitive Places/disjoint field borrowing;
- general reborrow;
- general borrow return/escape;
- deterministic compiler-inserted Drop for general owned values;
- allocator/`Owned<T>`/typed OOM;
- explicit unsafe/raw-pointer surface;
- mutable `Slice<T>`;
- runtime scoped Authority;
- nominal generic lifecycle propagation;
- behavioral traits/method ownership contracts.

The compiler must reject unsupported forms rather than approximate them unsafely.

## Future-scope boundary

Those boundaries remain outside Alpha.8. Their release sequencing is governed by the active roadmap.

Execution-roadmap references:

- `docs/OMNI_LANGUAGE_1_0_MASTER_PLAN.md`.

The transfer is a release-scope decision and does not assert that Alpha.8 implements the transferred semantics.

## Conformance

Alpha.8 conformance is defined by `spec/CONFORMANCE_0_8.md`.

Canonical exact-source gate:

```bash
./tools/ci-mainline-full.sh
```

No `core-v0.8.0-alpha.8` promotion until that gate succeeds on the exact candidate SHA.

## Non-goals for Alpha.8

- mandatory garbage collector;
- default reference counting;
- multi-node OSNMF;
- new LLM/provider dependency;
- raw pointers in ordinary safe code;
- full async/concurrency model;
- stable public C ABI;
- packages/stdlib/application-platform completeness;
- production-ready 1.0 claim.
