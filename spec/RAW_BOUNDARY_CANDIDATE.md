> Distribution status: WIP / NOT_RELEASED. Technical version labels describe independent contracts, not public release certification.

# The raw boundary — CP-08 candidate

**Status:** `CANDIDATE` (CP-08 row 8.3; MN-08). Not adopted, not certified. **Representation:** none new. **Tests:** `tests/cp08_raw_boundary.py`.

## 1. Formal: one operation, one capability

| Operations | Capability |
|---|---|
| `raw.load8/32/64`, `raw.store8/32/64`, `raw.read<R>`, `raw.write<R>` | `memory.raw` |
| `atomic.*` | `memory.atomic` |
| `tls.*`, `pcpu.*` | `memory.tls`, `memory.pcpu` |
| `port.in8/16/32`, `port.out8/16/32` | `port.io` |
| `cpu.*` (control registers, MSR, CPUID, descriptor tables, context, FP state, flags) | `cpu.control` |
| `cpu.trap3` (system gate) | `cpu.syscall` |
| calls to an `extern` function | `ffi.call` plus whatever the declaration lists |

Without the capability the program does not compile (`E_CAPABILITY`, naming it); another capability does not stand in for it. All of them are `critical`, not delegable and not serializable in the capability registry: authority never leaves the program.

## 2. Localized and visible

`omni capabilities` separates `direct_required` (what a function does itself) from `required` (what it reaches through calls) and reports `excess` (declared and never used). The **boundary** is the set of functions whose `direct_required` names a raw-class capability; a caller of such a function is not part of it. The same facts are in the OSNMF function identities (capabilities and calls are part of the fingerprint).

## 3. Obligations the author accepts

`memory.raw`: the address is valid for the access, the access does not violate the aliasing the program relies on; typed `raw.read/write` never assume alignment. `port.io`/`cpu.control`: the instruction is legal at the current privilege and device state. `memory.atomic`: the address is aligned (a misaligned atomic is a trap, `E_ATOMIC_ALIGN`). `ffi.call`: the foreign routine does what its declaration says. The language cannot check these; it records where they are.

## 4. Not done in 1.3

A block syntax `raw<Memory|Device|Abi> { ... }` is sugar over this per-function boundary and is deferred to 1.4.
