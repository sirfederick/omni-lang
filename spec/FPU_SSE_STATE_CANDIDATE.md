> Distribution status: WIP / NOT_RELEASED. Technical version labels describe independent contracts, not public release certification.

# x87 / SSE state in the freestanding x86-64 profile — candidate (OMNI-CORE-PRO-FOUNDATION-001, CP-10)

**Status:** `CANDIDATE`, not adopted, not certified. Profile: `baremetal-x86_64` only. One vCPU or many; eager state preservation only.
**Representation:** the new builtins share the Wave21/OMC21 fence (`HARDWARE_REPRESENTATION_FENCE_CANDIDATE.md`: any `cpu.` builtin and `cpu.control`).

## 1. Why this is a language/backend/ABI contract and not a kernel feature
Before this change a freestanding image had exactly one defined ISA mode, general-purpose registers only (the conformance suites compile with
`-mno-sse -mno-sse2 -mno-mmx -mno-80387`), and nothing in the compiler said so: a program with `f64` arithmetic was emitted anyway and its
SSE instructions faulted, or silently used whatever FP state the previous context left. SysV makes XMM registers caller-saved, so a cooperative
switch (a call) needs to carry only the *control* state (MXCSR rounding/exception masks, x87 control word); live XMM/x87 values are at risk
only across an **asynchronous** entry, where the interrupted code did not choose to be interrupted. The contract below names both.

## 2. ISA mode (`--target-isa`)
| Mode | Meaning |
|---|---|
| `gpr` (default) | general-purpose registers only; the profile today. `f32`/`f64` types, literals, arithmetic and conversions, and every FP-state primitive are rejected at emission with `E_TARGET_PROFILE` ("requires --target-isa sse2"). |
| `sse2` | floating point allowed. The environment must build the image with SSE2 enabled and enable SSE **before the image's first instruction that can use it** (`CR0.EM=0`, `CR0.MP=1`, `CR4.OSFXSR=1`, `CR4.OSXMMEXCPT=1`). Omni code cannot be the one that does it for its own image, because the compiler is free to use SSE anywhere in an `sse2` image; the conformance adapter (`tests/x64/boot64.S`, `--defsym SSE=1`) does it. Support is discovered with `cpu.cpuid(1, 3)`: bit 24 FXSR, 25 SSE, 26 SSE2. Without the enabling an FP instruction raises `#UD`. |
`--target-isa` is valid only with `--target-profile baremetal-x86_64`.

## 3. Primitives (capability `cpu.control`, `--target-isa sse2`; the evaluator cannot execute them: `E_TARGET_PROFILE`)
| Primitive | Type | Lowering | Rule |
|---|---|---|---|
| `cpu.fxsave(area u64)` | `u32` (0) | `fxsave64 (area)` | area is 512 bytes, 16-byte aligned, non-null |
| `cpu.fxrstor(area u64)` | `u32` (0) | `fxrstor64 (area)` | same area rule; the saved MXCSR (offset 24) is checked against the image's MXCSR_MASK (offset 28, `0` means `0xFFBF`) **before** the instruction |
| `cpu.read_mxcsr()` | `u32` | `stmxcsr` | |
| `cpu.write_mxcsr(v u32)` | `u32` (0) | `ldmxcsr` | `v` with a bit outside `0xFFBF` is rejected |
| `cpu.fninit()` | `u32` (0) | `fninit` | resets the x87 unit to its default control word |
A violated rule is trap code `12` (extended-state fault), never a hardware `#GP`. This extends the provider fault classes (1 bounds, 2 overflow,
3 div0, 4 cast range, 9 internal, 11 atomic access); a provider's `trap` receives 12 like any other code.

## 4. Asynchronous entry (`--exception-save-fpu`)
With `--exception-handler H --exception-resume --target-isa sse2`, `--exception-save-fpu` makes the resumable tail save the interrupted x87/SSE
state with `fxsave64` into 512 bytes it reserves on the interrupted stack (16-byte aligned) before calling `H`, and restore it with `fxrstor64`
before `iretq`. Without it the tail preserves general registers only and a handler that uses floating point corrupts the interrupted code.
The option requires the resumable tail and `sse2`.

## 5. A new context starts clean
A new context must not inherit the previous context's FP state. The clean image is ordinary Omni data (FCW `0x037F`, MXCSR `0x1F80`, everything
else zero) restored with `cpu.fxrstor`; no builtin hides it.

## 6. Non-claims
No XSAVE/AVX/AVX-512/AMX (no primitive exists and none is emitted); no lazy FPU switching (`#NM`); no claim for real hardware, only QEMU TCG;
the FP *values* computed are IEEE operations of the LLVM backend, not a new numeric model.

## 7. Acceptance
Positive: floats compile and run in an `sse2` image; two contexts with different MXCSR rounding modes and distinct x87/XMM contents each read
back their own after cooperative switches; a timer interrupt whose handler uses floating point leaves the interrupted computation exact with
`--exception-save-fpu` and demonstrably corrupts it without. Negative: floats and every primitive rejected in `gpr`; misaligned/null area and an
invalid restore image trap with code 12; `--exception-save-fpu` without its prerequisites, and `--target-isa` on the i386 profile, rejected.

## 8. Discovery of the CPU state (CP-10 row 10.6)
`cpu.cpuid_sub(leaf u32, subleaf u32, reg)` (capability `cpu.control`, `reg` a literal 0 eax / 1 ebx / 2 ecx / 3 edx) is `cpu.cpuid` with an explicit sub-leaf. `examples/storage/cpustate.omni` builds on it: the features an
image needs or must not use (FXSR, SSE2, XSAVE, AVX), the XSAVE area (the mask of supported components, the size for the components enabled now and for all of them, size and offset of each
component) and the MXCSR_MASK the CPU reports in the FXSAVE area. Nothing is assumed: an `--target-isa sse2` image asks `isa_covered()`; a CPU without XSAVE reports mask and sizes 0. Evidence: `tests/cp10_state.py`
on two CPUs under QEMU TCG (`qemu64`, no XSAVE; `max`, XSAVE and AVX: enabled area 512 + 64, AVX component 256 bytes at offset 576).

## 9. A privileged transition keeps the state (CP-10 row 10.5)
The x87/SSE control state a context set before a CPL3 -> CPL0 -> CPL3 transition is the one it finds afterwards when the resumable tail saves it (`--exception-save-fpu`); without the option the handler's own
rounding mode leaks into the interrupted context (the contrast is part of the test). A new context starts from a clean image restored by its creator (section 5). Evidence: `PrivilegedTransitionTests`.

## 10. The frame that is resumed, stacks and their limits (CP-12 rows 12.4-12.6)
* **Validated frame.** The resumable tail never trusts the frame a handler returns: after the handler returns 0 it compares the frame it is about to `iretq` with what the hardware pushed (CS and RFLAGS are kept below the saved registers). Report bits: 1 CS changed, 2 RIP not
  canonical, 4 RFLAGS without its reserved bit, with NT, or another IOPL, 8 RSP not canonical (entry from CPL0) or not in the lower half (entry from CPL3). A failing frame is not resumed: the handler is called once
  more with vector 256 and the report in the error-code slot, then the CPU stops. A pointer kept from an earlier entry cannot make the next resume unsound. Evidence: `tests/cp12_frames.py` (both tails, kernel and user frames).
* **Guard page.** A thread stack ends at a not-present 4 KiB page of a 2 MiB mapping split by the program; the fault is taken on a separate stack (IST 1 of a TSS the program builds in Omni), recognised by CR2 and recovered by
  pointing the validated frame at the thread trampoline on a fresh stack; with the guard mapped the same overflow is silent. Evidence: `tests/cp12_stacks.py::GuardPageTests`.
* **Sentinels.** A routine that loads a distinct pattern into every general register, every XMM register and the FS base runs on a painted thread stack under timer interrupts: with `--exception-save-fpu` nothing changes and the
  stack the thread did not use keeps its paint; without it only the XMM sentinels change. Evidence: `tests/cp12_stacks.py::SentinelTests`. Nesting: one level (the handler runs with interrupts masked by the gate); a nested
  exception inside a handler is not supported and ends in the terminal path.

