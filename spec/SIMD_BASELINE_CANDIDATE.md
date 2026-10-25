> Distribution status: WIP / NOT_RELEASED. Technical version labels describe independent contracts, not public release certification.

# 128-bit SIMD baseline — CP-10 candidate

**Status:** `CANDIDATE` (MN-04, owner amendment of 2026-10-22: basic vector operations **with comparison, mask and select**; advanced shuffles are DEFER_1_4). Not adopted, not certified.
**Representation:** the `simd.*` intrinsics share the Wave21/OMC21 fence of the machine primitives (`HARDWARE_REPRESENTATION_FENCE_CANDIDATE.md`); no new type kind, no new opcode.
**Library:** `examples/storage/simd.omni`. **Tests:** `tests/cp10_simd.py`.

## 1. A vector is a record of lanes

No new type exists. A **vector** is a record of 2, 4, 8 or 16 fields of one integer type (`u8..u64`, `i8..i64`) or float type (`f32`, `f64`) that together measure 128 bits; a **mask** is a record of the same number of
`bool` lanes. `simd.omni` names the ten vectors (`U8x16 U16x8 U32x4 U64x2 I8x16 I16x8 I32x4 I64x2 F32x4 F64x2`, lanes `l0 l1 ...`) and the four masks (`M8x16 M16x8 M32x4 M64x2`); a program may define its own
record of the right shape and use it. A lane is a field, so **extract and insert are field read and record construction**; every representation, the layout rules, the ownership checks and the identity already carry the type.
`E_SIMD` says why a record is not a vector (lane count, mixed lane types, not 128 bits, non-numeric lanes) or why a mask and a vector were confused.

## 2. The intrinsics (type arguments name the records)

| Intrinsic | Type arguments | Result |
|---|---|---|
| `simd.splat<V>(x)` | vector | every lane `x` |
| `simd.add / sub / mul<V>(a, b)` | vector | per lane; integers **wrap**, floats are IEEE (the image's MXCSR rounding applies) |
| `simd.div<V>(a, b)` | float vector | per lane |
| `simd.and / or / xor<V>(a, b)` | integer vector | bitwise per lane |
| `simd.eq / ne / lt / le / gt / ge<V, M>(a, b)` | vector, mask of the same lane count | a **mask**; unsigned lanes compare unsigned, `iN` signed, floats ordered (`ne` is true for NaN) |
| `simd.select<V, M>(m, a, b)` | vector, mask | lane `a` where the mask lane is true, else `b` |
| `simd.mask_and / mask_or / mask_xor<M>(a, b)`, `simd.mask_not<M>(a)` | mask | per lane |
| `simd.any<M>(m)`, `simd.all<M>(m)`, `simd.bitmask<M>(m)` | mask | `bool`, `bool`, `u32` with bit `i` = lane `i` |
| `simd.reduce_add<V>(v)` | vector | the lane type; integers wrap, floats are added in lane order 0..n-1 |
| `simd.load / load_aligned<V>(addr u64)`, `simd.store / store_aligned<V>(addr, v)` | vector | memory.raw; lane `i` at `addr + i * width`, little endian, volatile; the `_aligned` forms and address 0 trap (14) unless the address is 16-aligned |

A mask is never an integer vector: a comparison produces one, only `select`, the mask operations and `any/all/bitmask` consume it. The operations are pure (no capability) except loads and stores (`memory.raw`).

## 3. Targets

Evaluator: lane by lane over the same arithmetic as the scalar operations (loads and stores over its sparse memory, `E_LAYOUT` for a null or misaligned address). Hosted native: LLVM vectors. Freestanding `baremetal-x86_64`:
LLVM vectors, SSE2 instructions, **`--target-isa sse2` required** (`E_TARGET_PROFILE` for a general-register image, as for floating point); the i386 boot profile refuses them. Floating-point vector arithmetic uses the same constrained
intrinsics as the scalar code in an sse2 image. No AVX; the CPU is asked with `cpustate.omni` (`has_avx`) and AVX use stays rejected.
Stack alignment: `omni_boot_entry` must be entered as if called (`TARGET_BAREMETAL_PROFILE_CANDIDATE.md`); otherwise the first spill of a vector faults.

## 4. Acceptance

A Python oracle computes every lane of every operation for the ten vector types over edge, random and (floats) exactly representable values; the generated program (40 cases, about 25 checks each) agrees in the evaluator, as a hosted
native binary and in a freestanding sse2 image under QEMU TCG, where the operands go through memory so that real SSE2 instructions run. NaN lanes, wrapping, little-endian lane order, unaligned loads, the aligned trap, every wrong shape
and capability, the profile fences and the representation fence are tested.

## 5. Not in 1.3

Shuffles and permutations, vectors wider than 128 bits, lane counts as parameters (const generics), AVX and wider ISAs, per-lane masks on memory operations, an autovectorization guarantee.
