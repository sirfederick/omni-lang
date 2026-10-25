> Distribution status: WIP / NOT_RELEASED. Technical version labels describe independent contracts, not public release certification.

# Memory model of `atomic.*` — candidate (OMNI-CORE-PRO-FOUNDATION-001, CP-13 rows 13.5 and 13.6)

**Status:** `CANDIDATE`, frozen for the 1.3 SDK candidate; not certified. Profile `baremetal-x86_64` only. This text fixes what the orders **promise**, what the compiler and the
x86-64 backend **do** with them, and what the tests can and cannot show. It adds no feature: it names the contract of `ATOMICS_CANDIDATE_ST09.md` and the library that depends on it
(`examples/storage/mailbox.omni`, `tests/x64/{spin,epoch}.omni`).

## 1. What is atomic and what is not
* `atomic.load32/64`, `store32/64`, `cas32/64`, `fetch_add32/64`, `fence` are the only operations with an order. `raw.*` loads and stores are `volatile`: the compiler keeps them,
  keeps their order with respect to every other volatile or atomic access of the same thread, and does not merge them. They are **not atomic and not ordered between CPUs**.
  A plain (`raw.*`) location that one CPU writes and another reads is race-free **only** if the pair is ordered by a release/acquire edge (section 2). Otherwise the program has a data race
  and this contract promises nothing about the value read.
* `volatile` is not an order; `cli` is not a lock (`GUARDS_AND_LOCKS_CANDIDATE.md`); `memory.atomic` is not `memory.raw` (a mailbox needs both).

## 2. Orders and the happens-before they build
Orders are the literals 0 relaxed, 1 acquire, 2 release, 3 acq_rel, 4 seq_cst (`E_ATOMIC_ORDER` outside the table of each operation). They are the C++/LLVM orders of the same name
(LLVM `monotonic` = relaxed).

| Edge | Rule |
|---|---|
| program order | the operations of one thread, in the order written (the compiler cannot reorder volatile or atomic accesses across each other) |
| synchronizes-with | a **release** (or stronger) store S and an **acquire** (or stronger) load L that reads the value written by S (or by a later write in S's release sequence of read-modify-writes) |
| happens-before | the transitive closure of program order and synchronizes-with. A plain write that happens-before a plain read is visible to it; a write that does not is a race |
| RMW | `cas` and `fetch_add` read the latest value in the modification order of the cell; their success order applies to the read-and-write, a failed `cas` is a load with the failure order |
| coherence | for every single cell all threads agree on one modification order, and a thread never reads backwards in it, with every order including relaxed |
| fences | `fence(seq_cst)` is a full barrier: two seq_cst fences are totally ordered, and a store before a seq_cst fence is visible to a load after a seq_cst fence that follows it in that order. `fence` acquire/release/acq_rel order the relaxed accesses around them as in C++ (compiler barrier on x86) |
| seq_cst | all seq_cst operations are in one total order that agrees with program order and with happens-before |
| CAS failure | acquire at most (relaxed, acquire, seq_cst), never stronger than the success order (`E_ATOMIC_ORDER`) |

Not promised: fairness, progress (a CAS loop may fail forever against a hostile peer), freedom from ABA (a library carries a generation), a total order for relaxed accesses of different cells,
load-buffering outcomes are **not** produced by the bounded model but are not forbidden by the contract either (relaxed is C++ relaxed).

## 3. What the compiler and the backend do (checked by `tests/cp13_memory_model.py`)
| Omni | LLVM IR | x86-64 instruction |
|---|---|---|
| `load` relaxed / acquire / seq_cst | `load atomic volatile` monotonic / acquire / seq_cst | `mov` (all three) |
| `store` relaxed / release | `store atomic volatile` monotonic / release | `mov` (compiler barrier only) |
| `store` seq_cst | `store atomic volatile` seq_cst | `xchg` with memory |
| `cas` (any orders) | `cmpxchg volatile` | `lock cmpxchg` |
| `fetch_add` (any order) | `atomicrmw volatile add` | `lock xadd` |
| `fence` seq_cst | `fence seq_cst` | `mfence` |
| `fence` acquire / release / acq_rel | `fence acquire` / `release` / `acq_rel` | none (compiler barrier) |

Consequences, stated so that nobody argues from a passing x86 run:
* On x86 (TSO) a release store and an acquire load are plain `mov`s. A program that uses `relaxed` where the contract needs release/acquire still **passes** on x86, because the
  hardware keeps store→store and load→load order; it is nevertheless wrong against this contract and is wrong on any weaker target. Only the order argument in the IR, and the models
  below, tell the two apart.
* x86 allows **store→load reordering** (the store buffer). Dekker-style protocols (`epoch.enter`: publish the slot, then read the pointer) need the seq_cst store or fence;
  release/acquire is not enough, on x86 or in the model.

## 4. Evidence (what each artefact proves and does not)
| Artefact | Proves | Does not prove |
|---|---|---|
| `tests/cp13_memory_model.py` view-based model (relaxed / acquire / release / seq_cst fences) | exhaustively, for the bounded litmus tests MP, SB, CoRR and for the mailbox protocol with 2 messages in a 1-slot queue, which outcomes the contract allows; that the release/acquire pair is necessary (the relaxed variants have a violating execution) | linearizability, fairness, more than two threads, load buffering (the model has no promises) |
| the same file, x86-TSO model (store buffers) | that every outcome x86 can show is allowed by the contract model (the abstraction is sound for these tests) and that x86 hides the MP violation but not SB | the real hardware or QEMU |
| IR and instruction tests of `mailbox.omni`, `spin.omni`, `epoch.omni` | the orders the libraries actually emit (the only place where relaxed-for-release shows) | nothing about execution |
| two-vCPU runs (`mailbox_handoff`, the store-buffering litmus, `epoch_smp`, `lock_smp`) | on QEMU TCG with one host thread per vCPU: no loss, repetition, reordering or torn message in the runs; the fenced SB variant never shows the forbidden outcome | the relaxed SB variant is *reported*, not required: TCG does not have to exhibit the reordering; a green run does not show a barrier is unnecessary |

## 5. Non-claims
x86-64 only; QEMU TCG is not hardware; no ARM/RISC-V; no linearizability proof of any library; no DMA/device ordering (MMIO ordering is `MMIO_PORTS_CANDIDATE.md`); the bounded models
are bounded.

## 6. The bounded SPSC mailbox (`examples/storage/mailbox.omni`, CP-13 rows 13.5 / 13.7)
Two CPUs, one producer and one consumer, a capacity that is a power of two, a fixed slot size, plain data only. The producer writes the payload with plain stores and publishes the tail with a **release** store; the consumer
reads the tail with an **acquire** load and then the payload, and releases the slot with a **release** store of the head that the producer reads with **acquire** (orders pinned on the IR, `MailboxContractTests`).
Full answers 15, empty 16, nothing blocks. Exclusivity of the ends: `open_producer` / `open_consumer` claim a cell with an acq_rel compare-and-swap, so exactly one of two simultaneous opens wins (5000 rounds with both CPUs
lined up at a barrier, `MailboxEndRaceTests`; the control that claims with a load and a store shows two winners in a large share of the rounds); a second open answers 14; `create` answers 14 and changes nothing when an end is
open. The nominal resource makes a *handle* non-copyable; the claim is what makes the *end* exclusive, under the platform precondition that nothing writes the claim cells with raw stores. A message must have a native
layout (integers and plain records); a `Resource`, a loan, `Text` or an enum is `E_LAYOUT`, so ownership never travels through the queue as bytes (`TransferTests`), and the record of a sealed resource that does travel as bytes
gives the receiver no authority (`E_RESOURCE_ACCESS`). Not claimed: MPMC, linearizability, ownership transfer, progress under a hostile peer.
