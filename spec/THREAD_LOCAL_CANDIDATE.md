> Distribution status: WIP / NOT_RELEASED. Technical version labels describe independent contracts, not public release certification.

# Typed thread-local variables — candidate (OMNI-CORE-PRO-FOUNDATION-001, CP-11)

**Status:** `CANDIDATE`, not adopted, not certified. Profile: `baremetal-x86_64` only. Builds on `TLS_AND_PERCPU_CANDIDATE.md` (the checked FS/GS block
substrate, which is unchanged). Representation: a `thread_local` item and the `tls.get/set/init/block_size/teardown` builtins share the Wave21/OMC21
fence (`HARDWARE_REPRESENTATION_FENCE_CANDIDATE.md`); no new version number.

## 1. Declaration
```
thread_local NAME Type = literal
```
Top-level item of a module (contextual keyword: it only means something at the start of an item). `Type` is an integer type (`u8 u16 u32 u64 i8 i16 i32 i64`).
The initial value is a constant integer literal of exactly that type (`7u64`, `-5i16`; a plain literal is `u32`). `pub` is rejected: the variable is private to
its module, and other modules reach it through the module's functions. Errors: non-integer type, non-literal or wrongly typed initial value (`E_THREAD_LOCAL`
/ `E_TYPE`), value outside the type's range (`E_OVERFLOW_LITERAL`), negative value on an unsigned type, duplicate name (`E_DUPLICATE`).

## 2. Access
| Expression | Type | Meaning |
|---|---|---|
| `tls.get(NAME)` | the variable's type | reads this thread's copy |
| `tls.set(NAME, v)` | `u32` (0) | writes this thread's copy; `v` must have the variable's type |
| `tls.block_size() u64` | `u64` | size in bytes of the per-thread block of this program (header + variables, multiple of 16) |
| `tls.init(base u64) u64` | `u64` | builds a block at `base` from the program's template; returns its size |
| `tls.teardown() u32` | `u32` (0) | invalidates the current thread's block |
`NAME` is the variable's identifier, not an expression: it cannot be passed around, borrowed or captured, so no reference into thread-local storage exists and
none can outlive a thread. All five need `memory.tls`; `tls.init` also needs `memory.raw` (it writes the block's memory). Hosted compilation, the evaluator and the
i386 profile refuse them (and a program that declares a `thread_local`) with `E_TARGET_PROFILE`.

## 3. Model (freestanding ELF, initial)
- **Layout:** one block per thread, addressed from the `FS` base (`IA32_FS_BASE`, installed by the scheduler for the thread it runs, exactly as for the substrate).
  A 16-byte header (`"OMNITLS1"`, block size) is followed by every variable of the program in module-major, declaration order, each at its natural alignment.
  The layout is a pure function of the checked program (`threadLocalLayout`), so Particle, Wave, Wire, ONME and OSNMF carry no offsets and every
  representation yields the same layout.
- **Template:** the compiler emits the initial image of a block (header, initial values, zero padding; there is no separate bss: a zero initialiser is a zero in the
  image) as a read-only constant. `tls.init(base)` copies it with `rep movsq`. `base` must be 16-byte aligned and non-zero (trap 13 otherwise). Initialisation
  cannot fail or re-enter: initial values are constants and the copy touches only the destination block. Calling it again on a live block resets that block.
- **Base and relocations:** accesses are `FS`-relative constants; there are no relocations and no `PT_TLS` program header. The block memory is owned by the caller
  (the conformance scheduler uses fixed addresses; a real consumer allocates it).
- **Faults:** before every access the header is checked (magic, and `offset + width <= size`). An unset base, a torn-down block, a block of the wrong kind or a block
  smaller than the program needs is trap code 13; nothing is read or written first. `tls.teardown` clears the magic after checking it, so a second teardown is also
  trap 13. Destruction of a scalar is the invalidation of the block; there are no destructors.
- **Per-thread versus per-CPU:** per-CPU blocks stay the substrate (`pcpu.*`, `GS`); typed per-CPU variables are not provided. `pin.omni`
  (`NO_MIGRATION_CANDIDATE.md`) detects a context resumed on another CPU.

## 4. Acceptance (`tests/language_0_8_3_alpha8.py::A83X64ThreadLocalTests`)
- two threads use the same symbols (`counter`, `flag`, `delta`, and a library module's `ticks`) with different values, across 1000 switches each; both start from the
  template although the memory was poisoned first; final values land in the right blocks; `tls.block_size()` equals the template;
- the template bytes emitted by the compiler (header, natural alignment, two's complement, declaration order across modules) are exactly the expected image;
- faults: access before `init`, after `teardown`, double `teardown`, a block whose size field is too small, a misaligned or null `init` base: trap 13;
  `init` on a live block resets it;
- compile time: unknown name, non-name argument, wrong value type, missing capability, missing `memory.raw` for `init`, access to another module's variable, a
  borrow of a thread-local, malformed declarations; hosted, evaluator and i386 refusals;
- representation: Wave21/OMC21, `E_VERSION` when relabelled older, Particle/Wave/Wire/ONME round-trips, OSNMF identical through every representation with a
  `thread-local` nucleus per variable.

## 5. Not provided (explicit limits)
Dynamic TLS, `PT_TLS` and a loader, non-integer variables (floats, records, resources: they would need destructors and lifetimes), variables initialised by an
expression, exporting a variable across modules, typed per-CPU variables, automatic block allocation (the consumer provides the memory and installs the base),
hardware other than QEMU TCG. Mutating the same variable from an interrupt handler that preempts the thread is an ordinary data race on the thread's own block
(use the interrupt guards).
