<!--
SPDX-FileCopyrightText: 2026 Federico T. Begna
SPDX-License-Identifier: MIT OR Apache-2.0
-->

# Compiler implementation

compiler/src contains the actual C++20 compiler and shared SDK implementation. The source language remains Omni (.omni); this implementation is not self-hosted.

The driver is main.cpp; particle.cpp handles parsing; check.cpp validates types, ownership, effects and authority; modules.cpp/packages.cpp resolve dependencies; formats.cpp implements structural representations; onme.cpp and osnmf.cpp provide semantic projections and memory; llvm.cpp emits textual LLVM IR for Clang. Public headers are under include/omni, not this internal header directory.

tools/core_sources.txt lists 21 executable units. host_invocation_loader.cpp and host_sdk_public.cpp are two additional loader/SDK units, not executable entry points. Shared implementation is not copied into a second SDK tree.

See [pipeline](../docs/architecture/COMPILER_PIPELINE.md), [build](../DEVELOPMENT.md), and [ABI](../include/omni/omni_host_sdk_v1.h).
