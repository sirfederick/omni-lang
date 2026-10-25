> Distribution status: WIP / NOT_RELEASED. Technical version labels describe independent contracts, not public release certification.

# Omni Language 0.8.1-alpha.8 — A81.4 Range / Iterator Contract

**Slice:** A81.4 — Range and iteration contract  
**Current representation:** Wave16 / OMC16  
**Status:** design baseline; WIP / NOT_RELEASED.

## 1. Purpose

A81.4 closes the last Data + Language Completeness slice without inventing a parallel collection or ownership model.

The executable Core contract is:

```text
Range<u32>
Array<T,N>
View<T>
        ↓
structured for-in
```

User-defined iterator traits are deferred to `0.8.2-alpha.8`, where traits/interfaces become executable language semantics.

## 2. Range type

The initial executable range type is:

```text
Range<u32>
```

It is a Copy/Plain value with deterministic canonical content:

```text
start:     u32
end:       u32
inclusive: bool
```

Canonical layout:

```text
size      = 12 bytes
alignment = 4 bytes
offsets   = [0,4,8]
```

No heap allocation, hidden iterator object or ambient runtime state is required.

## 3. Syntax

Exclusive end:

```omni
0u32..10u32
```

Inclusive end:

```omni
0u32..=10u32
```

The expression is first-class and may be stored:

```omni
let r Range<u32> = 2u32..8u32
for x in r { ... }
```

## 4. Iteration semantics

For an exclusive range `a..b`:

```text
a, a+1, ... while current < b
```

For an inclusive range `a..=b`:

```text
a, a+1, ... while current <= b
```

Rules:

- if `start > end`, iteration is empty;
- if `start == end`, exclusive is empty and inclusive yields one element;
- inclusive `..=u32::MAX` must terminate without wraparound;
- iteration order is deterministic and ascending;
- step is exactly 1;
- negative, descending and custom-step ranges are not admitted in 0.8.1.

## 5. for-in sources

0.8.1 admits exactly:

```text
Array<T,N>
View<T>
Range<u32>
```

All three use structured loop-control semantics from A81.3.

The loop variable is immutable for each iteration. `_` may be used when the produced element is intentionally ignored.

## 6. Future iterator abstraction

0.8.1 freezes the semantic shape but does not add executable traits ahead of 0.8.2.

The next release may generalize the built-in rule through contracts equivalent to:

```text
trait Iterator<T> {
    next(...) -> Option<T>
}

trait IntoIterator<T> {
    into_iter(...) -> Iterator<T>
}
```

These names are design targets, not yet executable trait declarations.

Any 0.8.2 trait implementation MUST preserve the observable 0.8.1 behavior of Array/View/Range iteration.

## 7. Ownership and authority

Range carries values only.

It does not:

- own external resources;
- grant Authority;
- create a borrow;
- bypass Array/View lifetime rules;
- allocate;
- perform I/O.

Therefore:

```text
Value != Resource != Authority
Range != iterator authority
```

remains invariant.

## 8. Representation fence

A81.4 introduces `Range<u32>` and range-call semantics.

Therefore:

```text
current writer: Wave16 / OMC16
legacy readers: 1..15
```

Wave/OMC <=15 MUST reject:

- `Range<...>` type semantics;
- exclusive range construction;
- inclusive range construction.

Authentic Wave15/OMC15 A81.3 programs remain readable.

ONME remains ONME2 because its envelope schema is unchanged.

## 9. Deferred

Deferred beyond 0.8.1:

- generic integer ranges;
- descending ranges;
- custom step;
- iterator adapters;
- lazy map/filter/fold chains;
- user-defined iterators;
- collection iteration through traits.

Those belong to abstraction/stdlib work, not to this foundational syntax slice.
