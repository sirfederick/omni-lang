> Distribution status: WIP / NOT_RELEASED. Technical version labels describe independent contracts, not public release certification.

# Omni Release Hardening — 0.8.9

**Status:** `FROZEN_FOR_IMPLEMENTATION`
**Language version:** `0.8.9-alpha.8`
**Authority:** normative A89 hardening and evidence contract

## Scope

A89 closes the A8 Core train by making malformed input, recovery, dependency
inventory, provenance and compatibility evidence reproducible. It adds no
syntax, type, ownership, authority, runtime-effect or representation semantics.
Wave20 / OMC20 remains the latest writer.

## Versioned malformed corpus

`tests/corpus/a89/manifest.json` is the corpus authority. Each case binds an ID,
input format, base64 bytes, expected diagnostic class and SHA-256. The harness
materializes cases only into a disposable directory, imposes per-case time and
output bounds, and rejects crashes, hangs and unexpected acceptance. Corpus
growth is additive; changing existing bytes requires a new case ID.

The deterministic mutation campaign retains its recorded seed and count. A
finite corpus or mutation run is regression evidence, not proof of parser
correctness or security.

## Recovery and stress

The A89 harness repeatedly checks clean-versus-cached build equivalence, corrupt
cache repair, atomic output replacement behavior, evaluator/native agreement and
malformed-input rejection. It records exact elapsed duration, iterations,
platform, target, toolchain and seed. Development may use a short duration;
release certification requires at least 60 observed seconds. Neither is called
a prolonged soak.

Power-loss durability, disk-full behavior, OOM-kill recovery and multi-host
failover are not claimed by this Core profile. consumer integration owns the
historical long-run failure class and must report its actual duration.

## Dependency and provenance inventory

The harness emits `omni.release-hardening/1` with:

- exact Core source SHA and compiler hash;
- governed target-probe payload;
- every compiler translation unit and SHA-256;
- stdlib manifest/lock hashes and direct local dependency closure;
- toolchain identities and commands/exit codes;
- corpus manifest/case hashes and stress results.

This inventory is an SBOM-like source/dependency inventory, not a signed SBOM.
Hashes provide integrity, not publisher authenticity. Remote CI remains a
separate state and cannot be inferred from local evidence.

## Compatibility and upgrade rules

All legacy representation readers 1..20 remain accumulated gates. Unknown or
future representation versions, target IDs, lock versions, capability IDs and
host-policy generations fail closed. A downgrade cannot erase required
semantics, authority or target evidence. Clean and incremental/cached builds of
the same admitted inputs must have equivalent artifact bytes and provenance;
causal input, dependency, toolchain, option or target changes invalidate cache.

## Operational policy

Supported/deprecated behavior is versioned in active documentation. Certified
tags and receipts are immutable; a defect is repaired in a successor release or
documented advisory, never by retagging. Security reports preserve evidence and
follow `SECURITY.md`. Rollback is allowed only to an admitted, compatible,
unrevoked artifact and never bypasses current authority checks.

## Required gates

1. accumulated matrix and evaluator/native differentials;
2. versioned malformed corpus plus deterministic mutation campaign;
3. ASan/UBSan and compiler reproducibility;
4. dependency inventory and package integrity;
5. at least 60 seconds of bounded A89 recovery/stress under certification;
6. exact-SHA disposable worktree with clean post-status;
7. consumer integration compatibility smoke after Core certification;
8. annotated tag and governed release receipt.

consumer integration, Final Lock and LANGUAGE-USABLE evaluation follow A89. They do
not retroactively enlarge the Core A89 receipt.
