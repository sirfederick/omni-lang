#include "omni.hpp"

namespace omni {
namespace {
namespace fs=std::filesystem;

uint64_t number(const std::string& raw,const std::string& field) {
    if(raw.empty())fail("E_HOST_POLICY","valor vacio: "+field);
    uint64_t value=0;
    const auto result=std::from_chars(raw.data(),raw.data()+raw.size(),value);
    if(result.ec!=std::errc()||result.ptr!=raw.data()+raw.size()||value==0)
        fail("E_HOST_POLICY","valor numerico invalido: "+field);
    return value;
}

std::vector<std::string> fields(const std::string& line) {
    std::vector<std::string> result;
    size_t start=0;
    for(size_t i=0;i<=line.size();++i)if(i==line.size()||line[i]=='|') {
        result.push_back(line.substr(start,i-start));
        start=i+1;
    }
    return result;
}

bool hasParentTraversal(const fs::path& path) {
    for(const auto& part:path)if(part=="..")return true;
    return false;
}

std::string pathScope(const std::string& raw,bool grant) {
    if(raw.empty()||raw.find('\0')!=std::string::npos)fail("E_HOST_POLICY","scope path invalido");
    const fs::path path(raw);
    if(!path.is_absolute()||hasParentTraversal(path))
        fail("E_HOST_POLICY","scope path debe ser absoluto y sin traversal");
    std::error_code ec;
    const auto normalized=grant?fs::canonical(path,ec):fs::weakly_canonical(path,ec);
    if(ec)fail("E_HOST_POLICY","scope path no canonicalizable");
    if(normalized==normalized.root_path())fail("E_HOST_POLICY","scope path raiz no admitido");
    return normalized.generic_string();
}

std::string endpointScope(const std::string& raw) {
    const auto colon=raw.rfind(':');
    if(colon==std::string::npos||colon==0||colon+1>=raw.size())fail("E_HOST_POLICY","endpoint invalido");
    const auto host=raw.substr(0,colon),portRaw=raw.substr(colon+1);
    uint32_t octets=0;
    size_t start=0;
    while(start<host.size()) {
        const auto dot=host.find('.',start);
        const auto end=dot==std::string::npos?host.size():dot;
        if(end==start||end-start>3)fail("E_HOST_POLICY","endpoint requiere IPv4 numerico");
        uint64_t value=0;
        const auto part=host.substr(start,end-start);
        const auto parsed=std::from_chars(part.data(),part.data()+part.size(),value);
        if(parsed.ec!=std::errc()||parsed.ptr!=part.data()+part.size()||value>255)
            fail("E_HOST_POLICY","endpoint requiere IPv4 numerico");
        ++octets;
        if(dot==std::string::npos)break;
        start=dot+1;
    }
    if(octets!=4)fail("E_HOST_POLICY","endpoint requiere IPv4 numerico");
    const auto port=number(portRaw,"endpoint.port");
    if(port>65535)fail("E_HOST_POLICY","puerto fuera de rango");
    return host+":"+std::to_string(port);
}

std::string normalizedScope(const std::string& capability,const std::string& raw,bool grant) {
    if(capability=="net.connect")return endpointScope(raw);
    if(capability=="fs.read"||capability=="fs.write"||capability=="process.spawn"||capability=="ffi.call")
        return pathScope(raw,grant);
    fail("E_HOST_POLICY","capability no admitida en OHP1: "+capability);
}

bool inside(const fs::path& root,const fs::path& candidate) {
    auto a=root.begin(),b=candidate.begin();
    for(;a!=root.end();++a,++b)if(b==candidate.end()||*a!=*b)return false;
    return true;
}
}

HostPolicy parseHostPolicy(const std::string& text) {
    if(text.size()>65536u)fail("E_HOST_POLICY","policy excede 64 KiB");
    validateUTF8(text);
    if(text.find('\0')!=std::string::npos)fail("E_HOST_POLICY","NUL no admitido");
    std::vector<std::string> lines;
    std::istringstream input(text);
    for(std::string line;std::getline(input,line);) {
        if(!line.empty()&&line.back()=='\r')line.pop_back();
        if(line.empty())fail("E_HOST_POLICY","linea vacia no admitida");
        lines.push_back(std::move(line));
    }
    if(lines.size()<4||lines.front()!="OHP1")fail("E_HOST_POLICY","header OHP1 requerido");
    if(text.empty()||text.back()!='\n')fail("E_HOST_POLICY","newline final requerido");
    const auto generation=fields(lines[1]),expiry=fields(lines[2]);
    if(generation.size()!=2||generation[0]!="generation")fail("E_HOST_POLICY","generation debe ser el primer header");
    if(expiry.size()!=2||expiry[0]!="not_after_tick")fail("E_HOST_POLICY","not_after_tick debe ser el segundo header");
    HostPolicy policy;
    policy.generation=number(generation[1],"generation");
    policy.notAfterTick=number(expiry[1],"not_after_tick");
    std::set<std::string> unique;
    for(size_t i=3;i<lines.size();++i) {
        const auto item=fields(lines[i]);
        if(item.size()!=4||item[0]!="grant")fail("E_HOST_POLICY","grant OHP1 invalido");
        const auto capability=canonicalCapability(item[1]);
        const auto scope=normalizedScope(capability,item[2],true);
        const auto maxBytes=number(item[3],"grant.max_bytes");
        if(maxBytes>OMNI_TEXT_VALUE_LIMIT_BYTES)fail("E_HOST_POLICY","grant.max_bytes excede 1 MiB");
        const auto identity=capability+"|"+scope;
        if(!unique.insert(identity).second)fail("E_HOST_POLICY","grant duplicado: "+identity);
        policy.grants.push_back({capability,scope,maxBytes});
    }
    if(policy.grants.empty())fail("E_HOST_POLICY","se requiere al menos un grant");
    std::sort(policy.grants.begin(),policy.grants.end(),[](const HostGrant& a,const HostGrant& b){
        return std::tie(a.capability,a.scope,a.maxBytes)<std::tie(b.capability,b.scope,b.maxBytes);
    });
    return policy;
}

bool HostPolicy::allows(const std::string& requested,const std::string& subject,
                        uint64_t bytes,uint64_t tick,uint64_t expectedGeneration) const {
    const auto capability=canonicalCapability(requested);
    if(generation==0||expectedGeneration!=generation||tick>notAfterTick)return false;
    if(capability=="fs.read"||capability=="fs.write") {
        if(subject.empty()||subject.find('\0')!=std::string::npos)return false;
        const fs::path raw(subject);
        if(!raw.is_absolute()||hasParentTraversal(raw))return false;
        const auto lexical=raw.lexically_normal();
        if(lexical==lexical.root_path())return false;
        bool eligible=false;
        for(const auto& grant:grants) {
            if(grant.capability==capability&&bytes<=grant.maxBytes&&
               inside(fs::path(grant.scope),lexical)) { eligible=true; break; }
        }
        if(!eligible)return false;
        std::error_code ec;
        const auto canonical=fs::weakly_canonical(lexical,ec);
        if(ec)return false;
        for(const auto& grant:grants) {
            if(grant.capability==capability&&bytes<=grant.maxBytes&&
               inside(fs::path(grant.scope),canonical))return true;
        }
        return false;
    }
    std::string normalized;
    try { normalized=normalizedScope(capability,subject,false); }
    catch(const Error&) { return false; }
    for(const auto& grant:grants) {
        if(grant.capability!=capability||bytes>grant.maxBytes)continue;
        if(grant.scope==normalized)return true;
    }
    return false;
}

std::string hostPolicySummaryJson(const HostPolicy& policy) {
    std::ostringstream canonical;
    canonical<<"OHP1\ngeneration|"<<policy.generation<<"\nnot_after_tick|"<<policy.notAfterTick<<"\n";
    for(const auto& grant:policy.grants)
        canonical<<"grant|"<<grant.capability<<'|'<<grant.scope<<'|'<<grant.maxBytes<<"\n";
    std::ostringstream output;
    output<<"{\n  \"schema\": \"omni.host-policy-summary/1\",\n"
          <<"  \"status\": \"VALID\",\n"
          <<"  \"generation\": "<<policy.generation<<",\n"
          <<"  \"not_after_tick\": "<<policy.notAfterTick<<",\n"
          <<"  \"grant_count\": "<<policy.grants.size()<<",\n"
          <<"  \"policy_sha256\": \""<<sha256(canonical.str())<<"\",\n"
          <<"  \"capabilities\": [";
    bool first=true;
    for(const auto& grant:policy.grants){if(!first)output<<',';first=false;output<<quote(grant.capability);}
    output<<"]\n}\n";
    return output.str();
}
}
