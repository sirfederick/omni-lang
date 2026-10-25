> Distribution status: WIP / NOT_RELEASED. Technical version labels describe independent contracts, not public release certification.

# Omni Language 0.8.1-alpha.8 — Data + Language Completeness

**Status:** design baseline; WIP / NOT_RELEASED.
**Predecessor:** `0.8.0-alpha.8 — Enterprise Memory & Authority Foundation`.
**Tranche:** A8-T1 Language Usability Foundation.

## Purpose

0.8.1 closes ordinary data/control gaps that block real programs while preserving the Alpha.8 ownership and authority invariants.

## Planned semantic slices

### A81.1 — Floating point
- `f32` and `f64`;
- IEEE-754 representation;
- explicit literal typing;
- deterministic casts;
- NaN/Inf comparison and serialization rules;
- evaluator/native/Wave/Wire agreement.

### A81.2 — Unicode/Text
- Unicode scalar/code-point policy;
- explicit bytes vs scalar vs grapheme distinction;
- fallible Text/Bytes conversion;
- normalization policy;
- no implicit lossy conversion.

### A81.3 — Data/control ergonomics
- flat immutable Tuple destructuring;
- native checked Array/View index syntax;
- `break` / `continue`;
- wildcard payload pattern `_`;
- strict loop-control Result/ownership safety.

Range syntax and the iterator/range contract remain in A81.4.

### A81.4 — Range/iterator contracts
- first-class `Range<u32>`;
- exclusive `a..b` and inclusive `a..=b`;
- deterministic ascending step-1 semantics;
- `for-in` over Array/View/Range;
- iterator trait shape frozen for 0.8.2 generalization;
- no ownership or lifetime bypass.

## Dynamic collection dependency

`Vector<T>`, `Map<K,V>`, and `Set<T>` are part of A8-T1 data completeness, but their general heap-backed implementation is gated by the allocator/`Owned<T>`/Drop work in `0.8.3-alpha.8`.

0.8.1 may freeze collection API/type contracts but MUST NOT introduce an ambient hidden heap or a second ownership model.

## Inherited invariants

```text
Value != Resource != Authority
Borrow != pointer
Identity != Authority
Unsafe != Authority
Observation != Authority
AI proposal != execution
```

## Representation rule

A81.1 introduced executable IEEE `f32/f64` semantics at Wave13/OMC13. A81.2 adds Unicode `Char` and scalar-aware Text semantics and advances the current writer again:

```text
Wave writer = 16
Wire writer = OMC16
legacy readers = 1..15
ONME = ONME2
OSM/OSMI = OSM2/OSMI2
```

Wave12/OMC12 remains the certified Alpha.8 representation. Wave13/OMC13 remains the A81.1 float representation; Wave14/OMC14 the A81.2 Unicode representation; Wave15/OMC15 the A81.3 data/control representation. A81.4 Range semantics are fenced from Wave/OMC <=15. Historical readers remain read-only compatibility surfaces.

## Promotion gate

Every candidate must:
1. pass `core/tools/verify_alpha8_release_ssot.py`;
2. pass the complete inherited normative matrix;
3. add dedicated 0.8.1 tests for every landed semantic;
4. preserve evaluator/native parity;
5. preserve downgrade/fail-closed behavior;
6. pass mutation, sanitizer, reproducibility and final package integrity gates.


## Unicode/Text authority

Normative A81.2 semantics are defined in `spec/UNICODE_TEXT_0_8_1.md`. No implicit Unicode normalization or approximate grapheme algorithm is admitted in Language Core.


## Data/Control authority

Normative A81.3 semantics are defined in `spec/DATA_CONTROL_0_8_1.md`. Range syntax remains deferred to A81.4 so it lands with one coherent Range/Iterator contract rather than as provisional syntax.


## Range/Iterator authority

Normative A81.4 semantics are defined in `spec/RANGE_ITERATION_0_8_1.md`. User-defined iterator traits are intentionally deferred to 0.8.2 so the abstraction layer generalizes one existing iteration contract rather than creating a parallel runtime model.
