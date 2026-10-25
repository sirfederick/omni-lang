> Distribution status: WIP / NOT_RELEASED. Technical version labels describe independent contracts, not public release certification.

# Omni Borrowed Views — 0.2 alpha.5

**Language:** Omni Language 0.2.0-alpha.6  
**Status:** normative for implemented `View<T>` semantics.  
**Representation:** Wave10 / logical OMC10.

## 1. Purpose

`View<T>` is Omni's first general read-only contiguous borrow abstraction. It allows code to inspect a bounded subrange of a fixed array without changing array value semantics or exposing a portable raw pointer. It is deliberately smaller than a general slice/borrow system.

```text
Array<T,N> immutable binding
        │
        └── view(...) ──► View<T>
                           │
                           ├── view.len
                           ├── view.get
                           └── view.sub ──► View<T>
```

## 2. Construction

Alpha.5 admits:

```omni
let a Array<u32,4> = array(10u32,20u32,30u32,40u32)
let v View<u32> = view(a)
```

`view(x)` requires:

1. exactly one argument;
2. the argument is a named variable/parameter, not a temporary expression;
3. the resolved source type is `Array<T,N>`;
4. the source binding is immutable.

The immutable-source rule avoids mutable aliasing before Omni has a generalized exclusive-borrow model.

## 3. Operations

```text
view(array)                 -> View<T>
view.len(view)              -> u32
view.get(view,index:u32)    -> T
view.sub(view,off:u32,n:u32)-> View<T>
```

`view.get` requires `index < length`. `view.sub` requires both `off <= length` and `n <= length - off`. The subtraction form is normative so validation does not rely on overflow-prone `off + n` arithmetic. Violations are deterministic `E_BOUNDS` in evaluator and native execution.

Zero-length views and `view.sub(v, view.len(v), 0)` are valid.

## 4. Lifetime and non-escape contract

In alpha.5 a View may exist only as:

- an immutable local binding;
- a function parameter;
- a temporary operand used within the current call/expression flow;
- a subview of another admitted View.

The following are rejected:

- returning `View<T>` from a function (`E_VIEW_ESCAPE`);
- `var` View bindings (`E_VIEW_MUTABLE`);
- View fields in structs;
- View payloads in enums;
- View nested in `Result`, `Option`, `Tuple`, or `Array`;
- `View<View<T>>`;
- View of linear/resource/async elements under the current restricted memory model.

This is a conservative lexical/function-bound lifetime contract, not the final generalized borrow checker.


## 4.1 Stable diagnostics

- `E_VIEW_SOURCE`: source is temporary, mutable, or not an admitted `Array<T,N>` binding.
- `E_VIEW_MUTABLE`: a View is declared with mutable storage.
- `E_VIEW_ESCAPE`: a View is used as a function return type/escape surface.
- `E_BOUNDS`: `view.get` or `view.sub` exceeds the current bounded region.

## 5. Read-only semantics and backend freedom

`View<T>` exposes no mutation operation. The source Array is immutable for admitted construction. Therefore the language guarantees observations of the logical source value and subrange but does not require any particular physical implementation.

A backend may:

- point at existing immutable storage;
- materialize a private backing copy;
- choose another representation preserving the same checked observations.

Consequently alpha.5 makes **no zero-copy guarantee**.

## 6. Identity, layout and authority

`View<T>` participates in semantic type identity: `View<u8>` and `View<u32>` are distinct. The type descriptor declares `borrowed-readonly` and `portable_address=false`.

`View<T>` is not canonical plain-data in `omni.layout-descriptor/1` and never claims `zero_copy_candidate=true`.

```text
View type_id     != ObjectID
View type_id     != ResourceID
View             != Capability
View             != Authority
View             != raw pointer/address
```

A later ABI/ECU profile may map a validated View contract to runtime-native mechanisms, but those adapters do not redefine Core semantics.

## 7. Representation fencing

View syntax/operations require Wave10 and logical OMC10. Wave9/OMC9 readers reject View semantics with `E_VERSION`; changing only version metadata cannot bypass this invariant.

OMC10 uses an extended binary header:

```text
bytes 0..3  = "OMCX"
bytes 4..7  = little-endian u32 version = 10
```

This avoids ambiguity with the legacy fixed four-byte `OMC1`..`OMC9` magics. After the extended header, OMC10 retains the compatible alpha.4 body structure and encodes View through the type-string/call representation.

## 8. Deferred semantics

Alpha.5 intentionally does **not** define:

- mutable `Slice<T>`;
- exclusive/mutable borrows;
- View over `Bytes` or `Resource<Buffer>`;
- storing Views in heap/containers;
- async suspension carrying Views;
- raw pointer extraction;
- public stable C ABI layout for View;
- transport leases/generations/ResourceRef;
- Node/Python view objects.

Those require later memory/FFI/concurrency/profile gates.

## Alpha.6 canonicalization note

View semantics were introduced at the Wave10/OMC10 fence and remain valid. Under the current 0.2.0-alpha.6 writer, admitted View programs canonicalize to Wave11/OMC11; the minimum historical version that may claim View semantics remains 10.
