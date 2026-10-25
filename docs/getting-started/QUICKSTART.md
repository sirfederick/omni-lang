<!--
SPDX-FileCopyrightText: 2026 Federico T. Begna
SPDX-License-Identifier: MIT OR Apache-2.0
-->

# First Omni program

Start at the [repository README](../../README.md#build-and-run) to obtain sources and dependencies. All commands below start at the checkout root.

On Linux/WSL:

```sh
python3 -B tools/omni_dev.py build --target compiler --jobs 2
python3 -B tools/omni_dev.py check examples/hola.omni
python3 -B tools/omni_dev.py run examples/hola.omni
```

On PowerShell (the build and program run inside WSL):

```powershell
python -B tools/omni_dev.py --allow-slow-fs build --target compiler --jobs 2
python -B tools/omni_dev.py --allow-slow-fs check examples/hola.omni
python -B tools/omni_dev.py --allow-slow-fs run examples/hola.omni
```

Expected output and exit 0:

```text
Hola, Omni
720
```

The exact source is [hola.omni](../../examples/hola.omni). [Learn the syntax](../language/README.md), then run [result_minimo.omni](../../examples/result_minimo.omni), which prints `100` and `El programa continua` and exits 0. [First-use tests](../../tests/cli_smoke.py) check the evaluator and real Clang/C-runtime executable separately.

If the compiler reports a missing/stale/changed output, rerun the build command. On mounted WSL paths add `--allow-slow-fs` before the subcommand. [Development](../../DEVELOPMENT.md) lists host dependencies and other diagnostics.
