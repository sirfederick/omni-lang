#include "host_invocation_codegen.hpp"
#include "host_invocation_codec.hpp"
#include "host_sdk_schema.hpp"
#include <map>

namespace omni {
namespace {
const RecordDef& recordFor(const Program& p,const Type& t) {
    for(const auto& d:p.records)if(d.key==t.key)return d;
    fail("E_HOST_ENTRY","record definition missing");
}
const EnumDef& enumFor(const Program& p,const Type& t) {
    for(const auto& d:p.enums)if(d.key==t.key)return d;
    fail("E_HOST_ENTRY","enum definition missing");
}
struct Entry {Type type;std::string ctype;std::vector<size_t> children;};
class Generator {
    const Program& p;
    std::vector<Entry> entries;
    std::map<std::string,size_t> seen;
    std::ostringstream definitions,metadata;
    static constexpr size_t NO_CHILD=static_cast<size_t>(-1);
    std::string typeName(size_t index) const {return entries.at(index).ctype;}
    std::string typeIdBytes(const Type& t) const {
        const auto id=invocationTypeId(t);std::ostringstream o;
        for(size_t i=0;i<id.size();i++){if(i)o<<',';o<<static_cast<unsigned>(id[i]);}
        return o.str();
    }
    std::string childArray(size_t index) const {
        const auto& entry=entries[index];std::ostringstream o;
        for(size_t i=0;i<entry.children.size();i++){
            if(i)o<<',';
            if(entry.children[i]==NO_CHILD)o<<"NULL";
            else o<<"&omni_meta_"<<entry.children[i];
        }
        return o.str();
    }
    std::string offsets(size_t index) const {
        const auto& e=entries[index];std::ostringstream o;
        for(size_t i=0;i<e.children.size();i++){
            if(i)o<<',';
            if(e.children[i]==NO_CHILD){o<<'0';continue;}
            const char *field=e.type.kind==Type::Option?"payload":
                e.type.kind==Type::Result?(i==0?"ok":"err"):NULL;
            if(field)o<<"offsetof("<<e.ctype<<","<<field<<")";
            else o<<"offsetof("<<e.ctype<<","<<(e.type.kind==Type::Enum?"v":"f")<<i<<")";
        }
        return o.str();
    }
    void emitDefinition(size_t index) {
        const auto& e=entries[index];const auto& t=e.type;
        switch(t.kind) {
            case Type::Tuple:case Type::Record:case Type::Enum:
            case Type::Option:case Type::Result:case Type::Array:break;
            default:return;
        }
        definitions<<"typedef struct {\n";
        if(t.kind==Type::Enum)definitions<<"  uint8_t tag;\n";
        if(t.kind==Type::Option||t.kind==Type::Result)definitions<<"  _Bool tag;\n";
        if(t.kind==Type::Array)
            definitions<<"  "<<typeName(e.children[0])<<" data["<<t.extent<<"];\n";
        else for(size_t i=0;i<e.children.size();i++){
            if(e.children[i]==NO_CHILD)continue;
            const char* field=t.kind==Type::Option?"payload":
                t.kind==Type::Result?(i==0?"ok":"err"):NULL;
            definitions<<"  "<<typeName(e.children[i])<<' ';
            if(field)definitions<<field;
            else definitions<<(t.kind==Type::Enum?"v":"f")<<i;
            definitions<<";\n";
        }
        definitions<<"} "<<e.ctype<<";\n";
    }
public:
    explicit Generator(const Program& program):p(program) {}
    size_t add(const Type& t) {
        const auto key=canonicalTypeIdentity(t);
        if(auto it=seen.find(key);it!=seen.end())return it->second;
        Entry e;e.type=t;
        switch(t.kind) {
            case Type::Bool:e.ctype="_Bool";break;
            case Type::U8:e.ctype="uint8_t";break;case Type::U16:e.ctype="uint16_t";break;
            case Type::U32:case Type::Char:e.ctype="uint32_t";break;
            case Type::U64:case Type::Text:case Type::Bytes:e.ctype="uint64_t";break;
            case Type::I8:e.ctype="int8_t";break;case Type::I16:e.ctype="int16_t";break;
            case Type::I32:e.ctype="int32_t";break;case Type::I64:e.ctype="int64_t";break;
            case Type::Tuple:for(const auto& child:t.parts)e.children.push_back(add(child));break;
            case Type::Array:e.children.push_back(add(t.parts.at(0)));break;
            case Type::Option:e.children.push_back(add(t.parts.at(0)));break;
            case Type::Result:for(const auto& child:t.parts)e.children.push_back(add(child));break;
            case Type::Record:
                for(const auto& f:recordFor(p,t).fields)e.children.push_back(add(f.type));
                break;
            case Type::Enum:
                for(const auto& v:enumFor(p,t).variants)
                    e.children.push_back(v.hasPayload?add(v.payload):NO_CHILD);
                break;
            default:fail("E_HOST_ENTRY","unsupported host value type");
        }
        const auto index=entries.size();
        if(e.ctype.empty())e.ctype="OmniHostType"+std::to_string(index);
        entries.push_back(std::move(e));seen.emplace(key,index);
        emitDefinition(index);
        return index;
    }
    std::string generate(const HostBuildSelection& selection) {
        const Function* function=nullptr;
        for(const auto& f:p.functions)if(f.key==selection.functionKey){function=&f;break;}
        if(!function)fail("E_HOST_ENTRY","selected function disappeared");
        std::vector<size_t> params;
        for(const auto& arg:function->params)params.push_back(add(arg.type));
        const size_t result=add(function->result);
        for(size_t i=0;i<entries.size();i++){
            const auto& e=entries[i];
            if(!e.children.empty()){
                metadata<<"static const OmniInvocationTypeV1 *const omni_children_"<<i
                        <<"[] = {"<<childArray(i)<<"};\n";
                if(e.type.kind!=Type::Array)
                    metadata<<"static const uint32_t omni_offsets_"<<i
                            <<"[] = {"<<offsets(i)<<"};\n";
            }
            metadata<<"static const OmniInvocationTypeV1 omni_meta_"<<i<<" = {"
                    <<static_cast<uint32_t>(invocationTypeTag(e.type))<<",{"<<typeIdBytes(e.type)<<"},sizeof("<<e.ctype<<"),"
                    <<(e.type.kind==Type::Array?e.type.extent:e.children.size())<<','
                    <<(e.type.kind==Type::Array?"sizeof("+typeName(e.children[0])+")":"0")<<','
                    <<(e.children.empty()?"NULL":"omni_children_"+std::to_string(i))<<','
                    <<(e.children.empty()||e.type.kind==Type::Array?"NULL":"omni_offsets_"+std::to_string(i))
                    <<"};\n";
        }
        std::ostringstream output;
        output<<"#include <stdint.h>\n#include <stddef.h>\n#include <string.h>\n"
              <<"#include \"omni_invocation_internal.h\"\n"
              <<"#include \"omni_invocation_v1.h\"\n"
              <<definitions.str()<<metadata.str();
        const auto descriptor=encodeInvocationDescriptor(selection.descriptor);
        output<<"__attribute__((visibility(\"default\"))) const uint8_t omni_module_v1_descriptor[] = {";
        for(size_t i=0;i<descriptor.size();i++){if(i)output<<',';output<<static_cast<unsigned>(descriptor[i]);}
        output<<"};\n";
        const auto schema=encodeHostSdkSchema(p,[&](){std::vector<Type> values;for(const auto& parameter:function->params)values.push_back(parameter.type);return values;}(),function->result,selection.descriptor.signatureDigest);
        output<<"__attribute__((visibility(\"default\"))) const uint8_t omni_module_host_sdk_v1_schema[] = {";
        for(size_t i=0;i<schema.size();i++){if(i)output<<',';output<<static_cast<unsigned>(schema[i]);}
        output<<"};\n";
        const auto& sig=selection.descriptor.signatureDigest;
        output<<"static const uint8_t omni_signature[32] = {";
        for(size_t i=0;i<sig.size();i++){if(i)output<<',';output<<static_cast<unsigned>(sig[i]);}
        output<<"};\n";
        output<<"extern void omni_host_call(void **,void *);\n"
              <<"static uint32_t omni_body(uint32_t mode,const uint8_t *request,uint32_t request_len,"
              <<"uint8_t *result,uint32_t capacity,uint32_t *result_len){\n"
              <<"  if(mode>2)return OMNI_INVOCATION_V1_MALFORMED_INPUT;\n"
              <<"  "<<typeName(result)<<" value; memset(&value,0,sizeof value);\n"
              <<"  if(mode==2){\n"
              <<"    const OmniInvocationTypeV1 *return_types[1]={&omni_meta_"<<result<<"};\n"
              <<"    void *return_values[1]={&value};\n"
              <<"    return omni_invocation_decode_kind_v1(request,request_len,2,omni_signature,"
              <<"return_types,return_values,1);\n"
              <<"  }\n";
        for(size_t i=0;i<params.size();i++)
            output<<"  "<<typeName(params[i])<<" arg"<<i<<"; memset(&arg"<<i
                  <<",0,sizeof arg"<<i<<");\n";
        output<<"  void *args["<<(params.empty()?1:params.size())<<"] = {";
        if(params.empty())output<<"NULL";
        for(size_t i=0;i<params.size();i++){if(i)output<<',';output<<"&arg"<<i;}
        output<<"};\n  const OmniInvocationTypeV1 *types["<<(params.empty()?1:params.size())<<"] = {";
        if(params.empty())output<<"NULL";
        for(size_t i=0;i<params.size();i++){if(i)output<<',';output<<"&omni_meta_"<<params[i];}
        output<<"};\n  uint32_t status=omni_invocation_decode_v1(request,request_len,omni_signature,"
              <<"types,args,"<<params.size()<<");\n"
              <<"  if(status||mode==0)return status;\n"
              <<"  omni_host_call(args,&value);\n"
              <<"  status=omni_invocation_encode_v1(result,capacity,omni_signature,"
              <<"&omni_meta_"<<result<<",&value,result_len);\n"
              <<"  if(status)return status;\n";
        if(function->result.kind==Type::Result&&function->result.parts[1].kind==Type::U32)
            output<<"  return value.tag?OMNI_INVOCATION_V1_SEMANTIC_OK:OMNI_INVOCATION_V1_SEMANTIC_ERR;\n";
        else output<<"  return OMNI_INVOCATION_V1_SEMANTIC_OK;\n";
        output<<"}\n__attribute__((visibility(\"default\"))) uint32_t omni_module_v1_entry("
              <<"uint32_t mode,const uint8_t *request,uint32_t request_len,"
              <<"const uint8_t *policy,uint32_t policy_len,uint64_t policy_generation,"
              <<"uint64_t deadline_ns,uint64_t allocation_limit,const uint8_t trace_id[16],"
              <<"const uint32_t *cancel_flag,uint8_t *result,uint32_t result_capacity,"
              <<"uint32_t *result_len,uint32_t *effect_observation){\n"
              <<"  return omni_runtime_execute_invocation_v1(omni_body,mode,request,request_len,"
              <<"policy,policy_len,policy_generation,deadline_ns,allocation_limit,trace_id,"
              <<"cancel_flag,result,result_capacity,result_len,effect_observation);\n}\n";
        return output.str();
    }
};
}
std::string hostInvocationWrapperC(const HostBuildSelection& selection) {
    return Generator(selection.program).generate(selection);
}
}
