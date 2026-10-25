> Distribution status: WIP / NOT_RELEASED. Technical version labels describe independent contracts, not public release certification.

# Omni host invocation ABI — proposed Core 1.1.0.0

**Status:** `FROZEN_FOR_IMPLEMENTATION`
**ABI identifier:** `omni.module-invoke/1` (`OMI1`)
**Target:** `linux-x86_64-gnu` native embedding
**Authority:** normative contract for CORE-HOST-02/03; no 1.0.0.0 behavior is changed by this document.

**CORE-HOST-01A addendum:** §2's build identity and loader verification rules below supersede the earlier unqualified instruction to recompute every digest. The ABI and descriptor format version remain 1.

## 1. Scope and invariants

An embedding host can bind an exact compiled Omni module, submit a bounded dynamic request, invoke one designated public function, read a bounded typed result, destroy the invocation, and repeat in the same host process. Every call has a fresh runtime context. The module decides its application semantics; the host invokes and transports values. Module/artifact identity, a TypeID, an ABI handle, request bytes and a successful load are never effect authority.

The ABI adds no listener, daemon lifecycle, database, credential store, worker supervisor, provider or application-specific type. It does not change ordinary `main` execution. A host module artifact is a Core-built Linux ELF shared object with a single fixed Core-generated invocation descriptor/entry trampoline. The host uses the Core-supplied versioned loader interface; it never resolves an application function through arbitrary `dlsym` or calls a native function by its mangled name.

This is a new public runtime/tooling capability proposed for Omni Language `1.1.0.0`. Core `1.0.0.0` remains immutable. The public name of a future product/library is not frozen; the protocol identifier above is.

The generated module artifact has no executable load/unload constructors, TLS callbacks or mutable process-global initializer. Its dynamic dependencies are restricted to the exact matching Core loader/runtime and an allowlisted Linux C runtime set recorded in the descriptor/build receipt. `module_open` verifies those properties before loading executable bytes and performs no application/module effect. An arbitrary third-party ELF is outside the trusted compiled-module profile even if a caller supplies its digest.

## 2. Build selection, module identity and entrypoint

The build command for this profile is:

```text
omni build PACKAGE_ROOT --host-entry src/relative-module.omni:function -o ARTIFACT.so --offline
```

`--host-entry` selects exactly one `pub func` in a regular `.omni` file under the locked package `src/` tree. The compiler resolves that function and its import closure from the exact package/lock; the package's ordinary `entry` and `main` need not be the selected function. No source annotation, manifest rewrite, source-tree copy or runtime source lookup is required. A second public function requires a separately built artifact. Missing/private/ambiguous/generic/unresolved functions, unsafe paths, unlocked source and unsupported signatures fail the build. Selection is an explicit build input and participates in the artifact/build digest.

The only v1 host-entry build profile is `omni.module-invoke.native/1`. It fixes every artifact/codegen-affecting compiler option for this ABI. The compiler rejects an unsupported build-affecting override; it does not silently fold an unversioned flag into the identity. A required future codegen option must be represented by a versioned profile or descriptor field. Output path (`-o`), current working directory, cache path, temporary directory, diagnostic verbosity and `--offline` do not enter build identity. `--offline` constrains resolution; the resulting lock and semantic source hashes bind the resolved inputs. Environment values, timestamps and unrelated filesystem paths must not enter the build-input digest.

The selected function may have zero or more parameters, each an admitted owned value type (§3), and returns either an admitted owned value `T` or `Result<T,u32>`. It may declare only `pure` or existing A86 hosted effects (`fs.read`, `fs.write`, `process.spawn`, `net.connect`, `ffi.call`). `io.print`, borrowed or resource-bearing inputs/returns, open task/channel handles, captured non-transferable state and varargs are excluded from v1. No new Omni source keyword or effect is introduced. A `Result<T,u32>.Err` is an ABI-level semantic error; an application enum that encodes denial remains an ordinary semantic result for the application to interpret.

An embedded immutable OMID1 descriptor binds:

- ABI identifier and exact version `omni.module-invoke/1`;
- target ID `linux-x86_64-gnu`, Core runtime ABI ID `omni.module-invoke.runtime/1`, raw 32-byte `core_runtime_build_sha256`, raw 32-byte `compiler_sha256`, build profile ID `omni.module-invoke.native/1`, and selected package `(origin,name,version)`;
- SHA-256 of the exact package manifest, locked semantic source closure and package lock;
- selected normalized module path and public function name;
- ordered parameter TypeIDs, return TypeID, declared effect set and signature digest;
- deterministic build-input digest over the exact material below (excluding artifact bytes) and descriptor format version 1.

The signature digest remains `SHA256("omni.module-invoke.signature/1\n" || signature_material)`. `signature_material` is the following exact sequence of length-prefixed fields: ABI identifier, package origin, package name, package version, manifest SHA-256, locked semantic source SHA-256, selected module path, selected function name, parameter count encoded as `u32le`, each ordered parameter TypeID raw digest, return TypeID raw digest, effect count encoded as `u32le`, and each effect name in sorted UTF-8 byte order. A length-prefixed field is `u32le(byte_length) || exact bytes`; hashes and TypeIDs are raw 32-byte values, strings are UTF-8 without NUL, and integer/count fields are four raw little-endian bytes. No Unicode normalization occurs after the compiler has canonicalized identity strings.

The canonical embedded descriptor is exactly the following concatenation, with no padding or trailing bytes:

```text
bytes("OMID1\0\0\0")
u32le(1)                                   // descriptor_format_version
length_prefixed(ABI identifier)
length_prefixed(package_origin)
length_prefixed(package_name)
length_prefixed(package_version)
manifest_sha256                            // raw 32 bytes
locked_semantic_source_sha256              // raw 32 bytes
length_prefixed(normalized_selected_module_path)
length_prefixed(selected_function_name)
u32le(parameter_count)
parameter TypeID[parameter_count]          // ordered, each raw 32 bytes
return TypeID                              // raw 32 bytes
u32le(effect_count)
length_prefixed(effect_name)[effect_count] // sorted UTF-8 byte order
length_prefixed(target_id)
length_prefixed(core_runtime_abi_id)
core_runtime_build_sha256                  // raw 32 bytes
compiler_sha256                            // raw 32 bytes
length_prefixed(build_profile_id)
lock_sha256                                // raw 32 bytes
signature_digest                          // raw 32 bytes
build_input_digest                        // raw 32 bytes
```

The `build_input_digest` is `SHA256("omni.module-invoke.build-input/1\n" || BUILD_INPUT_MATERIAL)`. `BUILD_INPUT_MATERIAL` is exactly this concatenation, in order:

```text
length_prefixed(ABI identifier)
u32le(descriptor_format_version)
length_prefixed(target_id)
length_prefixed(core_runtime_abi_id)
core_runtime_build_sha256                  // raw 32 bytes
compiler_sha256                            // raw 32 bytes
length_prefixed(build_profile_id)
length_prefixed(package_origin)
length_prefixed(package_name)
length_prefixed(package_version)
manifest_sha256                            // raw 32 bytes
locked_semantic_source_sha256              // raw 32 bytes
lock_sha256                                // raw 32 bytes
length_prefixed(normalized_selected_module_path)
length_prefixed(selected_function_name)
signature_digest                          // raw 32 bytes
```

The parameter and effect sequences enter build-input identity only through the raw `signature_digest`; they are not duplicated in `BUILD_INPUT_MATERIAL`. The exact compiler executable's SHA-256 is measured at build time. `core_runtime_build_sha256` is the published raw 32-byte canonical build identity of the exact matching Core invocation loader/runtime build; the compiler records the value supplied by that runtime build, and the installed loader compares it to its own build identity. It is not a hash of a descriptor containing itself. The runtime build identity and runtime ABI ID are separate checks.

`module_open` follows this verification sequence before executing module code: (1) hash the exact ELF bytes to be loaded and compare with `expected_artifact_sha256`; (2) extract OMID1 from those same bytes without a path-replacement or symlink race; (3) hash the complete descriptor and compare with `expected_descriptor_sha256`; (4) parse it canonically and reject unknown version, wrong ABI/target, wrong build profile, unknown or trailing bytes; (5) compare the runtime ABI ID and build identity to the installed loader/runtime; (6) recompute the signature and build-input digests from their complete canonical descriptor preimages and reject mismatches; (7) validate the selected fixed entry and load only the bytes verified. Artifact size and ELF safety checks occur before unsafe mapping/allocation. A digest mismatch, wrong target, wrong build profile or wrong runtime build identity is `IDENTITY_MISMATCH`; unsupported descriptor or runtime ABI/version is `UNSUPPORTED_ABI`. No mismatch falls back to a different module.

The loader does **not** independently recompute manifest, semantic source or lock hashes from a source checkout, nor compiler SHA-256 from an absent compiler executable. Those are build-time provenance attestations embedded in the immutable descriptor, covered by both descriptor and artifact SHA-256, and linked by build/release evidence. Recomputed signature and build-input digests establish internal descriptor consistency; they do not prove the provenance of those input attestations. Artifact SHA-256 proves exact ELF identity; descriptor SHA-256 proves exact descriptor identity; the runtime ABI/build comparison proves installed-runtime compatibility. No one digest substitutes for all claims.

The build tool emits an external machine-readable `omni.module-invoke.build-receipt/1` record containing at least: schema, ABI identifier, build profile ID, compiler SHA-256, Core runtime build SHA-256, package origin/name/version, manifest/semantic-source/lock SHA-256, selected host entry, signature digest, build-input digest, descriptor SHA-256 and artifact SHA-256. It is emitted outside or alongside the artifact and is never embedded back into the ELF, avoiding artifact self-hash recursion. Deployment/release tooling must compare receipt fields to the canonical descriptor, recompute descriptor/artifact hashes from the actual deployed bytes, and reject a mismatch before providing expected hashes to the loader. Provenance authority comes from accepted build/release evidence, not from an unauthenticated receipt by itself. The loader does not need a receipt path at runtime. The installed bundle includes the matching Core 1.1 loader/runtime and declared native dependencies, with no developer checkout or compiler.

The same compiler, runtime, profile, source, lock, host entry and target produce the same signature and build-input digests regardless of output path, working directory, cache path or temporary directory. Artifact byte reproducibility is a separate claim and must not be inferred from build-input digest equality.

## 3. Invocable value profile and `OMI1` codec

The v1 profile admits owned `bool`, fixed-width signed/unsigned integers through 64 bits, `Char`, `Text`, `Bytes`, closed non-recursive public records/enums, fixed arrays, tuples, `Option<T>` and `Result<T,E>` recursively when all members are admitted by the existing checker. This codec does not legalize a type form that the language currently rejects. Float values, dynamic/unbounded containers, `Resource`, `Borrow`, `BorrowMut`, `View`, `Future`, `Stream`, closures, host handles and Authority are not serializable through `OMI1`. Unsupported signatures fail the build, not at an arbitrary runtime cast. Nominal types use the existing canonical `omni.type/1` TypeID; TypeID is identity only and never authority.

`OMI1` is a new external invocation-value format. It is not Particle, AST, Wave, Wire, ONME or OSNMF. A request/result frame is:

```text
offset  size  field
0       8    magic = bytes 4f 4d 49 56 31 00 00 00  ("OMIV1\0\0\0")
8       4    format version = u32le(1)
12      4    kind = u32le(1 request | 2 result)
16      32   selected entry signature SHA-256
48      4    payload byte length, u32le
52      4    top-level item count, u32le
56      N    encoded values; N equals payload byte length
```

There are no padding bytes or trailing bytes. Request item count equals the selected function's parameter count. A semantic result frame has one item, including a top-level `Result.Err`. The only accepted frame version is 1. A wrong signature, kind, count, type, length, canonical encoding or surplus byte fails before invoking the function. A zero-parameter request has an empty payload; zero-length `Text` and `Bytes` values are valid. A null host pointer is valid only with length zero, and no pointer is retained.

Each encoded value begins with one tag byte and the raw 32-byte SHA-256 part of its expected `omni.type/1` TypeID, then its payload. The descriptor determines the expected type at every position; the decoder compares both tag and TypeID before constructing a value. Tags are fixed as follows:

| Tag | Value payload |
| --- | --- |
| `0x01` | `bool`: one byte `0` or `1` |
| `0x02`–`0x05` | `u8`, `u16`, `u32`, `u64`: exact-width little-endian unsigned |
| `0x06`–`0x09` | `i8`, `i16`, `i32`, `i64`: exact-width little-endian two's complement |
| `0x0a` | `Char`: `u32le` Unicode scalar; surrogates/out-of-range reject |
| `0x0b`, `0x0c` | `Text`, `Bytes`: `u32le` length followed by exactly that many bytes; Text is valid UTF-8 without NUL |
| `0x0d` | tuple: `u16le` arity, then values in declared order |
| `0x0e` | fixed array: `u32le` count, then values in index order; count equals the type's fixed length |
| `0x0f` | record: `u16le` field count, then fields in declaration order |
| `0x10` | enum: `u16le` zero-based declared variant index, `u8` payload count (`0` or `1`), then its declared payload if present |
| `0x11` | `Option<T>`: `u8` variant (`0 None`, `1 Some`), followed by a value only for Some |
| `0x12` | `Result<T,E>`: `u8` variant (`0 Ok`, `1 Err`), followed by exactly one value of the selected arm |

No host/native struct padding, pointer, vtable, resource handle, arbitrary symbol or executable representation crosses this format. Integer overflow, invalid bool/Char/Text, unexpected variant, recursive depth above 32, value-node count above 65,536, truncated field, size arithmetic overflow and noncanonical extra bytes reject the frame. Nested type identity is checked against the exact compiled signature descriptor. The encoder produces one canonical byte sequence per admitted value. The decoder never upgrades a malformed or unknown frame version.

## 4. ABI result and failure domains

The outer invocation status is separate from the typed Omni return value. Stable v1 status codes are:

| Code | Name | Meaning |
| ---: | --- | --- |
| 0 | `SEMANTIC_OK` | Function returned `T` or top-level `Result.Ok(T)`; one typed result frame is readable. |
| 1 | `SEMANTIC_ERR` | Function returned top-level `Result.Err(u32)`; that exact typed result frame is readable. |
| 2 | `MALFORMED_INPUT` | Request frame/type/length failed validation before call. |
| 3 | `IDENTITY_MISMATCH` | Artifact, package, lock, descriptor or signature differs from expected identity. |
| 4 | `UNSUPPORTED_ABI` | ABI/codec/runtime version unsupported. |
| 5 | `ENTRYPOINT_MISSING` | Selected entry absent or invalid in artifact. |
| 6 | `LIMIT_EXCEEDED` | Declared request/result/allocator/diagnostic bound exceeded. |
| 7 | `AUTHORITY_DENIED` | Invocation policy malformed, excess or invalid for the selected entry before execution. A denied hosted effect is delivered to Omni source as its existing A86 typed error. |
| 8 | `DEADLINE_EXCEEDED` | Deadline observed without an unresolved external effect. |
| 9 | `CANCELLED` | Cancellation observed without an unresolved external effect. |
| 10 | `RUNTIME_FAILURE` | Recoverable runtime fault/trap; no valid semantic result. |
| 11 | `UNKNOWN_OUTCOME` | Invocation terminated while an external effect may have occurred without a complete acknowledgement. |
| 12 | `INVALID_HANDLE` | Stale, destroyed, wrong-kind or cross-module/context handle. |
| 13 | `BUSY` | Operation conflicts with an active invocation/reader. |
| 14 | `POISONED` | Detected unrecoverable runtime invariant failure; binding cannot be invoked again. |
| 15 | `ALREADY_TERMINAL` | Cancellation arrived after the invocation reached a terminal state. |

`SEMANTIC_ERR` describes the module's `Result.Err`; it does not authorize the host to reinterpret application-defined denial enums. An effect `DENIED` returned to Omni source remains governed by the existing A86 typed host error; the module may handle it. An unrecoverable native corruption that prevents safe status return may terminate the host process. It never permits silent reuse of a suspect binding.

Each terminal outcome also carries an independent effect observation: `NONE`, `ACKNOWLEDGED`, or `UNCERTAIN`. `NONE` means no hosted effect crossed dispatch during this invocation. `ACKNOWLEDGED` means every dispatched effect has a complete valid acknowledgement; it does not assert business finality. `UNCERTAIN` is sticky when any effect may have occurred without a complete acknowledgement. A normal semantic return may coexist with `UNCERTAIN`; the host must pass both facts to the application and cannot relabel the effect as failed or successful. If execution aborts on timeout/cancellation/runtime failure while `UNCERTAIN`, the outer status is `UNKNOWN_OUTCOME`. No result frame is returned for statuses 2–15. Diagnostics are bounded and redacted; they cannot carry request, secret or effect authority.

When more than one invalid condition is present, validation order is fixed: `module_open` checks artifact size/safety and exact artifact digest, descriptor digest, canonical descriptor version/ABI/target, installed runtime identity, recomputed signature/build-input digests, then selected entry; `invocation_create` checks handle/state, scalar bounds, complete OMI1 frame, then OHP1 policy/generation. No semantic or hosted effect occurs on either rejection path. During execution, sticky `UNCERTAIN` takes precedence over timeout/cancellation/runtime failure when no complete semantic result exists; otherwise a complete semantic return has its normal `SEMANTIC_OK`/`SEMANTIC_ERR` status with the independent effect observation. For simultaneous observed cancellation and deadline before dispatch, cancellation wins. This order may not be changed by an optimizer or backend.

## 5. Conceptual ABI lifecycle and handle rules

The Core 1.1 Linux loader exposes only the following versioned operations through its fixed public C header. These are contractual declarations, not H01 implementation:

```c
uint32_t omni_invocation_v1_module_open(
    const uint8_t *absolute_path, uint32_t path_len,
    const uint8_t expected_artifact_sha256[32],
    const uint8_t expected_descriptor_sha256[32], uint64_t *out_module);
uint32_t omni_invocation_v1_invocation_create(
    uint64_t module, const uint8_t *request_frame, uint32_t request_len,
    const uint8_t *ohp1_policy, uint32_t policy_len,
    uint64_t expected_policy_generation, uint64_t absolute_deadline_ns,
    uint64_t allocation_limit, uint32_t result_limit,
    uint32_t diagnostic_limit, const uint8_t trace_id[16],
    uint64_t *out_invocation);
uint32_t omni_invocation_v1_invoke(
    uint64_t invocation, uint32_t *out_effect_observation,
    uint32_t *out_result_frame_length);
uint32_t omni_invocation_v1_cancel(uint64_t invocation);
uint32_t omni_invocation_v1_result_read(
    uint64_t invocation, uint8_t *output, uint32_t capacity,
    uint32_t *out_copied);
uint32_t omni_invocation_v1_diagnostic_read(
    uint64_t invocation, uint8_t *output, uint32_t capacity,
    uint32_t *out_copied);
uint32_t omni_invocation_v1_invocation_destroy(uint64_t invocation);
uint32_t omni_invocation_v1_module_close(uint64_t module);
```

The Core-supplied loader is a versioned native library with exactly these fixed `omni_invocation_v1_*` C symbols. The generated artifact exposes fixed `omni_module_v1_descriptor` and `omni_module_v1_entry` symbols to that loader; direct application calls to the trampoline are outside the supported ABI. Application function names are never native symbol names in this API. All functions use Linux x86-64 System V C calling convention; no C++ exception or unwind crosses the boundary. Return value is the status code in §4, with `0` meaning success for lifecycle/read operations. An output pointer is required and must be non-null; null is `MALFORMED_INPUT`. A byte-span input pointer may be null only when its length is zero; fixed hash and trace pointers must point to their complete indicated size. Invalid non-null C addresses are caller misuse outside the ABI guarantee. The loader validates lengths before reading spans and retains no host pointer. `out_effect_observation` uses `0 NONE`, `1 ACKNOWLEDGED`, `2 UNCERTAIN`. On nonsemantic terminal failures `out_result_frame_length` is zero. Hashes are 32 raw bytes, trace identity is 16 opaque bytes, and handles are opaque generation-checked `u64` values. No C struct layout is an Omni value. Artifact paths are absolute UTF-8 byte spans of at most 4096 bytes; no search path, relative path or symlink follows from a module identity. `expected_descriptor_sha256` is the SHA-256 of the canonical embedded descriptor bytes and binds every field in §2.

`module_open` moves the binding from absent to `OPEN`; successful `invocation_create` creates `CREATED`; `invoke` moves it to `RUNNING` then exactly one `TERMINAL` outcome; `invocation_destroy` moves it to `DESTROYED`. A malformed request or invalid policy at `invocation_create` returns a status with no handle and releases all temporary allocations. A `POISONED` module can only be closed after its contexts are destroyed. `module_close` returns `BUSY` while a context exists. Destroying a running invocation returns `BUSY`; the host must cancel and wait for terminal cleanup first. Reusing, double-destroying or crossing a handle between modules fails with `INVALID_HANDLE` and cannot free a different live object. Generation wrap fails closed rather than reusing a stale identifier.

`result_read` is allowed once after `SEMANTIC_OK` or `SEMANTIC_ERR`; it copies the complete canonical result frame into host-owned storage. Capacity below the announced length returns `LIMIT_EXCEEDED` without partial copy or consumption and sets `out_copied` to the required length. A successful read sets `out_copied` to the copied length and consumes the stored result. `diagnostic_read` similarly copies at most one bounded, redacted UTF-8 diagnostic after a terminal `invoke`; zero diagnostic bytes are valid, and an insufficient buffer returns the required length without partial copy. No returned pointer aliases runtime memory. `invocation_destroy` releases any unread result/diagnostic and every context-owned temporary resource exactly once. The host owns and frees its input/output buffers; Core copies input before execution and never retains their addresses. A host may reuse or free an input buffer immediately after successful `invocation_create`.

## 6. Context, state, bounds and ownership

Each invocation owns fresh allocator accounting, runtime fuel/ticks, task/channel tables, temporary `Bytes`/`Text`, error/diagnostic state, trace identity, cancellation state, deadline and OHP1 grants. All mutable runtime state is destroyed on every terminal path. Immutable compiled code, constants, type descriptors and verified module metadata may be shared by later invocations. No mutable `static`, TLS or heap object from one call may influence the next unless the application explicitly passes state in a later request or uses an authorized external effect. The host cannot retain an Omni pointer and Omni cannot retain a host pointer.

For v1 the complete request/result frame maximum is 1,048,576 bytes each, including the 56-byte header. The caller may choose smaller positive maxima. The OHP1 policy copy is at most 65,536 bytes; an empty policy means deny all host effects. The diagnostic maximum is 16,384 bytes, with caller-selected smaller maximum including zero. The total mutable Core allocation quota per invocation is at most 67,108,864 bytes, with a positive caller-selected smaller quota; it includes request/result copies, decoded values, task/channel storage and diagnostics. Compiler-generated static code and immutable module metadata are outside that per-call quota and must be bounded separately by a maximum 268,435,456-byte artifact. Allocation accounting must cover all Core runtime allocation sites; no fallback to untracked allocation is allowed. Quota exhaustion returns `LIMIT_EXCEEDED` after cleanup. Size limits are checked with overflow-safe arithmetic before allocation or copy. An invocation deadline must be finite, strictly positive and at most 300 seconds from the current monotonic clock at creation.

Host-created buffers are never borrowed across `invocation_create` return. Result bytes are Core-owned until copied by `result_read` or discarded by `invocation_destroy`. `Resource`, `Borrow`, `BorrowMut`, `View` and opaque Authority cannot cross `OMI1`. Zero-length Text/Bytes have a valid canonical encoding and distinct type tags. A zero-length frame is invalid because it lacks the header.

## 7. Deadline and cancellation

The host supplies an absolute `CLOCK_MONOTONIC` deadline in nanoseconds. Core checks it at context creation, before semantic dispatch, at bounded compiler/runtime safe points (including loop backedges and function calls), and immediately before every hosted effect. Long-running runtime primitives must be chunked or bounded so the deadline is observed; hosted operations receive the smaller of their own deadline and the invocation deadline. A85 logical task deadlines retain their existing meaning and are not reinterpreted as wall-clock deadlines.

`cancel` atomically marks a runtime-owned cancellation state. It is the only operation permitted from another host thread; it never dereferences a destroyed handle or retains a host pointer. It is idempotent while the invocation is `CREATED` or `RUNNING`; after terminal it returns `ALREADY_TERMINAL`. Cancellation is observed at the same safe points as the deadline and by blocking hosted effects. If both are already active at one safe point, cancellation wins. A `cancel` request does not itself prove that the module stopped or that an external effect did not occur; the host waits for a terminal outcome and cleanup.

Before any semantic/effect dispatch, an expired deadline returns `DEADLINE_EXCEEDED` and observed cancellation returns `CANCELLED`, with effect observation `NONE`. Once a hosted effect has crossed dispatch, a timeout, cancellation, lost ACK or runtime failure returns `UNKNOWN_OUTCOME` if the effect's application cannot be ruled out. A fully acknowledged effect may yield a later `CANCELLED` or `DEADLINE_EXCEEDED` with effect observation `ACKNOWLEDGED`; the host must not treat those statuses as proof that the acknowledged effect did not occur. Core never blind-retries. The A93 causal phase oracle (`PRE_DISPATCH`, `DISPATCHED`, `ACKNOWLEDGED`) governs these classifications.

## 8. Effect authority

`module_open` grants no effects. `invocation_create` accepts an explicit copied OHP1 policy or empty deny-all. The Core parser validates the policy using A86 rules before semantic execution. Its grants must be a subset of the selected entry's declared effect capabilities, with exact scopes, generation, expiry and quantitative limits. A nonempty policy requires positive `expected_policy_generation` equal to its OHP1 generation; empty deny-all requires zero. Unknown/excess capabilities, malformed policies and mismatched generation reject. Every effect is checked again immediately before dispatch. Policy is per invocation, never inherited by the next call. Module name, package/version, content digest, host PID/UID, entrypoint, trace ID, TypeID, payload and prior invocation outcome never confer capability. The host has no application/tenant authority merely by supplying an OHP1 grant; application policy still decides whether and how to use it.

## 9. Serial execution, thread confinement and failure isolation

V1 permits one active `invoke` per process-wide Core loader instance. All operations on module/invocation handles except `cancel` are serialized on the owning host thread; `cancel` is safe from another thread and linearizes at an atomic state transition. Different native worker processes may open the same exact artifact and invoke independently. This contract does not promise parallel execution within one process or a general thread-safe Omni runtime. A concurrent second `invoke` returns `BUSY` before it changes either context. Handle destruction is synchronized with in-flight cancellation operations.

A malformed frame, semantic `Err`, recoverable runtime fault, cancellation, timeout or ordinary effect denial destroys its context and must not corrupt a later independent call. Detected invariant failure poisons the binding; later invocation returns `POISONED`. The loader never reports a poisoned binding as healthy. A foreign library that violates its own ABI or an undetectable native memory corruption may terminate the host process; the capability is not an arbitrary-code sandbox. H02/03 must prove the recoverable paths with sanitizers and a real host process.

## 10. Evaluator/native and compatibility ledger

Native `linux-x86_64-gnu` embedding is the production claim. The evaluator must match native for selected function typing, `OMI1` decode/encode, semantic values, malformed-input denial, capability checks, request isolation, typed errors and causal outcome classification under the same deterministic test fixtures. Wall-clock scheduling, Linux loader behavior and actual process/FFI/socket effects are native-only real-boundary tests; evaluator results do not substitute for them.

| Layer | V1 impact and fence |
| --- | --- |
| Particle/AST/source | No new Omni syntax. Existing `pub func` is selected by explicit build flag. |
| Wave/Wire/OMC | Existing Wave20/OMC20 writer selection and reader rules remain unchanged; no executable form is added. |
| ONME/OSNMF/OCAP | ONME2, OSM2/OSMI2, OSMC1/OSMT1 and OCAP1 remain unchanged. No host grant or live pointer is serialized into them. |
| Package manifest/lock | `omni.package/1` and `omni.lock/2` remain unchanged. Selection, target and build identity enter the artifact receipt/descriptor, not the package source lock. |
| New external representation | `OMI1` frame version 1 and descriptor version 1; unknown versions reject. Its `omni.type/1` IDs are checked, not used as authority. |
| Native artifact | New explicitly built module artifact and fixed ABI. Core 1.0 executables remain valid; an old loader does not claim to open a v1 module. |

**Representation decision:** `REPRESENTATION_COMPATIBLE_NO_BUMP` for Particle/AST/Wave/Wire/ONME/OSNMF/OCAP; `OMI1` is a new separately versioned host-value format. A v1 frame cannot be relabeled as Wire/ONME. Downgrade to an earlier OMI version is unavailable and fails closed. Round-trip, malformed, wrong-version and identity-integrity cases are mandatory.

## 11. Release and evidence gate

Proposed Core version is `1.1.0.0`, an additive public runtime capability after immutable `1.0.0.0`. CORE-HOST-01 changes only this normative specification and architecture/governance documents. CORE-HOST-02 implements the generic Core capability; CORE-HOST-03 performs differential, native embedding, sanitizer, performance/resource and downstream consumer certification. Neither stage may modify the certified tags/receipts. The machine-readable acceptance matrix is `docs/governance/requirements/CORE_HOST_INVOCATION_ACCEPTANCE_MATRIX.json`.

The downstream application subsystem test selects an existing public function such as `application subsystem-v1.0.0:application subsystem-ecu/omni-application subsystem/src/execution_fabric.omni:grant_use` from the exact immutable tagged source and lock. Its closed record/enum/u32 signature exercises the generic codec; no application subsystem 1.0 source is edited. This is consumer evidence, not a application subsystem-specific Core API or proof that a full application subsystem Host is production-ready.

Measure module load time, invocation overhead, peak per-invocation memory and repeated-call memory stability with recorded artifact/compiler/runtime/host identities. No latency or throughput SLA is frozen before those measurements exist.
