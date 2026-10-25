> Distribution status: WIP / NOT_RELEASED. Technical version labels describe independent contracts, not public release certification.

# Callable registration, deferred use and safe retirement — candidate (OMNI-CORE-PRO-FOUNDATION-001, CP-06)

**Status:** `CANDIDATE`, not adopted, not certified. A library written in Omni (`tests/x64/cbreg.omni`, with `epoch.omni`) over `CROSS_MODULE_TRAITS_CANDIDATE.md`,
`NATIVE_LAYOUT_CANDIDATE.md` (typed raw access), `QUIESCENCE_CANDIDATE.md` and nominal affine resources. **No compiler feature of its own.**

## 1. The callable family
A callable is a **plain environment record `H`** plus the code of its `Handler` impl, selected statically (`Handler.call<H>`): no function pointers, no vtables, no
dynamic dispatch. The trait is `call(h, x) u32 !{memory.raw}` and `dispose(h) u32 !{memory.atomic}`; an impl may use at most those capabilities (`E_TRAIT_EFFECT`
otherwise), and `register`/`retire` carry them transitively. The environment is plain data (integers and plain records): an environment that is not plain (`Text`,
`Resource`, borrow) cannot be placed in the slot (`E_LAYOUT`), so a short-lived capture cannot be retained. Closures with syntactic capture stay immediate-call only;
the supported way to retain a callable is to write its environment as a record.

## 2. Operations (`cbreg`)
| Operation | Meaning |
|---|---|
| `register<H>(slot, env) Resource<Reg>` | writes the environment into the slot (`raw.write<H>`), bumps the 24-bit generation, publishes the slot with release stores; the slot must be empty and below 2^40 |
| `handle(borrow(reg)) u64` | the token: slot address in bits 0..39, generation in 40..63 |
| `fire<H>(slot, token, x) Result<u32,u32>` | `Err(1)` slot not live, `Err(2)` stale generation, `Err(3)` token for another slot; otherwise `Ok(call(copy of env, x))`. Used inside an epoch read section |
| `retire<H>(reg, epoch, reader_slot, attempts) u32` | unpublishes the slot, waits for the reader slot to quiesce (`epoch.advance`/`epoch.wait`), THEN disposes the environment exactly once and poisons its bytes |
`Reg` is a nominal affine resource: a registration never retired (`E_RESOURCE_UNCONSUMED`), retired twice (`E_RESOURCE_MOVED`), or leaked by an early return does not compile.

## 3. Acceptance (`A83CrossModuleTraitTests`, `A83X64CallbackTests`)
- one CPU: use, late call after retirement, reuse of the slot (the old token is refused by generation, the new one works), a forged address is refused, exact disposal, poisoned bytes;
- two vCPUs: a reader fires continuously while the writer registers and retires 2000 times in the same slot; no call saw a torn or poisoned environment, every environment
  was disposed exactly once, the slot ends idle; the control without the quiescence wait does see poison, every time;
- compile time: leaked / double / early-exit registration, non-plain environment, excess authority, a type without an impl.

## 4. Not provided
Syntactic closures that outlive their frame, function pointers and dynamic dispatch, more than one reader slot, grace-period batching, preemption inside a call (a call
runs to completion inside its read section), callbacks across the hosted FFI, a proof of the memory model beyond the tested interleavings. The generation is never reused: a slot whose 16777215 generations are
spent refuses a new registration (exit value 93), see the amendment of 2026-10-23. The hosted (non-freestanding) composition pattern with environments that own Resources (`A83CallbackPatternTests`) is unchanged.

## Type binding amendment (frozen for implementation, 2026-10-20)
The raw slot header becomes 40 bytes: state +0 u32, generation +4 u32, nominal layout digest +8..39 (four u64), environment +40.
`register<H>` writes all four `layout.identity<H>` words before publishing live. `fire<H>` returns Err(4) on a digest mismatch before reading H or invoking code.
`retire<H>` checks live state, token generation, and all four words before unpublishing or reading/disposal; invalid retire halts the guest with 93.
Registration/retirement require one serialized writer for a slot. A caller must hold an epoch reader guard while checking and invoking fire, publish the token only
after register returns, stop publishing it before retire, and prevent writer reentrancy. These are RAW API preconditions (memory.raw), not statically enforced safety.
The 24-bit generation runs through 1..16777215 and is NOT reused (amendment of 2026-10-23, adendum 009A CBREG-01): `next_generation` answers 0 for a spent slot and `register` ends the guest with 93 instead of wrapping to 1,
so a token from an earlier occupation of a slot can never match a later one; the limit is visible (16777215 registrations of one slot). Tested with the generation preloaded near its end (`CallbackGenerationTests`), not by
running millions of callbacks. `retire` and `retire_all` check that the epoch can advance before they touch the registration (exit value 96). A token is a plain copyable u64; the `Reg` resource is the one that cannot be copied.
No universal ABA or memory-order proof is claimed. TypeID still does not grant memory authority, capacity, synchronization or lifetime.
