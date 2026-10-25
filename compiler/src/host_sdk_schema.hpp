#pragma once

#include "host_invocation_descriptor.hpp"

namespace omni {

struct HostSdkSchemaNode {
    uint8_t tag=0;
    InvocationHash typeId{};
    // Present only for nominal Record/Enum nodes.  This is contract identity,
    // not an authority grant, and is re-hashed against typeId before use.
    std::string nominalKey;
    uint32_t extent=0;
    std::vector<uint32_t> children;
    std::vector<std::string> labels;
};

struct HostSdkSchema {
    uint32_t version=1;
    InvocationHash signature{};
    std::vector<HostSdkSchemaNode> nodes;
    std::vector<uint32_t> requestRoots;
    uint32_t resultRoot=0;
};

std::vector<uint8_t> encodeHostSdkSchema(const Program& program,
                                         const std::vector<Type>& parameters,
                                         const Type& result,
                                         const InvocationHash& signature);
HostSdkSchema decodeHostSdkSchema(std::span<const uint8_t> bytes);
void validateHostSdkSchema(const HostSdkSchema& schema,
                           const HostInvocationDescriptor& descriptor);
Program hostSdkSchemaProgram(const HostSdkSchema& schema);
std::vector<Type> hostSdkSchemaRequestTypes(const HostSdkSchema& schema,
                                            const Program& program);
Type hostSdkSchemaResultType(const HostSdkSchema& schema,
                             const Program& program);
Type hostSdkSchemaNodeType(const HostSdkSchema& schema, const Program& program,
                           uint32_t node);

}
