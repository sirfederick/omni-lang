> Distribution status: WIP / NOT_RELEASED. Technical version labels describe independent contracts, not public release certification.

# Integer bit intrinsics — CP-07 candidate

**Status:** `CANDIDATE` (OMNI-CORE-PRO-FOUNDATION-001, OM-012). Not adopted, not certified.
**Representation:** Wave21 / OMC21 (shared with `BORROW_RETURN_REGIONS_CANDIDATE.md`), emitted only for programs that call a `bit.*` intrinsic.

## 1. Problem

Core 1.2.1.0 has checked, wrapping (`+% -% *%`) and saturating (`+| -| *|`) arithmetic but no bit-level
operation: no and/or/xor/not, no shifts, no masks. Address arithmetic, register fields and flags cannot be
expressed without a host call.

## 2. Contract

Declarative intrinsics, no new keyword, operator token or lexer change (a `>>` token would collide with
nested generic closers such as `Option<Resource<Buffer>>`). Names are `bit.and`, `bit.or`, `bit.xor`,
`bit.not`, `bit.shl`, `bit.shr`. They are pure (no effect, no capability) and defined for every integer
type `u8/u16/u32/u64/i8/i16/i32/i64`; never for `bool`, `char`, floats or anything else (`E_TYPE`).

| Intrinsic | Signature | Semantics |
|---|---|---|
| `bit.and/or/xor(a T, b T)` | `T` | bitwise on the two's-complement representation of width(T) |
| `bit.not(a T)` | `T` | bitwise complement within width(T) |
| `bit.shl(a T, n u32)` | `T` | logical left shift; bits shifted out are discarded (no overflow trap) |
| `bit.shr(a T, n u32)` | `T` | right shift; arithmetic for signed `T`, logical for unsigned `T` |

Operand types must match exactly (no implicit widening; `E_TYPE`). A shift count `n >= width(T)` is
`E_BOUNDS`: rejected at check time when `n` is a literal, a runtime trap otherwise. Evaluator and native
code implement the same semantics. Other `bit.*` names are not intrinsics and resolve as ordinary calls.

## 3. Out of scope

Operator syntax, rotates, population count, `u128`, endian conversion and byte-view reinterpretation, and
address/MMIO domain types (CP-07/CP-08 continue separately).

## 4. Representation fence

A program that calls a `bit.*` intrinsic is encoded only as Wave21 / OMC21; Wave/OMC ≤ 20 readers reject
it with `E_VERSION`. Programs that do not use the feature keep their previous version.

## 5. Acceptance

`tests/language_0_8_3_alpha8.py::A83BitIntrinsicTests`: values per operation and type with evaluator/native
parity, signed arithmetic shift, 64-bit values above 4 GiB, literal and runtime out-of-range counts,
type/arity errors, and the Wave/OMC fence.
