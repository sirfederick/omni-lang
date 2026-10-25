> Distribution status: WIP / NOT_RELEASED. Technical version labels describe independent contracts, not public release certification.

# Omni Language 0.9.3 — Runtime Hardening

**Status:** `FROZEN_FOR_IMPLEMENTATION`

**Language version:** `0.9.3`

**Authority:** normative A93 hardening contract

## 1. Scope and non-expansion boundary

A93 hardens the already-certified A85 structured-concurrency and A86 hosted-
effect contracts. It adds no syntax, type, task primitive, effect, capability,
ABI or representation form. It closes the Core-owned `REM-C04`, `REM-C05`,
`REM-C06` and `REM-Q04` instances through causal tests and any minimal repair
needed to make the inherited behavior conform.

Wall-clock duration is not evidence by itself. The A93 campaign prefers dense,
deterministic scenario matrices, explicit fault injection and independent
oracles over passive waiting.

## 2. Syntax and static semantics

The grammar, typing and ownership rules are unchanged. In particular:

- `Future<T>` and `Stream<T>` remain lexical, linear handles;
- a task handle is consumed exactly once by `join`, `cancel` or `deadline`;
- resource, borrow, view and authority-bearing values do not become
  transferable because a failure path or retry exists;
- a task, generation, identity, observation, score or receipt never grants
  effect authority.

No source construct is added for the harness lifecycle phases defined below.
Those phases classify evidence; they are not new language values.

## 3. Effect outcome and acknowledgement semantics

The causal oracle classifies each attempted hosted effect as:

```text
PRE_DISPATCH  -> no request bytes or effect invocation crossed the boundary
DISPATCHED    -> the effect may have been observed; terminal ACK is absent
ACKNOWLEDGED  -> a valid terminal response was completely validated
```

An error may be treated as proven `NOT_APPLIED` only in `PRE_DISPATCH` with an
oracle that establishes no boundary invocation occurred. `NOT_APPLIED` is an
evidence classification, not an additional public error code.

After `DISPATCHED`, timeout, cancellation, connection loss, worker death or a
lost/truncated ACK MUST return the existing hosted error `UNKNOWN_OUTCOME (10)`
unless a stronger protocol-specific terminal result was fully validated. Such
a result MUST NOT be silently retried, relabeled `DEADLINE_EXCEEDED`, or
reported as clean non-application. A later reconciliation may establish an
outcome; it cannot rewrite the original observation.

Before dispatch, an expired deadline returns `DEADLINE_EXCEEDED (6)`, denial
returns `DENIED (1)`, invalid input returns `INVALID_INPUT (2)`, and an
observed task cancellation returns the inherited `CANCELLED (7)` where the
operation exposes that path. These results do not imply anything about an
earlier, separately identified effect.

The in-memory A85 scalar scheduler performs no external effect dispatch. Its
logical-tick deadline and cancellation outcomes remain evaluator/native
deterministic and do not claim wall-clock preemption.

## 4. Resource cleanup and exhaustion

Every acquired runtime-owned resource has one terminal cleanup path on success,
typed failure, cancellation, timeout and internal setup failure. This includes:

- channel queues and queued transferable values;
- `Resource<Buffer>` allocations and generation slots;
- process pipes, child processes and wait/reap obligations;
- TCP sockets and temporary response buffers;
- disposable files and subprocesses created by the test harness.

Cleanup is exact-once for the local resource; it is not an exactly-once claim
for an external effect. Allocation failure, slot exhaustion, size overflow and
bounded-capacity exhaustion fail with the already specified typed result or
diagnostic. They MUST NOT wrap, leak, reuse a live generation, widen a bound,
fall back to an unbounded allocation or trap unless an internal invariant was
violated.

## 5. Freshness, subject and generation

A freshness assertion is valid only for the subject and versioned state that
produced it:

- an OHP1 grant is current only when the expected generation equals the policy
  generation and the monotonic tick is not after `not_after_tick`;
- an OMP1 cognitive proposal applies only when its `base_epoch` equals the
  current system epoch and its target belongs to that epoch;
- certification evidence is reusable only when source SHA, harness SHA,
  toolchain, target, configuration, corpus and failure model all match.

Stale, cross-subject, cross-artifact, wrong-generation or unbound observations
MUST fail closed or remain `UNKNOWN`; they cannot satisfy freshness, authority
or release closure. Identity and integrity hashes do not by themselves prove
freshness or grant authority.

## 6. Deterministic fault matrix

The A93 executable matrix MUST bind every scenario to a deterministic seed,
fault point, expected lifecycle phase, expected public result and resource
oracle. At minimum it covers:

| Fault point | Required observation |
| --- | --- |
| validation/authority/deadline before dispatch | no invocation; inherited typed pre-dispatch result |
| process request write after partial/full dispatch | `UNKNOWN_OUTCOME`; child reaped; pipes closed |
| process response header/payload truncated or malformed | protocol failure or `UNKNOWN_OUTCOME` according to dispatch evidence; no orphan |
| TCP connect refused before payload | typed I/O failure; no effect claim |
| TCP timeout/error after any payload byte | `UNKNOWN_OUTCOME`; socket closed |
| cancellation/deadline race at a defined safe point | exactly one terminal local task outcome and exact-once cleanup |
| bounded channel full/closed/drained | stable backpressure/closed behavior; no unbounded growth |
| buffer allocation/slot/size exhaustion | typed bounded failure; live counters and generations remain coherent |
| stale epoch, wrong target or wrong host-policy generation | rejection; no authority or semantic mutation |
| recovery/retry after uncertain outcome | no automatic duplicate effect; explicit reconciliation required |

Fault injection may use a test-only seam, virtual clock, deterministic fixture
process/server, allocator budget or bounded model. A seam MUST be inaccessible
to Omni source, disabled in shipped runtime behavior and incapable of granting
authority. Mocks may prove state-machine behavior but do not satisfy a real-
process, real-socket or external-provider claim.

## 7. Evaluator/native and real-boundary evidence

All in-language task/channel cases require evaluator/native parity. Hosted
process and TCP outcome cases exercise their real OS process/socket boundary
with deterministic local fixtures. Tests distinguish:

```text
model/fault-injection evidence
!= real process/socket integration evidence
!= external provider evidence
```

No external provider is required or claimed by A93. The exact-candidate application subsystem
smoke remains consumer evidence and cannot close these Core-owned contracts.

## 8. Memory and authority invariants

For every failure path:

```text
Value != Resource != Borrow != BorrowMut != Authority
Identity != Observation != Authority
```

Cancellation does not revoke or mint a capability. Retry does not inherit a
previous dispatch permission without current revalidation. Cleanup may release
locally owned resources but cannot erase durable evidence that an external
effect may have happened.

## 9. Representation and compatibility

A93 retains Wave20/OMC20, ONME2, OSM2, OSMI2 and OCAP1. Readers 1..20 remain
supported under their existing fences. The lifecycle phases and fault records
are test/evidence metadata and MUST NOT be serialized into a language program
or used to reinterpret historical payloads. No downgrade may erase an existing
effect, cancellation, bound, generation, deadline or authority requirement.

## 10. Acceptance and negative semantics

A93 closes only when:

1. every required fault point has a machine-readable expected/observed row;
2. lost-ACK and post-dispatch timeout/cancellation never report proven
   non-application;
3. cleanup/resource counters return to baseline after every supported path;
4. stale/cross-subject/wrong-generation evidence is rejected;
5. evaluator/native and real local boundary gates pass where applicable;
6. ASan/UBSan, accumulated compatibility and representation fences pass;
7. the exact candidate passes the bounded application subsystem smoke and full disposable-
   worktree certification.

A missing oracle, unclassified fault, orphan process/descriptor/resource,
silent retry, hidden permission broadening or unexplained parity difference is
a release blocker. No result may remain `UNKNOWN` as a test classification;
`UNKNOWN_OUTCOME` remains a valid, explicit runtime result when causally
required.

## 11. Deferred work

application subsystem `application subsystem`, application-specific components, provider transport, PostgreSQL,
distributed reconciliation, cross-process cancellation, multi-host failover,
production Node/Python orchestration and exactly-once external effects are not
Core A93 semantics. application subsystem consumes A93 only after Core closes; any general gap
found there follows the cross-track RFC path.
