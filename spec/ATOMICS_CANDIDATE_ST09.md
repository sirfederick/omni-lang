> Distribution status: WIP / NOT_RELEASED. Technical version labels describe independent contracts, not public release certification.

# ATOMICS candidate (target-profile atomics) — target-profile atomic cells

Status: local candidate, **not certified**, x86-64 baremetal profile only. Other targets: NOT_VERIFIED.

## Surface
Authority: capability `memory.atomic` (critical, target-memory, address-range; unavailable to hosted programs). It does **not**
imply `memory.raw` and `memory.raw` does not imply it. No new pointer type is introduced: the address is a `u64`, as in `raw.*`.

| form | result | notes |
|---|---|---|
| `atomic.load32/64(addr u64, order u32)` | u32/u64 | order: 0 relaxed, 1 acquire, 4 seq_cst |
| `atomic.store32/64(addr, value, order)` | u32 (0) | order: 0 relaxed, 2 release, 4 seq_cst |
| `atomic.cas32/64(addr, expected, desired, success, failure)` | observed value | success iff observed == expected |
| `atomic.fetch_add32/64(addr, delta, order)` | previous value | **modular** (wraps) by intent |
| `atomic.fence(order u32)` | u32 (0) | order 1..4 (relaxed refused) |

Orders are literal `u32` 0..4 (0 relaxed, 1 acquire, 2 release, 3 acq_rel, 4 seq_cst) and are checked at compile time
(`E_ATOMIC_ORDER`). CAS failure order ∈ {relaxed, acquire, seq_cst} and may not exceed the success order
(release → relaxed only; acquire/acq_rel → ≤ acquire; seq_cst → any). Unknown op: `E_ATOMIC_OP`.

## Runtime checks
Natural alignment and non-null are checked before the access: LLVM lowering traps with `omni_fault(11)` (atomic access fault);
the evaluator fails `E_ATOMIC_ALIGN`.

## Lowering (x86-64)
`load atomic volatile`, `store atomic volatile`, `cmpxchg volatile`, `atomicrmw volatile add`, `fence`. `volatile` keeps the
optimizer from merging or eliding the access. x86 machine code observed: `lock cmpxchg`, `lock xadd`, `mfence` (seq_cst fence).
`acq_rel` fence and release/acquire load/store have no x86 instruction beyond a compiler barrier: their presence is
verifiable at IR level, not in the disassembly.

## Evaluator
Single-flow model over the same sparse memory as `raw.*`: checks alignment and values. It proves **no** inter-CPU ordering.

## Non-claims
No SMP, no linearizability proof, no memory-model equivalence with C11 beyond the LLVM semantic mapping, no AArch64/RISC-V.
`volatile`/`cli` remain non-atomic and unchanged.

The orders, the happens-before they build and what the x86-64 backend does with them are frozen in `MEMORY_MODEL_X86_64_CANDIDATE.md` (CP-13 row 13.6); the bounded SPSC mailbox that depends on them is in its section 6.
