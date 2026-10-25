> Distribution status: WIP / NOT_RELEASED. Technical version labels describe independent contracts, not public release certification.

# Trait methods with static dispatch — CP-05b candidate

**Status:** `CANDIDATE` (OMNI-CORE-PRO-FOUNDATION-001, OM-021/OM-027). Not adopted, not certified.
**Representation:** unchanged. Traits and impls are never encoded; every impl method becomes an ordinary function, so Wave/Wire/ONME carry only concrete functions (**no new version**).
**Authority:** extends the marker traits of `TRAITS_0_8_2.md`; coherence (`E_TRAIT_COHERENCE`) and bound checking (`E_GENERIC_CONSTRAINT`) are unchanged.

## 1. Contract

1. **Trait.** `trait Shape { func area(s Self) u32 !pure }`: body-less method signatures. `Self` is the implementing type and may appear in parameters and result.
   Methods may declare capabilities (`!{memory.read}`); a method without `!` is pure. Generic methods are out of scope (`E_TRAIT_METHOD`).
2. **Impl.** `impl Shape for Circle { func area(s Circle) u32 { … } }`. Every trait method must be defined exactly once and nothing else may be
   (`E_TRAIT_METHOD`). Parameter and result types must equal the trait signature with `Self := Circle`. **An impl method may not use a capability the trait
   method does not declare** (`E_TRAIT_EFFECT`), so a caller that knows only the trait signature cannot be surprised by hidden authority.
   The implementing type must be concrete (not a generic struct/enum specialization in v1); the impl lives in the trait's module (existing coherence rule).
3. **Call.** Explicit and static: `Shape.area<Circle>(c)` (or `alias.Shape.area<Circle>(c)`). The single type argument is the implementing type; inside a
   generic function it is the type parameter (`func total<T: Shape>(x T) u32 { return Shape.area<T>(x) }`), so the call is resolved when the function is
   specialized. No receiver inference, no `::` resolution by type, **no dynamic dispatch, no vtable**. A missing impl is `E_TRAIT`.
4. **Specialization.** Each impl method is checked and lowered as the ordinary function `area__impl_<hash12>` (hash over trait and type identity). The result
   is deterministic and the normal checker applies all ownership, borrow and capability rules to the body.
5. **Visibility.** A call from another module requires a `pub` trait; the generated function inherits the trait's visibility.

## 2. Out of scope

Dynamic dispatch / trait objects, default methods, associated types and constants, generic methods, impls for generic specializations, receiver-based
`x::m()` resolution, supertraits, negative or blanket impls.

## 3. Diagnostics

Reuses `E_TRAIT`, `E_TRAIT_COHERENCE`, `E_GENERIC_CONSTRAINT`, `E_VISIBILITY`; registers `E_TRAIT_METHOD` (category `types`) and `E_TRAIT_EFFECT` (`capability`).

## 4. Acceptance (`tests/language_0_8_3_alpha8.py::A83TraitMethodTests`)

Evaluator/native parity; static dispatch through a bounded generic function for two types; effect subset; every conformance error without artifact;
cross-module call; Wave18 unchanged with no trait/impl in the representation; round-trip; idempotent formatter.
