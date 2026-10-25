> Distribution status: WIP / NOT_RELEASED. Technical version labels describe independent contracts, not public release certification.

# Omni Buffer Typed Access — CANDIDATE (CORE-INWARD-007 / R1)

**Status:** local candidate, **not** normative Core and **not** an official release. It extends
`MEMORY_LIFECYCLE_0_8_3.md` §5 (allocation and bounds) without changing it. Base: Omni 1.2.1.0
((design baseline; not distribution identity)). The candidate still reports `1.2.1.0`; its identity is the
compiler/runtime hash in the candidate manifest.

## 1. Operations

| Operation | Operands | Result | Capability |
|---|---|---|---|
| `buffer.read_u8` | `Borrow<Buffer>` or `BorrowMut<Buffer>`, `u32` offset | `Result<u32,u32>` (0..255) | `memory.read` |
| `buffer.read_u32le` | same | `Result<u32,u32>` | `memory.read` |
| `buffer.read_u64le` | same | `Result<u64,u32>` | `memory.read` |
| `buffer.write_u32le` | `BorrowMut<Buffer>`, `u32` offset, `u32` value | `Result<u32,u32>` | `memory.write` |
| `buffer.write_u64le` | `BorrowMut<Buffer>`, `u32` offset, `u64` value | `Result<u32,u32>` | `memory.write` |

`buffer.write_u8` (existing) is unchanged.

## 2. Semantics
* **Byte order:** little endian; the byte at `offset` is the least significant. No alignment requirement;
  an access at any offset is defined.
* **Bounds:** width `w` is 1, 4 or 8. The access is valid iff `offset <= len && w <= len - offset` (no
  `offset + w` arithmetic, no wrap). Otherwise the result is `Err(1)`.
* **Errors:** `Err(1)` out of bounds. A write that fails writes **no** byte (no partial write). A stale or
  forged handle is a runtime fault (`E_RESOURCE_HANDLE` in the evaluator; `buffer_get` fault in native), not a
  typed result; handles are not forgeable from source and use-after-`release`/`freeze`/`move` is rejected
  statically with `E_RESOURCE_MOVED`.
* **Success payload:** reads return the value; writes return `Ok(1)` (same as `write_u8`).
* **Types are strict:** the offset is `u32`, the value type is exactly `u32` / `u64`; no implicit widening
  (`E_TYPE`).
* **Authority:** capabilities as in the table; borrowing grants no capability. A read through `Borrow`
  does not mint write authority; writes require `BorrowMut` (a shared borrow is `E_TYPE`).
* **Loans:** operand evaluation is left to right and participates in the loan graph exactly like
  `write_u8`/`len` (an argument expression that overlaps a live exclusive loan is `E_BORROW_CONFLICT`).
* **Parity:** the evaluator and the native backend implement the same function; the differential gate
  `core-changes/CORE-INWARD-007/tests*` compares both against a fixed expected output.
* **Cost:** one runtime call per operation (one builtin tick), independent of width.

## 3. Representations
Source, Wave/`inspect`, `.owire` pack/unpack, `.onme`, OSNMF/graph and `emit-llvm` carry the operations by
builtin name. Consumers of the 1.2.1.0 admitted SDK reject them fail-closed (`E_IMPORT: alias no importado:
buffer`); they are never reinterpreted. The legacy fences (`E_VERSION` for `buffer.*` in pre-OMC5 formats) apply
by prefix.

## 4. Non-goals
No `View`/slice of a Buffer, no zero-copy, no raw pointer or integer→address conversion, no host policy change,
no new ownership rule. Backends other than hosted `linux-x86_64-gnu` are not specified here.

## 5. Companion implementation note (not semantics)
Native lowering allocates fixed-size temporaries once per call frame (entry block) so loops do not grow the
stack (G14). Hoisting `view.make` slots is safe because views are `let`-only (`E_VIEW_MUTABLE`)
and cannot outlive the iteration that created them.
