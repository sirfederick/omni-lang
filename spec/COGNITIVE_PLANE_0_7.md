> Distribution status: WIP / NOT_RELEASED. Technical version labels describe independent contracts, not public release certification.

# Cognitive Plane Foundation 0.7

**Foundation release:** `0.7.0-alpha.7`  
**Current hardened release:** `0.7.0-alpha.7.1`

> **One persistent computational body. Many replaceable cognitive engines.**

The Cognitive Plane is optional and provider-neutral. Alpha.7 embeds no required remote provider.

`omni cognition` emits a read-only projection bound to a Neural Epoch. Confidential-domain nuclei are excluded by default and `mutation_authorized=false`.

## Governed Semantic Memory mutation

Alpha.7 implements a deliberately narrow mutation protocol for **Semantic Memory only**; it does not permit direct executable-code mutation.

```text
OSM1/OSM2 epoch E
 → OMP1 proposal
 → integrity + target + closed-action validation
 → stale-epoch check
 → explicit memory.write gate
 → Semantic Memory publication (authority remains AI-inferred)
 → one transactional new epoch
```

`proposal != authority`, `model agreement != truth`, `reasoning != execution`.

Multi-agent batches share the same base epoch. Different targets can publish atomically; differing notes on the same target are deterministic conflicts and abort the batch.

## OCAP / provider-neutral offload

The optional acceleration path is specified by `OCAP1` (see `OCAP_0_7.md`). Core can prepare an authorized, budget-bound, redacted context envelope and validate an adapter result without making any model a runtime dependency. The built-in `loopback` adapter is certification-only; production remote-provider adapters remain replaceable derived integrations.

`external.egress` is required to prepare an offload envelope. Provider output remains advisory and cannot bypass OMP1/epoch/capability publication rules.

## Persisted-body cognition

The Cognitive Plane can consume a persisted SystemMemory snapshot directly. Released Alpha.7 snapshots may be `OSM1`; Alpha.7.1 writes authenticated `OSM2` snapshots while retaining legacy full-store `OSM1` reads. `omni cognition SNAPSHOT.omem` and `omni cognition-offload SNAPSHOT.omem` therefore operate without reopening Particle/Wave source; their projections report `source_files_scanned = 0`. Provider outage never disables deterministic Core execution.
