> Distribution status: WIP / NOT_RELEASED. Technical version labels describe independent contracts, not public release certification.

# Generic `Resource<T>`, `Borrow<T>` and `BorrowMut<T>` — candidate (OMNI-CORE-PRO-FOUNDATION-001, CP-01 / CP-05)

**Status:** `CANDIDATE`, not adopted, not certified. No new syntax, no new Wave/Wire/ONME instruction, no new capability: the change is how a type argument is
substituted. Tests: `tests/cp01_generic_resources.py`; mutants: `tests/mutants/generic_resources.json`.

## 1. Reproducer (measured on `120a24b`, before the change)

| Program | Result |
|---|---|
| `func hold<T>(x Resource<T>) Resource<T> { return move(x) }` called as `hold<Tok>(…)` for a nominal `Tok { h u64 }` | `E_RESOURCE_TYPE` |
| `struct Holder<T> { item Option<Resource<T>> }` used as `Holder<Tok>` | `E_RESOURCE_TYPE` |
| `trait Own { func give(v Resource<Self>) u64 }` with `impl Own for Tok` | `E_TRAIT_METHOD` (parameter 0 differs from the trait) |
| `Array<Resource<Tok>,2>` | accepted (CP-01 row 1.6) |

The cause is the representation of the type, not an ownership rule: `Resource<X>`, `Borrow<X>` and `BorrowMut<X>` keep `X` in the type's *name* (and its generic
arguments in `parts`), not in `parts`, so the monomorphizer (`substituteGenericType`) and the trait checker (`Self := implementing type`) never replaced a
parameter that stood in that position, and the name `T` or `Self` was looked up as if it were a declared struct.

## 2. Rule

When the name of a `Resource`, `Borrow` or `BorrowMut` is a generic parameter (or `Self` in a trait body), it is replaced, together with the generic arguments of
the argument, by the nominal record the argument stands for. The argument must be a nominal record (`E_GENERIC_CONSTRAINT` otherwise: `u32`, a tuple, `Text`).
After the substitution the type is exactly what the programmer could have written by hand for that instance, so **every existing rule applies unchanged**:

- the instance must be a declared `struct` with one `u64` handle, or a nominal wrapper of a `Resource<Buffer>` (`E_RESOURCE_TYPE` otherwise);
- exact-once consumption and move (`E_RESOURCE_UNCONSUMED`, `E_RESOURCE_MOVED`) are checked on the monomorphized body;
- `resource.seal`, `resource.unseal`, `resource.peek`, `resource.inner*` stay private to the module that declares the record (`E_RESOURCE_PRIVATE`): a generic
  function in another module has no more authority over `vec.Vec<u32>` than a non-generic one;
- distinct instances are distinct types (`Resource<Tok>` is not `Resource<Other>`, `E_TYPE`).

A generic parameter therefore never opens a resource, forges a handle from an integer, or turns a nominal type into another one.

## 3. What this does not do

It stores nothing. A *collection* of resources needs storage that owns values, which a byte `Buffer` cannot provide without turning handles into integers; that is
the next contract (`OWNED_SLOTS_CANDIDATE.md`). `hold<Buffer>` (the builtin `Resource<Buffer>` as an argument) is `E_TYPE`: `Buffer` is not a declared record.

## 4. CP obligations this supports

| CP row | How |
|---|---|
| 5.1 / 5.2 / 5.3 | nominal generic types and trait methods now carry resources by `T` and `Self` (previously only through a concrete name) |
| 1.7 | prerequisite of a generic collection of resources (not satisfied by this change alone) |
| 5.9 | instances of different resources are distinct types; fail on constraint |
