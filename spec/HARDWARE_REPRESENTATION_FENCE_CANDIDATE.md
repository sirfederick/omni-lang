> Distribution status: WIP / NOT_RELEASED. Technical version labels describe independent contracts, not public release certification.

# Hardware representation fence — candidate (OMNI-CORE-PRO-FOUNDATION-001, G5)

**Status:** `CANDIDATE`, not adopted, not certified. Resolves the "hardware representation fence" left open when the application subsystem
candidates were merged (`TARGET_BAREMETAL_PROFILE_CANDIDATE.md`, `ATOMICS_CANDIDATE_ST09.md`, `NOMINAL_AFFINE_RESOURCE_CANDIDATE.md`).

## 1. Problem (measured, not assumed)
The merged specs state that Wave/Wire/ONME do not change, because the primitives are ordinary named calls and the capabilities are ordinary
names. That is true of the **grammar**. It was not true of the **version label**. With the merged compiler (`bde2578`):

| Program | Writer | Reader `core-v1.2.1.0` |
|---|---|---|
| no new semantics | Wire 18 | accepted |
| `bit.*` | Wire 21 | `E_VERSION` (the CP-07 fence) |
| `atomic.*` / `cpu.*` / `raw.*` / `port.*` / `tls.*` / `pcpu.*` | **Wire 18** | `E_CAPABILITY: capability Wire desconocida: cpu.control` |

A program carrying new authority was labelled with an old version and was rejected only by an incidental capability lookup. A different
old reader that tolerated unknown capability names would have accepted it. The master (§6.2) forbids hiding new semantics under an old
label; the minimum valid writer rule still applies to everything else.

## 2. Decision
These constructs share the existing Wave21 / OMC21 fence (no new version number, no new grammar):

1. a call to a machine primitive: any builtin whose name starts with `raw.`, `port.`, `cpu.`, `atomic.`, `tls.` or `pcpu.`;
2. the nominal-resource builtins `resource.seal`, `resource.unseal`, `resource.peek`;
3. a nominal `Resource<R>` / `Borrow<R>` / `BorrowMut<R>` in a type position (parameter, result, local, annotation) — `Resource<Buffer>`
   is **not** nominal and keeps its Wave18/19/20 encoding;
4. a function whose declared capabilities include `memory.raw`, `memory.atomic`, `memory.tls`, `memory.pcpu`, `port.io`, `cpu.control` or `cpu.syscall`.

Consequences:
- the writer emits Wave21 / OMC21 for any program containing one of them, and the minimum writer (18/19/20) for every other program;
- a reader accepts them only at version 21; a Wave/OMC 18–20 artifact that contains one is rejected with `E_VERSION`, so relabelling is
  not a bypass; a reader older than this candidate rejects the version 21 envelope with `E_VERSION`, not through a capability lookup;
- ONME, OSM and OMI are unchanged (their grammars did not change).

## 3. What this does not do
It grants no authority and carries no live state: capabilities remain declarations checked by the compiler and enforced by the target
profile, hosted compilation still refuses every primitive (`E_TARGET_PROFILE`), and a number in an address is still not a mapping.
Two candidate compilers that both write 21 are distinguished by SHA, spec and build, as before.

## 4. Acceptance (`tests/language_0_8_3_alpha8.py::A83HardwareFenceTests`)
Each construct writes `(omni-wave 21` and `OMCX\x15`, is accepted by the current reader, and is rejected with `E_VERSION` when relabelled as
18, 19 or 20 (text and binary); programs without these semantics keep Wave18, including programs using `Resource<Buffer>`.
