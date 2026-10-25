> Distribution status: WIP / NOT_RELEASED. Technical version labels describe independent contracts, not public release certification.

# Omni 0.2 — User Algebraic Data Types (alpha.3)

**Language:** Omni Language 0.2.0-alpha.3  
**Status:** normative for user-defined enum semantics implemented in alpha.3.

## 1. Purpose

Alpha.3 introduces closed nominal sum types without introducing inheritance or an open variant hierarchy. The design goal is a small, statically checkable foundation that can later support richer patterns without invalidating current programs.

## 2. Declaration

```omni
enum State {
    Pending,
    Active(u32),
    Failed(Text),
}
```

An enum contains 1..64 variants. A variant is either:

- unit: no payload;
- payload: exactly one statically typed payload.

Variant names are unique within the enum. The enum is nominal: two enums with identical variant shapes remain different types.

## 3. Construction

```omni
let a State = State.Pending()
let b State = State.Active(42u32)
```

Imported public enums use the import alias:

```omni
let s t.Status = t.Status.Running(7u32)
```

Arity and payload type are checked statically. A nonexistent variant is rejected.

## 4. Matching and exhaustiveness

```omni
match state {
    Pending { return 0 }
    Active(value) { return value }
    Failed(message) { return text.len(message) }
}
```

For a closed enum `E`, the checker computes:

```text
DeclaredVariants(E) == MatchedVariants(match)
```

with set equality plus duplicate rejection. This is the complete alpha.3 exhaustiveness algorithm. It does not normalize/rewrite pattern label sets and does not perform GADT reasoning.

Rules:

- each variant must appear exactly once;
- unknown variants are rejected;
- payload variants require exactly one binder;
- unit variants cannot bind a payload;
- all continuing branches must preserve Result/Resource flow consistently;
- if every branch returns, the match statement returns for control-flow analysis.

Stable diagnostic families introduced/used here include:

- `E_MATCH_NON_EXHAUSTIVE`;
- `E_MATCH_DUPLICATE`;
- `E_MATCH_VARIANT`;
- `E_MATCH_BINDING`;
- `E_ARITY` / `E_TYPE` for constructor mismatches.

## 5. Visibility

`pub enum` may cross module boundaries. A private enum cannot be named or constructed from an importing module. A public enum may not expose a private payload type from its defining module.

## 6. Payload restrictions in alpha.3

Payloads may contain ordinary value types, structs, other non-recursive enums, Text, Bytes, Option and other admitted value forms whose flow semantics are already sound.

The following payloads are temporarily rejected in alpha.3:

- `Resource<T>`;
- `Borrow<T>`;
- `Future<T>`;
- `Stream<T>`;
- `Result<T,E>`.

This is a soundness restriction, not a permanent language principle. Nested linear/async/error ownership must be specified before these forms are admitted.

Core 1.3 candidate amendments in OWNERSHIP_COMPOSITION_CANDIDATE.md supersede
the Resource/Result and nested-pending sum restrictions under a single explicit
consumption law. Borrow/async restrictions remain. This does not retroactively
change certified alpha.3 semantics or its historical evidence.

## 7. Recursive layout

Direct or indirect by-value recursion is rejected with `E_LAYOUT_CYCLE`. A future indirection/container type may permit recursive data structures without making a value infinitely large.

## 8. Current lowering model

The current LLVM lowering uses:

```text
{ i8 discriminant, payload-slot-for-variant-1, payload-slot-for-variant-2, ... }
```

Only variants with payloads contribute payload fields. This is an **alpha implementation layout**, not a stable Omni public ABI. Future releases may compact representation while preserving source/IR semantics through a representation-version or ABI boundary.

## 9. Deliberately deferred

Alpha.3 does not implement:

- wildcard/default enum arms;
- guards;
- or-patterns;
- tuple/record destructuring patterns;
- open/extensible variants;
- GADTs/refinement typing;
- multi-field variant payload syntax;
- pattern matching as an expression.

These require separate research/spec waves.

## 10. Future SisNervCent seam

A future program-aware nominal type descriptor can derive identity from module-qualified name plus canonical variant schema, for example conceptually:

```text
enum|acme.State|Pending;Active(u32);Failed(Text)
```

Alpha.3 does **not** persist this identity, create ObjectIDs, or introduce SisNervCent. This is only a documented seam for future reflection/type-registry work.
