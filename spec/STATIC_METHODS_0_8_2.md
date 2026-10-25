> Distribution status: WIP / NOT_RELEASED. Technical version labels describe independent contracts, not public release certification.

# Omni static methods — 0.8.2

**Status:** `FROZEN_FOR_IMPLEMENTATION` for the A82 static-method slice.

## Surface

A function may mark its first parameter with one receiver mode:

```omni
func add(read self u32, rhs u32) u32 { return self + rhs }
func main() u32 { return (40u32)::add(2u32) }
```

The only call spelling in this slice is the existing UFCS form
`receiver::method(arguments)`. It resolves exactly as the static function call
`method(receiver, arguments)` in the caller's module/import scope. A receiver
mode is a checked declaration property, not a method value, trait object,
virtual table, dynamic dispatch slot, or runtime representation.

`read` is the only executable receiver mode introduced by this slice. It
requires a non-Resource, non-Borrow, non-BorrowMut, non-View, non-Future,
non-Stream, non-Result Copy value. `mutate` and `consume` are reserved words;
they are rejected in declarations in 0.8.2 until their ownership proofs are
frozen by a later slice. There is no implicit `move`, `borrow`, `borrow_mut`,
or authority grant.

## Static and dynamic semantics

The receiver must be supplied only by UFCS and becomes argument zero. A direct
call to the same function remains valid and has identical argument order,
type checking, capability requirements, evaluation order, evaluator result and
native result. A function with a receiver mode may not be generic only through
the receiver; normal monomorphization remains the authority for all type
parameters.

The compiler rejects: a receiver annotation on any non-first parameter;
duplicate/missing receiver names; `read` on a non-Copy/authority-bearing type;
`mutate`/`consume`; and any attempt to encode a receiver mode in Wave/Wire as a
runtime value. Historical UFCS calls to a function without a receiver annotation
remain valid: the annotation strengthens the declared contract for new code but
does not reinterpret existing static calls. Diagnostics are `E_METHOD_RECEIVER`.

## Representation and compatibility

Receiver mode is a function-signature declaration property and is encoded in
Wave17/OMC17 function parameters. It does not require a Wave18/OMC18 bump
because Wave17 is not released and its parameter declaration records are
extended before its first release. The physical OMCX u32(17) header is unchanged.
Wave1–16 remain readable for their own formats and yield parameters with no
receiver mode. A Wave17/OMC17 payload with an unknown receiver mode fails closed.
ONME2 carries the Wave payload unchanged.

## Deferred

Trait-associated methods, `mutate`, `consume`, automatic receiver coercions,
dynamic dispatch, method values, receiver capture by closures, and custom
iterator traits are deferred. The closed built-in static iteration plans are
specified separately in `ITERATION_PROTOCOL_0_8_2.md`; that contract does not
turn arbitrary marker traits into runtime-dispatched iterators.

Core 1.3 derives the `read` Copy restriction recursively through concrete record
fields and sum payloads. A pending Result/Option/enum, or a record containing
Resource/pending obligations, cannot be a read receiver (E_METHOD_RECEIVER),
even if its body explicitly consumes the value. Plain Copy records retain UFCS
and direct-call semantics. This repairs declaration validation; it introduces
no implicit transfer, receiver mode or runtime representation.
