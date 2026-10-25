> Distribution status: WIP / NOT_RELEASED. Technical version labels describe independent contracts, not public release certification.

# Omni marker traits — 0.8.2

**Status:** `FROZEN_FOR_IMPLEMENTATION` for the first A82.1 slice.

This slice introduces nominal, compile-time-only marker traits:

```omni
trait Serializable {}
impl Serializable for u32 {}
func identity<T:Serializable>(value T) T { return value }
```

Trait names are local to their declaring module in this slice. An implementation
requires a declared local trait and one concrete type. At most one implementation
for the same `(trait, concrete type)` exists; a duplicate is
`E_TRAIT_COHERENCE`. A generic instantiation whose concrete argument lacks the
required implementation fails `E_GENERIC_CONSTRAINT`.

Marker traits have no methods, associated types, inheritance, specialization,
trait objects, dynamic dispatch, automatic implementation, cross-module lookup,
runtime representation, serialization or authority effect. Generic templates are
monomorphized and rechecked before executable Wave/Wire emission, so the emitted
program contains only the concrete specialization; source trait declarations do
not become a runtime capability or type-erasure ABI.

The slice must prove source check/evaluation, unsatisfied/unknown/duplicate
negatives, and a Wave round trip of the resulting concrete program.
