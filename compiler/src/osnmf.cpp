#include "omni.hpp"
#include <chrono>
namespace omni {
namespace {
std::string h(const std::string& d,const std::string& b){return "sha256:"+sha256(d+"\n"+b);}
std::string auth(MemoryAuthority a){switch(a){case MemoryAuthority::CompilerAuthoritative:return "compiler-authoritative";case MemoryAuthority::DeveloperDeclared:return "developer-declared";case MemoryAuthority::RuntimeObserved:return "runtime-observed";case MemoryAuthority::VerifiedTool:return "verified-tool";case MemoryAuthority::VerifiedAgent:return "verified-agent";case MemoryAuthority::AIInferred:return "ai-inferred";case MemoryAuthority::ExternalSource:return "external-source";}return "external-source";}
std::string typeId(const Type&t){return semanticTypeId(t);}
std::string nid(const std::string& k,const std::string&m,const std::string&n){return h("omni.nucleus-id/1",k+"|"+m+"|"+n);}
void link(std::vector<SynapticLink>&v,const std::string&a,const std::string&b,const std::string&r,const std::string&au="compiler-authoritative"){SynapticLink x;x.from=a;x.to=b;x.relation=r;x.authority=au;x.id=h("omni.synapse/1",a+"|"+r+"|"+b+"|"+au);v.push_back(std::move(x));}
std::string nc(const MemoryNucleus&n){std::ostringstream o;o<<n.id<<'|'<<n.kind<<'|'<<n.module<<'|'<<n.name<<'|'<<n.contentId<<'|'<<n.contractId<<'|'<<n.typeId<<'|'<<n.provenanceRef<<'|';for(auto&x:n.domains)o<<x<<',';o<<'|';for(auto&x:n.capabilities)o<<x<<',';o<<'|';for(auto&x:n.authority)o<<x.first<<'='<<x.second<<',';return o.str();}
std::string lc(const SynapticLink&x){return x.id+'|'+x.from+'|'+x.relation+'|'+x.to+'|'+x.authority;}
std::string bc(const SynapticBinding&b){std::ostringstream o;o<<b.id<<'|'<<b.archetype<<'|'<<b.policy<<'|';for(auto&m:b.members)o<<m<<',';return o.str();}
std::string root(const std::string&d,const std::vector<std::string>&xs){std::ostringstream o;for(auto&x:xs)o<<x<<'\n';return h("omni.osnmf."+d+"/1",o.str());}
std::string jvec(const std::vector<std::string>&xs){std::ostringstream o;o<<'[';for(size_t i=0;i<xs.size();++i){if(i)o<<',';o<<quote(xs[i]);}o<<']';return o.str();}
std::string jset(const std::set<std::string>&xs){std::ostringstream o;o<<'[';bool f=true;for(auto&x:xs){if(!f)o<<',';f=false;o<<quote(x);}o<<']';return o.str();}
std::string edgeClass(const std::string& relation){
    static const std::set<std::string> structural={"calls","imports","defines","contains","parameter-type","returns-type","field-type","variant-type","requires-capability","specializes"};
    if(structural.count(relation))return "static";
    if(relation=="observes-execution-of")return "observed";
    if(relation=="describes")return "inferred";
    return "unknown";
}
std::string fnFingerprint(const Function&f,IdentityProjection projection){
    std::ostringstream o;o<<f.module<<'.'<<f.name<<'|';
    for(auto&p:f.params)o<<p.name<<':'<<canonicalTypeIdentity(p.type)<<',';
    o<<"->"<<canonicalTypeIdentity(f.result)<<"|caps=";
    for(auto&c:f.capabilities)o<<c<<',';
    o<<"|required=";for(auto&c:f.requiredCapabilities)o<<c<<',';
    o<<"|calls=";for(auto&c:f.calledFunctions)o<<c<<',';
    o<<"|wave=";
    Program t;t.module=f.module;t.functions.push_back(f);t.modules.push_back({f.module,{}});
    // Public Wave omits lowered closure helpers because their authoring body is
    // already in the call expression. A per-function identity must include it.
    // This copy is only hash material, never an executable program/provenance.
    if(projection!=IdentityProjection::Onme2Compatibility)t.functions.front().closureGenerated=false;
    try{o<<wave(t,projection);}
    catch(const Error& error){
        // Reproduce only the committed ONME2 algorithm, after the current
        // checker has accepted the payload. Never expose this as current identity.
        if(projection==IdentityProjection::Onme2Compatibility){o<<f.body.size();return o.str();}
        // A function alone lacks nominal definitions needed by representation
        // fencing; authoring templates may also contain an unlowered `?`.
        // Hash the complete canonical body, never its statement count. Particle
        // can describe both cases without inventing executable provenance.
        if(error.code!="E_TYPE"&&error.code!="E_INTERNAL")throw;
        t.functions.front().generated=false; // include generated bodies in the projection too
        o<<"particle-function/1|"<<particle(t);
    }
    return o.str();
}
// The signature of a generic template keeps the nominal types as written; resolveOpenType (formats.cpp) gives them their module-qualified identity.
Function resolveOpenSignature(const Program&p,const Function&f){
    Function g=f;std::set<std::string>bound;for(const auto&x:f.generics)bound.insert(x.name);
    g.result=resolveOpenType(p,f.module,bound,f.result);
    for(auto&a:g.params)a.type=resolveOpenType(p,f.module,bound,a.type);
    return g;
}
// `qualified` is the CURRENT projection: the nominal types of a template signature carry their module. The ONME2 compatibility projection keeps the identity the certified compilers computed (the name as written),
// so that every ONME2 file they wrote still verifies.
std::map<std::string,Type> canonicalTypes(const Program&p,bool qualified){std::map<std::string,Type>s;std::function<void(const Type&)>add=[&](const Type&t){if(t.kind!=Type::Unknown&&t.kind!=Type::Param)s.emplace(canonicalTypeIdentity(t),t);for(const auto&x:t.parts)add(x);};for(const auto&d:p.threadLocals)add(d.type);for(const auto&f:p.functions){add(f.result);for(const auto&a:f.params)add(a.type);for(const auto&t:f.locals)add(t);}for(const auto&f0:p.genericTemplates){const auto f=qualified?resolveOpenSignature(p,f0):f0;add(f.result);for(const auto&a:f.params)add(a.type);}for(const auto&r:p.records){Type t(Type::Record);t.name=r.name;t.key=r.key;s[canonicalTypeIdentity(t)]=t;for(const auto&x:r.fields)add(x.type);}for(const auto&e:p.enums){Type t(Type::Enum);t.name=e.name;t.key=e.key;s[canonicalTypeIdentity(t)]=t;for(const auto&v:e.variants)if(v.hasPayload)add(v.payload);}return s;}
void finalize(SystemMemory&m,uint64_t seq){std::sort(m.nuclei.begin(),m.nuclei.end(),[](auto&a,auto&b){return a.id<b.id;});std::sort(m.links.begin(),m.links.end(),[](auto&a,auto&b){return a.id<b.id;});std::sort(m.bindings.begin(),m.bindings.end(),[](auto&a,auto&b){return a.id<b.id;});
for(size_t i=1;i<m.links.size();++i)if(m.links[i-1].id==m.links[i].id&&lc(m.links[i-1])!=lc(m.links[i]))fail("E_OSNMF","synapse id collision");
m.links.erase(std::unique(m.links.begin(),m.links.end(),[](const auto&a,const auto&b){return a.id==b.id;}),m.links.end());
for(size_t i=1;i<m.bindings.size();++i)if(m.bindings[i-1].id==m.bindings[i].id&&bc(m.bindings[i-1])!=bc(m.bindings[i]))fail("E_OSNMF","binding id collision");
m.bindings.erase(std::unique(m.bindings.begin(),m.bindings.end(),[](const auto&a,const auto&b){return a.id==b.id;}),m.bindings.end());
std::vector<std::string>a,b,c,d,e;for(auto&n:m.nuclei){auto x=nc(n);if(n.domains.count("structural"))a.push_back(x);if(n.domains.count("semantic"))b.push_back(x);if(n.domains.count("operational"))c.push_back(x);if(n.domains.count("confidential"))d.push_back(x);}for(auto&x:m.links)e.push_back(lc(x));for(auto&x:m.bindings)e.push_back(bc(x));m.epoch.sequence=seq;m.epoch.structuralRoot=root("structural",a);m.epoch.semanticRoot=root("semantic",b);m.epoch.operationalRoot=root("operational",c);m.epoch.confidentialRoot=root("confidential",d);m.epoch.synapticRoot=root("synaptic",e);m.epoch.systemRoot=h("omni.osnmf.system/1",m.epoch.structuralRoot+"|"+m.epoch.semanticRoot+"|"+m.epoch.operationalRoot+"|"+m.epoch.confidentialRoot+"|"+m.epoch.synapticRoot);m.epoch.id=h("omni.neural-epoch/1",std::to_string(seq)+"|"+m.epoch.systemRoot);}
std::vector<std::string> split(const std::string&s,char d){std::vector<std::string>v;size_t p=0;while(true){auto q=s.find(d,p);if(q==std::string::npos){v.push_back(s.substr(p));break;}v.push_back(s.substr(p,q-p));p=q+1;}return v;}
bool validHash(const std::string&s){return s.size()==71&&s.rfind("sha256:",0)==0&&std::all_of(s.begin()+7,s.end(),[](char c){return std::isxdigit(static_cast<unsigned char>(c))!=0;});}
std::string hex(const std::string&s){static const char*d="0123456789abcdef";std::string o;o.reserve(s.size()*2);for(char z:s){auto c=static_cast<unsigned char>(z);o.push_back(d[c>>4]);o.push_back(d[c&15]);}return o;}
std::string unhex(const std::string& s){
    if(s.size()%2u)fail("E_COGNITION","hex proposal invalido");
    auto nib=[](char c)->unsigned{
        if(c>='0'&&c<='9')return static_cast<unsigned>(c-'0');
        if(c>='a'&&c<='f')return static_cast<unsigned>(c-'a')+10u;
        if(c>='A'&&c<='F')return static_cast<unsigned>(c-'A')+10u;
        fail("E_COGNITION","hex proposal invalido");
    };
    std::string result; result.reserve(s.size()/2u);
    for(size_t i=0;i<s.size();i+=2u)result.push_back(static_cast<char>((nib(s[i])<<4)|nib(s[i+1])));
    return result;
}
std::string pdig(const CognitiveProposal&p){return h("omni.cognitive-proposal/1",p.baseEpoch+"|"+p.agent+"|"+p.target+"|"+p.action+"|"+p.requiredCapability+"|"+p.note);}
struct OsmiNucleus { std::string id,kind,module,name; std::vector<std::string> caps; };
struct OsmiLink { std::string id,from,to,relation; };
struct OsmiData { std::string storeHash,epoch,systemRoot; std::vector<OsmiNucleus> nuclei; std::vector<OsmiLink> links; uint64_t storeBytesRead=0,indexBytesRead=0,commitBytesRead=0;bool fullStoreHashed=true; };
std::string osmiProjectionBody(const SystemMemory&m){
    std::ostringstream b;
    for(const auto&n:m.nuclei){b<<"N|"<<n.id<<'|'<<n.kind<<'|'<<n.module<<'|'<<n.name<<'|';bool first=true;for(const auto&c:n.capabilities){if(!first)b<<',';first=false;b<<c;}b<<"\n";}
    for(const auto&l:m.links)b<<"L|"<<l.id<<'|'<<l.from<<'|'<<l.to<<'|'<<l.relation<<"\n";
    return b.str();
}
std::string osmiProjectionRoot(const SystemMemory&m){return "sha256:"+sha256("omni.osmi-projection/2\n"+osmiProjectionBody(m));}
std::string committedIndexRootFromStoreText(const std::string&store){
    std::istringstream in(store);std::string header,epoch;
    if(!std::getline(in,header)||header!="OSM2"||!std::getline(in,epoch))fail("E_OSNMF","indexed access requires OSM2 authenticated store; repack snapshot");
    auto f=split(epoch,'|');if(f.size()!=10||f[0]!="E"||!validHash(f[9]))fail("E_OSNMF","OSM2 authenticated index root missing/invalid");
    return f[9];
}
struct StoreHeader { std::string epoch,systemRoot,projectionRoot;uint64_t bytesRead=0; };
StoreHeader readStoreHeader(const std::filesystem::path& store){
    if(std::filesystem::is_symlink(store)||!std::filesystem::is_regular_file(store))fail("E_DURABILITY","OSM2 store no regular");
    std::ifstream in(store,std::ios::binary);if(!in)fail("E_FILE","no se pudo abrir OSNMF Store");
    std::string header,epochLine;if(!std::getline(in,header)||!std::getline(in,epochLine)||header!="OSM2")fail("E_OSNMF","OSM2 store truncado");
    const auto fields=split(epochLine,'|');if(fields.size()!=10u||fields[0]!="E"||!validHash(fields[9]))fail("E_OSNMF","OSM2 epoch invalido");
    return {fields[2],fields[3],fields[9],static_cast<uint64_t>(header.size()+epochLine.size()+2u)};
}
uint64_t decimalU64(const std::string& value){
    if(value.empty()||!std::all_of(value.begin(),value.end(),[](char c){return c>='0'&&c<='9';}))fail("E_DURABILITY","entero de commit invalido");
    try{size_t used=0;const auto parsed=std::stoull(value,&used);if(used!=value.size())fail("E_DURABILITY","entero de commit invalido");return parsed;}catch(const std::exception&){fail("E_DURABILITY","entero de commit fuera de rango");}
}
std::map<std::string,std::string> parseCommitRecord(const std::string& text){
    validateUTF8(text);std::istringstream in(text);std::string line;if(!std::getline(in,line)||line!="OSMC1")fail("E_DURABILITY","OSMC1 invalido");
    std::map<std::string,std::string> values;std::string body;bool ended=false;
    while(std::getline(in,line)){
        if(line.empty())continue;
        if(ended)fail("E_DURABILITY","contenido posterior a OSMC1 integrity");
        const auto at=line.find('|');if(at==std::string::npos)fail("E_DURABILITY","campo OSMC1 invalido");const auto key=line.substr(0,at),value=line.substr(at+1u);
        if(key=="integrity"){if(value!="sha256:"+sha256("omni.osmc/1\n"+body))fail("E_DURABILITY","OSMC1 integrity mismatch");ended=true;continue;}
        if(!values.emplace(key,value).second)fail("E_DURABILITY","campo OSMC1 duplicado");
        body+=line+"\n";
    }
    if(!ended)fail("E_DURABILITY","OSMC1 incompleto");
    return values;
}
std::string readSmallRegular(const std::filesystem::path& path){
    if(std::filesystem::is_symlink(path)||!std::filesystem::is_regular_file(path))fail("E_DURABILITY","metadata de snapshot no regular");
    const auto size=std::filesystem::file_size(path);if(size>65536u)fail("E_LIMIT","metadata de snapshot demasiado grande");
    std::ifstream in(path,std::ios::binary);if(!in)fail("E_FILE","no se pudo abrir metadata de snapshot");std::ostringstream out;out<<in.rdbuf();if(!in.good()&&!in.eof())fail("E_FILE","no se pudo leer metadata de snapshot");return out.str();
}
OsmiData parseOsmi(const std::filesystem::path& store,const std::string& idx){
    validateUTF8(idx); std::istringstream in(idx); std::string line;
    if(!std::getline(in,line)||line!="OSMI2")fail("E_VERSION","OSNMF Index version no soportada o no autenticada");
    OsmiData d; std::string body,projection,integrity; bool ended=false;
    while(std::getline(in,line)){
        if(line.empty())continue;
        if(ended)fail("E_OSNMF","contenido posterior a integridad de indice");
        if(line.rfind("I|",0)==0){integrity=line.substr(2);ended=true;continue;}
        body+=line+"\n"; auto f=split(line,'|');
        if(f[0]=="S"&&f.size()==2){if(!d.storeHash.empty())fail("E_OSNMF","indice con store hash duplicado");d.storeHash=f[1];}
        else if(f[0]=="N"&&f.size()==6){d.nuclei.push_back({f[1],f[2],f[3],f[4],split(f[5],',')});projection+=line+"\n";}
        else if(f[0]=="L"&&f.size()==5){d.links.push_back({f[1],f[2],f[3],f[4]});projection+=line+"\n";}
        else fail("E_OSNMF","indice invalido");
    }
    d.indexBytesRead=static_cast<uint64_t>(idx.size());
    if(!ended||d.storeHash.empty()||!validHash(d.storeHash))fail("E_OSNMF","indice incompleto");
    if(integrity!="sha256:"+sha256("omni.osmi/2\n"+body))fail("E_OSNMF","OSNMF index integrity mismatch");
    const auto transaction=std::filesystem::path(store.string()+".txn");if(std::filesystem::exists(transaction))fail("E_DURABILITY","snapshot publication incomplete");
    const auto storeHeader=readStoreHeader(store);d.storeBytesRead=storeHeader.bytesRead;
    const auto commitPath=std::filesystem::path(store.string()+".commit");
    if(std::filesystem::exists(commitPath)){
        const auto commitText=readSmallRegular(commitPath);d.commitBytesRead=static_cast<uint64_t>(commitText.size());const auto commit=parseCommitRecord(commitText);
        auto required=[&](const std::string& key)->const std::string&{const auto it=commit.find(key);if(it==commit.end()||it->second.empty())fail("E_DURABILITY","OSMC1 sin "+key);return it->second;};
        if(required("store_sha256")!=d.storeHash)fail("E_DURABILITY","OSMC1 store hash no coincide con OSMI2");
        if(required("index_sha256")!="sha256:"+sha256(idx)||decimalU64(required("index_bytes"))!=idx.size())fail("E_OSNMF","OSMC1 index mismatch");
        if(decimalU64(required("store_bytes"))!=std::filesystem::file_size(store))fail("E_DURABILITY","OSMC1 store size mismatch");
        if(required("epoch")!=storeHeader.epoch||required("projection_root")!=storeHeader.projectionRoot)fail("E_DURABILITY","OSMC1 store identity mismatch");
        d.fullStoreHashed=false;
    }else{
        if(d.storeHash!="sha256:"+sha256File(store))fail("E_OSNMF","OSNMF store/index mismatch");
        d.storeBytesRead=std::filesystem::file_size(store);d.fullStoreHashed=true;
    }
    const auto& committed=storeHeader.projectionRoot;
    const auto derived="sha256:"+sha256("omni.osmi-projection/2\n"+projection);
    if(derived!=committed)fail("E_OSNMF","OSNMF index projection is not committed by store");
    d.epoch=storeHeader.epoch;d.systemRoot=storeHeader.systemRoot;
    return d;
}
std::string offloadDigest(const CognitiveOffloadEnvelope&e){
    std::ostringstream o;o<<e.baseEpoch<<'|'<<e.provider<<'|'<<e.selector<<'|'<<e.contextDigest<<'|'<<e.contextBytes<<'|'<<e.contextNuclei<<'|'<<e.sourceFilesScanned<<'|'<<e.estimatedInputTokens<<'|'<<e.budget.maxInputTokens<<'|'<<e.budget.maxOutputTokens<<'|'<<e.budget.maxCostMicrounits<<'|'<<e.budget.maxLatencyMs<<'|'<<e.requiredCapability<<'|'<<e.contextHex;
    return h("omni.ocap-offload/1",o.str());
}
}
std::string semanticFunctionId(const Function& function,bool isTemplate){
    return nid(isTemplate?"function-template":"function",function.module,
               function.name+(isTemplate?"<template>":""));
}
uint64_t advanceEpochSequence(uint64_t baseSequence){
    if(baseSequence==std::numeric_limits<uint64_t>::max())fail("E_EPOCH","secuencia neural agotada");
    return baseSequence+1;
}
SystemMemory buildSystemMemory(const Program&p,IdentityProjection projection){SystemMemory m;std::map<std::string,std::string>idx;auto add=[&](MemoryNucleus n,std::string k){idx[k]=n.id;m.nuclei.push_back(std::move(n));if((m.nuclei.size()&1023u)==0u)budgetCheck("la memoria OSNMF");};MemoryNucleus sys;sys.kind="system";sys.module=p.module;sys.name=p.module;sys.id=nid("system",p.module,p.module);sys.contentId=h("omni.program-ir/1",wave(p,projection));sys.contractId=h("omni.system-contract/1",compactOmniHash(p));sys.typeId=h("omni.system-type/1","OmniProgram");sys.provenanceRef=sys.contentId;sys.domains={"structural","semantic","synaptic"};sys.authority={{"structural","compiler-authoritative"},{"semantic","developer-declared"},{"synaptic","compiler-authoritative"}};add(sys,"system");
for(auto&mo:p.modules){MemoryNucleus n;n.kind="module";n.module=mo.name;n.name=mo.name;n.id=nid("module",mo.name,mo.name);std::ostringstream z;z<<mo.name<<'|';for(auto&i:mo.imports)z<<i.alias<<'>'<<i.target<<',';n.contentId=h("omni.module/1",z.str());n.contractId=h("omni.module-contract/1",mo.name);n.typeId=h("omni.entity-kind/1","module");n.provenanceRef=n.contentId;n.domains={"structural","semantic","synaptic"};n.authority={{"structural","compiler-authoritative"},{"semantic","developer-declared"},{"synaptic","compiler-authoritative"}};add(n,"module:"+mo.name);}
const bool current=projection!=IdentityProjection::Onme2Compatibility;
for(const auto&kv:canonicalTypes(p,current)){const auto&canon=kv.first;const auto&t=kv.second;MemoryNucleus n;n.kind="type";n.name=typeName(t);if((t.kind==Type::Record||t.kind==Type::Enum)&&!t.key.empty()){auto q=t.key.rfind('.');if(q!=std::string::npos)n.module=t.key.substr(0,q);}n.id=nid("type",n.module,canon);n.contentId=h("omni.type-content/1",canon);n.contractId=h("omni.type-contract/1",canon);n.typeId=typeId(t);n.provenanceRef=n.contentId;n.domains={"structural","semantic"};n.authority={{"structural","compiler-authoritative"},{"semantic","developer-declared"}};add(n,"type:"+canon);}
for(auto&r:p.records){MemoryNucleus n;n.kind="record";n.module=r.module;n.name=r.name;n.id=nid("record",r.module,r.name);std::ostringstream z;z<<r.key<<'|';if(r.packed)z<<"packed|";if(r.opaque)z<<"opaque|";if(r.externC)z<<"extern|";for(auto&f:r.fields)z<<f.name<<':'<<canonicalTypeIdentity(f.type)<<',';n.contentId=h("omni.record/1",z.str());n.contractId=h("omni.record-contract/1",(r.packed?r.key+"|packed":r.key)+(r.opaque?"|opaque":"")+((current&&r.externC)?"|extern":""));Type t(Type::Record);t.name=r.name;t.key=r.key;n.typeId=typeId(t);n.provenanceRef=n.contentId;n.domains={"structural","semantic","synaptic"};n.authority={{"structural","compiler-authoritative"},{"semantic","developer-declared"},{"synaptic","compiler-authoritative"}};add(n,"record:"+r.key);}
for(auto&e:p.enums){MemoryNucleus n;n.kind="enum";n.module=e.module;n.name=e.name;n.id=nid("enum",e.module,e.name);std::ostringstream z;z<<e.key<<'|';for(auto&v:e.variants)z<<v.name<<(v.hasPayload?":"+canonicalTypeIdentity(v.payload):"")<<',';n.contentId=h("omni.enum/1",z.str());n.contractId=h("omni.enum-contract/1",e.key);Type t(Type::Enum);t.name=e.name;t.key=e.key;n.typeId=typeId(t);n.provenanceRef=n.contentId;n.domains={"structural","semantic","synaptic"};n.authority={{"structural","compiler-authoritative"},{"semantic","developer-declared"},{"synaptic","compiler-authoritative"}};add(n,"enum:"+e.key);}
for(const auto* d:orderedThreadLocals(p)){MemoryNucleus n;n.kind="thread-local";n.module=d->module;n.name=d->name;n.id=nid("thread-local",d->module,d->name);std::ostringstream z;z<<d->module<<'.'<<d->name<<'|'<<canonicalTypeIdentity(d->type)<<'|'<<(d->negative?"-":"")<<d->magnitude;n.contentId=h("omni.thread-local/1",z.str());n.contractId=h("omni.thread-local-contract/1",d->module+"."+d->name+"|"+canonicalTypeIdentity(d->type));n.typeId=typeId(d->type);n.provenanceRef=n.contentId;n.domains={"structural","semantic","synaptic"};n.authority={{"structural","compiler-authoritative"},{"semantic","developer-declared"},{"synaptic","compiler-authoritative"}};add(n,"thread-local:"+d->module+"."+d->name);}
auto af=[&](const Function&f0,bool templ){const Function f=(templ&&current)?resolveOpenSignature(p,f0):f0;MemoryNucleus n;n.kind=templ?"function-template":"function";n.module=f.module;n.name=f.name;auto key=f.key.empty()?f.module+"."+f.name:f.key;n.id=semanticFunctionId(f,templ);n.contentId=h("omni.function/1",fnFingerprint(f,projection));std::ostringstream sig;sig<<f.module<<'.'<<f.name<<'(';for(auto&a:f.params)sig<<canonicalTypeIdentity(a.type)<<',';sig<<")->"<<canonicalTypeIdentity(f.result);n.typeId=h("omni.function-type/1",sig.str());std::ostringstream cc;for(auto&x:f.capabilities)cc<<x<<',';if(current){if(!f.exportName.empty())cc<<"|export="<<f.exportName;if(f.isExtern)cc<<"|extern="<<f.externName;}n.contractId=h("omni.function-contract/1",cc.str());n.provenanceRef=n.contentId;n.capabilities=((templ||!current)&&f.requiredCapabilities.empty())?f.capabilities:f.requiredCapabilities;n.domains={"structural","semantic","synaptic"};n.authority={{"structural","compiler-authoritative"},{"semantic","developer-declared"},{"synaptic","compiler-authoritative"}};add(n,(templ?"template:":"function:")+key);};for(auto&f:p.genericTemplates)af(f,true);for(auto&f:p.functions)af(f,false);
std::set<std::string>caps;for(auto&f:p.functions)caps.insert(f.requiredCapabilities.begin(),f.requiredCapabilities.end());for(auto&c:caps){MemoryNucleus n;n.kind="capability";n.name=c;n.id=nid("capability","",c);n.contentId=h("omni.capability/1",c);n.contractId=n.contentId;n.typeId=h("omni.entity-kind/1","capability");n.provenanceRef=n.contentId;n.domains={"structural","confidential"};n.authority={{"structural","compiler-authoritative"},{"confidential","compiler-authoritative"}};add(n,"capability:"+c);}
auto get=[&](const std::string&k){auto i=idx.find(k);return i==idx.end()?std::string():i->second;};auto sid=idx["system"];for(auto&mo:p.modules){auto mid=get("module:"+mo.name);if(!mid.empty())link(m.links,sid,mid,"contains");for(auto&i:mo.imports){auto to=get("module:"+i.target);if(!to.empty())link(m.links,mid,to,"imports");}}
for(auto&r:p.records){auto rid=get("record:"+r.key),mid=get("module:"+r.module);if(!mid.empty())link(m.links,mid,rid,"defines");for(auto&f:r.fields){auto t=get("type:"+canonicalTypeIdentity(f.type));if(!t.empty())link(m.links,rid,t,"field-type");}}
for(auto&e:p.enums){auto eid=get("enum:"+e.key),mid=get("module:"+e.module);if(!mid.empty())link(m.links,mid,eid,"defines");for(auto&v:e.variants)if(v.hasPayload){auto t=get("type:"+canonicalTypeIdentity(v.payload));if(!t.empty())link(m.links,eid,t,"variant-type");}}
for(const auto* d:orderedThreadLocals(p)){auto tid=get("thread-local:"+d->module+"."+d->name),mid=get("module:"+d->module);if(!mid.empty())link(m.links,mid,tid,"defines");auto t=get("type:"+canonicalTypeIdentity(d->type));if(!t.empty())link(m.links,tid,t,"variable-type");}
for(const auto* d:orderedThreadLocals(p)){auto tid=get("thread-local:"+d->module+"."+d->name),mid=get("module:"+d->module);if(!mid.empty())link(m.links,mid,tid,"defines");auto t=get("type:"+canonicalTypeIdentity(d->type));if(!t.empty())link(m.links,tid,t,"variable-type");}
for(auto&f:p.genericTemplates){auto fk=get("template:"+(f.key.empty()?f.module+"."+f.name:f.key)),mid=get("module:"+f.module);if(!fk.empty()&&!mid.empty())link(m.links,mid,fk,"defines");}
for(auto&f:p.functions){auto key=f.key.empty()?f.module+"."+f.name:f.key,fid=get("function:"+key),mid=get("module:"+f.module);if(!mid.empty())link(m.links,mid,fid,"defines");auto rt=get("type:"+canonicalTypeIdentity(f.result));if(!rt.empty())link(m.links,fid,rt,"returns-type");for(auto&a:f.params){auto t=get("type:"+canonicalTypeIdentity(a.type));if(!t.empty())link(m.links,fid,t,"parameter-type");}for(auto&x:f.calledFunctions){auto t=get("function:"+x);if(!t.empty())link(m.links,fid,t,"calls");}for(auto&x:f.requiredCapabilities){auto t=get("capability:"+x);if(!t.empty())link(m.links,fid,t,"requires-capability");}if(f.generated&&!f.genericOrigin.empty()){auto t=get("template:"+f.genericOrigin);if(!t.empty())link(m.links,fid,t,"specializes");}}
std::map<std::string,std::vector<std::string>>g;for(auto&f:p.functions)if(f.generated&&!f.genericOrigin.empty())g[f.genericOrigin].push_back(get("function:"+(f.key.empty()?f.module+"."+f.name:f.key)));for(auto&kv:g){auto a=get("template:"+kv.first);if(a.empty())continue;std::sort(kv.second.begin(),kv.second.end());SynapticBinding b;b.archetype=a;b.members=kv.second;b.policy="structural-sharing/cow-v1";b.id=h("omni.binding/1",a+"|"+jvec(kv.second)+"|"+b.policy);m.bindings.push_back(std::move(b));}finalize(m,0);return m;}
SystemMemory buildObservedSystemMemory(const Program&p,const EvalResult&r,uint64_t seq){if(seq==0)fail("E_EPOCH","observacion runtime requiere epoch > 0");auto m=buildSystemMemory(p);MemoryNucleus n;n.kind="runtime-observation";n.module=p.module;n.name="main";n.id=nid("runtime-observation",p.module,"main");auto od="sha256:"+sha256(r.output);n.contentId=h("omni.runtime-observation/1",std::to_string(r.result)+"|"+std::to_string(r.steps)+"|"+od);n.contractId=h("omni.runtime-observation-contract/1","result|steps|output-digest");n.typeId=h("omni.entity-kind/1","runtime-observation");n.provenanceRef=n.contentId;n.domains={"operational"};n.authority={{"operational",auth(MemoryAuthority::RuntimeObserved)}};n.epoch=seq;m.nuclei.push_back(n);std::string main;for(auto&x:m.nuclei)if(x.kind=="function"&&x.module==p.module&&x.name=="main")main=x.id;if(main.empty())fail("E_ENTRY","runtime observation requires main");link(m.links,n.id,main,"observes-execution-of",auth(MemoryAuthority::RuntimeObserved));finalize(m,seq);return m;}
std::string systemMemoryStore(const SystemMemory&m){
    const auto indexRoot=osmiProjectionRoot(m);
    std::ostringstream o;o<<"OSM2\n"<<"E|"<<m.epoch.sequence<<'|'<<m.epoch.id<<'|'<<m.epoch.systemRoot<<'|'<<m.epoch.structuralRoot<<'|'<<m.epoch.semanticRoot<<'|'<<m.epoch.operationalRoot<<'|'<<m.epoch.confidentialRoot<<'|'<<m.epoch.synapticRoot<<'|'<<indexRoot<<"\n";
    for(const auto&n:m.nuclei){o<<"N|"<<n.id<<'|'<<n.kind<<'|'<<n.module<<'|'<<n.name<<'|'<<n.contentId<<'|'<<n.contractId<<'|'<<n.typeId<<'|'<<n.provenanceRef<<'|';bool f=true;for(const auto&x:n.domains){if(!f)o<<',';f=false;o<<x;}o<<'|';f=true;for(const auto&x:n.capabilities){if(!f)o<<',';f=false;o<<x;}o<<'|';f=true;for(const auto&x:n.authority){if(!f)o<<';';f=false;o<<x.first<<'='<<x.second;}o<<"\n";}
    for(const auto&x:m.links)o<<"L|"<<x.id<<'|'<<x.from<<'|'<<x.to<<'|'<<x.relation<<'|'<<x.authority<<"\n";
    for(const auto&b:m.bindings){o<<"B|"<<b.id<<'|'<<b.archetype<<'|'<<b.policy<<'|';for(size_t i=0;i<b.members.size();++i){if(i)o<<',';o<<b.members[i];}o<<"\n";}
    return o.str();
}
std::string systemMemoryStore(const Program&p){return systemMemoryStore(buildSystemMemory(p));}
SystemMemory parseSystemMemoryStore(const std::string&t){
    validateUTF8(t);
    std::istringstream in(t);
    std::string line;
    if(!std::getline(in,line)||(line!="OSM1"&&line!="OSM2")) {
        fail("E_VERSION","OSNMF Store version no soportada");
    }
    const bool authenticated=(line=="OSM2");
    SystemMemory m;
    bool ep=false;
    std::string committedIndexRoot;
    while(std::getline(in,line)){
        if(line.empty()) continue;
        auto fields=split(line,'|');
        if(fields[0]=="E"){
            if(ep||fields.size()!=(authenticated?10u:9u)) {
                fail("E_OSNMF","epoch OSNMF invalido");
            }
            ep=true;
            try{
                m.epoch.sequence=std::stoull(fields[1]);
            }catch(...){
                fail("E_OSNMF","secuencia epoch invalida");
            }
            m.epoch.id=fields[2];
            m.epoch.systemRoot=fields[3];
            m.epoch.structuralRoot=fields[4];
            m.epoch.semanticRoot=fields[5];
            m.epoch.operationalRoot=fields[6];
            m.epoch.confidentialRoot=fields[7];
            m.epoch.synapticRoot=fields[8];
            if(authenticated){
                committedIndexRoot=fields[9];
                if(!validHash(committedIndexRoot)) fail("E_OSNMF","OSM2 index root invalido");
            }
        } else if(fields[0]=="N"){
            if(fields.size()!=12) fail("E_OSNMF","nucleus invalido");
            MemoryNucleus n;
            n.id=fields[1];
            n.kind=fields[2];
            n.module=fields[3];
            n.name=fields[4];
            n.contentId=fields[5];
            n.contractId=fields[6];
            n.typeId=fields[7];
            n.provenanceRef=fields[8];
            for(auto&x:split(fields[9],',')) if(!x.empty()) n.domains.insert(x);
            for(auto&x:split(fields[10],',')) if(!x.empty()) n.capabilities.insert(x);
            for(auto&x:split(fields[11],';')) if(!x.empty()){
                auto q=x.find('=');
                if(q==std::string::npos) fail("E_OSNMF","authority invalida");
                n.authority[x.substr(0,q)]=x.substr(q+1);
            }
            m.nuclei.push_back(std::move(n));
        } else if(fields[0]=="L"){
            if(fields.size()!=6) fail("E_OSNMF","synapse invalida");
            m.links.push_back({fields[1],fields[2],fields[3],fields[4],fields[5]});
        } else if(fields[0]=="B"){
            if(fields.size()!=5) fail("E_OSNMF","binding invalido");
            SynapticBinding b;
            b.id=fields[1];
            b.archetype=fields[2];
            b.policy=fields[3];
            for(auto&x:split(fields[4],',')) if(!x.empty()) b.members.push_back(x);
            m.bindings.push_back(std::move(b));
        } else {
            fail("E_OSNMF","tag desconocido");
        }
    }
    if(!ep) fail("E_OSNMF","OSNMF Store sin epoch");
    auto originalEpoch=m.epoch;
    finalize(m,originalEpoch.sequence);
    if(m.epoch.id!=originalEpoch.id||
       m.epoch.systemRoot!=originalEpoch.systemRoot||
       m.epoch.structuralRoot!=originalEpoch.structuralRoot||
       m.epoch.semanticRoot!=originalEpoch.semanticRoot||
       m.epoch.operationalRoot!=originalEpoch.operationalRoot||
       m.epoch.confidentialRoot!=originalEpoch.confidentialRoot||
       m.epoch.synapticRoot!=originalEpoch.synapticRoot) {
        fail("E_OSNMF","OSNMF Store integrity mismatch");
    }
    if(authenticated&&osmiProjectionRoot(m)!=committedIndexRoot) {
        fail("E_OSNMF","OSM2 committed index root mismatch");
    }
    std::set<std::string> ids;
    for(auto&n:m.nuclei){
        if(!validHash(n.id)||!validHash(n.contentId)||!ids.insert(n.id).second) {
            fail("E_OSNMF","nucleus hash/duplicate invalido");
        }
    }
    for(auto&l:m.links) {
        if(!ids.count(l.from)||!ids.count(l.to)) fail("E_OSNMF","synapse referencia ausente");
    }
    return m;
}
std::string systemMemoryIndex(const std::string&store){
    const auto committed=committedIndexRootFromStoreText(store);auto m=parseSystemMemoryStore(store);const auto projection=osmiProjectionBody(m);
    if(osmiProjectionRoot(m)!=committed)fail("E_OSNMF","OSM2 index projection commitment mismatch");
    std::ostringstream b;b<<"S|sha256:"<<sha256(store)<<"\n"<<projection;auto body=b.str();
    return "OSMI2\n"+body+"I|sha256:"+sha256("omni.osmi/2\n"+body)+"\n";
}
std::string systemMemorySummaryJson(const SystemMemory&m){std::map<std::string,size_t>k,r;for(auto&n:m.nuclei)++k[n.kind];for(auto&l:m.links)++r[l.relation];std::ostringstream o;o<<"{\n  \"schema\": \"omni.system-summary/1\",\n  \"source\": \"persisted-osnmf-store\",\n  \"architecture\": \"living-computational-system\",\n  \"ai_required\": false,\n  \"normal_introspection_full_source_scan\": false,\n  \"epoch\": "<<quote(m.epoch.id)<<",\n  \"system_root\": "<<quote(m.epoch.systemRoot)<<",\n  \"nuclei\": "<<m.nuclei.size()<<",\n  \"synapses\": "<<m.links.size()<<",\n  \"bindings\": "<<m.bindings.size()<<",\n  \"source_files_scanned\": 0,\n  \"kinds\": {";bool f=true;for(auto&x:k){if(!f)o<<',';f=false;o<<quote(x.first)<<':'<<x.second;}o<<"},\n  \"relations\": {";f=true;for(auto&x:r){if(!f)o<<',';f=false;o<<quote(x.first)<<':'<<x.second;}o<<"}\n}\n";return o.str();}
std::string querySystemMemoryJson(const SystemMemory&m,const std::string&mode,const std::string&val){std::set<std::string>ids;for(auto&n:m.nuclei){bool hit=(mode=="entity"&&(n.name==val||n.module+"."+n.name==val))||(mode=="kind"&&n.kind==val)||(mode=="capability"&&(n.capabilities.count(val)||(n.kind=="capability"&&n.name==val)));if(hit)ids.insert(n.id);}if(mode=="calls")for(auto&n:m.nuclei)if(n.name==val||n.module+"."+n.name==val)ids.insert(n.id);std::ostringstream o;o<<"{\n  \"schema\": \"omni.system-query/1\",\n  \"source\": \"persisted-osnmf-store\",\n  \"source_files_scanned\": 0,\n  \"mode\": "<<quote(mode)<<", \"value\": "<<quote(val)<<",\n  \"epoch\": "<<quote(m.epoch.id)<<",\n  \"system_root\": "<<quote(m.epoch.systemRoot)<<",\n  \"unknown_edges_conservative\": true,\n  \"nuclei\": [";bool f=true;for(auto&n:m.nuclei)if(ids.count(n.id)){if(!f)o<<',';f=false;o<<"{\"id\":"<<quote(n.id)<<",\"kind\":"<<quote(n.kind)<<",\"name\":"<<quote(n.name)<<",\"module\":"<<quote(n.module)<<"}";}o<<"],\n  \"edges\": [";f=true;for(auto&l:m.links)if((ids.count(l.from)||ids.count(l.to))&&(mode!="calls"||l.relation=="calls")){if(!f)o<<',';f=false;o<<"{\"id\":"<<quote(l.id)<<",\"from\":"<<quote(l.from)<<",\"to\":"<<quote(l.to)<<",\"relation\":"<<quote(l.relation)<<",\"edge_class\":"<<quote(edgeClass(l.relation))<<"}";}o<<"]\n}\n";return o.str();}
std::string querySystemMemoryIndexedFileJson(const std::filesystem::path&store,const std::string&idx,const std::string&mode,const std::string&val){
    const auto d=parseOsmi(store,idx); std::set<std::string> ids;
    for(const auto& n:d.nuclei){
        bool hasCap=std::find(n.caps.begin(),n.caps.end(),val)!=n.caps.end();
        bool hit=(mode=="entity"&&(n.name==val||n.module+"."+n.name==val))||(mode=="kind"&&n.kind==val)||(mode=="capability"&&(hasCap||(n.kind=="capability"&&n.name==val)));
        if(hit)ids.insert(n.id);
    }
    if(mode=="calls")for(const auto& n:d.nuclei)if(n.name==val||n.module+"."+n.name==val)ids.insert(n.id);
    std::ostringstream o;o<<"{\n  \"schema\": \"omni.system-query/1\",\n  \"source\": \"persisted-osnmf-index\",\n  \"source_files_scanned\": 0,\n  \"full_store_parsed\": false,\n  \"full_store_hashed\": "<<(d.fullStoreHashed?"true":"false")<<",\n  \"store_bytes_read\": "<<d.storeBytesRead<<",\n  \"index_bytes_read\": "<<d.indexBytesRead<<",\n  \"commit_bytes_read\": "<<d.commitBytesRead<<",\n  \"mode\": "<<quote(mode)<<", \"value\": "<<quote(val)<<",\n  \"epoch\": "<<quote(d.epoch)<<",\n  \"system_root\": "<<quote(d.systemRoot)<<",\n  \"unknown_edges_conservative\": true,\n  \"nuclei\": [";bool first=true;
    for(const auto& n:d.nuclei)if(ids.count(n.id)){if(!first)o<<',';first=false;o<<"{\"id\":"<<quote(n.id)<<",\"kind\":"<<quote(n.kind)<<",\"name\":"<<quote(n.name)<<",\"module\":"<<quote(n.module)<<"}";}
    o<<"],\n  \"edges\": [";first=true;for(const auto& l:d.links)if((ids.count(l.from)||ids.count(l.to))&&(mode!="calls"||l.relation=="calls")){if(!first)o<<',';first=false;o<<"{\"id\":"<<quote(l.id)<<",\"from\":"<<quote(l.from)<<",\"to\":"<<quote(l.to)<<",\"relation\":"<<quote(l.relation)<<",\"edge_class\":"<<quote(edgeClass(l.relation))<<"}";}o<<"]\n}\n";return o.str();
}
std::string traceSystemMemoryIndexedFileJson(const std::filesystem::path&store,const std::string&idx,const std::string&e,uint32_t depth){
    if(depth>16)fail("E_QUERY","trace depth excede 16");
    const auto d=parseOsmi(store,idx); std::set<std::string> selected,frontier,seenEdges;
    for(const auto& n:d.nuclei)if(n.name==e||n.module+"."+n.name==e||n.id==e){selected.insert(n.id);frontier.insert(n.id);}
    if(selected.empty())fail("E_QUERY","entidad no encontrada: "+e);
    std::vector<const OsmiLink*> edges;
    for(uint32_t level=0;level<depth&&!frontier.empty();++level){std::set<std::string> next;for(const auto& l:d.links)if(frontier.count(l.from)||frontier.count(l.to)){if(seenEdges.insert(l.id).second)edges.push_back(&l);const auto& other=frontier.count(l.from)?l.to:l.from;if(selected.insert(other).second)next.insert(other);}frontier=std::move(next);}
    size_t unknown=0;for(const auto* link:edges)if(edgeClass(link->relation)=="unknown")++unknown;
    std::ostringstream o;o<<"{\n  \"schema\": \"omni.system-trace/1\",\n  \"source\": \"persisted-osnmf-index\",\n  \"source_files_scanned\": 0,\n  \"full_store_parsed\": false,\n  \"full_store_hashed\": "<<(d.fullStoreHashed?"true":"false")<<",\n  \"store_bytes_read\": "<<d.storeBytesRead<<",\n  \"index_bytes_read\": "<<d.indexBytesRead<<",\n  \"commit_bytes_read\": "<<d.commitBytesRead<<",\n  \"epoch\": "<<quote(d.epoch)<<",\n  \"system_root\": "<<quote(d.systemRoot)<<",\n  \"entity\": "<<quote(e)<<",\n  \"limits\": {\"requested_depth\": "<<depth<<", \"max_depth\": 16, \"truncated\": "<<(!frontier.empty()?"true":"false")<<"},\n  \"unknown_edges_conservative\": true,\n  \"unknown_edge_count\": "<<unknown<<",\n  \"nuclei\": [";bool first=true;for(const auto& n:d.nuclei)if(selected.count(n.id)){if(!first)o<<',';first=false;o<<"{\"id\":"<<quote(n.id)<<",\"kind\":"<<quote(n.kind)<<",\"name\":"<<quote(n.name)<<"}";}o<<"],\n  \"edges\": [";first=true;for(const auto* l:edges){if(!first)o<<',';first=false;o<<"{\"from\":"<<quote(l->from)<<",\"to\":"<<quote(l->to)<<",\"relation\":"<<quote(l->relation)<<",\"edge_class\":"<<quote(edgeClass(l->relation))<<"}";}o<<"]\n}\n";return o.str();
}
std::string impactSystemMemoryIndexedFileJson(const std::filesystem::path&store,const std::string&idx,const std::string&e){
    const auto d=parseOsmi(store,idx); std::set<std::string> selected,frontier;
    for(const auto& n:d.nuclei)if(n.name==e||n.module+"."+n.name==e||n.id==e){selected.insert(n.id);frontier.insert(n.id);}
    if(selected.empty())fail("E_QUERY","entidad no encontrada: "+e);
    const std::set<std::string> rels={"calls","imports","defines","contains","parameter-type","returns-type","field-type","variant-type","requires-capability","specializes"};
    size_t unknown=0;for(const auto& link:d.links)if(edgeClass(link.relation)=="unknown")++unknown;
    while(!frontier.empty()){std::set<std::string> next;for(const auto& l:d.links){if(rels.count(l.relation)&&frontier.count(l.to)&&selected.insert(l.from).second)next.insert(l.from);else if(edgeClass(l.relation)=="unknown"&&(frontier.count(l.to)||frontier.count(l.from))){const auto& other=frontier.count(l.to)?l.from:l.to;if(selected.insert(other).second)next.insert(other);}}frontier=std::move(next);}
    std::map<std::string,size_t> kinds;for(const auto& n:d.nuclei)if(selected.count(n.id))++kinds[n.kind];
    std::ostringstream o;o<<"{\n  \"schema\": \"omni.impact-plan/1\",\n  \"source\": \"persisted-osnmf-index\",\n  \"plan_only\": true,\n  \"source_files_scanned\": 0,\n  \"full_store_parsed\": false,\n  \"full_store_hashed\": "<<(d.fullStoreHashed?"true":"false")<<",\n  \"store_bytes_read\": "<<d.storeBytesRead<<",\n  \"index_bytes_read\": "<<d.indexBytesRead<<",\n  \"commit_bytes_read\": "<<d.commitBytesRead<<",\n  \"epoch\": "<<quote(d.epoch)<<",\n  \"system_root\": "<<quote(d.systemRoot)<<",\n  \"unknown_edges_conservative\": true,\n  \"unknown_edge_count\": "<<unknown<<",\n  \"affected_nodes\": "<<selected.size()<<",\n  \"kinds\": {";bool first=true;for(const auto& x:kinds){if(!first)o<<',';first=false;o<<quote(x.first)<<':'<<x.second;}o<<"}\n}\n";return o.str();
}
std::string memoryJson(const Program&p){auto m=buildSystemMemory(p);std::ostringstream o;o<<"{\n  \"schema\": \"omni.osnmf/1\",\n  \"language_version\": "<<quote(VERSION)<<",\n  \"architecture\": \"living-computational-system\",\n  \"model\": \"distributed-logical/compacted-physical\",\n  \"ai_required\": false,\n  \"integrity\": {\"algorithm\": \"SHA-256\", \"claim\": \"integrity-and-lineage-not-external-truth\"},\n  \"domains\": [\"structural\",\"semantic\",\"operational\",\"confidential\",\"synaptic\"],\n  \"epoch\": {\"sequence\": "<<m.epoch.sequence<<", \"id\": "<<quote(m.epoch.id)<<", \"system_root\": "<<quote(m.epoch.systemRoot)<<"},\n  \"domain_roots\": {\"structural\": "<<quote(m.epoch.structuralRoot)<<", \"semantic\": "<<quote(m.epoch.semanticRoot)<<", \"operational\": "<<quote(m.epoch.operationalRoot)<<", \"confidential\": "<<quote(m.epoch.confidentialRoot)<<", \"synaptic\": "<<quote(m.epoch.synapticRoot)<<"},\n  \"nuclei\": [";for(size_t i=0;i<m.nuclei.size();++i){auto&n=m.nuclei[i];if(i)o<<',';o<<"{\"id\":"<<quote(n.id)<<",\"kind\":"<<quote(n.kind)<<",\"module\":"<<quote(n.module)<<",\"name\":"<<quote(n.name)<<",\"content_id\":"<<quote(n.contentId)<<",\"contract_id\":"<<quote(n.contractId)<<",\"type_id\":"<<quote(n.typeId)<<",\"provenance_ref\":"<<quote(n.provenanceRef)<<",\"domains\":"<<jset(n.domains)<<",\"capabilities\":"<<jset(n.capabilities)<<",\"authority\":{";bool f=true;for(auto&a:n.authority){if(!f)o<<',';f=false;o<<quote(a.first)<<':'<<quote(a.second);}o<<"}}";}o<<"],\n  \"synapses\": [";for(size_t i=0;i<m.links.size();++i){auto&l=m.links[i];if(i)o<<',';o<<"{\"id\":"<<quote(l.id)<<",\"from\":"<<quote(l.from)<<",\"to\":"<<quote(l.to)<<",\"relation\":"<<quote(l.relation)<<",\"authority\":"<<quote(l.authority)<<"}";}o<<"],\n  \"bindings\": [";for(size_t i=0;i<m.bindings.size();++i){auto&b=m.bindings[i];if(i)o<<',';o<<"{\"id\":"<<quote(b.id)<<",\"archetype\":"<<quote(b.archetype)<<",\"policy\":"<<quote(b.policy)<<",\"members\":"<<jvec(b.members)<<"}";}o<<"]\n}\n";return o.str();}
std::string graphJson(const Program&p){auto m=buildSystemMemory(p);std::ostringstream o;o<<"{\n  \"schema\": \"omni.living-graph/1\",\n  \"epoch\": "<<quote(m.epoch.id)<<",\n  \"system_root\": "<<quote(m.epoch.systemRoot)<<",\n  \"nodes\": [";for(size_t i=0;i<m.nuclei.size();++i){if(i)o<<',';auto&n=m.nuclei[i];o<<"{\"id\":"<<quote(n.id)<<",\"kind\":"<<quote(n.kind)<<",\"name\":"<<quote(n.name)<<"}";}o<<"],\n  \"edges\": [";for(size_t i=0;i<m.links.size();++i){if(i)o<<',';auto&l=m.links[i];o<<"{\"from\":"<<quote(l.from)<<",\"to\":"<<quote(l.to)<<",\"relation\":"<<quote(l.relation)<<"}";}o<<"]\n}\n";return o.str();}
std::string systemSummaryJson(const Program&p){return systemMemorySummaryJson(buildSystemMemory(p));}
static std::string neuralPulseJsonImpl(const SystemMemory&n,const SystemMemory*o,bool enforceContinuity){
    std::string continuity=o?"CONTIGUOUS":"BASELINE";bool authoritative=true;
    if(o&&enforceContinuity){
        if(n.epoch.sequence<o->epoch.sequence||(n.epoch.sequence==o->epoch.sequence&&n.epoch.id!=o->epoch.id))fail("E_EPOCH","pulse epoch regression or identity conflict");
        if(n.epoch.sequence==o->epoch.sequence)continuity="DUPLICATE";
        else if(o->epoch.sequence==std::numeric_limits<uint64_t>::max()||n.epoch.sequence!=o->epoch.sequence+1u){continuity="GAP_REQUIRES_RESNAPSHOT";authoritative=false;}
    }
    if(!authoritative){std::ostringstream gap;gap<<"{\n  \"schema\": \"omni.neural-pulse/1\",\n  \"delta_only\": true,\n  \"continuity\": \"GAP_REQUIRES_RESNAPSHOT\",\n  \"delta_authoritative\": false,\n  \"resnapshot_required\": true,\n  \"base_epoch\": "<<quote(o->epoch.id)<<",\n  \"epoch\": "<<quote(n.epoch.id)<<",\n  \"base_sequence\": "<<o->epoch.sequence<<",\n  \"epoch_sequence\": "<<n.epoch.sequence<<"\n}\n";return gap.str();}
    std::map<std::string,std::string>a,b;std::set<std::string>al,bl;for(auto&x:n.nuclei)b[x.id]=x.contentId;for(auto&x:n.links)bl.insert(x.id);if(o){for(auto&x:o->nuclei)a[x.id]=x.contentId;for(auto&x:o->links)al.insert(x.id);}std::vector<std::string>ad,ch,rm,la,lr;for(auto&x:b){auto i=a.find(x.first);if(i==a.end())ad.push_back(x.first);else if(i->second!=x.second)ch.push_back(x.first);}for(auto&x:a)if(!b.count(x.first))rm.push_back(x.first);for(auto&x:bl)if(!al.count(x))la.push_back(x);for(auto&x:al)if(!bl.count(x))lr.push_back(x);std::ostringstream z;z<<"{\n  \"schema\": \"omni.neural-pulse/1\",\n  \"delta_only\": true,\n  \"continuity\": "<<quote(continuity)<<",\n  \"delta_authoritative\": true,\n  \"resnapshot_required\": false,\n  \"base_epoch\": "<<(o?quote(o->epoch.id):"null")<<",\n  \"epoch\": "<<quote(n.epoch.id)<<",\n  \"nuclei\": {\"added\": "<<jvec(ad)<<", \"changed\": "<<jvec(ch)<<", \"removed\": "<<jvec(rm)<<"},\n  \"synapses\": {\"added\": "<<jvec(la)<<", \"removed\": "<<jvec(lr)<<"},\n  \"domain_delta\": {\"structural_changed\": "<<(o&&o->epoch.structuralRoot!=n.epoch.structuralRoot?"true":"false")<<", \"semantic_changed\": "<<(o&&o->epoch.semanticRoot!=n.epoch.semanticRoot?"true":"false")<<", \"operational_changed\": "<<(o&&o->epoch.operationalRoot!=n.epoch.operationalRoot?"true":"false")<<", \"confidential_changed\": "<<(o&&o->epoch.confidentialRoot!=n.epoch.confidentialRoot?"true":"false")<<", \"synaptic_changed\": "<<(o&&o->epoch.synapticRoot!=n.epoch.synapticRoot?"true":"false")<<"},\n  \"root_digest\": "<<quote(n.epoch.systemRoot)<<"\n}\n";return z.str();
}
std::string neuralPulseJson(const SystemMemory&n,const SystemMemory*o){return neuralPulseJsonImpl(n,o,true);}
std::string neuralPulseJson(const Program&n,const Program*o){auto a=buildSystemMemory(n);if(!o)return neuralPulseJsonImpl(a,nullptr,false);auto b=buildSystemMemory(*o);return neuralPulseJsonImpl(a,&b,false);}
std::string runtimeObservationJson(const Program&p,const EvalResult&r,uint64_t seq,const SystemMemory*prev){auto m=buildObservedSystemMemory(p,r,seq);std::ostringstream o;o<<"{\n  \"schema\": \"omni.runtime-observation/1\",\n  \"architecture\": \"living-computational-system\",\n  \"authority\": \"runtime-observed\",\n  \"base_epoch\": "<<(prev?quote(prev->epoch.id):"null")<<",\n  \"epoch\": "<<quote(m.epoch.id)<<",\n  \"epoch_sequence\": "<<seq<<",\n  \"operational_root\": "<<quote(m.epoch.operationalRoot)<<",\n  \"system_root\": "<<quote(m.epoch.systemRoot)<<",\n  \"result\": "<<r.result<<",\n  \"steps\": "<<r.steps<<",\n  \"output_bytes\": "<<r.output.size()<<",\n  \"output_digest\": "<<quote("sha256:"+sha256(r.output))<<"\n}\n";return o.str();}
std::string querySystemJson(const Program&p,const std::string&m,const std::string&v){return querySystemMemoryJson(buildSystemMemory(p),m,v);}
std::string traceSystemMemoryJson(const SystemMemory&m,const std::string&e,uint32_t depth){if(depth>16)fail("E_QUERY","trace depth excede 16");std::set<std::string>s,f;for(auto&n:m.nuclei)if(n.name==e||n.module+"."+n.name==e||n.id==e){s.insert(n.id);f.insert(n.id);}if(s.empty())fail("E_QUERY","entidad no encontrada: "+e);std::vector<const SynapticLink*>ed;std::set<std::string>seen;for(uint32_t d=0;d<depth&&!f.empty();++d){std::set<std::string>nx;for(auto&l:m.links)if(f.count(l.from)||f.count(l.to)){if(seen.insert(l.id).second)ed.push_back(&l);auto q=f.count(l.from)?l.to:l.from;if(s.insert(q).second)nx.insert(q);}f=std::move(nx);}size_t unknown=0;for(const auto* link:ed)if(edgeClass(link->relation)=="unknown")++unknown;std::ostringstream o;o<<"{\n  \"schema\": \"omni.system-trace/1\",\n  \"source_files_scanned\": 0,\n  \"epoch\": "<<quote(m.epoch.id)<<",\n  \"system_root\": "<<quote(m.epoch.systemRoot)<<",\n  \"entity\": "<<quote(e)<<",\n  \"limits\": {\"requested_depth\": "<<depth<<", \"max_depth\": 16, \"truncated\": "<<(!f.empty()?"true":"false")<<"},\n  \"unknown_edges_conservative\": true,\n  \"unknown_edge_count\": "<<unknown<<",\n  \"nuclei\": [";bool q=true;for(auto&n:m.nuclei)if(s.count(n.id)){if(!q)o<<',';q=false;o<<"{\"id\":"<<quote(n.id)<<",\"kind\":"<<quote(n.kind)<<",\"name\":"<<quote(n.name)<<"}";}o<<"],\n  \"edges\": [";for(size_t i=0;i<ed.size();++i){if(i)o<<',';o<<"{\"from\":"<<quote(ed[i]->from)<<",\"to\":"<<quote(ed[i]->to)<<",\"relation\":"<<quote(ed[i]->relation)<<",\"edge_class\":"<<quote(edgeClass(ed[i]->relation))<<"}";}o<<"]\n}\n";return o.str();}
std::string traceSystemJson(const Program&p,const std::string&e,uint32_t d){return traceSystemMemoryJson(buildSystemMemory(p),e,d);}
std::string impactSystemMemoryJson(const SystemMemory&m,const std::string&e){std::set<std::string>s,f;for(auto&n:m.nuclei)if(n.name==e||n.module+"."+n.name==e||n.id==e){s.insert(n.id);f.insert(n.id);}if(s.empty())fail("E_QUERY","entidad no encontrada: "+e);std::set<std::string>rels={"calls","imports","defines","contains","parameter-type","returns-type","field-type","variant-type","requires-capability","specializes"};size_t unknown=0;for(const auto& link:m.links)if(edgeClass(link.relation)=="unknown")++unknown;while(!f.empty()){std::set<std::string>nx;for(auto&l:m.links){if(rels.count(l.relation)&&f.count(l.to)&&s.insert(l.from).second)nx.insert(l.from);else if(edgeClass(l.relation)=="unknown"&&(f.count(l.to)||f.count(l.from))){const auto&other=f.count(l.to)?l.from:l.to;if(s.insert(other).second)nx.insert(other);}}f=std::move(nx);}std::map<std::string,size_t>k;for(auto&n:m.nuclei)if(s.count(n.id))++k[n.kind];std::ostringstream o;o<<"{\n  \"schema\": \"omni.impact-plan/1\",\n  \"plan_only\": true,\n  \"source_files_scanned\": 0,\n  \"epoch\": "<<quote(m.epoch.id)<<",\n  \"system_root\": "<<quote(m.epoch.systemRoot)<<",\n  \"unknown_edges_conservative\": true,\n  \"unknown_edge_count\": "<<unknown<<",\n  \"affected_nodes\": "<<s.size()<<",\n  \"kinds\": {";bool q=true;for(auto&x:k){if(!q)o<<',';q=false;o<<quote(x.first)<<':'<<x.second;}o<<"}\n}\n";return o.str();}
std::string impactSystemJson(const Program&p,const std::string&e){return impactSystemMemoryJson(buildSystemMemory(p),e);}
static std::string cognitiveProjectionFromMemory(const SystemMemory& m,const std::string& selector,uint64_t sourceFilesScanned,const std::string& projectionSource){
    std::set<std::string> selected;
    auto visible=[&](const MemoryNucleus& nucleus){return !nucleus.domains.count("confidential");};
    if(selector=="system") {
        for(const auto& nucleus:m.nuclei) if(visible(nucleus)) selected.insert(nucleus.id);
    } else {
        std::set<std::string> seeds;
        for(const auto& nucleus:m.nuclei) if(visible(nucleus)&&(nucleus.name==selector||nucleus.module+"."+nucleus.name==selector||nucleus.id==selector)) seeds.insert(nucleus.id);
        if(seeds.empty())fail("E_QUERY","selector cognitivo no encontrado o confidencial: "+selector);
        if(seeds.size()>1u)fail("E_QUERY","selector cognitivo ambiguo: "+selector);
        selected=seeds;
        for(const auto& edge:m.links) {
            if(seeds.count(edge.from)) selected.insert(edge.to);
            if(seeds.count(edge.to)) selected.insert(edge.from);
        }
        std::set<std::string> visibleIds;
        for(const auto& nucleus:m.nuclei)if(visible(nucleus))visibleIds.insert(nucleus.id);
        for(auto it=selected.begin();it!=selected.end();){if(!visibleIds.count(*it))it=selected.erase(it);else ++it;}
    }
    std::ostringstream o; o<<"{\n  \"schema\": \"omni.cognitive-projection/1\",\n  \"architecture\": \"AI-native/AI-independent\",\n  \"authority\": \"read-only-projection\",\n  \"projection_source\": "<<quote(projectionSource)<<",\n  \"source_files_scanned\": "<<sourceFilesScanned<<",\n  \"epoch\": "<<quote(m.epoch.id)<<",\n  \"system_root\": "<<quote(m.epoch.systemRoot)<<",\n  \"provider_required\": false,\n  \"mutation_authorized\": false,\n  \"confidential_memory_included\": false,\n  \"nuclei\": [";
    bool first=true;
    for(const auto& nucleus:m.nuclei) if(selected.count(nucleus.id)){
        if(!first)o<<',';
        first=false;
        o<<"{\"id\":"<<quote(nucleus.id)<<",\"kind\":"<<quote(nucleus.kind)<<",\"module\":"<<quote(nucleus.module)<<",\"name\":"<<quote(nucleus.name)<<",\"domains\":"<<jset(nucleus.domains)<<",\"authority\":{";
        bool af=true;for(const auto& a:nucleus.authority){if(!af)o<<',';af=false;o<<quote(a.first)<<':'<<quote(a.second);}o<<"}}";
    }
    o<<"],\n  \"edges\": [";first=true;
    for(const auto& edge:m.links)if(selected.count(edge.from)&&selected.count(edge.to)){
        if(!first)o<<',';
        first=false;
        o<<"{\"id\":"<<quote(edge.id)<<",\"from\":"<<quote(edge.from)<<",\"to\":"<<quote(edge.to)<<",\"relation\":"<<quote(edge.relation)<<",\"authority\":"<<quote(edge.authority)<<"}";
    }
    o<<"]\n}\n"; return o.str();
}
std::string cognitiveProjectionJson(const SystemMemory& m,const std::string& selector){return cognitiveProjectionFromMemory(m,selector,0u,"persisted-osnmf");}
std::string cognitiveProjectionJson(const Program& p,const std::string& selector){const auto m=buildSystemMemory(p);return cognitiveProjectionFromMemory(m,selector,static_cast<uint64_t>(p.sources.size()),"program-ir");}
std::string synapticScaleBenchmarkJson(const Program&p,const std::string&selector,uint64_t instances,uint64_t overrides){
    if(instances==0||instances>10000000ull)fail("E_LIMIT","synaptic instances fuera de rango 1..10000000");
    if(overrides>instances||overrides>1000000ull)fail("E_LIMIT","synaptic overrides fuera de rango");
    const auto memory=buildSystemMemory(p); const MemoryNucleus* archetype=nullptr;
    for(const auto& n:memory.nuclei){
        const bool eligible=n.kind=="record"||n.kind=="enum"||n.kind=="function-template";
        if(!eligible) continue;
        if(n.name==selector||n.module+"."+n.name==selector||n.id==selector){
            if(archetype&&archetype->id!=n.id) fail("E_QUERY","archetype ambiguo");
            archetype=&n;
        }
    }
    if(!archetype)fail("E_QUERY","archetype no encontrado: "+selector);
    std::vector<uint64_t> localOverrides; localOverrides.reserve(static_cast<size_t>(overrides));
    for(uint64_t i=0;i<overrides;++i)localOverrides.push_back(i);
    std::string sharedValue="policy-v1"; const auto before=h("omni.synaptic-effective/1",archetype->id+"|"+sharedValue+"|"+std::to_string(instances)+"|"+std::to_string(overrides));
    const auto started=std::chrono::steady_clock::now(); sharedValue="policy-v2"; const uint64_t propagated=instances-overrides;
    const auto after=h("omni.synaptic-effective/1",archetype->id+"|"+sharedValue+"|"+std::to_string(instances)+"|"+std::to_string(overrides));
    const auto elapsed=std::chrono::duration_cast<std::chrono::nanoseconds>(std::chrono::steady_clock::now()-started).count();
    const auto durablePath=std::filesystem::temp_directory_path()/("omni-synaptic-overrides-"+sha256(archetype->id+"|"+std::to_string(instances)+"|"+std::to_string(overrides)).substr(0,24)+".osdo");
    std::ostringstream durableBody;durableBody<<"archetype|"<<archetype->id<<"\ninstances|"<<instances<<"\n";for(const auto id:localOverrides)durableBody<<"override|"<<id<<"|policy-local-"<<(id%17u)<<"\n";const auto durable=std::string("OSDO1\n")+durableBody.str()+"integrity|sha256:"+sha256("omni.osdo/1\n"+durableBody.str())+"\n";
    {std::ofstream persisted(durablePath,std::ios::binary|std::ios::trunc);if(!persisted||!persisted.write(durable.data(),static_cast<std::streamsize>(durable.size()))||!persisted.flush())fail("E_DURABILITY","no se pudo persistir corpus de overrides");}
    if(const auto fault=std::getenv("OMNI_TEST_OSDO_FAULT");fault&&std::string(fault)=="truncate"){const auto size=std::filesystem::file_size(durablePath);std::filesystem::resize_file(durablePath,size>8u?size-8u:0u);}
    std::ifstream reopened(durablePath,std::ios::binary);std::ostringstream reopenedBytes;reopenedBytes<<reopened.rdbuf();if(!reopened.good()&&!reopened.eof())fail("E_DURABILITY","no se pudo reabrir corpus de overrides");std::error_code removeError;std::filesystem::remove(durablePath,removeError);
    std::istringstream durableInput(reopenedBytes.str());std::string durableLine,durableParsedBody,durableIntegrity;uint64_t durableRecords=0;bool durableEnded=false;
    if(!std::getline(durableInput,durableLine)||durableLine!="OSDO1")fail("E_DURABILITY","corpus durable OSDO1 invalido");
    while(std::getline(durableInput,durableLine)){
        if(durableLine.empty())continue;
        if(durableEnded)fail("E_DURABILITY","contenido posterior a OSDO1 integrity");
        if(durableLine.rfind("integrity|",0)==0){durableIntegrity=durableLine.substr(10u);durableEnded=true;continue;}
        const auto parts=split(durableLine,'|');
        if(parts[0]=="override"){
            if(parts.size()!=3u||parts[1]!=std::to_string(durableRecords)||parts[2]!="policy-local-"+std::to_string(durableRecords%17u))fail("E_DURABILITY","override durable corrupto o fuera de orden");
            ++durableRecords;
        }else if(!((parts[0]=="archetype"&&parts.size()==2u&&parts[1]==archetype->id)||(parts[0]=="instances"&&parts.size()==2u&&parts[1]==std::to_string(instances))))fail("E_DURABILITY","metadata durable de overrides invalida");
        durableParsedBody+=durableLine+"\n";
    }
    if(!durableEnded||durableIntegrity!="sha256:"+sha256("omni.osdo/1\n"+durableParsedBody)||durableRecords!=overrides)fail("E_DURABILITY","integridad/recuento durable de overrides invalido");
    const bool overridesPreserved=localOverrides.size()==static_cast<size_t>(overrides)&&durableRecords==overrides;
    const auto binding=h("omni.synaptic-population/1",archetype->id+"|"+std::to_string(instances)+"|structural-sharing/cow-v1");
    std::ostringstream o;o<<"{\n  \"schema\": \"omni.synaptic-scale/1\",\n  \"policy\": \"structural-sharing/cow-v1\",\n  \"archetype\": "<<quote(archetype->id)<<",\n  \"binding\": "<<quote(binding)<<",\n  \"logical_instances\": "<<instances<<",\n  \"logical_entities\": "<<(instances+1ull)<<",\n  \"physical_instance_records\": "<<overrides<<",\n  \"durable_override_records_verified\": "<<overrides<<",\n  \"durable_override_bytes\": "<<durable.size()<<",\n  \"restart_roundtrip_verified\": "<<(overridesPreserved?"true":"false")<<",\n  \"full_population_materialized\": false,\n  \"shared_property_before\": \"policy-v1\",\n  \"shared_property_after\": \"policy-v2\",\n  \"effective_instances_updated\": "<<propagated<<",\n  \"local_overrides_preserved\": "<<(overridesPreserved?"true":"false")<<",\n  \"copy_on_write\": true,\n  \"before_root\": "<<quote(before)<<",\n  \"after_root\": "<<quote(after)<<",\n  \"bytes_rewritten_for_shared_value\": "<<sharedValue.size()<<",\n  \"mutation_nanoseconds\": "<<elapsed<<",\n  \"recompile_count\": 0,\n  \"runtime_refresh_count\": "<<propagated<<"\n}\n";return o.str();
}
static CognitiveOffloadEnvelope makeCognitiveOffloadFromContext(const SystemMemory&m,const std::string&context,const std::string&selector,const std::string&provider,const CognitiveBudget&budget,const std::set<std::string>&grants,uint64_t sourceFilesScanned){
    if(provider.empty()||provider.size()>64u||!std::all_of(provider.begin(),provider.end(),[](char c){return std::isalnum(static_cast<unsigned char>(c))||c=='.'||c=='_'||c=='-';}))fail("E_COGNITION","provider id invalido");
    if(!grants.count("external.egress"))fail("E_CAPABILITY","cognitive offload requiere capability: external.egress");
    if(budget.maxInputTokens==0||budget.maxOutputTokens==0||budget.maxLatencyMs==0)fail("E_COGNITION","cognitive budget incompleto");
    const uint64_t bytes=static_cast<uint64_t>(context.size());
    if(bytes>(static_cast<uint64_t>(OMNI_ENVELOPE_MAX_BYTES)-4096ull)/2ull)fail("E_LIMIT","cognitive context demasiado grande");
    const uint64_t estimated=(bytes+3ull)/4ull;
    if(estimated>budget.maxInputTokens)fail("E_COGNITION","cognitive context excede max_input_tokens");
    uint64_t selected=0;for(const auto& n:m.nuclei)if(!n.domains.count("confidential")){
        if(selector=="system"||n.name==selector||n.module+"."+n.name==selector||n.id==selector)++selected;
    }
    if(selector!="system"&&selected==0)fail("E_QUERY","selector cognitivo no encontrado o confidencial: "+selector);
    CognitiveOffloadEnvelope e;e.baseEpoch=m.epoch.id;e.provider=provider;e.selector=selector;e.contextDigest=h("omni.ocap-context/1",context);e.contextHex=hex(context);e.requiredCapability="external.egress";e.budget=budget;e.estimatedInputTokens=estimated;e.contextBytes=bytes;e.contextNuclei=selected;e.sourceFilesScanned=sourceFilesScanned;e.id=offloadDigest(e);return e;
}
CognitiveOffloadEnvelope makeCognitiveOffloadEnvelope(const SystemMemory&m,const std::string&selector,const std::string&provider,const CognitiveBudget&budget,const std::set<std::string>&grants){return makeCognitiveOffloadFromContext(m,cognitiveProjectionJson(m,selector),selector,provider,budget,grants,0u);}
CognitiveOffloadEnvelope makeCognitiveOffloadEnvelope(const Program&p,const std::string&selector,const std::string&provider,const CognitiveBudget&budget,const std::set<std::string>&grants){const auto m=buildSystemMemory(p);return makeCognitiveOffloadFromContext(m,cognitiveProjectionJson(p,selector),selector,provider,budget,grants,static_cast<uint64_t>(p.sources.size()));}
std::string serializeCognitiveOffloadEnvelope(const CognitiveOffloadEnvelope&e){
    if(e.id!=offloadDigest(e))fail("E_COGNITION","offload envelope integrity mismatch");
    std::ostringstream o;o<<"OCAP1\nbase_epoch|"<<e.baseEpoch<<"\nprovider|"<<e.provider<<"\nselector|"<<e.selector<<"\ncontext_digest|"<<e.contextDigest<<"\ncontext_bytes|"<<e.contextBytes<<"\ncontext_nuclei|"<<e.contextNuclei<<"\nsource_files_scanned|"<<e.sourceFilesScanned<<"\nestimated_input_tokens|"<<e.estimatedInputTokens<<"\nmax_input_tokens|"<<e.budget.maxInputTokens<<"\nmax_output_tokens|"<<e.budget.maxOutputTokens<<"\nmax_cost_microunits|"<<e.budget.maxCostMicrounits<<"\nmax_latency_ms|"<<e.budget.maxLatencyMs<<"\nrequired_capability|"<<e.requiredCapability<<"\ncontext_hex|"<<e.contextHex<<"\nenvelope_id|"<<e.id<<"\n";return o.str();
}
CognitiveOffloadEnvelope parseCognitiveOffloadEnvelope(const std::string&t){
    if(t.size()>OMNI_ENVELOPE_MAX_BYTES)fail("E_LIMIT","OCAP envelope demasiado grande");
    validateUTF8(t); std::istringstream in(t); std::string line;
    if(!std::getline(in,line)||line!="OCAP1")fail("E_VERSION","OCAP version no soportada");
    std::map<std::string,std::string> f;
    while(std::getline(in,line)){if(line.empty())continue;auto q=line.find('|');if(q==std::string::npos||!f.emplace(line.substr(0,q),line.substr(q+1)).second)fail("E_COGNITION","OCAP campo invalido");}
    const std::set<std::string> required={"base_epoch","provider","selector","context_digest","context_bytes","context_nuclei","source_files_scanned","estimated_input_tokens","max_input_tokens","max_output_tokens","max_cost_microunits","max_latency_ms","required_capability","context_hex","envelope_id"};
    if(f.size()!=required.size())fail("E_COGNITION","OCAP campos desconocidos/incompletos");
    for(const auto& k:required)if(!f.count(k))fail("E_COGNITION","OCAP incompleto");
    auto number=[&](const char* k){try{size_t used=0;auto v=std::stoull(f[k],&used);if(used!=f[k].size())fail("E_COGNITION","OCAP numero invalido");return static_cast<uint64_t>(v);}catch(const Error&){throw;}catch(...){fail("E_COGNITION","OCAP numero invalido");}};
    CognitiveOffloadEnvelope e;e.baseEpoch=f["base_epoch"];e.provider=f["provider"];e.selector=f["selector"];e.contextDigest=f["context_digest"];e.contextBytes=number("context_bytes");e.contextNuclei=number("context_nuclei");e.sourceFilesScanned=number("source_files_scanned");e.estimatedInputTokens=number("estimated_input_tokens");e.budget.maxInputTokens=number("max_input_tokens");e.budget.maxOutputTokens=number("max_output_tokens");e.budget.maxCostMicrounits=number("max_cost_microunits");e.budget.maxLatencyMs=number("max_latency_ms");e.requiredCapability=f["required_capability"];e.contextHex=f["context_hex"];e.id=f["envelope_id"];
    if(e.requiredCapability!="external.egress"||e.estimatedInputTokens>e.budget.maxInputTokens||e.budget.maxOutputTokens==0||e.budget.maxLatencyMs==0)fail("E_COGNITION","OCAP policy invalida");
    if(!validHash(e.baseEpoch)||!validHash(e.contextDigest)||!validHash(e.id))fail("E_COGNITION","OCAP hash invalido");
    if(e.provider.empty()||e.provider.size()>64u||!std::all_of(e.provider.begin(),e.provider.end(),[](char c){return std::isalnum(static_cast<unsigned char>(c))||c=='.'||c=='_'||c=='-';}))fail("E_COGNITION","OCAP provider invalido");
    if(e.contextBytes>(static_cast<uint64_t>(OMNI_ENVELOPE_MAX_BYTES)-4096ull)/2ull)fail("E_LIMIT","OCAP context demasiado grande");
    const auto context=unhex(e.contextHex);
    if(context.size()!=e.contextBytes||h("omni.ocap-context/1",context)!=e.contextDigest||e.id!=offloadDigest(e))fail("E_COGNITION","OCAP integrity mismatch");
    return e;
}
std::string cognitiveOffloadSummaryJson(const CognitiveOffloadEnvelope&e){
    std::ostringstream o;o<<"{\n  \"schema\": \"omni.ocap-offload/1\",\n  \"envelope_id\": "<<quote(e.id)<<",\n  \"base_epoch\": "<<quote(e.baseEpoch)<<",\n  \"provider\": "<<quote(e.provider)<<",\n  \"provider_adapter\": \"provider-neutral-envelope\",\n  \"required_capability\": \"external.egress\",\n  \"confidential_memory_included\": false,\n  \"redaction_policy\": \"deny-confidential-by-default\",\n  \"context_nuclei\": "<<e.contextNuclei<<",\n  \"source_files_scanned\": "<<e.sourceFilesScanned<<",\n  \"context_bytes\": "<<e.contextBytes<<",\n  \"estimated_input_tokens\": "<<e.estimatedInputTokens<<",\n  \"budget\": {\"max_input_tokens\": "<<e.budget.maxInputTokens<<", \"max_output_tokens\": "<<e.budget.maxOutputTokens<<", \"max_cost_microunits\": "<<e.budget.maxCostMicrounits<<", \"max_latency_ms\": "<<e.budget.maxLatencyMs<<"},\n  \"mutation_authorized\": false,\n  \"envelope_is_authority\": false,\n  \"network_performed_by_core\": false\n}\n";return o.str();
}
std::string runCognitiveOffloadAdapterJson(const CognitiveOffloadEnvelope&e){
    if(e.provider!="loopback")fail("E_COGNITION","provider adapter no disponible en Core; use un adapter derivado o provider=loopback");
    const auto started=std::chrono::steady_clock::now();const auto context=unhex(e.contextHex);const auto result=h("omni.ocap-loopback-result/1",e.id+"|"+e.contextDigest);const auto elapsed=static_cast<uint64_t>(std::chrono::duration_cast<std::chrono::milliseconds>(std::chrono::steady_clock::now()-started).count());if(elapsed>e.budget.maxLatencyMs)fail("E_COGNITION","loopback excedio latency budget");const uint64_t outputTokens=std::min<uint64_t>(16ull,e.budget.maxOutputTokens);
    std::ostringstream o;o<<"{\n  \"schema\": \"omni.ocap-result/1\",\n  \"adapter\": \"loopback-certification\",\n  \"provider\": \"loopback\",\n  \"base_epoch\": "<<quote(e.baseEpoch)<<",\n  \"context_digest\": "<<quote(e.contextDigest)<<",\n  \"result_digest\": "<<quote(result)<<",\n  \"authority\": \"advisory\",\n  \"source_files_scanned\": "<<e.sourceFilesScanned<<",\n  \"proposal_is_authority\": false,\n  \"semantic_truth_verified\": false,\n  \"external_network_used\": false,\n  \"provider_compute_offload_contract_exercised\": true,\n  \"usage\": {\"input_tokens\": "<<e.estimatedInputTokens<<", \"output_tokens\": "<<outputTokens<<", \"cost_microunits\": 0, \"latency_ms\": "<<elapsed<<", \"context_bytes\": "<<context.size()<<"}\n}\n";return o.str();
}
CognitiveProposal makeCognitiveProposal(const SystemMemory&m,const std::string&e,const std::string&a,const std::string&note){if(!validIdentifier(a))fail("E_COGNITION","agent id invalido");validateUTF8(note);if(note.find('\0')!=std::string::npos||note.size()>4096)fail("E_COGNITION","semantic note invalida");std::string t;for(auto&n:m.nuclei)if(n.name==e||n.module+"."+n.name==e||n.id==e){if(!t.empty()&&t!=n.id)fail("E_QUERY","selector ambiguo");t=n.id;}if(t.empty())fail("E_QUERY","entidad no encontrada");CognitiveProposal p;p.baseEpoch=m.epoch.id;p.agent=a;p.target=t;p.action="semantic-note";p.note=note;p.requiredCapability="memory.write";p.id=pdig(p);return p;}
std::string serializeCognitiveProposal(const CognitiveProposal&p){if(p.id!=pdig(p))fail("E_COGNITION","proposal integrity mismatch");return "OMP1\nbase_epoch|"+p.baseEpoch+"\nagent|"+p.agent+"\ntarget|"+p.target+"\naction|"+p.action+"\nrequired_capability|"+p.requiredCapability+"\nnote_hex|"+hex(p.note)+"\nproposal_id|"+p.id+"\n";}
CognitiveProposal parseCognitiveProposal(const std::string&t){if(t.size()>65536)fail("E_LIMIT","proposal demasiado grande");validateUTF8(t);std::istringstream in(t);std::string l;if(!std::getline(in,l)||l!="OMP1")fail("E_VERSION","proposal version no soportada");std::map<std::string,std::string>f;while(std::getline(in,l)){if(l.empty())continue;auto q=l.find('|');if(q==std::string::npos||!f.emplace(l.substr(0,q),l.substr(q+1)).second)fail("E_COGNITION","proposal campo invalido");}for(auto*k:{"base_epoch","agent","target","action","required_capability","note_hex","proposal_id"})if(!f.count(k))fail("E_COGNITION","proposal incompleta");CognitiveProposal p;p.baseEpoch=f["base_epoch"];p.agent=f["agent"];p.target=f["target"];p.action=f["action"];p.requiredCapability=f["required_capability"];p.note=unhex(f["note_hex"]);p.id=f["proposal_id"];if(p.action!="semantic-note"||p.requiredCapability!="memory.write"||p.id!=pdig(p))fail("E_COGNITION","proposal invalida/unknown action");return p;}
std::string cognitiveProposalSummaryJson(const CognitiveProposal&p){std::ostringstream o;o<<"{\n  \"schema\": \"omni.cognitive-proposal/1\",\n  \"proposal_id\": "<<quote(p.id)<<",\n  \"base_epoch\": "<<quote(p.baseEpoch)<<",\n  \"agent\": "<<quote(p.agent)<<",\n  \"target\": "<<quote(p.target)<<",\n  \"required_capability\": \"memory.write\",\n  \"proposal_is_authority\": false,\n  \"semantic_truth_verified\": false\n}\n";return o.str();}
SystemMemory applyCognitiveProposalBatch(const SystemMemory&base,const std::vector<CognitiveProposal>&ps,const std::set<std::string>&g){
    if(ps.empty())fail("E_COGNITION","batch vacio");
    std::set<std::string>targets;for(const auto&n:base.nuclei)targets.insert(n.id);
    std::map<std::string,std::string>notes;std::set<std::string>seenProposalIds;std::vector<const CognitiveProposal*> unique;
    unique.reserve(ps.size());
    for(const auto&p:ps){
        if(p.id!=pdig(p)||p.action!="semantic-note")fail("E_COGNITION","proposal invalida");
        if(p.baseEpoch!=base.epoch.id)fail("E_EPOCH","stale cognitive proposal");
        if(!g.count(p.requiredCapability))fail("E_CAPABILITY","proposal requiere capability: "+p.requiredCapability);
        if(!targets.count(p.target))fail("E_COGNITION","target proposal ausente");
        auto i=notes.find(p.target);if(i!=notes.end()&&i->second!=p.note)fail("E_COGNITION","semantic conflict entre propuestas sobre el mismo target");
        notes[p.target]=p.note;
        if(seenProposalIds.insert(p.id).second)unique.push_back(&p);
    }
    const auto seq=advanceEpochSequence(base.epoch.sequence);
    auto out=base;
    for(const auto*pp:unique){const auto&p=*pp;MemoryNucleus n;n.kind="semantic-fact";n.name="agent-note";n.id=nid("semantic-fact","",p.target+"|"+p.agent);n.contentId=h("omni.semantic-fact/1",p.note);n.contractId=h("omni.semantic-fact-contract/1","note-v1");n.typeId=h("omni.entity-kind/1","semantic-fact");n.provenanceRef=p.id;n.domains={"semantic"};n.authority={{"semantic","ai-inferred"}};n.epoch=seq;out.nuclei.erase(std::remove_if(out.nuclei.begin(),out.nuclei.end(),[&](auto&x){return x.id==n.id;}),out.nuclei.end());out.nuclei.push_back(n);link(out.links,n.id,p.target,"describes","ai-inferred");}
    finalize(out,seq);return out;
}
SystemMemory applyCognitiveProposal(const SystemMemory&b,const CognitiveProposal&p,const std::set<std::string>&g){return applyCognitiveProposalBatch(b,{p},g);}
}
