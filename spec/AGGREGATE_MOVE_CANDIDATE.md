> Distribution status: WIP / NOT_RELEASED. Technical version labels describe independent contracts, not public release certification.

# Moving a struct that owns Resources — CP-01b candidate

**Status:** `CANDIDATE` (OMNI-CORE-PRO-FOUNDATION-001, OM-031 composition). Not adopted, not certified.
**Representation:** unchanged. The move is rewritten by the checker into constructs that already exist (field moves and a struct initializer); Wave/Wire/ONME carry nothing new.

## 1. Problem

A `struct` with `Resource` fields could be built inline and its fields moved one by one (`move(p.left)`), but the aggregate could not be passed to another function by name:
`record con Resource requiere proyeccion de campo probada; no puede copiarse`. Ownership could not be transferred as a unit, so a callback environment, a handle bundle or a
container owning resources could not be handed to a callee.

## 2. Contract

1. `move(r)` is allowed when `r` is a binding or a field path whose type is a `struct` that contains `Resource` leaves (directly or in nested structs).
   It denotes the **construction** `R { f: move(r.f) | r.f, … }`: Resource leaves and nested owning structs are moved (recursively), Copy fields are read.
   The result is an owned value of the same type, usable wherever one is expected (argument, `let`, `return`).
2. Every rule of a field move applies to each leaf: a leaf already moved/released is `E_RESOURCE_MOVED`; a live loan on a leaf is `E_BORROW_CONFLICT`
   (with the related location of the loan); a callee that receives the aggregate owns its leaves and must discharge them or they are cleaned up on exit.
3. A bare use of such a struct (`f(r)`, `let c = r`) is still `E_RESOURCE_ACCESS`: moves stay explicit. `move(r)` on a struct without Resource leaves keeps its
   existing error (`move` requires a Resource).
4. No new authority, runtime or representation; the rewrite happens during checking.

## 3. Acceptance (`tests/language_0_8_3_alpha8.py::A83AggregateMoveTests`)

Parity evaluator/native; nested owning structs with Copy fields preserved; moved-twice and use-after-move errors; live loan conflict; 3000-cycle leak oracle
(the callee does not release and cleanup runs); callbacks with an owning environment (`A83CallbackPatternTests`).

For imported records the checker-generated initializer uses the caller's existing
alias for the declaring module. Moving an imported owner must not require an
unqualified type name to be in scope. Ordinary visibility and constructor checks
still apply. The nominal-record amendment in NOMINAL_AFFINE_RESOURCE_CANDIDATE.md
adds explicit-consumption leaves to this same expansion, without granting module
authority or changing the persisted expression grammar.
