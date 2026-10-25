#include "sdk_tooling.hpp"
namespace omni {
namespace {
std::string hexBytes(const std::vector<uint8_t>& b){ return std::string(reinterpret_cast<const char*>(b.data()), b.size()); }
std::string receiptSourcePath(const Program& p,const std::filesystem::path& source){
    if(p.sources.empty())return source.filename().generic_string();
    std::error_code ec;
    const auto root=std::filesystem::weakly_canonical(p.sources.front(),ec).parent_path();
    if(ec)return source.filename().generic_string();
    const auto canonical=std::filesystem::weakly_canonical(source,ec);
    if(ec)return source.filename().generic_string();
    const auto relative=canonical.lexically_relative(root);
    if(relative.empty()||relative.is_absolute()||(!relative.empty()&&*relative.begin()==".."))return source.filename().generic_string();
    return relative.generic_string();
}
}
std::string compactOmniHash(const Program& p){
    size_t io=0; for(const auto& f:p.functions)if(f.effectful())++io;
    std::ostringstream o;
    o<<"ohi1:program:sha256:"<<sha256(wave(p))
     <<";entry="<<p.module<<";m="<<p.modules.size()<<";f="<<p.functions.size()<<";r="<<p.records.size()<<";e="<<p.enums.size()<<";io="<<io;
    return o.str();
}
namespace {
template<class Range> void sdkStrings(std::ostream& out,const Range& values){
    out<<'[';bool first=true;
    for(const auto& value:values){if(!first)out<<',';first=false;out<<quote(value);}
    out<<']';
}
std::string sdkFactsJson(){
    const auto& facts=targetFacts();std::ostringstream out;
    out<<"{\"architecture\":"<<quote(facts.arch)<<",\"pointer_width\":"<<facts.pointerWidth
       <<",\"little_endian\":"<<(facts.littleEndian?"true":"false")
       <<",\"hosted\":"<<(facts.hosted?"true":"false")<<",\"features\":";
    sdkStrings(out,facts.features);return out.str()+"}";
}
std::string componentType(const Program& p,const Type& type,const std::string& module,bool open){
    std::ostringstream out;
    out<<"{\"display_type\":"<<quote(typeName(type));
    if(open){out<<",\"type_id\":null,\"ownership\":null,\"availability\":\"open-template\"}";return out.str();}
    out<<",\"type_id\":"<<quote(semanticTypeId(type))
       <<",\"contains_resource\":"<<(typeContainsResource(p,type,module)?"true":"false")
       <<",\"requires_consumption\":"<<(typeRequiresConsumption(p,type,module)?"true":"false")
       <<",\"descriptor\":"<<typeDescriptorJson(type)
       <<",\"canonical_layout\":"<<layoutDescriptorJson(type)<<'}';
    return out.str();
}
void sdkNucleus(std::ostream& out,const MemoryNucleus& nucleus){
    out<<"\"id\":"<<quote(nucleus.id)<<",\"content_id\":"<<quote(nucleus.contentId)
       <<",\"contract_id\":"<<quote(nucleus.contractId)<<",\"type_id\":"<<quote(nucleus.typeId);
}
void sdkGenerics(std::ostream& out,const std::vector<GenericParam>& generics){
    out<<'[';
    for(size_t i=0;i<generics.size();++i){if(i)out<<',';out<<"{\"name\":"<<quote(generics[i].name)<<",\"checked_constraint\":"<<quote(generics[i].constraint)<<'}';}
    out<<']';
}
}
std::string targetContextJson(const std::filesystem::path& root,const std::string& profile){
    // Export the actual shipped contracts, avoiding a second intrinsic/signature registry.
    const std::vector<std::pair<std::string,std::string>> contracts={
        {"target","TARGET_INTROSPECTION_CANDIDATE.md"},
        {"bit","BIT_INTRINSICS_CANDIDATE.md"},{"raw,port,cpu","RAW_BOUNDARY_CANDIDATE.md"},
        {"address","ADDRESS_DOMAINS_CANDIDATE.md"},{"layout","NATIVE_LAYOUT_CANDIDATE.md"},
        {"C ABI","LINKAGE_ABI_CANDIDATE.md"},{"cpu state","FPU_SSE_STATE_CANDIDATE.md"},
        {"simd","SIMD_BASELINE_CANDIDATE.md"},{"atomic","ATOMICS_CANDIDATE_ST09.md"},
        {"memory model","MEMORY_MODEL_X86_64_CANDIDATE.md"},
        {"tls,pcpu","TLS_AND_PERCPU_CANDIDATE.md"},
        {"ownership","MEMORY_AUTHORITY_0_8.md"},
        {"host invocation","HOST_INVOCATION_ABI_1_1.md"},{"host SDK","HOST_SDK_1_2.md"}};
    std::vector<std::string> requested;
    for(const auto& contract:contracts)requested.push_back("spec/"+contract.second);
    const auto verified=sdkContractTexts(root,requested);
    std::ostringstream out;
    out<<"{\"schema\":\"omni.target-context/1\",\"sdk_version\":"<<quote(VERSION)
       <<",\"target\":"<<quote(profile)<<",\"for\":\"llm\",\"facts\":"<<sdkFactsJson()
       <<",\"grants_authority\":false,\"granted_capabilities\":[],\"capability_registry\":"<<capabilityRegistryJson()
       <<",\"intrinsic_families\":[";
    for(size_t i=0;i<contracts.size();++i){if(i)out<<',';out<<quote(contracts[i].first);}
    out<<"],\"normative_references\":[";
    for(size_t i=0;i<contracts.size();++i){
        budgetCheck("el contexto del SDK");
        const auto relative="spec/"+contracts[i].second;
        const auto& contents=verified.at(relative);
        if(i)out<<',';
        out<<"{\"family\":"<<quote(contracts[i].first)<<",\"path\":"<<quote(relative)
           <<",\"sha256\":"<<quote(sha256(contents))<<",\"content\":"<<quote(contents)<<'}';
    }
    out<<"],\"canonical_layouts\":[";bool first=true;
    for(auto kind:{Type::U8,Type::U16,Type::U32,Type::U64,Type::I8,Type::I16,Type::I32,Type::I64,Type::F32,Type::F64,Type::Bool}){
        if(!first){out<<',';}first=false;out<<layoutDescriptorJson(Type(kind));
    }
    out<<"],\"abi\":{\"C\":\"SysV x86-64 integers; up to six integer arguments; explicit address/length; freestanding contract\","
          "\"host_invocation\":\"OMI1 fixed ABI; no live Resource or borrow transport\","
          "\"i386_bootstrap_is_general_C_ABI\":false},"
          "\"prohibited_or_deferred\":[\"AVX assumptions\",\"C++ ABI\",\"varargs\",\"arbitrary inline asm\",\"general SIMD shuffles\"],"
          "\"memory_model_scope\":\"The atomic memory-model contract is baremetal-x86_64; raw volatile is not inter-CPU synchronization. Evaluator models and QEMU do not certify physical hardware.\","
          "\"execution_availability\":\"Static checking does not imply evaluator/native/provider availability. Existing lowering and runtime checks remain mandatory.\","
          "\"certification_authority\":\"external exact-SHA receipt\"}\n";
    return out.str();
}
std::string componentContractJson(const Program& p,const std::string& profile){
    const auto memory=buildSystemMemory(p); // one materialization, no independently reloaded program
    size_t describedTypes=0;
    auto describeType=[&](const Type& type,const std::string& module,bool open){
        if((++describedTypes&1023u)==0u)budgetCheck("los tipos del componente");
        return componentType(p,type,module,open);
    };
    std::map<std::string,const MemoryNucleus*> nuclei;
    std::map<std::string,const MemoryNucleus*> declarations;
    for(const auto& nucleus:memory.nuclei){nuclei.emplace(nucleus.id,&nucleus);declarations.emplace(nucleus.kind+"\n"+nucleus.module+"\n"+nucleus.name,&nucleus);}
    std::map<std::string,const ModuleInfo*> modules;
    for(const auto& module:p.modules)modules.emplace(module.name,&module);
    std::map<std::string,std::map<std::string,std::pair<const Function*,bool>>> functionGroups;
    for(const auto& function:p.functions)functionGroups[function.module].emplace(semanticFunctionId(function),std::make_pair(&function,false));
    for(const auto& function:p.genericTemplates)functionGroups[function.module].emplace(semanticFunctionId(function,true),std::make_pair(&function,true));
    std::map<std::string,std::map<std::string,std::pair<const RecordDef*,bool>>> recordGroups;
    for(const auto& record:p.records)recordGroups[record.module].emplace(record.key,std::make_pair(&record,false));
    for(const auto& record:p.genericRecordTemplates)recordGroups[record.module].emplace(record.key,std::make_pair(&record,true));
    std::map<std::string,std::map<std::string,std::pair<const EnumDef*,bool>>> enumGroups;
    for(const auto& enumeration:p.enums)enumGroups[enumeration.module].emplace(enumeration.key,std::make_pair(&enumeration,false));
    for(const auto& enumeration:p.genericEnumTemplates)enumGroups[enumeration.module].emplace(enumeration.key,std::make_pair(&enumeration,true));
    std::ostringstream out;
    out<<"{\"schema\":\"omni.component-contract/1\",\"sdk_version\":"<<quote(VERSION)
       <<",\"program_content_id\":"<<quote("sha256:"+sha256(wave(p)))
       <<",\"system_root\":"<<quote(memory.epoch.systemRoot)<<",\"target_profile\":"<<quote(profile)
       <<",\"facts\":"<<sdkFactsJson()<<",\"grants_authority\":false,\"granted_capabilities\":[],"
         "\"native_emission_validated\":false,\"modules\":[";
    bool firstModule=true;
    for(const auto& [name,module]:modules){
        budgetCheck("el descriptor de componente");
        if(!firstModule){out<<',';}firstModule=false;
        const auto moduleNucleus=declarations.find("module\n"+name+"\n"+name);
        if(moduleNucleus==declarations.end())fail("E_INTERNAL","modulo comprobado sin identidad OSNMF");
        out<<"{\"name\":"<<quote(name)<<',';sdkNucleus(out,*moduleNucleus->second);out<<",\"imports\":[";
        std::vector<std::string> imports;for(const auto& item:module->imports)imports.push_back(item.target);
        std::sort(imports.begin(),imports.end());
        for(size_t i=0;i<imports.size();++i){if(i)out<<',';out<<quote(imports[i]);}
        out<<"],\"functions\":[";
        const auto& functions=functionGroups[name];
        bool firstFunction=true;
        for(const auto& [id,entry]:functions){
            budgetCheck("las funciones del componente");
            const auto& function=*entry.first;const bool open=entry.second;
            const auto found=nuclei.find(id);
            if(found==nuclei.end())fail("E_INTERNAL","funcion comprobada sin identidad OSNMF");
            if(!firstFunction){out<<',';}firstFunction=false;
            out<<"{\"name\":"<<quote(function.name)<<",\"function_id\":"<<quote(id)<<',';
            sdkNucleus(out,*found->second);
            out<<",\"public\":"<<(function.pub?"true":"false")<<",\"generics\":";sdkGenerics(out,function.generics);
            out<<",\"open_template\":"<<(open?"true":"false")<<",\"generated\":"<<(function.generated?"true":"false")<<",\"parameters\":[";
            for(size_t i=0;i<function.params.size();++i){if(i)out<<',';out<<"{\"name\":"<<quote(function.params[i].name)<<",\"type\":"<<describeType(function.params[i].type,name,open)<<'}';}
            out<<"],\"result\":"<<describeType(function.result,name,open)<<",\"declared_capabilities\":";
            sdkStrings(out,function.capabilities);out<<",\"direct_required_capabilities\":";sdkStrings(out,function.directCapabilities);
            out<<",\"required_capabilities\":";sdkStrings(out,function.requiredCapabilities);
            out<<",\"granted_capabilities\":[],\"linkage\":{\"export_name\":"<<quote(function.exportName)
               <<",\"extern_name\":"<<quote(function.externName)<<",\"section\":"<<quote(function.section)
               <<",\"noinline\":"<<(function.noInline?"true":"false")<<"},\"abi\":";
            if(function.isExtern||!function.exportName.empty()){
                std::string material="omni.component-c-abi/1\nsysv-x86_64-integer-v1\n"+function.exportName+"\n"+function.externName+"\n";
                for(const auto& parameter:function.params)material+=canonicalTypeIdentity(parameter.type)+"\n";
                material+="->"+canonicalTypeIdentity(function.result);
                out<<"{\"calling_convention\":\"sysv-x86_64-integer-v1\",\"abi_id\":"<<quote("sha256:"+sha256(material))
                   <<",\"emission_validated\":false,\"contract_profile\":\"baremetal-x86_64\"}";
            }else out<<"null";
            out<<'}';
        }
        out<<"],\"records\":[";bool firstRecord=true;
        const auto& records=recordGroups[name];
        for(const auto& [key,entry]:records){
            const auto& record=*entry.first;const bool open=entry.second;
            if(!firstRecord){out<<',';}firstRecord=false;
            out<<"{\"name\":"<<quote(record.name)<<",\"key\":"<<quote(key)<<',';
            const auto recordNucleus=declarations.find("record\n"+name+"\n"+record.name);
            if(!open&&recordNucleus!=declarations.end())sdkNucleus(out,*recordNucleus->second);else out<<"\"id\":null";
            out<<",\"public\":"<<(record.pub?"true":"false")<<",\"generics\":";sdkGenerics(out,record.generics);
            out<<",\"open_template\":"<<(open?"true":"false")
               <<",\"opaque\":"<<(record.opaque?"true":"false")<<",\"extern_C\":"<<(record.externC?"true":"false")
               <<",\"packed\":"<<(record.packed?"true":"false")<<",\"fields\":[";
            for(size_t i=0;i<record.fields.size();++i){if(i)out<<',';out<<"{\"name\":"<<quote(record.fields[i].name)<<",\"type\":"<<describeType(record.fields[i].type,name,open)<<'}';}
            std::string why=open?"open-template":plainRecordProblem(p,key);
            std::optional<RecordLayout> layout;
            if(why.empty())try{layout=recordLayout(p,key,targetFacts().pointerWidth==32?4u:8u);}catch(const Error& error){if(error.code!="E_LAYOUT")throw;why=error.what();}
            out<<"],\"native_layout\":";
            if(layout){out<<"{\"size_bytes\":"<<layout->size<<",\"alignment_bytes\":"<<layout->align<<",\"field_offsets\":[";for(size_t i=0;i<layout->offsets.size();++i){if(i)out<<',';out<<layout->offsets[i];}out<<"]}";}
            else out<<"null";
            out<<",\"layout_unavailable_reason\":"<<quote(why)<<'}';
        }
        out<<"],\"enums\":[";bool firstEnum=true;
        const auto& enums=enumGroups[name];
        for(const auto& [key,entry]:enums){
            const auto& enumeration=*entry.first;
            if(!firstEnum){out<<',';}firstEnum=false;
            out<<"{\"name\":"<<quote(enumeration.name)<<",\"key\":"<<quote(key)<<',';
            const auto enumNucleus=declarations.find("enum\n"+name+"\n"+enumeration.name);
            if(!entry.second&&enumNucleus!=declarations.end())sdkNucleus(out,*enumNucleus->second);else out<<"\"id\":null";
            out<<",\"public\":"<<(enumeration.pub?"true":"false")<<",\"generics\":";sdkGenerics(out,enumeration.generics);
            out<<",\"open_template\":"<<(entry.second?"true":"false")<<",\"variants\":[";
            for(size_t i=0;i<enumeration.variants.size();++i){const auto& variant=enumeration.variants[i];if(i)out<<',';out<<"{\"name\":"<<quote(variant.name)<<",\"payload\":";if(variant.hasPayload)out<<describeType(variant.payload,name,entry.second);else out<<"null";out<<'}';}
            out<<"]}";
        }
        out<<"]}";
    }
    out<<"]}\n";return out.str();
}
std::string programManifest(const Program& p){
    const auto canonical=wave(p);
    const auto packed=wire(p);
    const auto waveWriter=writerRepresentation(p);
    size_t io=0,pure=0; std::set<std::string> capabilities,required;
    for(const auto& f:p.functions) { (f.effectful()?io:pure)++; capabilities.insert(f.capabilities.begin(),f.capabilities.end()); required.insert(f.requiredCapabilities.begin(),f.requiredCapabilities.end()); }
    std::ostringstream o;
    o<<"{\n"
     <<"  \"schema\": \"omni.omnihash-descriptor/3\",\n"
     <<"  \"language_version\": "<<quote(VERSION)<<",\n"
     <<"  \"kind\": \"program\",\n"
     <<"  \"omnihash\": "<<quote(compactOmniHash(p))<<",\n"
     <<"  \"entry_module\": "<<quote(p.module)<<",\n"
     <<"  \"program_content_id\": \"sha256:"<<sha256(canonical)<<"\",\n"
     <<"  \"wire_content_id\": \"sha256:"<<sha256(hexBytes(packed))<<"\",\n"
     <<"  \"properties\": {\"modules\": "<<p.modules.size()<<", \"functions\": "<<p.functions.size()<<", \"generic_templates\": "<<p.genericTemplates.size()<<", \"generated_specializations\": "<<std::count_if(p.functions.begin(),p.functions.end(),[](const Function& f){return f.generated;})<<", \"records\": "<<p.records.size()<<", \"enums\": "<<p.enums.size()<<", \"pure_functions\": "<<pure<<", \"effectful_functions\": "<<io<<"},\n"
     <<"  \"declared_capabilities\": [";
    { bool first=true; for(const auto& c:capabilities){ if(!first)o<<","; first=false; o<<quote(c); } }
    o<<"],\n  \"required_capabilities\": [";
    { bool first=true; for(const auto& c:required){ if(!first)o<<","; first=false; o<<quote(c); } }
    std::string capCanon; for(const auto& c:required){ if(!capCanon.empty())capCanon+=","; capCanon+=c; }
    o<<"],\n  \"capability_contract_hash\": \"sha256:"<<sha256("omni.capabilities/3:"+capCanon)<<"\",\n  \"wire_profile\": \"OMC"<<waveWriter<<"\",\n  \"attestation_status\": \"unsigned\",\n  \"modules\": [";
    for(size_t i=0;i<p.modules.size();++i){
        if(i)o<<",";
        const auto&m=p.modules[i];
        o<<"\n    {\"name\": "<<quote(m.name)<<", \"imports\": [";
        for(size_t j=0;j<m.imports.size();++j){ if(j)o<<","; o<<quote(m.imports[j].target); }
        o<<"]}";
    }
    o<<"\n  ],\n  \"sources\": [";
    for(size_t i=0;i<p.sources.size();++i){
        if(i)o<<",";
        o<<"\n    {\"path\": "<<quote(receiptSourcePath(p,p.sources[i]))<<", \"sha256\": \""<<sha256File(p.sources[i])<<"\"}";
    }
    o<<"\n  ]\n}\n";
    return o.str();
}
std::string buildKey(const Program& p,const std::filesystem::path& runtime,const std::string& compilerArtifactHash,const std::string& backendIdentity,const std::string& opt,const std::string& target){
    std::ostringstream s;
    s<<"omni.build-key/2\n"
     <<"language="<<VERSION<<"\n"
     <<"target="<<target<<"\n"
     <<"opt="<<opt<<"\n"
     <<"compiler=sha256:"<<compilerArtifactHash<<"\n"
     <<"backend=sha256:"<<sha256(backendIdentity)<<"\n"
     <<"runtime=sha256:"<<sha256File(runtime)<<"\n"
     <<"program=sha256:"<<sha256(wave(p))<<"\n";
    return sha256(s.str());
}
std::string artifactReceipt(const Program& p,const std::filesystem::path& artifact,const std::string& key,const std::filesystem::path& runtime,const std::string& compilerArtifactHash,const std::string& backendIdentity,const std::string& opt,const std::string& target,bool cacheHit){
    std::ostringstream o;
    const auto encodedWave=wave(p);
    const auto programHash=sha256(encodedWave);
    const auto waveWriter=writerRepresentation(p);
    const auto artifactHash=sha256File(artifact);
    const auto runtimeHash=sha256File(runtime);
    const auto backendHash=sha256(backendIdentity);
    std::set<std::string> required; for(auto&f:p.functions)required.insert(f.requiredCapabilities.begin(),f.requiredCapabilities.end()); std::string capCanon; for(auto&c:required){if(!capCanon.empty())capCanon+=",";capCanon+=c;} auto capHash=sha256("omni.capabilities/3:"+capCanon);
    const auto hybrid=std::string("ohi1:artifact:sha256:")+artifactHash+";parent=sha256:"+programHash+";target="+target+";opt="+opt;
    o<<"{\n"
     <<"  \"schema\": \"omni.build-receipt/2\",\n"
     <<"  \"language_version\": "<<quote(VERSION)<<",\n"
     <<"  \"omnihash\": "<<quote(hybrid)<<",\n"
     <<"  \"build_key\": \"sha256:"<<key<<"\",\n"
     <<"  \"program_content_id\": \"sha256:"<<programHash<<"\",\n"
     <<"  \"artifact_sha256\": \""<<artifactHash<<"\",\n"
     <<"  \"lineage\": {\"parent\": \"sha256:"<<programHash<<"\", \"transform\": \"compile/llvm-clang-v1\"},\n"
     <<"  \"target_id\": "<<quote(target)<<",\n"
     <<"  \"target\": "<<quote(target)<<",\n"
     <<"  \"optimization\": "<<quote(opt)<<",\n"
     <<"  \"cache_hit\": "<<(cacheHit?"true":"false")<<",\n"
     <<"  \"wave_writer\": "<<waveWriter<<",\n"
     <<"  \"wire_profile\": \"OMC"<<waveWriter<<"\",\n"
     <<"  \"provenance\": {\n"
     <<"    \"omni_compiler_version\": "<<quote(VERSION)<<",\n"
     <<"    \"omni_compiler_sha256\": \""<<compilerArtifactHash<<"\",\n"
     <<"    \"backend_identity_sha256\": \""<<backendHash<<"\",\n"
     <<"    \"backend_identity\": "<<quote(backendIdentity)<<",\n"
     <<"    \"runtime_sha256\": \""<<runtimeHash<<"\",\n"
     <<"    \"source_files\": [";
    for(size_t i=0;i<p.sources.size();++i){ if(i)o<<","; o<<"\n      {\"path\": "<<quote(receiptSourcePath(p,p.sources[i]))<<", \"sha256\": \""<<sha256File(p.sources[i])<<"\"}"; }
    if(!p.sources.empty())o<<"\n    ";
    o<<"]\n  },\n"
     <<"  \"capability_contract_hash\": \"sha256:"<<capHash<<"\",\n"
     <<"  \"required_capabilities\": [";
    { bool first=true; for(const auto& c:required){ if(!first)o<<","; first=false; o<<quote(c); } }
    o<<"],\n  \"attestation\": {\"status\": \"unsigned-dev\", \"signature\": null}\n"
     <<"}\n";
    return o.str();
}
std::string sourceMapJson(const Program& p,const std::filesystem::path& artifact){
    std::ostringstream o;
    o<<"{\n  \"schema\": \"omni.source-map/1\",\n"
     <<"  \"language_version\": "<<quote(VERSION)<<",\n"
     <<"  \"target_id\": \"linux-x86_64-gnu\",\n"
     <<"  \"program_content_id\": \"sha256:"<<sha256(wave(p))<<"\",\n"
     <<"  \"artifact_sha256\": \""<<sha256File(artifact)<<"\",\n"
     <<"  \"regions\": [";
    for(size_t i=0;i<p.functions.size();++i){
        const auto& function=p.functions[i];
        if(i)o<<",";
        o<<"\n    {\"id\": "<<i<<", \"symbol\": "<<quote("omni.fn."+function.key)
         <<", \"module\": "<<quote(function.module)<<", \"name\": "<<quote(function.name)
         <<", \"generated\": "<<(function.generated?"true":"false")
         <<", \"source\": "<<quote(function.loc.file.empty()?"":receiptSourcePath(p,function.loc.file))
         <<", \"span\": {\"line\": "<<function.loc.line<<", \"column\": "<<function.loc.column<<"}}";
    }
    o<<"\n  ]\n}\n";
    return o.str();
}
}
