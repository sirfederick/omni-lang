> Distribution status: WIP / NOT_RELEASED. Technical version labels describe independent contracts, not public release certification.

# Systemic Durability 0.9.4

**Status:** normative A94 convergence contract
**Language version:** `0.9.4`

This specification hardens persistence and observation of the existing System
Memory model. It introduces no Omni language semantic construct.

## Snapshot set

A newly published snapshot is the set:

```text
STORE.omem          OSM2
STORE.omem.idx      OSMI2
STORE.omem.commit   OSMC1
```

`OSMC1` is an external publication record, not an OSM/OSMI representation
version. It binds the exact SHA-256 and byte size of the store and index plus
the epoch and OSM2-committed index projection root. Its final integrity line
commits every preceding record in canonical order.

Publication uses a bounded `STORE.omem.txn` record while replacement is in
progress. A reader encountering an incomplete or inconsistent transaction
fails with `E_DURABILITY`. If every final path already matches all transaction
hashes, recovery may remove the transaction record and expose the committed
set. No partial set is treated as current.

The guarantee is atomic *visibility* of the coherent set, not an unsupported
claim that a filesystem performs one atomic operation across three paths.

Symlink or non-regular transaction, commit, store or index paths fail closed.
Temporary files are private siblings and are never authority.

## Indexed locality

For OSM2/OSMI2 with valid OSMC1, an indexed operation validates:

- OSMI2 internal integrity over the exact index bytes;
- OSMC1 integrity and exact index hash/size;
- the OSM2 header, epoch and committed projection root;
- equality of epoch/projection commitments across OSM2, OSMI2 and OSMC1.

It reads only the OSM2 header records from the store. It does not assert that
the unconsumed body was read or revalidated. A later full-store consumer still
validates the complete OSM2 semantic roots. Legacy snapshots without OSMC1
retain exact full-store hashing during indexed access.

The observable locality report includes `store_bytes_read`,
`index_bytes_read`, `commit_bytes_read`, `full_store_parsed` and
`full_store_hashed`.

## Pulse continuity

For previous sequence `p` and current sequence `c`:

- `c = p + 1`: `CONTIGUOUS`, delta is authoritative for that pair;
- identical epoch at `c = p`: `DUPLICATE`, no new delta;
- `c > p + 1`: `GAP_REQUIRES_RESNAPSHOT`, delta absence is not asserted;
- `c < p`, or equal sequence with different identity: `E_EPOCH`.

Sequence arithmetic is checked and never wraps.

## Durable scale

Logical structural sharing and durable overrides are separate claims. The
durable gate writes a canonical bounded override corpus, closes it, reopens it
in a fresh process, validates every identity/value/checksum and proves conflict
and truncation rejection. Reports state both logical population and exact
durable record count; one cannot substitute for the other.

## Compatibility

OSM1 full-store reads and historical OSM2/OSMI2 pairs remain readable. Their
bytes and historical receipts are unchanged. New OSMC1-aware readers retain
the legacy full-store-hash path when OSMC1 is absent. Wave20/OMC20, ONME2 and
OCAP1 are unchanged.
