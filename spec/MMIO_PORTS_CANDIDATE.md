> Distribution status: WIP / NOT_RELEASED. Technical version labels describe independent contracts, not public release certification.

# Typed MMIO, ports and device transfers — CP-08 candidate

**Status:** `CANDIDATE` (CP-08 rows 8.2, 8.4, 8.5, 8.6; MN-03/05). Not adopted, not certified.
**Representation:** none new (a library over `raw.*`, `port.*`, nominal resources). **Library:** `examples/storage/mmio.omni`, `dma.omni`. **Tests:** `tests/cp08_mmio.py`, `tests/cp08_dma.py`.

## 1. Registers and ports

A device is described by **policy types**: a `Region` says where its registers are (`base`, `size`); each register is a type implementing the traits of what the device allows on it. An operation exists only for the registers that implement its trait, so a forbidden access does not compile (`E_GENERIC_CONSTRAINT`).

| Trait | Operation | Notes |
|---|---|---|
| `Readable` | `read` | no side effect |
| `Writable` | `write` | a write-only register has no `read` |
| `ReadClear` | `read_clear` | a read changes the device; no plain `read` exists for it |
| `W1C` | `clear(mask)` | one store of the mask, never a read-modify-write |
| `ReadWrite` | `modify(clear, set)` | the explicit, non-atomic read-modify-write; returns the old value |
| `PortReadable`/`PortWritable`/`PortReadClear` | `port_read`/`port_write`/`port_read_clear` | same permissions on port numbers |

Checked at run time (what depends on numbers): width 1/2/4/8, offset aligned to width, offset+width inside the region, a value that fits the width, a valid region (non-empty, no wrap, canonical). Outcome codes 1..8 are in the header of `mmio.omni`. No accidental read-modify-write is proved on the emitted code: a write-only/W1C operation reaches no load, a plain read reaches no store.

## 2. Mapping lifetime

`Mapping<G>` is an owned resource: lent to every access, consumed by `unmap`. A register cannot be reached after the mapping ended (`E_RESOURCE_MOVED`) and a mapping cannot be forgotten (`E_RESOURCE_UNCONSUMED`). Raw access still needs `memory.raw` (`port.io` for ports).

## 3. Operations the device performs by itself (8.6)

`dma.Block<S>` is storage the program owns; `start` rings a doorbell register and turns it into `InFlight<S>` (the program holds no `Block`, so nothing can read, write or free the storage); `finish` returns the `Block` only when the status register reads zero and otherwise gives the `InFlight` back; the only other exit is the explicit `abandon` (the storage is given up for good). Dropping an `InFlight` is `E_RESOURCE_UNCONSUMED`. A doorbell that cannot be rung starts nothing and returns the block.

## 4. Evidence kinds (kept apart)

MODEL (evaluator over RAM), ARTIFACT (what the emitted code reaches), EMULATION (QEMU: local APIC page, 16550 UART, LAPIC timer as the DMA device). Emulation is not hardware.
