> Distribution status: WIP / NOT_RELEASED. Technical version labels describe independent contracts, not public release certification.

# `cpu.enter_ring3_interruptible` - candidate contract

**Status:** `LOCAL_CANDIDATE` for Omni Core 1.3.0.0. It extends `spec/TARGET_BAREMETAL_PROFILE_CANDIDATE.md` section K1 and adds no new
capability, option or representation: the name is covered by the existing `cpu.` prefix of the Wave21/OMC21 fence.

## 1. Problem
`cpu.enter_ring3` builds its `iretq` frame with `RFLAGS = 0x2`, so the CPU runs user code with `IF = 0`: no asynchronous interrupt is ever
delivered while a user context runs. A consumer that preempts or time-slices user code needs the same entry with `IF = 1` at CPL3 only,
without giving user code the means to change that.

## 2. Contract
`cpu.enter_ring3_interruptible(entry u64, usp u64, area u64) u64`

| Aspect | Rule |
|---|---|
| capability | `cpu.control` (`E_CAPABILITY` otherwise) |
| typing | exactly three `u64` operands (`E_ARITY`, `E_TYPE`); result `u64` |
| profile | `baremetal-x86_64` with `--ring3-support` (`E_TARGET_PROFILE` otherwise); hosted `emit-llvm` / `build` refuse it |
| area | the same 7-qword save area as `cpu.enter_ring3` (rbx, rbp, r12-r15, rsp); the shared `cpu.leave_ring3(area, value)` restores it and returns `value` from the matching `enter` call |
| frame | `iretq` frame `SS=0x1B`, `RSP=usp`, **`RFLAGS=0x202`**, `CS=0x23`, `RIP=entry` (`cpu.enter_ring3` uses `RFLAGS=0x2`) |
| registers | every general register other than `rsp`/`rip` is cleared on entry |

### Security properties (the part that is verified, not assumed)
1. `IF = 1` is in force **only at CPL3**: the primitive does not enable interrupts for the caller, and the caller regains `IF` as it was
   when `leave_ring3` runs inside the consumer's handler.
2. `IOPL = 0`: user code cannot `cli`/`sti` (`#GP`), cannot execute port I/O, and `popf` at CPL3 cannot modify `IF`.
3. An interrupt at CPL3 uses `RSP0` of the loaded TSS; the consumer owns the GDT, TSS, IDT and the resumable tail. A missing or invalid
   `RSP0` is a consumer defect (double fault), not something this primitive can repair.
4. After the handler returns with `iretq` the interrupted user code continues with every register unchanged.

### Not claimed
Interrupt latency, fairness, preemption policy, SMP, controller behaviour, or that a consumer's handler is correct.

## 3. Lowering
`omni_enter_ring3_interruptible` is the byte-for-byte twin of `omni_enter_ring3` with `pushq $514` in place of `pushq $2`. It is declared and
defined (module asm) **only in modules that call the primitive**; every other program keeps byte-identical IR. The call is
`call i64 @omni_enter_ring3_interruptible(i64 entry, i64 usp, i64 area)`.

## 4. Gates (tests/language_1_3_hardware_primitives.py)
- checker: positive; missing capability; wrong arity; wrong operand type; missing `--ring3-support`; wrong profile; hosted refusal;
- IR: twin of `enter_ring3` differing exactly in the pushed RFLAGS; absent from programs that do not use it;
- QEMU (TCG, one vCPU), same user loop under both entries: with the interruptible entry the local-APIC timer interrupts it (every
  recorded CS is 0x23, count > 0) and the result is exact; with `cpu.enter_ring3` the count is 0; RFLAGS read by the user is `0x202`
  vs `0x002`; user `cli` ends the session with `1000 + 13`; callee-saved registers and the return value survive `cpu.leave_ring3`;
- mutants: RFLAGS image `0x2` (interruptibility lost) and `0x3202` (IOPL=3, containment lost) are rejected by the fixtures.
