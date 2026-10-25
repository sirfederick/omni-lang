<!--
SPDX-FileCopyrightText: 2026 Federico T. Begna
SPDX-License-Identifier: MIT OR Apache-2.0
-->

# Capability status and reproducible evidence

Product: **0.1.0.00 WIP / NOT_RELEASED**. Implementation and verification are separate facts. Implemented means a concrete implementation exists; implemented subset states a bounded surface; proposed denotes design without an adopted implementation claim. Not executed in this revision does not mean absent.

Examples below use Linux x86-64/Ubuntu WSL. Start at [README](../../README.md#capabilities-and-evidence) or [DEVELOPMENT](../../DEVELOPMENT.md). Reproduce a group from the root with `python3 -B tools/omni_dev.py test --group GROUP`; add `--allow-slow-fs` before `test` for a mounted WSL checkout. [MATRIX](../../tests/MATRIX.json) discovers suites. Example tests compare explicit output and exit oracles in evaluator/native paths, including intentional nonzero results.

Accepted compatibility/projection, package, application and independent-SDK evidence is reused where unchanged. Current acceptance uses `bash tools/ci.sh`; this is not a claim of a fresh complete historical matrix. Generated execution evidence belongs in ignored `build/`. [Specification status](../../spec/INDEX.md) describes authority and candidate adoption independently of runtime verification.

## Functions and flow

| Field | Scope |
| --- | --- |
| Use | Compute typed recursive functions and branch on values. |
| Implementation | Implemented |
| Verification | First-use evaluator/native oracles |
| Implementation entry | [compiler/src/particle.cpp](../../compiler/src/particle.cpp), [compiler/src/check.cpp](../../compiler/src/check.cpp) |
| Example | [examples/hola.omni](../../examples/hola.omni) |
| Test / command | `python3 -B tools/omni_dev.py test --group cli` |
| Limits | Examples do not certify all recursion/budget bounds. |
| Contract | [LANGUAGE_0_2.md](../../spec/LANGUAGE_0_2.md) |

## Numeric types and conversions

| Field | Scope |
| --- | --- |
| Use | Use fixed-width integers, checked casts, wrapping/saturating arithmetic and f32/f64. |
| Implementation | Implemented |
| Verification | Numeric/float examples in evaluator and native execution |
| Implementation entry | [compiler/src/check.cpp](../../compiler/src/check.cpp), [compiler/src/llvm.cpp](../../compiler/src/llvm.cpp) |
| Example | [examples/numeric.omni](../../examples/numeric.omni), [examples/floats.omni](../../examples/floats.omni) |
| Test / command | `python3 -B tools/omni_dev.py test --group capabilities` |
| Limits | Not a full IEEE/NaN/differential campaign; floats intentionally returns 7. |
| Contract | [DATA_LANGUAGE_0_8_1.md](../../spec/DATA_LANGUAGE_0_8_1.md) |

## Records tuples and arrays

| Field | Scope |
| --- | --- |
| Use | Represent checked records, heterogeneous tuples and fixed-size arrays. |
| Implementation | Implemented subset |
| Verification | Product example evaluator/native oracles |
| Implementation entry | [compiler/src/check.cpp](../../compiler/src/check.cpp), [compiler/src/particle.cpp](../../compiler/src/particle.cpp) |
| Example | [examples/product_types.omni](../../examples/product_types.omni), [record example](../../examples/result_minimo.omni) |
| Test / command | `python3 -B tools/omni_dev.py test --group cli --group capabilities` |
| Limits | Owning aggregates have additional move/cleanup restrictions. |
| Contract | [PRODUCT_TYPES_LAYOUT_0_2.md](../../spec/PRODUCT_TYPES_LAYOUT_0_2.md) |

## Option Result enums and matching

| Field | Scope |
| --- | --- |
| Use | Handle missing/error alternatives, including an Err branch that continues execution. |
| Implementation | Implemented |
| Verification | First-use and Option/enum example oracles |
| Implementation entry | [compiler/src/check.cpp](../../compiler/src/check.cpp), [compiler/src/particle.cpp](../../compiler/src/particle.cpp) |
| Example | [examples/result_minimo.omni](../../examples/result_minimo.omni), [examples/option.omni](../../examples/option.omni), [examples/adt_enum.omni](../../examples/adt_enum.omni) |
| Test / command | `python3 -B tools/omni_dev.py test --group cli --group capabilities` |
| Limits | Closed variants and checked payload restrictions apply. |
| Contract | [ADTS_0_2.md](../../spec/ADTS_0_2.md) |

## Generics and traits

| Field | Scope |
| --- | --- |
| Use | Specialize explicit type arguments and statically checked trait implementations. |
| Implementation | Implemented static subset |
| Verification | Generic example evaluator/native; broader trait methods not rerun here |
| Implementation entry | [compiler/src/check.cpp](../../compiler/src/check.cpp), [compiler/src/particle.cpp](../../compiler/src/particle.cpp) |
| Example | [examples/generics_iteration.omni](../../examples/generics_iteration.omni) |
| Test / command | `python3 -B tools/omni_dev.py test --group capabilities` |
| Limits | Example covers generic constraints/UFCS, not every trait method or dynamic dispatch. |
| Contract | [GENERICS_ABSTRACTION_0_2.md](../../spec/GENERICS_ABSTRACTION_0_2.md) |

## Ownership loans views and resources

| Field | Scope |
| --- | --- |
| Use | Borrow a buffer exclusively, release it and inspect bounded read-only views. |
| Implementation | Implemented subset |
| Verification | Borrow/view examples evaluator/native; broader owning containers separate |
| Implementation entry | [compiler/src/check.cpp](../../compiler/src/check.cpp), [runtime/omni_runtime.c](../../runtime/omni_runtime.c) |
| Example | [examples/borrow_mut.omni](../../examples/borrow_mut.omni), [examples/borrowed_views.omni](../../examples/borrowed_views.omni) |
| Test / command | `python3 -B tools/omni_dev.py test --group capabilities` |
| Limits | Examples intentionally return 8 and 50; no whole-family ownership certification. |
| Contract | [MEMORY_AUTHORITY_0_8.md](../../spec/MEMORY_AUTHORITY_0_8.md) |

## Effects and capabilities

| Field | Scope |
| --- | --- |
| Use | Declare required effects and reject I/O in a pure function before execution. |
| Implementation | Implemented |
| Verification | Positive evaluator/native and semantic E_CAPABILITY rejection |
| Implementation entry | [compiler/src/capabilities.cpp](../../compiler/src/capabilities.cpp), [compiler/src/check.cpp](../../compiler/src/check.cpp) |
| Example | [tests/fixtures/dx/io_allowed.omni](../../tests/fixtures/dx/io_allowed.omni), [tests/fixtures/dx/pure_io_denied.omni](../../tests/fixtures/dx/pure_io_denied.omni) |
| Test / command | `python3 -B tools/omni_dev.py test --group cli` |
| Limits | Static capability declarations do not provide runtime grants or a security sandbox. |
| Contract | [OCAP_0_7.md](../../spec/OCAP_0_7.md) |

## Unicode text and iteration

| Field | Scope |
| --- | --- |
| Use | Distinguish UTF-8 byte/scalar counts and iterate bounded ranges/views. |
| Implementation | Implemented subset |
| Verification | Unicode/range examples evaluator/native |
| Implementation entry | [compiler/src/check.cpp](../../compiler/src/check.cpp), [compiler/src/llvm.cpp](../../compiler/src/llvm.cpp) |
| Example | [examples/unicode_text.omni](../../examples/unicode_text.omni), [examples/ranges.omni](../../examples/ranges.omni) |
| Test / command | `python3 -B tools/omni_dev.py test --group capabilities` |
| Limits | Examples return 3 and 22; full Unicode/differential suites remain separate. |
| Contract | [UNICODE_TEXT_0_8_1.md](../../spec/UNICODE_TEXT_0_8_1.md) |

## Tasks and concurrency

| Field | Scope |
| --- | --- |
| Use | Spawn/join scoped tasks and persist recovery generations. |
| Implementation | Implemented bounded subset |
| Verification | Existing native application evidence; full concurrency suite not rerun here |
| Implementation entry | [compiler/src/check.cpp](../../compiler/src/check.cpp), [compiler/src/llvm.cpp](../../compiler/src/llvm.cpp), [runtime/omni_runtime.c](../../runtime/omni_runtime.c) |
| Example | [examples/applications/recovery-service/src/main.omni](../../examples/applications/recovery-service/src/main.omni) |
| Test / command | `python3 -B tools/run_app_examples.py` (prepares file placeholders and OHP1 policy) |
| Limits | Requires prepared files/OHP1 policy; not general async or distributed exactly-once. |
| Contract | [CONCURRENCY_0_8_5.md](../../spec/CONCURRENCY_0_8_5.md) |

## Files and permissions

| Field | Scope |
| --- | --- |
| Use | Read bounded input and write checked output under explicit filesystem grants. |
| Implementation | Implemented hosted subset |
| Verification | Existing exact-output native application evidence |
| Implementation entry | [compiler/src/host_policy.cpp](../../compiler/src/host_policy.cpp), [runtime/omni_runtime.c](../../runtime/omni_runtime.c) |
| Example | [examples/applications/data-cli/src/main.omni](../../examples/applications/data-cli/src/main.omni) |
| Test / command | `python3 -B tools/run_app_examples.py` (prepares file placeholders and OHP1 policy) |
| Limits | The fixture needs OHP1 setup; no ambient authorization or provider-security claim. |
| Contract | [HOSTED_EFFECTS_FFI_0_8_6.md](../../spec/HOSTED_EFFECTS_FFI_0_8_6.md) |

## Modules packages and stdlib

| Field | Scope |
| --- | --- |
| Use | Resolve declared imports/dependencies and generate/check offline locks. |
| Implementation | Implemented offline subset |
| Verification | Package evidence and real extracted-SDK stdlib consumption |
| Implementation entry | [compiler/src/modules.cpp](../../compiler/src/modules.cpp), [compiler/src/packages.cpp](../../compiler/src/packages.cpp) |
| Example | [examples/a84_package_consumer/src/main.omni](../../examples/a84_package_consumer/src/main.omni) |
| Test / command | `python3 -B tools/omni_dev.py test --group packages13` |
| Limits | No published registry; omni.std has an independent package version. |
| Contract | [PACKAGES_STDLIB_0_8_4.md](../../spec/PACKAGES_STDLIB_0_8_4.md) |

## Evaluator and native compilation

| Field | Scope |
| --- | --- |
| Use | Evaluate checked programs or emit LLVM IR and build with Clang and the C runtime. |
| Implementation | Implemented Linux profile |
| Verification | Exact first-use evaluator/native output and exit oracles |
| Implementation entry | [compiler/src/check.cpp](../../compiler/src/check.cpp), [compiler/src/llvm.cpp](../../compiler/src/llvm.cpp), [compiler/src/main.cpp](../../compiler/src/main.cpp) |
| Example | [examples/hola.omni](../../examples/hola.omni) |
| Test / command | `python3 -B tools/omni_dev.py test --group cli` |
| Limits | Linux x86-64 exercised; Windows commands bridge to WSL. |
| Contract | [TARGET_PROFILES_0_8_8.md](../../spec/TARGET_PROFILES_0_8_8.md) |

## Wave Wire ONME and OSNMF

| Field | Scope |
| --- | --- |
| Use | Read/write structured programs and project/query semantic identities and memory. |
| Implementation | Implemented versioned surfaces |
| Verification | Accepted projection/compatibility evidence retained; not rerun wholesale here |
| Implementation entry | [compiler/src/formats.cpp](../../compiler/src/formats.cpp), [compiler/src/onme.cpp](../../compiler/src/onme.cpp), [compiler/src/osnmf.cpp](../../compiler/src/osnmf.cpp) |
| Example | [examples/hola.owave](../../examples/hola.owave), [examples/hola.omni](../../examples/hola.omni) |
| Test / command | `python3 -B tools/omni_dev.py test --group projection13` |
| Limits | ONME is not an ISA; identity does not grant authority; native compilation need not traverse every projection. |
| Contract | [IR_WAVE_WIRE_0_2.md](../../spec/IR_WAVE_WIRE_0_2.md) |

## C Node and Python SDK

| Field | Scope |
| --- | --- |
| Use | Embed admitted host entries and exchange values through the public ABI and codecs. |
| Implementation | Implemented bounded ABI and codecs |
| Verification | C invokes; Node/Python encode and decode a real runtime response |
| Implementation entry | [compiler/src/host_sdk_public.cpp](../../compiler/src/host_sdk_public.cpp), [compiler/src/host_invocation_loader.cpp](../../compiler/src/host_invocation_loader.cpp), [include/omni/omni_host_sdk_v1.h](../../include/omni/omni_host_sdk_v1.h) |
| Example | [examples/host-sdk/consumer.c](../../examples/host-sdk/consumer.c), [examples/host-sdk/consumer.mjs](../../examples/host-sdk/consumer.mjs), [examples/host-sdk/consumer.py](../../examples/host-sdk/consumer.py) |
| Test / command | `python3 -B tools/run_sdk_examples.py --output build/sdk-catalog-example`; [full SDK smoke](../../tools/run_sdk_smoke.py) needs a fresh output |
| Limits | Node/Python do not expose arbitrary direct invocation; OMI1 admits only its declared type subset. |
| Contract | [HOST_SDK_1_2.md](../../spec/HOST_SDK_1_2.md) |

## Development tools

| Field | Scope |
| --- | --- |
| Use | Check/format code, inspect diagnostics, export context and use the existing LSP implementation. |
| Implementation | Implemented subset |
| Verification | Tooling regressions; full LSP/admission suites not rerun here |
| Implementation entry | [tools/omni_dev.py](../../tools/omni_dev.py), [tools/omni_lsp.py](../../tools/omni_lsp.py), [tools/run_test_matrix.py](../../tools/run_test_matrix.py) |
| Example | [docs/language/IMPLEMENTATION_SURFACE.md](../../docs/language/IMPLEMENTATION_SURFACE.md) |
| Test / command | `python3 -B tools/omni_dev.py test --group tooling` |
| Limits | Discovery/export is not proof of every command or complete editor support. |
| Contract | [CP16_TOOLING_CANDIDATE.md](../../spec/CP16_TOOLING_CANDIDATE.md) |

## SIMD

| Field | Scope |
| --- | --- |
| Use | Use supported 128-bit lane records and masks with explicit profile fences. |
| Implementation | Implemented target-bound subset |
| Verification | Not executed in this revision; dedicated tests indexed |
| Implementation entry | [compiler/src/check.cpp](../../compiler/src/check.cpp), [compiler/src/llvm.cpp](../../compiler/src/llvm.cpp) |
| Example | [examples/storage/simd.omni](../../examples/storage/simd.omni) |
| Test / command | `python3 -B tools/omni_dev.py test --group cpustate13` |
| Limits | No AVX, wide vectors, shuffle or autovectorization guarantee; baremetal SSE2 needs its ISA profile and emulator prerequisites. |
| Contract | [SIMD_BASELINE_CANDIDATE.md](../../spec/SIMD_BASELINE_CANDIDATE.md) |

## Dynamic storage

| Field | Scope |
| --- | --- |
| Use | Build resource-based heaps, arenas, vectors and related containers. |
| Implementation | Implemented library subset |
| Verification | Not executed in this revision; dedicated tests indexed |
| Implementation entry | [examples/storage/heap.omni](../../examples/storage/heap.omni), [examples/storage/seq.omni](../../examples/storage/seq.omni), [runtime/omni_runtime.c](../../runtime/omni_runtime.c) |
| Example | [examples/storage/vec.omni](../../examples/storage/vec.omni) |
| Test / command | `python3 -B tools/omni_dev.py test --group storage13` |
| Limits | Allocator, lifetime and cleanup contracts apply; no unrestricted GC heap claim. |
| Contract | [DYNAMIC_STORAGE_CANDIDATE.md](../../spec/DYNAMIC_STORAGE_CANDIDATE.md) |

## Hardware profiles

| Field | Scope |
| --- | --- |
| Use | Express checked raw-memory, layout, CPU and port operations in explicit freestanding profiles. |
| Implementation | Implemented experimental subsets |
| Verification | Not executed in this revision; target/QEMU suites indexed |
| Implementation entry | [compiler/src/check.cpp](../../compiler/src/check.cpp), [compiler/src/llvm.cpp](../../compiler/src/llvm.cpp) |
| Example | [tests/x64/README.md](../../tests/x64/README.md) |
| Test / command | `python3 -B tools/omni_dev.py test --group freestanding13` |
| Limits | Not physical-hardware or universal-platform certification; i386 bootstrap is not general C ABI. |
| Contract | [TARGET_BAREMETAL_PROFILE_CANDIDATE.md](../../spec/TARGET_BAREMETAL_PROFILE_CANDIDATE.md) |

## Candidate extensions and adoption status

The complete [specification index](../../spec/INDEX.md) includes every retained contract. These candidate rows may already have implemented subsets; they are not automatically future features or accepted roadmap commitments. Names, scope and caveats come from their documents. Founder/DT adoption remains pending where not explicitly established.

| Area | Candidate contract | Implementation / example / test references | Status |
| --- | --- | --- | --- |
| Language / memory | [ADDRESS_DOMAINS_CANDIDATE.md](../../spec/ADDRESS_DOMAINS_CANDIDATE.md) | [examples/storage/addr.omni](../../examples/storage/addr.omni), [tests/cp07_address_domains.py](../../tests/cp07_address_domains.py), [tests/cp07_casts.py](../../tests/cp07_casts.py) | DESIGN_CANDIDATE / uncertified; inspect implementation and target limits before advertising |
| Language / memory | [AGGREGATE_MOVE_CANDIDATE.md](../../spec/AGGREGATE_MOVE_CANDIDATE.md) | [tests/language_0_8_3_alpha8.py](../../tests/language_0_8_3_alpha8.py) | DESIGN_CANDIDATE / uncertified; inspect implementation and target limits before advertising |
| Runtime / target | [ATOMICS_CANDIDATE_ST09.md](../../spec/ATOMICS_CANDIDATE_ST09.md) | No executable example established for this contract; review gap | DESIGN_CANDIDATE / uncertified; inspect implementation and target limits before advertising |
| Language / memory | [BIT_INTRINSICS_CANDIDATE.md](../../spec/BIT_INTRINSICS_CANDIDATE.md) | [tests/language_0_8_3_alpha8.py](../../tests/language_0_8_3_alpha8.py) | DESIGN_CANDIDATE / uncertified; inspect implementation and target limits before advertising |
| Language / memory | [BORROW_RETURN_REGIONS_CANDIDATE.md](../../spec/BORROW_RETURN_REGIONS_CANDIDATE.md) | [tests/language_0_8_3_alpha8.py](../../tests/language_0_8_3_alpha8.py) | DESIGN_CANDIDATE / uncertified; inspect implementation and target limits before advertising |
| Language / memory | [BUFFER_TYPED_ACCESS_CANDIDATE_007.md](../../spec/BUFFER_TYPED_ACCESS_CANDIDATE_007.md) | No executable example established for this contract; review gap | DESIGN_CANDIDATE / uncertified; inspect implementation and target limits before advertising |
| Language / memory | [CALLBACK_REGISTRY_CANDIDATE.md](../../spec/CALLBACK_REGISTRY_CANDIDATE.md) | [tests/x64/cbreg.omni](../../tests/x64/cbreg.omni) | DESIGN_CANDIDATE / uncertified; inspect implementation and target limits before advertising |
| Language / memory | [CALLBACK_REGISTRY_HOSTED_CANDIDATE.md](../../spec/CALLBACK_REGISTRY_HOSTED_CANDIDATE.md) | [examples/storage/registry.omni](../../examples/storage/registry.omni) | DESIGN_CANDIDATE / uncertified; inspect implementation and target limits before advertising |
| Language / memory | [CANCELLATION_CANDIDATE.md](../../spec/CANCELLATION_CANDIDATE.md) | [examples/storage/coop.omni](../../examples/storage/coop.omni), [tests/cp03_cancellation.py](../../tests/cp03_cancellation.py) | DESIGN_CANDIDATE / uncertified; inspect implementation and target limits before advertising |
| Language / memory | [CLEANUP_FAILURE_CANDIDATE.md](../../spec/CLEANUP_FAILURE_CANDIDATE.md) | [examples/storage/seq.omni](../../examples/storage/seq.omni) | DESIGN_CANDIDATE / uncertified; inspect implementation and target limits before advertising |
| Language / memory | [COLLECTIONS_PROTOCOLS_CANDIDATE.md](../../spec/COLLECTIONS_PROTOCOLS_CANDIDATE.md) | [examples/storage/alloc.omni](../../examples/storage/alloc.omni) | DESIGN_CANDIDATE / uncertified; inspect implementation and target limits before advertising |
| Language / memory | [CORE_1_3_0_0_PUBLIC_DELTA_CANDIDATE.json](../../spec/CORE_1_3_0_0_PUBLIC_DELTA_CANDIDATE.json) | No executable example established for this contract; review gap | DESIGN_CANDIDATE / uncertified; inspect implementation and target limits before advertising |
| SDK / tools | [CP16_TOOLING_CANDIDATE.md](../../spec/CP16_TOOLING_CANDIDATE.md) | No executable example established for this contract; review gap | DESIGN_CANDIDATE / uncertified; inspect implementation and target limits before advertising |
| SDK / tools | [CP17_SDK_INTEGRATION_CANDIDATE.md](../../spec/CP17_SDK_INTEGRATION_CANDIDATE.md) | No executable example established for this contract; review gap | DESIGN_CANDIDATE / uncertified; inspect implementation and target limits before advertising |
| Language / memory | [CROSS_MODULE_TRAITS_CANDIDATE.md](../../spec/CROSS_MODULE_TRAITS_CANDIDATE.md) | [tests/language_0_8_3_alpha8.py](../../tests/language_0_8_3_alpha8.py) | DESIGN_CANDIDATE / uncertified; inspect implementation and target limits before advertising |
| Language / memory | [DIAGNOSTIC_RELATED_LOCATIONS_CANDIDATE.md](../../spec/DIAGNOSTIC_RELATED_LOCATIONS_CANDIDATE.md) | [tests/language_0_8_3_alpha8.py](../../tests/language_0_8_3_alpha8.py), [tests/language_0_8_7_alpha8.py](../../tests/language_0_8_7_alpha8.py) | DESIGN_CANDIDATE / uncertified; inspect implementation and target limits before advertising |
| Language / memory | [DYNAMIC_STORAGE_CANDIDATE.md](../../spec/DYNAMIC_STORAGE_CANDIDATE.md) | [examples/storage/arena.omni](../../examples/storage/arena.omni), [examples/storage/heap.omni](../../examples/storage/heap.omni), [examples/storage/ktask.omni](../../examples/storage/ktask.omni), [examples/storage/region.omni](../../examples/storage/region.omni) | DESIGN_CANDIDATE / uncertified; inspect implementation and target limits before advertising |
| Language / memory | [ENDIAN_UNALIGNED_CANDIDATE.md](../../spec/ENDIAN_UNALIGNED_CANDIDATE.md) | [examples/storage/endian.omni](../../examples/storage/endian.omni), [tests/cp07_endian.py](../../tests/cp07_endian.py) | DESIGN_CANDIDATE / uncertified; inspect implementation and target limits before advertising |
| Runtime / target | [ENTER_RING3_INTERRUPTIBLE_CANDIDATE.md](../../spec/ENTER_RING3_INTERRUPTIBLE_CANDIDATE.md) | [tests/language_1_3_hardware_primitives.py](../../tests/language_1_3_hardware_primitives.py) | DESIGN_CANDIDATE / uncertified; inspect implementation and target limits before advertising |
| Runtime / target | [FPU_SSE_STATE_CANDIDATE.md](../../spec/FPU_SSE_STATE_CANDIDATE.md) | [examples/storage/cpustate.omni](../../examples/storage/cpustate.omni), [tests/cp10_state.py](../../tests/cp10_state.py), [tests/cp12_frames.py](../../tests/cp12_frames.py), [tests/cp12_stacks.py](../../tests/cp12_stacks.py) | DESIGN_CANDIDATE / uncertified; inspect implementation and target limits before advertising |
| Representations / identity | [GENERATED_PROVENANCE_CANDIDATE.md](../../spec/GENERATED_PROVENANCE_CANDIDATE.md) | No executable example established for this contract; review gap | DESIGN_CANDIDATE / uncertified; inspect implementation and target limits before advertising |
| Language / memory | [GENERIC_RESOURCE_CANDIDATE.md](../../spec/GENERIC_RESOURCE_CANDIDATE.md) | [tests/cp01_generic_resources.py](../../tests/cp01_generic_resources.py) | DESIGN_CANDIDATE / uncertified; inspect implementation and target limits before advertising |
| Language / memory | [GENERIC_STRUCT_CANDIDATE.md](../../spec/GENERIC_STRUCT_CANDIDATE.md) | [tests/language_0_8_3_alpha8.py](../../tests/language_0_8_3_alpha8.py) | DESIGN_CANDIDATE / uncertified; inspect implementation and target limits before advertising |
| Runtime / target | [GUARDS_AND_LOCKS_CANDIDATE.md](../../spec/GUARDS_AND_LOCKS_CANDIDATE.md) | [examples/storage/critical.omni](../../examples/storage/critical.omni), [tests/cp14_sections.py](../../tests/cp14_sections.py), [tests/language_0_8_3_alpha8.py](../../tests/language_0_8_3_alpha8.py), [tests/x64/irq.omni](../../tests/x64/irq.omni) | DESIGN_CANDIDATE / uncertified; inspect implementation and target limits before advertising |
| Representations / identity | [HARDWARE_REPRESENTATION_FENCE_CANDIDATE.md](../../spec/HARDWARE_REPRESENTATION_FENCE_CANDIDATE.md) | [tests/language_0_8_3_alpha8.py](../../tests/language_0_8_3_alpha8.py) | DESIGN_CANDIDATE / uncertified; inspect implementation and target limits before advertising |
| Language / memory | [INDEPENDENT_ADOPTION_0_9_8.md](../../spec/INDEPENDENT_ADOPTION_0_9_8.md) | No executable example established for this contract; review gap | DESIGN_CANDIDATE / uncertified; inspect implementation and target limits before advertising |
| Language / memory | [LINKAGE_ABI_CANDIDATE.md](../../spec/LINKAGE_ABI_CANDIDATE.md) | [tests/cp09_freestanding.py](../../tests/cp09_freestanding.py), [tests/cp09_linkage.py](../../tests/cp09_linkage.py) | DESIGN_CANDIDATE / uncertified; inspect implementation and target limits before advertising |
| Runtime / target | [MEMORY_MODEL_X86_64_CANDIDATE.md](../../spec/MEMORY_MODEL_X86_64_CANDIDATE.md) | [examples/storage/mailbox.omni](../../examples/storage/mailbox.omni), [tests/cp13_memory_model.py](../../tests/cp13_memory_model.py) | DESIGN_CANDIDATE / uncertified; inspect implementation and target limits before advertising |
| Runtime / target | [MMIO_PORTS_CANDIDATE.md](../../spec/MMIO_PORTS_CANDIDATE.md) | [examples/storage/mmio.omni](../../examples/storage/mmio.omni), [tests/cp08_dma.py](../../tests/cp08_dma.py), [tests/cp08_mmio.py](../../tests/cp08_mmio.py) | DESIGN_CANDIDATE / uncertified; inspect implementation and target limits before advertising |
| Language / memory | [NATIVE_LAYOUT_CANDIDATE.md](../../spec/NATIVE_LAYOUT_CANDIDATE.md) | [tests/language_0_8_3_alpha8.py](../../tests/language_0_8_3_alpha8.py) | DESIGN_CANDIDATE / uncertified; inspect implementation and target limits before advertising |
| Runtime / target | [NO_MIGRATION_CANDIDATE.md](../../spec/NO_MIGRATION_CANDIDATE.md) | [tests/language_0_8_3_alpha8.py](../../tests/language_0_8_3_alpha8.py), [tests/x64/pin.omni](../../tests/x64/pin.omni), [tests/x64/pin_migrate.omni](../../tests/x64/pin_migrate.omni) | DESIGN_CANDIDATE / uncertified; inspect implementation and target limits before advertising |
| Language / memory | [NOMINAL_AFFINE_RESOURCE_CANDIDATE.md](../../spec/NOMINAL_AFFINE_RESOURCE_CANDIDATE.md) | No executable example established for this contract; review gap | DESIGN_CANDIDATE / uncertified; inspect implementation and target limits before advertising |
| Language / memory | [NOMINAL_BUFFER_RESOURCE_CANDIDATE.md](../../spec/NOMINAL_BUFFER_RESOURCE_CANDIDATE.md) | [examples/storage/region.omni](../../examples/storage/region.omni), [examples/storage/vec.omni](../../examples/storage/vec.omni), [tests/cp02_borrowed_containers.py](../../tests/cp02_borrowed_containers.py) | DESIGN_CANDIDATE / uncertified; inspect implementation and target limits before advertising |
| Language / memory | [OPTION_RESOURCE_CANDIDATE.md](../../spec/OPTION_RESOURCE_CANDIDATE.md) | [tests/language_0_8_3_alpha8.py](../../tests/language_0_8_3_alpha8.py) | DESIGN_CANDIDATE / uncertified; inspect implementation and target limits before advertising |
| Language / memory | [OWNED_SLOTS_CANDIDATE.md](../../spec/OWNED_SLOTS_CANDIDATE.md) | [compiler/src/check.cpp](../../compiler/src/check.cpp), [compiler/src/formats.cpp](../../compiler/src/formats.cpp), [compiler/src/llvm.cpp](../../compiler/src/llvm.cpp), [examples/storage/seq.omni](../../examples/storage/seq.omni) | DESIGN_CANDIDATE / uncertified; inspect implementation and target limits before advertising |
| Language / memory | [OWNERSHIP_COMPOSITION_CANDIDATE.md](../../spec/OWNERSHIP_COMPOSITION_CANDIDATE.md) | [tests/language_0_8_3_alpha8.py](../../tests/language_0_8_3_alpha8.py) | DESIGN_CANDIDATE / uncertified; inspect implementation and target limits before advertising |
| Language / memory | [PACKAGE_DEPENDENCY_IMPORTS_CANDIDATE.md](../../spec/PACKAGE_DEPENDENCY_IMPORTS_CANDIDATE.md) | [tests/cp05_packages.py](../../tests/cp05_packages.py) | DESIGN_CANDIDATE / uncertified; inspect implementation and target limits before advertising |
| Runtime / target | [QUIESCENCE_CANDIDATE.md](../../spec/QUIESCENCE_CANDIDATE.md) | [tests/language_0_8_3_alpha8.py](../../tests/language_0_8_3_alpha8.py), [tests/x64/epoch.omni](../../tests/x64/epoch.omni) | DESIGN_CANDIDATE / uncertified; inspect implementation and target limits before advertising |
| Language / memory | [RAW_BOUNDARY_CANDIDATE.md](../../spec/RAW_BOUNDARY_CANDIDATE.md) | [tests/cp08_raw_boundary.py](../../tests/cp08_raw_boundary.py) | DESIGN_CANDIDATE / uncertified; inspect implementation and target limits before advertising |
| Language / memory | [REGISTER_FIELDS_CANDIDATE.md](../../spec/REGISTER_FIELDS_CANDIDATE.md) | [examples/storage/bitfield.omni](../../examples/storage/bitfield.omni), [tests/cp08_fields.py](../../tests/cp08_fields.py) | DESIGN_CANDIDATE / uncertified; inspect implementation and target limits before advertising |
| Runtime / target | [SIMD_BASELINE_CANDIDATE.md](../../spec/SIMD_BASELINE_CANDIDATE.md) | [examples/storage/simd.omni](../../examples/storage/simd.omni), [tests/cp10_simd.py](../../tests/cp10_simd.py) | DESIGN_CANDIDATE / uncertified; inspect implementation and target limits before advertising |
| Language / memory | [STATIC_ASSERT_CANDIDATE.md](../../spec/STATIC_ASSERT_CANDIDATE.md) | [tests/cp07_static_assert.py](../../tests/cp07_static_assert.py) | DESIGN_CANDIDATE / uncertified; inspect implementation and target limits before advertising |
| Language / memory | [STATIC_DATA_CANDIDATE.md](../../spec/STATIC_DATA_CANDIDATE.md) | [tests/cp07_static_data.py](../../tests/cp07_static_data.py) | DESIGN_CANDIDATE / uncertified; inspect implementation and target limits before advertising |
| Runtime / target | [TARGET_BAREMETAL_PROFILE_CANDIDATE.md](../../spec/TARGET_BAREMETAL_PROFILE_CANDIDATE.md) | [tests/cp10_simd.py](../../tests/cp10_simd.py) | DESIGN_CANDIDATE / uncertified; inspect implementation and target limits before advertising |
| Runtime / target | [TARGET_INTROSPECTION_CANDIDATE.md](../../spec/TARGET_INTROSPECTION_CANDIDATE.md) | [tests/cp07_target.py](../../tests/cp07_target.py) | DESIGN_CANDIDATE / uncertified; inspect implementation and target limits before advertising |
| Runtime / target | [THREAD_LOCAL_CANDIDATE.md](../../spec/THREAD_LOCAL_CANDIDATE.md) | [tests/language_0_8_3_alpha8.py](../../tests/language_0_8_3_alpha8.py) | DESIGN_CANDIDATE / uncertified; inspect implementation and target limits before advertising |
| Runtime / target | [TLS_AND_PERCPU_CANDIDATE.md](../../spec/TLS_AND_PERCPU_CANDIDATE.md) | [tests/language_0_8_3_alpha8.py](../../tests/language_0_8_3_alpha8.py) | DESIGN_CANDIDATE / uncertified; inspect implementation and target limits before advertising |
| Language / memory | [TRAIT_METHODS_CANDIDATE.md](../../spec/TRAIT_METHODS_CANDIDATE.md) | [tests/language_0_8_3_alpha8.py](../../tests/language_0_8_3_alpha8.py) | DESIGN_CANDIDATE / uncertified; inspect implementation and target limits before advertising |
| Language / memory | [TRY_PROPAGATION_CANDIDATE.md](../../spec/TRY_PROPAGATION_CANDIDATE.md) | [tests/language_0_8_3_alpha8.py](../../tests/language_0_8_3_alpha8.py) | DESIGN_CANDIDATE / uncertified; inspect implementation and target limits before advertising |
| Language / bounded storage | [WINDOWS_CANDIDATE.md](../../spec/WINDOWS_CANDIDATE.md) | [examples/storage/window.omni](../../examples/storage/window.omni), [tests/cp02_adversarial.py](../../tests/cp02_adversarial.py) | DESIGN_CANDIDATE / uncertified; inspect implementation and target limits before advertising |

## Documented future work, not current functionality

These are explicitly deferred clauses, not newly approved work or dates. Old deferrals can be superseded by later implemented amendments (for example dependency imports); do not infer the current backlog from an old sentence alone.

| Item | Documented boundary | Decision |
| --- | --- | --- |
| SIMD shuffles, wider vectors and AVX | [SIMD section 5](../../spec/SIMD_BASELINE_CANDIDATE.md) | Deferred design scope; no schedule approved here |
| Scoped raw block sugar | [raw boundary](../../spec/RAW_BOUNDARY_CANDIDATE.md) | Deferred syntax; existing per-function capability boundary remains |
| Pending-place assignment/reinitialization | [ownership composition](../../spec/OWNERSHIP_COMPOSITION_CANDIDATE.md) | Deferred until cleanup/replacement contract exists |
| Remote package registry and signed publishers | [packages](../../spec/PACKAGES_STDLIB_0_8_4.md) | Outside current offline profile; needs current founder/DT decision |
| General C ABI mapping / zero-copy / arbitrary symbols | [hosted effects deferred scope](../../spec/HOSTED_EFFECTS_FFI_0_8_6.md) | Not supplied by fixed copy-only host effects |
| Additional host platforms | [development](../../DEVELOPMENT.md) | NOT_VERIFIED; Linux x86-64/WSL is the exercised profile |

Adding a new capability requires a contract, an authentic example, a positive oracle, relevant rejection cases and a recorded execution profile. Missing example coverage is a gap to record, not permission to invent syntax or claim a test passed. The README summarizes this catalog; neither is a release certification.
