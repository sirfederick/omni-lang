> Distribution status: WIP / NOT_RELEASED. Technical version labels describe independent contracts, not public release certification.

# Omni Host SDK 1.2

**Status:** `FROZEN_FOR_IMPLEMENTATION`
**Release:** Core `1.2.0.0`
**Scope:** public, descriptor-bound access to the existing canonical `OMI1`
codec and portable distribution of `omni.std`.

## 1. Purpose and boundary

This contract adds a general Core host SDK. It is useful to any Omni host and
contains no application-specific components, provider, tenant, policy, or application type.

The SDK exposes the existing `omni.module-invoke/1` invocation ABI through a
stable C foundation and thin generated bindings. It does not add Omni source
syntax, effects, authority, a package registry, or a second serialization
implementation.

```text
Value != Resource != Borrow != BorrowMut != Authority
TypeID != authority
Decode success != authority
```

## 2. Compatibility decision

The release retains every existing representation and invocation identity:

```text
OMI1 = 1
OMID1 = 1
omni.module-invoke/1 = unchanged
Particle/Wave/Wire/ONME/OSNMF = unchanged
REPRESENTATION_COMPATIBLE_NO_BUMP
```

`OMIS1` is a new, separately versioned *SDK schema sidecar*. It describes a
compiled host entry's public value tree. It is neither an `OMI1` value frame
nor a modification of `OMID1`; old invocation loaders do not claim to expose
it. An `OMIS1` schema is accepted only after its roots and TypeIDs bind exactly
to the verified `OMID1` selected-entry descriptor.

## 3. Public C ABI

The installed header is `include/omni/omni_host_sdk_v1.h`; the library is
`lib/libomni_host_sdk_v1.so`; its namespace is `omni_host_sdk_v1_*`.

The ABI uses only fixed-width integers, caller-owned bounded buffers and
opaque `uint64_t` handles. It exposes no `OmniInvocationTypeV1`, C++ object,
AST pointer, runtime pointer, or private descriptor layout.

Public operations are:

```text
module_open / module_close / module_schema_read
module_request_count / module_request_node / module_result_node
schema_node_kind / schema_node_typeid / schema_node_child* / schema_node_label_read
value_create / value_destroy / value_kind / value_typeid
value_scalar_set/get / value_data_set/read
value_discriminant_set/get / value_child_set/get
request_encode / result_decode
```

All functions return existing invocation status codes where applicable. A
stale, wrong-kind, cross-module or destroyed handle returns
`OMNI_INVOCATION_V1_INVALID_HANDLE`; malformed host values and frames return
`OMNI_INVOCATION_V1_MALFORMED_INPUT`; bounds or allocation exhaustion return
`OMNI_INVOCATION_V1_LIMIT_EXCEEDED`. No API reports success with a partial
projection.

## 4. Descriptor and schema binding

`module_open` first performs the existing artifact and `OMID1` verification.
The loader then verifies the optional exported `OMIS1` byte blob before making
it available through a bounded copy API. `OMIS1` contains canonical type-tree
nodes and ordered request/result roots. A node contains only:

```text
kind tag, exact TypeID, nominal Record/Enum key, child arity/order,
fixed-array extent, enum variant arity/order, and public nominal labels.
```

The loader rejects a schema when its magic/version/canonical ordering/bounds
are invalid; when a root TypeID differs from the descriptor; when the supplied
nominal key and child shape cannot reproduce the stored Core TypeID; or when
depth exceeds 32 or nodes exceed
65,536. Labels are presentation metadata and do not select a layout or grant
authority.

The public encoder and decoder receive a verified module/schema plus the
selected request or result root. Callers cannot choose an arbitrary type for a
frame. `TypeID` is checked at every node but never acts as an authority token.

### 4.1 Bounded canonical TypeID cache

The codec implementation may retain a **bounded canonical TypeID cache** keyed
by the internal canonical type identity. This is an implementation economy
measure only: it neither authenticates a module nor authorizes an invocation,
and it does not alter OMI1, OMID1, descriptor, or OMIS1 bytes. A cache miss
falls back to the one canonical `semanticTypeId()` oracle; cache failure cannot
change protocol behavior.

The current bound conservatively reuses `OMI1_NODE_MAX`. That reuse is not a
wire contract or a statement that frame-node and process-cache cardinalities
are semantically equivalent. On a hit the canonical SHA-256 derivation is
avoided, while canonical identity construction and the bounded lookup remain
implementation work. A future module-local pre-materialized table requires
separate evidence; this specification does not claim one.

## 5. One codec law

There is one canonical OMI1 parser and writer. The private native-value adapter
and public SDK-value adapter must invoke shared framing, canonicality, bounds,
TypeID and structural traversal code. Node, Python and generated code call the
public C ABI and must not contain generic OMI1 tag, frame or TypeID hashing
logic.

The public builder constructs an opaque SDK value tree constrained by the
verified schema. `builder_finish` is the only public request-frame encoder.
`value_decode_result` is the only public result-frame decoder. The canonical
parser rejects wrong magic/version/kind/signature/TypeID/tag/arity, truncated
or trailing bytes, invalid bool/Char/UTF-8, invalid enum/Option/Result arms,
depth/node/length overflow and noncanonical encodings.

`value_child_get` returns an independent owned value handle containing the
selected child value. It is not a borrow or alias: destroying the parent does
not invalidate it; destroying that child handle invalidates only that handle.
The module remains busy while either handle is live.

## 6. Lifetime, threading and authority

A module owns immutable descriptor/schema state. A schema is an immutable
borrow-counted view of that module. Values, builders and encoded frames are
owned handles tied to one schema. Closing a module while dependent handles are
live returns `BUSY`; destroying any handle invalidates it permanently; double
destroy and cross-schema use fail closed. Text and bytes are copied into
caller buffers; no caller-visible pointer aliases runtime memory.

All operations except cancellation follow the existing owning-thread
invocation discipline. The SDK does not promise global thread safety or permit
cross-thread value mutation. It grants no capability and never infers
authority from a module, descriptor, artifact hash, TypeID, schema or decode.

## 7. Bindings and generation

The TypeScript and Python bindings are thin FFI wrappers over the C ABI. They
use `BigInt` and Python `int` for 64-bit values, `Uint8Array`/`bytes` for byte
values, and bounded copies for text. `omni sdk generate` may emit nominal
wrappers from a verified module schema; generated code contains names, fields,
variants and Core-supplied TypeIDs only, never an OMI1 codec.

An Enum variant without a payload is a labelled arm with no schema child:
`schema_node_child_count` counts it and `schema_node_label_read` names it, while
`schema_node_child` rejects that index with `OMNI_INVOCATION_V1_MALFORMED_INPUT`
and the selected value reports zero children. Generators record that arm as an
absent child and project it as a tag whose value is `null`/`None`; they do not
treat the rejection as a schema failure.

`value_scalar_get`/`scalarGet`/`scalar_get` always return the raw 64-bit bits
of a scalar regardless of kind; they carry no kind-specific coercion. Bool is
the one scalar kind whose declared generated type (`boolean` in TypeScript,
`bool` in Python) differs from that raw value, so a generated decode path
must coerce it explicitly (bits `!= 0`) rather than pass the bits through.

## 8. Portable standard library

The SDK archive installs the exact `omni.std` package under
`packages/omni.std/<package-version>/`. The resolver locates it through the
installed SDK root, validates its existing manifest/source commitments, and
never falls back to a checkout-relative path. Historical locks are not
rewritten; explicit offline relock is required if path relocation changes a
consumer lock location. The verified predecessor bytes are authoritative,
including the actual lock identity rather than a value copied from a prompt.

## 9. Required tests

The implementation must provide positive, negative and evaluator/native
differential coverage for all admitted scalar and composite types; stale and
cross-module handles; schema/descriptor identity tampering; malformed OMI1;
bounds; Node and Python real consumers; fresh extraction without a checkout;
and sanitizer/fuzz coverage of the public ABI. A application subsystem fixture is read-only
consumer evidence only and adds no product semantics to Core.

## 10. Deferred

Go/Rust/Java/C# bindings, a remote registry, publisher identity, arbitrary
dynamic containers, zero-copy foreign buffers, a general thread-safe runtime,
and application subsystem/application subsystem semantics are outside this release.
