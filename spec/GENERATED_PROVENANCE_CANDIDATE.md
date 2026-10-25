> Distribution status: WIP / NOT_RELEASED. Technical version labels describe independent contracts, not public release certification.

# Generated provenance and rechecked authoring capsules

Status: FROZEN_FOR_IMPLEMENTATION for candidate 1.3.0.0, 2026-10-20.

A name containing `__g_` or `__impl_` is an ordinary user name. It grants no
import, visibility or public-signature exception. Only monomorphization and
trait implementation lowering create internal generated provenance. Function
specializations carry the canonical nominal types validated at instantiation;
only those types may bypass a missing reverse import/private type lookup.
Canonical calls may target an actual generated declaration, never a substring.
Duplicate generated/user declarations reject. A template body gains no right to
an unrelated private type by becoming a specialization.

Generated provenance cannot be accepted from serialized flags. Programs that
need generic/trait lowering are encoded using an authoring capsule, rechecked
and re-expanded at every entry. The capsule is normalized Particle bundled
source, including templates and trait implementations, captured before
lowering. It is data, never a filesystem import or executable host script.
It must be self contained: unbundled unresolved filesystem imports reject.
The existing parser/checker, limits and capability checks apply in full.
Repeated validation rebuilds the same checked program without duplicating
specializations. No runtime pointers, authority or resource instances persist.

Wave22 grammar: `(omni-wave 22 (authoring-source "<normalized Particle>" ...))`.
Source is split deterministically into UTF-8 boundary chunks of at most 4096
bytes; concatenate quoted chunks before parsing. Ordinary Wave text limits
remain unchanged.
OMC22 physical encoding: ASCII `OMCX`, u32le 22, existing length-prefixed UTF-8
string containing that same normalized Particle, and end of input. Bounds and
UTF-8 validation apply. Extra/truncated data reject. Earlier readers reject the
new version. Unknown versions reject. Relabeling a capsule to an older version
rejects, with E_VERSION. No implicit downgrade: old concrete representations
remain readable under ordinary strict visibility, but cannot recreate lost
generation privileges from names. Such intermediate development snapshots must
be regenerated from authoring source.

Programs without templates/trait impls retain their minimum existing writer.
The capsule contains authoring inputs, not a second unchecked executable body;
the compiler computes every specialization anew. ONME2 continues to commit the
Wave stream and semantic roots; its envelope does not change. OSNMF preserves
the same checked authoring and executable relations through the capsule.
Formatter preserves the canonical authoring program. Version/spec/source SHA
identify development snapshots; no released tag or historical receipt changes.

Acceptance: forged source/bundle names and aliases; forged ordinary Wave/Wire
functions; generic body using unrelated private type; valid cross-module private
type instantiation; source/representations evaluator/native parity and OSNMF
identity; repeated recheck; downgrade, malformed and future-version rejection.

Compatibility ledger: Particle grammar unchanged; AST has nonserialized
provenance; Wave/OMC writer 22 for authoring capsules, minimum reader 22;
readers 1..21 retained without name-based privileges. ONME2 and OSNMF envelope
versions unchanged. REPRESENTATION_VERSION_BUMP_REQUIRED (implemented at 22).
