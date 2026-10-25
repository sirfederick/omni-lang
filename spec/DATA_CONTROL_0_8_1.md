> Distribution status: WIP / NOT_RELEASED. Technical version labels describe independent contracts, not public release certification.

# Omni Language 0.8.1-alpha.8 — A81.3 Data / Control Ergonomics

**Slice:** A81.3  
**Current representation:** Wave15 / OMC15  
**Status:** design baseline; WIP / NOT_RELEASED.

## 1. Purpose

A81.3 removes high-friction syntax/control gaps without changing the Alpha.8 ownership model or inventing the A81.4 iterator/range contract.

## 2. Tuple destructuring

Implemented Particle syntax:

```omni
let (left, right) = tuple(10u32, 20u32)
let (first, _, third) = tuple(1u32, 2u32, 3u32)
```

Rules:

- only immutable `let` destructuring is admitted;
- the right-hand side must be `Tuple<T...>`;
- pattern arity must exactly equal tuple arity;
- bindings cannot repeat;
- `_` discards one element and creates no local;
- nested destructuring is not admitted in A81.3;
- Tuple's existing no-linear-payload rule remains authoritative.

## 3. Index syntax

Implemented:

```omni
array_value[index]
view_value[index]
```

The syntax lowers to the existing checked operations:

```text
Array<T,N>[i] -> array.get(Array<T,N>,i)
View<T>[i]    -> view.get(View<T>,i)
```

Therefore:

- index type is `u32`;
- bounds behavior is unchanged;
- no unchecked indexing exists;
- Text is not byte-indexable through `[]`;
- mutable indexing/assignment is not introduced.

## 4. break / continue

Implemented structured loop control:

```omni
break
continue
```

for `for condition { ... }` and `for item in iterable { ... }`.

Rules:

- only the innermost loop is targeted;
- labels are not admitted;
- break-with-value is not admitted;
- `continue` on for-each advances to the next element;
- use outside a loop is `E_LOOP_CONTROL`;
- a break/continue edge cannot silently consume an outer Result;
- a break/continue edge cannot move/release outer ownership relative to the loop-entry state;
- a live local Resource cannot be abandoned across loop control.

These restrictions are intentionally fail-closed until A8.3 general Drop/CleanupGraph exists.

## 5. Pattern wildcard

Payload bindings may use `_`:

```omni
match result {
  Ok(_) { ... }
  Err(e) { ... }
}
```

The wildcard creates no local binding. This applies to Result, Option, and enum payload arms.

A81.3 does not claim full literal/nested pattern matching.

## 6. Representation fence

A81.3 introduces executable statement forms and pattern meaning that were absent in Wave14/OMC14.

Therefore:

```text
current writer: Wave15 / OMC15
legacy readers: 1..14
```

Wave/OMC <=14 MUST reject:

- tuple destructuring statements;
- break/continue;
- canonical index-call representation;
- wildcard payload pattern semantics.

Wave14/OMC14 Unicode programs without A81.3 semantics remain readable.

## 7. Deferred to A81.4

A81.4 owns:

- range syntax;
- Range semantics;
- iterator protocol contracts;
- interaction of ranges with Array/View and future collections.

No provisional range object is introduced here.
