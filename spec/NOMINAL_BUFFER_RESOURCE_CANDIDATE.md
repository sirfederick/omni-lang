> Distribution status: WIP / NOT_RELEASED. Technical version labels describe independent contracts, not public release certification.

# Nominal resources that wrap a Buffer, generic nominal uses and borrowed parameters — CP-02 / CP-05 candidate

**Status:** local candidate for Omni Core 1.3.0.0, **not** a release. Extends `NOMINAL_AFFINE_RESOURCE_CANDIDATE.md`, `GENERIC_STRUCT_CANDIDATE.md` and
`MEMORY_LIFECYCLE_0_8_3.md` (reborrow). Representation: Wave21 / OMC21; a program that also uses generics or traits keeps its authoring capsule (Wave22).

## 1. Problem

A container library needs three things the language did not have: to hand a *whole container* to a function as `Borrow` / `BorrowMut` (only `Buffer` and
`u64`-handle nominal resources could be borrowed), to name an instance of a generic struct as such a resource (`Resource<Vec<u32>>`), and to reborrow a
borrow *parameter* (`borrow(p)` on a parameter was `E_BORROW_EXPIRED`). The master prompt asks for borrowed aggregates "or a safe explicit abstraction";
this is that abstraction. A general `Borrow<Record>` (a pointer to a record place) is **not** introduced: it would need a second representation for borrows and a
projection law for every field kind, and nothing in CP-01…CP-05 needs it once containers are resources.

## 2. Surface

* `Resource<Name>`, `Borrow<Name>`, `BorrowMut<Name>` where `Name` is a declared struct with **exactly one field**, which is either `u64` (a handle, as before) or
  `Resource<Buffer>` (the resource *wraps* a buffer).
* The name may be an instance of a generic struct: `Resource<Vec<u32>>`. The arguments are parsed into the type and, like every generic struct use, replaced by
  the monomorphized record before checking; the arguments are part of the type's identity (`Vec<u32>` and `Vec<u64>` are different types).
* A nominal resource is affine and has **no automatic cleanup**: it must be consumed (`E_RESOURCE_UNCONSUMED`, `E_RESOURCE_MOVED`, `E_RESOURCE_ACCESS` for a copy).

## 3. Operations (valid only in the module that declares the struct: `E_RESOURCE_PRIVATE`)

| Operation | `u64` handle | wraps a `Buffer` |
|---|---|---|
| `resource.seal(S { .. })` | `Resource<S>` from the record | `Resource<S>`; the record is consumed (its buffer moves into the resource) |
| `resource.unseal(move(r))` | the record (a copy of the handle) | the record that owns the buffer again |
| `resource.peek(Borrow<S>)` | a copy of the record | `E_RESOURCE_TYPE` (would copy an owner): use `inner` |
| `resource.inner(b)` / `resource.inner_mut(b)` | `E_RESOURCE_TYPE` | `Borrow<Buffer>` from a `Borrow<S>` or `BorrowMut<S>`; `BorrowMut<Buffer>` from a `BorrowMut<S>` only (`E_TYPE` otherwise) |

`resource.inner*` yields the buffer as a borrow *of the same storage and Place* as the borrow it came from. For the checking of a call's arguments it is that
borrow: `f(resource.inner_mut(x), resource.inner(x))` is `E_BORROW_CONFLICT`. Inside the declaring module the wrapped buffer behaves as any `Borrow<Buffer>`
(`buffer.len`, `buffer.read_*`, `buffer.grow` under `BorrowMut`, …), so growth while any other borrow of the container is live is not expressible.

## 4. Borrowed parameters are loans

A `Borrow<T>` / `BorrowMut<T>` parameter is a loan held by the caller for the whole call. It is entered in the loan ledger when the function starts, so that

* `borrow(p)` / `borrow_mut(p)` are ordinary reborrows (`E_REBORROW_KIND` for `borrow_mut` of a shared `p`);
* while a child reborrow is live the parent `p` is suspended: using `p` directly, or creating a second exclusive child, is `E_BORROW_CONFLICT`;
* passing `p` itself to a call is unchanged.

Before this change `borrow(p)` on a parameter was rejected with `E_BORROW_EXPIRED` and nothing suspended `p`. One existing expectation changed with it: returning
a reborrow of the region parameter through a local (`let local = borrow(b); return local`) is now diagnosed as `E_BORROW_ESCAPE`, as `BORROW_RETURN_REGIONS_CANDIDATE.md`
§2.2 says, instead of `E_BORROW_EXPIRED` (which only appeared because the reborrow itself was refused).

## 5. Library: `examples/storage/vec.omni`

`Vec<T: Codec>` is a `struct Vec<T: Codec> { buf Resource<Buffer> }` nominal resource; `Codec` is a trait with `size`, `put` and `get`, implemented for `u32` and `u64`
in the library and for any user type with `impl vec.Codec for UserType`. Operations take the container by borrow, so a failing call never takes the vector from
the caller: `new`, `len`, `capacity`, `get`, `set`, `push` (geometric growth through `buffer.grow`), `pop` (zeroes the slot) and `destroy` (the only consumer).
The count lives in the first four bytes of the buffer; elements start at byte 8. Outcome codes: `1` capacity, `2` budget, `3` host OOM, `10` index, `11` empty.

## 6. Evidence and non-goals

Evidence: `tests/cp02_borrowed_containers.py` (evaluator and native agree; leak oracle above the 1024-slot table; negatives for the nominal laws, privacy, kind
mismatch, borrow conflicts, element constraints, representation fences) and `tests/mutants/borrowed_containers.json`.

Not here (named so that they are not assumed): elements that own Resources (a container of resources needs per-element drop; CP-05), `Map`/`Set`, a pointer-like
`Borrow<Record>`, views and sub-ranges of a container (CP-02 remaining), a Buffer-wrapping resource for target profiles (the u64 handle over a raw region,
`examples/storage/region.omni`, remains the freestanding form).
