> Distribution status: WIP / NOT_RELEASED. Technical version labels describe independent contracts, not public release certification.

# Omni Memory and Lifecycle — 0.8.3

**Status:** `FROZEN_FOR_IMPLEMENTATION`  
**Language version:** `0.8.3-alpha.8`  
**Authority:** This contract refines `MEMORY_AUTHORITY_0_8.md` under
`ADR-0068-a83-memory-lifecycle-scope.md` for the A83 release only.

## 1. Scope and non-goals

A83 extends the existing root `Resource<Buffer>` loan model with checker-proven
field Places, non-escalating reborrows, structured cleanup and typed allocation
failure. Value, resource, borrow and authority remain distinct:

```text
Value != Resource != Borrow != Authority
Place identity != capability != authority
```

This release does not admit raw pointers, general `unsafe`, arbitrary `Owned<T>`,
escaping borrow returns, aggregate/capture/serialization of borrows, unproved
array-index disjointness, shared ownership, or cross-task loan transfer.

## 2. Syntax and Place formation

The existing `borrow(...)` and `borrow_mut(...)` forms accept only a **Place**:

```ebnf
Place ::= Identifier ( "." Identifier )*
LoanExpression ::= "borrow" "(" Place ")"
                 | "borrow_mut" "(" Place ")"
```

The terminal Place type must be `Resource<Buffer>` for a root borrow, or
`Borrow<Buffer>` / `BorrowMut<Buffer>` for a reborrow. Calls, temporaries,
array/index projections and unknown/dynamic projections are not Places for A83.
They fail closed with `E_PLACE` rather than being approximated as a root borrow.

A field Place is structurally proven only when every projection is a declared
record field of the resolved nominal record type. Two Places are disjoint only
when they share a root and their first differing proven field projection differs.
A root overlaps every descendant. Identical paths and prefix paths overlap.
Array or dynamic projections conservatively overlap their aggregate.

## 3. Static ownership and loan semantics

For overlapping Places, any number of shared loans or one exclusive loan are
admitted, never both. Move, replacement, direct resource access and cleanup of a
Place conflict with a live overlapping loan.

Core 1.3 clarification: a loan supplied as a call argument remains live while
later arguments are evaluated and through the invocation. The same proven
Place overlap rule applies to accesses nested inside those later expressions,
including release/move; comparing only root identifiers or only final argument
types is insufficient. Shared/shared overlap and disjoint proven fields remain
admitted. The owning Tuple amendment extends this rule to literal indices.

Loans carry `(origin, place path, kind, region, parent loan if reborrowed)` in the
checker. The origin is the root owner; a child never receives a new owner or any
authority.

### Reborrow

`borrow(r)` where `r: Borrow<Buffer>` creates a shorter shared reborrow.
`borrow(r)` where `r: BorrowMut<Buffer>` creates a shorter shared child and
suspends use of the parent until the child region ends.
`borrow_mut(r)` where `r: BorrowMut<Buffer>` creates a shorter exclusive child and
suspends use of the parent until the child region ends.
`borrow_mut(r)` where `r: Borrow<Buffer>` is rejected with `E_REBORROW_KIND`.

A reborrow cannot outlive its parent region. Moving, releasing, or accessing a
suspended parent is rejected with `E_BORROW_CONFLICT`; using a child after its
region ends is rejected with `E_BORROW_EXPIRED`.

## 4. Regions and structured exits

Regions are intra-function and dataflow-derived. Last use can end a local loan
before lexical scope exit, but branches and loops remain conservative unless the
checker proves the same state at every continuing edge. A return, break, continue,
branch join or loop edge cannot strand an active child loan or live resource.

Every live `Resource<Buffer>` obligation is cleaned exactly once on supported
structured scope exit: normal fallthrough, `return`, `break`, `continue`, and
typed `Result`/match branch exits. Explicit `move`, `buffer.release` and
`buffer.freeze` discharge the same obligation and prevent a second cleanup.
Process kill, host abort and unsupported unwinding are outside this guarantee.

## 5. Allocation and bounds

`buffer.alloc(size)` remains an explicit capability-gated operation returning a
recoverable `Result<Resource<Buffer>, u32>`. Its `Err` payload is the stable typed
allocation-failure code for the current runtime profile; allocation failure does
not abort the process, leak an existing resource, or mint authority.

All buffer/view span checks use checked subtraction form:

```text
offset <= length
span <= length - offset
```

Overflow-prone `offset + span` acceptance is forbidden. Invalid bounds produce
the existing typed `Err`/`E_BOUNDS` contract consistently in evaluator and native
execution.

## 6. Authority

Borrowing and cleanup grant no capability. `buffer.alloc`, reads and writes retain
their existing declared capability requirements. A Place path, type identity,
allocation handle, checker metadata or serialized representation is never runtime
Authority. Reborrowing may reduce or suspend access but cannot increase it.

## 7. Dynamic semantics and parity

Evaluator and native backend execute the same left-to-right argument evaluation,
loan conflicts, cleanup discharge and typed allocation/bounds outcomes. Cleanup is
not observable as a new authority effect. A compiler-internal disagreement between
the checked loan plan and execution plan is an internal invariant failure, never a
dynamic fallback to unchecked access.

## 8. Representation and compatibility

A83 projected/reborrowed loan semantics require **Wave18 / OMC18** with the
existing `OMCX + u32le(18)` physical header. Writer, reader and ONME projection
must agree on the version. ONME remains ONME2 because its envelope carries the
fenced Wave payload. OSM2, OSMI2 and OCAP1 are unchanged.

Wave/OMC 1–17 remain readable for their own historical semantics. They must reject
an A83 projected/reborrowed loan or cleanup-bearing payload with `E_VERSION`;
relabeling an A83 payload as an older version is invalid. No downgrade path silently
erases a Place path, parent loan or cleanup obligation.

## 9. Required negatives

The conformance suite must reject at least:

- overlapping field mutable/shared loans;
- a move/release of a root while a descendant loan is live;
- shared-to-exclusive reborrow;
- child borrow use after its parent/region ends;
- borrow from an array/dynamic projection or temporary;
- duplicate cleanup/double release and a resource stranded on every structured exit;
- malformed Wave18/OMC18 Place or parent metadata;
- relabeled Wave17/OMC17 downgrade payloads;
- capability denial and attempts to treat a borrow or handle as Authority.

It must also prove disjoint sibling field loans, valid shorter reborrows,
allocation failure recovery, bounds overflow rejection and evaluator/native
differential parity.

## 10. Deferred beyond A83

General `Owned<T>`, user-defined Drop hooks, raw pointers, unrestricted `unsafe`,
borrow return/origin parameters, aggregate/captured borrows, dynamic collection
place proofs, async suspension, cross-task transfer and FFI mappings remain
unavailable and fail closed until separately frozen.
