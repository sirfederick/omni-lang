> Distribution status: WIP / NOT_RELEASED. Technical version labels describe independent contracts, not public release certification.

# Generic structs and enums — CP-05 candidate

**Status:** `CANDIDATE` (OMNI-CORE-PRO-FOUNDATION-001, OM-023). Not adopted, not certified.
**Representation:** unchanged. Only concrete specializations enter Wave/Wire/ONME (as for generic functions, `GENERICS_ABSTRACTION_0_2.md` §7): **no new Wave/OMC version**.
**Authority:** lifts the "generic `struct`/`enum` declarations" exclusion of `GENERICS_ABSTRACTION_0_2.md` §8 (structs and enums).

## 1. Contract

1. **Declaration.** `struct Name<T, U: Constraint> { field T, other U }` (`pub` allowed). Constraints are the existing ones
   (`Any`, `Integer`, `SignedInteger`, `UnsignedInteger`, `Float`, user marker traits). 1..16 parameters; duplicate parameter,
   unknown constraint or a name that collides with another struct/enum/generic is `E_GENERIC_DECL` / `E_GENERIC_CONSTRAINT` / `E_DUPLICATE`.
2. **Use.** A type `Name<A, B>` (optionally `alias.Name<A, B>`) and an initializer `Name<A, B> { field: value, … }`.
   Arguments are **explicit** (no inference). Wrong arity: `E_GENERIC_ARGS`; an initializer without arguments for a generic
   struct: `E_GENERIC_ARGS`; arguments on a non-generic type: `E_GENERIC_TARGET`; a constraint not satisfied: `E_GENERIC_CONSTRAINT`.
   Arguments must be concrete (nested generic structs, records, enums, scalars, `Resource<Buffer>`, … as already admitted for generic functions).
3. **Monomorphization.** Each distinct argument list yields one ordinary record `Name__g_<hash16>` in the template's module,
   with the template's visibility. Field types are substituted, then checked **as an ordinary struct**: every ownership,
   Resource-field, linear-`Option`, layout-cycle and visibility rule applies unchanged. A generic container of a `Resource`
   therefore has exactly the semantics of the equivalent hand-written struct; nothing is hidden by the template.
4. **Bounds.** No count of templates or specializations is part of the language (the 128 and 64 of earlier versions are retired, Adenda 015E): a program has as many as the memory budget of the host allows
   (`E_BUDGET`, see `docs/architecture/OMNI-CORE-1_3-RESOURCE-BUDGET-015E.md`). The nesting of type arguments is still bounded structurally (`E_LIMIT`), which is what stops a recursive expansion.
5. **No new authority, no new runtime, no new representation.** Templates are never encoded; the specialization name is derived from the
   canonical type identity of the arguments, so equal arguments share one record and the result is deterministic.

## 1b. Generic enums

`enum Name<T, U: C> { A(T), B(U), C }` follows rules 1-5 above with these specifics: the type use is `Name<A, B>`; a **constructor carries its
type arguments like `Some<T>(v)` / `Ok<T,E>(v)`**: `Name.A<u32,u8>(1u32)` (or `alias.Name.A<u32,u8>(1u32)`); unit variants take no payload
(`Name.C<u32,u8>()`). Each distinct argument list yields one ordinary enum `Name__g_<hash16>`; `match` arms name only variants, so patterns need no
arguments, and exhaustiveness/payload rules are the ordinary enum rules.

## 2. Out of scope

Trait methods, inference of arguments, const/value parameters, specialization of a template by a different module's
private type, OSNMF nuclei for the template itself (OSNMF describes the concrete specializations).
`omni fmt` prints the template and the generated specializations as ordinary structs (the formatter works on the validated program).

## 3. Acceptance (`tests/language_0_8_3_alpha8.py::A83GenericStructTests / A83GenericEnumTests`)

Evaluator/native parity; one record per distinct argument list; nested and cross-function use; `Resource<Buffer>` as argument with the
full ownership checks; every constraint/arity/target error without artifact; Wave18 unchanged, round-trip through wave/wire/ONME,
idempotent formatter.
