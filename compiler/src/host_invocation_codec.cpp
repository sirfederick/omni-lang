#include "host_invocation_codec.hpp"
#include <algorithm>
#include <limits>
#include <map>
#include <mutex>

namespace omni {
namespace {
[[noreturn]] void malformed() { fail("E_OMI_MALFORMED", "invalid OMI1 value frame"); }
[[noreturn]] void limited() { fail("E_OMI_LIMIT", "OMI1 limit exceeded"); }
constexpr uint8_t MAGIC[8]={'O','M','I','V','1',0,0,0};

uint8_t tag(const Type& type) {
    switch(type.kind) {
        case Type::Bool:return 0x01;
        case Type::U8:return 0x02; case Type::U16:return 0x03;
        case Type::U32:return 0x04; case Type::U64:return 0x05;
        case Type::I8:return 0x06; case Type::I16:return 0x07;
        case Type::I32:return 0x08; case Type::I64:return 0x09;
        case Type::Char:return 0x0a; case Type::Text:return 0x0b;
        case Type::Bytes:return 0x0c; case Type::Tuple:return 0x0d;
        case Type::Array:return 0x0e; case Type::Record:return 0x0f;
        case Type::Enum:return 0x10; case Type::Option:return 0x11;
        case Type::Result:return 0x12;
        default:fail("E_OMI_TYPE", "unsupported invocation value type");
    }
}
unsigned width(const Type& t) {
    switch(t.kind) {
        case Type::U8:case Type::I8:return 1;
        case Type::U16:case Type::I16:return 2;
        case Type::U32:case Type::I32:case Type::Char:return 4;
        case Type::U64:case Type::I64:return 8;
        default:return 0;
    }
}
bool scalarValid(uint32_t cp) {
    return cp<=0x10ffffu && !(cp>=0xd800u&&cp<=0xdfffu);
}
const RecordDef& recordFor(const Program& p,const Type& t) {
    for(const auto& d:p.records)if(d.key==t.key)return d;
    fail("E_OMI_TYPE", "unresolved invocation record");
}
const EnumDef& enumFor(const Program& p,const Type& t) {
    for(const auto& d:p.enums)if(d.key==t.key)return d;
    fail("E_OMI_TYPE", "unresolved invocation enum");
}
bool admitted(const Program& p,const Type& t,uint32_t depth,
              std::set<std::string>& active) {
    if(depth>OMI1_DEPTH_MAX)return false;
    switch(t.kind) {
        case Type::Bool:case Type::U8:case Type::U16:case Type::U32:
        case Type::U64:case Type::I8:case Type::I16:case Type::I32:
        case Type::I64:case Type::Char:case Type::Text:case Type::Bytes:
            return true;
        case Type::Tuple:
            if(t.parts.size()>UINT16_MAX)return false;
            for(const auto& x:t.parts)if(!admitted(p,x,depth+1,active))return false;
            return true;
        case Type::Array:
            return t.parts.size()==1 && t.extent<=OMI1_NODE_MAX &&
                admitted(p,t.parts.front(),depth+1,active);
        case Type::Option:
            return t.parts.size()==1 && admitted(p,t.parts.front(),depth+1,active);
        case Type::Result:
            return t.parts.size()==2 && admitted(p,t.parts[0],depth+1,active) &&
                admitted(p,t.parts[1],depth+1,active);
        case Type::Record: {
            if(t.key.empty()||!active.insert(t.key).second)return false;
            const auto& d=recordFor(p,t);bool ok=d.pub && d.fields.size()<=UINT16_MAX;
            for(const auto& f:d.fields)ok=ok&&admitted(p,f.type,depth+1,active);
            active.erase(t.key);return ok;
        }
        case Type::Enum: {
            if(t.key.empty()||!active.insert(t.key).second)return false;
            const auto& d=enumFor(p,t);bool ok=d.pub && d.variants.size()<=UINT16_MAX;
            for(const auto& v:d.variants)if(v.hasPayload)ok=ok&&admitted(p,v.payload,depth+1,active);
            active.erase(t.key);return ok;
        }
        default:return false;
    }
}
struct Reader {
    std::span<const uint8_t> b;size_t pos=0;uint32_t nodes=0;
    void need(size_t n) {if(n>b.size()-pos)malformed();}
    uint64_t integer(unsigned n) {
        need(n);uint64_t x=0;for(unsigned i=0;i<n;i++)x|=uint64_t(b[pos++])<<(8u*i);return x;
    }
    std::span<const uint8_t> bytes(size_t n) {need(n);auto s=b.subspan(pos,n);pos+=n;return s;}
    Value value(const Program& p,const Type& t,uint32_t depth) {
        if(depth>OMI1_DEPTH_MAX||++nodes>OMI1_NODE_MAX)limited();
        if(integer(1)!=tag(t))malformed();
        const auto id=invocationTypeId(t);auto found=bytes(32);
        if(!std::equal(found.begin(),found.end(),id.begin()))malformed();
        Value v(t);
        switch(t.kind) {
            case Type::Bool:v.bits=integer(1);if(v.bits>1)malformed();break;
            case Type::Char:v.bits=integer(4);if(!scalarValid(static_cast<uint32_t>(v.bits)))malformed();break;
            case Type::U8:case Type::U16:case Type::U32:case Type::U64:
            case Type::I8:case Type::I16:case Type::I32:case Type::I64:
                v.bits=integer(width(t));break;
            case Type::Text:case Type::Bytes: {
                auto n=integer(4);auto s=bytes(static_cast<size_t>(n));
                v.text.assign(reinterpret_cast<const char*>(s.data()),s.size());
                if(t.kind==Type::Text) {
                    if(v.text.find('\0')!=std::string::npos)malformed();
                    try {validateUTF8(v.text);}catch(const Error&) {malformed();}
                }
                break;
            }
            case Type::Tuple: {
                if(integer(2)!=t.parts.size())malformed();
                v.fields.reserve(t.parts.size());
                for(const auto& f:t.parts)v.fields.push_back(value(p,f,depth+1));
                break;
            }
            case Type::Array: {
                if(integer(4)!=t.extent)malformed();
                v.fields.reserve(t.extent);
                for(uint32_t i=0;i<t.extent;i++)v.fields.push_back(value(p,t.parts[0],depth+1));
                break;
            }
            case Type::Record: {
                const auto& d=recordFor(p,t);
                if(integer(2)!=d.fields.size())malformed();
                v.fields.reserve(d.fields.size());
                for(const auto& f:d.fields)v.fields.push_back(value(p,f.type,depth+1));
                break;
            }
            case Type::Enum: {
                const auto& d=enumFor(p,t);v.bits=integer(2);
                if(v.bits>=d.variants.size())malformed();
                const auto& selected=d.variants[static_cast<size_t>(v.bits)];
                if(integer(1)!=(selected.hasPayload?1u:0u))malformed();
                if(selected.hasPayload)v.fields.push_back(value(p,selected.payload,depth+1));
                break;
            }
            case Type::Option: {
                v.bits=integer(1);if(v.bits>1)malformed();
                if(v.bits)v.fields.push_back(value(p,t.parts[0],depth+1));
                break;
            }
            case Type::Result: {
                const auto arm=integer(1);if(arm>1)malformed();
                v.bits=arm==0?1u:0u;
                v.fields.push_back(value(p,t.parts[static_cast<size_t>(arm)],depth+1));
                break;
            }
            default:malformed();
        }
        return v;
    }
};
struct Writer {
    std::vector<uint8_t> b;uint32_t nodes=0;
    void integer(uint64_t x,unsigned n) {
        if(b.size()>OMI1_FRAME_MAX-n)limited();
        for(unsigned i=0;i<n;i++)b.push_back(static_cast<uint8_t>(x>>(8u*i)));
    }
    void bytes(std::span<const uint8_t> s) {
        if(s.size()>OMI1_FRAME_MAX-b.size())limited();
        b.insert(b.end(),s.begin(),s.end());
    }
    void value(const Program& p,const Type& t,const Value& v,uint32_t depth) {
        if(depth>OMI1_DEPTH_MAX||++nodes>OMI1_NODE_MAX)limited();
        if(v.type!=t)malformed();
        integer(tag(t),1);
        const auto id=invocationTypeId(t);bytes(id);
        switch(t.kind) {
            case Type::Bool:if(v.bits>1)malformed();integer(v.bits,1);break;
            case Type::Char:if(v.bits>UINT32_MAX||!scalarValid(static_cast<uint32_t>(v.bits)))malformed();integer(v.bits,4);break;
            case Type::U8:case Type::U16:case Type::U32:case Type::U64:
            case Type::I8:case Type::I16:case Type::I32:case Type::I64: {
                const auto n=width(t);
                if(n<8) {
                    const uint64_t lowMask=(uint64_t{1}<<(n*8u))-1u;
                    const uint64_t upper=v.bits&~lowMask;
                    const bool signedValue=t.kind==Type::I8||t.kind==Type::I16||
                                           t.kind==Type::I32;
                    const bool negative=(v.bits&(uint64_t{1}<<(n*8u-1u)))!=0;
                    if(upper!=0 && !(signedValue&&negative&&upper==~lowMask))malformed();
                }
                integer(v.bits,n);break;
            }
            case Type::Text:case Type::Bytes: {
                if(v.text.size()>UINT32_MAX)limited();
                if(t.kind==Type::Text) {
                    if(v.text.find('\0')!=std::string::npos)malformed();
                    try {validateUTF8(v.text);}catch(const Error&) {malformed();}
                }
                integer(v.text.size(),4);
                bytes(std::span<const uint8_t>(reinterpret_cast<const uint8_t*>(v.text.data()),v.text.size()));
                break;
            }
            case Type::Tuple:
                if(v.fields.size()!=t.parts.size())malformed();
                integer(v.fields.size(),2);
                for(size_t i=0;i<t.parts.size();i++)value(p,t.parts[i],v.fields[i],depth+1);
                break;
            case Type::Array:
                if(v.fields.size()!=t.extent)malformed();
                integer(t.extent,4);
                for(const auto& f:v.fields)value(p,t.parts[0],f,depth+1);
                break;
            case Type::Record: {
                const auto& d=recordFor(p,t);
                if(v.fields.size()!=d.fields.size())malformed();
                integer(d.fields.size(),2);
                for(size_t i=0;i<d.fields.size();i++)value(p,d.fields[i].type,v.fields[i],depth+1);
                break;
            }
            case Type::Enum: {
                const auto& d=enumFor(p,t);if(v.bits>=d.variants.size())malformed();
                const auto& selected=d.variants[static_cast<size_t>(v.bits)];
                if(v.fields.size()!=(selected.hasPayload?1u:0u))malformed();
                integer(v.bits,2);integer(selected.hasPayload?1u:0u,1);
                if(selected.hasPayload)value(p,selected.payload,v.fields[0],depth+1);
                break;
            }
            case Type::Option:
                if(v.bits>1||v.fields.size()!=v.bits)malformed();
                integer(v.bits,1);
                if(v.bits)value(p,t.parts[0],v.fields[0],depth+1);
                break;
            case Type::Result:
                if(v.bits>1||v.fields.size()!=1)malformed();
                integer(v.bits?0u:1u,1);
                value(p,t.parts[v.bits?0u:1u],v.fields[0],depth+1);
                break;
            default:malformed();
        }
    }
};
}

std::array<uint8_t,32> invocationTypeId(const Type& type) {
    // TypeIDs are identity data, never authority.  The canonical computation
    // remains the sole oracle; this bounded process cache only avoids repeated
    // SHA-256 derivation for already-admitted immutable type shapes.
    const auto identity=canonicalTypeIdentity(type);
    static std::mutex cacheMutex;
    static std::map<std::string,std::array<uint8_t,32>> cache;
    {std::lock_guard guard(cacheMutex);if(const auto found=cache.find(identity);found!=cache.end())return found->second;}
    const auto id=semanticTypeId(type);
    if(id.size()!=71||id.rfind("sha256:",0)!=0)fail("E_INTERNAL", "invalid semantic TypeID");
    std::array<uint8_t,32> raw{};
    auto nibble=[](char c)->uint8_t {
        if(c>='0'&&c<='9')return static_cast<uint8_t>(c-'0');
        if(c>='a'&&c<='f')return static_cast<uint8_t>(c-'a'+10);
        fail("E_INTERNAL", "invalid semantic TypeID hex");
    };
    for(size_t i=0;i<32;i++)raw[i]=static_cast<uint8_t>((nibble(id[7+i*2])<<4)|nibble(id[8+i*2]));
    {std::lock_guard guard(cacheMutex);if(cache.size()<OMI1_NODE_MAX)cache.emplace(identity,raw);}
    return raw;
}
uint8_t invocationTypeTag(const Type& type) { return tag(type); }
bool admittedInvocationType(const Program& p,const Type& t,uint32_t depth) {
    std::set<std::string> active;return admitted(p,t,depth,active);
}
std::vector<Value> decodeInvocationFrame(const Program& p,std::span<const uint8_t> frame,
        uint32_t kind,const std::array<uint8_t,32>& signature,const std::vector<Type>& expected) {
    if(frame.size()>OMI1_FRAME_MAX)limited();
    if(frame.size()<56)malformed();
    Reader r{frame};if(!std::equal(std::begin(MAGIC),std::end(MAGIC),frame.begin()))malformed();
    r.pos=8;if(r.integer(4)!=1)fail("E_OMI_VERSION", "unsupported OMI1 version");
    if(r.integer(4)!=kind)malformed();
    const auto found=r.bytes(32);if(!std::equal(found.begin(),found.end(),signature.begin()))malformed();
    if(r.integer(4)!=frame.size()-56 || r.integer(4)!=expected.size())malformed();
    std::vector<Value> values;values.reserve(expected.size());
    for(const auto& t:expected)values.push_back(r.value(p,t,0));
    if(r.pos!=frame.size())malformed();
    return values;
}
std::vector<uint8_t> encodeInvocationFrame(const Program& p,uint32_t kind,
        const std::array<uint8_t,32>& signature,const std::vector<Type>& expected,
        const std::vector<Value>& values) {
    if(expected.size()!=values.size()||expected.size()>UINT32_MAX)malformed();
    Writer w;w.bytes(MAGIC);w.integer(1,4);w.integer(kind,4);w.bytes(signature);
    w.integer(0,4);w.integer(expected.size(),4);
    for(size_t i=0;i<expected.size();i++)w.value(p,expected[i],values[i],0);
    const auto length=w.b.size()-56;
    for(unsigned i=0;i<4;i++)w.b[48+i]=static_cast<uint8_t>(length>>(i*8u));
    return std::move(w.b);
}
}
