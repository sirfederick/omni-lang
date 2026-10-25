> Distribution status: WIP / NOT_RELEASED. Technical version labels describe independent contracts, not public release certification.

# Quiescence and safe retirement — candidate (OMNI-CORE-PRO-FOUNDATION-001, CP-14, second slice)

**Status:** `CANDIDATE`, not adopted, not certified. Profile: `baremetal-x86_64`, QEMU TCG with two vCPUs only. No new compiler feature:
this is a library written in Omni (`tests/x64/epoch.omni`) on top of `atomic.*` and nominal affine resources. It is evidence that the existing
language is enough to express the pattern; it is **not** a general RCU, a scheduler or a memory reclaimer.

## 1. Library (`tests/x64/epoch.omni`)
| Function | Meaning |
|---|---|
| `enter(gen, slot) Resource<Reader>` | begins a read-side section: loads the global epoch, publishes it in the reader's slot (`seq_cst` store), `seq_cst` fence |
| `exit(move(g))` | ends the section: release store of 0 in the slot |
| `advance(gen) u32` | `seq_cst` fetch-add on the epoch; returns the new epoch |
| `wait(slot, target, attempts)` | returns when the slot is 0 (quiescent) or `>= target` (entered after the advance); a slot that never gets there is a deadlock, exit value 95 |
The guard is a nominal affine resource: a section that is never left (`E_RESOURCE_UNCONSUMED`) or left twice (`E_RESOURCE_MOVED`) does not compile.

## 2. Protocol and why it is safe
Writer: (1) store the new pointer, (2) `advance`, (3) `wait` on every reader slot, (4) reclaim the old object. Reader: (a) `enter`, (b) load the pointer,
(c) use the object, (d) `exit`. Dekker argument: the reader stores its slot and fences before loading the pointer; the writer publishes the pointer before its
`seq_cst` RMW and reads the slots after it. Either the writer sees the reader's slot and waits for it, or the reader sees the new pointer and never holds the
old one. A reader that entered after `advance` carries an epoch `>= target` and is not waited for.

## 3. Acceptance (`tests/language_0_8_3_alpha8.py::A83X64QuiescenceTests`)
- two vCPUs: the writer retires (poisons) a buffer after each of 3000 publications while the reader dwells inside its section holding that pointer; the
  reader observes poison **zero** times, completes more than 1000 sections, and the epoch and slot end consistent;
- control (same program, `advance`/`wait` removed by text substitution): the reader observes poison;
- compile time: a leaked section and a double exit do not compile;
- ordering is not left to x86: the emitted IR contains the `seq_cst` slot store, the `seq_cst` fence and the `seq_cst` RMW of the protocol.

## 4. Not provided
Callbacks (Omni has no function values, so retirement is the caller's code after `wait`), grace-period batching, more than the readers whose slots the
caller scans, preemption (a context switched out inside a section blocks the writer: sections must be short and non-blocking), no-migration enforcement
(sections are only meaningful while the reader stays on the CPU whose slot it uses; Core does not enforce that), real hardware, a memory-model proof.
CP-14 therefore still lacks no-migration enforcement and callback retirement as a language feature.

## 5. Amendment: complete coverage, the horizon of the epoch and priority (CP-14 rows 14.5 / 14.6, adendum 009A)
* **A grace period proves exactly what it scanned.** `epoch.wait` looks at one reader slot; `epoch.wait_all(first, count, stride, target, attempts)` at `count` slots, and `cbreg.retire_all` uses it. With three vCPUs (a writer
  and two readers) the wait over every slot never lets either reader see a retired buffer, and the wait over a list that leaves one reader out lets that reader see it (`Quiescence3Tests`). The library cannot know the readers: the
  caller owns the list.
* **A call in flight at the moment of retirement** (`cb_inflight.omni`): a long call reads a cell its environment points to and `dispose` poisons that cell. 1500 retirements, both readers served more than 100 calls, the
  oracle counts the retirements that overlapped an in-flight call (coverage), no call read poison, each environment was disposed once. Without the wait, or with a partial wait, the image reads poison or dies on the poisoned
  pointer (`CallbackRetirementTests`).
* **The epoch does not wrap.** 0 means "no reader"; a counter that wrapped to 0, or compared below what an active reader published, would make that reader look quiescent. `advance` is a compare-and-swap that stays in
  1..4294967295 and answers 0, changing nothing, when the epoch is uninitialized (0) or exhausted; `can_advance` says so beforehand; `wait` with the target 0 ends the guest with exit value 96; `cbreg.retire` and `retire_all`
  check `can_advance` before they unpublish anything. The cell must be initialized to 1. Tested on the cell before and after (`EpochHorizonTests`): the last allowed step, the refusals, a reader active at MAX-1 waited for,
  a reader entering at MAX, and a cell wrapped from outside.
* **Priority and reentrancy.** An interrupt handler is a higher priority context on the same CPU. A handler that retires an object against the reader it interrupted can never succeed (the reader cannot run while the
  handler waits) and the bounded wait ends the guest with exit value 95 instead of reclaiming under the reader; the same retirement succeeds when the interrupted code is not a reader (`InterruptPriorityTests`). A callable
  cannot fire, register or retire anything: `Handler.call` is `!{memory.raw}` and those operations need atomics and the epoch wait (`E_CAPABILITY` / `E_TRAIT_EFFECT`).
Still not provided: batching, preemption inside a section, a proof beyond the interleavings the tests drive, real hardware.
