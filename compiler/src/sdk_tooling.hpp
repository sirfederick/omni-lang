#pragma once
#include "omni.hpp"

namespace omni {
std::map<std::string,std::string> sdkContractTexts(const std::filesystem::path&,const std::vector<std::string>&);
std::string targetContextJson(const std::filesystem::path&,const std::string&);
std::string componentContractJson(const Program&,const std::string&);
}
