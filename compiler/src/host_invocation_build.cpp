#include "host_invocation_build.hpp"
#include "host_invocation_codec.hpp"

namespace omni {
namespace {
const Function& selectedFunction(const Program& program,const std::string& name) {
    const Function* result=nullptr;bool privateFound=false;
    for(const auto& function:program.functions) {
        if(function.module!=program.module||function.name!=name||function.generated)continue;
        if(!function.pub){privateFound=true;continue;}
        if(result)fail("E_HOST_ENTRY","ambiguous host entry");
        result=&function;
    }
    for(const auto& function:program.genericTemplates)
        if(function.module==program.module&&function.name==name)
            fail("E_HOST_ENTRY","generic host entry unsupported");
    if(!result)fail("E_HOST_ENTRY",privateFound?"private host entry":"missing host entry");
    return *result;
}
void validateSignature(const Program& program,const Function& function) {
    if(!function.generics.empty()||function.closureGenerated)
        fail("E_HOST_ENTRY","generic or captured host entry unsupported");
    for(const auto& parameter:function.params)
        if(!admittedInvocationType(program,parameter.type))
            fail("E_HOST_ENTRY","unsupported host entry parameter");
    if(!admittedInvocationType(program,function.result))
        fail("E_HOST_ENTRY","unsupported host entry result");
    static const std::set<std::string> admitted={"fs.read","fs.write","process.spawn",
                                                   "net.connect","ffi.call"};
    for(const auto& effect:function.capabilities)
        if(!admitted.count(effect))fail("E_HOST_ENTRY","unsupported host entry effect");
    for(const auto& effect:function.requiredCapabilities)
        if(!admitted.count(effect))fail("E_HOST_ENTRY","unsupported transitive effect");
}
}
HostBuildSelection selectHostBuild(const std::filesystem::path& packageRoot,
        const std::string& hostEntry,const InvocationHash& compilerHash,
        const InvocationHash& runtimeBuildHash,const std::filesystem::path& bundledStdlib) {
    const auto colon=hostEntry.rfind(':');
    if(colon==std::string::npos||colon==0||colon+1==hostEntry.size()||
       hostEntry.find(':')!=colon)fail("E_HOST_ENTRY","expected src/module.omni:function");
    const auto modulePath=hostEntry.substr(0,colon);
    const auto name=hostEntry.substr(colon+1);
    if(!validIdentifier(name))fail("E_HOST_ENTRY","invalid function name");
    const auto source=lockedHostSource(packageRoot,modulePath,bundledStdlib);
    const auto package=lockedHostPackage(packageRoot,bundledStdlib);
    HostBuildSelection selection;
    selection.program=load(source);
    const auto& function=selectedFunction(selection.program,name);
    validateSignature(selection.program,function);
    selection.functionKey=function.key;
    auto& d=selection.descriptor;
    d.packageOrigin=package.origin;d.packageName=package.name;d.packageVersion=package.version;
    d.manifestHash=invocationHashHex(package.manifestHash);
    d.sourceHash=invocationHashHex(package.sourceHash);
    d.lockHash=invocationHashHex(package.lockHash);
    d.modulePath=modulePath;d.functionName=name;
    for(const auto& param:function.params)d.parameterTypeIds.push_back(invocationTypeId(param.type));
    d.returnTypeId=invocationTypeId(function.result);
    d.effects.assign(function.capabilities.begin(),function.capabilities.end());
    d.compilerHash=compilerHash;d.runtimeBuildHash=runtimeBuildHash;
    d.signatureDigest=computeInvocationSignature(d);
    d.buildInputDigest=computeInvocationBuildInput(d);
    return selection;
}
std::string hostBuildReceiptJson(const HostBuildSelection& selection,
        const std::filesystem::path& artifact,const InvocationHash& descriptorHash) {
    const auto& d=selection.descriptor;
    std::ostringstream out;
    out<<"{\n  \"schema\": \"omni.module-invoke.build-receipt/1\",\n"
       <<"  \"abi_identifier\": "<<quote(d.abi)<<",\n"
       <<"  \"build_profile_id\": "<<quote(d.buildProfile)<<",\n"
       <<"  \"compiler_sha256\": \""<<invocationHashHex(d.compilerHash)<<"\",\n"
       <<"  \"core_runtime_build_sha256\": \""<<invocationHashHex(d.runtimeBuildHash)<<"\",\n"
       <<"  \"package_origin\": "<<quote(d.packageOrigin)<<",\n"
       <<"  \"package_name\": "<<quote(d.packageName)<<",\n"
       <<"  \"package_version\": "<<quote(d.packageVersion)<<",\n"
       <<"  \"manifest_sha256\": \""<<invocationHashHex(d.manifestHash)<<"\",\n"
       <<"  \"semantic_source_sha256\": \""<<invocationHashHex(d.sourceHash)<<"\",\n"
       <<"  \"lock_sha256\": \""<<invocationHashHex(d.lockHash)<<"\",\n"
       <<"  \"selected_host_entry\": "<<quote(d.modulePath+":"+d.functionName)<<",\n"
       <<"  \"parameter_type_ids\": [";
    for(size_t i=0;i<d.parameterTypeIds.size();i++) {
        if(i)out<<", ";
        out<<quote(invocationHashHex(d.parameterTypeIds[i]));
    }
    out<<"],\n  \"return_type_id\": "<<quote(invocationHashHex(d.returnTypeId))<<",\n"
       <<"  \"signature_digest\": \""<<invocationHashHex(d.signatureDigest)<<"\",\n"
       <<"  \"build_input_digest\": \""<<invocationHashHex(d.buildInputDigest)<<"\",\n"
       <<"  \"descriptor_sha256\": \""<<invocationHashHex(descriptorHash)<<"\",\n"
       <<"  \"artifact_sha256\": \""<<sha256File(artifact)<<"\"\n}\n";
    return out.str();
}
}
