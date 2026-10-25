> Distribution status: WIP / NOT_RELEASED. Technical version labels describe independent contracts, not public release certification.

# Omni Hosted Effects and Foreign Boundary — 0.8.6

**Status:** `FROZEN_FOR_IMPLEMENTATION`  
**Language version:** `0.8.6-alpha.8`  
**Authority:** normative A86 contract

## 1. Scope and invariant

A86 introduces bounded filesystem, child-process, TCP and fixed-ABI foreign
effects. Every operation is dual-gated:

```text
declared source capability + matching runtime HostAuthority grant
    -> effect may be attempted
```

Neither half implies the other. Package identity, a hash, `DecisionEvidence`,
an observation, model confidence or an ordinary struct is never authority.
Missing, malformed, expired or out-of-scope authority fails before the effect.

## 2. Explicit runtime authority

The host supplies an `OHP1` policy through an explicit command-line option.
Evaluator and native execution use the same canonical policy parser and scope
rules. Environment variables, current-directory inference and source metadata
cannot silently broaden the policy.

An admitted grant contains a capability ID, canonical scope, generation,
not-after monotonic budget and quantitative limits. Unknown fields, duplicate
keys, absolute/relative ambiguity, traversal after normalization, NUL, invalid
UTF-8 and numeric overflow reject the policy. Revocation is represented by a
generation change; an operation revalidates immediately before the effect.

`HostAuthority` is runtime-owned and opaque. Omni source cannot construct,
serialize, copy or return it. The runtime context owns the grants and releases
them at program exit.

## 3. Source surface

The A86 built-ins use existing `Bytes`, `Text`, `Result<T,u32>` and declared
capabilities:

| Operation | Capability | Result |
| --- | --- | --- |
| `host.read(path, max_bytes)` | `fs.read` | `Result<Bytes,u32>` |
| `host.write(path, payload)` | `fs.write` | `Result<u32,u32>` |
| `host.process(adapter, payload, max_bytes, deadline_ticks)` | `process.spawn` | `Result<Bytes,u32>` |
| `host.tcp(endpoint, payload, max_bytes, deadline_ticks)` | `net.connect` | `Result<Bytes,u32>` |
| `host.ffi(library, payload, max_bytes)` | `ffi.call` | `Result<Bytes,u32>` |

The legacy `file.read_text` and `file.write_text` operations remain source
compatible but are routed through the same runtime policy and bounded error
model. They no longer imply ambient filesystem access.

Arguments are evaluated left-to-right before the host call. A failed effect
returns a typed numeric host error; malformed runtime state may trap only as an
internal invariant failure. No operation silently retries, changes adapter,
widens scope or converts a partial result into success.

## 4. Error contract

The stable A86 error codes are: `1 DENIED`, `2 INVALID_INPUT`, `3 NOT_FOUND`,
`4 IO_FAILURE`, `5 LIMIT_EXCEEDED`, `6 DEADLINE_EXCEEDED`, `7 CANCELLED`,
`8 PROTOCOL_MISMATCH`, `9 FOREIGN_FAILURE`, and `10 UNKNOWN_OUTCOME`.
Success uses the existing `Result` success discriminant and never carries a
non-zero error code.

Partial writes and a process/network timeout after dispatch are not reported as
clean failure when the effect may have happened; they return
`UNKNOWN_OUTCOME`. A85 cancellation is observed at defined safe points. A86
does not claim exactly-once execution.

## 5. Filesystem boundary

Filesystem grants name canonical roots separately for read and write. A path
must remain under an admitted root after normalization. Symlink/reparse-point
escape is rejected where the host can establish the final target; otherwise
the operation fails closed. Reads and writes are bounded by both the call and
grant limits. Writes use a create/truncate profile and report the committed
byte count only after the host reports success.

Text wrappers validate UTF-8. Byte operations do not reinterpret payloads as
text. No implicit search path, home expansion or network filesystem promise is
made.

## 6. Process adapter boundary

`host.process` executes only an exact executable identity admitted by policy.
The A86 protocol is a single request/single response, length-delimited copy
exchange over inherited pipes. The child receives no implicit shell, command
string, ambient credential injection or unbounded inherited handle set.

The handshake identifies `omni.host-process/1`, adapter identity and maximum
frame sizes. Wrong version, truncated frame, surplus frame, non-zero exit,
timeout, cancellation and output overflow are typed failures. Node and Python
fixtures use this same provider-neutral protocol; their names do not gain
special language semantics.

## 7. TCP boundary

`host.tcp` admits only policy-listed numeric endpoint identities in the A86
profile. DNS, listener sockets, TLS identity and credential stores are not
silently inferred. The operation performs one bounded connect/write/read
exchange with deadline propagation and explicit partial/unknown outcomes.
Responses beyond the declared limit are rejected without returning a prefix as
success.

## 8. Fixed foreign ABI

The only A86 dynamic-library entry point is `omni_ffi_v1`. Its C shape uses
fixed-width integers, byte pointers and explicit lengths. Input is borrowed for
the call; output is copied into a caller-owned bounded buffer. The callee never
owns Omni storage and cannot retain pointers after return.

The ABI starts with version negotiation and returns a tagged status. Endian is
irrelevant to the byte payload; structured payloads require their own declared
codec. No exception/unwind may cross the boundary. A library/symbol/version
mismatch, oversized length, invalid status or thrown foreign exception fails
closed. Shared memory, callbacks, raw Omni object layouts and arbitrary symbol
invocation are excluded.

## 9. Memory, cancellation and authority

Payload copies are bounded before allocation. Length arithmetic uses checked
operations. Cancelling a task releases runtime-owned buffers and child/socket
handles. Borrowed Omni references and `Resource<T>` values cannot cross any A86
boundary; callers must produce owned `Bytes`.

Every operation rechecks capability, grant scope, generation, remaining
deadline and limits immediately before dispatch. Selection, recommendation or
successful protocol validation is not authorization.

## 10. Representation and compatibility

Programs containing an A86 host operation require Wave20 / OMC20 and physical
header `OMCX+u32le(20)`. Programs without A86 forms retain the lowest valid
writer version. Readers 1..19 reject A86 executable forms with `E_VERSION`.
Downgrade may not erase an effect, grant requirement, bound, deadline or error
contract. ONME records the operation and required capability but never embeds
live authority or credentials.

Existing A85 source without host effects remains source compatible. Legacy file
operations now require matching runtime policy when executed; compile-time
capability checking is unchanged.

## 11. Required gates

Each operation requires checker/evaluator/native parity, missing-capability and
missing-grant negatives, malformed policy cases, scope escape, zero/max/overflow
bounds, cancellation/deadline, partial/late result and cleanup tests. Process
fixtures cover both Node and Python when those interpreters are present and
record `NOT_RUN`, never PASS, otherwise. TCP uses a local deterministic server;
no Internet dependency is a release gate. FFI uses a versioned fixture library
with malformed and throwing implementations.

Wave/Wire round-trip, downgrade rejection, unknown-version rejection,
sanitizers, reproducibility, package integrity and the accumulated matrix are
mandatory. The application subsystem smoke remains consumer-only.

## 12. Deferred work

A86 does not claim a security sandbox, TLS/provider authenticity, DNS policy,
listener/server API, shared memory, zero copy, general C ABI mapping, callbacks,
arbitrary dynamic symbols, credential management, distributed exactly-once,
application subsystem activation, staged deployment modes or production Node/Python orchestration.
Tooling/observability belongs to A87; target parity to A88; prolonged fault and
recovery hardening to A89.
