> Distribution status: WIP / NOT_RELEASED. Technical version labels describe independent contracts, not public release certification.

# Operations / Maintenance 0.9.7

**Status:** normative A97 convergence contract

**Language version:** `0.9.7`

A97 defines release-evidence obligations for the existing Core operational
profile. It introduces no source-language form, runtime capability, ABI,
representation writer or target support guarantee.

## Measurement contract

Every published A97 measurement records the exact source SHA, compiler hash,
target/profile, host-scoped environment, workload/corpus, repetitions, units,
denominator, percentile method and limits of inference. A measurement is not a
portable benchmark, capacity commitment or SLO unless a separately governed
profile supplies those terms.

Metric labels and dimensions are bounded and declared before execution.
Invalid budgets, unbounded cardinality and absent units/denominators fail the
operational gate rather than being silently omitted.

## Recovery and maintenance contract

Clean installation, upgrade, rollback, diagnostics, profiling and recovery
are exercised through the supported local profile. A fault-injected interruption
may produce `UNKNOWN_OUTCOME`; rollback or retry must not reclassify it as a
successful effect without reconciliation evidence.

Recovery tests use deterministic seeds, virtual time or fault injection where
physical waiting is not the hypothesis. The normal integral gate is bounded to
1,200 seconds. Wall-clock duration alone is not robustness evidence.

## Evidence boundaries

The A97 gate may prove the exact candidate on its exercised host/process and
filesystem boundaries. It does not prove external provider behavior, application subsystem
tenant isolation, a production deployment or an unsupported target. Mocks and
loopbacks may support isolated fault evidence only and cannot close a real
boundary claim.
