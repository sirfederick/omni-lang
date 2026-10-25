> Distribution status: WIP / NOT_RELEASED. Technical version labels describe independent contracts, not public release certification.

# Omni A8 release architecture freeze — 0.8.2 through 0.8.9

**Status:** `DESIGN_FROZEN`; normative only for the version-scoped features named
below. It does not claim that those features exist in the 0.8.1 source release.

**Authority:** this contract refines the inherited specifications in this directory.
If it conflicts with an already released specification, the released specification
governs its released feature until a versioned compatibility rule below takes effect.
Operational roadmaps and application subsystem documents cannot redefine these semantics.

## 1. Release boundary and non-goals

The A8 train is ordered `0.8.2` through `0.8.9`. A release is implemented only
after its stated prerequisites are `GATE_GREEN`; it is closed only after exact-SHA
certification. The dependency graph is machine-readable in
`A8_RELEASE_DEPENDENCY_GRAPH.json`.

No release may silently add ambient authority, dynamic dispatch, raw-pointer
authority, implicit ownership transfer, or an ABI promise. A feature that is not
listed as implemented for the current version is rejected with a stable diagnostic
or remains unavailable; it is never simulated by a documentation-only API.

Representation writers advance only when an existing representation cannot encode
the new executable semantics without ambiguity. Readers retain documented historic
compatibility and must reject a newer semantic construct that they cannot represent.

## 2. A82 — abstraction foundation

**Prerequisite:** `CORE-EPOCH-001` is fixed under
`EPOCH_MONOTONICITY_0_8_2.md` and has a regression across every real epoch-advance
path.

0.8.2 introduces only static, whole-program abstractions:

- traits are nominal contracts with explicit implementations; implementation lookup
  is deterministic, overlapping implementations and unknown traits are rejected,
  and there is no specialization, orphan bypass, trait-object construction or
  dynamic dispatch;
- a method is static syntax for a resolved implementation whose receiver mode is
  explicit (`read`, `mutate`, or `consume`); it must preserve the existing loan and
  move rules;
- generic trait/method use is monomorphized and rechecked as concrete Omni code;
- closures are immediate, non-escaping expressions whose capture set is explicit.
  By-value capture is admitted only for Copy values. Shared-borrow capture is
  admitted only when its region ends before the closure value ends. Mutable-borrow,
  Resource, Owned, reborrow, return, aggregate storage, serialization, task transfer
  and foreign-boundary capture are rejected in 0.8.2;
- iteration may use only an explicitly resolved static iterator protocol; exhaustion,
  evaluation order and cleanup are defined by the concrete implementation.

The conformance suite must contain resolved and ambiguous trait calls, conflicting
implementations, each receiver mode, valid and invalid captures, evaluator/native
differentials, malformed representation inputs, and legacy-reader rejection where
needed. `CLOSURES_0_8_2.md` authorizes Wave17/OMC17 because the closure body and
capture set require a new executable encoding; no other representation bump is
pre-authorized by this freeze.

## 3. A83 — memory and lifecycle

0.8.3 may extend the root-loan model only with proofs carried by the checker:

- field-disjoint Places require a structural proof; uncertain projections remain
  overlapping;
- reborrows retain a parent origin and cannot increase authority;
- an escaping borrow is rejected unless its origin, region and owner relationship
  are represented and checked;
- deterministic cleanup runs exactly once on every supported structured exit.
  Process kill, host abort and unsupported unwind are explicitly outside that claim;
- allocation returns a typed recoverable failure and does not mint authority;
- bounds use checked arithmetic (`offset <= length` and `span <= length - offset`),
  and alignment/provenance are validated before foreign or shared mappings.

No general raw pointers, unrestricted unsafe blocks, or unproved cross-task borrow
transfer are enabled by A83. All failure cases are fail-closed and differential
tests cover evaluator and native execution.

## 4. A84 — packages and minimum standard library

0.8.4 defines package identity as `(publisher-or-local-origin, package name,
version, module path)` under a deterministic resolver. Imports and exports are
explicit; illegal visibility, cycles, missing packages, lock drift, checksum mismatch
and ambiguity fail before compilation. A lock records the selected graph and hashes;
a hash alone is not publisher authentication.

The standard library is a versioned package set with explicit error/result,
iteration, text/bytes and deterministic utility contracts. It does not provide
placeholder async, I/O, networking or authority APIs. Clean/offline resolution and
consumer examples are release gates. The interval closes only after consumer integration.

## 5. A85 — bounded structured concurrency

0.8.5 defines tasks as lexically owned children: a parent joins or cancels every
child before its supported scope exits. Cancellation, deadline and failure are typed
outcomes. Monotonic clocks measure durations; wall clocks are audit data only.

Only values proven transferable by the checker cross task boundaries. A live borrow,
mutable loan, non-transferable handle or resource without an explicit transfer/drop
protocol is rejected. Channels and streams declare bounded message/byte capacity,
backpressure, close and cancellation semantics. Scheduler order is not promised
unless a deterministic test scheduler is selected. Global mutable evaluator state
is not a concurrency contract and must be removed or isolated before this release.

## 6. A86 — hosted effects and foreign boundary

0.8.6 gives filesystem, process and network effects an explicit host capability,
scope, timeout/deadline, cancellation and typed error contract. Partial I/O and
cleanup are observable; ambient host access is forbidden.

The public ABI/IDL specifies version negotiation, endian/layout rules, tagged errors,
length-delimited buffers, ownership/release, no cross-runtime unwinding and opaque
generation-bound handles. Node and Python adapters use the copy path unless a
separate shared-memory proof validates bounds, alignment, lifetime, mutability,
principal and revocation. Foreign data is untrusted until validated. This release
does not claim sandboxing merely because it launches a host process.

## 7. A87 — developer and systemic tooling

0.8.7 makes documented build, formatter, diagnostics and inspection paths usable
from a clean checkout. Diagnostics preserve code and source span; incremental and
clean builds are semantically equivalent under identical inputs. Native observation
is correlated to the executing artifact, bounded and redacted. Unknown foreign or
dynamic edges remain conservative/unknown in impact output. The interval closes
only after consumer integration.

## 8. A88 — target-profile acceptance criteria

0.8.8 freezes, before testing, an explicit matrix of supported versus experimental
targets. For every supported target the compiler, runtime, package resolver and
applicable application subsystem adapter must execute natively; cross compilation and WSL do not
substitute for native execution. Paths, Unicode, permissions, signals/processes,
clocks, atomics, filesystem durability, endian/layout and ABI behavior are tested
where relevant. A missing required runner yields `BLOCKED` or `NOT_RUN`, never PASS.

## 9. A89 — hardening and convergence acceptance criteria

0.8.9 requires the accumulated suite, versioned malformed-input corpus, mutation
and fuzz seeds, sanitizers, reproducibility, package integrity, recovery/chaos/soak
evidence, dependency inventory/provenance available within the approved profile,
and compatibility/upgrade rejection tests. Claims are limited to observed duration,
platform and profile. A hash is not a signature and a short stress run is not a soak.

The interval closes only after consumer integration, including the historical long-run
failure class, a durable lock/manifest, and a LANGUAGE-USABLE evaluation. This is
not authorization to publish 1.0.

## 10. Cross-release gates

Every semantic slice supplies positive, negative, malformed and differential tests.
Every release supplies exact source identity, certification evidence, a new annotated
tag and a governed receipt that distinguishes release source, receipt commit, tag
object and tag target. application subsystem is a consumer: each release runs a compatibility smoke;
Sync A/B/Final are separate integration gates. Remote CI remains separately reported
from local certification and must not be called PASS without a real remote result.
