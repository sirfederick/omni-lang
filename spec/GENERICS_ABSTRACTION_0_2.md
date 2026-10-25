> Distribution status: WIP / NOT_RELEASED. Technical version labels describe independent contracts, not public release certification.

# Omni Generics & Abstraction Foundation — 0.2 alpha.6

**Language:** Omni Language 0.2.0-alpha.6  
**Representation:** Particle templates → closed Wave11 / logical OMC11 specializations.  
**Status:** normative for the implemented alpha.6 subset.

## 1. Goal

Alpha.6 introduces abstraction mechanisms without adding hidden heap ownership, dynamic dispatch, type erasure, or an implicit runtime. The design is deliberately compile-time-first so it composes with Omni's existing type/capability/resource checks.

## 2. Generic functions

A generic function declares one or more type parameters:

```omni
func add<T:Integer>(a T, b T) T { return a + b }
```

Calls supply explicit type arguments in alpha.6:

```omni
let n u32 = add<u32>(20u32, 22u32)
```

There is no generic-call type inference in alpha.6. Omitting required type arguments is `E_GENERIC_ARGS`; supplying type arguments to a non-generic call is `E_GENERIC_TARGET`.

## 3. Constraints

The closed built-in alpha.6 constraint vocabulary is:

- `Any` — any admitted concrete generic argument;
- `Integer` — any Omni integer type;
- `SignedInteger` — `i8/i16/i32/i64`;
- `UnsignedInteger` — `u8/u16/u32/u64`;
- `Scalar` — integer or `bool`;
- `Plain` — non-linear, non-async, non-View plain values under the current 0.2 type model.

Unknown constraints fail with `E_GENERIC_CONSTRAINT`. Behavioral/user-defined traits are not alpha.6 semantics.

## 4. Monomorphization

Generic functions are source-level templates. The compiler deterministically instantiates each used `(template, concrete type arguments)` tuple at most once per checked program. The concrete specialization is rechecked by the ordinary checker; capabilities, resource rules, bounds and return rules are not bypassed.

Specialization identity is internal and deterministic. Open `Type::Param` values are not serialized into Wave/Wire.

Consequently:

```text
Particle generic template
        ↓ explicit type args
monomorphization
        ↓
ordinary concrete Omni function
        ↓
checker / capabilities / evaluator / LLVM
        ↓
closed Wave/Wire program
        ↓
historical Alpha.6: Wave11 / OMC11
current Alpha.8 writer: Wave12 / OMC12
```

A generic abstraction cannot erase required capability authority: transitive capability propagation is computed over the concrete call graph.

## 5. Uniform Method Call Syntax (UFCS)

Alpha.6 adds a method-shaped call surface without classes or hidden dispatch:

```omni
value::op<T>(arg)
```

is semantically equivalent to:

```omni
op<T>(value, arg)
```

The free function remains the unique semantic definition. `::` does not create virtual methods, implicit receivers, object inheritance, vtables or ABI commitments.

## 6. Iteration

Alpha.6 adds:

```omni
for item in sequence {
    ...
}
```

Admitted sequences are exactly:

- `Array<T,N>`;
- `View<T>`.

The sequence expression is evaluated once. `item` is an immutable binding scoped to the body. The loop may execute zero times, therefore its body cannot be used to prove an unconditional return or to consume an outer linear/Result state inconsistently across iterations.

A non-admitted sequence fails with `E_ITERABLE`.

## 7. Representation fencing

Alpha.6 advanced the then-current canonical representation to Wave11 / OMC11 because `for-each` added a statement form. OMC11 uses the extensible `OMCX` prefix followed by little-endian `u32(11)`.

Generic templates and type parameters are never encoded as open executable IR in alpha.6; only concrete monomorphized functions enter Wave/Wire. `for-each` cannot be relabeled as Wave10/OMC10.

## 8. Deliberate exclusions

Alpha.6 does **not** claim:

- generic `struct`/`enum` declarations;
- capturing closures/lambdas;
- generic type-argument inference;
- user-defined behavioral traits/interfaces;
- dynamic dispatch;
- heap `Vector/Map/Set` collections;
- mutable `Slice<T>`;
- generalized ownership/borrowing.

Those features depend on the generalized memory/abstraction work planned for subsequent waves. Rejecting or deferring them is preferable to introducing an unsound lifetime/ABI model.
