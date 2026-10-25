> Distribution status: WIP / NOT_RELEASED. Technical version labels describe independent contracts, not public release certification.

# Cancellation and withdrawal of a task that owns resources — candidate (OMNI-CORE-PRO-FOUNDATION-001, CP-03 row 3.4)

**Status:** `CANDIDATE`, not adopted, not certified. Profile `baremetal-x86_64`, QEMU TCG with one and two vCPUs. No compiler feature: a library written in Omni (`examples/storage/coop.omni`)
on `cpu.switch_context` / `cpu.thread_trampoline` / `--thread-entry` (CP-12), nominal affine resources (CP-01/03), the freestanding heap (`heap.omni`) and `atomic.*`.
The hosted A85 contract (`task_scope`, `spawn`, `cancel`, `join`) is **unchanged**: it still forbids `Resource`, `Borrow`, `BorrowMut`, `View` and handles across a task boundary (`E_TASK_TRANSFER`).
Review contract: prompt 009 (section 5) and adendum 009A (COOP-01).

## 1. What is claimed, and the profile that can show it
A *real* task is a context (the 56-byte save area of `cpu.switch_context`) with its own stack, started by a scheduler that is plain Omni code on some CPU, running the function named by
`--thread-entry`. The `state=dead` record of `ktask.omni` is **not** such a task (it protects a record, it stops nothing); `coop.omni` is.
Claim: a task that owns resources can be cancelled before it starts, while it runs on the same or another CPU, while it is inside a critical section, after an acquisition or a close failed, and after an
externally visible effect may have been dispatched, **without** a leak, a double close, a premature close, a use after the stack was freed, a continuation on a freed stack or a false acknowledgement.
Not claimed: stopping a task that never reaches a checkpoint, cleanup after a trap, an NMI, the loss of a CPU or a power failure, real hardware, a scheduler policy.

## 2. The four events (adendum 009A) and who gives each
| Event | Meaning | Who writes it |
| --- | --- | --- |
| request | `stop` flag of the control block | the owner (`request_cancel`, release store) |
| cleanup finished = acknowledgement | state `DONE` (3), after the result | **only** the task (`finish`: the result, then `DONE`, both release stores) |
| execution quiescent | state `RETIRED` (5): the CPU has left the task | **only** the scheduler (`run`: its LAST access to the block is the release store `DONE -> RETIRED`) |
| stack reclaimable | `destroy` may free | the owner, and only if the state is `RETIRED` (or `CANCELLED_UNSTARTED`) |
After the task stores `DONE` it still executes: the return address of its last call is pushed on its stack and `cpu.switch_context` saves its registers in the control block. Both would land in freed
memory if `destroy` accepted `DONE`. `destroy` therefore frees **nothing** (answers 24, consumes the handle, the heap reports the leak) unless the task is retired; `await_retired` waits for it.
Other states: `NEW` (1), `RUNNING` (2), `CANCELLED_UNSTARTED` (4); 0 is freed memory and matches nothing. A task that has not started is cancelled by a compare-and-swap `NEW -> CANCELLED_UNSTARTED` and
started by `NEW -> RUNNING`: exactly one wins.

## 3. Ownership
* The owner holds `Resource<coop.Task>`, sealed in the module, which owns two heap blocks (control block, stack). Forged, opened or copied outside the module: `E_RESOURCE_ACCESS` / `E_RESOURCE_PRIVATE`.
* The resources of the task are ordinary `Resource<T>` locals of its body. The checker makes the body consume each one on every path **including the path taken after a cancellation**
  (`E_RESOURCE_UNCONSUMED`, `E_RESOURCE_MOVED`, `E_RESULT_UNHANDLED`) and keeps a loan from being live across the move that closes the resource (`E_BORROW_CONFLICT`).
* Fallible close (`Close` semantics, CP-03): the resource is consumed even when the close fails; the remaining resources are still closed; the first failure is the result of the task.
* A critical section (`critical.omni`) cannot yield (no `cpu.control`), so a request that arrives inside one is seen at the next checkpoint, with the lock released and the section complete.

## 4. Outcome of an end (`outcome`) and what a timeout means
`0` completed, `1` cancelled with no effect dispatched (NOT_APPLIED), `2` cancelled with an effect dispatched and not confirmed (**UNKNOWN_OUTCOME**), `3` failed, `4` not finished (**PENDING**),
`5` cancelled after the effect was confirmed (APPLIED). The classification reads the task's own journal (none / dispatched / confirmed), never a timer: `await_end` returning `Err(23)` says nothing
about what the task did and the outcome stays `4`.

## 5. Evidence (`tests/cp03_cancellation.py`, programs in `tests/corpus/cp03/`)
One CPU: normal, cancel before start, cancel while running, acquisition failure, close failure, effect cancelled before the dispatch / between dispatch and confirmation / after the confirmation / not at all,
abandonment, a task that uses more than half of a small stack (the head of the block below it is intact). Two CPUs: cancel while running on the application processor, a task that does not cooperate (the wait
times out, the outcome is PENDING, `destroy` abandons, the task then ends correctly on the memory it still had), a request inside a critical section, the acknowledgement-is-not-quiescence race with a
scheduler made slow to leave (and its control: a `destroy` that trusts the acknowledgement frees the block under the scheduler, which ends on state 0). Orders of the protocol on the IR; laws of the checker;
mutation `tests/mutants/b3_coop.json`.

## 6. Limits that stay written
Cooperative only: a task without checkpoints is abandoned, not stopped. An abandoned task leaks its two blocks on purpose. `RETIRED` is published only by `coop.run`; a scheduler that does not use it must
do the same or its tasks are never freed. Overlapping ranges, `memory.raw` writes to the control block and a hostile scheduler are outside the contract (`memory.raw` is a capability, not a sandbox).
