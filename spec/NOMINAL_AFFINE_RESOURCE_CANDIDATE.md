> Distribution status: WIP / NOT_RELEASED. Technical version labels describe independent contracts, not public release certification.

# Nominal affine resources (candidate, OMNI-NATIVE-FRAME-RESOURCE-001)

Status: LOCAL CANDIDATE, not certified, not part of the admitted SDK. Representation version unchanged (no new
Wave/Wire instruction; the three builtins lower to existing record/handle operations).

## Problem (reproduced)
`Resource<T>` was operational only for `T = Buffer` (`E_RESOURCE_TYPE`). A kernel frame token expressed as a record is
Copy: it can be copied, forged from an integer and dropped without a diagnostic; only a runtime ledger notices.

## Capability
- `Resource<R>`, `Borrow<R>`, `BorrowMut<R>` are admitted when `R` is a declared, visible `struct` with exactly one
  `u64` field (the handle). `R` may be module-qualified (`Resource<frames.FrameTok>`). The resolved type name is the
  qualified record key, so nominal identity is the declaration.
- Ownership is the existing move/borrow machinery (E_RESOURCE_MOVED, E_RESOURCE_ACCESS, E_RESOURCE_MUTABLE,
  E_RESOURCE_FLOW, E_BORROW_CONFLICT) applied to the nominal type.
- A nominal resource has NO automatic cleanup. Leaving a scope (fall-through, `return`, `break`/`continue`, branch,
  match arm) while it is live is `E_RESOURCE_UNCONSUMED`. It must be moved to a consumer.
- Three builtins, valid only inside the module that declares `R` (`E_RESOURCE_PRIVATE` elsewhere), no capability:
  `resource.seal(r R) Resource<R>` (mint), `resource.unseal(move(x)) R` (consume, yields the record),
  `resource.peek(b Borrow<R>|BorrowMut<R>) R` (read the record through a borrow).
- A nominal resource cannot be a record/tuple/array field (`E_RESOURCE_TYPE`), cannot be built from an integer
  (`E_TYPE`), cannot be cast to one (`E_*`).

## Lowering
Handle = the `u64` field (i64). seal = extractvalue 0; unseal/peek = insertvalue into the record. Scope-exit cleanup
code for a nominal handle is a no-op (the checker proved it moved). Evaluator mirrors this.

## Limits
- Guarantees are for code that obtains handles through the declaring module's API. Code holding the raw `u64` and
  `memory.raw` (ring 0) is a different trust boundary.
- No persistent/global storage of a handle (records cannot hold it): the handle ends in an explicit commit/release.
- Not a replacement for dynamic ownership checks of an external authority (a physical-frame ledger).

## CP-01 record composition amendment (frozen for implementation)

This amendment supersedes the record-field prohibition above, for immutable
owning records only. A direct or recursively nested `Resource<R>` field carries
the same typed ownership entry as a root Resource: live/moved state, automatic
drop obligation for Buffer, mandatory explicit consumption for a nominal R.
No second resource kind or implicit conversion is introduced. Generic instances
and module-qualified types obey their resolved nominal declaration.

Construction requires an explicit resource move. Moving a field, or moving the
whole record through the existing recursive construction lowering, transfers its
obligation exactly once. Copy projections remain allowed; reading an owning
field without move/borrow remains E_RESOURCE_ACCESS. A loan conflicts with a
move of the same or enclosing Place. Moved fields cannot be consumed twice.

Every structured exit checks live nominal leaves, including return, fall-through,
break, continue, branches and match payloads (E_RESOURCE_UNCONSUMED). Live Buffer
leaves retain automatic cleanup; a nominal leaf never receives buffer.release,
even when its handle equals a Buffer handle. Moving a record into a parameter,
return value or admitted Option/enum payload transfers its leaves to the new
owner; the old record is not an additional destructor. Pending containers remain
consumed by match. Mutable owning bindings, wildcard abandonment and closure
capture remain forbidden. Module-private seal/unseal/peek authority is unchanged.

Wave21/OMC21 is the minimum even for an unused declaration with a nominal
Resource field; older labels fail E_VERSION. Existing type and field encodings
already describe the complete law; no new grammar or runtime authority is
serialized. Wave22 authoring capsules and the ONME2/ONME3 root-algorithm fence
remain applicable. Legacy readers that lack nominal record composition fail
closed. Source, Particle, Wave, Wire and ONME must preserve evaluator/native
behavior and current OSNMF identity after round-trip. Unknown or forged inputs
must not erase explicit consumption. Tuple/Array and pending fields are separate
mandatory CP-01 obligations, not implemented or closed by this amendment.

The aggregate-move expansion spells an imported record through the caller's
existing import alias. A valid move cannot depend on the declaring module's
unqualified type name being visible in the caller. This uses the same visibility
and constructor checks as an explicit aliased record expression; it grants no
additional constructor, seal/unseal/peek or transitive import authority.
