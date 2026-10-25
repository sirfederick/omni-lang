> Distribution status: WIP / NOT_RELEASED. Technical version labels describe independent contracts, not public release certification.

# Per-thread and per-CPU blocks — candidate (OMNI-CORE-PRO-FOUNDATION-001, CP-11, substrate)

**Status:** `CANDIDATE`, not adopted, not certified. Profile: `baremetal-x86_64`. This document is the checked FS/GS block substrate (raw offsets); the typed per-thread variables built on it are in `THREAD_LOCAL_CANDIDATE.md`, which
is where the CP-11 acceptance is specified and tested. Per-CPU blocks (`pcpu.*`) remain this substrate.
**Representation:** `tls.*`, `pcpu.*`, `memory.tls` and `memory.pcpu` share the Wave21/OMC21 fence (`HARDWARE_REPRESENTATION_FENCE_CANDIDATE.md`).

## 1. Surface
| Builtin | Type | Segment | Capability |
|---|---|---|---|
| `tls.load32(off u64)` / `tls.load64(off u64)` | `u32` / `u64` | `FS` | `memory.tls` |
| `tls.store32(off u64, v u32)` / `tls.store64(off u64, v u64)` | `u32` (0) | `FS` | `memory.tls` |
| `pcpu.load32` / `load64` / `store32` / `store64` (same shapes) | | `GS` | `memory.pcpu` |
The two capabilities are distinct from each other and from `memory.raw`: authority over a thread's block is not authority over arbitrary
addresses, and a number is not a mapping. The base registers are installed with the existing `cpu.wrmsr` (`IA32_FS_BASE` `0xC0000100`,
`IA32_GS_BASE` `0xC0000101`, per CPU); no new privileged builtin was needed.

## 2. Block contract
A block starts with a 16-byte header: `+0` magic (`"OMNITLS1"` for `tls.*`, `"OMNIPCP1"` for `pcpu.*`, as little-endian `u64`), `+8` size in bytes.
Data starts at `+16`. Every access is checked **before** it happens: the magic must match, the offset must be `>= 16`, `offset + width` must not wrap and
must not exceed the size. Any violation is trap code `13` (block fault), never an access. An unset base (`0`) reads the real-mode vector table, which
is not the magic, so it faults rather than touching low memory; a block whose magic was cleared (teardown) faults; a per-CPU block used through
`tls.*` (or the reverse) faults on the magic. The evaluator cannot execute these builtins (`E_TARGET_PROFILE`); hosted compilation and the i386
profile refuse them. Fault codes of the provider's `trap`: 1 bounds, 2 overflow, 3 div0, 4 cast range, 9 internal, 11 atomic access, 12 extended
state, 13 block.

## 3. What a context switch must do
The base register is part of the context. The conformance scheduler installs the next thread's `FS` base before switching to it; Core provides the
accessors and the checks, not the policy. A new thread's block is initialised by copying a template (header included) over the block;
the conformance program poisons the memory first so that the test reads the template and not leftovers.

## 4. Acceptance (`tests/language_0_8_3_alpha8.py::A83X64TlsTests`)
- two Omni threads use the same offsets and read their own values 1000/1000 times across switches; both start from the template (value 7 and a 64-bit
  pattern) although the block memory was poisoned; final contents are in the right blocks;
- two vCPUs each install their own `GS` block and count 200000 with a plain load+store: both exact; the control (both CPUs on one block) loses updates;
- faults: unset base, offset inside the header, past the size, wrapping offset, torn-down block, block of the other kind: all trap 13; the in-bounds
  edge succeeds; options and capabilities are validated before any artifact.

## 5. Not provided (the typed per-thread surface is specified in `THREAD_LOCAL_CANDIDATE.md`)
- No typed per-CPU variables and no ELF `PT_TLS` template/relocation model, no dynamic TLS, no destructors, no borrow lifetime tied to a thread, no migration guard for per-CPU data
  (a context that can migrate between CPUs must not hold a per-CPU block across the migration; Core only detects it: `pin.omni`, NO_MIGRATION_CANDIDATE.md).
- QEMU TCG only, ring 0 only (`wrmsr` of the base).
