> Distribution status: WIP / NOT_RELEASED. Technical version labels describe independent contracts, not public release certification.

# Host Interoperability Profile 0.9.5

**Status:** normative A95 convergence contract  
**Language version:** `0.9.5`

This specification composes already-certified Core capabilities into a bounded
consumer profile. It introduces no keyword, type rule, authority kind, foreign
ABI, provider API or representation version.

## Profile boundaries

The A95 Core profile consists of:

- the A86 hosted filesystem, process, TCP and fixed copy-only FFI contracts;
- real Node and Python child-process fixtures using the same bounded protocol;
- OCAP1 provider-neutral context envelopes and the certification-only loopback
  adapter;
- OHP1 decisions immediately before hosted effects;
- OCAP/OMP separation: evidence or proposal is never authority;
- the exact Core package/stdlib and target profile consumed by application subsystem.

External provider transports, credentials, SDKs, calibration, decision policy,
application-specific components
remain application subsystem-owned. Their names and product schemas do not become Core
semantics.

## Authority invariants

1. Every hosted effect requires a fresh OHP1 allow decision bound to effect,
   target, subject, generation and relevant constraints.
2. A package digest, provider identity, model response, confidence, evidence,
   recommendation or OCAP envelope grants no authority.
3. Node/Python processes receive only the bounded copy protocol; they do not
   inherit ambient authority or internal Core objects.
4. FFI admits only the fixed versioned copy ABI and rejects size, status,
   timeout and malformed-output violations with typed errors.
5. Pre-dispatch refusal is distinct from post-dispatch lost acknowledgement;
   the latter remains `UNKNOWN_OUTCOME` and is never retried automatically.
6. Core remains deterministic and usable with every remote provider absent.

## Conformance evidence

The profile gate MUST exercise the actual available local boundaries where the
claim requires them:

- real compiled C shared-library fixture through the A86 FFI protocol;
- real Node and Python processes with fresh endpoints and bounded payloads;
- real local TCP refusal, timeout/malformed response and lost-ACK oracles;
- OCAP loopback as loopback evidence only, plus rejection of unavailable
  external adapters without affecting local execution;
- package/target identity and exact-candidate application subsystem compatibility.

Mocks and loopbacks may test isolated state machines and fault paths, but may
not satisfy real-process, real-FFI, real-provider or production-profile claims.
No external provider claim is made by Core A95.

## Compatibility

Wave20/OMC20, ONME2, OSM2, OSMI2, OSMC1, OSMT1 and OCAP1 remain unchanged.
Historical readers and release receipts retain their meaning. A95 freezes a
composed profile; it does not broaden the public surface frozen at A91.
