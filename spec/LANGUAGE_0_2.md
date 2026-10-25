> Distribution status: WIP / NOT_RELEASED. Technical version labels describe independent contracts, not public release certification.

# Omni Language 0.2 — Normative Language Specification (alpha.6)

**Version:** 0.2.0-alpha.6  
**Status:** inherited normative contract for Alpha.6 language features. Current Alpha.8 additions are defined by `LANGUAGE_0_8.md` and `MEMORY_AUTHORITY_0_8.md`.  
**Grammar:** `spec/particle.ebnf`.

## 1. Scope

Omni is a statically typed general-purpose language. Particle is the human source form; Wave and Wire are alternate representations of a checked closed program. Correct execution does not require an LLM, application subsystem, ECU, Node or Python. Roadmap items are not semantics until promoted into versioned normative specification and conformance.

## 2. Implemented value model

Implemented primitive/foundation types include portable integers `u8/u16/u32/u64`, `i8/i16/i32/i64`, `bool`, immutable UTF-8 `Text`, immutable `Bytes`, nominal structs, closed nominal enums, `Result<T,E>`, `Option<T>`, structural `Tuple<T...>`, fixed `Array<T,N>`, read-only borrowed `View<T>`, and the restricted `Resource<Buffer>` / `Borrow<Buffer>` proving ground.

Distinct integer widths/signedness do not implicitly coerce. Explicit integer casts are range checked. Ordinary arithmetic is checked; wrapping (`+% -% *%`) and saturating (`+| -| *|`) arithmetic are explicit.

`Future<T>` and `Stream<T>` remain reserved/non-executable in Core alpha.6.

## 3. Algebraic and product types

User enums are closed nominal sum types with unit or one typed payload per variant and exhaustive `match`. `Tuple<T...>` and `Array<T,N>` are fixed products; `N` participates in Array type identity. Array access is bounds checked and `array.with` is functional copy-update. See `ADTS_0_2.md` and `PRODUCT_TYPES_LAYOUT_0_2.md`.

## 4. Borrowed contiguous View

`View<T>` is read-only and non-owning. It can be constructed from a stable immutable `Array<T,N>` binding, subdivided with `view.sub`, measured with `view.len` and read with `view.get`. It cannot be `var`, returned, or stored inside aggregates/containers under the current conservative lifetime model. Mutable `Slice<T>` is not alpha.6 semantics. See `BORROWED_VIEWS_0_2.md`.

## 5. Generic functions and constraints (alpha.6)

Alpha.6 adds generic **functions** with explicit type arguments and deterministic whole-program monomorphization. Built-in constraints are `Any`, `Integer`, `SignedInteger`, `UnsignedInteger`, `Scalar`, and `Plain`. Every used specialization is lowered to an ordinary concrete function and re-enters ordinary type/capability/resource checks.

Generic templates are Particle/source-level. Open generic parameters are not executable Wave/Wire values. Generic inference, generic nominal declarations and user-defined behavioral traits are deferred. See `GENERICS_ABSTRACTION_0_2.md`.

## 6. Method-shaped composition

`receiver::operation(args)` is Uniform Method Call Syntax. It lowers to `operation(receiver,args)` and introduces no class hierarchy, implicit object authority, vtable, virtual dispatch or independent ABI.

## 7. Control flow and iteration

Implemented forms are `if/else`, condition-controlled `for expr {}`, `for item in sequence {}`, `return`, `match Result`, `match Option`, and exhaustive enum `match`.

Alpha.6 `for item in` admits `Array<T,N>` and `View<T>`. The iterable expression is evaluated once. The item is immutable and body-scoped. Because the body may execute zero or multiple times it cannot be used to inconsistently consume an outer `Result`/linear resource or to prove an unconditional return.

## 8. Bindings, effects and capabilities

`let` is immutable; `var` is mutable subject to type/resource restrictions; parameters are immutable; implicit shadowing is rejected in the implemented subset.

External effects remain explicit. `!pure` declares no capability; `!io` is a source alias; canonical semantics use explicit capabilities such as `io.print`, `fs.read`, and `fs.write`. Required capabilities propagate transitively over the concrete call graph, including generic specializations.

## 9. Restricted memory/resource semantics

Core exposes no general raw pointer or source-level `unsafe` in alpha.6. `Resource<Buffer>` is move tracked; `Borrow<Buffer>` is non-owning/non-escaping. General heap ownership, nested linear values, generalized borrow checking, deterministic destruction and explicit unsafe/FFI are later waves.

## 10. Modules and visibility

Programs use named modules and explicit local imports. Definitions may be `pub`; private imported definitions are inaccessible. Imported public generic functions can be instantiated explicitly through their import alias. Public API visibility rules remain enforced for nominal types.

## 11. Identity / representation

`type_id` describes semantic type identity for admitted context-free descriptors. `layout_id` describes eligible plain-data representation compatibility. Neither identity grants authority, ownership, lifetime or persistence.

## 12. Representation compatibility

Alpha.6 emitted Wave11 / OMC11. `for-each` is a new statement representation and cannot be hidden under Wave10/OMC10. Generic templates are compiled away before Wave/Wire; only concrete functions cross that boundary. Alpha.8 preserves that history while the active writer is Wave12 / OMC12. See `COMPATIBILITY_0_2.md`, `COMPATIBILITY_0_8.md` and `IR_WAVE_WIRE_0_2.md`.
