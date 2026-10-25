> Distribution status: WIP / NOT_RELEASED. Technical version labels describe independent contracts, not public release certification.

# Owned slots — dynamic storage whose elements are resources — candidate (OMNI-CORE-PRO-FOUNDATION-001, CP-01 / CP-04 / CP-05)

**Status:** `CANDIDATE`, not adopted, not certified. Hosted profile only. Implementation: `runtime/omni_runtime.c` (`omni_slots_*`), `compiler/src/check.cpp` (checker and
evaluator), `compiler/src/llvm.cpp`, `compiler/src/formats.cpp` (Wave21/OMC21 fence); library `examples/storage/seq.omni`; tests `tests/cp01_owned_slots.py`; mutants
`tests/mutants/owned_slots.json`.

## 1. Why a Buffer cannot hold resources

A nominal resource is a typed handle. A `Resource<Buffer>` stores bytes; the only way to put a resource into bytes is to turn its handle into an integer and to
rebuild it later with `resource.seal` from that integer. That is not ownership: the module that does it can mint any handle from any integer, a copy of the
bytes is a second owner, and nothing says whether the slot is still occupied. `vec.omni` therefore stores only plain data, and its `Codec` trait cannot be
implemented for a resource (`get` returns a copy). The handle must never become an integer visible to Omni code.

## 2. Decision: slot-bearing buffers with a type tag and occupancy, moved in and out whole

`slots.alloc<T>(cells)` returns a `Resource<Buffer>` that the runtime marks as *slot-bearing*: `cells` cells of 8 bytes, one occupancy byte and one 4-byte generation per cell (13 bytes accounted per cell), and the
canonical key of the nominal record `T` (compared whole). No new type is introduced (the buffer is still `Resource<Buffer>`, borrowed with `Borrow<Buffer>` /
`BorrowMut<Buffer>`), so no Wave/Wire/ONME type encoding changes; the new operations are named calls under the Wave21/OMC21 fence, like `buffer.grow`.

| Operation | Signature | Outcome |
|---|---|---|
| `slots.alloc<T>(cells)` | `u32 -> Result<Resource<Buffer>,u32>` | 1 limit, 2 budget, 3 host out of memory (as `buffer.alloc`); `T` must be a nominal resource record |
| `slots.len(b)` / `slots.count(b)` | `Borrow<Buffer> -> u32` | cells / occupied cells |
| `slots.state<T>(b, i)` | `Borrow<Buffer>, u32 -> u32` | 0 empty and usable, 1 occupied, 2 index out of range, 3 not a slot buffer or another `T`, 4 empty but **exhausted** (its generation reached the horizon: it takes no more `put`) |
| `slots.gen<T>(b, i)` | `Borrow<Buffer>, u32 -> u32` | the generation of the cell (starts at 1, every take raises it up to the horizon, 2^32-1; an empty cell at the horizon is state 4); 0 = out of range or another `T` (CP-06, `CALLBACK_REGISTRY_HOSTED_CANDIDATE.md`) |
| `slots.put<T>(b, i, move(x))` | `BorrowMut<Buffer>, u32, Resource<T> -> Result<u32,Resource<T>>` | `Ok(i)`: the cell now owns `x`. `Err(x)`: refused (state was not 0), the caller gets `x` back, nothing changed |
| `slots.take<T>(b, i)` | `BorrowMut<Buffer>, u32 -> Result<Resource<T>,u32>` | `Ok(x)`: ownership leaves the cell, which is empty and zeroed. `Err(state)`: nothing changed |
| `slots.borrow<T>(b, i)` / `slots.borrow_mut<T>(b, i)` | `Borrow<Buffer>` / `BorrowMut<Buffer>, u32 -> Borrow<T>` / `BorrowMut<T>` | the element lent for as long as the borrow of `b`; an empty or foreign cell is the fatal fault `E_SLOT_STATE` (callers check `state` first, as they check an index) |
| `slots.grow(b, cells)` | `BorrowMut<Buffer>, u32 -> Result<u32,u32>` | as `buffer.grow` for cells; occupancy and contents are kept |
| `slots.release(move(b))` | `Resource<Buffer> -> Result<u32,Resource<Buffer>>` | `Ok(0)` when no cell is occupied; `Err(b)` otherwise, nothing freed |

Rules that make this ownership and not serialization:

- **No integer ever represents the handle in Omni.** `put` and `take` move a typed `Resource<T>`; the runtime copies the 64-bit value between the owner and the cell.
  The byte accessors (`buffer.read_*`, `write_*`, `zero`, `freeze`, `grow`) on a slot-bearing buffer return the outcome `8` (not a byte buffer): there is no path from
  a cell to bytes.
- **Exactly one owner.** A cell is occupied or empty; `put` into an occupied cell is refused and returns the resource; `take` from an empty cell returns the state;
  a taken cell is zeroed. A resource is in the caller, or in exactly one cell, never both.
- **The key prevents type confusion.** The buffer keeps the canonical key of its resource type (`t.Tok`) and every operation compares the **whole key**, never a
  hash of it, so two types cannot be confused by a collision. `slots.alloc<Tok>` and `slots.take<Other>` on the same buffer is state `3`; a module cannot turn a `Tok` into an `Other` by
  routing it through a buffer. `T` must be a nominal record, so `alloc<u32>` is `E_GENERIC_CONSTRAINT`/`E_RESOURCE_TYPE` and no plain value is ever stored as an
  owned element.
- **No new authority.** Moving a resource in and out needs to own it; nothing here can mint, open (`seal`/`unseal`/`peek` stay private to the declaring module) or
  copy one. A borrow of an element is a reborrow of the borrow of the buffer (monoorigin return region): it dies with it, and `grow` (`BorrowMut`) conflicts with
  every live element borrow, so growth can never invalidate an element in use.
- **Exact cleanup.** The buffer is a `Resource<Buffer>`; freeing it while a cell is occupied would lose the element resources, so `slots.release` refuses
  (`Err(b)`), and the automatic release of a leaf at scope exit, `buffer.release` and `buffer.freeze` on an occupied slot buffer are the fatal fault
  `E_SLOT_OCCUPIED` instead of a silent leak. A library owns its elements by draining with `take` and consuming each one through a trait method that takes
  `Resource<Self>` (`GENERIC_RESOURCE_CANDIDATE.md`), then releasing.
- **Hosted only.** Profiles without a Core allocator keep `E_TARGET_PROFILE`, as for `buffer.grow`.

## 3. Library on top: `examples/storage/seq.omni`

`Seq<T>` is a nominal resource wrapping the slot-bearing buffer (`resource.inner*` only inside the module). The occupied cells are exactly `0 .. len-1`,
so the length is `slots.count` and there is no second counter to disagree with it. API: `new`, `len`, `capacity`, `reserve` (geometric growth, at least 4 cells,
clamped by the buffer limit; a failure keeps every element), `push` (moves the element in; when full the push is refused and the element is the error), `pop` (moves
the last element out to the caller, who must consume it), `get` / `get_mut` (the element lent for the life of the borrow of the sequence; `index < len` is a
precondition) and `destroy`, which moves every remaining element out, last to first, disposes it through `Dispose.dispose(Resource<Self>)` and releases the buffer.
`Dispose` is the infallible ending: its `u32` is a report that `destroy` sums, not an error channel. The ending that can fail (`Close.finish`, with the error preserved and
every remaining element still closed by `close_all`) is the CP-03 contract in `CLEANUP_FAILURE_CANDIDATE.md`; the sequence itself takes no trait bound, the function that ends it does. `buffer.freeze` of a slot buffer consumes it: an empty one is freed and the outcome is 8 (nothing is
frozen), an occupied one is the `E_SLOT_OCCUPIED` fault.

## 4. Tests (`tests/cp01_owned_slots.py`; the mutants in `tests/mutants/owned_slots.json` cover each rule)

creation and zero length; push/pop transfer (ownership leaves the caller and returns on pop); borrowing an element and mutating it through `BorrowMut`; growth past
the table size with live elements kept; OOM and budget on `alloc` and on `grow` leaving the vector and its elements intact, and `push` returning the element;
`take_at` and exact cleanup with 3000 elements (a leak or double release exceeds the 1024-handle table); `destroy` of a non-empty vector disposes each element once
(spy `Dispose`); refusals: put into an occupied cell, take from an empty one, wrong tag, bytes accessors, release while occupied, borrow conflict with growth,
use after move, element of another module opened, plain value as element; evaluator and native agree.

## 5. CP obligations

| Row | Satisfied by |
|---|---|
| CP-01 1.7 | a dynamic collection of resources with the one ownership law |
| CP-04 4.7 | storage of elements that own resources |
| CP-04 4.8 | `destroy`/`release` with live elements: refused or fatal, never silent |
| CP-05 5.7 / 5.9 | a container of resources instantiated for distinct resources; distinct types |
| CP-15 | the operations are named calls under the existing representation fence; no new type encoding |
