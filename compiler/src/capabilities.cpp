#include "omni.hpp"
namespace omni {
const std::map<std::string,CapabilitySpec>& capabilityRegistry(){
    static const std::map<std::string,CapabilitySpec> r={
        {"io.print",{"io.print","io","none","low","",6,true,true,true,true,false}},
        {"fs.read",{"fs.read","filesystem","path-set","medium","",6,true,true,true,true,false}},
        {"fs.write",{"fs.write","filesystem","path-set","high","",6,true,true,true,true,false}},
        {"data.read",{"data.read","data","resource-scope","high","",5,true,true,true,true,false}},
        {"data.write",{"data.write","data","resource-scope","high","",5,true,true,true,true,false}},
        {"memory.read",{"memory.read","memory","resource-scope","medium","",5,true,true,true,true,false}},
        {"memory.write",{"memory.write","memory","resource-scope","high","",5,true,true,true,true,false}},
        {"memory.raw",{"memory.raw","target-memory","address-range","critical","",1,false,false,true,true,false}},
        {"memory.atomic",{"memory.atomic","target-memory","address-range","critical","",1,false,false,true,true,false}},
        {"memory.tls",{"memory.tls","target-memory","thread-block","high","",1,false,false,true,true,false}},
        {"memory.pcpu",{"memory.pcpu","target-memory","cpu-block","high","",1,false,false,true,true,false}},
        {"port.io",{"port.io","target-io","port-set","critical","",1,false,false,true,true,false}},
        {"cpu.control",{"cpu.control","target-cpu","privileged-op-set","critical","",1,false,false,true,true,false}},
        {"cpu.syscall",{"cpu.syscall","target-cpu","service-gate","high","",1,false,false,true,true,false}},
        {"net.connect",{"net.connect","network","endpoint-set","high","",6,true,true,true,true,false}},
        {"net.listen",{"net.listen","network","endpoint-set","critical","",6,true,false,true,true,false}},
        {"process.spawn",{"process.spawn","process","executable-set","critical","",20,false,false,true,true,false}},
        {"ffi.call",{"ffi.call","foreign","library-set","critical","",20,false,false,true,true,false}},
        {"external.egress",{"external.egress","egress","destination-set","critical","",5,true,false,true,true,false}},
        {"secret.use",{"secret.use","secret","secret-set","critical","",6,true,false,true,true,false}},
    };
    return r;
}
std::string canonicalCapability(const std::string& in){
    if(in=="net") return "net.connect"; // dev.5 source compatibility only
    return in;
}
bool isKnownCapability(const std::string& in){ return capabilityRegistry().count(canonicalCapability(in)); }
std::set<std::string> legacyIoCapabilities(){ return {"fs.read","fs.write","io.print"}; }
std::string capabilityRegistryJson(){
    std::ostringstream o; o<<"{\n  \"schema\": \"omni.capability-registry/1\",\n  \"registry_version\": 1,\n  \"capabilities\": [";
    bool first=true;
    for(const auto& [name,c]:capabilityRegistry()){
        if(!first) o<<",";
        first=false;
        o<<"\n    {\"id\": "<<quote(name)
         <<", \"category\": "<<quote(c.category)
         <<", \"scope_kind\": "<<quote(c.scopeKind)
         <<", \"risk_class\": "<<quote(c.riskClass)
         <<", \"introduced_version\": "<<c.introducedVersion
         <<", \"serializable\": "<<(c.serializable?"true":"false")
         <<", \"delegable\": "<<(c.delegable?"true":"false")
         <<", \"revocable\": "<<(c.revocable?"true":"false")
         <<", \"auditable\": "<<(c.auditable?"true":"false")
         <<", \"deprecated\": "<<(c.deprecated?"true":"false");
        if(!c.replacement.empty())o<<", \"replacement\": "<<quote(c.replacement);
        o<<"}";
    }
    o<<"\n  ]\n}\n"; return o.str();
}
std::string capabilitiesJson(const Program& p,bool explain){
    std::ostringstream o; o<<"{\n  \"schema\": \"omni.capabilities/3\",\n  \"registry_version\": 1,\n  \"functions\": [";
    for(size_t j=0;j<p.functions.size();++j){
        const auto& f=p.functions[j]; if(j)o<<","; o<<"\n    {\"function\": "<<quote(f.key)<<", \"declared\": [";
        bool first=true; for(auto&c:f.capabilities){if(!first)o<<",";first=false;o<<quote(c);} o<<"]";
        o<<", \"direct_required\": ["; first=true; for(auto&c:f.directCapabilities){if(!first)o<<",";first=false;o<<quote(c);} o<<"]";
        o<<", \"required\": ["; first=true; for(auto&c:f.requiredCapabilities){if(!first)o<<",";first=false;o<<quote(c);} o<<"]";
        o<<", \"excess\": ["; first=true; for(auto&c:f.excessCapabilities){if(!first)o<<",";first=false;o<<quote(c);} o<<"]";
        if(explain) o<<", \"analysis\": \"least-privilege\"";
        o<<"}";
    }
    o<<"\n  ]\n}\n"; return o.str();
}
std::string failureName(FailureKind k){
    switch(k){
        case FailureKind::CompileError:return "CompileError";
        case FailureKind::ValidationError:return "ValidationError";
        case FailureKind::CapabilityDenied:return "CapabilityDenied";
        case FailureKind::DeadlineExceeded:return "DeadlineExceeded";
        case FailureKind::Cancelled:return "Cancelled";
        case FailureKind::ResourceExhausted:return "ResourceExhausted";
        case FailureKind::Trap:return "Trap";
    }
    return "UnknownFailure";
}
}
