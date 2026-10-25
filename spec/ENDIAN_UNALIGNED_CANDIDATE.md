> Distribution status: WIP / NOT_RELEASED. Technical version labels describe independent contracts, not public release certification.

# Endianness and unaligned access — CP-07 candidate

**Status:** `CANDIDATE` (MN-12). Not adopted, not certified. **Representation:** none new (library). **Library:** `examples/storage/endian.omni` (pure), `endian_mem.omni` (raw memory). **Tests:** `tests/cp07_endian.py`.

## 1. Contract

* `swap16/32/64`, `to_be*`/`from_be*`, `to_le*`/`from_le*` over unsigned integers. The `be`/`le` functions branch on `target.little_endian()`, folded at validation, so the dead branch is not in the checked program. `to_X` and `from_X` are the same operation (a byte swap is its own inverse); both names exist to say the direction.
* `endian_mem.load_{le,be}{16,32,64}(Virt)` and `store_{le,be}{16,32,64}(Virt, x)`: byte-by-byte access at **any** address (never assumes alignment, never merged into a wider aligned-only access by the source), byte order as named, on every target. A store writes exactly N bytes. The whole range must be a valid virtual range; an access that would run past the canonical space is refused with the outcome of `addr.virt_add` and touches nothing.

## 2. Oracle

Python `int.to_bytes`/`from_bytes` over edge and pseudo-random values for the pure functions (evaluator, hosted native and compile time agree); a guest at an odd address in QEMU for memory.
