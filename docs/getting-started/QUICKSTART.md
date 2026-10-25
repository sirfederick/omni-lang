<!--
SPDX-FileCopyrightText: 2026 Federico T. Begna
SPDX-License-Identifier: MIT OR Apache-2.0
-->

# First Omni program

Use the existing [hola.omni](../../examples/hola.omni), whose actual source is the executable example; no pseudocode is substituted. From the root:

```powershell
python tools/omni_dev.py --allow-slow-fs env
python tools/omni_dev.py --allow-slow-fs build --target compiler --jobs 2
python tools/omni_dev.py --allow-slow-fs check examples/hola.omni
python tools/omni_dev.py --allow-slow-fs run examples/hola.omni
```

In Linux/WSL use python3. --version must report 0.1.0.00. To build a persistent native executable from Linux:

```sh
OMNI_HOME="$PWD" build/dev/omni build examples/hola.omni -o build/dev/hola
build/dev/hola
```

The runtime is compiled by Clang on this profile; C++ source is the compiler implementation, not the program syntax. See [requirements](../../DEVELOPMENT.md) and [example navigation](../../examples/README.md).
