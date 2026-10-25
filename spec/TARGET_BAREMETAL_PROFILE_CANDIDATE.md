> Distribution status: WIP / NOT_RELEASED. Technical version labels describe independent contracts, not public release certification.

# Bare-metal target profile — candidate (application subsystem-OMNI-ONLY-BAREMETAL-001)

**Status:** `LOCAL_CANDIDATE` — not part of a certified release. It does not change Particle, Wave, Wire, ONME or
any hosted behavior; every addition is reachable only through new capability names and a new `emit-llvm` option.
Generalizable requirement (not application subsystem-specific): *write a freestanding program, its runtime services and its boot
entry in Omni, with one compiler-emitted machine operation per privileged primitive*.

## 1. Capabilities (new, critical risk, not delegable, not serializable)

| Capability | Meaning |
|---|---|
| `memory.raw` | load/store of target memory by numeric address |
| `port.io` | x86 port input/output |
| `cpu.control` | privileged CPU control operations |

A function that calls a primitive must declare the capability (`E_CAPABILITY` otherwise), and callers inherit the
requirement through the existing transitive capability analysis. No primitive is reachable without it.

## 2. Primitives (`namespace.name`, all return `u32` unless stated)

| Primitive | Type | Semantics |
|---|---|---|
| `raw.load8(a u64)` / `raw.load32` / `raw.load64` | `u32` / `u32` / `u64` | volatile, unaligned-tolerant, little endian |
| `raw.store8(a u64, v u32)` / `store32` / `store64(a, v u64)` | `u32` (=0) | volatile; `store8` with `v>255` faults `E_CAST_RANGE` |
| `port.in8(p u32)` / `port.in16` / `port.in32` | `u32` | `inb` / `inw` / `inl`; 8- and 16-bit results are zero-extended to `u32` |
| `port.out8(p u32, v u32)` / `port.out16` / `port.out32` | `u32` (=0) | `outb` / `outw` / `outl`; `v` truncated to the port width |
| `cpu.halt()` | `u32` | `cli; hlt` loop; never returns |
| `cpu.set_stack(a u32)`, `cpu.lgdt(a u32)` | `u32` | `movl a,%esp`, `lgdt (a)` |
| `cpu.write_cr(n, v u32)`, `cpu.read_cr(n)` | `u32` | `n` is a literal 0, 3 or 4 (`E_TARGET_PROFILE` otherwise) |
| `cpu.wrmsr(msr, lo, hi u32)` | `u32` | `wrmsr` |
| `cpu.far_jump(sel, addr)` | `u32` | both literals; `ljmpl`; never returns |

**Port I/O width contract (`port.in16`, `port.in32`, `port.out16`).** Each operation is one x86 port instruction of exactly that
width (`inw`, `inl`, `outw`), volatile and with a memory clobber, so the compiler can neither reorder it with another port
operation or memory access nor split it. A wider access is never composed from narrower ones (`in8` x 4 for `in32`, `out8` x 2 for
`out16`): a device may give a wide access a different, or an atomic, meaning than the bytes it covers. The port is the low 16 bits
of `p` (`DX` is 16 bits). **`out16` writes the low 16 bits of `v`; bits 16..31 are discarded and never rejected**, exactly as
`out8` writes the low 8 bits and `out32` all 32: the value operand is a `u32` for every width and is truncated to the port width.
Type rules are those of `port.in8`/`port.out8`: capability `port.io` (`E_CAPABILITY`), arity (`E_ARITY`), `u32` operands (`E_TYPE`);
hosted `emit-llvm` / `build` refuses them (`E_TARGET_PROFILE`). They are available in both bare-metal profiles (the encodings are
the same in 32-bit protected mode). Wave/OMC: the Wave21/OMC21 fence is unchanged (every `port.` name already selects it).

Evaluator semantics: raw memory is a sparse zero-filled byte map; `port.in8` yields 255, `port.in16` 65535 and `port.in32`
4294967295 (an idle bus reads all ones at the access width); port writes are recorded (`out16` records the low 16 bits of the value);
`cpu.halt` stops with `E_TARGET_HALT` reporting the bytes written to port `0x3F8` and the last `0xF4` value; any other
`cpu.*` fails with `E_TARGET_PROFILE`. Hosted `emit-llvm` / `build` of a program that uses a primitive fails with
`E_TARGET_PROFILE` (no hosted lowering exists).

## 3. Target profiles (`omni emit-llvm FILE --target-profile P --service-module M [...]`)

| Profile | Triple | Provider | Notes |
|---|---|---|---|
| `baremetal-x86_64` | `x86_64-unknown-none-elf` | yes | services bound to `M` |
| `baremetal-i386-boot` | `i386-unknown-none-elf` | no | PVH note, internal functions, entry stub |

Common effects:

1. no hosted runtime symbol is called: no `omni_runtime_begin/configure/end`, no `omni_tooling_visit`, no hosted `main`;
2. checked arithmetic (`add sub mul div rem sat_*` over all integer widths) is generated inline from the LLVM overflow
   intrinsics with the same fault classes (`E_OVERFLOW`, `E_DIVZERO`); unsigned-to-unsigned numeric conversion is inline
   (widening lossless, narrowing range checked, `E_CAST_RANGE`);
3. functions of module `M` are *service code*: no `tick`/`enter`/`leave` instrumentation; all other functions keep it;
4. the entry symbol `omni_boot_entry` (`omni_boot_entry32` for the i386 profile) calls `M.begin()` (provider profile),
   then the program's `main`; if `main` returns, the entry faults with class 9;
5. faults call `M.trap(code u32) u32` (provider profile) or halt (boot profile). Codes: 1 bounds, 2 overflow, 3 div0,
   4 cast range, 9 internal.

### Provider contract (profile `baremetal-x86_64`)
`M` must define, with exactly these Omni signatures (`E_SERVICE_BINDING` otherwise):
`begin() u32` (called by the entry once, before `main`, exactly as the hosted wrapper calls `omni_runtime_begin`),
`tick() u32`, `enter() u32`, `leave() u32`, `trap(u32) u32`, `buf_alloc(u32) u32`, `buf_len(u64) u32`,
`buf_release(u64) u32`, `buf_read8/32/64(u64,u32) u32`, `buf_write8(u64,u32,u32) u32`, `buf_write32(u64,u32,u32) u32`,
`buf_write64(u64,u32,u64) u32`, `out32() u32`, `out64() u64`, `print_u32(u32) u32`, `print_u64(u64) u32`,
`cast_int(u64,u32,u32,u32,u32) u64`. The compiler generates adapters that preserve the hosted service ABI
(status code + out value) so component code lowering is unchanged.

### Boot profile (`baremetal-i386-boot`)
Options `--entry-address N` (value recorded in the PVH note, the linker script places the entry there) and
`--entry-stack N` (entry is a naked two-instruction stub: `movl $N,%esp; jmp main`, placed first in the single entry
section so no relocation remains). All functions go to the entry section.
Option `--entry-handoff-store N` (1..2^32-1): the stub additionally executes `movl %ebx, N` before the jump, so the
boot-protocol register that carries the loader handoff (PVH: physical address of `hvm_start_info`) is preserved at a
fixed physical address before any compiled prologue can clobber it. Without it the handoff register is unobservable
from Omni code.

## 4. Non-goals
No interrupts/exceptions, no paging abstraction, no SMP, no ARM, no stable ABI promise, no hosted-runtime changes, no
claim that the compiler is self-hosted (the compiler remains the C++ bootstrap), no certification.

## 5. Gates
Positive and negative checker/evaluator tests per primitive; hosted refusal; profile binding errors; IR closure (every
called symbol is defined); differential: hosted IR is byte-identical to the 007 candidate; inline arithmetic parity
against the hosted runtime; accumulated Core matrix.

## Control registers in the 64-bit profile (PVH-VIRTUAL-PAGING-4K-001)

`cpu.read_cr(n)` / `cpu.write_cr(n, v)` (n literal 0, 3 or 4, operands `u32`) are lowered per profile:

- `baremetal-i386-boot`: `movl %crN, r32` / `movl r32, %crN` (unchanged).
- `baremetal-x86_64`: `movq %crN, r64` / `movq r64, %crN`. The `u32` value is zero-extended on write and is the
  low 32 bits of the register on read. Earlier candidates emitted the 32-bit form in both profiles, which the
  x86-64 assembler rejects ("instruction requires: Not 64-bit mode"), so the 64-bit kernel could not read or reload CR3.

Reloading CR3 with its own value is the invalidation primitive available (all non-global translations). The
values are limited to 32 bits: sufficient for CR3 below 4 GiB, CR0 and CR4; not for PCID/high CR3 bits.
No change to hosted compilation, to the index rule (E_TARGET_PROFILE for n other than 0/3/4) or to the i386 boot IR.

## CPU and exception primitives (PVH-EXCEPTION-IDT-PF-GP-NXE-001)

All require capability `cpu.control`; hosted compilation refuses them (`E_TARGET_PROFILE`).

| Primitive | Type | Profiles | Lowering |
|---|---|---|---|
| `cpu.read_cr(2)` | `u32` | both | `mov crN` (read only; `write_cr(2,..)` still refused) |
| `cpu.read_cr64(n)`, n literal 0/2/3/4 | `u64` | x86_64 | `movq %crN, r64` |
| `cpu.lidt(addr u32)` | `u32` (0) | both | `lidt (addr)` |
| `cpu.rdmsr(msr u32, part)`, part literal 0 (low) / 1 (high) | `u32` | both | `rdmsr` |
| `cpu.cpuid(leaf u32, reg)`, reg literal 0 eax /1 ebx /2 ecx /3 edx (subleaf 0) | `u32` | both | `cpuid` |
| `cpu.call_addr(addr u64)` | `u32` (eax) | x86_64 | `call *r64`; caller-saved registers clobbered |

`emit-llvm --exception-handler MODULE.FUNCTION` (x86_64 only; handler `(u64) u32`, else `E_EXCEPTION_HANDLER`):
emits, in section `.text.omni_isr`, 32 stubs of 16 bytes (vector v at table + 16*v) and a common tail.
Each stub pushes a zero error code when the vector has none, then the vector, and jumps to the tail; the tail
does `cld; mov %rsp,%rdi; and $-16,%rsp; call omni.fn.<handler>; cli; hlt`. The handler receives a pointer to
`[vector][error][rip][cs][rflags][rsp][ss]`. There is no `iretq` path: handlers are terminal. The linker script
chooses the section address. Unchanged IR when the option is absent.

## Resumable exception tail (PVH-PF-RECOVERY-IRETQ-001)

`emit-llvm --exception-handler M.F --exception-resume` (x86_64 only; requires `--exception-handler`, else `E_CLI`)
replaces the terminal tail by: push rax, rcx, rdx, rsi, rdi, r8-r11 (nine caller-saved GPRs); `cld`;
`lea 72(%rsp),%rdi` (frame pointer -> `[vector][error][rip][cs][rflags][rsp][ss]`); `call M.F`; if the result is 0:
pop the nine registers in reverse, `add $16,%rsp` (drops vector and error code) and `iretq`; otherwise `cli; hlt`.
At the tail `rsp` is 8 (mod 16) on every vector, so the nine pushes give the callee a 16-byte aligned call site.

**Entry of the image.** `omni_boot_entry` is an ordinary function that never returns and the compiler assumes the SysV rule at its entry: the loader enters it as if it had been called, `rsp` = 8 (mod 16) (a 16-aligned stack plus a
return address). A loader that jumps in with an aligned stack makes every stack slot the compiler assumes 16-aligned misaligned, which faults (#GP on `movdqa`/`movaps`) as soon as an `--target-isa sse2` image spills a vector.
The conformance adapter (`tests/x64/boot64.S`) pushes a zero return address for this reason; `--defsym ALIGNED_ENTRY=1` builds the faulty loader and `tests/cp10_simd.py::EntryAlignmentTests` shows the fault.
No SSE/FPU state is saved: the image must be built without SSE (`-mno-sse`). Callee-saved registers are preserved
by the handler's own ABI. Without `--exception-resume` the emitted code is unchanged.

## Machine counter (KERNEL-MVP-K0)

`cpu.rdtsc() u64` (capability `cpu.control`, target profiles only; hosted compilation refuses it): reads the
time-stamp counter (`rdtsc`, EDX:EAX combined into a u64). The value is in TSC ticks of the machine; the primitive
makes no claim about frequency, invariance or monotonicity across CPUs or virtual-machine migration. Callers keep the
unit explicit and compare with checked arithmetic.

## Kernel-frontier extensions (target-profile extension proposal; local candidates, not certified)

All of these apply to `--target-profile baremetal-x86_64` only, require `cpu.control` (except `cpu.trap3`, which requires the new
capability `cpu.syscall`), and are refused by the hosted profile (E_TARGET_PROFILE). Default options keep the emitted IR byte-identical
to the previous candidate (gate: `k1_image_ir_byte_identical_*`, `k2_image_ir_byte_identical_*`, `k2_image_ir_byte_identical_without_thread_entry`).

### K1 (application subsystem-K1-RING3-001)
- `cpu.ltr(selector u32) u32`: `ltr` with the 16-bit selector (the descriptor becomes busy, type 0x8B).
- `cpu.trap3(vec literal 32..255, nr u64, a u64, b u64) u64`: `int vec` with rax=nr, rdi=a, rsi=b; result in rax. Capability `cpu.syscall`.
- `cpu.enter_ring3(entry u64, usp u64, area u64) u64` / `cpu.leave_ring3(area u64, value u64) u64` (need `--ring3-support`): enter saves the
  callee-saved registers and rsp in `area` (7 qwords), builds an iretq frame (SS=0x1B, CS=0x23, RFLAGS=2) and clears every other register;
  leave restores them and returns `value` from the matching `enter` (longjmp-like).
- `cpu.enter_ring3_interruptible(entry, usp, area)`: as `cpu.enter_ring3` with RFLAGS=0x202 (IF=1 at CPL3, IOPL=0); contract in `spec/ENTER_RING3_INTERRUPTIBLE_CANDIDATE.md`.
- `--isr-extra-vector N`: one more ISR stub (after the table) for a DPL3 service vector.

### K2 (application subsystem-K2-IRQ-TIMER-001)
- `cpu.sti() u32`, `cpu.cli() u32`, `cpu.wait_irq() u32` (`sti; hlt; cli`, so a wakeup is always observed before interrupts are masked again).
- `--isr-count N` (32..128, default 32): number of ISR stubs; vectors >= 32 push a zero error code.

### K3 (application subsystem-K3-CONTEXT-001)
- `--thread-entry module.function` (function type `() u32`): emits `omni_switch_context` and `omni_thread_trampoline`.
- `cpu.switch_context(old_area u64, new_area u64) u64`: saves rbx, rbp, r12-r15 and rsp into the 56-byte `old_area`, loads them from
  `new_area`, and `ret`s into the new context (a fresh context has the trampoline address on top of its stack); returns 0 when the old
  context is resumed later.
- `cpu.thread_trampoline() u64`: the trampoline address (aligns rsp, calls the thread entry, parks with `cli; hlt` if it returns).
- Not covered: FPU/SSE state (the profile forbids SSE), per-thread TLS, stack bounds (caller-owned), preemption safety (the caller must keep
  interrupts masked across the switch; an ISR may call `cpu.switch_context`).
