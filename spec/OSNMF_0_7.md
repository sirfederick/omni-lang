> Distribution status: WIP / NOT_RELEASED. Technical version labels describe independent contracts, not public release certification.

# OSNMF — Omni Systemic Neural Memory Fabric

**Foundation language:** `0.7.0-alpha.7`  
**Current hardened release:** `0.7.0-alpha.7.1` — OSM2 / OSMI2

OSNMF is a deterministic systemic memory/relationship projection of an Omni program. It is not metadata glued around source text and it is not an AI database.

## Omni Memory Nucleus

Nuclei expose StableEntityID, ContentID, ContractID, TypeID, domain membership, required capabilities, provenance and per-domain authority. Stable identity remains distinct from changing content identity.

Nominal type identity is canonical and module-qualified. Display spelling is not identity material. Two types that display as `User` in different modules MUST receive different canonical identities and TypeIDs.

## Alpha.8 compatibility

OSM2 / OSMI2 remain the persisted systemic formats in Alpha.8 because the physical store/index schema does not change when the language adds a new canonical type kind.

Alpha.8 `BorrowMut<T>` participates in canonical type identity exactly like other compiler-authoritative type nuclei:

```text
Borrow<Buffer>    != BorrowMut<Buffer>
shared TypeID     != exclusive TypeID
```

OSNMF records the semantic distinction through canonical TypeID/content material. It does not persist raw pointers, runtime addresses or loan-region machine state as authority. Region/Place analysis remains compiler semantics; systemic memory may describe it but cannot grant or extend a loan.

No OSM schema bump is warranted unless the persisted record grammar itself changes.

## Five logical memory domains

`structural`, `semantic`, `operational`, `confidential`, `synaptic`.

Authority is orthogonal and includes `compiler-authoritative`, `developer-declared`, `runtime-observed`, `verified-tool`, `verified-agent`, `ai-inferred`, `external-source`.

## Cryptographic roots

Each domain receives a canonical SHA-256 root. `system_root` binds the domain roots; a Neural Epoch binds sequence + system root. These prove deterministic integrity/lineage under the canonical encoding, not external truth.

## Synaptic Graph / Binding

Typed relations include `contains`, `imports`, `defines`, type relations, `requires-capability`, `specializes`, `observes-execution-of`, `describes`.

The Alpha.7 foundation demonstrates `structural-sharing/cow-v1`; full persistent propagation/conflict/migration policy remains a later gate.

## Persistence and authenticated index-first cognition

The released Alpha.7 format used `OSM1` + `OSMI1`.

Alpha.7.1 introduces:

- **OSM2** — persisted systemic snapshot whose epoch record also commits the canonical index projection root;
- **OSMI2** — acceleration index bound both to the exact store bytes and to the index projection root committed inside OSM2.

Index verification therefore checks three distinct relationships:

```text
OSMI2 self-integrity
        +
exact OSM2 file hash
        +
OSMI2 projection root == OSM2 committed index root
```

A forged index whose contents are changed and whose own integrity hash is recomputed MUST still fail while the OSM2 store remains unchanged.

Indexed query/trace/impact may hash/read the store for integrity, but they do not materialize or parse the complete graph; they report `full_store_parsed=false`.

OSM1 remains readable through the full-store parser for compatibility. OSMI1 is not accepted as an authenticated index path by Alpha.7.1; snapshots must be repacked to OSM2/OSMI2 for index-first trust.

Commands remain:

```text
omni memory SOURCE
omni memory-pack SOURCE -o system.omem
omni memory-summary system.omem
omni memory-query system.omem --entity NAME|--kind KIND|--capability CAP|--calls NAME
omni memory-trace system.omem --entity ENTITY [--depth 0..16]
omni memory-impact system.omem --entity ENTITY
```

## Operational Memory

`omni observe` adds runtime-observed nuclei under the operational domain. Raw output is not inserted by default. Previous snapshots advance the sequence and permit source-free Neural Pulse generation.

## Materialization

Logical distribution does not require one physical allocation per nucleus. Implementations may compact, deduplicate, mmap, page, stream, cache or evict provided identities, commitments and roots remain valid.

> distributed logically, compacted physically.

## Core 1.3 candidate — what the projection says, and from what

The projection is derived from the verified program (`Program` after the checker), never from a label, a name, a string or a comment, and it is the same through Particle, Wave, Wire and ONME: reading any of them and projecting gives
the same store.

* **Capabilities.** A function nucleus lists the capabilities it **requires** (those of the operations it performs and of everything it calls). A capability that is declared and not required is `excess` in `omni capabilities` and
  appears in no nucleus and in no `requires-capability` edge; the declaration is part of the function's `ContractID`. An open generic template is not analysed, so its nucleus lists its declaration. `granted` is not a field of any
  report: no grant is observed by a static projection.
* **Contracts.** The `ContractID` of a record includes `packed`, `opaque` and `extern` (the C layout contract); that of a function includes its declared capabilities, its exported C symbol and its imported one. `section` and
  `noinline` are placement, not interface, and change the `ContentID` only.
* **Generic templates.** The nominal types named in the signature of a template have a module-qualified identity (`TYPE_IDENTITY_0_2.md`), resolved in the scope of the template's module with the import alias rule of the expander.
  A name that names nothing is refused by the checker where the template is declared (`E_TYPE`, or `E_RESOURCE_TYPE` for `Resource<R>`, `Borrow<R>`, `BorrowMut<R>`), so the projection never meets an unresolved identity.
* **Historical identities.** The `Onme2Compatibility` projection computes the identities the certified compilers computed: the ONME2 files they wrote still verify. A program that those compilers could not project is written as ONME3.
* **Bounds.** `trace` accepts a depth of 0..16; a selector is an exact name, never a path or a pattern; the answers are deterministic and the persisted index is read without parsing the whole store.
