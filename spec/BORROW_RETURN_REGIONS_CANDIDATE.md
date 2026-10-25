> Distribution status: WIP / NOT_RELEASED. Technical version labels describe independent contracts, not public release certification.

# Borrow return regions — CP-02a candidate

**Status:** `CANDIDATE` (OMNI-CORE-PRO-FOUNDATION-001, slice CP-02a). Not adopted, not certified.
**Representation:** Wave21 / OMC21, emitted only for programs that use this feature.
**Authority:** extends `MEMORY_LIFECYCLE_0_8_3.md`; weakens no rule of it.

## 1. Problem

Through Core 1.2.1.0 every function result of kind `Borrow<T>` / `BorrowMut<T>` is rejected
(`E_BORROW_ESCAPE`, "cannot be returned … A8.2"). Without a returned-borrow contract no accessor,
view or sub-region can be written as a library function.

## 2. Contract (v1, deliberately narrow)

1. **Region source.** A function whose result is `Borrow<T>` / `BorrowMut<T>` must have **exactly one**
   parameter of kind `Borrow`/`BorrowMut`. That parameter is the *region source*; the result lives no
   longer than the borrow passed for it. The region source must have the same kind and element type as
   the result (no upgrade `Borrow`→`BorrowMut`; no silent downgrade in v1).
   Otherwise: `E_BORROW_ESCAPE` (absent, ambiguous or mismatched source).
2. **Return rule.** Every `return` in such a function must return the region-source parameter itself.
   Returning anything else (a local, a temporary, a fresh `borrow(...)`, another call) is
   `E_BORROW_ESCAPE`.
3. **Call-site rule.** A call to such a function must be the direct initializer of a `let`:
   `let v = view(borrow(buf))` or `let v = view(existing_borrow)`. Any other position
   (nested argument, `return`, `match` scrutinee, expression statement) is `E_BORROW_ESCAPE`.
4. **Loan.** The `let` registers a loan on the origin of the region-source argument with the access
   kind of that argument (`borrow`→shared, `borrow_mut`→exclusive). When the argument is an existing
   borrow binding, the new loan is its child (the parent is suspended while the child is live), exactly
   as a reborrow. All existing conflict rules apply: moving, releasing or mutably borrowing the origin
   while `v` is live is `E_BORROW_CONFLICT`; use after the region ended is `E_BORROW_EXPIRED`.
5. **No new authority.** A returned borrow grants no capability and does not extend the lifetime of the
   resource; ownership, cleanup and effects are unchanged.

## 3. Out of scope for v1 (kept, not forgotten)

Field/sub-range projection results, several candidate sources with an explicit region relation,
returning a borrow through another call, borrows stored in aggregates, `Option`/`Result` of borrows.
Each needs its own contract; v1 only establishes the escape and loan-propagation rules they build on.

## 4. Representation fence

A function with a `Borrow`/`BorrowMut` result is encoded only as Wave21 / OMC21. Wave/OMC ≤ 20 readers
reject it with `E_VERSION`; relabeling a Wave21/OMC21 artifact as ≤ 20 is rejected. Programs that do not
use the feature keep emitting Wave18/19/20 unchanged.

## 5. Diagnostics

Reuses `E_BORROW_ESCAPE`, `E_BORROW_CONFLICT`, `E_BORROW_EXPIRED`, `E_VERSION` (all registered; category
`memory-resource`/`representation`). No new code.

## 6. Acceptance (tests live in `tests/language_0_8_3_alpha8.py`)

Positive: shared and exclusive forwarding accessor, evaluator/native parity, source/wave/wire round-trip.
Negative: local/temporary return, zero or two borrow parameters, kind mismatch, nested/expression-position
call, release of the origin while the returned borrow is live, Wave20/OMC20 relabeling, and the previous
rejection preserved for every case outside this contract.
