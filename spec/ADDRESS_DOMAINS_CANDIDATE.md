> Distribution status: WIP / NOT_RELEASED. Technical version labels describe independent contracts, not public release certification.

# Address domains and opaque records — CP-07 candidate

**Status:** `CANDIDATE` (OMNI-CORE-PRO-FOUNDATION-001, CP-07 rows 7.4–7.6; MN-03, MN-06). Not adopted, not certified.
**Representation:** `opaque struct` is Wave21 / OMC21 (Wave `(opaque)` mark, Wire flag bit 4); a program without one keeps its previous version.
**Library:** `examples/storage/addr.omni`, `addr_access.omni`. **Tests:** `tests/cp07_address_domains.py`, `tests/cp07_casts.py`.

## 1. Problem

A `u64` is a physical address, a virtual address, a device (bus) address and a size at once; the compiler cannot tell a translated address from a raw one, and an integer cast can silently drop bits.

## 2. Contract

* `opaque struct Name { ... }` — a struct whose **literal and fields can only be written/read inside its declaring module** (`E_OPAQUE` elsewhere; generated provenance code is exempt). It has the layout of a plain struct and no other special behaviour; it is how a module makes a constructor the only way to obtain a value.
* `addr.Phys` (at most 52 bits), `addr.Virt` (canonical form), `addr.Bus` are opaque. Constructors check the domain (`phys`, `phys_within`, `virt`, `bus`); `*_value` projections give the full 64 bits; `phys_add`/`virt_add` stay inside the domain and never wrap. Outcome codes: 1 outside the domain, 2 not canonical, 3 would leave the domain or wrap, 4 no translation.
* A translation between domains is a **policy type** (`addr.Translate`, `Identity1G`), like the allocator: nothing converts one domain into another implicitly and nothing is global.
* Typed access through a `Virt` is `addr_access.omni` (separate module because a hosted native binary refuses raw memory wherever it is linked).
* Integer casts are range checked (`E_CAST_RANGE`; evaluator rc 2, native 70) for every width pair — the 56-pair matrix in `cp07_casts.py` is the oracle.

## 3. Identity

OSNMF identity of a record includes `opaque|` only when set, so programs without opaque records keep their identities.

## 4. Out of scope

`Ptr<T, Space>` generic pointers; user/kernel address spaces beyond the three domains above.
