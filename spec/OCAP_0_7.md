> Distribution status: WIP / NOT_RELEASED. Technical version labels describe independent contracts, not public release certification.

# OCAP/1 — Omni Cognitive Acceleration Plane Contract

**Foundation version:** `0.7.0-alpha.7`  
**Current hardened release:** `0.7.0-alpha.7.1`

OCAP is an **optional** cognitive acceleration contract above the deterministic Omni runtime and OSNMF. It is not systemic memory, not runtime authority and not required for Core operation.

## OCAP1 offload envelope

`omni cognition-offload` creates an integrity-bound `OCAP1` request containing:

- Neural Epoch binding;
- provider identifier;
- OSNMF selector;
- authorized cognitive projection digest + payload;
- `CognitiveBudget` (`max_input_tokens`, `max_output_tokens`, `max_cost_microunits`, `max_latency_ms`);
- required capability `external.egress`;
- usage-estimation metadata;
- `source_files_scanned`, integrity-bound into the envelope, so persisted OSNMF projections can prove source-free cognitive context construction.

Confidential-domain nuclei are excluded by default under policy `deny-confidential-by-default`. A projection or envelope never grants mutation authority.

Core performs **no implicit network call**. Provider integration is an adapter boundary. Alpha.7 ships `loopback` solely as a deterministic certification adapter proving envelope parsing, budget accounting, integrity and advisory-result semantics without Internet access.

```text
OSNMF epoch
   ↓ authorized projection
OCAP1 envelope
   ↓ provider adapter
analysis/result
   ↓ local verifier / proposal path
```

A real remote adapter may transport OCAP1 context to external compute, but it remains replaceable and outside the authority root of the language.

## Invariants

1. `external.egress` is required before producing an offload envelope.
2. Confidential memory is denied by default.
3. Context must fit declared input-token budget before publication.
4. Envelope integrity, context digest, provenance-of-context counters and budget fields are verified before adapter execution.
5. Provider output is advisory; `proposal != authority` remains true.
6. Removing the provider or Internet does not affect deterministic Core execution, OSNMF, ONME, querying, build or run.
7. Token counts are resource/accounting estimates, never a measure of intelligence.
8. `cognition` and `cognition-offload` may operate directly from a persisted SystemMemory snapshot (`OSM1` legacy full-store or `OSM2` hardening candidate); in that mode `source_files_scanned = 0` and the source repository is not required.
9. An OCAP1 envelope is an integrity-bound request artifact, **not authority**; real dispatch must re-check policy/capability at the adapter boundary.
