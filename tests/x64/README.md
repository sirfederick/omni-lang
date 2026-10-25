# x86-64 freestanding conformance programs

Owned by Omni Core. These are small programs that test Core contracts under QEMU; they are not a kernel, not a runtime for a product and not a
copy of any consumer's code. The suites that use them live in `tests/language_0_8_3_alpha8.py` (classes `A83X64*`, `A83HardwareFenceTests`,
`A83OsnmfNewSemanticsTests`).

## What each file is, and who provides what

| File | Role | What it contributes | What it does **not** prove about Omni |
|---|---|---|---|
| `boot64.S` | **test-owned boot adapter** | QEMU's PVH loader hands over 32-bit protected mode with paging off. The adapter does the 32→64 transition (identity map of 1 GiB + the local-APIC page, PAE, `EFER.LME`, paging, 64-bit GDT), optionally enables x87/SSE (`--defsym SSE=1`), copies the AP start trampoline to `0x8000`, and jumps to `omni_boot_entry`. It also carries the AP trampoline (real → protected → long mode) for the two-vCPU programs. | Long mode, paging and AP wake-up are **adapter** work. Omni code starts at `omni_boot_entry` (BSP) and at `AP_ENTRY` (AP). Nothing here claims that Omni writes a bootloader. |
| `link32.ld` | adapter link script | explicit load addresses (QEMU loads `PT_LOAD` segments by `p_paddr`) | – |
| `payload.ld` | payload link script | entry first at `0x200000`, ISR table at `0x210000` | – |
| `rt.omni` | **Core-owned minimal service provider** | the 19 signatures the `baremetal-x86_64` profile requires, with real behaviour for what the programs execute (start, per-CPU accounting, fault reporting, serial output, exit status) and explicit `UNSUPPORTED` (exit value 126, marker `UNS`) for what they do not. Also `user_main`, the CPL3 code of the ring-3 program (in the service module so it has no accounting hook that would touch supervisor memory). | A provider with all signatures is `SERVICE_ABI_DECLARED`, not `SERVICE_RUNTIME_COMPLETE`: the suite asserts, on the emitted IR, which services each executable can reach. |
| `idt.omni` | helper module | builds a 32-gate IDT (+ one DPL3 gate) in Omni with raw stores and `bit.*` | – |
| `*.omni` programs | **the conformance programs** | atomics, SMP, exceptions, interrupts, context switch, ring 3, FP state | each states in its header what it claims |

## Claims, separated

| Observation | Admissible claim |
|---|---|
| Omni source → ELF links with no undefined references | `X64_ELF=PASS`, not `X64_RUNTIME=PASS` |
| Adapter reaches long mode and Omni code runs | `X64_BOOT_HANDOFF=PASS` for this adapter; **not** an autonomous transition written in Omni |
| atomics executed on one vCPU under QEMU TCG | `ATOMIC_NATIVE_SINGLE_CPU=PASS`, not SMP |
| two vCPUs, the AP running Omni code (it reports its own APIC id), exact shared counter, plain-pair control losing updates | `SMP_TWO_VCPU_ATOMIC_COUNTER=PASS` under QEMU TCG with `thread=multi`; **not** a memory-model proof (x86 TSO cannot show release/acquire differences, so ordering is checked on the emitted IR) |
| a callable (plain environment + Handler impl) is registered, fired from the other CPU and retired 2000 times; no call sees a retired environment, each is disposed once; the control without the quiescence wait does | `CALLBACK_REGISTRY_TWO_VCPU=PASS` under QEMU TCG; static selection only, no function pointers |
| layout queries equal LLVM's layout of the emitted types on x86-64 and i386; typed writes leave zero padding; native access is checked (trap 14); a read above 4 GiB reports the exact address | `NATIVE_LAYOUT_TYPED_ACCESS=PASS` under QEMU TCG and the evaluator; no address-domain types, no static data |
| two threads use the same `thread_local` symbols with different values across switches and start from the compiler-emitted template | `THREAD_LOCAL_TYPED_QEMU=PASS` under QEMU TCG, integer variables, FS-based, no dynamic TLS |
| a context entered on one CPU and resumed on the other is reported by the pin guard (both directions), the same-CPU control is not | `NO_MIGRATION_DETECTION_TWO_VCPU=PASS` under QEMU TCG; detection only, not prevention |
| epoch quiescence: reader never sees a retired (poisoned) object across 3000 retirements; the control without the grace period does | `QUIESCENCE_EPOCH_TWO_VCPU=PASS` under QEMU TCG; **not** a proof, not preemption-safe, no callbacks |
| exception, interrupt, context switch, ring 3, FP-state programs pass | the individual contracts named in the class docstrings, on one vCPU, under QEMU; **not** hardware |
| provider declares a signature the executable never reaches | `SERVICE_ABI_DECLARED`, listed as unreached by `test_required_signatures_are_distinguished_from_reachable_services` |

## Environment
QEMU 8.2 (`qemu-system-x86_64`, TCG), clang 18, GNU binutils (`as`, `ld`, `objcopy`, `objdump`, `nm`, `readelf`). Images are built with
`-O2 -ffunction-sections --gc-sections` and, for `gpr` images, `-mno-sse -mno-sse2 -mno-mmx -mno-80387`; **only `-O2` is claimed**. `-O0` keeps
the profile's internal arithmetic helpers and was observed to need `libgcc` symbols (`__udivdi3` …) on i386, so it is outside the claim.
The suites skip when these tools are missing; they never install anything.

## Mutants documented as equivalent (not test gaps)
- *F7, the resumable tail without `and $-16, %rsp` before `fxsave64`*: the CPU aligns `rsp` to 16 on every delivery in 64-bit mode, each stub pushes
  exactly `[error-or-0][vector]` and the tail pushes nine registers, so `rsp` is already 16-aligned for error-code and no-error-code vectors alike. The
  handler's frame argument is `8 mod 16` on the timer path (`fpu_irq`) and on the #PF path (`exc_resume`), asserted by the tests; the `and` is defensive.
- *F14, the adapter not clearing CR0.EM*: the PVH start state has `EM=0`; clearing it is redundant for this adapter and matters only to a loader that
  starts with `EM` set.
- *T19, the fence ignoring the `tls.`/`pcpu.` builtin names*: using such a builtin requires `memory.tls`/`memory.pcpu` (`E_CAPABILITY` otherwise) and both
  capabilities are fenced, so every program the name test would catch is already caught by the capability test. The name test is kept for diagnostics.
- *X10, the impl call spelled with the canonical key even inside the impl's own module*: the same function is called; only the spelling in Wave differs (`app.call__impl_…` instead of `call__impl_…`).
- *C9, `register` publishing the slot before writing the environment*: a call needs a token, and the token is published only after `register` returns, so no reader can observe the intermediate order in this protocol (the token publication is the happens-before edge). The order is kept correct anyway.
