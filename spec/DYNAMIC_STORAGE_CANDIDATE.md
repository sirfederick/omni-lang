> Distribution status: WIP / NOT_RELEASED. Technical version labels describe independent contracts, not public release certification.

# Dynamic storage and allocator — CP-04 candidate

**Status:** local candidate for Omni Core 1.3.0.0, **not** a release. Normative intent: `MEMORY_AUTHORITY_0_8.md` §8 (allocator-explicit, no
hidden heap, typed recoverable OOM) and `DATA_LANGUAGE_0_8_1.md` (collections need a proved allocator). Representation: Wave21 / OMC21.

## 1. Shape of the solution

Core adds **two primitives** to the existing owned `Resource<Buffer>`. Everything else is an Omni library written on top
(`examples/storage/vec_u32.omni`, `examples/storage/arena.omni`), so there is one ownership law, no second heap and no collector:
the owner of the bytes is always a `Resource<Buffer>` released exactly once by the existing cleanup.

| Operation | Operands | Result | Capability |
|---|---|---|---|
| `buffer.grow` | `BorrowMut<Buffer>`, `u32` new length | `Result<u32,u32>`: `Ok(new length)` | `memory.write` |
| `buffer.zero` | `BorrowMut<Buffer>`, `u32` offset, `u32` length | `Result<u32,u32>`: `Ok(1)` | `memory.write` |

## 2. Semantics

* **Growth keeps the owner and the handle.** The new length must be `>=` the current length; the existing bytes are preserved and the new
  bytes are zero. Growing to the current length succeeds and changes nothing.
* **Outcome codes** (same meaning as `buffer.alloc`): `1` the length exceeds the 1 MiB per-buffer limit, `2` the 16 MiB total budget would be
  exceeded, `3` the host is out of memory, `4` the request would shrink the buffer. They are checked in the order 4, 1, 2, 3 and **a refusal
  changes nothing**: not the contents, not the length, not the accounted total. A request of `2^32 - 1` is code `1`; no arithmetic wraps.
* **`buffer.zero`** clears `[offset, offset + length)`. The range is valid iff `offset <= len && length <= len - offset` (no addition, so no
  wrap); a zero-length range at `offset <= len` is valid. Otherwise code `1` and **no byte changes**.
* **Borrow law.** Both operations take `BorrowMut<Buffer>`. A `BorrowMut` excludes every other loan on the buffer, so any `Borrow`, returned
  borrow (`Borrow<Buffer>` result region) or `BorrowMut` that is still live makes the call `E_BORROW_CONFLICT`: *reallocation while a borrow
  into the old backing is live is not expressible*. A shared borrow is `E_TYPE`; a moved or released owner is `E_RESOURCE_MOVED`; the result
  must be handled (`E_RESULT_UNHANDLED`).
* **Accounting.** Growth is charged to the same budget as `buffer.alloc`; releasing the buffer returns the whole grown size.
* **Targets.** Defined for the hosted profile only, in both the evaluator and native code. Under `--target-profile` the call is refused with
  `E_TARGET_PROFILE`; a freestanding allocator is an Omni library over raw memory, not these primitives.
* **Representation.** Programs that call them need Wave21/OMC21; an older label is `E_VERSION` (same fence as the other 1.3 intrinsics).

## 3. Libraries (Omni source, not Core)

Both libraries leave the buffer owned by the caller and never hide an allocation.

* `vec_u32` — a growable vector of `u32`: `new_buffer(capacity)`, `reserve`, `push` (geometric growth), `get`, `set`, `pop` (zeroes the vacated
  slot). The element count is a plain value passed in and returned, so a failing call cannot leave it half updated. Codes: `1` over the
  262144-element limit, `2` budget, `3` host OOM, `10` index `>= len`, `11` element-count arithmetic would overflow.
* `arena` — a bump allocator over one buffer with runtime-sized blocks and power-of-two alignment `1..16` measured from the buffer base (the
  host base is 16-aligned). A block is an offset (never an address), so growth cannot invalidate it. Typed accessors check the epoch, the
  block bounds and the element alignment. `reset` zeroes what was handed out and starts a new epoch, so every earlier block is stale
  (region reclamation). Codes: `1` over the 1 MiB limit, `2` budget, `3` host OOM, `4` stale, `5` bad alignment, `6` size/offset arithmetic
  would overflow, `7` index outside the block, `8` block not aligned for the element type, `9` epoch counter exhausted.

## 3b. Region over raw memory (`examples/storage/region.omni`) — target profiles and the evaluator

For targets without a host buffer the allocator is a typed bump allocator over a **raw memory range** handed over by the platform. It uses
only existing Core: `layout.size/align<T>` (CP-07), `raw.read/write<T>`, a nominal affine `Resource<Region>` and generic functions.

* **Ownership.** `create(base, size)` returns `Result<Resource<Region>,u32>`; `destroy(move(r))` is the only way to consume it, so forgetting the
  teardown is `E_RESOURCE_UNCONSUMED` and using the region after it is `E_RESOURCE_MOVED`. Allocation takes `BorrowMut<Region>`, access `Borrow<Region>`.
* **State** lives in a 32-byte header at `base` (magic, top, limit, epoch); a damaged header is code `10` and changes nothing.
* **Typed blocks.** `alloc<T>` / `alloc_array<T>(count)` return `Slot<T>` / `Slice<T>` (address + epoch). Size and alignment come from the element type;
  `count` may be 0. `T` must be a plain record (a scalar has no layout: `E_LAYOUT`; wrap it in a one-field struct). `store`/`load` (`_at` for arrays)
  re-check the epoch, the block range, the index and the alignment first, and answer `4` stale, `7` index, `8` misaligned instead of reaching memory.
* **Failure** is typed and leaves the header untouched: `1` range exhausted, `5` bad range or limit, `6` size/address arithmetic would wrap, `9` epoch exhausted.
* **Growth** of the backing range is `extend(new_limit)` (monotonic, no wrap). **Reclamation** is `reset` (scrubs what was handed out, new epoch, every earlier
  block stale) and `destroy` (scrubs data and header, returns the bytes that were in use).
* **Evidence.** One program, `tests/corpus/cp04/region_conformance.omni`, produces a serial transcript that is derived by hand in the test, produced by
  the evaluator and produced by a freestanding x86-64 image booted under QEMU; the three must agree.

## 3c. Heap with individual release over raw memory (`examples/storage/heap.omni`, `rvec.omni`) — row 4.9

Region releases everything at once. For the profiles without a host buffer (`buffer.grow` is `E_TARGET_PROFILE`) the allocator that frees one block at a time, reuses
the space and merges neighbours is also an Omni library over a raw range; it adds nothing to Core.

* **Ownership model (design A).** The range has **one owner**: `Resource<Heap>` is a nominal affine resource (`create` hands it over, `destroy` consumes it once; the
  checker's `E_RESOURCE_UNCONSUMED` / `E_RESOURCE_MOVED` apply). It cannot be forged (a `Heap` built from a number is a plain value: `borrow`, `borrow_mut` and `move`
  answer `E_RESOURCE_ACCESS`), opened (`resource.peek`/`unseal` outside the module: `E_RESOURCE_PRIVATE`), copied or torn down while lent (`E_BORROW_CONFLICT`).
  `Block<T>` is **not** an owner: it is a plain copyable descriptor `{address, count, serial}`. Nothing in it is a claim of exclusivity; what protects a block is that
  every operation that touches bytes takes a loan of the heap and revalidates the descriptor (magic, range, alignment, tag and serial in the block head, size). `free` is
  the revocation: afterwards every copy of the descriptor is stale (`4`).
* **Identity and revocation.** Every allocation takes a new serial (never reused; the counter stops with code `9` before a tag could be zero). The head of a live block holds the
  serial mixed with a constant; a free block holds 0. A reused address is a new serial (ABA), a descriptor of another heap lies outside this range (`4`), and serials continue
  across incarnations of a range: `destroy` leaves a retired mark and the last serial, `create` over it starts after it and refuses (`9`) a range whose serials are spent.
  Residual: a block absorbed by a merge and now inside a live block holds user bytes where its head was; a stale descriptor of it is detected unless those bytes are exactly its
  64-bit tag (the user would have to write that value).
* **`descriptor_at`.** Rebuilds the descriptor of the live block that starts at an address (serial recovered from the head). It proves that a live block starts there and that
  `count` elements fit; it does **not** prove ownership and creates no owner. It exists for a library that keeps the address in its own sealed resource (`rvec`, `ktask`):
  the exclusivity of those blocks is the resource's, which nobody else can build or open. Code that forges addresses with `memory.raw` can free or overwrite such a block; the
  library answers every later use with a typed error (`4`, `11`, `12`) and never follows a damaged link, but `memory.raw` is a capability, not a sandbox.
* **Layout.** 64-byte header (magic, brk, limit, serial, free_head, live, 2 spare); blocks are a 16-byte head `{size, tag}` plus a 16-aligned payload (a multiple of 16, at least
  16); the free list is ordered by address and kept in the first payload word of each free block. First fit, split only when at least a 16-byte block remains, merge with both
  neighbours on `free`, and a free block that touches the end of the carved area goes back to the untouched range. Payloads are zero when handed out and zeroed on release and teardown.
  Overlapping ranges are a violation of the platform contract of `create` (there is no registry of ranges); the library cannot detect it.
* **Failure** is typed and changes nothing (the checks come before the first write): `1` exhausted, `4` stale or unknown, `5` bad range, `6` size/address arithmetic would wrap,
  `7` index (or realloc to fewer elements), `8` unaligned, `9` serial counter exhausted, `10` header corrupt, `11` the descriptor claims more than the block has, `12` damage
  found while walking (a link outside the carved area, backwards, unaligned, a size beyond the area, an odd size, a zero live count).
* **`rvec.omni`** is a growable vector of **plain** elements (`T` with an owning field has no layout: `E_LAYOUT`) kept in two heap blocks (metadata and elements) behind a sealed
  `Resource<RVec<T>>`. `new`, `push`, `pop`, `get`, `set`, `reserve`, `len`, `capacity`, `destroy`; growth by `realloc_array` (allocate, copy, release), so a failing call changes nothing;
  code `7` index, `13` pop of an empty vector. Blocks released behind the vector's back make later calls answer `4` and `destroy` report it.
* **Evidence.** `tests/corpus/cp04/heap_conformance.omni` and `rvec_conformance.omni`: serial transcripts derived by hand in `tests/cp04_dynamic_storage.py`, produced by the evaluator and by
  a freestanding x86-64 image under QEMU (`nm -u` empty); checker-level laws for the owner, the loans and the plain-only elements; mutation campaign `tests/mutants/heap_libraries.json`.

## 3d. A kernel aggregate lent by API (`examples/storage/ktask.omni`) — row 2.3b

A multi-field kernel aggregate (a task control record: id, state, priority, stack range, ticks) lives in one block of the heap and is held as a sealed `Resource<Task>`. It is lent with
`Borrow<Task>` (reads) and `BorrowMut<Task>` (changes) to functions of any module, and **only** the functions of `ktask` can look inside or change it, so the invariants (a state machine,
a stack range that does not wrap, a priority range, ticks that do not wrap) hold for every holder. Outside the module the checker refuses: opening, unsealing or sealing the resource
(`E_RESOURCE_PRIVATE`), a `Task` made from a number (`E_RESOURCE_ACCESS`), a field access (`E_TYPE`), two changes at once, a change while a read is lent and the teardown while lent
(`E_BORROW_CONFLICT`), a change through a shared loan (`E_TYPE`), a returned loan that does not come from a loan parameter (`E_BORROW_ESCAPE`) and a loan kept in a record (`E_TYPE`).
Codes: the heap's plus `20` argument out of range, `21` transition not allowed, `22` ticks charged to a task that is not running. Evidence: `ktask_conformance.omni` (evaluator and QEMU
transcripts), `KtaskLibraryTests`, `tests/mutants/ktask_libraries.json`.

## 4. Evidence and non-goals

Evidence: `tests/cp04_dynamic_storage.py` and `tests/corpus/cp04/*.omni` (evaluator and native agree on every positive program; leak oracles
exceed the 1024-slot table; mutation results are recorded in the CP-04 receipt).

Not in this candidate (named so that they are not assumed): elements that own Resources (a `Vector` of owning values needs per-element drop
and belongs to CP-05); a generic `Vector<T>` (CP-05); an allocator for target profiles (a library over raw memory, CP-07/08);
shrinking or returning memory to the host before release; a global allocator interface selectable from Omni (allocator identity stays an
ordinary value the caller passes).
