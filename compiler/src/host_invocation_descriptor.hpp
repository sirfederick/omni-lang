#pragma once

#include "omni.hpp"
#include <array>
#include <span>

namespace omni {
inline constexpr const char* INVOCATION_ABI_ID="omni.module-invoke/1";
inline constexpr const char* INVOCATION_TARGET_ID="linux-x86_64-gnu";
inline constexpr const char* INVOCATION_RUNTIME_ABI_ID="omni.module-invoke.runtime/1";
inline constexpr const char* INVOCATION_BUILD_PROFILE_ID="omni.module-invoke.native/1";
using InvocationHash=std::array<uint8_t,32>;

struct HostInvocationDescriptor {
    uint32_t version=1;
    std::string abi=INVOCATION_ABI_ID;
    std::string packageOrigin,packageName,packageVersion;
    InvocationHash manifestHash{},sourceHash{};
    std::string modulePath,functionName;
    std::vector<InvocationHash> parameterTypeIds;
    InvocationHash returnTypeId{};
    std::vector<std::string> effects;
    std::string target=INVOCATION_TARGET_ID;
    std::string runtimeAbi=INVOCATION_RUNTIME_ABI_ID;
    InvocationHash runtimeBuildHash{},compilerHash{};
    std::string buildProfile=INVOCATION_BUILD_PROFILE_ID;
    InvocationHash lockHash{},signatureDigest{},buildInputDigest{};
};

InvocationHash invocationHash(std::span<const uint8_t> bytes);
InvocationHash invocationHashHex(const std::string& hex);
std::string invocationHashHex(const InvocationHash& hash);
InvocationHash computeInvocationSignature(const HostInvocationDescriptor& descriptor);
InvocationHash computeInvocationBuildInput(const HostInvocationDescriptor& descriptor);
std::vector<uint8_t> encodeInvocationDescriptor(const HostInvocationDescriptor& descriptor);
HostInvocationDescriptor decodeInvocationDescriptor(std::span<const uint8_t> bytes,
                                                     bool verifyDigests=true);
}
