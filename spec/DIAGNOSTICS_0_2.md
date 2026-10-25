> Distribution status: WIP / NOT_RELEASED. Technical version labels describe independent contracts, not public release certification.

# Omni Diagnostics Contract — 0.2 alpha.6

Omni diagnostics expose stable `E_*` codes in text and `omni.diagnostic/1` JSON form. Exact prose can improve; code/category semantics are compatibility surfaces inside the 0.2 line.

## Alpha.6 abstraction diagnostics

- `E_GENERIC_ARGS` — missing, mismatched or non-concrete generic arguments.
- `E_GENERIC_DECL` — malformed/duplicate generic declaration.
- `E_GENERIC_CONSTRAINT` — unknown constraint or concrete argument outside the constraint.
- `E_GENERIC_TARGET` — type arguments supplied to a non-generic call target.
- `E_GENERIC_INTERNAL` — compiler invariant around unresolved generic state; should not arise for a valid source program.
- `E_ITERABLE` — `for item in` operand is not an admitted Array/View sequence.

These join inherited diagnostics including `E_VIEW_SOURCE`, `E_VIEW_MUTABLE`, `E_VIEW_ESCAPE`, `E_VERSION`, `E_CAPABILITY`, `E_BOUNDS`, `E_TYPE`, `E_IMMUTABLE`, `E_UNDEFINED`, resource/result flow diagnostics and toolchain/runtime errors.

Unknown privileged capability/action input continues to fail closed; representation version mismatch is not silently downgraded.


## Alpha.8 memory / loan diagnostics

Alpha.8 extends the registry without changing historical meanings:

- `E_BORROW_CONFLICT` — an overlapping shared/exclusive loan or move/drop violates the active Loan graph.
- `E_BORROW_ESCAPE` — a Borrow/BorrowMut attempts a currently unsupported storage/escape/rebinding path.
- `E_BORROW_EXPIRED` — defensive fail-closed diagnostic for use of a loan after its inferred Region has ended.
- `E_REBORROW_KIND` — a shared Borrow attempts to create an exclusive reborrow.
- `E_PLACE` — a loan operation requires a structurally proven Place, not a temporary or dynamic projection.
- existing `E_RESOURCE_MOVED`, `E_RESOURCE_FLOW` and `E_RESOURCE_LEAK` continue to describe ownership/lifecycle failures rather than borrow-alias failures.

All `E_BORROW_*` and `E_RESOURCE_*` codes are categorized as `memory-resource`.

The current Alpha.8 representation is Wave12 / OMC12; representation downgrade cannot hide BorrowMut or loan semantics.
