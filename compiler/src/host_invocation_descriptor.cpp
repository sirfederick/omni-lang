#include "host_invocation_descriptor.hpp"
#include <algorithm>
#include <limits>

namespace omni {
namespace {
constexpr uint8_t MAGIC[8]={'O','M','I','D','1',0,0,0};
[[noreturn]] void bad() {fail("E_OMID_IDENTITY","invalid OMID1 descriptor");}
void canonical(const std::string& value) {
    if(value.find('\0')!=std::string::npos)bad();
    try {validateUTF8(value);}catch(const Error&) {bad();}
}
struct Writer {
    std::vector<uint8_t> bytes;
    void raw(std::span<const uint8_t> part) {bytes.insert(bytes.end(),part.begin(),part.end());}
    void u32(uint32_t x) {for(unsigned i=0;i<4;i++)bytes.push_back(static_cast<uint8_t>(x>>(8u*i)));}
    void text(const std::string& value) {
        canonical(value);if(value.size()>UINT32_MAX)bad();
        u32(static_cast<uint32_t>(value.size()));
        raw(std::span<const uint8_t>(reinterpret_cast<const uint8_t*>(value.data()),value.size()));
    }
};
struct Reader {
    std::span<const uint8_t> bytes;size_t pos=0;
    std::span<const uint8_t> raw(size_t n) {
        if(pos>bytes.size()||n>bytes.size()-pos)bad();
        const auto found=bytes.subspan(pos,n);pos+=n;return found;
    }
    uint32_t u32() {
        const auto s=raw(4);return uint32_t(s[0])|(uint32_t(s[1])<<8)|
                                (uint32_t(s[2])<<16)|(uint32_t(s[3])<<24);
    }
    std::string text() {
        const auto n=u32();const auto s=raw(n);
        std::string value(reinterpret_cast<const char*>(s.data()),s.size());
        canonical(value);return value;
    }
    InvocationHash hash() {
        InvocationHash h{};const auto s=raw(32);std::copy(s.begin(),s.end(),h.begin());return h;
    }
};
std::vector<uint8_t> signatureMaterial(const HostInvocationDescriptor& d) {
    Writer w;w.text(d.abi);w.text(d.packageOrigin);w.text(d.packageName);
    w.text(d.packageVersion);w.raw(d.manifestHash);w.raw(d.sourceHash);
    w.text(d.modulePath);w.text(d.functionName);
    if(d.parameterTypeIds.size()>UINT32_MAX||d.effects.size()>UINT32_MAX)bad();
    w.u32(static_cast<uint32_t>(d.parameterTypeIds.size()));
    for(const auto& id:d.parameterTypeIds)w.raw(id);
    w.raw(d.returnTypeId);w.u32(static_cast<uint32_t>(d.effects.size()));
    for(const auto& effect:d.effects)w.text(effect);
    return std::move(w.bytes);
}
std::vector<uint8_t> buildMaterial(const HostInvocationDescriptor& d) {
    Writer w;w.text(d.abi);w.u32(d.version);w.text(d.target);w.text(d.runtimeAbi);
    w.raw(d.runtimeBuildHash);w.raw(d.compilerHash);w.text(d.buildProfile);
    w.text(d.packageOrigin);w.text(d.packageName);w.text(d.packageVersion);
    w.raw(d.manifestHash);w.raw(d.sourceHash);w.raw(d.lockHash);
    w.text(d.modulePath);w.text(d.functionName);w.raw(d.signatureDigest);
    return std::move(w.bytes);
}
InvocationHash domainHash(const char* domain,std::span<const uint8_t> material) {
    const std::string prefix(domain);
    std::string all;all.reserve(prefix.size()+material.size());
    all+=prefix;all.append(reinterpret_cast<const char*>(material.data()),material.size());
    return invocationHashHex(sha256(all));
}
void validateFields(const HostInvocationDescriptor& d) {
    if(d.version!=1||d.abi!=INVOCATION_ABI_ID||d.target!=INVOCATION_TARGET_ID||
       d.runtimeAbi!=INVOCATION_RUNTIME_ABI_ID||d.buildProfile!=INVOCATION_BUILD_PROFILE_ID)bad();
    if(d.packageOrigin.empty()||d.packageName.empty()||d.packageVersion.empty()||
       d.modulePath.empty()||d.functionName.empty())bad();
    if(!std::is_sorted(d.effects.begin(),d.effects.end())||
       std::adjacent_find(d.effects.begin(),d.effects.end())!=d.effects.end())bad();
}
}
InvocationHash invocationHashHex(const std::string& hex) {
    const std::string_view digits=hex.rfind("sha256:",0)==0?
        std::string_view(hex).substr(7):std::string_view(hex);
    if(digits.size()!=64)bad();
    InvocationHash out{};
    auto nibble=[](char c)->uint8_t {
        if(c>='0'&&c<='9')return static_cast<uint8_t>(c-'0');
        if(c>='a'&&c<='f')return static_cast<uint8_t>(c-'a'+10);
        bad();
    };
    for(size_t i=0;i<32;i++)out[i]=static_cast<uint8_t>((nibble(digits[i*2])<<4)|nibble(digits[i*2+1]));
    return out;
}
std::string invocationHashHex(const InvocationHash& hash) {
    constexpr char HEX[]="0123456789abcdef";std::string result;result.reserve(64);
    for(const auto b:hash){result.push_back(HEX[b>>4]);result.push_back(HEX[b&15u]);}
    return result;
}
InvocationHash invocationHash(std::span<const uint8_t> bytes) {
    return invocationHashHex(sha256(std::string(reinterpret_cast<const char*>(bytes.data()),bytes.size())));
}
InvocationHash computeInvocationSignature(const HostInvocationDescriptor& d) {
    validateFields(d);const auto material=signatureMaterial(d);
    return domainHash("omni.module-invoke.signature/1\n",material);
}
InvocationHash computeInvocationBuildInput(const HostInvocationDescriptor& d) {
    validateFields(d);const auto material=buildMaterial(d);
    return domainHash("omni.module-invoke.build-input/1\n",material);
}
std::vector<uint8_t> encodeInvocationDescriptor(const HostInvocationDescriptor& d) {
    validateFields(d);
    if(d.signatureDigest!=computeInvocationSignature(d)||
       d.buildInputDigest!=computeInvocationBuildInput(d))bad();
    Writer w;w.raw(MAGIC);w.u32(d.version);w.text(d.abi);
    w.text(d.packageOrigin);w.text(d.packageName);w.text(d.packageVersion);
    w.raw(d.manifestHash);w.raw(d.sourceHash);w.text(d.modulePath);w.text(d.functionName);
    if(d.parameterTypeIds.size()>UINT32_MAX||d.effects.size()>UINT32_MAX)bad();
    w.u32(static_cast<uint32_t>(d.parameterTypeIds.size()));
    for(const auto& id:d.parameterTypeIds)w.raw(id);
    w.raw(d.returnTypeId);w.u32(static_cast<uint32_t>(d.effects.size()));
    for(const auto& effect:d.effects)w.text(effect);
    w.text(d.target);w.text(d.runtimeAbi);w.raw(d.runtimeBuildHash);
    w.raw(d.compilerHash);w.text(d.buildProfile);w.raw(d.lockHash);
    w.raw(d.signatureDigest);w.raw(d.buildInputDigest);
    return std::move(w.bytes);
}
HostInvocationDescriptor decodeInvocationDescriptor(std::span<const uint8_t> bytes,
                                                     bool verifyDigests) {
    Reader r{bytes};const auto magic=r.raw(8);
    if(!std::equal(magic.begin(),magic.end(),std::begin(MAGIC)))bad();
    HostInvocationDescriptor d;d.version=r.u32();d.abi=r.text();
    d.packageOrigin=r.text();d.packageName=r.text();d.packageVersion=r.text();
    d.manifestHash=r.hash();d.sourceHash=r.hash();d.modulePath=r.text();d.functionName=r.text();
    const auto paramCount=r.u32();if(paramCount>(bytes.size()-r.pos)/32u)bad();
    d.parameterTypeIds.reserve(paramCount);
    for(uint32_t i=0;i<paramCount;i++)d.parameterTypeIds.push_back(r.hash());
    d.returnTypeId=r.hash();const auto effectCount=r.u32();
    if(effectCount>(bytes.size()-r.pos)/4u)bad();
    d.effects.reserve(effectCount);for(uint32_t i=0;i<effectCount;i++)d.effects.push_back(r.text());
    d.target=r.text();d.runtimeAbi=r.text();d.runtimeBuildHash=r.hash();
    d.compilerHash=r.hash();d.buildProfile=r.text();d.lockHash=r.hash();
    d.signatureDigest=r.hash();d.buildInputDigest=r.hash();
    if(r.pos!=bytes.size())bad();
    validateFields(d);
    if(verifyDigests&&(d.signatureDigest!=computeInvocationSignature(d)||
       d.buildInputDigest!=computeInvocationBuildInput(d)))bad();
    return d;
}
}
