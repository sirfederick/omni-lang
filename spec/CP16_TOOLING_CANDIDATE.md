> Distribution status: WIP / NOT_RELEASED. Technical version labels describe independent contracts, not public release certification.

# CP-16 tooling contract

Status: implementation candidate in the integrated 0.1.0.00 WIP distribution; not release-certified.

This completes the existing CP-16 tooling obligations. Language typing,
ownership, effects, evaluation and persisted representations are unchanged.

## Checked binding snapshots

`omni check FILE --bindings-json` runs the ordinary loader/checker and emits
`omni.bindings/1` only after successful validation. The report contains source
tokens tied to checked function identities and function-local binding IDs.
It conveys no runtime authority. Source coordinates explicitly use UTF-8 byte
columns, one based, and token lengths in bytes. Comments and strings are never
occurrences. Synthetic or unsupported source mappings are omitted and reported
as incomplete; rename fails closed for an incomplete source closure.

The LSP uses this report on its workspace snapshot for definition, references
and rename. Homonyms with different bindings remain distinct. Rename checks the
edited snapshot through the same compiler and preserves the binding partition
of every indexed occurrence. A successful type check alone does not prove that
rename avoided name capture. The response proposes edits, never writes source.
UTF-16 ranges must not split surrogate pairs. Versioned document edits bind the
proposal to the analyzed snapshot. Truncated workspaces/results must reject
rename instead of returning a partial edit set. Unavailable analysis rejects;
there is no fallback to spelling-based resolution.

Package manifests and locks in the admitted source closure are retained byte
for byte in diagnostic and binding snapshots. They are never automatically
relocked. Changes to those commitments during rename invalidate the proposal.
The installed LSP uses the root/version of its shipped SDK, including its
bundled stdlib. Ordinary dependency loading must use the same bundled
`omni.std` resolution and lock verification as `package lock/check`; other
dependencies do not gain an exception to workspace/path restrictions. A local
declared dependency takes precedence over the bundle exactly as in the resolver.

The stdlib provider is selected from the SDK's existing
`metadata/omni-sdk.json` (`omni.sdk-distribution/1`) component inventory. Its
`packages/` manifest entry must remain inside the SDK, match its recorded
SHA-256 and identify `omni.std` with a valid manifest version. Exactly one
provider is admitted; malformed, ambiguous or corrupt metadata is an error.
The compiler does not duplicate a stdlib version or guess a version directory.
Without a distribution manifest, the active development tree may use its
authoritative `stdlib/omni.package.json`; an installed tree with neither has
no bundled provider. Invalid existing SDK metadata never triggers fallback.
The packager takes the package name/version from that same source manifest.
This selects an input provider, not authority, and does not change a package's
legitimately pinned version or the SDK's private version.

This repairs resolution consistency, not a new package/format contract:
`REPRESENTATION_COMPATIBLE_NO_BUMP`. Writers remain minimum Wave/OMC18…22,
ONME2/3 and current OSNMF; legacy/unknown-version behavior is unchanged. Module,
type and function identities are still derived from checked content, not an
SDK path or metadata grant. Retain ordinary relative imports, malformed path,
lock drift, undeclared dependency, authority denial and round-trip regressions.

## Hypothetical admission

`omni admit FILE` checks a candidate source snapshot using the ordinary loader
and checker and returns `omni.admission/1`, `YES` or `NO`, with the ordinary
structured diagnostic on rejection. The caller supplies the hypothetical
source; the command never executes it, builds an executable, grants authority,
applies an edit, or writes a persistent artifact. CLI misuse remains an error.
Acceptance certifies only the same static properties as `check`.

## Diagnostic proposals

The approved AI-02 diagnostic context is additive to `omni.diagnostic/1`.
Ownership/loan/capability failures may include `symbol_id`, `symbol`, `place`,
`owner`, `active_loan`, `constraint` and `required_fix_classes`. Symbol identity
reuses the existing OSNMF function/template nucleus identity, not its content
or contract commitment: identifying a declaration in a rejected program does
not assert that its body is valid. A place describes checked function-local
root/projection indices, and a loan describes the actual conflicting ledger
entry. These values describe this diagnostic snapshot and grant no lifetime
or runtime authority. Unknown facts are null/absent; never derive them by
parsing the human message. Repair classes are advisory constraints to recheck,
not verified edits or a recommendation to fabricate/grant authority. Other
diagnostics retain their established output. Success-path ownership, loan and
capability rules do not change, and this context is not serialized into IR.

Optional `fixits` on `omni.diagnostic/1` are deterministic replacement proposals
with source URI, exact range, expected old text and replacement text. No fix is
emitted when the source span cannot be established. `check` and admission do
not apply them. Edits that may change effects/ownership require explicit user
application and a fresh check. Primary diagnostics retain their existing code;
related locations retain the established additive contract. A rejection leaves
existing output artifacts intact and emits no replacement artifact.

Particle lexer/AST positions remain byte based internally. Primary and related
diagnostics convert them to the declared Unicode scalar columns when rendering
text or JSON. Decoded Wave/Wire/ONME positions without a proven mapping to the
original artifact use a null diagnostic span; an internal decoded-source offset
must not be presented as a position in its envelope. Binding reports and fix-it
proposals explicitly retain byte coordinates, converted to UTF-16 by the LSP.

## Acceptance

Test binding homonyms, shadowing/capture, imports and unsaved buffers, Unicode
UTF-16, stale/malformed edits, unsupported mappings, unchanged disk contents,
and refusal on compiler failure. Admission must agree with check across input
representations and reject without executing effectful code. Test fix-it ranges
and the positive recheck of a user-applied proposal. Preserve historical format
fixtures and use CP-16 baseline, focal mutation and exact-SHA gate B for closure.
