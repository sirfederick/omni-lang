> Distribution status: WIP / NOT_RELEASED. Technical version labels describe independent contracts, not public release certification.

# Interrupt guards and spinlocks — candidate (OMNI-CORE-PRO-FOUNDATION-001, CP-14, first slice)

**Status:** `CANDIDATE`, not adopted, not certified. Profile: `baremetal-x86_64`. One new builtin; everything else is a library written in Omni on top
of mechanisms Core already has (nominal affine resources, transitive capabilities, atomics).
**Representation:** `cpu.read_flags` shares the Wave21/OMC21 fence (any `cpu.` builtin; `HARDWARE_REPRESENTATION_FENCE_CANDIDATE.md`).

## 1. Contract
A guard **owns an obligation**: it is a `Resource<G>` of a nominal struct, so the compiler requires it to be consumed exactly once.
- a path that leaves the guard alive is `E_RESOURCE_UNCONSUMED` (fall-through, early `return`, a branch that forgets it);
- a second release, or a use after release, is `E_RESOURCE_MOVED` / `E_RESOURCE_ACCESS`;
- the guard cannot be copied, forged from an integer or stored in a record (the nominal-resource rules).

### 1.1 `cpu.read_flags() u64` (capability `cpu.control`, `baremetal-x86_64` only)
Returns `RFLAGS` (`pushfq; pop`). It needs the freestanding no-red-zone ABI the profile already requires. The evaluator cannot execute it; hosted
compilation and the i386 profile refuse it with `E_TARGET_PROFILE`.

### 1.2 `irq` (tests/x64/irq.omni, candidate library)
`save() Resource<Guard>` reads `RFLAGS`, disables interrupts and returns the previous `RFLAGS` in the guard. `restore(move(g))` re-enables
interrupts **only if `RFLAGS.IF` was set when the guard was taken**, never unconditionally. Guards therefore nest: restoring the inner leaves
interrupts disabled, restoring the outer re-enables them.

### 1.3 `spin` (tests/x64/spin.omni, candidate library)
`acquire(addr, attempts)` disables interrupts, then spins on `atomic.cas32(addr, 0, 1, acq_rel, acquire)`; the handle packs the lock address
and the interrupt state found, **losslessly for every 64-bit address**: the lock word is a naturally aligned 32-bit cell, so address bits 0..1 are
zero and the interrupt state travels in bit 0 (`pack`, `handle_addr`, `handle_irq`). An earlier draft spent bit 63 of the address, which cannot
represent x86-64 higher-half addresses (review observation); no address bit is spent now. A misaligned cell is refused with trap 11 by the first
compare-and-swap, before the lock can be taken, so the encoding is never ambiguous. `release(move(g))` stores 0 with `release` and restores the
interrupt state.
`acquire_noirq` is the same without touching interrupts, for contexts that already run with them disabled (an interrupt handler). A lock not
obtained within `attempts` tries is reported as a deadlock (exit value 95 in the conformance provider), never as an endless spin.

### 1.4 Restrictions of a critical section
"No allocation / no blocking" is the existing effect system: a function declared without `memory.write` cannot allocate, directly or through
any chain of calls (`E_CAPABILITY`). The guards add no second mechanism (section 1.5 states what the restriction does and does not prove). Not provided: a distinct no-migration capability, priority inheritance,
fairness, a blocking primitive, quiescence for callback retirement.

### 1.5 What a critical section may do: a property of its type (`examples/storage/critical.omni`, CP-14 rows 14.4 / 14.5, adendum 009A)
Section 1.4 said that the restriction comes from the effect system. `critical.omni` makes that a contract of the section itself: the body is an `impl critical.Section`, and the trait declares the only capabilities
the body may use, `!{memory.raw,memory.atomic}`. The checker enforces it at the impl (`E_TRAIT_EFFECT` for any other capability in the signature) and through every call the body makes, because the capabilities a
function requires are those of the operations it performs and of everything it calls (`E_CAPABILITY`; `omni capabilities` reports `required` and `direct_required`): a direct call, calls nested three deep, a function of an
imported module, a generic function and the impl of another trait are all covered, and the same paths with allowed capabilities compile and instantiate. Every capability of the registry has a stated disposition
(`tests/cp14_sections.py`: the test fails if the registry grows); for the capabilities that have an operation in the language the operation itself is the oracle, for the five that have none yet (`data.read`, `data.write`,
`net.listen`, `external.egress`, `secret.use`) only the refusal at the impl exists and it is recorded as such.
`irq_off` saves RFLAGS, disables interrupts, runs the body and re-enables them only if they were enabled on entry; `locked` adds a spinlock (acq_rel compare-and-swap, release store) and answers `Err(17)` with the
interrupt state restored when the lock is not taken in `attempts` tries. There is no guard to forget: the release is the code after the body. A timer interrupt does not land inside a section and does land in the same
body outside one (`InterruptSectionTests`), which is the mechanism behind "not preempted"; the body cannot name `cpu.control`, so it cannot yield, switch context, halt or re-enable interrupts, which is the mechanism behind
"does not migrate" (a pin guard still detects a migration, `NO_MIGRATION_CANDIDATE.md`).
**Scope, stated so that it is not read as more:** the claim is about the capabilities and operations the checker sees. It does not prove that a body never waits: `memory.raw` accepts any address, including a device
register, and a loop on atomics or on a cell is an ordinary computation (nothing tells a bounded loop from an endless one). A body that polls a device or spins on a flag blocks the CPU and the profile cannot say so.
The library bounds its own waits (`attempts`); the body is the programmer's. No priority inheritance, no fairness, no real hardware.

## 2. Acceptance (`tests/language_0_8_3_alpha8.py::A83X64GuardTests`)
- interrupt state: enabled → guard → restore enables; disabled → guard → restore stays disabled; nested restore order;
- two vCPUs: a relaxed load+store pair under the lock gives the exact total, the same loop without it loses updates; the lock word is free at the end;
- interrupts: with `acquire` the handler and the loop never interleave (total = iterations + interrupts); with `acquire_noirq` in the loop an
  interrupt inside the critical section makes the handler spin and the bounded spin reports the deadlock;
- handle: address and interrupt state round-trip for low, higher-half (bit 63 set), highest aligned and bit-2 addresses; a misaligned cell traps 11;
- ordering: the lock's compare-and-swap is `acq_rel`/`acquire` and its release is a `release` store, checked on the emitted IR because x86 cannot
  show the difference;
- compile time: leaked lock, double release, early-return leak, leaked IRQ guard, use after release, and an allocation reachable from a section.

## 3. Non-claims
One architecture, QEMU TCG only; no memory-model proof; the library is a candidate and not part of the certified distribution.
