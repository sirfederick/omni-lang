> Distribution status: WIP / NOT_RELEASED. Technical version labels describe independent contracts, not public release certification.

# Native layout, `packed struct` and typed raw memory access — candidate (OMNI-CORE-PRO-FOUNDATION-001, CP-07, first slice)

**Status:** `CANDIDATE`, not adopted, not certified. Targets: `baremetal-x86_64`, `baremetal-i386-boot` and (for the queries) hosted x86-64. Representation:
`packed struct`, the `layout.*` queries and `raw.read/raw.write` share the Wave21/OMC21 fence (no new version number).

## 1. Layout rules
A **plain record** is a `struct` whose fields are integers (`u8..u64`, `i8..i64`) or other plain records. Its layout is a pure function of the checked program and
the target (`recordLayout`):
- **native** (default): fields in declaration order, each at its natural alignment (`min(size, maxAlign)`; `maxAlign` is 8 on x86-64 and 4 on i386), tail padding
  up to the record's alignment (the largest field alignment). A nested record is placed at its own alignment.
- **`packed struct`**: alignment 1, no padding anywhere; a nested record keeps its own internal layout but is placed at the next byte.
Records that are not plain (`bool`, `Text`, `Option`, enums, borrows, resources, arrays in fields), generic templates and layouts above 4096 bytes have no layout
(`E_LAYOUT`). An instantiation of a generic record (`Box<u64>`) is a concrete record and has one. `packed` on a generic struct is `E_LAYOUT`.

## 2. Queries (pure, compile-time constants of type `u64`)
`layout.size<R>()`, `layout.align<R>()`, `layout.offset<R>(field)`. `field` is a name, not an expression. They need no capability and also work in the evaluator
(x86-64 rules) and in hosted binaries. For the i386 profile the answers use `maxAlign = 4`.

## 3. Typed raw access (`memory.raw`; freestanding targets only)
- `raw.read<R>(addr u64) R` and `raw.write<R>(addr u64, v R) u32` access the record **field by field with volatile 1-aligned loads/stores**, so a packed or unaligned
  record is never read through a falsely aligned reference. `raw.write` stores **zero in every padding byte** (including nested and tail padding): no uninitialised
  padding reaches memory. Bytes outside the record are untouched.
- A native record (`align > 1`) must be accessed at its alignment and address 0 is never a record: otherwise **trap code 14** before any access. A `packed struct` may
  be accessed at any address except 0.
- The address is a full `u64`: nothing truncates it (a read at `0x100001000` faults with `CR2 = 0x100001000`).
- The evaluator performs the same access over its sparse memory (`E_LAYOUT` instead of trap 14); a hosted native binary refuses it (`E_TARGET_PROFILE`).
- The record type is carried in the call text (`raw.read<mod.Rec>`), so Wave, Wire and ONME gain no new form; the checker rewrites `raw.read<Rec>` into that spelling.

## 4. Acceptance (`tests/language_0_8_3_alpha8.py::A83X64LayoutTests`)
- the sizes, alignments and offsets of 7 records (mixed widths, `u64` after a byte, nested native, packed, packed containing a native record) equal **LLVM's own
  layout of the very struct types the compiler emitted**, on x86-64 and on i386 (where they differ), the i386 numbers coming from a QEMU run;
- typed writes over `0xAA`-poisoned memory leave zero padding and untouched neighbours; packed records at odd addresses; nested records; read back;
- misaligned or null native access traps 14; a read above 4 GiB reports the exact address in CR2;
- evaluator and native image print the same bytes for the same statements;
- compile time: non-plain, generic template, non-record, unknown field, wrong value type, missing `memory.raw`, private record of another module;
- representation: Wave21/OMC21, `E_VERSION` when relabelled, `packed` and the query alone are each new semantics, Wave/Wire/ONME/OSNMF agree, packing is part of the
  record's OSNMF identity.

## 5. Not provided
Address-domain types (physical, virtual, device) and restricted constructors, `static`/`const` data and bss placement, bit-fields, arrays inside records, explicit
`align(N)` attributes, big-endian, endianness conversion, atomic access to a record, and any claim about real hardware. A record with a Resource, Text or enum field
cannot be viewed in raw memory.

## Candidate amendment — nominal layout identity (frozen for implementation, 2026-10-20)
`layout.identity<R>(word)` is a pure `u64` query on a checked plain record. `word` must be a literal u32 in 0..3; other arguments reject with E_LAYOUT.
Its four words, in order, encode the SHA-256 of a domain-separated canonical recursive description: module-qualified nominal key, packed/native distinction,
field names and integer types or nested record descriptions, with length-prefixed strings. Words are interpreted big-endian. The query is target independent;
it distinguishes nominally different records even when their size/alignment agree. No allocation, IO, resource, borrow or authority is created.
The digest is a type discriminator inside one checked program, not an authorization token, runtime lifetime, portable resource handle or collision-free mathematical proof.
The checker recomputes it on every entry; evaluator and both native targets return the same constant. The call is preserved as a call in Particle/Wave/OMC/ONME;
it shares the existing Wave21/OMC21 layout fence, with no new grammar or binary field. Earlier release readers reject the unsupported call; candidate snapshots
are distinguished by source SHA. Legacy layout queries are unchanged. All four words must be compared before typed callback environment reads or disposal.
