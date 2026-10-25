> Distribution status: WIP / NOT_RELEASED. Technical version labels describe independent contracts, not public release certification.

# Omni Language 0.9.2 — Semantic Conformance

**Status:** `FROZEN_FOR_IMPLEMENTATION`

**Authority:** normative A92 contract

**Causal input:** `IR-C01` / `RFC-0071`

## 1. Scope

A92 repairs observable divergence between evaluator and native execution. It
adds no syntax, type, effect, capability, ABI, representation form or ambient
authority. The first mandatory repair is hosted filesystem error ordering for
an absent target beneath an admitted root.

## 2. Inherited surface

The public surface frozen by 0.9.1 and every certified 0.8.x semantic contract
remain unchanged. In particular, `host.read` and `host.write` retain their A86
signatures, declared capabilities, bounded payload rules and stable numeric
errors:

```text
1 DENIED
2 INVALID_INPUT
3 NOT_FOUND
4 IO_FAILURE
5 LIMIT_EXCEEDED
```

## 3. Authority before existence

For a filesystem host effect the implementation SHALL apply this order:

1. evaluate arguments left-to-right and reject malformed path/input or invalid
   numeric bounds without probing the filesystem;
2. convert the path to an absolute lexical-normal form;
3. reject a path lexically outside every eligible canonical grant root before
   probing path existence;
4. resolve the nearest existing ancestor through the platform's canonical,
   symlink-aware path mechanism and append the still-absent suffix lexically;
5. require the resolved candidate to remain within the canonical grant root;
6. immediately dispatch the effect under that proof and return the effect's
   typed result.

An implementation may use an equivalent algorithm only if it preserves the
same non-disclosure, containment and error ordering.

## 4. Missing targets

After the authority proof succeeds:

- an absent `host.read` final target returns `NOT_FOUND (3)`;
- an absent intermediate component for `host.read` returns `NOT_FOUND (3)`;
- `host.write` may create/truncate an absent final target only when the write
  grant is valid and its nearest existing parent is contained;
- a missing required parent for `host.write` follows the existing typed
  filesystem failure contract and never broadens the grant.

Existence SHALL NOT be checked first and then used to choose whether authority
is required.

## 5. Fail-closed cases

The evaluator and native runtime both return `DENIED (1)` before the effect
when the matching grant is absent, expired, stale, wrong-generation or
out-of-scope, or when a canonical existing ancestor escapes through a symlink,
reparse point or traversal. A digest, package identity, observation, evidence,
path spelling or successful prior call never grants authority.

Malformed encodings, embedded NUL and invalid numeric inputs retain their
existing typed invalid-input/limit behavior. They are not normalized into
`NOT_FOUND`, and malformed input cannot trigger an existence oracle.

## 6. Parity and race boundary

Evaluator and native execution SHALL produce the same success bytes or stable
error code for the same program, policy, target profile and filesystem state.
The containment proof is recomputed at the effect boundary; it is not cached as
authority across calls. This release does not claim to eliminate filesystem
races beyond the existing A86 hosted profile.

## 7. Required causal matrix

The A92 gate includes at least:

1. admitted existing root plus missing final child -> `NOT_FOUND` in both;
2. admitted existing root plus missing intermediate path -> `NOT_FOUND` in both;
3. no grant, stale generation and lexically outside root -> `DENIED` in both;
4. existing symlink/reparse ancestor escaping the root -> `DENIED` in both;
5. existing contained readable child -> identical bytes in both;
6. absent write target under an existing admitted parent -> existing bounded
   write behavior in both;
7. malformed path and limit boundaries -> identical typed failures;
8. Wave/Wire/package outputs for unchanged programs -> byte/identity compatible.

Every discovered divergence is classified before repair. A application subsystem-specific
workaround cannot satisfy this Core gate.

## 8. Representation and compatibility fence

A92 retains Wave20/OMC20, ONME2, OSM2, OSMI2 and OCAP1. No writer version,
header, opcode, manifest or ABI bump is permitted for this repair. Existing
source needs no migration. The only intended observable correction is native
`DENIED` becoming the already-specified `NOT_FOUND` for an authorized absent
target.

## 9. Deferred work

Runtime stress, resource exhaustion and concurrency hardening belong to A93.
Systemic durability belongs to A94. The downstream application consumes certified Core
behavior but cannot certify or redefine this contract.
