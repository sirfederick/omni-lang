#pragma once

#include "host_invocation_descriptor.hpp"

namespace omni {
struct HostBuildSelection {
    Program program;
    std::string functionKey;
    HostInvocationDescriptor descriptor;
};

HostBuildSelection selectHostBuild(const std::filesystem::path& packageRoot,
                                   const std::string& hostEntry,
                                   const InvocationHash& compilerHash,
                                   const InvocationHash& runtimeBuildHash,
                                   const std::filesystem::path& bundledStdlib);
std::string hostBuildReceiptJson(const HostBuildSelection& selection,
                                 const std::filesystem::path& artifact,
                                 const InvocationHash& descriptorHash);
}
