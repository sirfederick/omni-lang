> Distribution status: WIP / NOT_RELEASED. Technical version labels describe independent contracts, not public release certification.

# Link-time identity and the C ABI v1 — CP-09 candidate

**Status:** `CANDIDATE` (MN-07, MN-13, MN-14, MN-16; CP-09 rows 9.2–9.5). Not adopted, not certified.
**Representation:** Wave21 / OMC21. Wave: `(linkage (export "sym") (extern "sym") (section ".x") (noinline))` after the visibility of a function that has any; Wire: an `LNK1` trailer after the optional `TLS1` trailer (module, name, flags, export, extern, section per function). Older readers refuse with `E_VERSION`. The OSNMF function identity includes the Wave form, so a program that differs only in linkage is a different program.
**Tests:** `tests/cp09_linkage.py`, `tests/cp09_freestanding.py`.

## 1. Syntax

Between `pub` and `func`, in any order (printed canonically as export, extern, section, noinline), each at most once:

* `export "sym" func f(...)` — the C symbol `sym` reaches `f`: a thin external wrapper in the section `.text.omni_export.sym` (so a linker script can `KEEP(*(.text.omni_export.*))`).
* `extern "sym" func f(...) R !{ffi.call, ...}` — a declaration with no body; calls reach `sym`. It **must declare `ffi.call`**: what the language cannot see is never assumed pure; what it declares is what its callers need.
* `section ".name" func f` — the code goes to that section (`.text.omni_*` is the compiler's).
* `noinline func f`.

* `extern struct Name { ... }` — the C layout of a record is a **contract**: integers and plain/extern structs only (`E_LAYOUT` for a bool, float, text, resource, array, generic, or when combined with `packed`/`opaque`), natural C alignment (the one layout rule the compiler has: `layout.size/align/offset`, asserted with `static_assert`; the oracle in the tests is clang's own record layout). It is reached through an **explicit address** (`raw.read<Name>(addr)`, `raw.write<Name>(addr, v)`); it is never passed by value across the boundary. Wave21/OMC21: Wave `(extern)` mark, Wire struct flag bit 8; part of the OSNMF identity of the record.

## 2. C ABI v1 (frozen minimal)

SysV x86-64 integer convention: **up to six integer parameters and an integer result**, so a raw pointer is an explicit `u64`, a buffer is `(address u64, length u64)` and an `extern struct` is its address (the guest test passes a header and a 16-byte buffer to a C routine) (`u8..u64`, `i8..i64`; addresses are explicit `u64`s). 8- and 16-bit values carry `zeroext`/`signext` exactly as a C compiler gives them, in both directions. Names: `[A-Za-z_$][A-Za-z0-9_$]*`, at most 128 bytes, never starting with `omni` or `llvm.`, unique across the program. `extern` exists only under a freestanding profile (the evaluator and a hosted native build refuse it with `E_TARGET_PROFILE`). Everything else is `E_LINKAGE`: floats, bool, structs, more than six parameters, generics, `extern` with `export`/`section`/`noinline`, an empty or malformed name.

Out of scope for 1.3: C++ ABI, varargs, exceptions, RTTI, templates, retained callbacks, aggregate passing.

## 3. Red zone and image closure (CP-09)

Every function of an x86-64 freestanding image **built with an exception table (`--exception-handler`)** carries `noredzone` in the artifact (exceptions and interrupts push on the stack the code runs on), whatever flags the backend is given; an image without the table keeps exactly the IR it always had (no drift: `A13PortWideLoweringTests` compares it with the baseline compiler), and the i386 boot profile never gets the attribute. An image that installs its own IDT from Omni code without that flag must still be built with `-mno-red-zone`, as the SDK builder contract says. The final ELF has no undefined or libc symbol, no INTERP/DYNAMIC, the link is the program object alone, and no writable LOAD segment. Mixing profiles (a 64-bit feature in the 32-bit profile, a hosted allocator in a freestanding one, a `thread_local` in a hosted image) is `E_TARGET_PROFILE` at emission.
