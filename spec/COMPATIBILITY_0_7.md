> Distribution status: WIP / NOT_RELEASED. Technical version labels describe independent contracts, not public release certification.

# Omni 0.7 Compatibility Contract — alpha.7

**Foundation language:** `0.7.0-alpha.7`  
**Current hardened release:** `0.7.0-alpha.7.1`

1. Admitted Alpha.6 programs remain admitted unless they relied on undefined/tooling-only behavior.
2. Canonical executable output remains Wave11 / logical OMC11 (`OMCX + u32le(11)`).
3. Historical Wave/OMC readers 1..10 remain supported.
4. The released Alpha.7 tag remains immutable.
5. Alpha.7.1 does not assign new semantics to the old systemic schema labels:
   - OSM1 remains a legacy full-store reader format;
   - OSMI1 is not trusted for authenticated index-first access;
   - new authenticated snapshots use OSM2 + OSMI2;
   - new hardened machine-semantic artifacts use ONME2.
6. OSNMF/OSM/OSMI/ONME/OMP are additive systemic formats; none replaces Omni IR or Wire.
7. Identity/root equality never grants authority.
8. Unknown systemic versions/actions and integrity mismatches fail closed.
9. Core remains executable with Cognitive Plane/provider unavailable.
10. Migration from OSM1/OSMI1 to OSM2/OSMI2 is explicit repacking, not silent reinterpretation.
