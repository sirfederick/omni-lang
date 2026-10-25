> Distribution status: WIP / NOT_RELEASED. Technical version labels describe independent contracts, not public release certification.

# Omni Language 0.8.1-alpha.8 — Compatibility Contract

**Current writer:** Wave16 / OMC16  
**Executable legacy readers:** Wave/OMC 1..15  
**Systemic persistence:** OSM2 / OSMI2  
**Machine-semantic envelope:** ONME2  
**Cognitive offload:** OCAP1

## 1. Alpha.8 predecessor compatibility

`0.8.0-alpha.8` is the immutable certified predecessor and writes Wave12/OMC12.

0.8.1 MUST read authentic Wave12/OMC12 programs, including Alpha.8 `BorrowMut<T>` and persistent local-loan semantics.

## 2. Float semantic fence

Wave13/OMC13 is the first executable representation that admits IEEE f32/f64. Wave14/OMC14 inherits those semantics unchanged.

The following are 0.8.1/Wave13/OMC13 semantics:

- `f32` and `f64` types;
- explicit `f32`/`f64` literals;
- explicit integer/float casts;
- float arithmetic/comparisons.

They MUST NOT be accepted after representation relabeling to Wave/OMC <=12.

A program containing no post-Alpha.8 semantics may be decoded from its authentic historical version. Compatibility is semantic, not permission to lie about an artifact's writer version.

## 3. ONME and OSNMF

ONME remains ONME2 because its envelope schema and integrity/lineage contract are unchanged. ONME2 carries the current Wave representation internally and therefore inherits the Wave13 float fence.

OSM2/OSMI2 remain unchanged. Float TypeIDs use the existing `omni.type/1` canonical identity domain.

## 4. Downgrade rule

```text
new semantics + older representation label => reject
authentic older semantics + older representation => accept
```

No parser, checker, evaluator, ONME decoder, or Wire reader may use a representation version as a cosmetic field.


## 5. Unicode semantic fence

Wave14/OMC14 is the first executable representation that admits:

- `Char`;
- `char.from_u32` / `char.codepoint`;
- `text.from_char`;
- `text.equals`;
- `text.byte_len`;
- `text.scalar_len`;
- `text.scalar_at`;
- exact Text equality as an executable Core semantic.

Relabeling any of those semantics to Wave13/OMC13 or earlier MUST fail closed.

Authentic Wave13/OMC13 f32/f64 programs remain readable.


## 6. A81.3 data/control fence

Wave15/OMC15 is the first executable representation that admits:

- flat Tuple destructuring statements;
- structured `break` / `continue`;
- canonical checked index syntax lowering;
- wildcard payload pattern `_`.

Relabeling those semantics to Wave14/OMC14 or earlier MUST fail closed.

Authentic Wave14/OMC14 Unicode programs remain readable, and Wave15/OMC15 inherits all prior float, Unicode, ownership and authority semantics.


## 7. A81.4 Range fence

Wave16/OMC16 is the first executable representation that admits:

- `Range<u32>`;
- exclusive range construction `a..b`;
- inclusive range construction `a..=b`;
- structured `for-in` over Range values.

Relabeling those semantics to Wave15/OMC15 or earlier MUST fail closed.

Authentic Wave15/OMC15 A81.3 programs remain readable. Wave16/OMC16 inherits all prior float, Unicode, ownership, authority and data/control semantics.
