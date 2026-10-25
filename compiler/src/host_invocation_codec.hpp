#pragma once

#include "omni.hpp"
#include <array>
#include <span>

namespace omni {
inline constexpr uint32_t OMI1_FRAME_MAX = 1048576u;
inline constexpr uint32_t OMI1_NODE_MAX = 65536u;
inline constexpr uint32_t OMI1_DEPTH_MAX = 32u;

// OMI1 is a host-value representation. These values carry no capability.
std::vector<Value> decodeInvocationFrame(
    const Program& program, std::span<const uint8_t> frame,
    uint32_t kind, const std::array<uint8_t,32>& signature,
    const std::vector<Type>& expected);
std::vector<uint8_t> encodeInvocationFrame(
    const Program& program, uint32_t kind,
    const std::array<uint8_t,32>& signature,
    const std::vector<Type>& expected, const std::vector<Value>& values);
std::array<uint8_t,32> invocationTypeId(const Type& type);
uint8_t invocationTypeTag(const Type& type);
bool admittedInvocationType(const Program& program, const Type& type,
                            uint32_t depth=0);
}
