> Distribution status: WIP / NOT_RELEASED. Technical version labels describe independent contracts, not public release certification.

# Constants and static data — CP-07 candidate

**Status:** `CANDIDATE` (CP-07 row 7.7; MN-10). Not adopted, not certified.
**Representation:** none new. A constant is an ordinary pure function without parameters; a use of its name is a call. No Wave/Wire form was added.
**Tests:** `tests/cp07_static_data.py` (model, formatter, representations, guest image).

## 1. Contract

* `const NAME Type = literal` and `const NAME Array<T,N> = array(literal, ...)` — immutable static data, `pub` or private, shared across modules (`alias.NAME`), indexed and iterated like any value, never assignable. A local name wins over a constant of the same name.
* **Scalar constants (integers, bool) may be any pure expression**: other constants, arithmetic, pure functions, `layout.*`, `target.*`, `bit.*`. A constant declares no capability, so an effect in its initializer is `E_CAPABILITY`. The checker evaluates it with the evaluator's fuel and depth limits; overflow, division by zero, a cycle between constants or exhaustion is `E_CONST`. Tables stay literal (computed tables are not part of 1.3).
* A name used before it is declared inside a constant that refers to itself is a cycle (`E_CONST`).

## 2. Image policy (what a freestanding image contains)

The guest ELF is code and read-only data: no `.data`, `.bss`, `.got`, `.plt`, `.init_array`, no relocation table, no writable LOAD segment, `FileSiz == MemSiz`. A mutable global is therefore never ambient: it is a `thread_local` (its template is part of the TLS substrate) or memory the program owns, and passes through the effect system. This is asserted on the final image by the tests (`cp07_static_data.py`, `cp09_freestanding.py`).
