> Distribution status: WIP / NOT_RELEASED. Technical version labels describe independent contracts, not public release certification.

# Postfix `?` propagation — CP-05c candidate

**Status:** `CANDIDATE` (OMNI-CORE-PRO-FOUNDATION-001, OM-016 ergonomics). Not adopted, not certified.
**Representation:** unchanged. `?` is lowered **before checking** into existing statements, so Wave/Wire/ONME never contain it (**no new version**).

## 1. Contract

`expr?` unwraps a `Result<T,E>` (or `Option<T>`) in a function whose own result is `Result<U,E>` (or `Option<U>`) and returns early on failure:

```text
let x = parse(a)?      ==>   let __try_t0 = parse(a)
rest…                        match __try_t0 {
                               Ok(__try_v0)  { let x = __try_v0   rest… }
                               Err(__try_e0) { return Err<U,E>(__try_e0) } }
```

1. **Same error type.** The `Err` payload is returned as is; a different error type is the ordinary `E_TYPE` of the generated `return` (no implicit conversion).
   `Result` and `Option` are not mixed (`?` on an `Option` inside a `Result` function is `E_TYPE`).
2. **Context.** The enclosing function must return `Result` or `Option` (`E_TRY_CONTEXT`). `?` inside a closure body is rejected (`E_TRY_POSITION`).
3. **Position.** Allowed in the expression of `let`/`var`/assignment/`return`/`print`/`if`/`for … in`/`match`/destructuring. **Not** in a loop condition (it would be
   evaluated repeatedly): `E_TRY_POSITION`.
4. **Evaluation order is preserved.** The operand of the first `?` is lifted first, so no call (or move) may be evaluated before it in the same expression;
   otherwise `E_TRY_ORDER` (bind earlier operands with `let`). Several `?` in one expression are lifted left to right.
5. **Ownership is unchanged.** The rest of the block moves into the success arm, so every move, loan, cleanup and linear-value rule applies as if written by hand;
   a live `Resource` is cleaned up on the early return exactly as on any `return`.
   A plain `let x = expr?` (no declared type) binds the payload **directly as `x`** in the success arm, so a `Resource` payload is moved into `x` with no copy.
   A `Resource` payload used deeper in an expression (`consume(make()?)`) is a copy of a linear value and is rejected by the ordinary ownership check: bind it first with `let`.
6. **No new authority, no runtime, no representation.** `omni fmt` prints the lowered form (the formatter works on the validated program).

## 2. Out of scope

Error conversion (`From`), `?` on mixed `Result`/`Option`, `try` blocks, `?` in closures, labelled early exit.

## 3. Diagnostics

Registers `E_TRY_CONTEXT`, `E_TRY_ORDER`, `E_TRY_POSITION` (category `flow`).

## 4. Acceptance (`tests/language_0_8_3_alpha8.py::A83TryOperatorTests`)

Evaluator/native parity for `Result` and `Option`; several `?` per expression; no `Resource` leaked over 3000 failing cycles (runtime slot oracle); every
context/order/position/type error without artifact; Wave18 with no `?` in any representation; stable formatter.
