<!--
SPDX-FileCopyrightText: 2026 Federico T. Begna
SPDX-License-Identifier: MIT OR Apache-2.0
-->

# Learn Omni

Begin with programs you can run; use the [specification authority](../../spec/README.md) for normative rules and the [capability catalog](CAPABILITY_STATUS.md) for implemented scope and test limits.

## Types, functions and flow

[hola.omni](../../examples/hola.omni) defines `factorial(n u32) u32 !pure`. The parameter and result use unsigned 32-bit integers; recursion and `if/else` compute a value without I/O. Its `main` declares `!io`, prints a greeting and factorial(6), and returns zero. Build/check/run commands are in [Quick Start](../getting-started/QUICKSTART.md).

[Numeric examples](../../examples/numeric.omni) show fixed-width arithmetic, checked casts and explicitly wrapping/saturating operators. [Product types](../../examples/product_types.omni) demonstrate tuples and fixed arrays; [Option](../../examples/option.omni) and [enums](../../examples/adt_enum.omni) make alternatives explicit. Their evaluator/native oracles are in [capability_smoke.py](../../tests/capability_smoke.py).

## Handle an error and continue

[result_minimo.omni](../../examples/result_minimo.omni) computes `Result<u32,u32>`. Its zero-count input returns `Err(100)`; `match` handles both alternatives, prints `100`, then continues to `El programa continua`. This is ordinary control flow, not an unhandled native exception. See [ADTs](../../spec/ADTS_0_2.md).

## Effects and capabilities

A working positive program is [io_allowed.omni](../../tests/fixtures/dx/io_allowed.omni):

```text
module capability_example

func main() u32 !{io.print} {
    print("Capability accepted")
    return 0
}
```

Run it from Linux at the project root:

```sh
python3 -B tools/omni_dev.py check tests/fixtures/dx/io_allowed.omni
python3 -B tools/omni_dev.py run tests/fixtures/dx/io_allowed.omni
```

It prints `Capability accepted` and exits 0. The negative [pure_io_denied.omni](../../tests/fixtures/dx/pure_io_denied.omni) is valid syntax but declares `!pure` while printing:

```text
module capability_rejection

func main() u32 !pure {
    print("This requires io.print")
    return 0
}
```

`omni check tests/fixtures/dx/pure_io_denied.omni` must exit 2 with `E_CAPABILITY`, not a parse error. [First-use tests](../../tests/cli_smoke.py) assert that distinction. Static declarations do not replace the runtime OHP1 grants needed for hosted file/process/network effects; see [hosted effects](../../spec/HOSTED_EFFECTS_FFI_0_8_6.md).

## Continue by behavior

- [Borrowing and views](../../spec/BORROWED_VIEWS_0_2.md): inspect [borrow_mut.omni](../../examples/borrow_mut.omni) and [borrowed_views.omni](../../examples/borrowed_views.omni).
- [Generics and abstraction](../../spec/GENERICS_ABSTRACTION_0_2.md): [generics_iteration.omni](../../examples/generics_iteration.omni) specializes explicit type arguments and returns 42.
- [Unicode](../../examples/unicode_text.omni) distinguishes UTF-8 bytes from scalar count; [ranges](../../examples/ranges.omni) shows bounded iteration.
- [Examples](../../examples/README.md), [tests](../../tests/README.md), and [spec index](../../spec/INDEX.md) separate demonstrations, contracts and unadopted proposals.

For mounted WSL checkouts add `--allow-slow-fs` before the driver subcommand. PowerShell uses `python` and the same documented bridge. Never infer whole-family certification from one working example.
