<!--
SPDX-FileCopyrightText: 2026 Federico T. Begna
SPDX-License-Identifier: MIT OR Apache-2.0
-->

# Executable examples and library snippets

Start with [hola.omni](hola.omni) and [result_minimo.omni](result_minimo.omni). From the project root:

```powershell
python -B tools/omni_dev.py --allow-slow-fs check examples/hola.omni
python -B tools/omni_dev.py --allow-slow-fs run examples/hola.omni
python -B tools/omni_dev.py --allow-slow-fs run examples/result_minimo.omni
```

The first prints `Hola, Omni` then `720`; the second prints `100` then `El programa continua`. Both return zero. [Quick Start](../docs/getting-started/QUICKSTART.md) explains the toolchain.

Application fixtures: `python3 -B tools/run_app_examples.py` under Linux/WSL copies packages into build/, substitutes file paths, creates explicit OHP1 read/write grants, locks packages offline and executes native programs. Data CLI checks exact output bytes; recovery runs twice and checks `generation=1` then `generation=2`. The source examples retain placeholders intentionally; they are not standalone without setup.

For SDK examples use [host-sdk](host-sdk/src/echo.omni), the [SDK guide](../docs/sdk/QUICKSTART.md), and the public C/Node/Python probes under [host_invocation_h02](../tests/host_invocation_h02/). These exercise actual artifacts; they are not language syntax examples for Node/Python.

Storage files are libraries or target-bound examples. Importing one does not demonstrate that the current host can run every hardware operation. Some require a baremetal profile and QEMU. This index enumerates source files, not a count of supported features.

See [capability status](../docs/language/CAPABILITY_STATUS.md) for specification/test navigation.

| Source | Demonstration status | Knowledge / test entry |
| --- | --- | --- |
| [a84_package_consumer/src/main.omni](a84_package_consumer/src/main.omni) | NOT_RUN individually; source admitted | [contracts](../spec/INDEX.md), [behavior suites](../tests/MATRIX.json) |
| [adt_enum.omni](adt_enum.omni) | NOT_RUN individually; source admitted | [contracts](../spec/INDEX.md), [behavior suites](../tests/MATRIX.json) |
| [applications/data-cli/src/main.omni](applications/data-cli/src/main.omni) | VERIFIED native fixture runner; paths substituted only in build/ | [contracts](../spec/INDEX.md), [behavior suites](../tests/MATRIX.json) |
| [applications/recovery-service/src/main.omni](applications/recovery-service/src/main.omni) | VERIFIED native fixture runner; paths substituted only in build/ | [contracts](../spec/INDEX.md), [behavior suites](../tests/MATRIX.json) |
| [applications/recovery-service/tests/native_multi_spawn.omni](applications/recovery-service/tests/native_multi_spawn.omni) | NOT_RUN individually; source admitted | [contracts](../spec/INDEX.md), [behavior suites](../tests/MATRIX.json) |
| [borrow_mut.omni](borrow_mut.omni) | NOT_RUN individually; source admitted | [contracts](../spec/INDEX.md), [behavior suites](../tests/MATRIX.json) |
| [borrowed_views.omni](borrowed_views.omni) | NOT_RUN individually; source admitted | [contracts](../spec/INDEX.md), [behavior suites](../tests/MATRIX.json) |
| [contratos_puros.omni](contratos_puros.omni) | NOT_RUN individually; source admitted | [contracts](../spec/INDEX.md), [behavior suites](../tests/MATRIX.json) |
| [data_control.omni](data_control.omni) | NOT_RUN individually; source admitted | [contracts](../spec/INDEX.md), [behavior suites](../tests/MATRIX.json) |
| [floats.omni](floats.omni) | NOT_RUN individually; source admitted | [contracts](../spec/INDEX.md), [behavior suites](../tests/MATRIX.json) |
| [generics_iteration.omni](generics_iteration.omni) | NOT_RUN individually; source admitted | [contracts](../spec/INDEX.md), [behavior suites](../tests/MATRIX.json) |
| [hola.canonical.omni](hola.canonical.omni) | NOT_RUN individually; source admitted | [contracts](../spec/INDEX.md), [behavior suites](../tests/MATRIX.json) |
| [hola.omni](hola.omni) | VERIFIED check/build/run; output oracle in local CLI report | [contracts](../spec/INDEX.md), [behavior suites](../tests/MATRIX.json) |
| [host-sdk/src/echo.omni](host-sdk/src/echo.omni) | NOT_RUN individually; source admitted | [contracts](../spec/INDEX.md), [behavior suites](../tests/MATRIX.json) |
| [numeric.omni](numeric.omni) | NOT_RUN individually; source admitted | [contracts](../spec/INDEX.md), [behavior suites](../tests/MATRIX.json) |
| [observaciones/main.omni](observaciones/main.omni) | NOT_RUN individually; source admitted | [contracts](../spec/INDEX.md), [behavior suites](../tests/MATRIX.json) |
| [observaciones/mediciones.omni](observaciones/mediciones.omni) | NOT_RUN individually; source admitted | [contracts](../spec/INDEX.md), [behavior suites](../tests/MATRIX.json) |
| [observaciones/resumen.omni](observaciones/resumen.omni) | NOT_RUN individually; source admitted | [contracts](../spec/INDEX.md), [behavior suites](../tests/MATRIX.json) |
| [option.omni](option.omni) | NOT_RUN individually; source admitted | [contracts](../spec/INDEX.md), [behavior suites](../tests/MATRIX.json) |
| [product_types.omni](product_types.omni) | NOT_RUN individually; source admitted | [contracts](../spec/INDEX.md), [behavior suites](../tests/MATRIX.json) |
| [ranges.omni](ranges.omni) | NOT_RUN individually; source admitted | [contracts](../spec/INDEX.md), [behavior suites](../tests/MATRIX.json) |
| [resource_buffer.omni](resource_buffer.omni) | NOT_RUN individually; source admitted | [contracts](../spec/INDEX.md), [behavior suites](../tests/MATRIX.json) |
| [result_minimo.omni](result_minimo.omni) | VERIFIED check/build/run; output oracle in local CLI report | [contracts](../spec/INDEX.md), [behavior suites](../tests/MATRIX.json) |
| [storage/addr.omni](storage/addr.omni) | Target/profile-specific library; NOT_RUN individually; not a hosted application | [contracts](../spec/INDEX.md), [behavior suites](../tests/MATRIX.json) |
| [storage/addr_access.omni](storage/addr_access.omni) | Target/profile-specific library; NOT_RUN individually; not a hosted application | [contracts](../spec/INDEX.md), [behavior suites](../tests/MATRIX.json) |
| [storage/alloc.omni](storage/alloc.omni) | Target/profile-specific library; NOT_RUN individually; not a hosted application | [contracts](../spec/INDEX.md), [behavior suites](../tests/MATRIX.json) |
| [storage/arena.omni](storage/arena.omni) | Target/profile-specific library; NOT_RUN individually; not a hosted application | [contracts](../spec/INDEX.md), [behavior suites](../tests/MATRIX.json) |
| [storage/bitfield.omni](storage/bitfield.omni) | Target/profile-specific library; NOT_RUN individually; not a hosted application | [contracts](../spec/INDEX.md), [behavior suites](../tests/MATRIX.json) |
| [storage/coop.omni](storage/coop.omni) | Target/profile-specific library; NOT_RUN individually; not a hosted application | [contracts](../spec/INDEX.md), [behavior suites](../tests/MATRIX.json) |
| [storage/cpustate.omni](storage/cpustate.omni) | Target/profile-specific library; NOT_RUN individually; not a hosted application | [contracts](../spec/INDEX.md), [behavior suites](../tests/MATRIX.json) |
| [storage/critical.omni](storage/critical.omni) | Target/profile-specific library; NOT_RUN individually; not a hosted application | [contracts](../spec/INDEX.md), [behavior suites](../tests/MATRIX.json) |
| [storage/dma.omni](storage/dma.omni) | Target/profile-specific library; NOT_RUN individually; not a hosted application | [contracts](../spec/INDEX.md), [behavior suites](../tests/MATRIX.json) |
| [storage/endian.omni](storage/endian.omni) | Target/profile-specific library; NOT_RUN individually; not a hosted application | [contracts](../spec/INDEX.md), [behavior suites](../tests/MATRIX.json) |
| [storage/endian_mem.omni](storage/endian_mem.omni) | Target/profile-specific library; NOT_RUN individually; not a hosted application | [contracts](../spec/INDEX.md), [behavior suites](../tests/MATRIX.json) |
| [storage/field.omni](storage/field.omni) | Target/profile-specific library; NOT_RUN individually; not a hosted application | [contracts](../spec/INDEX.md), [behavior suites](../tests/MATRIX.json) |
| [storage/heap.omni](storage/heap.omni) | Target/profile-specific library; NOT_RUN individually; not a hosted application | [contracts](../spec/INDEX.md), [behavior suites](../tests/MATRIX.json) |
| [storage/ktask.omni](storage/ktask.omni) | Target/profile-specific library; NOT_RUN individually; not a hosted application | [contracts](../spec/INDEX.md), [behavior suites](../tests/MATRIX.json) |
| [storage/mailbox.omni](storage/mailbox.omni) | Target/profile-specific library; NOT_RUN individually; not a hosted application | [contracts](../spec/INDEX.md), [behavior suites](../tests/MATRIX.json) |
| [storage/map.omni](storage/map.omni) | Target/profile-specific library; NOT_RUN individually; not a hosted application | [contracts](../spec/INDEX.md), [behavior suites](../tests/MATRIX.json) |
| [storage/mmio.omni](storage/mmio.omni) | Target/profile-specific library; NOT_RUN individually; not a hosted application | [contracts](../spec/INDEX.md), [behavior suites](../tests/MATRIX.json) |
| [storage/region.omni](storage/region.omni) | Target/profile-specific library; NOT_RUN individually; not a hosted application | [contracts](../spec/INDEX.md), [behavior suites](../tests/MATRIX.json) |
| [storage/registry.omni](storage/registry.omni) | Target/profile-specific library; NOT_RUN individually; not a hosted application | [contracts](../spec/INDEX.md), [behavior suites](../tests/MATRIX.json) |
| [storage/rvec.omni](storage/rvec.omni) | Target/profile-specific library; NOT_RUN individually; not a hosted application | [contracts](../spec/INDEX.md), [behavior suites](../tests/MATRIX.json) |
| [storage/seq.omni](storage/seq.omni) | Target/profile-specific library; NOT_RUN individually; not a hosted application | [contracts](../spec/INDEX.md), [behavior suites](../tests/MATRIX.json) |
| [storage/simd.omni](storage/simd.omni) | Target/profile-specific library; NOT_RUN individually; not a hosted application | [contracts](../spec/INDEX.md), [behavior suites](../tests/MATRIX.json) |
| [storage/vec.omni](storage/vec.omni) | Target/profile-specific library; NOT_RUN individually; not a hosted application | [contracts](../spec/INDEX.md), [behavior suites](../tests/MATRIX.json) |
| [storage/vec_u32.omni](storage/vec_u32.omni) | Target/profile-specific library; NOT_RUN individually; not a hosted application | [contracts](../spec/INDEX.md), [behavior suites](../tests/MATRIX.json) |
| [storage/window.omni](storage/window.omni) | Target/profile-specific library; NOT_RUN individually; not a hosted application | [contracts](../spec/INDEX.md), [behavior suites](../tests/MATRIX.json) |
| [sumatoria.omni](sumatoria.omni) | NOT_RUN individually; source admitted | [contracts](../spec/INDEX.md), [behavior suites](../tests/MATRIX.json) |
| [text_file.omni](text_file.omni) | NOT_RUN individually; source admitted | [contracts](../spec/INDEX.md), [behavior suites](../tests/MATRIX.json) |
| [unicode_text.omni](unicode_text.omni) | NOT_RUN individually; source admitted | [contracts](../spec/INDEX.md), [behavior suites](../tests/MATRIX.json) |
