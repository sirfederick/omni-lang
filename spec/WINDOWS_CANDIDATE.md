> Distribution status: WIP / NOT_RELEASED. Technical version labels describe independent contracts, not public release certification.

# CP-02 candidate — dynamic windows over a buffer, disjoint splitting, and no forged lifetime or authority

Status: candidate for Core 1.3.0.0. A library written in Omni (`examples/storage/window.omni`); no compiler feature of its own. It answers rows 2.5 (a dynamic view of storage
with bounds and validity during all of its use) and 2.6 (splitting into sub-regions that are checked to be disjoint), and the adversarial rows 2.10 of the closure matrix.

## 1. What a window is

`Window { off u32, len u32 }` is **plain data**: it grants nothing. It is used on a buffer the caller already holds, lent with `Borrow<Buffer>` (to read) or `BorrowMut<Buffer>`
(to write), so a window can only reach bytes of a buffer the caller is entitled to. Its validity is not assumed: **every use checks the window against the buffer it is used on**
(`fits`: `off <= len(buffer) && len <= len(buffer) - off`, a form that cannot overflow) and the index against the window. A window that does not fit (forged, made for a larger
buffer, or with an offset that would overflow) is refused with a typed code and no byte is touched. A buffer only grows, so a window that fit stays valid; growth needs
`BorrowMut`, so it cannot happen while a read is in progress.

| Operation | Result |
|---|---|
| `whole(b)` | the window of the whole buffer |
| `fits(b, w)` | does the window fit this buffer |
| `sub(w, off, n)` | a window inside `w` (relative offsets), `Err(5)` when it does not fit in `w` |
| `split(w, at)` | `Pair { left [0,at), right [at,len) }`: no shared byte, together exactly `w`; `Err(5)` when `at > len` |
| `get(b, w, i)` / `put(b, w, i, v)` | one byte inside the window; `Err(1)` window does not fit, `Err(2)` index outside the window |
| `fill(b, w, v)` | every byte of the window |
| `overlap(a, b)` | do two windows share a byte (empty windows share none) |
| `copy(b, src, dst)` | bytes of `src` over `dst`; `Err(1)` a window does not fit, `Err(4)` different lengths, `Err(3)` the windows overlap: the disjointness is **checked, not assumed** |

## 2. What is and is not guaranteed

- Guaranteed, and tested for every offset and length up to 10 on an 8-byte buffer: `fits` is exactly `off + len <= buffer length`, and a read inside a fitting window returns
  the byte at `off + i`; a split never shares a byte and always covers the window; writes through one half leave the other untouched; a refused call changes nothing.
- A window is not a borrow: the compiler does not tie it to the buffer, which is why it is re-checked at each use. Two forged windows can overlap; the operation that needs
  them disjoint (`copy`) refuses. A static view type with a region over dynamic storage (a `View<u8>` that the borrow checker keeps alive and exclusive) is not part of this
  candidate.

## 3. Forged lifetimes and authorities (row 2.10)

`ForgedLifetimeAndAuthorityTests` (`tests/cp02_adversarial.py`): an integer is not a `Borrow`, a `Resource` or a buffer (`E_TYPE`, and a cast of a resource to an integer or of an
integer to a resource does not compile); a borrow cannot be kept in a record, returned from a local, or wrapped in a `Result` (`E_TYPE`, `E_BORROW_ESCAPE`); an element lent by a
cursor does not outlive its sequence (`E_BORROW_CONFLICT`); a token of one registry type does not open another kind of registry (`E_TYPE`), the buffer inside a registry is not
reachable outside its module (`E_RESOURCE_PRIVATE`), and a registry forged from a buffer and a record literal cannot be sealed (`E_RESOURCE_PRIVATE`); a forged cursor position is
`more == false`, and `at` on it is the typed fault `E_SLOT_STATE` in both engines (never a read); another type's `put` hands its resource back, its `take` and `state` are refused.

## 4. Field projection by API (row 2.4)

A borrowable value is a nominal resource: one `u64` or one `Resource<Buffer>` field (`E_RESOURCE_TYPE` otherwise). The projection of that single field is `resource.inner` /
`resource.inner_mut`, available only inside the module that declares the type; the element of a container is lent by the container's own API (`Seq.get`, `Seq.at`). A record
with several fields is a **value**, not a resource: its fields are read by value or borrowed on locals (`borrow(r.field)`), and it cannot be lent across an API as a
whole. That is the decision of the language for this profile; a multi-field kernel aggregate over a region keeps the handle pattern of `region.omni` (row 2.3b).
