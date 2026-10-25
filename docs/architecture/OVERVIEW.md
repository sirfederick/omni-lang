<!--
SPDX-FileCopyrightText: 2026 Federico T. Begna
SPDX-License-Identifier: MIT OR Apache-2.0
-->

# Product architecture

Omni Language is the .omni language. C++20 implements the current compiler; C implements the native runtime and invocation codec. The minimal standard library contains .omni source. The integrated SDK exposes the compiler/runtime contracts to C, Node N-API and Python ctypes hosts.

The product is WORK IN PROGRESS / NOT_RELEASED, identity 0.1.0.00. Compiler, runtime and SDK share the distribution identity; ABI and representations have independent identities. No kernel, autonomous AI, remote-provider security or native Windows/macOS support is implied.

The organization follows compiler visibility from [Rust](https://github.com/rust-lang/rust), an explicit compiler pipeline from [Go](https://go.dev/src/cmd/compile/README), and implementation/library boundaries from [CPython](https://github.com/python/cpython). These are organizational references, not replacements for Omni semantics.

Start with [development](../../DEVELOPMENT.md), [first program](../getting-started/QUICKSTART.md), [compiler pipeline](COMPILER_PIPELINE.md), [version domains](VERSION_IDENTITIES.md), [SDK](../sdk/QUICKSTART.md) and [specification index](../../spec/INDEX.md).
