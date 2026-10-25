> Distribution status: WIP / NOT_RELEASED. Technical version labels describe independent contracts, not public release certification.

# Adversarial Security & Supply Chain 0.9.6

**Status:** normative A96 convergence contract  
**Language version:** `0.9.6`

A96 closes the cumulative Core security campaign begun at A91. It introduces
no language feature, authority kind, package fetcher, signing format or vendor
dependency.

## Required closure domains

1. Authority and capability checks fail closed across source, Wave, Wire,
   hosted effects and proposal publication.
2. Stale generation, epoch, subject, request or policy bindings cannot be
   replayed as current authority.
3. Representation downgrade, malformed input and incompatible writer fences
   are rejected with stable diagnostics.
4. Package manifests and locks are canonical, offline and exact-hash bound;
   drift, missing artifacts, path escape and symlink substitution fail closed.
5. Build/release evidence binds compiler, runtime, backend, source and target
   provenance. A digest is integrity evidence, not publisher authenticity.
6. Distribution evidence includes a deterministic machine-readable component
   inventory with path, kind, SHA-256 and declared role. It does not call that
   inventory a signed or complete third-party SBOM.
7. Secrets and bearer credentials are neither required by Core nor admitted in
   tracked fixtures, reports or receipts. Named environment-variable references
   are not secret values.
8. Disabled functionality, a missing test, remote CI billing or a successful
   mock cannot preserve or manufacture PASS.

## Causal evidence

Each security scenario names the attack, exact boundary, negative oracle and
evidence class. The gate combines existing regression suites with a bounded
adversarial campaign for current bytes. Findings are classified before repair;
tests are not weakened solely to obtain green.

Component inventory hashing is streaming and bounded by the tracked Core
source/package manifest. Paths are safe relative paths; symlinks and duplicates
are rejected. Generated binaries and external durable evidence remain outside
the inventory of authoritative source.

## Compatibility and limitations

All representation versions remain unchanged. A96 does not claim cryptographic
publisher identity, transparency-log inclusion, remote registry security,
provider security, multi-tenant application subsystem isolation or application subsystem product security.
Those claims require their owning profiles and real boundaries.
