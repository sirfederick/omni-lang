> Distribution status: WIP / NOT_RELEASED. Technical version labels describe independent contracts, not public release certification.

# Omni Product Types and Canonical Layout — 0.2 alpha.4

**Language:** Omni Language 0.2.0-alpha.6 (product semantics introduced in alpha.4)  
**Status:** normative for inherited alpha.4 Tuple/Array/layout semantics under alpha.5.  
**Schemas:** `omni.type-descriptor/1`, `omni.layout-descriptor/1`.

## 1. Purpose

Alpha.4 adds fixed product values that are useful to ordinary applications and that later profiles can map efficiently across ABI/runtime boundaries without giving those boundaries authority over core language semantics.

Implemented product types:

```text
Tuple<T0,T1,...>
Array<T,N>
```

A product type is a value type. It is not a pointer, allocation, ResourceRef, capability, lease, ObjectID or persistence record.

## 2. Tuple

`Tuple<T...>` is structural and ordered. Element order and element types are part of the type.

```omni
let p Tuple<u8,u32,bool> = tuple(7u8, 42u32, true)
let n u32 = tuple.get(p, 1u32)
```

Rules:

- `Tuple<>` is the unit tuple and is valid.
- `tuple(...)` infers the exact tuple type from its arguments.
- `tuple.get(value, index)` requires an unsuffixed or `u32` compile-time integer literal in alpha.4.
- A statically out-of-range tuple index is `E_BOUNDS`.
- Tuple equality/operators are not introduced in alpha.4.

## 3. Fixed Array

`Array<T,N>` is homogeneous and fixed-length. `N` is part of the semantic type.

```omni
let a Array<u16,3> = array(10u16, 20u16, 30u16)
let n u32 = array.len(a)
let x u16 = array.get(a, 1u32)
let b Array<u16,3> = array.with(a, 1u32, 99u16)
```

Rules:

- `array(v0,...)` requires at least one value and all element types are identical.
- `array.fill(value,N)` constructs an `Array<T,N>`; `N=0` is allowed.
- `array.len(a)` is `u32`.
- `array.get(a,index)` is runtime bounds checked when the index is not statically known.
- `array.with(a,index,value)` performs a functional copy-update and returns a new array. It does not mutate `a`.
- `Array<T,N>` and `Array<T,M>` are distinct if `N != M`.
- Alpha.4 limits `N` to 65535 to bound compiler/resource costs. This is an implementation limit, not a permanent language ABI promise.

## 4. Bounds safety

Safe product operations never perform unchecked indexing. A bounds violation produces stable runtime diagnostic `E_BOUNDS` in both evaluator and native execution.

This is a language semantic requirement, not an optimizer hint.

## 5. Current linear/async restriction

Alpha.4 temporarily rejects direct product elements whose type is `Resource`, `Borrow`, `Future`, `Stream`, or `Result` with `E_PRODUCT_LINEAR` where the compiler cannot yet prove nested lifecycle semantics.

This is conservative. It must not be interpreted as a permanent statement that product types can never contain such values. Generalized ownership/drop/borrow semantics are a later memory-model gate.

## Core 1.3 owning Tuple amendment (frozen for implementation)

Tuple may contain admitted Resource, owning product and pending-sum elements.
This supersedes only the Tuple linear restriction above. Array and borrowed/
async element restrictions remain. Copy is derived from every concrete element;
an owning Tuple is immutable and cannot be copied, captured or discarded.

The same typed projected obligations used by records apply at literal tuple
indices, recursively through fields and other tuples. `tuple.get` retains its
literal-u32 index and bounds law. Its selected Copy element is readable; a
Resource element requires explicit move/borrow, a pending sum transfers once,
and an owning product requires whole-product move. `move(tuple)` reconstructs
the tuple by transferring its owning elements and copying its Copy elements.
Loans conflict on identical/prefix Places; distinct proven literal indices are
disjoint. Dynamic or temporary ownership projections are rejected, not guessed.

Destructuring transfers all owning elements to their named bindings; `_` cannot
erase one. Buffer leaves are cleaned once in reverse element order; nominal and
pending leaves require explicit consumption. Moved leaves are not cleaned again.
Record and Tuple use the same leaf/Place/exit checks. No sum destructor, implicit
authority, pointer or alternative ownership type is introduced.

Existing Tuple AST/Wave/Wire encodings suffice. Active owning Tuple use requires
Wave21/OMC21 (Wave22 authoring capsules retain precedence). The checker derives
the writer requirement from concrete signatures/expressions and recomputes it;
it is never deserialized authority. Lower labels fail E_VERSION during semantic
validation even when an inferred constructor hides its element type. Historical
ONME2 projection retains its original selection. Plain-data layout descriptors
remain Copy-only; adding ownership does not make resource tuples portable data.

## Core 1.3 owning Array amendment (frozen for implementation)

`Array<T,N>` may hold an element `T` that owns a Resource, an owning product or a
pending sum. This supersedes only the Array linear restriction above; Borrow,
BorrowMut, Future, Stream and View elements remain rejected (`E_PRODUCT_LINEAR`).

* **Bound.** An owning Array has `1 <= N <= 16` (`E_LIMIT` otherwise), the same
  bound as Tuple. Each element is an individually tracked Place, whole moves are
  rewritten into N element moves and cleanup is emitted per element, so the
  checker and LLVM work grow linearly with N (measured: 196 lines at N=1, 601 at
  N=16 for one consuming and one forwarding function, about 27 lines per element).
  Larger owning collections are the dynamic storage of CP-04/CP-05, not this type.
  Arrays whose elements own nothing keep their 65535-element limit and their IR.
* **Places.** Only a literal u32 index names an element: `a[2u32]`,
  `array.get(a, 2u32)`. The index is bounds-checked at check time (`E_BOUNDS`). A
  dynamic index cannot prove which element is read or moved and is rejected
  (`E_ARRAY_OWNING_INDEX`), also under `move`/`borrow`/`borrow_mut`.
  Distinct literal indices are disjoint; identical or prefix Places conflict.
* **Values.** An element of Copy type is not possible (an owning Array has only
  owning elements); a Resource element needs explicit `move`/`borrow`, a pending
  element transfers once when read, an owning product needs a whole move.
  `move(a)` is rewritten to `array(move(a[0]), ..., move(a[N-1]))`.
* **Rejected.** Copying the Array or an element, `var`, capture by a closure,
  `array.fill` (would duplicate an owning value), `array.with` (would discard or
  duplicate one), `view(a)`, `for x in a`, and any projection, length or
  iteration of a temporary Array that is not bound to an owner
  (`E_RESOURCE_ACCESS`). `array.len(a)` on a bound owner is static and does not
  move anything.
* **Cleanup.** Buffer leaves are released once in reverse element order on every
  structured exit; moved elements are skipped; nominal and pending leaves must be
  consumed explicitly. A failure while building the Array releases the elements
  already acquired through their own bindings.
* **Representations.** No new encoding. Active owning Array use requires
  Wave21/OMC21 through the same checker-derived (never deserialized) fence as
  owning Tuples; `E_VERSION` otherwise. Plain-data layout descriptors remain
  Copy-only.

## 6. Canonical plain-data layout

`omni type layout TYPE` exposes a versioned canonical layout descriptor for context-free plain-data types supported by layout schema 1.

Current eligible primitives:

- fixed-width integers;
- `bool`;
- eligible fixed arrays;
- eligible tuples recursively composed from eligible types.

The current representation is named:

```text
canonical-little-endian-v1
```

Rules:

- integer size is its width divided by 8;
- integer alignment equals its byte size in schema 1;
- `bool` is size/alignment 1;
- arrays are contiguous `N * element_size`, aligned as the element;
- tuples use deterministic natural alignment/padding and expose field offsets;
- final tuple size is rounded to maximum field alignment;
- overflow/unsupported/dynamic layouts are not zero-copy candidates.

Example:

```text
Tuple<u8,u32,bool>
size = 12
alignment = 4
offsets = [0,4,8]
```

This descriptor is a portable Omni contract; it does not claim to equal the in-memory layout of every C/Rust/Node/Python object.

## 7. `layout_id`

The descriptor carries a content-derived `layout_id` over canonical representation metadata.

Invariants:

```text
layout_id != type_id
layout_id != ObjectID
layout_id != ResourceID
layout_id != capability
layout_id != ownership
layout_id != lease
layout_id != pointer/address
```

`type_id` answers semantic type identity. `layout_id` answers representation compatibility under a particular layout schema. A future high-performance profile must check both relevant semantic and layout contracts plus runtime authority/lifetime conditions.

## 8. ECU / heterogeneous-runtime seam

Alpha.4 deliberately does **not** implement Node↔Python shared memory. It creates the general-language representation contract that such a profile may consume.

A future ECU data plane may negotiate:

```text
semantic type / schema
+ layout_id
+ bounded region metadata
+ ResourceRef/generation/lease
+ authority/policy
```

and then choose a transport independently:

1. trusted local shared/loaned buffer fast path;
2. validated binary copy fallback;
3. framed remote transport.

Raw process pointers are never part of the portable contract.

## 9. ABI status

The LLVM aggregate layout used internally for tuple/array native lowering is not a stable public cross-language ABI in alpha.4. The canonical layout descriptor is separately versioned precisely so portable data exchange does not accidentally depend on undocumented backend layout choices.

## 10. Relationship to alpha.5 View

`View<T>` is specified separately in `BORROWED_VIEWS_0_2.md`. It deliberately does not become canonical plain-data in `omni.layout-descriptor/1`: a borrow/view describes access to another value and therefore cannot be represented as a portable address-bearing payload or treated as authority.
