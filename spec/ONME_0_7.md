> Distribution status: WIP / NOT_RELEASED. Technical version labels describe independent contracts, not public release certification.

# ONME — Omni Neural Machine Encoding

**Foundation language:** `0.7.0-alpha.7`  
**Current hardened release:** `0.7.0-alpha.7.1`  
**Current writer:** `ONME2`

ONME is a compact **machine-semantic projection** of concrete executable Omni IR plus OSNMF lineage. It is not an ISA, not source-of-truth semantics and not a Wire replacement.

```text
Particle ↔ Wave ↔ Omni IR
                    ├── ONME
                    └── Wire → native target
```

Executable semantics remain Omni IR. Wire is physical interchange/encoding. ONME is a separate machine-semantic projection.

## Alpha.8 compatibility

ONME2 remains the current machine-semantic envelope in Alpha.8. The ONME envelope version and the executable Wave version are **orthogonal**:

```text
ONME2 envelope
  ├── executable OSNMF root
  ├── authoring-lineage root
  ├── envelope commitment
  └── encoded canonical Wave payload
         ├── historical Wave11 when decoding a historical artifact
         └── current Wave12 for Alpha.8 writers
```

Wave12 / BorrowMut / persistent-loan semantics do not require ONME3 because ONME2 already carries a length-delimited token stream plus the Wave header itself. The embedded Wave version remains authoritative for executable semantic fencing.

A conforming Alpha.8 implementation MUST prove `Wave12 → ONME2 → Wave12` round-trip for BorrowMut/persistent-loan programs and MUST still reject a relabeled historical Wave payload that violates the Wave-version gates.

## ONME2 hardening

ONME2 carries:

- executable OSNMF root;
- authoring-lineage OSNMF root;
- encoded executable Wave payload;
- an envelope commitment over all three.

The commitment is:

```text
SHA-256(
  domain-separator
  + executable-root
  + authoring-lineage-root
  + encoded-payload
)
```

Changing only the authoring-lineage root, executable root or payload without updating the complete envelope commitment fails closed.

This is an **integrity/lineage binding**, not proof that an external historical source was truthful or authored by a particular person. Authenticity beyond artifact integrity requires an external trusted signature/attestation layer.

ONME2 still requires supported executable `IR → ONME → IR` round-trip without semantic loss. Generic authoring templates remain authoring lineage; executable ONME carries canonical concrete/monomorphized IR.

Malformed lengths, unknown opcodes, unsupported versions, commitment mismatch and executable-root mismatch fail closed.

## Core 1.3 candidate: complete function identities

`OPTION_RESOURCE_CANDIDATE.md`, ONME root algorithm fence, defines ONME3 for
corrected function ContentIDs. The payload grammar is unchanged; the header and
commitment domain `/3` select current complete-function roots. Compatible roots
retain ONME2 output. ONME2 remains readable with current semantic validation and
strict historical-root verification, followed by a current in-memory projection.
No cross-algorithm root fallback, ownership bypass or authority transfer is allowed.
Historical artifacts and certified receipts are never rewritten.
