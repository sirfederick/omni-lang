> Distribution status: WIP / NOT_RELEASED. Technical version labels describe independent contracts, not public release certification.

# Composable ownership â€” candidate (OMNI-CORE-PRO-FOUNDATION-001, CP-01, linear enums)

**Status:** `FROZEN_FOR_CANDIDATE_1.3.0.0`, not release-certified. Extends `OPTION_RESOURCE_CANDIDATE.md` and `AGGREGATE_MOVE_CANDIDATE.md`; weakens none of their rules.
**Representation:** an enum declaration with a `Resource` payload is new semantics: Wave21/OMC21 (`E_VERSION` when relabelled older), no new form.

## 1. The common law
A value is **pending** when its type is a `Result`, a linear `Option<Resource<Buffer>>`, or a **linear enum**: an enum with at least one `Resource` payload (`Resource<Buffer>` or a
nominal `Resource<R>`). A pending value is consumed **exactly once**: by `match`, by being moved into a call, or by being returned. Using it twice is `E_RESULT_MOVED`;
leaving scope, returning, or breaking out with it unconsumed is `E_RESULT_UNHANDLED`; consuming an outer one inside a repeated body is `E_RESULT_FLOW`. This is the same ledger
that already governs `Result` and `Option<Resource>`: no second mechanism.
- **Construction:** `Slot.Full(move(r))` moves the payload (`E_RESOURCE_MOVED` on later use); a variant without payload is `Slot.Empty()`.
- **Match:** the arm that binds a payload owns it: a `Resource<Buffer>` is released at the end of the arm unless moved, a nominal resource must be consumed in the arm
  (`E_RESOURCE_UNCONSUMED`). The empty arm owns nothing. There is no tag-dependent destructor and no cleanup path for the enum itself.
- **No hiding places (v1):** a linear enum cannot be a `struct` field, another enum's payload, an `Option`/`Result` payload, a `Tuple`/`Array` element, or be captured by a
  closure (`E_TYPE`, `E_PRODUCT_LINEAR`, `E_CLOSURE_CAPTURE`). Those need pending leaves inside projected places (a later slice).
- Payloads that were already rejected stay rejected (`Borrow`, `BorrowMut`, `Future`, `Stream`, `Result`, `View`); `Option<Resource>` inside an enum stays rejected.
- Copy enums are unchanged. The historical expectation that a `Resource` payload is an error (`language_0_2_alpha3.py`) is replaced by this contract.

## 2. Acceptance (`tests/language_0_8_3_alpha8.py::A83LinearEnumTests`)
- full and empty variants matched, evaluator and native binary agree; the value moves into a call and out of a function;
- 3000 cycles over the runtime's 1024 buffer slots (a single leak per cycle would change the result), on every path;
- a nominal payload consumed in its arm, and rejected when the arm drops it;
- rejected without artifact: unmatched at scope exit, used twice, early-return leak, consumption inside a loop, struct field, enum payload, Option, Result, Tuple, Array, borrow and Result
  payloads, closure capture;
- Wave21/OMC21, `E_VERSION` when relabelled, the declaration alone is enough, representations agree and OSNMF is identical through them.

## 3. Not provided
Tuple/Array of resources, collections of resources (Vector/Map/Set: CP-05), pending values as fields of a struct (a nested ownership tree), partial consumption of an
enum payload without `match`, recursion through an enum, generic linear enums.


## Pending bindings are immutable (frozen repair, 2026-10-20)
Every pending type (Result, linear Option with Buffer or nominal payload, linear enum)
requires `let` or a parameter. `var` is rejected with E_RESULT_MUTABLE, before artifact
emission. Overwriting a still-owned active payload cannot implicitly abandon it. Mutable
assignment/reinitialization of pending Places is deferred until its replacement/cleanup
law exists. Ordinary Copy Options/enums and scalar vars remain admitted. This extends the
existing Result rule through the same `isPendingType` predicate; no new ownership ledger,
runtime destructor, capability, syntax or representation version is introduced.
The formerly accepted overwrite loop exhausted Buffer slots: preserve that failing input
as the regression. E_VERSION/authority/round-trip rules of the payload remain unchanged.


## Recursive owning payload and inference repair (frozen, 2026-10-20)
A record that owns Resource leaves remains owning when used as an enum payload. The enum
is pending exactly once, including empty variants, and its named payload binding owns the
existing projected record leaves. Classification walks canonical record/enum definitions
and type parts with memoization, bounded depth and cycle rejection; names alone grant no
permission. This preserves the existing generic enum-of-owning-record positive capability
while rejecting copies, drops and mutable overwrite of its owner.
Tuple/Array/array.fill reject owning/pending elements through BOTH inferred constructors
and explicit annotations (E_PRODUCT_LINEAR); projected element ownership is not implemented.
An Option payload is admitted for direct Resource (Buffer or nominal), but owning compound
payloads and Result remain rejected (E_TYPE) until their recursive pending law is implemented.
`_` cannot discard an owning/pending match payload (E_RESOURCE_UNCONSUMED). Bind it by name
for automatic Buffer cleanup or explicit nominal consumption; Copy wildcards remain valid.
Representation: enum declarations with any Resource-bearing record payload require Wave21/
OMC21, even unused. Readers reject older labels. No new binary field: the complete type
structure already records ownership. Development readers must be the actual candidate
source/spec SHA; withdrawn earlier candidates are not supported readers for this repair.
Wave22 authoring capsules and ONME2 envelopes are unchanged. No runtime resource or authority
is encoded. This is a fail-closed safety repair, not completed Tuple/Array resource support.

The owning-record amendment in `OPTION_RESOURCE_CANDIDATE.md` supersedes only the
Option-of-owning-record rejection above. Such an Option is pending under the same
recursive classifier and transfers its projected leaves to the named Some binding.
Nested pending values and owning Tuple/Array remain rejected until their own law
is implemented and verified; CP-01 remains open.

## Proven field Places and value reads (candidate safety repair)

A structural Ref/Field path may locate an owning field for explicit `move`,
`borrow` or `borrow_mut`. Resolving that Place never copies its intermediate
owning records. Reading the final field as a value requires a Copy field;
an owning Resource or record field requires explicit transfer (E_RESOURCE_ACCESS).
This applies equally to bindings, call arguments and aggregate/ADT constructors.
Copy fields of a stable owning record remain readable, and Copy temporaries may
be projected. Projecting an owning temporary is rejected (E_RESOURCE_ACCESS)
until temporary ownership and cleanup are implemented; bind its owner first.
Closure capture checks apply to every root lookup, including structural Places.
No new syntax, persisted field or implicit ownership transition is introduced.

## Typed projected consumption

The CP-01 record amendment in NOMINAL_AFFINE_RESOURCE_CANDIDATE.md applies the
existing root OwnershipEntry law to every projected Resource leaf: type, move
state, automatic cleanup and mandatory explicit consumption. Thus a nominal
leaf remains must-consume inside records and admitted enum/Option payloads;
Buffer cleanup remains automatic. Exit and branch/loop checks compare those
same typed obligations. No separate nominal-container ownership law is added.

## Nested pending sums (frozen for implementation)

Option, Result and enum payloads may recursively contain admitted pending sums.
This supersedes their mutual payload prohibitions above; it does not admit
pending fields in records, Tuple or Array. Result is always pending; Option is
pending if its payload owns Resource leaves or itself requires consumption; an
enum is pending if any payload owns Resource leaves or requires consumption.
Other Copy Options/enums remain Copy. Empty variants of a pending type still
require one consumption.

Match/call/return consumes the outer pending binding exactly once. Only the
selected arm's named binding receives the payload obligation. If that payload
is pending, it enters the SAME pending ledger and must in turn be consumed;
otherwise its projected/root Resource cleanup/explicit-consumption law applies.
No sum destructor, implicit discard or second owner is added. `_` cannot erase a
pending payload, including a Result with Copy alternatives. Mutable pending
bindings, replay, divergent continuing branch consumption and closure capture
remain rejected. Borrow/View/async payload restrictions and by-value cycle/layout
limits remain in force. Generic instantiations cannot turn this obligation into
Copy. Authority still comes from the actual operation.

Existing AST/type, Wave and Wire sum encodings carry nested payloads faithfully.
New pending composition requires Wave21/OMC21, even signature/constructor-only
use or an unused enum declaration. Ordinary single-level Copy Result keeps its
existing fence. The old ONME2 projection retains its original fence; current
ONME3 and authoring Wave22/OMC22 rules remain applicable. Lower/unknown labels,
malformed payloads and ownership-forged representations fail closed. No runtime
handle/authority is persisted. Source/Wave/Wire/ONME and evaluator/native must
agree, including empty and both Result alternatives, cleanup and error flow.

## Pending fields in immutable records (frozen for implementation)

An immutable record may own pending sum fields recursively. This supersedes
only the record-field restriction above; Tuple/Array restrictions remain until
their product Place/cleanup implementation. Every projected leaf is either a
Resource or a pending sum and uses the existing typed OwnershipEntry law. A
pending leaf is must-consume, with no automatic sum destructor. A record is not
Copy when any concrete field has an ownership/consumption obligation, even if
there are no Resource leaves. This property follows through nested records,
sum payloads, generic instances, inference and imports.

Reading a pending field through a proven structural Place transfers its whole
obligation once, like reading a root pending binding. The selected named match
payload then owns the next obligation. Re-reading the field is E_RESULT_MOVED;
leaving it live on any structured exit is E_RESULT_UNHANDLED. A whole-record
`move` transfers all its owning leaves; ordinary Copy fields remain readable.
Mutable owning records, aliases/copies, closure capture, wildcard abandonment,
unproved/temporary projections and inconsistent branch/loop flow remain errors.
Loans forbid overlapping transfers. Buffer cleanup and explicit nominal-resource
consumption retain their existing law; there is no hidden close or authority.

Record cleanup skips sum fields: their selected payload was already transferred,
and their live obligation must never be silently dropped. Existing recursive
record/field encodings suffice. Current Wave21/OMC21 is required even for unused
pending-field declarations; Wave22 authoring capsules retain precedence. Legacy
ONME2 root selection remains historical, not an admission or authority bypass.
Unsupported old readers fail closed. Evaluator/native and representation parity,
no-resource pending records, partial moves and failure exits must discriminate
lost obligations, double cleanup and premature release.

Projected field branch/loop consistency retains E_RESOURCE_FLOW; unhandled or
replayed pending fields use E_RESULT_UNHANDLED/E_RESULT_MOVED respectively.
