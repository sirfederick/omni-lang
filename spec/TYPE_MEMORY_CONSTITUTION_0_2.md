> Distribution status: WIP / NOT_RELEASED. Technical version labels describe independent contracts, not public release certification.

# Omni Type & Memory Constitution — 0.2 foundation

**Status:** normative design constraints for subsequent 0.x features. It does not make unimplemented syntax available.

## A. Core constitutional rules

1. **Defined behavior by default.** Ordinary safe Omni semantics must not rely on C-style undefined behavior for signed overflow, invalid shifts, lifetime violations or uninitialized reads.
2. **Explicit information loss.** Numeric conversion that may change range/signedness requires explicit syntax or a separately specified compile-time constant rule.
3. **No hidden promotion lattice.** Alpha.2 integer variables of different types do not silently promote to a common type.
4. **Checked arithmetic is the default.** Integer `+ - *` have deterministic overflow failure independent of build mode.
5. **Intentional arithmetic is visible.** Wrapping (`+% -% *%`) and saturating (`+| -| *|`) semantics are explicit at source/IR level.
6. **Value is not Resource.** Copy/value semantics and lifecycle-governed Resource semantics stay distinct.
7. **Borrow is not a pointer.** A borrow expresses temporary non-owning access under language rules; future raw-pointer operations require an explicit unsafe/system boundary.
8. **Unsafe must be local and auditable.** Future FFI/MMIO/raw memory cannot silently weaken ordinary language rules.
9. **ADTs are first-class.** `Option`/`Result` are the proving subset for future user-defined sum types and exhaustive matching.
10. **Interfaces are composition, not class inheritance.** Future polymorphism must not require a nominal class hierarchy as the language's organizing principle.
11. **C ABI compatibility is not Omni-safe semantics.** FFI layout/calling conventions may be exposed without importing C's implicit conversions or undefined behavior.

## B. Numeric constitution frozen by alpha.2

- Standard integer widths are `8/16/32/64`, signed and unsigned.
- Width/sign are part of semantic type identity and do not vary by target.
- Signed integers use two's-complement value interpretation for implemented targets/operations.
- Unsuffixed decimal literals remain `u32` temporarily for compatibility; explicit suffixes select other standard widths.
- Binary integer arithmetic requires exact operand type equality in alpha.2.
- Ordinary arithmetic is checked; explicit wrapping/saturating arithmetic is represented distinctly in Omni IR.
- Explicit casts are range-checked at runtime when source value is not a compile-time-known value.
- Arbitrary bit-width integers are a researched future option, not alpha.2 semantics.

## C. Identity seam for future memory

`omni.type-descriptor/1` establishes semantic type identity before the full reflection/object memory system exists. It may later be referenced by SisNervCent/OmniHash/object descriptors. It does not grant authority, identify allocations, or create persistence. See `TYPE_IDENTITY_0_2.md`.

## D. Inspirations and deliberate divergences

Omni learns from C's explicit representation/control and ABI ecosystem, Go's intentionally small conversion/promotion model and tooling discipline, Rust's distinction between safe and unsafe/lifecycle-aware semantics, and Zig's explicit arithmetic intent operators. These are design inputs, not compatibility claims and not a commitment to copy their surface syntax or full type systems.

The independent Omni choices frozen here are: deterministic checked arithmetic in every build mode, explicit alternative arithmetic modes, content-derived type descriptors, and a future profile architecture where low-level capabilities do not contaminate everyday code.
## Security invariants reinforced by alpha.4.1

- **Data is not authority.** Semantic identity (`type_id`), representation identity (`layout_id`), object/resource identity and authorization are distinct domains. No identity/layout match grants permission.
- **Single source of truth for effects.** Function effectfulness is derived from its capability set; a second mutable `io`/security boolean is not part of the compiler IR.
- **Unknown privileged capability fails closed.** Capability names must belong to the closed registry before they enter a checked program.
- **Textual inputs are length-aware UTF-8.** Embedded NUL and malformed UTF-8 are rejected as text; binary payloads belong to `Bytes`/Wire and are processed with explicit lengths.
- **Cryptography is provider-backed.** Omni may define identity/envelope semantics, but cryptographic primitives are supplied by established providers; the compiler does not implement SHA-256 itself.
- **Representation downgrade fails closed.** A historical Wave/Wire reader may admit only the semantics of that historical version; relabeling newer semantics under an older version must fail.

