> Distribution status: WIP / NOT_RELEASED. Technical version labels describe independent contracts, not public release certification.

# CP-17/18 SDK integration and descriptive exports

Status: implementation candidate in the integrated `0.1.0.00` WIP distribution. Scope is the
already approved AI-07 target context and module component descriptor, plus
distribution/conformance. This adds no language token or execution semantics.
Certification is determined by an external exact-SHA receipt, not this status.

## Distribution

The prebuilt SDK ships its advertised LSP, VERSION, public delta and normative
specifications. LSP uses Python's standard library and the installed compiler;
producer-only C++ build/package tools are not part of the consumer distribution.
The component inventory hashes every shipped file (excluding its own root);
the retained archive hash/receipt binds that inventory. Doctor validates indexed
bytes and required tools. Package locks separately bind resolved source bytes;
neither a manifest nor a lock proves static program validity or grants authority.
The consumer never rebuilds the C++ compiler; Clang/LLVM remains permitted.

The invocation loader build identity includes all local source/runtime/public
headers as well as translation units, scripts, flags and compiler identities.
Changing a shared header changes identity without requiring a .cpp change.
No existing invocation ABI or representation version is changed.

## AI-07: target context

`omni context --target T --for llm [--target-isa gpr|sse2]` emits descriptive
JSON `omni.target-context/1`. T is `linux-x86_64-gnu`, `baremetal-x86_64` or
`baremetal-i386-boot`; experimental targets reject with an existing diagnostic.
ISA selection applies only to freestanding profiles; i386 bootstrap has no
SSE2 assumption. Facts use the same selector as ordinary `target.*` folding.

The context includes SDK version, architecture/pointer width/endianness/hosted
state/features, existing canonical layouts, capability registry, ABI scope,
prohibited/deferred features and the memory-model scope. Intrinsic families
include their full shipped normative contracts, relative paths and SHA-256;
an installed inventory must identify and match the exact bytes read. Missing,
altered or symlinked contracts reject; absence of an inventory is only the
ordinary development-source layout, never an installed SDK integrity claim.
this is an LLM context, not the deferred AI-10 constrained-code schema or a
second signature registry. Contracts distinguish static admission, evaluator
models and target/backend/provider restrictions. No profile is promoted to
physical-hardware certification by this export. Unknown flags/targets reject
without partial stdout. The command executes no supplied user program.

## Per-module component descriptor

`omni component FILE [--target-profile PROFILE] [--target-isa gpr|sse2]
[--diagnostic-format text|json]` uses the ordinary loader/checker, then emits
`omni.component-contract/1`. It accepts the existing four representations.
It never evaluates, builds, writes a file/cache or applies an edit. Invalid
input is refused before metadata, with the ordinary diagnostic code.

One checked Program supplies content ID, OSNMF system root and all module/type/
function IDs and contracts. Modules/functions are ordered deterministically.
Each module describes imports, functions/templates, records and enums,
parameter/result/field types, recursive ownership/consumption classification,
declared/direct/required effects, linkage and ABI/profile constraints. Open
templates retain their existing OSNMF identities; unresolved parameter type
IDs/layouts are explicitly unavailable. Known layouts use existing rules;
unsupported/open layouts are null with a reason, never a fabricated size.
Visibility and checked generic-constraint spellings are descriptive; use the
ordinary checker/admission command to decide an actual call or substitution.
For a foreign declaration, `abi_id` hashes `omni.component-c-abi/1\n`,
`sysv-x86_64-integer-v1\n`, export name + newline, extern name + newline,
each canonical parameter type + newline, and `->` + canonical result type.
It is a separately named ABI identity, not an alias for an OSNMF contract ID.

Canonical data layout and native C ABI are distinct. C ABI metadata describes
the existing x86-64 SysV integer contract; i386 bootstrap is not a general C ABI.
Metadata does not assert that every checked function can be emitted/executed
under every profile. Existing backend/provider checks remain mandatory.

Declared/required capabilities are not grants. Outputs contain no live Resource,
loan, address, authority credential or invocation handle. OSNMF authority labels
remain provenance labels. `grants_authority=false`, with no granted capabilities.
All existing OSNMF IDs/roots and Wave/Wire/ONME versions remain unchanged:
`REPRESENTATION_COMPATIBLE_NO_BUMP`. Equal checked subjects under the same
profile yield equivalent descriptors, excluding source paths/trivia entirely.

## Acceptance and exclusions

Check facts against actual compile-time assertions, malformed/unknown options,
invalid program rejection, ownership/effect witnesses, exact OSNMF identities,
four-representation equivalence, installed tooling, header identity mutation,
ordinary/focal sanitizers and mutation with a clean baseline. Then the coherent
integration gate, installed SDK and unmodified genuine external consumer.
Keep the 120 IDs/24 groups/18 CP traceable without rewriting historical scope.
GitHub Actions is excluded by the owner; no remote PASS. The unique 45-minute
2 GiB campaign follows C3 acceptance and functional freeze. Six hours, public
publishing, new language features and other products remain outside scope.
