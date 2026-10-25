> Distribution status: WIP / NOT_RELEASED. Technical version labels describe independent contracts, not public release certification.

# Diagnostic related locations — CP-16 candidate

**Status:** `CANDIDATE` (OMNI-CORE-PRO-FOUNDATION-001 / DX-001 slice 2). Not adopted, not certified.
**Compatibility:** **additive** to `omni.diagnostic/1`. The new field is omitted when a diagnostic has no secondary location, so every existing diagnostic is byte-identical;
consumers that ignore unknown fields keep working (the LSP server and the VS Code extension read `code`, `message` and `span` only). No new schema major version.

## 1. Contract

1. **JSON.** `"related": [ { "role", "note", "source", "source_uri", "span": {line, column, coordinate} } ]` follows `span`. `role` is a stable identifier:
   - `conflicting-loan` — on `E_BORROW_CONFLICT` (loan-vs-access conflicts): the place where the active loan was created;
   - `moved-here` — on `E_RESOURCE_MOVED`: the place where the Resource was moved or released.
   Coordinates use the same unit as `span` (`unicode-scalar-1-based`). `note` is explanatory prose and may be refined; `role` is the compatibility surface.
2. **Text.** The primary line is unchanged; each related location follows on its own line: `  nota (<role>): <file>:<line>:<column>: <note>`. A diagnostic without a
   related location is still exactly one line.
3. **LSP.** `relatedInformation[{location:{uri,range},message}]` with the file mapped back from the analysis snapshot to the workspace URI and the range in UTF-16.
4. **Scope of v1.** Only the loan-versus-access conflicts and the root/field use-after-move sites. Other `E_BORROW_CONFLICT` sources (overlapping call arguments, suspended
   reborrows) carry no related location yet. A related location never changes which diagnostic is emitted, never applies a fix and grants nothing.

## 2. Acceptance

`tests/language_0_8_3_alpha8.py::A83RelatedLocationTests` (JSON, text, unchanged output when absent) and
`tests/language_0_8_7_alpha8.py::A87LspDiagnosticsParityTests::test_related_locations_become_related_information`.
