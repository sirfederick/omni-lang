> Distribution status: WIP / NOT_RELEASED. Technical version labels describe independent contracts, not public release certification.

# Omni epoch monotonicity — 0.8.2

**Status:** `DESIGN_FROZEN`; normative for `CORE-EPOCH-001` repair.

## Contract

An epoch sequence is an unsigned 64-bit logical counter. Sequence zero is valid for
an initial static snapshot. A state transition that advances an existing epoch has
only this outcome:

```text
base.sequence < UINT64_MAX  -> next.sequence = base.sequence + 1
base.sequence = UINT64_MAX  -> E_EPOCH, no next state and no success receipt
```

The terminal value is not reserved: the transition from `UINT64_MAX - 1` to
`UINT64_MAX` is valid. No transition wraps to zero, reuses an epoch identity, emits
a partial snapshot/index, or emits a JSON success result after terminal rejection.

The rule applies to every executable path that advances a persisted `SystemMemory`
epoch, including cognitive apply, batch/merge, replay or restore when implemented,
and any CLI wrapper that publishes their result. A caller may validate a maximum
early, but the state-transition API itself must guard the increment so future callers
cannot bypass the invariant.

## Required evidence

The repair includes direct unit coverage of the transition API and CLI regressions:

1. `UINT64_MAX - 1` advances to `UINT64_MAX` and publishes a valid result.
2. `UINT64_MAX` rejects with `E_EPOCH` for apply and merge/batch.
3. terminal rejection creates neither output snapshot nor index sidecar and leaves
   the input snapshot byte-identical.
4. existing ordinary apply/merge behavior remains deterministic.

This contract is independent of application subsystem's distinct bounded-score arithmetic.
