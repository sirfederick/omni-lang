> Distribution status: WIP / NOT_RELEASED. Technical version labels describe independent contracts, not public release certification.

# Omni IR / Wave / Wire — Versioned Representation Contract

**Inherited introduction:** Omni Language 0.2.0-alpha.6 introduced Wave11 / OMC11 for `for-each`.  
**Current textual writer:** Wave22 for rechecked authoring capsules (see `GENERATED_PROVENANCE_CANDIDATE.md`); otherwise Wave21 for programs with a returned `Borrow`/`BorrowMut`
(`BORROW_RETURN_REGIONS_CANDIDATE.md`), a `bit.*` intrinsic, an `Option<Resource>`, a machine
primitive (`raw.`/`port.`/`cpu.`/`atomic.`/`tls.`/`pcpu.`), a nominal-resource builtin or type, or a declared
machine capability (`HARDWARE_REPRESENTATION_FENCE_CANDIDATE.md`); Wave20 for A86 hosted-effect
programs; Wave19 for A85 programs; Wave18 otherwise.
**Current binary logical writer:** OMC21 for the same programs as Wave21; OMC20 for A86
hosted-effect programs; OMC19 for A85 programs; OMC18 otherwise.
**Physical prefix:** `OMCX` + little-endian `u32(version)`.

## 1. Canonical rule

Particle, Wave and Wire represent the same checked **closed** program. Writers emit the current schema. Historical readers preserve only the semantics admitted by their declared version.

A new executable semantic form receives a new representation version when an older reader could omit, reinterpret or fail to enforce its invariant. Version metadata is never authority and cannot be used to smuggle newer semantics under an older schema.

## 2. Generic lowering boundary

Legacy concrete formats omit generic templates/type parameters. Candidate Wave22/OMC22 authoring capsules preserve their normalized Particle source for mandatory rechecking. Before Wave/Wire emission, every used generic call is deterministically monomorphized to a concrete function. Wave/Wire therefore do not encode an open `T`, generic constraint environment, runtime type dictionary or type-erasure payload.

## 3. Historical Wave11 / OMC11 — Alpha.6

Alpha.6 advanced Wave10/OMC10 → Wave11/OMC11 for the `for-each` statement.

Wave11 begins:

```text
(omni-wave 11 ...)
```

and encodes iteration as:

```text
(for-each item iterable (block ...))
```

Wave10 and older reject `for-each` with `E_VERSION`.

OMC11 uses:

```text
"OMCX" | u32_le(11) | body...
```

OMC11 appends the `ForEach` statement tag after existing statement tags. OMC10 cannot decode/claim `ForEach`; a relabeled OMC11 body fails closed.

Wave11/OMC11 remain historical compatibility formats in Alpha.8. They continue to admit the Alpha.7.1 temporary shared `borrow(resource)` usage that already existed before Alpha.8.

## 4. Current Wave12 / OMC12 — Alpha.8

Alpha.8 A8.2 introduces executable `BorrowMut<T>` / `borrow_mut(...)` semantics and A8.2b persistent local loan storage. These semantics cannot be claimed by Wave11/OMC11 without changing the safety contract, therefore the writer advanced to Wave12/OMC12.

Current Wave begins:

```text
(omni-wave 12 ...)
```

Current Wire uses:

```text
"OMCX" | u32_le(12) | body...
```

Wave12/OMC12 preserve all Wave11/OMC11 forms and add the Alpha.8 loan semantics.

The downgrade fence is intentionally asymmetric:

- historical temporary shared `borrow(resource)` remains valid under Wave11/OMC11;
- `BorrowMut<T>` / `borrow_mut(...)` require Wave12/OMC12;
- a local `let/var` initialized directly from `borrow(...)` or `borrow_mut(...)` is an A8.2b persistent loan and requires Wave12/OMC12;
- relabeling a Wave12/OMC12 persistent loan as 11 MUST fail with `E_VERSION`.

## 5. Extended Wire versions

Legacy OMC1..OMC9 use their historical physical forms. Extended profiles use:

```text
"OMCX" | u32_le(version) | body...
```

The current reader admits supported historical versions through OMC12 and applies version-specific semantic fences after deserialization. Unknown extended versions fail closed with `E_VERSION`.

## 6. Trust / resource limits

Wire is data, not authority. Readers bound input size, depth/counts and string lengths before allocation/iteration. Deserialized programs are semantically revalidated, including capabilities, ownership/loan rules and version gates.

## 7. Native ABI

LLVM lowering, internal borrow/resource handles and generated symbol names are implementation details, not a stable public ABI. Core exposes no portable raw pointer or runtime generic ABI in the current Alpha.8 foundation.

## 8. Historical compatibility

Self-contained fixtures `reference/compat/legacy1` through `legacy11` exercise historical reader compatibility. Admitted historical programs canonicalize through the current compiler to Wave18.

The compiler MUST prove both directions of the A8.2 compatibility boundary:

1. authentic historical temporary shared-borrow programs remain admitted under Wave11/OMC11;
2. Alpha.8-only mutable or persistent loan semantics cannot be relabeled as Wave11/OMC11.


## Wave13 / OMC13 — f32/f64

`0.8.1-alpha.8` introduces executable IEEE floating-point semantics behind a new representation fence:

```text
Wave writer = 13
Wire writer = OMC13
legacy readers = 1..12
```

Float values reuse the existing Number node/wire payload shape but interpret its 64-bit payload as canonical raw IEEE bits according to the attached type:

- `f32`: low 32 bits are IEEE-754 binary32;
- `f64`: all 64 bits are IEEE-754 binary64.

This is semantically distinct from integer payload interpretation. Wave/OMC <=12 MUST reject `f32`, `f64`, float literals and float casts. Relabeling a Wave13/OMC13 program as an older representation must fail closed.

Particle literals require explicit `f32` or `f64` suffixes. Decimal spelling is authoring syntax; Wave/Wire preserve canonical bits.

NaN follows IEEE comparison behavior:

```text
NaN == x  -> false
NaN != x  -> true
NaN < x   -> false
NaN <= x  -> false
NaN > x   -> false
NaN >= x  -> false
```

Wrapping/saturating integer operators and `%` are not float operators.


## Wave14 / OMC14 — Unicode Char/Text

A81.2 advances the current executable writer to:

```text
Wave14 / OMC14
legacy executable readers 1..13
```

Wave14/OMC14 adds the semantic vocabulary for:

- `Char` as a distinct Unicode scalar type with u32 physical representation;
- `char.from_u32` and `char.codepoint`;
- `text.from_char`;
- explicit byte/scalar length separation;
- scalar-indexed Text access;
- explicit `text.equals` exact Text equality with no implicit normalization.

Wave13/OMC13 remains valid for authentic A81.1 float semantics.

Unicode semantics MUST fail closed if relabeled as Wave13/OMC13 or earlier. ONME remains ONME2 and carries the current Wave payload.


## Wave15 / OMC15 — A81.3 Data/Control ergonomics

A81.3 advances the current executable writer:

```text
Wave15 / OMC15
legacy executable readers 1..14
```

New executable statement vocabulary:

- `let-tuple` for flat immutable Tuple destructuring;
- `break`;
- `continue`.

Particle index syntax `seq[index]` canonicalizes to the existing checked Array/View access semantics. Wildcard payload binding `_` creates no local.

Wave/OMC <=14 MUST reject A81.3 statement/pattern semantics. Authentic Wave14/OMC14 Unicode programs remain readable. ONME remains ONME2 and carries the current Wave payload.


## Wave16 / OMC16 — A81.4 Range / Iterator

A81.4 advances the current executable writer:

```text
Wave16 / OMC16
legacy executable readers 1..15
```

New semantic vocabulary:

- `Range<u32>` as a first-class Copy/Plain value;
- exclusive range construction `a..b`;
- inclusive range construction `a..=b`;
- structured `for-in` over stored or inline Range values.

The canonical Range value contains start, end and inclusive mode. No hidden heap iterator is serialized.

Wave/OMC <=15 MUST reject Range type/construction semantics. Authentic Wave15/OMC15 A81.3 programs remain readable. ONME remains ONME2 and carries the current Wave payload.

## Wave17 / OMC17 — A82 immediate closures

The A82 closure-call representation advances the executable writer to:

```text
Wave17 / OMC17 (physical Wire header: OMCX + little-endian u32(17))
legacy executable readers 1..16
```

`closure-call` stores its explicit typed parameters, result type, ordered Copy
capture names, body, and ordered immediate-call arguments. It is not a closure
object encoding: no heap identity, reference capture, dynamic dispatch, or
serialized authority is introduced. Wave/OMC <=16 MUST reject closure-call;
authentic earlier payloads remain readable. ONME2 continues to carry the
current Wave payload.

## Wave18 / OMC18 — A83 proven Places and reborrows

The A83 memory/lifecycle contract advances the executable writer to:

```text
Wave18 / OMC18 (physical Wire header: OMCX + little-endian u32(18))
legacy executable readers 1..17
```

Wave18/OMC18 fences checker-proven `Resource<Buffer>` record-field Places,
parent-tracked reborrows and generated structured-cleanup obligations. The
payload remains declarative: a field path, loan plan or cleanup plan is not
capability metadata, and deserialization always rebuilds and checks the
ownership/loan proof. Wave/OMC <=17 MUST reject a resource-bearing record field,
reborrow or cleanup-bearing scope rather than silently treating it as an ordinary
aggregate or root loan. A relabeled OMC18 payload is rejected with `E_VERSION`;
malformed field paths, parent relationships and cleanup obligations are
revalidated and rejected fail-closed.

ONME remains ONME2 and carries the fenced Wave18 payload; OSM2, OSMI2 and OCAP1
are unchanged.

## Wave19 / OMC19 — A85 structured task and channel capabilities

A85 task scopes, `spawn`, `join`, `cancel`, logical `deadline`, and bounded
channel operations need a representation fence because old readers cannot
preserve the lexical child/handle and queue-bound invariants. A program using
one of those forms writes Wave19 / OMC19 with physical header `OMCX + u32le(19)`.
Programs without an A85 form retain Wave18 / OMC18 output to avoid relabelling
historical semantics.

Readers 1..18 reject A85 executable forms with `E_VERSION`. A downgrade must
never erase an owned child handle, cancellation/deadline outcome, channel
capacity, close state, or transfer proof. ONME remains ONME2 and wraps the
version-fenced Wave payload; OSM2, OSMI2 and OCAP1 remain unchanged.

## Wave20 / OMC20 — A86 hosted-effect requests

A86 `host.read`, `host.write`, `host.process`, `host.tcp`, and `host.ffi`
requests advance the executable writer to Wave20 / OMC20 with physical header
`OMCX + u32le(20)`. The payload records only the checked request expression and
ordinary values. It never serializes `HostAuthority`, live host grants,
credentials, handles, or an authorization decision.

Readers 1..19 reject these requests with `E_VERSION`. Deserialization restores
the request and the checker re-establishes its static capability contract; a
fresh OHP policy decision is still required immediately before the hosted
effect. Programs without hosted requests keep the smallest current compatible
writer. ONME2, OSM2, OSMI2, and OCAP1 are unchanged.


## 1.3 candidate: rechecked authoring capsules (Wave22 / OMC22)
See `GENERATED_PROVENANCE_CANDIDATE.md` for the frozen grammar, limits and migration.
Programs requiring generic/trait lowering preserve normalized pre-lowering Particle
in an authoring capsule. Readers recheck and regenerate it; generated names or
serialized flags never grant import/visibility privileges. Programs without these
features keep their previous minimum writer. ONME2 is unchanged. Intermediate
candidate generated snapshots without provenance may require regeneration from source.
