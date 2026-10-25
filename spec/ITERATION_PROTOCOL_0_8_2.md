> Distribution status: WIP / NOT_RELEASED. Technical version labels describe independent contracts, not public release certification.

# Omni static iteration protocol — 0.8.2

**Status:** `FROZEN_FOR_IMPLEMENTATION` for the A82 static-iteration slice.

## Scope

This contract makes the already supported `for x in sequence { ... }` surface an
explicitly resolved static protocol. It preserves the released A81 observable
semantics for `Array<T,N>`, `View<T>`, and `Range<u32>`; it does not add a hidden
iterator object, dynamic dispatch, allocation, ambient authority, or an ABI.

The parser surface and precedence are unchanged:

```omni
for item in sequence {
    // item is immutable and scoped to this body
}
```

## Static resolution

The checker evaluates `sequence` exactly once, determines its concrete checked
type, and records exactly one closed protocol plan:

| Concrete type | Static plan | Element type |
| --- | --- | --- |
| `Array<T,N>` | `array-elements` | `T` |
| `View<T>` | `view-elements` | `T` |
| `Range<u32>` | `range-u32-ascending` | `u32` |

No fallback by function name, structural field shape, trait-object, reflection or
runtime type test is permitted. A type with no listed plan fails `E_ITERABLE`.
The plan is checker metadata, not a source-level value and not an authority token.
It is reconstructed by semantic validation after every Particle, Wave, Wire or
ONME decode.

Trait-associated methods and user-defined `Iterator`/`IntoIterator` implementations
remain unavailable in this 0.8.2 slice. `TRAITS_0_8_2.md` and
`STATIC_METHODS_0_8_2.md` deliberately admit nominal marker constraints and static
receiver declarations without silently treating an arbitrary trait implementation
as executable iteration. A future version may add such a surface only with a
separate frozen ownership, exhaustion and representation contract.

## Dynamic and memory semantics

`sequence` is evaluated left-to-right once before the first iteration. Array and
View visit elements in ascending index order; Range preserves its released
ascending, step-one, inclusive/exclusive and `u32::MAX` termination rules. An
empty sequence executes zero iterations. `break` and `continue` retain their
existing structured-loop meanings.

The bound item is an immutable Copy value for the duration of its body iteration.
The protocol does not move, borrow, retain, release or clean up an outer Resource;
the existing checker rejection of a consuming iterable expression or repeated-body
outer-resource transition remains mandatory. There is no iterator cleanup action
because all three admitted plans are value/view traversal plans with no iterator
resource.

## Evaluator, native and representation parity

The evaluator and native backend must execute the checker-selected plan, rather
than choosing an unvalidated runtime fallback. For every admitted plan their exit
status and stdout must match. An unresolved or type-inconsistent internal plan is
an invariant failure, never a fallback to a different protocol.

`for-each` is already represented by Wave11+/OMC11+. The closed plan is derived
from the semantically checked iterable type, so this slice changes no executable
representation and does not authorize Wave18/OMC18. Historical readers retain
their existing `for-each` fences; malformed or semantically unsupported decoded
input is rejected during revalidation.

## Required proof and exclusions

Conformance requires Array, View and Range positive loops; zero-iteration,
inclusive-maximum, break and continue cases; non-iterable rejection; Wave/Wire/ONME
round trips; and evaluator/native differentials. No user-defined iterator,
trait-object, dynamic iterator dispatch, iterator value escape, closure capture of
iterator state, Resource/Borrow/BorrowMut iteration, implicit ownership transfer or
new representation writer belongs to this slice.
