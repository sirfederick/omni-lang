> Distribution status: WIP / NOT_RELEASED. Technical version labels describe independent contracts, not public release certification.

# Target introspection — CP-07 candidate

**Status:** `CANDIDATE` (MN-01). Not adopted, not certified.
**Representation:** none new. `target.*` is folded to a literal while the program is validated, so the checked program (and its hash, Wave and artifacts) contains the literal; a program that declares generics also keeps its authoring source, which stays as written.
**Tests:** `tests/cp07_target.py`.

## 1. Contract

| Expression | Type | Meaning |
|---|---|---|
| `target.pointer_width()` | `u32` | 64 (hosted, `baremetal-x86_64`) or 32 (`baremetal-i386-boot`) |
| `target.little_endian()` | `bool` | true on every supported target |
| `target.hosted()` | `bool` | false under `--target-profile` |
| `target.arch_is("x86_64" \| "i386")` | `bool` | |
| `target.has("sse2" \| "avx2" \| ...)` | `bool` | CPU features the generated code may assume: hosted x86-64 and `--target-isa sse2` images have `sse2`; `gpr` images and the i386 boot profile have none; AVX-class features are never assumed |

The argument of `arch_is`/`has` must be a quoted literal naming a known architecture/feature. An unknown name, a missing or non-literal argument, arguments where there are none, or an unknown member is `E_TARGET`: a typo is never silently `false`.

The facts come from `--target-profile` and `--target-isa`, set before the program is loaded; they are what `static_assert(target...)` and `if target.has(...)` see. The CPU feature *model* (a feature set per profile, `@requires_cpu`) is CP-10.

## 2. Out of scope

`target.os`/`target.abi` (one hosted OS, one ABI per profile), runtime lookup of any of this.
