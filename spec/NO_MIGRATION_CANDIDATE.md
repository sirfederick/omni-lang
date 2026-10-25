> Distribution status: WIP / NOT_RELEASED. Technical version labels describe independent contracts, not public release certification.

# No-migration obligation — candidate (OMNI-CORE-PRO-FOUNDATION-001, CP-14, third slice)

**Status:** `CANDIDATE`, not adopted, not certified. Profile `baremetal-x86_64`, QEMU TCG with two vCPUs. No compiler feature: a library written in Omni
(`tests/x64/pin.omni`) on nominal affine resources and `cpu.cpuid`. Core has no scheduler, so it **cannot prevent** a saved context from being resumed
on another CPU; it provides the obligation and the detection.

## 1. Library
| Function | Meaning |
|---|---|
| `cpu_id() u32` | the initial APIC id of the running CPU (CPUID leaf 1, EBX[31:24]) |
| `enter() Resource<Pin>` | starts a section pinned to the current CPU; the guard holds that id |
| `exit(move(g)) u32` | ends the section; 0 if still on the same CPU, 1 if the context moved |
| `exit_strict(move(g))` | as `exit`, but a moved context ends the guest with exit value 94: CPU-local data is never used as if it were still valid |
A section that is never ended (`E_RESOURCE_UNCONSUMED`) or ended twice (`E_RESOURCE_MOVED`) does not compile, so the check cannot be skipped by a path.

## 2. Acceptance (`tests/language_0_8_3_alpha8.py::A83X64PinTests`)
Real cross-CPU migration with `cpu.switch_context` (`tests/x64/pin_migrate.omni`): thread T enters on one CPU and yields inside the section; the other CPU
resumes it from the context the first CPU saved.
- CPU 0 → CPU 1: `exit` reports 1, entry id 0, exit id 1; CPU 1 → CPU 0: entry id 1, exit id 0;
- control, the same program resumed on the same CPU: `exit` reports 0;
- `exit_strict` after a migration: the guest ends with exit value 94 (status 189);
- compile time: leaked and double-ended sections do not compile.

## 3. Not provided
Prevention (a scheduler policy), interrupts and preemption inside a section (a pinned section must also keep interrupts off, which `irq`/`spin` guards
already express), per-CPU data access checked against the pin by the compiler (`pcpu.*` does not take a pin), CPU hotplug, real hardware. The CPU
identity is the APIC id, which the guest reads from CPUID; a hypervisor that remaps ids breaks the assumption.
