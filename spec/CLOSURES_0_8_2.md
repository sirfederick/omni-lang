> Distribution status: WIP / NOT_RELEASED. Technical version labels describe independent contracts, not public release certification.

# Omni closures — 0.8.2

**Status:** `FROZEN_FOR_IMPLEMENTATION` for the next A82.1 slice.

This slice introduces a closure expression only if the compiler can carry the
same closed callable through parsing, checking, evaluator execution, native
emission and supported executable representations. The surface is deliberately
small:

```omni
closure(x u32) u32 { return x + 1u32 }(41u32)
```

A closure has an explicit parameter list and result type, is non-recursive, and
is invoked immediately by its trailing argument list in the same function. It is
not a first-class value and therefore cannot be named, returned or stored. Its
capture set is computed by the checker. The first implementation admits:

- no capture; or
- by-value capture of an already-live `Copy` value, represented as an immutable
  closed environment value.

It rejects with a stable closure/capture diagnostic: mutable captures,
`Resource`, `Borrow`, `BorrowMut`, `View`, `Future`, `Stream`, `Result`, unsafe
or authority-bearing values, capture by reference, returning a closure, storing
one in an aggregate, serialization, foreign-boundary passage, task transfer,
recursive self-reference and any escape beyond the enclosing statement/function.

Closure invocation has ordinary left-to-right argument evaluation, re-enters the
ordinary capability and ownership checks, and does not create dynamic dispatch,
heap allocation, hidden reference counting or an authority token. A later A83/A85
contract must explicitly reopen any resource, borrow, escape or task-transfer
case.

Required proof: positive no-capture and Copy-capture examples; each rejected
capture class; evaluator/native differential; formatter and Wave/Wire round
trips; malformed closure representation rejection; and compatibility rejection
by readers that cannot encode the closure semantics.

## Representation fence

The closure body, explicit parameter types and capture references cannot be
faithfully represented by the Wave16/OMC16 expression vocabulary. This slice
therefore defines **Wave17 / OMC17**, with the existing physical `OMCX` header
followed by little-endian `u32(17)`. Wave17/OMC17 encode `closure-call` with its
parameter declarations, result type, body, ordered capture list and ordered call
arguments. Readers 1–16 remain supported for their own formats and reject a
closure-call; relabeling a closure payload as an earlier version is invalid.

## Core 1.3 fail-closed capture/context repair

Immediate closures still admit only immutable Copy parameters, captures and
results until their owning-environment contract is implemented. Copy records are
Copy recursively; a record with Resource leaves is not a Copy capture merely
because a selected field is scalar. Resource/pending/borrow/View/async/mutable
roots are forbidden through every access form, including field bases, borrow,
move, assignment targets and reborrows, with E_CLOSURE_CAPTURE. Bind a Copy field
to its own immutable value outside the closure when a projection is needed.

Capture discovery occurs at binding lookup, not only at a bare Ref expression.
It records ordinary Copy record field roots in the closed value environment.
The closure body must return its own declared Copy result type, independently of
the enclosing function's result. A mismatched body is E_TYPE; ownership-bearing
result annotations are rejected before lowering. Nested/escaping closures and
owning environments remain open CP-06 obligations, never closed by this repair.
