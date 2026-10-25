> Distribution status: WIP / NOT_RELEASED. Technical version labels describe independent contracts, not public release certification.

# Omni Structured Concurrency — 0.8.5

**Status:** `FROZEN_FOR_IMPLEMENTATION`  
**Language version:** `0.8.5-alpha.8`  
**Authority:** This is the normative A85 contract. It refines the A8 release
freeze; it does not add hosted I/O, provider, FFI, or ambient authority.

## 1. Scope

A85 adds bounded structured tasks, typed join/cancellation/deadline outcomes,
and bounded in-memory channels/streams. A task is a lexically owned child: its
parent either joins it or cancels it before the enclosing supported scope exits.
No detached task, ambient scheduler, implicit thread, implicit host process or
unbounded queue exists in this release.

## 2. Surface syntax

```ebnf
TaskScope   ::= "task_scope" Block
Spawn       ::= "spawn" Identifier "=" Expression ";"
Join        ::= "join" "(" Identifier ")"
Cancel      ::= "cancel" "(" Identifier ")"
Deadline    ::= "deadline" "(" Identifier "," UnsignedInteger ")"
Channel     ::= "channel" "<" Type ">" "(" UnsignedInteger ")"
Send        ::= "send" "(" Identifier "," Expression ")"
Receive     ::= "receive" "(" Identifier ")"
Close       ::= "close" "(" Identifier ")"
```

`task_scope` is a statement block. `spawn` is valid only directly inside a
`task_scope`; its right hand side is a scalar expression evaluated by its child.
`join`, `cancel`, `deadline`, `channel`, `send`, `receive` and `close` are
reserved contextual operations. A task or channel handle may not be synthesized
by a record/enum constructor, integer cast, serialized payload, identity, score
or evidence value.

## 3. Static semantics and transfer

`spawn x = expression` binds `x: Future<T>` where `T` is the expression type.
`join(x): Result<T, u32>` consumes the child handle. `cancel(x):
Result<u32, u32>` consumes it. The success value of `cancel` is the stable
`CANCELLED` outcome code. Stable outcome codes are `CANCELLED`, `CLOSED`,
`BACKPRESSURE`, and `DEADLINE_EXCEEDED`; their numeric assignments are part of
the Wave19 representation contract. Repeating either operation, using a handle
outside its scope, returning/storing/capturing it, or leaving it live at a scope
exit is rejected.

Only a value the checker proves transferable may cross a task boundary. Scalar,
text, bytes, closed Copy records/enums and arrays/tuples of transferable values
are transferable. `Borrow`, `BorrowMut`, `View`, `Resource`, an open `Future`,
an open `Stream`, a mutable loan, a non-transferable host handle and a closure
capturing any such value are rejected with `E_TASK_TRANSFER`. Names never stand
in for this proof. Task transfer moves the captured value; the parent may not
use it afterwards.

## 4. Dynamic semantics

The A85 reference scheduler is deterministic and cooperative. A child begins
only after successful spawn; a join observes exactly one terminal outcome:
`Ok(value)`, `Err(Cancelled)`, `Err(DeadlineExceeded)`, or `Err(Failed(code))`.
The scheduler ordering is an implementation/testing contract, not a promise of
general parallel execution. Native and evaluator must produce the same terminal
outcome and observable prints for the deterministic scheduler.

`deadline(handle, ticks)` consumes the owned child handle and returns the same
`Result<T, u32>` shape as `join`. `ticks` is a positive monotonic logical-tick
budget; zero yields `DEADLINE_EXCEEDED` without observing the child value.
The initial non-yielding scalar child profile either completes before a positive
budget or returns that typed deadline outcome. This deliberately does not
claim wall-clock preemption.

Cancellation is idempotent only while owned by the cancelling scope. It is
observed before expression evaluation and at every specified safe point; it
does not revoke authority, suppress cleanup, or turn an unknown external effect
into success. A deadline uses a monotonic logical tick in A85; wall time is
audit-only and hosted clocks belong to A86.

## 5. Channels, streams and backpressure

`channel<T>(capacity)` creates a lexical bounded `Stream<T>` endpoint pair with
an explicit element type; the explicit type avoids inference from a later
effectful `send` and keeps the representation self-describing. Capacity zero
and values above the documented implementation limit
reject with `E_CHANNEL_CAPACITY`. `send` returns `Result<u32, u32>` and never silently drops or allocates
an unbounded buffer. A full channel returns the `BACKPRESSURE` outcome code; a
closed channel returns `CLOSED`. `receive` returns `Result<Option<T>, u32>`:
`None` only means drained-and-closed, never a hidden timeout.

The certified native A85 channel profile admits transferable integer, `Text`
and `Bytes` payloads. Other transferable composite payloads remain a future
representation/lowering extension; they fail with `E_CHANNEL_PROFILE` rather
than receiving an unproved layout conversion.
`close` is idempotent for its owning endpoint and wakes only operations defined
by this deterministic profile. Cancellation releases queued transferable values
through the existing exact-once cleanup model.

Streams are bounded channel-backed producers in this release. No network,
filesystem, provider, clock-based blocking, fairness SLA, or cross-process
transport is implied.

## 6. Ownership, memory and authority

Task/channel metadata, scheduler tickets, deadlines, queue positions,
capabilities, identities, evidence and confidence are distinct. None grants an
authority. Borrowing across a task safe point is forbidden; resources require a
future explicit transfer/drop protocol and fail closed in A85. A cancelled or
failed child still discharges all locally owned obligations exactly once before
its terminal outcome becomes joinable.

Each evaluator/native invocation owns a separate `RuntimeContext`; fuel,
errors, output, task tables and queues are never global process state. Reentry
after context teardown is rejected.

## 7. Representation and compatibility

A85 task scopes and operations require Wave19 / OMC19 with physical header
`OMCX + u32le(19)`. ONME remains ONME2 carrying the fenced Wave payload; OSM2,
OSMI2 and OCAP1 are unchanged. Readers 1–18 keep historical semantics and
reject A85 task/channel metadata with `E_VERSION`. A downgrade must never erase
an owned child, cancellation/deadline state, transfer proof or queue bound.

## 8. Required negative and parity cases

The release must reject an orphaned child, duplicate join/cancel, task-handle
escape/capture/serialization, borrow/resource/view/non-transferable capture,
unbounded/zero/oversize channel, send after close, synthetic authority from a
task/evidence/identity, malformed Wave19 task metadata and a relabeled Wave18
payload. It must prove join/cancel races, deadline terminal outcomes,
backpressure, close/drain behavior, exact-once cleanup and independent runtime
contexts. Each supported case has evaluator/native parity.

## 9. Deferred

True parallel scheduling, atomics, locks, thread affinity, hosted timers,
network streams, cross-process channels, async I/O, FFI callbacks, provider
transport, fairness guarantees and cross-runtime task migration remain outside
A85. They require later frozen contracts and cannot be approximated by an A85
task API.
