> Distribution status: WIP / NOT_RELEASED. Technical version labels describe independent contracts, not public release certification.

# Option of Resource — CP-01a candidate

**Status:** `CANDIDATE` (OMNI-CORE-PRO-FOUNDATION-001, OM-016/OM-031). Not adopted, not certified.
**Representation:** Wave21 / OMC21 (shared fence with `BORROW_RETURN_REGIONS_CANDIDATE.md` and `BIT_INTRINSICS_CANDIDATE.md`).
**Authority:** extends `MEMORY_LIFECYCLE_0_8_3.md` and `ADTS_0_2.md`; weakens no rule of them.

## 1. Problem

`Option<Resource<T>>` is rejected (`E_TYPE`) although `Result<Resource<T>,E>` is a first-class owned
value. Slots, optional handles and "maybe a resource" return values therefore cannot be expressed.

## 2. Contract (v1)

1. **Admitted type.** `Option<Resource<T>>` where the payload is exactly a `Resource`. `Option<Borrow>`,
   `Option<BorrowMut>`, `Option<View>`, `Option<Future>` and `Option<Stream>` remain rejected.
2. **Linear value.** A binding, parameter or temporary of that type is *pending* exactly like a `Result`:
   it must be consumed exactly once, by `match`, by being returned, or by being passed to a call.
   Using it twice is `E_RESULT_MOVED`; leaving scope or returning with it unconsumed is `E_RESULT_UNHANDLED`.
   `None` is also pending (no data-dependent leniency); this is deliberately conservative.
3. **Payload ownership.** `Some<Resource<T>>(move(x))` moves `x` (use after is `E_RESOURCE_MOVED`). In
   `match o { Some(r) {...} None {...} }` the arm binding `r` is an owned `Resource` with the ordinary
   structured cleanup; the `None` arm owns nothing.
4. **No hiding places.** `Option<Resource>` cannot be a field of a `struct`, an `enum` payload, an element
   of `Array`/`Tuple`, a part of `Result` or `Option`, or be captured by a closure
   (`E_TYPE` / `E_PRODUCT_LINEAR` / `E_CLOSURE_CAPTURE`). Those need a recursive ownership model (later slice).
5. **No new cleanup path.** Because the value must be consumed by `match`, no cleanup is emitted for an
   `Option` itself; the backend needs no tag-dependent destructor.
6. **No new authority**; effects and capabilities are unchanged.

## 3. Representation fence

A program mentioning `Option<Resource<…>>` in a signature, a declared type or a constructor annotation is
encoded only as Wave21 / OMC21. Older readers reject it with `E_VERSION`.

## 4. Acceptance

`tests/language_0_8_3_alpha8.py::A83OptionResourceTests`: positives (let/match, return and parameter,
`None` path), evaluator/native parity, a 3000-cycle slot-exhaustion leak oracle (runtime limit 1024),
negatives for every rule above without artifact, fence by relabeling, wave/wire/ONME round-trip.


## Nominal resource amendment (CP-01, frozen for implementation, 2026-10-20)
`Option<Resource<R>>` for a valid nominal resource uses the same pending ledger as
`Option<Resource<Buffer>>`: exactly one match, call transfer, or return, including None.
The Some arm acquires the payload's ordinary obligation: Buffer has structured automatic
cleanup; a nominal Resource<R> MUST be consumed explicitly (E_RESOURCE_UNCONSUMED).
Some construction transfers its Resource once; reuse of the original owner is E_RESOURCE_MOVED.
Dropping/copying/repeating an Option is E_RESULT_UNHANDLED/E_RESULT_MOVED/E_RESULT_FLOW.
Returning an Option transfers its obligation to the caller; it does not destroy the payload.
No cleanup for the Option itself, no numeric handle exposure or new authority. Borrow,
BorrowMut, View, async values, nesting/containment and retained closure captures remain rejected.
This supersedes the earlier temporary rejection of all nominal Options in the integration
reconciliation; that rejection is retained historically as protection before this law was proved.
Representation: existing Option/Resource type grammar, Wave21/OMC21 minimum (or 22 for an
authoring capsule). No version bump: the complete semantics are expressible already.
Earlier candidate compilers may reject the newly supported combination; source/spec SHA
identifies the development snapshot. Old version relabels reject E_VERSION. No runtime
resource instance or authority is serialized. Canonical nominal identity and OSNMF source/
Wave/Wire/ONME parity are required. Evaluator/native observations MUST agree.
REPRESENTATION_COMPATIBLE_NO_BUMP. Partial aggregates and collections remain outside this delta.

## Owning record payload amendment (CP-01, frozen for implementation)

`Option<R>` also uses the pending ledger when R is a nominal record with recursive
Resource leaves. This includes generic record instances and nested records. Record
construction/transfer requires explicit moves of all Resource leaves; an existing
record is transferred with `move(record)`. Matching Some introduces the ordinary
projected owner, whose live Buffer leaves are cleaned on every structured exit.
None still carries a pending obligation. There is no destructor on Option itself:
match/call/return transfers the sole obligation, so stale Option storage is never
cleaned a second time. Mutable pending bindings and `_` payload discard are errors.
Loans on any leaf forbid transferring its aggregate. Reuse, conditional consumption,
loop replay, and closure capture obey the same errors as direct Resource Options.

This amendment does not yet admit nested pending values, nominal Resource fields,
owning Tuple/Array or owning enum payloads inside Option. Those obligations remain
open in CP-01; they cannot be treated as closed by this increment. Existing Copy
Options retain Copy semantics. No authority or runtime handle is serialized.

The complete record/Option grammar is unchanged. Wave21/OMC21 is the minimum for
this combination, including signature-only use and aliases/imports; lower labels
must fail E_VERSION. Wave/Wire/ONME round trips preserve the same ownership checks.
Evaluator and LLVM already share record-payload binding and structured cleanup;
their equivalence requires positive, negative and repeated allocation oracles.
This is development scope, not a certified release or a closed parent CP.

OSNMF function ContentID MUST distinguish different complete bodies even when
an isolated function cannot select a Wave fence without its nominal definitions.
The fallback is domain-marked canonical Particle of that function, including
generated bodies and authoring templates; instruction count is forbidden as
identity material. StableEntityID, ContractID and TypeID do not change merely
because a body literal changes. Existing OSM2/OSMI2 record grammar is unchanged;
historical stores and certified hashes are preserved, never rewritten. New
projections of affected bodies receive corrected ContentID/provenance/root hashes.
Unchanged successful Wave fingerprints retain their original material. Unexpected
serialization errors and limits propagate; no empty/size-only PASS fallback exists.
Lowered closure helpers also contribute their complete body to their individual
function ContentID. Their normal omission from public Wave is not an omission
from identity material. Visibility flags are normalized only on the temporary
hash projection; executable provenance and public representation stay unchanged.
ONME loading must preserve the projection checked against its committed root.
`parseONME` performs full semantic validation before checking executable integrity;
the loader must not lower it again and duplicate closure helpers. This is not a
validation bypass: forged semantic payloads with a recomputed envelope commitment
must still fail ownership checks; forged executable roots must fail E_ONME.

## ONME root algorithm fence (CP-15, frozen compatibility repair)

ONME3 uses the same length/opcode payload grammar as ONME2, but its R/P roots use
complete function identities, including lowered closure bodies and canonical
fallback bodies. Its commitment domain is `omni.onme-envelope/3`. The writer uses
ONME2 only when both executable and authoring roots equal their historical ONME2
projections; otherwise it MUST emit ONME3. Old readers reject ONME3 with E_VERSION.

The new reader retains ONME2: validate its payload with the CURRENT checker, then
verify the historical ONME2 root algorithm and `/2` envelope commitment. Historical
statement-count/omitted-helper material is allowed ONLY inside this compatibility
root calculation, never as an active function ContentID or as runtime authority.
The complete encoded body remains bound by the envelope and program-IR hashes.
Return the current checked program and its current projection. Never accept a
current root merely because a historical-root check failed, or vice versa.
ONME3 checks ONLY current roots and `/3`; relabel/recommit downgrade or upgrade
must fail root verification when the algorithms differ. Unsupported versions,
malformed payloads, authority/ownership failures and root mismatches fail closed.
OSM2/OSMI2 opaque ContentIDs and record grammar are unchanged; existing stored
snapshots retain their bytes and integrity. Wave/Wire grammar and reader fences
are unchanged. Legacy fixtures are newly generated compatibility probes using
the preserved SDK compiler, not recovered historical certification evidence.

Compatibility ledger: Particle/AST unchanged; Wave18–22 and OMC18–22 retain their
existing grammars and ownership fences; ONME3 is the additional current-root
envelope, with ONME2 compatibility retained; OSM2/OSMI2 record grammar unchanged.
Decision: REPRESENTATION_VERSION_BUMP_REQUIRED for the ONME root algorithm only.

The CP-01 record composition amendment in NOMINAL_AFFINE_RESOURCE_CANDIDATE.md
supersedes only the nominal-field restriction in the owning-record amendment.
Some's named record binding must explicitly consume every nominal Resource leaf;
its remaining Buffer leaves retain automatic cleanup. There is still no Option
destructor or duplicate owner. The nested-pending and Tuple/Array obligations
above remain open; this does not close CP-01.

The nested pending sums amendment in OWNERSHIP_COMPOSITION_CANDIDATE.md now
supersedes the mutual Option/Result/enum payload restrictions above. Named match
payloads transfer their own pending obligation into the existing ledger, even
without Resource leaves. The later pending-record-field amendment in
OWNERSHIP_COMPOSITION_CANDIDATE.md admits immutable record fields under the same
typed projected obligations. Tuple/Array pending fields remain rejected.
