> Distribution status: WIP / NOT_RELEASED. Technical version labels describe independent contracts, not public release certification.

# Typed register fields — CP-08 candidate

**Status:** `CANDIDATE` (MN-05). Not adopted, not certified.
**Representation:** none new (library). **Library:** `examples/storage/bitfield.omni` (pure), `field.omni` (mapped registers). **Tests:** `tests/cp08_fields.py`.

## 1. Contract

A **field** is a policy type implementing `bitfield.Field` (`shift`, `width`). Pure functions, usable anywhere including `static_assert`:

* `fits<F>(bits)` — the field is a valid bit range (width ≥ 1) inside a register of `bits` bits (1..64); `disjoint<A,B>()` — no shared bit; `mask<F>()`, `limit<F>()`, `get<F>(v)`, `put<F>(v, x)` (outcome 1: x needs more bits than the field has; 2: the field is not valid). An invalid field has mask 0: nothing built on it can change a bit.
* On a mapped register (`field.omni`): `read<G,R,F>` (register `Readable`), `update<G,R,F>(m, x)` (register `ReadWrite`; keeps every other bit as the device has it; returns the old register value), `clear<G,R,F>(m)` (register `W1C`; one store of the field's mask).

Permissions stay with the register: a field of a write-only register cannot be read, a field of a read-clear register cannot be read by accident — `E_GENERIC_CONSTRAINT`.

## 2. Layout declaration

A register layout is declared next to the register and asserted at compile time: `static_assert(bitfield.fits<Mode>(32u32) && bitfield.disjoint<Mode, Enable>(), "...")`. A field outside its register or overlapping another does not compile.

## 3. Out of scope

A `register Name u32 { ... }` declaration syntax (the library carries the same checks); reserved-bit write policies beyond "keep what the device has".
