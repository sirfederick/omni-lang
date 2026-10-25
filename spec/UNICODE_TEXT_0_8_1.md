> Distribution status: WIP / NOT_RELEASED. Technical version labels describe independent contracts, not public release certification.

# Omni Language 0.8.1-alpha.8 — Unicode & Text Contract

**Slice:** A81.2 — Unicode/Text completeness  
**Representation:** Wave14 / OMC14  
**Status:** design baseline; WIP / NOT_RELEASED.

## 1. Text model

`Text` is immutable, validated UTF-8.

The language distinguishes three concepts:

```text
bytes      = encoded storage units
Char       = one Unicode scalar value
grapheme   = user-perceived text cluster (stdlib-level segmentation)
```

These are not interchangeable.

## 2. Char

`Char` represents exactly one Unicode scalar value:

```text
U+0000 .. U+10FFFF
excluding U+D800 .. U+DFFF
```

`Char` is a distinct Copy/Plain scalar type. It is not an alias of `u32`.

Canonical representation:

```text
semantic type: Char
physical scalar: u32
layout: 4 bytes / 4-byte alignment
```

Construction from integers is explicit and recoverable:

```text
char.from_u32(u32) -> Result<Char,u32>
char.codepoint(Char) -> u32
```

Error code `1` means the input is not a Unicode scalar.

## 3. Text lengths

Legacy `text.len(Text)` remains byte length for compatibility.

New explicit APIs:

```text
text.byte_len(Text)   -> u32
text.scalar_len(Text) -> u32
```

No API may silently reinterpret byte length as scalar length.

## 4. Scalar access

```text
text.scalar_at(Text,u32) -> Result<Char,u32>
```

Indexing is by Unicode scalar index, not byte offset.

Error code `1` means out-of-range.

No unrestricted `Text[index]` syntax is introduced in A81.2.

## 5. Char ↔ Text

```text
text.from_char(Char) -> Result<Text,u32>
```

`Char(U+0000)` is valid, but current `Text` retains the security invariant **no embedded NUL**. Therefore conversion of U+0000 to Text fails recoverably.

## 6. Text ↔ Bytes

Existing contracts remain explicit:

```text
bytes.from_text(Text) -> Bytes
bytes.to_text(Bytes)  -> Result<Text,u32>
```

`bytes.to_text` validates UTF-8 and the Text no-NUL invariant. No lossy conversion exists.

## 7. Equality and normalization

Text equality is explicit and exact sequence equality:

```text
text.equals(Text,Text) -> bool
```

The generic binary `==`/`!=` surface is not promoted for Text in A81.2 because Wave13 did not encode operand semantic type in a way that can fence the new meaning without ambiguity.

```text
same UTF-8 scalar sequence  => equal
canonically equivalent but differently encoded sequence => not equal
```

No implicit NFC/NFD/NFKC/NFKD normalization occurs during:

- parsing;
- concatenation;
- equality;
- hashing;
- serialization;
- Text/Bytes conversion.

Normalization is an explicit future `std.text` operation backed by versioned Unicode data.

## 8. Grapheme policy

Grapheme segmentation is **not** approximated in Language Core.

A future `std.text.graphemes` surface must implement a declared Unicode segmentation standard/version (for example UAX #29) with conformance vectors. Until then, Language Core exposes bytes and Unicode scalars only.

## 9. Printing

`print(Char)` emits the UTF-8 encoding of the scalar.

`print(Text)` emits the exact Text byte sequence.

## 10. Representation fence

A81.2 semantics require Wave14 / OMC14.

Wave13 / OMC13 remains the A81.1 f32/f64 representation. It may carry floats, but MUST reject:

- `Char`;
- `char.from_u32`;
- `char.codepoint`;
- `text.from_char`;
- `text.byte_len`;
- `text.scalar_len`;
- `text.scalar_at`.

ONME remains ONME2 because its envelope schema is unchanged and carries the current Wave payload.
