> Distribution status: WIP / NOT_RELEASED. Technical version labels describe independent contracts, not public release certification.

# Cross-module trait impls and library generics over caller types — candidate (OMNI-CORE-PRO-FOUNDATION-001, CP-05)

**Status:** `FROZEN_FOR_CANDIDATE_1.3.0.0`, not release-certified. The hardened provenance and Wave22/OMC22 authoring-capsule contract is
`GENERATED_PROVENANCE_CANDIDATE.md`; it supersedes the earlier concrete-only representation and generated-name convention.

## 1. Surface
```
impl alias.Trait for Type { func m(x Type, ...) R !caps { ... } ... }
```
The trait may live in an imported module (`alias` is an import alias of the impl's module, or the module itself). Rules:
- **Visibility:** a trait of another module must be `pub` (`E_VISIBILITY`); an unknown alias or trait is `E_TRAIT`.
- **Orphan rule (`E_TRAIT_COHERENCE`):** an impl of a foreign trait is allowed only for a record or enum declared in the impl's module. A foreign trait for a foreign
  type (including the primitive types) is rejected. A duplicate impl of the same trait for the same type is rejected as before.
- **Signature:** every method must match the trait's (arity, types with `Self := Type`, capabilities not exceeding the trait's: `E_TRAIT_EFFECT`; all methods
  defined: `E_TRAIT_METHOD`). Trait signatures should use primitives and `Self`; a record of the trait's own module named in a signature is not resolved in the impl's module.
- **Constraints:** a library generic `f<T: Trait>` accepts exactly the types with an impl of that trait, wherever the impl lives (`E_GENERIC_CONSTRAINT`).
- **Dispatch:** static, `Trait.method<Type>(args)`, resolved to the generated impl function in the impl's module.

## 2. Generic bodies and the types of other modules
A specialization stays in the template's module. The type arguments it carries are the canonical `module.Name` keys that the caller already resolved and checked, and the
calls it makes to impl functions have compiler-only reference provenance. Private canonical type access is restricted to the validated substituted types;
spelling `__g_` / `__impl_` never grants privileges. The library does not import its caller (no cycle), and a private caller type remains a legal validated argument.
Wave22/OMC22 preserve the pre-lowering authoring bundle and recheck/re-expand it, rather than trusting flags or names. OSNMF source/representation parity includes templates.

## 3. Acceptance (`tests/language_0_8_3_alpha8.py::A83CrossModuleTraitTests`)
- `shapes.total<Sq>(..)` with `impl shapes.Area for Sq` in the caller: evaluator and native agree; the library module still imports nothing;
- Wave, Wire and ONME check, evaluate and agree among themselves (the generated bodies resolve after the round trip);
- rejected: foreign trait for foreign type, private trait, unknown alias, unknown trait, missing method, excess capability, duplicate impl, a type without an impl.

## 4. Not provided
Generic methods in traits, trait objects, default methods, impls of generic specializations, associated types, a trait signature that names records of its own
module for a foreign implementor, coherence beyond the orphan rule.
