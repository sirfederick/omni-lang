> Distribution status: WIP / NOT_RELEASED. Technical version labels describe independent contracts, not public release certification.

# CP-05 candidate — allocator contract, hash/equality, Map/Set, and the iterator contracts

Status: candidate for Core 1.3.0.0. Libraries written in Omni (`examples/storage/alloc.omni`, `vec.omni`, `map.omni`, `seq.omni`) plus one language change: a generic
bound can name a trait of an imported module (`A: alloc.Allocator`). No ownership law is added: a collection is a nominal resource lent with Borrow / BorrowMut and
consumed once.

## 1. Qualified bounds

`<A: Allocator>` names a trait of the declaring module; `<A: alloc.Allocator>` names a **pub** trait of the module the declaring module imported as `alloc`. The same
resolution serves the bound at the declaration (`E_GENERIC_CONSTRAINT` when it names no trait, `E_VISIBILITY` for a private one) and the check at every instantiation
(a type with no impl of that trait is `E_GENERIC_CONSTRAINT`). Before this, a library could only bound on traits of its own module, so a container could not require an
allocator or a codec defined elsewhere.

## 2. The allocator contract (`alloc.omni`)

```omni
pub trait Allocator {
  func allocate(bytes u32) Result<Resource<Buffer>,u32> !{memory.write}
  func resize(b BorrowMut<Buffer>, bytes u32) Result<u32,u32> !{memory.write}
  func release(b Resource<Buffer>) u32 !{memory.write}
}
```
An allocator is a **policy type** named as a type parameter: `Vec<u32, alloc.Heap>`, `Map<u32,u64,MyPolicy>`. The methods take no receiver, the choice is static
(monomorphized): no vtable, no hidden global, no ambient heap. `alloc.Heap` wraps the runtime buffers (`buffer.alloc/grow/release`); the program substitutes another by
naming another type, and can write its own (`impl alloc.Allocator for Tiny`). A container allocates, grows and releases through its allocator only. Typed failures are the
allocator's own (the runtime's are 1 limit, 2 budget, 3 host out of memory) and always leave the container as it was.

Provided for the collections that keep their elements in **one byte buffer**: `Vec`, `Map`, `Set`. The collections of owned resources (`Seq`, `Registry`) keep their cells in
slot buffers (`slots.*`), which are typed by the element, and a trait method cannot be generic over the element type: they draw from the same runtime budget and are not
parametrized by this trait. That is a limit of the language, stated here, not a hidden path.

`Vec<T: Codec>` became `Vec<T: Codec, A: alloc.Allocator>`; every use names the allocator.

## 3. Hash and equality (`map.omni`)

`Key` is the protocol of a key: how it is stored (`size`, `put`, `get`), how it is hashed (`hash(v) u64`) and when two keys are the same (`same(a, b) bool`). The language
does not derive them: a type that is a key says so with an `impl map.Key for T`, and `same` decides identity (a key type may deliberately treat several values as one).
Implemented for `u32` and `u64`; a user type implements it the same way. Values are plain data stored by `vec.Codec`.

## 4. `Map<K,V,A>` and `Set<K,A>`

One table over one `Resource<Buffer>` from the allocator `A`: open addressing with linear probing, header of four `u32` (live entries, used slots, slots, version), slots of
`state byte | key | value`. A load of more than 3/4 grows the table: the buffer grows through the allocator first (a failure there changes nothing), then the entries are placed
again in place. When the table cannot grow (the limit, or the allocator refuses) it drops its tombstones in place; with none to drop and no free slot the insert is
`Err(1)`. `Set<K,A>` is the same table with a value of zero bytes.

| Operation | Result |
|---|---|
| `insert(m, k, v)` / `set_insert(s, k)` | `Ok(1)` added, `Ok(0)` already there (value replaced); `Err(code)` nothing changed |
| `get(m, k)` | `Ok(v)` or `Err(13)` |
| `remove(m, k)` / `set_remove(s, k)` | the removed value (`Ok(1)` for a set) or `Err(13)`; the slot becomes a tombstone |
| `contains`, `len`, `capacity` | plain reads |
| `destroy` / `set_destroy` | releases the buffer through the allocator, once |

## 5. Invalidation and the iterator contracts

- **Values are copied out** (`get`, `remove`, cursor entries), so no borrow into the table can dangle when it grows: there is nothing to invalidate. Growth needs `BorrowMut`,
  so it cannot happen while the table is lent.
- **Map / Set cursor.** `cursor(m)` records the position 0 and the table **version** (raised by every new key, removal and rehash). `next(m, c)` returns the next entry with the
  cursor that follows it, `Err(14)` when there are no more, `Err(15)` when the table changed since the cursor was made. The cursor is plain data and proves nothing: `next`
  checks it every time.
- **Cursor of a collection of resources (`seq.Cursor`).** `more(v, c)` checks the position against the sequence on every step, `at(v, c)` **lends** the element for the life of
  the borrow of the sequence and `advance(c)` moves on. Walking never moves, copies or releases an element; the elements end in `destroy` / `close_all`. A push, pop or
  growth while an element is lent is `E_BORROW_CONFLICT`; if the sequence shrank under a cursor, `more` is false.
- `for x in sequence` keeps its closed plans (`ITERATION_PROTOCOL_0_8_2.md`); user-defined iterators in that syntax stay out. This contract is the safe protocol a library offers
  without extending the syntax.

## 6. Not provided

A Map of owned resources as values (the `Seq` / `Registry` cover collections of resources; a keyed one needs an owned-slot table), a generic algorithm over any cursor (a trait
cannot name the container type), iteration order guarantees beyond "every live entry once", concurrent access, and consumption of a library by another package without
copying source (row 5.10: the package system admits no imports between packages; it is its own unit).
