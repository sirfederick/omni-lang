> Distribution status: WIP / NOT_RELEASED. Technical version labels describe independent contracts, not public release certification.

# Static assertions — CP-07 candidate

**Status:** `CANDIDATE` (MN-15; limited compile-time evaluation MN-10). Not adopted, not certified.
**Representation:** none. A static assertion is a property of the source: it is decided while the program is validated and leaves no trace in the checked program, Wave, Wire, hash or OSNMF.
**Tests:** `tests/cp07_static_assert.py`.

## 1. Contract

`static_assert(condition, "message")` is a module item. The condition is the body of a hidden pure function `() bool` (it declares no capability, so it can read constants, call other pure functions and ask `layout.size/align/offset` and `target.*`, but cannot print, touch memory or use authority — the checker already refuses that with `E_CAPABILITY`). After the whole program is checked the evaluator decides it, under its normal fuel and depth limits:

* true — nothing happens;
* false — `E_STATIC_ASSERT` with the author's message at the assertion's place;
* undecidable (overflow, division by zero, recursion or loops without end) — `E_STATIC_ASSERT`, never silently ignored.

An assertion in an imported module guards every program that imports the module. It cannot be `pub`, must have a quoted message, and the condition must be `bool`.

## 2. Formatter

`omni fmt` prints it back canonically (`static_assert((cond), "message")`, idempotent). The parsed assertions live in `Program.staticAsserts`, outside `functions`, so no representation can observe them.

## 3. Use

Freeze a layout (`layout.size<Desc>() == 16u64`), a register map (`bitfield.fits`, `bitfield.disjoint`), a ring size, or a target assumption (`target.pointer_width() == 64u32`).
