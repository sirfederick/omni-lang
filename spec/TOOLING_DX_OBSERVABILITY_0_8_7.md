> Distribution status: WIP / NOT_RELEASED. Technical version labels describe independent contracts, not public release certification.

# Omni Tooling, DX and Observability — 0.8.7

**Status:** `FROZEN_FOR_IMPLEMENTATION`  
**Language version:** `0.8.7-alpha.8`  
**Authority:** normative A87 tooling contract

## 1. Scope and invariant

A87 makes the documented format, diagnostic, project-analysis, build and
observation paths usable from a clean checkout. It does not add language
syntax or weaken the memory, capability, host-authority or representation
contracts certified through A86.

Tool output is evidence about a named source/artifact and toolchain. It is not
runtime authority. Unknown dynamic or foreign behavior remains `unknown`; a
tool must not turn missing evidence into a safe edge, grant or causal fact.

## 2. Stable diagnostics

Every machine diagnostic has schema `omni.diagnostic/1`, stable code, severity,
message and an optional byte/line/column span tied to a canonical source URI.
Related locations and fix-its are ordered deterministically. A fix-it names the
exact replaced span and text and never applies itself during `check`.

Text and JSON modes describe the same primary diagnostic code and span. Invalid
UTF-8, unavailable source, overflowed offsets and synthetic diagnostics omit or
mark the unavailable coordinate instead of inventing one. Diagnostics do not
contain environment secrets or unrestricted source payloads.

## 3. Formatter

`omni fmt FILE` emits canonical source to stdout; `--check` returns non-zero
when the input differs and `--write` atomically replaces one regular file.
Formatting is deterministic, idempotent, syntax preserving and line-ending
normalized. Parse failure makes no change. Symlink, directory and non-regular
write targets fail closed. Formatter behavior is independent of network,
workspace cache and host authority.

## 4. Project analysis and LSP

The A87 language server uses LSP over stdio with Content-Length framing. Its
adopted surface is initialize/shutdown/exit, didOpen/didChange/didClose,
publishDiagnostics, completion, hover, definition, references and rename.
Responses are deterministic for a fixed workspace snapshot and are bounded by
configured file, message and result limits.

Incremental edits are version-ordered. Stale or malformed changes reject and
do not mutate the last valid snapshot. Rename refuses ambiguous bindings,
foreign/dynamic edges and edits outside the admitted workspace. Completion or
hover metadata never grants capabilities or asserts runtime liveness.

## 5. Build provenance and cache correctness

Clean and cache-hit builds with identical source closure, compiler, runtime,
target, optimization, declared capabilities and relevant flags produce the
same executable bytes. The cache key binds all those inputs. Dependency,
toolchain, flag, policy-affecting or runtime changes invalidate the entry.

Every build emits an `omni.build-receipt/2` containing normalized input
digests, toolchain identity, cache key/hit state, artifact digest and command
profile. The receipt contains no secret environment values. Cache corruption,
symlink substitution and digest mismatch are misses or failures, never hits.

## 6. Debug, profile and coverage profile

A87 adopts bounded offline artifacts rather than claiming a full interactive
debugger. Source maps correlate functions and stable source spans to emitted
native symbols. `profile` reports wall/cpu counters for a bounded execution;
`coverage` reports visited executable source regions. Each report binds source,
binary digest, compiler version, command profile and exit state.

The runtime records errors crossing a hosted boundary with the stable host code
and operation class, without credentials or payloads. Instrumentation overhead
is measured on the release fixture and reported as measurement, not an SLA.

## 7. Systemic inspection

Summary, query, trace and impact output identify schema, source or OSNMF epoch,
root digest and edge classification. Static, observed, foreign and unknown
edges are distinct. Truncation, depth and result limits are explicit. Impact
conservatively retains unknown foreign/dynamic edges and explains that limit.

Native observations bind the executing artifact digest and process instance.
They are bounded and redacted; runtime observation is not semantic truth or
authorization. Cardinality is limited by stable operation/function classes,
not unbounded user payloads.

## 8. CLI and clean-checkout workflows

`check`, `fmt`, `test`, `build`, `run`, `doctor`, `lsp`, `build-receipt`,
`profile`, `coverage`, `query`, `trace` and `impact` use consistent exit status
and `E_*` diagnostics. `doctor --json` reports required tools, versions and
actionable missing-dependency states without developer-machine paths.

An external package can build, test and document itself through public CLI and
package contracts. Release tests cover multi-file workspaces, dependency
changes, adapter failure, cancellation, malformed protocol, cache tampering and
redaction.

## 9. Authority, memory and security

Tooling reads only admitted files and never follows workspace paths outside the
workspace root. Language-server requests, build metadata, trace input and
foreign error strings are untrusted and bounded. No tool executes project code
unless its command explicitly promises execution and the existing A86 runtime
authority checks still apply.

Logs, receipts and telemetry omit host-policy secrets, credentials and source
payloads by default. A digest proves equality only; it does not authenticate a
producer or grant access.

## 10. Representation and compatibility

A87 does not change Particle, AST, Wave, Wire, ONME, OSNMF or OCAP semantic
representations. The latest writer remains Wave20 / OMC20 and older programs
retain their lowest valid writer. Tool receipts and LSP messages are separate,
versioned tooling schemas and cannot be loaded as executable representations.

All A86 source remains compatible. Stable diagnostic codes are additive; tools
must tolerate unknown optional JSON fields while rejecting unknown required
schema versions.

## 11. Required gates

Required gates cover formatter idempotence and semantic equivalence; text/JSON
diagnostic parity and spans; LSP framing, lifecycle, versioning and workspace
escape negatives; clean/cache-hit byte equivalence and dependency/flag/runtime
invalidation; corrupt-cache rejection; source-map correlation; bounded profile
and coverage reports; inspector epoch/root/unknown-edge reporting; redaction;
fresh-checkout build/test/doc flow; evaluator/native regressions; sanitizers,
reproducibility, package integrity and the accumulated matrix.

application subsystem smoke remains consumer-only after the Core release. consumer integration follows
the certified A87 release and adopts only contracts proven by the interval.

## 12. Deferred work

A87 does not claim a production DAP debugger, optimizer-grade variable
reconstruction, distributed tracing backend, continuous profiler, remote build
farm, authenticated telemetry service, IDE UI, application subsystem activation, target parity,
or prolonged soak/chaos evidence. Target-native parity belongs to A88;
recovery/supply-chain hardening to A89; product convergence to A9/Initial
Release governance.
