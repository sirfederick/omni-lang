<!--
SPDX-FileCopyrightText: 2026 Federico T. Begna
SPDX-License-Identifier: MIT OR Apache-2.0
-->

# Implementation surface reference

Observed by executing `omni --help`, `omni capability registry` and `omni context --target linux-x86_64-gnu --for llm` on the current build; all three returned zero. This verifies discovery/export only. It does not verify execution of each listed operation. No runtime authority is granted by the registry or the context export.

The [capability evidence index](CAPABILITY_STATUS.md) records exercised behavior. Specifications and tests determine the semantics; command availability alone is not a functional PASS.

## CLI discovery

The following actual help lines enumerate the available CLI surfaces. Historical profile wording in the compiler help does not ship a separate application profile in this distribution.

```text
Omni Language 0.1.0.00 (general-purpose alpha)
  omni host-policy verify POLICY.ohp
  omni host-policy allows POLICY.ohp CAPABILITY SUBJECT BYTES TICK GENERATION
  omni package check|lock PACKAGE_ROOT [--offline]
  omni sdk doctor
  omni lsp --workspace DIRECTORY
  omni check FILE [--deny-excess-capabilities] [--diagnostic-format text|json] [--bindings-json]
  omni admit FILE    (static hypothetical snapshot: YES/NO, no execution or persistent output)
  omni fmt FILE [--check|--write]
  omni deps FILE
  omni manifest FILE
  omni hash FILE
  omni wave FILE
  omni inspect FILE
  omni onme FILE [-o FILE.onme]
  omni onme-stats FILE
  omni memory FILE
  omni memory-pack FILE -o FILE.omem
  omni memory-summary FILE.omem
  omni memory-query FILE.omem --entity NAME|--capability CAP|--kind KIND|--calls FUNCTION
  omni memory-trace FILE.omem --entity NAME [--depth N]
  omni memory-impact FILE.omem --entity NAME
  omni memory-pulse CURRENT.omem --against PREVIOUS.omem
  omni proposal FILE.omem --entity NAME --agent ID --note TEXT -o FILE.oprop
  omni proposal-apply FILE.omem --proposal FILE.oprop --grant memory.write -o NEXT.omem
  omni proposal-merge FILE.omem --proposal A.oprop --proposal B.oprop [...] --grant memory.write -o NEXT.omem
  omni observe FILE [-o SNAPSHOT.omem] [--against PREVIOUS.omem]
  omni graph FILE
  omni summary FILE
  omni trace FILE --entity NAME [--depth N]
  omni impact FILE --entity NAME
  omni pulse FILE [--against PREVIOUS]
  omni query FILE --entity NAME|--capability CAP|--kind KIND|--calls FUNCTION
  omni cognition FILE [--selector ENTITY|system]
  omni synapse-scale FILE --entity ARCHETYPE --instances N [--overrides N]
  omni cognition-offload FILE [--selector ENTITY|system] --provider ID --grant external.egress --max-input-tokens N --max-output-tokens N --max-cost-microunits N --max-latency-ms N -o REQUEST.ocap
  omni cognition-offload-run REQUEST.ocap
  omni pack FILE -o FILE.owire
  omni unpack FILE.owire
  omni emit-llvm FILE [-o FILE.ll]
  omni eval FILE [--host-policy POLICY.ohp]
  omni test FILE
  omni profile FILE [-o REPORT.json] [--host-policy POLICY.ohp]
  omni coverage FILE [-o REPORT.json] [--host-policy POLICY.ohp]
  omni build FILE -o EXECUTABLE [--opt 0|2] [--force] [--no-cache] [--cache-dir DIR]     (ordinary executable build; FILE needs main)
  omni build PACKAGE_ROOT --host-entry MODULE:FUNCTION -o ARTIFACT.so --offline           (host-entry build; loadable module, no main)
  omni run FILE [--opt 0|2] [--no-cache] [--cache-dir DIR] [--host-policy POLICY.ohp]
  omni cache stats|clear [--cache-dir DIR]
  omni type describe TYPE
  omni type layout TYPE
  omni doctor [--json]
  omni target list|probe --json
  omni context --target TARGET --for llm [--target-isa gpr|sse2]
  omni component FILE [--target-profile PROFILE] [--target-isa gpr|sse2] [--diagnostic-format text|json]
Input: .omni / .owave / .owire / .onme. OSNMF and ONME are Core representations; cognition is optional.
Native target currently tested: Linux x86-64 + Clang. ECU remains a separate frozen profile.
```

## Capability registry

The following are effect/authority identifiers, not a count of language features. Category and scope are exported compiler facts; target operations still require the correct profile and runtime grants.

| Identifier | Area | Scope | Risk | Verification |
| --- | --- | --- | --- | --- |
| `cpu.control` | target-cpu | privileged-op-set | critical | Export observed; behavior evidence is separate |
| `cpu.syscall` | target-cpu | service-gate | high | Export observed; behavior evidence is separate |
| `data.read` | data | resource-scope | high | Export observed; behavior evidence is separate |
| `data.write` | data | resource-scope | high | Export observed; behavior evidence is separate |
| `external.egress` | egress | destination-set | critical | Export observed; behavior evidence is separate |
| `ffi.call` | foreign | library-set | critical | Export observed; behavior evidence is separate |
| `fs.read` | filesystem | path-set | medium | Export observed; behavior evidence is separate |
| `fs.write` | filesystem | path-set | high | Export observed; behavior evidence is separate |
| `io.print` | io | none | low | Export observed; behavior evidence is separate |
| `memory.atomic` | target-memory | address-range | critical | Export observed; behavior evidence is separate |
| `memory.pcpu` | target-memory | cpu-block | high | Export observed; behavior evidence is separate |
| `memory.raw` | target-memory | address-range | critical | Export observed; behavior evidence is separate |
| `memory.read` | memory | resource-scope | medium | Export observed; behavior evidence is separate |
| `memory.tls` | target-memory | thread-block | high | Export observed; behavior evidence is separate |
| `memory.write` | memory | resource-scope | high | Export observed; behavior evidence is separate |
| `net.connect` | network | endpoint-set | high | Export observed; behavior evidence is separate |
| `net.listen` | network | endpoint-set | critical | Export observed; behavior evidence is separate |
| `port.io` | target-io | port-set | critical | Export observed; behavior evidence is separate |
| `process.spawn` | process | executable-set | critical | Export observed; behavior evidence is separate |
| `secret.use` | secret | secret-set | critical | Export observed; behavior evidence is separate |

## Intrinsic / interface contract families

These are the actual contract references exported by the compiler. They do not claim every intrinsic was run.

| Family | Contract | Verification |
| --- | --- | --- |
| target | [spec/TARGET_INTROSPECTION_CANDIDATE.md](../../spec/TARGET_INTROSPECTION_CANDIDATE.md) | Exported with content hash; execution/adoption status in [spec index](../../spec/INDEX.md) |
| bit | [spec/BIT_INTRINSICS_CANDIDATE.md](../../spec/BIT_INTRINSICS_CANDIDATE.md) | Exported with content hash; execution/adoption status in [spec index](../../spec/INDEX.md) |
| raw,port,cpu | [spec/RAW_BOUNDARY_CANDIDATE.md](../../spec/RAW_BOUNDARY_CANDIDATE.md) | Exported with content hash; execution/adoption status in [spec index](../../spec/INDEX.md) |
| address | [spec/ADDRESS_DOMAINS_CANDIDATE.md](../../spec/ADDRESS_DOMAINS_CANDIDATE.md) | Exported with content hash; execution/adoption status in [spec index](../../spec/INDEX.md) |
| layout | [spec/NATIVE_LAYOUT_CANDIDATE.md](../../spec/NATIVE_LAYOUT_CANDIDATE.md) | Exported with content hash; execution/adoption status in [spec index](../../spec/INDEX.md) |
| C ABI | [spec/LINKAGE_ABI_CANDIDATE.md](../../spec/LINKAGE_ABI_CANDIDATE.md) | Exported with content hash; execution/adoption status in [spec index](../../spec/INDEX.md) |
| cpu state | [spec/FPU_SSE_STATE_CANDIDATE.md](../../spec/FPU_SSE_STATE_CANDIDATE.md) | Exported with content hash; execution/adoption status in [spec index](../../spec/INDEX.md) |
| simd | [spec/SIMD_BASELINE_CANDIDATE.md](../../spec/SIMD_BASELINE_CANDIDATE.md) | Exported with content hash; execution/adoption status in [spec index](../../spec/INDEX.md) |
| atomic | [spec/ATOMICS_CANDIDATE_ST09.md](../../spec/ATOMICS_CANDIDATE_ST09.md) | Exported with content hash; execution/adoption status in [spec index](../../spec/INDEX.md) |
| memory model | [spec/MEMORY_MODEL_X86_64_CANDIDATE.md](../../spec/MEMORY_MODEL_X86_64_CANDIDATE.md) | Exported with content hash; execution/adoption status in [spec index](../../spec/INDEX.md) |
| tls,pcpu | [spec/TLS_AND_PERCPU_CANDIDATE.md](../../spec/TLS_AND_PERCPU_CANDIDATE.md) | Exported with content hash; execution/adoption status in [spec index](../../spec/INDEX.md) |
| ownership | [spec/MEMORY_AUTHORITY_0_8.md](../../spec/MEMORY_AUTHORITY_0_8.md) | Exported with content hash; execution/adoption status in [spec index](../../spec/INDEX.md) |
| host invocation | [spec/HOST_INVOCATION_ABI_1_1.md](../../spec/HOST_INVOCATION_ABI_1_1.md) | Exported with content hash; execution/adoption status in [spec index](../../spec/INDEX.md) |
| host SDK | [spec/HOST_SDK_1_2.md](../../spec/HOST_SDK_1_2.md) | Exported with content hash; execution/adoption status in [spec index](../../spec/INDEX.md) |

## Explicitly prohibited or deferred by the current context

- AVX assumptions
- C++ ABI
- varargs
- arbitrary inline asm
- general SIMD shuffles

These are exclusions, not an approved future release commitment.
