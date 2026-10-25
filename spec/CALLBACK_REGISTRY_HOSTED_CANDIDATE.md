> Distribution status: WIP / NOT_RELEASED. Technical version labels describe independent contracts, not public release certification.

# CP-06 candidate — callables whose environment owns resources, registered, used later and retired (hosted profile)

Status: candidate for Core 1.3.0.0. A library written in Omni (`examples/storage/registry.omni`) over the owned slots of `OWNED_SLOTS_CANDIDATE.md`, plus one primitive,
`slots.gen`. It adds no ownership law and no calling convention: the freestanding family of `CALLBACK_REGISTRY_CANDIDATE.md` (raw slot, epoch quiescence, two vCPUs)
is unchanged and keeps its own evidence.

## 1. What is declared (master prompt 3.5)

| Question | Answer |
|---|---|
| Representation of the callable | an **environment record `H`** plus the code of its `Handler` impl, selected statically (`Handler.call<H>`). No function pointer, no vtable, no dynamic dispatch. Two callables with different code are two types, kept in two registries; two environments of one type are two registrations of one registry |
| Environment | a nominal resource: one `u64` or one `Resource<Buffer>` field (the rule of `resource.seal`). State that is not owned storage cannot be an environment (`E_RESOURCE_TYPE`) |
| Capture mode | by **move, at registration**: the source is consumed (`E_RESOURCE_MOVED` afterwards). A borrow cannot be captured: an environment that holds a `Borrow`/`BorrowMut` or a `Resource<Registry<..>>` is not a valid environment (`E_RESOURCE_TYPE`), so a short-lived capture and a way back into the registry are refused where the registry is typed |
| Ownership | the registry owns every registered environment until retirement or `destroy`; the environment is moved out and disposed **exactly once** |
| Effect / ABI | `Handler.call` declares `!{memory.read,memory.write}` and `dispose` `!{memory.read,memory.write}`; an impl may use at most those (`E_TRAIT_EFFECT`), and `fire` / `retire` / `destroy` carry them to their callers transitively. No foreign ABI is involved |
| Where it can be stored | in a `Registry<H>`, a nominal resource over a slot-bearing buffer (hosted profile). Not in a plain value, not across Wave/Wire/OSNMF (a callable is not serialized: nothing live is transported) |
| Lifetime | from `register` to `retire`/`destroy`. A token is `(cell, generation)` |
| Operations | `new`, `register` (environment in, token out; on failure the environment comes back), `fire` (one call, environment lent mutably), `retire` (token invalidated, environment out, `dispose` once), `check`, `count`, `capacity`, `destroy` |
| Result of an invalid call | a **typed result**, never a use of the environment: `Err(1)` nothing live in that cell, `Err(2)` stale generation. Never a fault |

## 2. `slots.gen<T>(borrow(b), i) u32`

The generation of a cell: it starts at 1, **every take of the cell raises it**, and an empty cell that reached the horizon (2^32-1) is `slots.state` 4, *exhausted*: it accepts
no further occupant (`put` is refused and hands the resource back). Hence a `(cell, generation)` token issued for one occupant can never match a later occupant of the same cell: reuse is safe without any
counter outside the cell. `0` means "no such cell" (out of range or another type). Like every `slots.*` call it is hosted-only and under the Wave21/OMC21 fence.
Accounting of a slot buffer is now 13 bytes per cell (8 of value, 1 of occupancy, 4 of generation).

**Verification variable.** 2^32 registrations of one cell are out of reach of a test, so `OMNI_SLOT_GEN_MAX=N` (N >= 2, evaluator and runtime alike; anything else is ignored)
lowers the horizon. With `OMNI_SLOT_GEN_MAX=3` a cell serves two occupants, the third registration goes to another cell, and the tokens of the first two occupants never reach it
(`GenerationHorizonTests`). Like `OMNI_FAIL_AT` and `OMNI_RESOURCE_AUDIT`, it does not exist in a program: it is read from the environment of the process that runs it.

## 3. The call in flight and the retirement

`fire` lends the environment (`BorrowMut<H>`) for the whole call and the registry is mutably borrowed for that time. The callback is handed its environment and nothing
else, and an environment cannot contain the registry or a borrow of it, so a callback **cannot register, retire or fire** anything of its registry (there is no
path to name it), and a retirement can never find a call of the same flow in flight. This is the contract of this profile: *rejection by construction*, not a lock
that a callback could wait on itself. After `retire` returns, the token is refused at once (`Err(1)`, `Err(2)` after reuse).

A retirement racing a call of **another** flow is the concurrent profile and is **not claimed here**: it is CP-13/CP-14. The freestanding quiescence evidence
(`A83X64CallbackTests`, two vCPUs) is unchanged and is not extended by this candidate.

## 4. Failure

Every acquisition point of a registration (the registry's buffer, the growth of the registry, and whatever the environment acquires) is an `OMNI_FAIL_AT` point
(`CLEANUP_FAILURE_CANDIDATE.md` §4). A registration that cannot complete hands the environment back; the sweep test ends every run with no leak and no double release.

## 5. Not provided

Callables that cross a format or an ABI, function pointers, dynamic dispatch, closures with syntactic capture that outlive their frame (they stay immediate-call:
`CLOSURES_0_8_2.md`), reentrant retirement (refused, see §3), a generation that wraps (the cell is retired for good at the maximum instead), and any claim about
unwinding (Omni has no unwinding in the hosted profile; a fault stops the process and is not a cleanup guarantee, row 3.6 of CP-03).
