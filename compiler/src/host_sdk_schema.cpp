#include "host_sdk_schema.hpp"
#include "host_invocation_codec.hpp"

namespace omni {
namespace {
constexpr uint8_t MAGIC[8]={'O','M','I','S','1',0,0,0};
constexpr uint32_t NODE_LIMIT=65536u;
constexpr uint32_t DEPTH_LIMIT=32u;
[[noreturn]] void bad(){fail("E_HOST_SDK_SCHEMA","invalid OMIS1 schema");}

struct Writer {
    std::vector<uint8_t> bytes;
    void u8(uint8_t value){bytes.push_back(value);}
    void u32(uint32_t value){for(unsigned i=0;i<4;i++)bytes.push_back(static_cast<uint8_t>(value>>(8u*i)));}
    void hash(const InvocationHash& value){bytes.insert(bytes.end(),value.begin(),value.end());}
    void text(const std::string& value){
        if(value.size()>UINT32_MAX||value.find('\0')!=std::string::npos)bad();
        try{validateUTF8(value);}catch(const Error&){bad();}
        u32(static_cast<uint32_t>(value.size()));
        bytes.insert(bytes.end(),value.begin(),value.end());
    }
};
struct Reader {
    std::span<const uint8_t> bytes;size_t pos=0;
    std::span<const uint8_t> take(size_t size){if(size>bytes.size()-pos)bad();auto result=bytes.subspan(pos,size);pos+=size;return result;}
    uint8_t u8(){return take(1)[0];}
    uint32_t u32(){const auto value=take(4);return uint32_t(value[0])|(uint32_t(value[1])<<8)|(uint32_t(value[2])<<16)|(uint32_t(value[3])<<24);}
    InvocationHash hash(){InvocationHash value{};const auto found=take(value.size());std::copy(found.begin(),found.end(),value.begin());return value;}
    std::string text(){const auto found=take(u32());std::string value(reinterpret_cast<const char*>(found.data()),found.size());if(value.find('\0')!=std::string::npos)bad();try{validateUTF8(value);}catch(const Error&){bad();}return value;}
};
const RecordDef& recordFor(const Program& p,const Type& t){for(const auto& d:p.records)if(d.key==t.key)return d;fail("E_HOST_SDK_SCHEMA","unresolved record");}
const EnumDef& enumFor(const Program& p,const Type& t){for(const auto& d:p.enums)if(d.key==t.key)return d;fail("E_HOST_SDK_SCHEMA","unresolved enum");}

class Builder {
    const Program& program;
    std::vector<HostSdkSchemaNode> nodes;
    std::map<std::string,uint32_t> seen;
public:
    explicit Builder(const Program& value):program(value){}
    uint32_t add(const Type& type,uint32_t depth=0){
        if(depth>DEPTH_LIMIT||nodes.size()>=NODE_LIMIT)bad();
        const auto key=canonicalTypeIdentity(type);
        if(const auto it=seen.find(key);it!=seen.end())return it->second;
        const uint32_t index=static_cast<uint32_t>(nodes.size());
        nodes.push_back({invocationTypeTag(type),invocationTypeId(type),
                         (type.kind==Type::Record||type.kind==Type::Enum)?type.key:"",
                         type.extent,{},{}});
        seen.emplace(key,index);
        auto child=[&](const Type& value,const std::string& label){const auto childIndex=add(value,depth+1);nodes[index].children.push_back(childIndex);nodes[index].labels.push_back(label);};
        switch(type.kind){
            case Type::Tuple:for(size_t i=0;i<type.parts.size();i++)child(type.parts[i],std::to_string(i));break;
            case Type::Array:child(type.parts.at(0),"element");break;
            case Type::Option:child(type.parts.at(0),"Some");break;
            case Type::Result:child(type.parts.at(0),"Ok");child(type.parts.at(1),"Err");break;
            case Type::Record:{const auto& record=recordFor(program,type);for(const auto& field:record.fields)child(field.type,field.name);break;}
            case Type::Enum:{const auto& enumeration=enumFor(program,type);for(const auto& variant:enumeration.variants){if(variant.hasPayload)child(variant.payload,variant.name);else {nodes[index].children.push_back(UINT32_MAX);nodes[index].labels.push_back(variant.name);}}break;}
            default:break;
        }
        return index;
    }
    std::vector<HostSdkSchemaNode> take(){return std::move(nodes);}
};

void validateNode(const HostSdkSchema& schema,uint32_t index,uint32_t depth,std::vector<uint8_t>& visiting){
    if(index>=schema.nodes.size()||depth>DEPTH_LIMIT||visiting[index])bad();
    visiting[index]=1;const auto& node=schema.nodes[index];
    if(node.tag<0x01||node.tag>0x12||node.labels.size()!=node.children.size())bad();
    if(node.tag==0x0e&&node.children.size()!=1)bad();
    if(node.tag==0x11&&node.children.size()!=1)bad();
    if(node.tag==0x12&&node.children.size()!=2)bad();
    for(const auto child:node.children)if(child!=UINT32_MAX)validateNode(schema,child,depth+1,visiting);
    visiting[index]=0;
}
}

std::vector<uint8_t> encodeHostSdkSchema(const Program& program,const std::vector<Type>& parameters,const Type& result,const InvocationHash& signature){
    Builder builder(program);std::vector<uint32_t> roots;roots.reserve(parameters.size());
    for(const auto& parameter:parameters)roots.push_back(builder.add(parameter));
    const uint32_t resultRoot=builder.add(result);const auto nodes=builder.take();
    Writer writer;writer.bytes.insert(writer.bytes.end(),std::begin(MAGIC),std::end(MAGIC));writer.u32(1);writer.hash(signature);writer.u32(static_cast<uint32_t>(nodes.size()));
    for(const auto& node:nodes){writer.u8(node.tag);writer.hash(node.typeId);writer.text(node.nominalKey);writer.u32(node.extent);writer.u32(static_cast<uint32_t>(node.children.size()));for(const auto child:node.children)writer.u32(child);for(const auto& label:node.labels)writer.text(label);}
    writer.u32(static_cast<uint32_t>(roots.size()));for(const auto root:roots)writer.u32(root);writer.u32(resultRoot);return std::move(writer.bytes);
}

HostSdkSchema decodeHostSdkSchema(std::span<const uint8_t> bytes){
    Reader reader{bytes};const auto magic=reader.take(8);if(!std::equal(magic.begin(),magic.end(),std::begin(MAGIC)))bad();
    HostSdkSchema schema;schema.version=reader.u32();if(schema.version!=1)bad();schema.signature=reader.hash();const auto count=reader.u32();if(count==0||count>NODE_LIMIT)bad();schema.nodes.reserve(count);
    for(uint32_t i=0;i<count;i++){HostSdkSchemaNode node;node.tag=reader.u8();node.typeId=reader.hash();node.nominalKey=reader.text();node.extent=reader.u32();const auto children=reader.u32();if(children>NODE_LIMIT||children>(bytes.size()-reader.pos)/8u)bad();node.children.reserve(children);node.labels.reserve(children);for(uint32_t j=0;j<children;j++)node.children.push_back(reader.u32());for(uint32_t j=0;j<children;j++)node.labels.push_back(reader.text());schema.nodes.push_back(std::move(node));}
    const auto roots=reader.u32();if(roots>count)bad();schema.requestRoots.reserve(roots);for(uint32_t i=0;i<roots;i++)schema.requestRoots.push_back(reader.u32());schema.resultRoot=reader.u32();if(reader.pos!=bytes.size())bad();
    std::vector<uint8_t> visiting(schema.nodes.size());for(const auto root:schema.requestRoots)validateNode(schema,root,0,visiting);validateNode(schema,schema.resultRoot,0,visiting);return schema;
}

void validateHostSdkSchema(const HostSdkSchema& schema,const HostInvocationDescriptor& descriptor){
    if(schema.version!=1||schema.signature!=descriptor.signatureDigest||schema.requestRoots.size()!=descriptor.parameterTypeIds.size())bad();
    for(size_t i=0;i<schema.requestRoots.size();i++)if(schema.nodes.at(schema.requestRoots[i]).typeId!=descriptor.parameterTypeIds[i])bad();
    if(schema.nodes.at(schema.resultRoot).typeId!=descriptor.returnTypeId)bad();
}

namespace {
struct SchemaProjection { Program program;std::vector<Type> types; };

SchemaProjection projectSchema(const HostSdkSchema& schema){
    SchemaProjection projection;auto& program=projection.program;program.module="omni.host-sdk.schema";
    auto& types=projection.types;types.resize(schema.nodes.size());std::vector<uint8_t> state(types.size());
    auto build=[&](auto&& self,uint32_t index)->Type {
        if(index>=types.size()||state[index]==1)bad();
        if(state[index]==2)return types[index];
        state[index]=1;const auto& node=schema.nodes[index];Type type;
        switch(node.tag){
            case 0x01:type=Type(Type::Bool);break;case 0x02:type=Type(Type::U8);break;
            case 0x03:type=Type(Type::U16);break;case 0x04:type=Type(Type::U32);break;
            case 0x05:type=Type(Type::U64);break;case 0x06:type=Type(Type::I8);break;
            case 0x07:type=Type(Type::I16);break;case 0x08:type=Type(Type::I32);break;
            case 0x09:type=Type(Type::I64);break;case 0x0a:type=Type(Type::Char);break;
            case 0x0b:type=Type(Type::Text);break;case 0x0c:type=Type(Type::Bytes);break;
            case 0x0d:type=Type(Type::Tuple);break;case 0x0e:type=Type(Type::Array);type.extent=node.extent;break;
            case 0x0f:type=Type(Type::Record);break;case 0x10:type=Type(Type::Enum);break;
            case 0x11:type=Type(Type::Option);break;case 0x12:type=Type(Type::Result);break;
            default:bad();
        }
        if((type.kind==Type::Record||type.kind==Type::Enum)?node.nominalKey.empty():!node.nominalKey.empty())bad();
        if(type.kind==Type::Record||type.kind==Type::Enum)type.name=type.key=node.nominalKey;
        for(const auto child:node.children)if(child!=UINT32_MAX)type.parts.push_back(self(self,child));
        if(invocationTypeId(type)!=node.typeId)bad();
        types[index]=type;state[index]=2;return type;
    };
    for(uint32_t i=0;i<types.size();i++)(void)build(build,i);
    for(size_t i=0;i<schema.nodes.size();i++){
        const auto& type=types[i];const auto& node=schema.nodes[i];
        if(type.kind==Type::Record){RecordDef record;record.name=record.key=type.key;record.pub=true;for(size_t j=0;j<node.children.size();j++){if(node.children[j]==UINT32_MAX)bad();record.fields.push_back({node.labels[j],types.at(node.children[j]),{}});}program.records.push_back(std::move(record));}
        if(type.kind==Type::Enum){EnumDef enumeration;enumeration.name=enumeration.key=type.key;enumeration.pub=true;for(size_t j=0;j<node.children.size();j++){VariantDef variant;variant.name=node.labels[j];variant.hasPayload=node.children[j]!=UINT32_MAX;if(variant.hasPayload)variant.payload=types.at(node.children[j]);enumeration.variants.push_back(std::move(variant));}program.enums.push_back(std::move(enumeration));}
    }
    return projection;
}
}

Program hostSdkSchemaProgram(const HostSdkSchema& schema){return projectSchema(schema).program;}

std::vector<Type> hostSdkSchemaRequestTypes(const HostSdkSchema& schema,const Program& program){
    (void)program;const auto projection=projectSchema(schema);
    std::vector<Type> values;values.reserve(schema.requestRoots.size());
    for(const auto root:schema.requestRoots)values.push_back(projection.types.at(root));
    return values;
}

Type hostSdkSchemaResultType(const HostSdkSchema& schema,const Program& program){
    (void)program;return projectSchema(schema).types.at(schema.resultRoot);
}

Type hostSdkSchemaNodeType(const HostSdkSchema& schema,const Program& program,uint32_t node){
    (void)program;return projectSchema(schema).types.at(node);
}
}
