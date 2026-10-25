#include "omni.hpp"
namespace omni  {
    bool validIdentifier(const std::string& s)  {
        auto alpha=[](unsigned char c)  {
            return (c>='a'&&c<='z')||(c>='A'&&c<='Z')||c=='_';
        };
        if(s.empty()||s.size()>128||!alpha(static_cast<unsigned char>(s[0]))) return false;
        for(char raw:s){ const auto c=static_cast<unsigned char>(raw); if(!alpha(c)&&!(c>='0'&&c<='9')) return false; }
        static const std::set<std::string> reserved=  {
            "module","func","let","var","return","if","else","for","in","break","continue","print","true","false",
            "u8","u16","u32","u64","i8","i16","i32","i64","f32","f64",
            "bool","Char","Text","Bytes","Resource","Borrow","Future","Stream","Tuple","Array","View","Range","import","struct","enum","trait","impl","for","match","pub","bundle","Result","Option","Ok","Err","Some","None","closure","infer","task_scope","spawn","join","cancel","deadline","channel","send","receive","close"
        };
        return !reserved.count(s);
    }
    void validateUTF8(const std::string& s)  {
        for(size_t i=0; i<s.size(); )  {
            auto c=static_cast<unsigned char>(s[i++]);
            if(c==0) fail("E_UTF8","NUL no permitido en entrada textual");
            if(c<128) continue;
            int n;
            uint32_t cp, min;
            if((c&224)==192)  {
                n=1;
                cp=c&31;
                min=128;
            }
            else if((c&240)==224)  {
                n=2;
                cp=c&15;
                min=2048;
            }
            else if((c&248)==240)  {
                n=3;
                cp=c&7;
                min=65536;
            }
            else fail("E_UTF8","UTF-8 invalido");
            while(n--)  {
                if(i>=s.size()) fail("E_UTF8","UTF-8 truncado");
                auto d=static_cast<unsigned char>(s[i++]);
                if((d&192)!=128) fail("E_UTF8","UTF-8 invalido");
                cp=(cp<<6)|(d&63);
            }
            if(cp<min||cp>0x10ffff||(cp>=0xd800&&cp<=0xdfff)) fail("E_UTF8","punto Unicode invalido");
        }
    }
    std::string quote(const std::string& s)  {
        std::string r="\"";
        for(char c:s)  {
            switch(c)  {
                case '\\':r+="\\\\";
                break;
                case '"':r+="\\\"";
                break;
                case '\n':r+="\\n";
                break;
                case '\r':r+="\\r";
                break;
                case '\t':r+="\\t";
                break;
                default:r+=c;
            }
        }
        return r+'"';
    }
    struct Token  {
        std::string s;
        Loc loc;
        bool str=false;
    };
    class Lexer  {
        const std::string& s;
        size_t p=0,line=1,col=1;
        char take()  {
            char c=s[p++];
            if(c=='\n')  {
                line++;
                col=1;
            }
            else col++;
            return c;
        }
        public: explicit Lexer(const std::string& x):s(x)  {
        }
        std::vector<Token> run()  {
            std::vector<Token> t;
            while(p<s.size())  {
                unsigned char c=static_cast<unsigned char>(s[p]);
                if(std::isspace(c))  {
                    take();
                    continue;
                }
                if(c=='/'&&p+1<s.size()&&s[p+1]=='/')  {
                    while(p<s.size()&&s[p]!='\n')take();
                    continue;
                }
                Loc l  {
                    line,col
                };
                std::string v;
                if(c=='"')  {
                    take();
                    bool closed=false;
                    while(p<s.size())  {
                        char d=take();
                        if(d=='"')  {
                            closed=true;
                            break;
                        }
                        if(d=='\n'||d=='\r')fail("E_STRING","salto de linea literal no escapado",l);
                        if(d=='\\')  {
                            if(p==s.size())fail("E_STRING","escape truncado",l);
                            d=take();
                            switch(d)  {
                                case 'n':d='\n';
                                break;
                                case 'r':d='\r';
                                break;
                                case 't':d='\t';
                                break;
                                case '\\':case '"':break;
                                default:fail("E_STRING","escape no soportado",l);
                            }
                        }
                        if(static_cast<unsigned char>(d)<32&&d!='\n'&&d!='\r'&&d!='\t')fail("E_STRING","control no permitido",l);
                        v+=d;
                        if(v.size()>4096)fail("E_LIMIT","literal demasiado largo",l);
                    }
                    if(!closed)fail("E_STRING","cadena sin cierre",l);
                    t.push_back(  {
                        v,l,true
                    });
                }
                else if(std::isdigit(c))  {
                    while(p<s.size()&&std::isdigit(static_cast<unsigned char>(s[p])))v+=take();
                    if(p+1<s.size()&&s[p]=='.'&&std::isdigit(static_cast<unsigned char>(s[p+1]))) {
                        v+=take();
                        while(p<s.size()&&std::isdigit(static_cast<unsigned char>(s[p])))v+=take();
                    }
                    if(p<s.size()&&(s[p]=='e'||s[p]=='E')) {
                        v+=take();
                        if(p<s.size()&&(s[p]=='+'||s[p]=='-'))v+=take();
                        if(p==s.size()||!std::isdigit(static_cast<unsigned char>(s[p])))fail("E_NUMBER","exponente flotante invalido",l);
                        while(p<s.size()&&std::isdigit(static_cast<unsigned char>(s[p])))v+=take();
                    }
                    while(p<s.size()&&(std::isalnum(static_cast<unsigned char>(s[p]))||s[p]=='_'))v+=take();
                    if(v.size()>128)fail("E_LIMIT","token numerico demasiado largo",l);
                    t.push_back({v,l,false});
                }
                else if(std::isalpha(c)||c=='_')  {
                    while(p<s.size()&&(std::isalnum(static_cast<unsigned char>(s[p]))||s[p]=='_'))v+=take();
                    if(v.size()>128)fail("E_LIMIT","token demasiado largo",l);
                    t.push_back(  {
                        v,l,false
                    });
                }
                else  {
                    if(p+1<s.size())  {
                        auto pair=s.substr(p,2);
                        if(pair=="=="||pair=="!="||pair=="<="||pair==">="||pair=="&&"||pair=="||"||pair=="::"||pair==".."||
                           pair=="+%"||pair=="-%"||pair=="*%"||pair=="+|"||pair=="-|"||pair=="*|")  {
                            char first=take();
                            char second=take();
                            v=std::string()+first+second;
                        }
                    }
                    if(v.empty())  {
                        v=take();
                        if(std::string("(){}[]!,;=+-*/%<>.:?").find(v)==std::string::npos)fail("E_LEX","caracter no soportado",l);
                    }
                    t.push_back(  {
                        v,l,false
                    });
                }
                if((t.size()&1023u)==0u)budgetCheck("el lexer");   // the tokens live in memory: the budget, not a count, bounds them
            }
            t.push_back(  {
                "<eof>",  {
                    line,col
                } ,false
            });
            return t;
        }
    };
    std::vector<std::pair<std::string,Loc>> sourceIdentifiers(const std::string& text) {
        std::vector<std::pair<std::string,Loc>> result;
        for(const auto& token:Lexer(text).run())
            if(!token.str&&validIdentifier(token.s))result.emplace_back(token.s,token.loc);
        return result;
    }
    bool validQualified(const std::string& s)  {
        if(s.empty()||s.size()>384)return false;
        size_t start=0,parts=0;
        while(start<s.size()) {
            auto dot=s.find('.',start);
            auto part=s.substr(start,dot==std::string::npos?std::string::npos:dot-start);
            if(!validIdentifier(part)||++parts>3)return false;
            if(dot==std::string::npos)break;
            start=dot+1;
        }
        return true;
    }
    bool isInteger(const Type& t) {
        return t.kind==Type::U8||t.kind==Type::U16||t.kind==Type::U32||t.kind==Type::U64||
               t.kind==Type::I8||t.kind==Type::I16||t.kind==Type::I32||t.kind==Type::I64;
    }
    bool isSignedInteger(const Type& t) {
        return t.kind==Type::I8||t.kind==Type::I16||t.kind==Type::I32||t.kind==Type::I64;
    }
    unsigned integerWidth(const Type& t) {
        switch(t.kind) {
            case Type::U8: case Type::I8:return 8;
            case Type::U16:case Type::I16:return 16;
            case Type::U32:case Type::I32:return 32;
            case Type::U64:case Type::I64:return 64;
            default: fail("E_TYPE","tipo no entero: "+typeName(t));
        }
    }
    uint64_t integerMaxUnsigned(const Type& t) {
        const auto w=integerWidth(t);
        return w==64?UINT64_MAX:((uint64_t(1)<<w)-1);
    }
    int64_t integerMinSigned(const Type& t) {
        const auto w=integerWidth(t);
        return w==64?INT64_MIN:-int64_t(uint64_t(1)<<(w-1));
    }
    int64_t integerMaxSigned(const Type& t) {
        const auto w=integerWidth(t);
        return w==64?INT64_MAX:int64_t((uint64_t(1)<<(w-1))-1);
    }
    static Type integerTypeByName(const std::string& n,Loc p={}) {
        if(n=="u8")return Type::U8;
        if(n=="u16")return Type::U16;
        if(n=="u32")return Type::U32;
        if(n=="u64")return Type::U64;
        if(n=="i8")return Type::I8;
        if(n=="i16")return Type::I16;
        if(n=="i32")return Type::I32;
        if(n=="i64")return Type::I64;
        fail("E_TYPE","tipo entero no soportado: "+n,p);
    }
    bool isFloat(const Type& t) {
        return t.kind==Type::F32||t.kind==Type::F64;
    }
    unsigned floatWidth(const Type& t) {
        if(t.kind==Type::F32)return 32;
        if(t.kind==Type::F64)return 64;
        fail("E_TYPE","tipo no flotante: "+typeName(t));
    }
    static Type floatTypeByName(const std::string& n,Loc p={}) {
        if(n=="f32")return Type::F32;
        if(n=="f64")return Type::F64;
        fail("E_TYPE","tipo flotante no soportado: "+n,p);
    }
    static uint64_t parseFloatLiteralBits(const std::string& text,const Type& t,Loc p={}) {
        if(t.kind==Type::F32) {
            float v=0.0f;
            auto r=std::from_chars(text.data(),text.data()+text.size(),v,std::chars_format::general);
            if(r.ec!=std::errc{}||r.ptr!=text.data()+text.size()||!std::isfinite(v))
                fail("E_OVERFLOW_LITERAL","literal f32 invalido/fuera de rango",p);
            return static_cast<uint64_t>(std::bit_cast<uint32_t>(v));
        }
        if(t.kind==Type::F64) {
            double v=0.0;
            auto r=std::from_chars(text.data(),text.data()+text.size(),v,std::chars_format::general);
            if(r.ec!=std::errc{}||r.ptr!=text.data()+text.size()||!std::isfinite(v))
                fail("E_OVERFLOW_LITERAL","literal f64 invalido/fuera de rango",p);
            return std::bit_cast<uint64_t>(v);
        }
        fail("E_TYPE","literal flotante requiere f32/f64",p);
    }
    static std::string formatFloatLiteral(const Type& t,uint64_t bits) {
        char buf[128];
        if(t.kind==Type::F32) {
            const auto v=std::bit_cast<float>(static_cast<uint32_t>(bits));
            auto r=std::to_chars(buf,buf+sizeof(buf),v,std::chars_format::general,std::numeric_limits<float>::max_digits10);
            if(r.ec!=std::errc{})fail("E_INTERNAL","no se pudo formatear f32");
            return std::string(buf,r.ptr)+"f32";
        }
        if(t.kind==Type::F64) {
            const auto v=std::bit_cast<double>(bits);
            auto r=std::to_chars(buf,buf+sizeof(buf),v,std::chars_format::general,std::numeric_limits<double>::max_digits10);
            if(r.ec!=std::errc{})fail("E_INTERNAL","no se pudo formatear f64");
            return std::string(buf,r.ptr)+"f64";
        }
        fail("E_TYPE","formato flotante requiere f32/f64");
    }
    std::string semanticTypeId(const Type& t) {
        if(hasUnresolvedNominalIdentity(t))fail("E_TYPE","semantic TypeID requires resolved nominal identity");
        return "sha256:"+sha256("omni.type/1\n"+canonicalTypeIdentity(t));
    }

    std::string typeDescriptorJson(const Type& t) {
        if(hasUnresolvedNominalIdentity(t))fail("E_TYPE","nominal type descriptor requires resolved project context");

        std::ostringstream out;
        const auto display=typeName(t);
        const auto canonical=canonicalTypeIdentity(t);
        const auto typeId=semanticTypeId(t);
        std::string legacyMaterial;

        if(isInteger(t)) {
            std::ostringstream legacy;
            legacy<<"integer|"<<display<<"|bits="<<integerWidth(t)<<"|signed="<<(isSignedInteger(t)?"true":"false")
                  <<"|default=checked|wrapping=explicit|saturating=explicit";
            legacyMaterial=legacy.str();

            out<<"{\n  \"schema\": \"omni.type-descriptor/2\",\n"
               <<"  \"name\": "<<quote(display)<<",\n  \"kind\": \"integer\",\n"
               <<"  \"width_bits\": "<<integerWidth(t)<<",\n"
               <<"  \"signed\": "<<(isSignedInteger(t)?"true":"false")<<",\n"
               <<"  \"arithmetic\": {\"default\": \"checked\", \"wrapping\": \"explicit\", \"saturating\": \"explicit\"},\n"
               <<"  \"type_identity_domain\": \"omni.type/1\",\n"
               <<"  \"canonical_identity_material\": "<<quote(canonical)<<",\n"
               <<"  \"type_id\": "<<quote(typeId)<<",\n"
               <<"  \"legacy_descriptor_schema\": \"omni.type-descriptor/1\",\n"
               <<"  \"legacy_descriptor_identity_material\": "<<quote(legacyMaterial)<<",\n"
               <<"  \"legacy_descriptor_id\": \"sha256:"<<sha256(legacyMaterial)<<"\"\n"
               <<"}\n";
            return out.str();
        }

        if(isFloat(t)) {
            std::ostringstream legacy;
            legacy<<"float|"<<display<<"|bits="<<floatWidth(t)<<"|ieee754=true";
            legacyMaterial=legacy.str();
            out<<"{\n  \"schema\": \"omni.type-descriptor/2\",\n"
               <<"\"name\": "<<quote(display)<<",\n  \"kind\": \"float\",\n"
               <<"\"width_bits\": "<<floatWidth(t)<<",\n"
               <<"\"ieee754\": true,\n"
               <<"\"type_identity_domain\": \"omni.type/1\",\n"
               <<"\"canonical_identity_material\": "<<quote(canonical)<<",\n"
               <<"\"type_id\": "<<quote(typeId)<<",\n"
               <<"\"legacy_descriptor_schema\": \"omni.type-descriptor/1\",\n"
               <<"\"legacy_descriptor_identity_material\": "<<quote(legacyMaterial)<<",\n"
               <<"\"legacy_descriptor_id\": \"sha256:"<<sha256(legacyMaterial)<<"\"\n"
               <<"}\n";
            return out.str();
        }

        if(t.kind==Type::Char) {
            legacyMaterial="char|unicode-scalar|bits=32";
            out<<"{\n  \"schema\": \"omni.type-descriptor/2\",\n"
               <<"  \"name\": \"Char\",\n"
               <<"  \"kind\": \"unicode-scalar\",\n"
               <<"  \"width_bits\": 32,\n"
               <<"  \"valid_range\": \"U+0000..U+10FFFF excluding surrogates\",\n"
               <<"  \"type_identity_domain\": \"omni.type/1\",\n"
               <<"  \"canonical_identity_material\": "<<quote(canonical)<<",\n"
               <<"  \"type_id\": "<<quote(typeId)<<",\n"
               <<"  \"legacy_descriptor_schema\": \"omni.type-descriptor/1\",\n"
               <<"  \"legacy_descriptor_identity_material\": "<<quote(legacyMaterial)<<",\n"
               <<"  \"legacy_descriptor_id\": \"sha256:"<<sha256(legacyMaterial)<<"\"\n"
               <<"}\n";
            return out.str();
        }

        const std::string kind=(t.kind==Type::Tuple||t.kind==Type::Array)?"product":
                               (t.kind==Type::Range?"range":
                               (t.kind==Type::View?"borrowed-view":
                               (t.kind==Type::Borrow?"borrowed-resource":
                               (t.kind==Type::BorrowMut?"borrowed-resource-mutable":"non-numeric"))));
        legacyMaterial="type|"+display;

        out<<"{\n  \"schema\": \"omni.type-descriptor/2\",\n"
           <<"  \"name\": "<<quote(display)
           <<",\n  \"kind\": "<<quote(kind);
        if(t.kind==Type::Array) out<<",\n  \"element_type\": "<<quote(typeName(t.parts.at(0)))<<",\n  \"length\": "<<t.extent;
        if(t.kind==Type::Range) out<<",\n  \"element_type\": "<<quote(typeName(t.parts.at(0)))<<",\n  \"bounds\": \"u32-start-end\",\n  \"end_mode\": \"exclusive-or-inclusive\",\n  \"ownership\": \"copy\"";
        if(t.kind==Type::View) out<<",\n  \"element_type\": "<<quote(typeName(t.parts.at(0)))<<",\n  \"ownership\": \"borrowed-readonly\",\n  \"portable_address\": false";
        if(t.kind==Type::Borrow) out<<",\n  \"ownership\": \"borrowed-shared-readonly\",\n  \"portable_address\": false";
        if(t.kind==Type::BorrowMut) out<<",\n  \"ownership\": \"borrowed-exclusive-mutable\",\n  \"portable_address\": false";
        if(t.kind==Type::Resource) out<<",\n  \"ownership\": \"owned-resource-opaque\",\n  \"portable_address\": false";
        if(t.kind==Type::Tuple){
            out<<",\n  \"elements\": [";
            for(size_t i=0;i<t.parts.size();++i){if(i)out<<", ";out<<quote(typeName(t.parts[i]));}
            out<<"]";
        }
        out<<",\n  \"type_identity_domain\": \"omni.type/1\""
           <<",\n  \"canonical_identity_material\": "<<quote(canonical)
           <<",\n  \"type_id\": "<<quote(typeId)
           <<",\n  \"legacy_descriptor_schema\": \"omni.type-descriptor/1\""
           <<",\n  \"legacy_descriptor_identity_material\": "<<quote(legacyMaterial)
           <<",\n  \"legacy_descriptor_id\": \"sha256:"<<sha256(legacyMaterial)<<"\"\n"
           <<"}\n";
        return out.str();
    }

    namespace {
        struct CanonLayout { bool eligible=false; uint64_t size=0,align=1; std::vector<uint64_t> offsets; std::string reason; };
        uint64_t alignUp(uint64_t n,uint64_t a){ return a<=1?n:((n+a-1)/a)*a; }
        CanonLayout canonLayout(const Type& t,int depth=0){
            if(depth>16)return {false,0,1,{},"type nesting too deep"};
            if(isInteger(t)){ auto n=integerWidth(t)/8; return {true,n,n,{},""}; }
            if(isFloat(t)){ auto n=floatWidth(t)/8; return {true,n,n,{},""}; }
            if(t.kind==Type::Char)return {true,4,4,{},""};
            if(t.kind==Type::Bool)return {true,1,1,{},""};
            if(t.kind==Type::Range){
                if(t.parts.size()!=1||t.parts[0].kind!=Type::U32)return {false,0,1,{},"Range currently requires u32"};
                return {true,12,4,{0,4,8},""};
            }
            if(t.kind==Type::Array){
                if(t.parts.size()!=1)return {false,0,1,{},"invalid array element type"};
                auto e=canonLayout(t.parts[0],depth+1); if(!e.eligible)return e;
                if(e.size && t.extent>UINT64_MAX/e.size)return {false,0,1,{},"layout overflow"};
                return {true,e.size*t.extent,e.align,{},""};
            }
            if(t.kind==Type::Tuple){
                CanonLayout r; r.eligible=true; r.size=0; r.align=1;
                for(const auto& p:t.parts){ auto c=canonLayout(p,depth+1); if(!c.eligible)return c; r.size=alignUp(r.size,c.align); r.offsets.push_back(r.size); if(c.size>UINT64_MAX-r.size)return {false,0,1,{},"layout overflow"}; r.size+=c.size; r.align=std::max(r.align,c.align); }
                r.size=alignUp(r.size,r.align); return r;
            }
            return {false,0,1,{},"type is not canonical plain-data in layout/1"};
        }
    }
    std::string layoutDescriptorJson(const Type& t){
        if(hasUnresolvedNominalIdentity(t))fail("E_TYPE","nominal layout descriptor requires resolved project context");
        const auto c=canonLayout(t); const auto tn=typeName(t);
        std::ostringstream material; material<<"omni.layout/1|little-endian|natural-align|"<<tn;
        if(c.eligible){ material<<"|size="<<c.size<<"|align="<<c.align; for(auto x:c.offsets)material<<"|off="<<x; }
        std::ostringstream o;
        o<<"{\n  \"schema\": \"omni.layout-descriptor/1\",\n"
         <<"  \"type\": "<<quote(tn)<<",\n"
         <<"  \"representation\": \"canonical-little-endian-v1\",\n"
         <<"  \"zero_copy_candidate\": "<<(c.eligible?"true":"false")<<",\n"
         <<"  \"size_bytes\": "<<c.size<<",\n  \"alignment_bytes\": "<<c.align;
        if(t.kind==Type::Array) o<<",\n  \"element_type\": "<<quote(typeName(t.parts.at(0)))<<",\n  \"length\": "<<t.extent;
        if(t.kind==Type::View) o<<",\n  \"element_type\": "<<quote(typeName(t.parts.at(0)))<<",\n  \"ownership\": \"borrowed-readonly\",\n  \"portable_address\": false";
        if(t.kind==Type::Borrow) o<<",\n  \"ownership\": \"borrowed-shared-readonly\",\n  \"portable_address\": false";
        if(t.kind==Type::BorrowMut) o<<",\n  \"ownership\": \"borrowed-exclusive-mutable\",\n  \"portable_address\": false";
        if(t.kind==Type::Resource) o<<",\n  \"ownership\": \"owned-resource-opaque\",\n  \"portable_address\": false";
        if(t.kind==Type::Tuple||t.kind==Type::Range){ o<<",\n  \"field_offsets\": ["; for(size_t i=0;i<c.offsets.size();++i){if(i)o<<", ";o<<c.offsets[i];} o<<"]"; }
        if(!c.eligible)o<<",\n  \"reason\": "<<quote(c.reason);
        o<<",\n  \"canonical_identity_material\": "<<quote(material.str())
         <<",\n  \"layout_id\": \"sha256:"<<sha256(material.str())<<"\"\n}\n";
        return o.str();
    }

    Type parseType(const std::string& s,Loc p)  {
        if(s.size()>512)fail("E_LIMIT","tipo demasiado largo",p);
        size_t i=0;
        std::function<Type(int)> one=[&](int d)->Type  {
            if(d>OMNI_LIMIT_TYPE_DEPTH)fail("E_LIMIT","tipo demasiado profundo",p);
            size_t start=i;
            while(i<s.size()&&(std::isalnum(static_cast<unsigned char>(s[i]))||s[i]=='_'||s[i]=='.'))i++;
            auto n=s.substr(start,i-start);
            if(n=="Result")  {
                Type t(Type::Result);
                if(i==s.size()||s[i++]!='<')fail("E_TYPE","Result requiere dos tipos",p);
                t.parts.push_back(one(d+1));
                if(i==s.size()||s[i++]!=',')fail("E_TYPE","Result requiere dos tipos",p);
                t.parts.push_back(one(d+1));
                if(i==s.size()||s[i++]!='>')fail("E_TYPE","Result sin cierre",p);
                return t;
            }
            if(n=="Option"||n=="Future"||n=="Stream") {
                Type t(n=="Option"?Type::Option:(n=="Future"?Type::Future:Type::Stream));
                if(i==s.size()||s[i++]!='<')fail("E_TYPE",n+" requiere un tipo",p);
                t.parts.push_back(one(d+1));
                if(i==s.size()||s[i++]!='>')fail("E_TYPE",n+" sin cierre",p);
                return t;
            }
            if(n=="View") {
                Type t(Type::View);
                if(i==s.size()||s[i++]!='<')fail("E_TYPE","View requiere un tipo",p);
                t.parts.push_back(one(d+1));
                if(i==s.size()||s[i++]!='>')fail("E_TYPE","View sin cierre",p);
                return t;
            }
            if(n=="Range") {
                Type t(Type::Range);
                if(i==s.size()||s[i++]!='<')fail("E_TYPE","Range requiere un tipo",p);
                t.parts.push_back(one(d+1));
                if(i==s.size()||s[i++]!='>')fail("E_TYPE","Range sin cierre",p);
                return t;
            }
            if(n=="Tuple") {
                Type t(Type::Tuple);
                if(i==s.size()||s[i++]!='<')fail("E_TYPE","Tuple requiere '<'",p);
                if(i<s.size()&&s[i]=='>'){++i; return t;}
                while(true){ t.parts.push_back(one(d+1)); if(t.parts.size()>16)fail("E_LIMIT","Tuple demasiado grande",p); if(i<s.size()&&s[i]==','){++i;continue;} break; }
                if(i==s.size()||s[i++]!='>')fail("E_TYPE","Tuple sin cierre",p);
                return t;
            }
            if(n=="Array") {
                Type t(Type::Array);
                if(i==s.size()||s[i++]!='<')fail("E_TYPE","Array requiere '<'",p);
                t.parts.push_back(one(d+1));
                if(i==s.size()||s[i++]!=',')fail("E_TYPE","Array requiere longitud",p);
                if(i==s.size()||!std::isdigit(static_cast<unsigned char>(s[i])))fail("E_TYPE","longitud Array invalida",p);
                uint64_t nlen=0; while(i<s.size()&&std::isdigit(static_cast<unsigned char>(s[i]))){nlen=nlen*10+uint64_t(s[i++]-'0'); if(nlen>65535)fail("E_LIMIT","Array demasiado grande",p);} t.extent=static_cast<uint32_t>(nlen);
                if(i==s.size()||s[i++]!='>')fail("E_TYPE","Array sin cierre",p);
                return t;
            }
            if(n=="Resource"||n=="Borrow"||n=="BorrowMut") {
                if(i==s.size()||s[i++]!='<')fail("E_TYPE",n+" requiere tipo nominal",p);
                size_t rs=i; while(i<s.size()&&(std::isalnum(static_cast<unsigned char>(s[i]))||s[i]=='_'||s[i]=='.'))i++;
                auto rn=s.substr(rs,i-rs); if(!validQualified(rn))fail("E_TYPE",n+" nominal invalido: "+rn,p);
                if(i==s.size()||s[i++]!='>')fail("E_TYPE",n+" sin cierre",p);
                Type::Kind k=n=="Resource"?Type::Resource:(n=="Borrow"?Type::Borrow:Type::BorrowMut);
                Type t(k); t.name=rn; return t;
            }
            if(n=="u8"||n=="u16"||n=="u32"||n=="u64"||n=="i8"||n=="i16"||n=="i32"||n=="i64")return integerTypeByName(n,p);
            if(n=="f32"||n=="f64")return floatTypeByName(n,p);
            if(n=="bool")return Type::Bool;
            if(n=="Char")return Type::Char;
            if(n=="Text")return Type::Text;
            if(n=="Bytes")return Type::Bytes;
            if(!validQualified(n))fail("E_TYPE","tipo no soportado: "+n,p);
            Type t(Type::Record);
            t.name=n;
            return t;
        };
        Type t=one(0);
        if(i!=s.size())fail("E_TYPE","contenido adicional en tipo",p);
        return t;
    }
    class Parser  {
        std::vector<Token> t;
        size_t p=0,nodes=0;
        int depth=0,blocks=0;
        std::set<std::string> genericNames;
        Token& cur() {
            return t[p];
        }
        bool at(const std::string& s) {
            return !cur().str&&cur().s==s;
        }
        bool eat(const std::string& s) {
            if(at(s)) {
                p++;
                return true;
            }
            return false;
        }
        Token expect(const std::string& s) {
            auto x=cur();
            // `Resource<Buffer>=...` must mean generic-close + assignment, not >=.
            if(s==">" && at(">=")) {
                cur().s="=";
                return Token{">",x.loc,false};
            }
            if(!eat(s))fail("E_PARSE","se esperaba '"+s+"', se obtuvo '"+x.s+"'",x.loc);
            return x;
        }
        std::string ident() {
            auto x=cur();
            if(x.str||!validIdentifier(x.s))fail("E_NAME","identificador invalido: "+x.s,x.loc);
            p++;
            return x.s;
        }
        std::string qualified() {
            auto n=ident();
            int parts=1;
            while(eat(".")) { if(++parts>3)fail("E_NAME","nombre cualificado demasiado profundo",cur().loc); n+="."+ident(); }
            return n;
        }
        std::string capabilityName() {
            auto part=[&](){ auto x=cur(); if(x.str||x.s.empty())fail("E_CAPABILITY","nombre de capability invalido",x.loc); for(char raw:x.s){ const auto c=static_cast<unsigned char>(raw); if(!(std::isalnum(c)||c=='_')) fail("E_CAPABILITY","nombre de capability invalido: "+x.s,x.loc); } p++; return x.s; };
            auto n=part(); if(eat(".")) n+="."+part(); return n;
        }
        // What can stand between the `<` and its closing `>` when they enclose type arguments: names, numbers (array extents), `.`, `,` and nested `<` `>`. Anything else (a parenthesis, an operator, `;`, a brace)
        // means that the `<` is a comparison: without this bound a `size < 64` was paired with the `>` of a LATER comparison that happened to be followed by `(`, and the program was refused.
        static bool typeArgumentToken(const Token& x) {
            if(x.str||x.s.empty())return false;
            if(x.s=="<"||x.s==">"||x.s==","||x.s==".")return true;
            const auto c=static_cast<unsigned char>(x.s[0]);
            return std::isalnum(c)||c=='_';
        }
        bool genericCallAheadAt(size_t start) const {
            if(start>=t.size()||t[start].s!="<")return false;
            size_t q=start; int angle=0;
            for(;q<t.size();++q){
                if(!typeArgumentToken(t[q]))return false;
                if(t[q].s=="<")++angle;
                else if(t[q].s==">"){ if(--angle==0)return q+1<t.size()&&t[q+1].s=="("; }
                else if(t[q].s==">=")return false;
                if(angle<0)return false;
            }
            return false;
        }
        bool genericCallAhead() const { return genericCallAheadAt(p); }
        // CP-05: `Name<args> { field: ...` (generic struct initializer): the closing '>' is followed by `{ ident :`.
        bool genericRecordAheadAt(size_t start) const {
            if(start>=t.size()||t[start].s!="<"||t[start].str)return false;
            size_t q=start; int angle=0;
            for(;q<t.size();++q){
                if(!typeArgumentToken(t[q]))return false;
                if(t[q].s=="<")++angle;
                else if(t[q].s==">"){ if(--angle==0)return q+3<t.size()&&t[q+1].s=="{"&&!t[q+2].str&&validIdentifier(t[q+2].s)&&t[q+3].s==":"; }
                if(angle<0)return false;
            }
            return false;
        }
        bool genericRecordAhead() const { return genericRecordAheadAt(p); }
        std::vector<Type> genericArgs() {
            std::vector<Type> out; expect("<");
            if(at(">"))fail("E_GENERIC_ARGS","generic call requires at least one type argument",cur().loc);
            do { out.push_back(type()); if(out.size()>16)fail("E_LIMIT","too many generic type arguments",cur().loc); } while(eat(","));
            expect(">"); return out;
        }
        Type type(int d=0) {
            if(d>OMNI_LIMIT_TYPE_DEPTH)fail("E_LIMIT","tipo demasiado profundo",cur().loc);
            if(!cur().str&&genericNames.count(cur().s)){ Type r(Type::Param); r.name=cur().s; ++p; return r; }
            if(eat("Result")) {
                Type r(Type::Result);
                expect("<");
                r.parts.push_back(type(d+1));
                expect(",");
                r.parts.push_back(type(d+1));
                expect(">");
                return r;
            }
            if(eat("Option")) { expect("<"); Type r(Type::Option); r.parts.push_back(type(d+1)); expect(">"); return r; }
            if(eat("View")) { expect("<"); Type r(Type::View); r.parts.push_back(type(d+1)); expect(">"); return r; }
            if(eat("Range")) { expect("<"); Type r(Type::Range); r.parts.push_back(type(d+1)); expect(">"); return r; }
            if(eat("Tuple")) { expect("<"); Type r(Type::Tuple); if(!(at(">")||at(">="))){ do{ r.parts.push_back(type(d+1)); if(r.parts.size()>16)fail("E_LIMIT","Tuple demasiado grande",cur().loc); }while(eat(",")); } expect(">"); return r; }
            if(eat("Array")) { expect("<"); Type r(Type::Array); r.parts.push_back(type(d+1)); expect(","); auto x=cur(); if(x.str||x.s.empty()||!std::all_of(x.s.begin(),x.s.end(),[](unsigned char c){return std::isdigit(c);}))fail("E_TYPE","longitud Array debe ser constante decimal",x.loc); uint64_t n=std::stoull(x.s); if(n>65535)fail("E_LIMIT","Array demasiado grande",x.loc); r.extent=static_cast<uint32_t>(n); p++; expect(">"); return r; }
            if(eat("Future")) { expect("<"); Type r(Type::Future); r.parts.push_back(type(d+1)); expect(">"); return r; }
            if(eat("Stream")) { expect("<"); Type r(Type::Stream); r.parts.push_back(type(d+1)); expect(">"); return r; }
            if(eat("Resource")) {
                // CP-02: a nominal resource may be an instance of a generic struct: Resource<Vec<u32>>. The arguments stay in `parts` until monomorphization.
                expect("<"); auto n=qualified(); std::vector<Type> args; if(at("<"))args=genericArgs(); expect(">"); Type r(Type::Resource); r.name=n; r.parts=std::move(args); return r;
            }
            if(eat("Borrow")) {
                // CP-02: a nominal resource may be an instance of a generic struct: Resource<Vec<u32>>. The arguments stay in `parts` until monomorphization.
                expect("<"); auto n=qualified(); std::vector<Type> args; if(at("<"))args=genericArgs(); expect(">"); Type r(Type::Borrow); r.name=n; r.parts=std::move(args); return r;
            }
            if(eat("BorrowMut")) {
                // CP-02: a nominal resource may be an instance of a generic struct: Resource<Vec<u32>>. The arguments stay in `parts` until monomorphization.
                expect("<"); auto n=qualified(); std::vector<Type> args; if(at("<"))args=genericArgs(); expect(">"); Type r(Type::BorrowMut); r.name=n; r.parts=std::move(args); return r;
            }
            for(const char* n:{"u8","u16","u32","u64","i8","i16","i32","i64"}) if(eat(n)) return integerTypeByName(n);
            for(const char* n:{"f32","f64"}) if(eat(n)) return floatTypeByName(n);
            if(eat("bool"))return Type::Bool;
            if(eat("Char"))return Type::Char;
            if(eat("Text"))return Type::Text;
            if(eat("Bytes"))return Type::Bytes;
            auto l=cur().loc;
            auto named=parseType(qualified(),l);
            // CP-05: a generic struct use `Name<A, B>` keeps its arguments in `parts` until monomorphization.
            if(named.kind==Type::Record&&at("<"))named.parts=genericArgs();
            return named;
        }
        void end() {
            if(eat(";"))return;
            if(at("}")||at("<eof>")||(p&&cur().loc.line>t[p-1].loc.line))return;
            fail("E_PARSE","se esperaba ';' o fin de linea",cur().loc);
        }
        void node() {
            if((++nodes&1023u)==0u)budgetCheck("el parser");
        }
        int prec() {
            auto s=cur().s;
            if(cur().str)return -1;
            if(s=="||")return 1;
            if(s=="&&")return 2;
            if(s=="=="||s=="!=")return 3;
            if(s=="<"||s==">"||s=="<="||s==">=")return 4;
            if(s=="+"||s=="-"||s=="+%"||s=="-%"||s=="+|"||s=="-|")return 5;
            if(s=="*"||s=="/"||s=="%"||s=="*%"||s=="*|")return 6;
            return -1;
        }
        // Height of the tree this parser builds. Recursion nesting is bounded by `depth` (192), but a left-associative chain (a+b+c+..., a.x.y.z..., f()::g()::h()...)
        // is built by loops and would otherwise yield an arbitrarily deep tree that every later pass walks recursively (stack overflow, found by audit 360).
        void lift(Expr& q) {
            uint32_t h=0;
            for(const auto& a:q.args)if(a.height>h)h=a.height;
            q.height=h+1u;
            if(q.height>static_cast<uint32_t>(OMNI_LIMIT_EXPR_HEIGHT))fail("E_LIMIT","expresion demasiado profunda",q.loc);   // the checker's structural bound (visit: depth > 64), enforced before any pass recurses
        }
        Expr expr(int min=1) {
            if(++depth>OMNI_LIMIT_PAREN_DEPTH)fail("E_LIMIT","expresion demasiado profunda",cur().loc);
            node();
            Expr e;
            auto x=cur();
            e.loc=x.loc;
            if(eat("!")||eat("-")) {
                e.kind=Expr::Unary;
                e.text=t[p-1].s;
                e.args.push_back(expr(7));
            }
            else if(eat("(")) {
                e=expr();
                expect(")");
            }
            else if(x.str) {
                e.kind=Expr::Text;
                e.text=x.s;
                p++;
            }
            else if(at("true")||at("false")) {
                e.kind=Expr::Boolean;
                e.value=at("true");
                p++;
            }
            else if(at("Some")||at("None")) {
                bool some=eat("Some");
                if(!some)expect("None");
                e.kind=some?Expr::Some:Expr::None;
                e.annotation=Type::Option;
                expect("<");
                e.annotation.parts.push_back(type());
                expect(">");
                expect("(");
                if(some)e.args.push_back(expr());
                expect(")");
            }
            else if(at("Ok")||at("Err")) {
                e.kind=eat("Ok")?Expr::Ok:Expr::Err;
                if(e.kind==Expr::Err)expect("Err");
                e.annotation=Type::Result;
                expect("<");
                e.annotation.parts.push_back(type());
                expect(",");
                e.annotation.parts.push_back(type());
                expect(">");
                expect("(");
                e.args.push_back(expr());
                expect(")");
            }
            else if(eat("join")) {
                e.kind=Expr::Join;
                expect("(");
                e.text=ident();
                expect(")");
            }
            else if(eat("cancel")) {
                e.kind=Expr::Cancel;
                expect("(");
                e.text=ident();
                expect(")");
            }
            else if(eat("deadline")) {
                e.kind=Expr::Deadline;
                expect("(");
                e.text=ident();
                expect(",");
                e.args.push_back(expr());
                expect(")");
            }
            else if(eat("channel")) {
                e.kind=Expr::Channel;
                expect("<");
                e.annotation=Type(Type::Stream);
                e.annotation.parts.push_back(type());
                expect(">");
                expect("(");
                e.args.push_back(expr());
                expect(")");
            }
            else if(eat("send")) {
                e.kind=Expr::Send;
                expect("(");
                e.text=ident();
                expect(",");
                e.args.push_back(expr());
                expect(")");
            }
            else if(eat("receive")) {
                e.kind=Expr::Receive;
                expect("(");
                e.text=ident();
                expect(")");
            }
            else if(eat("close")) {
                e.kind=Expr::Close;
                expect("(");
                e.text=ident();
                expect(")");
            }
            else if(eat("closure")) {
                e.kind=Expr::ClosureCall;
                e.closureBody=std::make_shared<std::vector<Stmt>>();
                expect("(");
                if(!at(")")) {
                    do {
                        Param a; a.loc=cur().loc; a.name=ident(); a.type=type();
                        e.closureParams.push_back(std::move(a));
                        
                    } while(eat(","));
                }
                expect(")");
                e.annotation=type();
                *e.closureBody=block();
                expect("(");
                if(!at(")")) {
                    do {
                        e.args.push_back(expr());
                        
                    } while(eat(","));
                }
                expect(")");
            }
            else if(!x.str&&(x.s=="u8"||x.s=="u16"||x.s=="u32"||x.s=="u64"||x.s=="i8"||x.s=="i16"||x.s=="i32"||x.s=="i64"||x.s=="f32"||x.s=="f64")&&p+1<t.size()&&t[p+1].s=="(") {
                e.kind=Expr::Call;
                e.text=x.s;
                p++;
                expect("(");
                e.args.push_back(expr());
                expect(")");
            }
            else if(!x.str&&!x.s.empty()&&std::isdigit(static_cast<unsigned char>(x.s[0]))) {
                std::string suffix;
                if(x.s.size()>=3&&(x.s.ends_with("f32")||x.s.ends_with("f64")))suffix=x.s.substr(x.s.size()-3);
                const auto numeric=suffix.empty()?x.s:x.s.substr(0,x.s.size()-suffix.size());
                const bool floatShape=numeric.find('.')!=std::string::npos||numeric.find('e')!=std::string::npos||numeric.find('E')!=std::string::npos||!suffix.empty();
                p++;
                e.kind=Expr::Number;
                if(floatShape) {
                    if(suffix.empty())fail("E_NUMBER","literal flotante requiere sufijo explicito f32/f64",x.loc);
                    auto lit=floatTypeByName(suffix,x.loc);
                    e.value=parseFloatLiteralBits(numeric,lit,x.loc);
                    e.annotation=lit;
                } else {
                    size_t cut=0; while(cut<x.s.size()&&std::isdigit(static_cast<unsigned char>(x.s[cut])))cut++;
                    auto digits=x.s.substr(0,cut),intSuffix=x.s.substr(cut);
                    uint64_t v=0;
                    for(char digit:digits) {
                        const auto d=uint64_t(digit-'0');
                        if(v>(UINT64_MAX-d)/10)fail("E_OVERFLOW_LITERAL","literal entero excede u64",x.loc);
                        v=v*10+d;
                    }
                    Type lit(Type::U32);
                    if(!intSuffix.empty()) {
                        static const std::set<std::string> validSuffixes={"u8","u16","u32","u64","i8","i16","i32","i64"};
                        if(!validSuffixes.count(intSuffix))fail("E_NUMBER","sufijo de literal entero no soportado: "+intSuffix,x.loc);
                        lit=integerTypeByName(intSuffix,x.loc);
                    }
                    e.value=v;
                    e.annotation=lit;
                }
            }
            else  {
                e.text=ident();
                e.kind=Expr::Ref;
                // Qualified functions/constructors can have module.Type.Variant; fields remain projections.
                if(at(".")&&p+2<t.size()&&!t[p+1].str&&validIdentifier(t[p+1].s)) {
                    bool call1=t[p+2].s=="("||genericCallAheadAt(p+2)||genericRecordAheadAt(p+2)||(t[p+2].s=="{"&&p+4<t.size()&&t[p+4].s==":");
                    bool call2=p+4<t.size()&&t[p+2].s=="."&&!t[p+3].str&&validIdentifier(t[p+3].s)&&(t[p+4].s=="("||genericCallAheadAt(p+4));
                    if(call1||call2) { expect("."); e.text+="."+ident(); if(call2){ expect("."); e.text+="."+ident(); } }
                }
                if(genericCallAhead()||genericRecordAhead()) e.typeArgs=genericArgs();
                if(eat("(")) {
                    e.kind=Expr::Call;
                    if(!at(")")) {
                        do {
                            e.args.push_back(expr());
                            
                        }
                        while(eat(","));
                    }
                    expect(")");
                }
                else if(at("{")&&p+2<t.size()&&!t[p+1].str&&validIdentifier(t[p+1].s)&&t[p+2].s==":") {
                    e.kind=Expr::RecordInit;
                    e.annotation=Type::Record;
                    e.annotation.name=e.text;
                    expect("{");
                    do {
                        e.names.push_back(ident());
                        expect(":");
                        e.args.push_back(expr());
                        
                    }
                    while(eat(",")&&!at("}"));
                    expect("}");
                }
            }
            lift(e);
            while(true) {
                if(eat("::")) {
                    Expr q; q.kind=Expr::Call; q.loc=cur().loc; q.text=ident(); q.methodCall=true;
                    if(genericCallAhead())q.typeArgs=genericArgs();
                    expect("("); q.args.push_back(std::move(e));
                    if(!at(")")){ do { q.args.push_back(expr());  } while(eat(",")); }
                    expect(")"); e=std::move(q); node(); lift(e); continue;
                }
                if(at("?")) {
                    // CP-05c: postfix error/absence propagation; the operand keeps its own evaluation, see lowerTry in check.cpp.
                    Expr q; q.kind=Expr::Try; q.loc=cur().loc; ++p;
                    q.args.push_back(std::move(e)); e=std::move(q); node(); lift(e); continue;
                }
                if(eat("[")) {
                    Expr q; q.kind=Expr::Call; q.loc=cur().loc; q.text="index";
                    q.args.push_back(std::move(e));
                    q.args.push_back(expr());
                    expect("]");
                    e=std::move(q); node(); lift(e); continue;
                }
                if(eat(".")) {
                    Expr q;
                    q.kind=Expr::Field;
                    q.loc=cur().loc;
                    q.text=ident();
                    q.args.push_back(std::move(e));
                    e=std::move(q);
                    node(); lift(e); continue;
                }
                break;
            }
            while(prec()>=min) {
                auto op=cur();
                int pr=prec();
                p++;
                Expr q;
                q.kind=Expr::Binary;
                q.text=op.s;
                q.loc=op.loc;
                q.args.push_back(std::move(e));
                q.args.push_back(expr(pr+1));
                e=std::move(q);
                node(); lift(e);
            }
            if(min==1&&eat("..")) {
                const bool inclusive=eat("=");
                Expr q;
                q.kind=Expr::Call;
                q.text=inclusive?"range.inclusive":"range.exclusive";
                q.loc=x.loc;
                q.args.push_back(std::move(e));
                q.args.push_back(expr(1));
                e=std::move(q);
                node(); lift(e);
            }
            depth--;
            return e;
        }
        std::vector<Stmt> block() {
            if(++blocks>OMNI_LIMIT_BLOCK_DEPTH)fail("E_LIMIT","bloques demasiado profundos",cur().loc);
            expect("{");
            std::vector<Stmt>b;
            while(!at("}")) {
                if(at("<eof>"))fail("E_PARSE","bloque sin cierre",cur().loc);
                b.push_back(stmt());
            }
            expect("}");
            blocks--;
            return b;
        }
        Stmt stmt() {
            node();
            Stmt s;
            s.loc=cur().loc;
            if(at("let")||at("var")) {
                const bool isLet=eat("let");
                if(!isLet)expect("var");
                if(isLet&&eat("(")) {
                    s.kind=Stmt::Destructure;
                    if(at(")"))fail("E_PATTERN","destructuring requiere al menos un elemento",s.loc);
                    do {
                        auto n=ident();
                        if(n!="_"&&std::find(s.names.begin(),s.names.end(),n)!=s.names.end())fail("E_PATTERN","binding duplicado en destructuring: "+n,s.loc);
                        s.names.push_back(n);
                        if(s.names.size()>16)fail("E_LIMIT","destructuring Tuple excede 16 elementos",s.loc);
                    } while(eat(","));
                    expect(")");
                    expect("=");
                    s.expr=expr();
                    end();
                } else {
                    s.kind=isLet?Stmt::Let:Stmt::Var;
                    s.name=ident();
                    if(!at("="))s.declared=type();
                    expect("=");
                    s.expr=expr();
                    end();
                }
            }
            else if(eat("return")) {
                s.kind=Stmt::Return;
                s.expr=expr();
                end();
            }
            else if(eat("task_scope")) {
                s.kind=Stmt::TaskScope;
                s.body=block();
            }
            else if(eat("spawn")) {
                s.kind=Stmt::Spawn;
                s.name=ident();
                expect("=");
                s.expr=expr();
                end();
            }
            else if(eat("break")) {
                s.kind=Stmt::Break;
                end();
            }
            else if(eat("continue")) {
                s.kind=Stmt::Continue;
                end();
            }
            else if(eat("if")) {
                s.kind=Stmt::If;
                s.expr=expr();
                s.body=block();
                if(eat("else"))s.other=block();
            }
            else if(eat("for")) {
                if(!cur().str&&validIdentifier(cur().s)&&p+1<t.size()&&t[p+1].s=="in") {
                    s.kind=Stmt::ForEach;
                    s.name=ident();
                    expect("in");
                    s.expr=expr();
                    s.body=block();
                } else {
                    s.kind=Stmt::Loop;
                    s.expr=expr();
                    s.body=block();
                }
            }
            else if(eat("match")) {
                s.expr=expr();
                expect("{");
                if(at("Ok")||at("Err")) {
                    s.kind=Stmt::Match;
                    bool ok=false,err=false;
                    for(int k=0; k<2; k++) {
                        bool a=eat("Ok");
                        if(!a)expect("Err");
                        if((a&&ok)||(!a&&err))fail("E_MATCH","brazo duplicado",cur().loc);
                        expect("("); auto n=ident(); expect(")"); auto b=block();
                        if(a){ok=true;s.name=n;s.body=std::move(b);} else {err=true;s.otherName=n;s.other=std::move(b);}
                    }
                } else if(at("Some")||at("None")) {
                    s.kind=Stmt::MatchOption;
                    bool some=false,none=false;
                    for(int k=0;k<2;k++) {
                        if(eat("Some")) {
                            if(some)fail("E_MATCH","brazo Some duplicado",cur().loc);
                            expect("("); auto n=ident(); expect(")"); auto b=block();
                            some=true;s.name=n;s.body=std::move(b);
                        } else {
                            expect("None"); if(none)fail("E_MATCH","brazo None duplicado",cur().loc);
                            auto b=block(); none=true;s.other=std::move(b);
                        }
                    }
                    if(!some||!none)fail("E_MATCH","Option requiere Some y None",s.loc);
                } else {
                    s.kind=Stmt::MatchEnum;
                    while(!at("}")) {
                        auto variant=ident(); std::string bind;
                        if(eat("(")){ bind=ident(); expect(")"); }
                        s.armVariants.push_back(variant); s.armNames.push_back(bind); s.arms.push_back(block());
                        s.armBindings.push_back(-1); s.armVariantIndices.push_back(-1); s.armPayloadFields.push_back(-1);
                        
                    }
                    if(s.arms.empty())fail("E_MATCH_NON_EXHAUSTIVE","match enum requiere brazos",s.loc);
                }
                expect("}");
            }
            else if(eat("print")) {
                expect("(");
                if(cur().str) {
                    s.kind=Stmt::PrintText;
                    s.text=cur().s;
                    p++;
                }
                else {
                    s.kind=Stmt::Print;
                    s.expr=expr();
                }
                expect(")");
                end();
            }
            else {
                s.kind=Stmt::Assign;
                s.name=ident();
                expect("=");
                s.expr=expr();
                end();
            }
            return s;
        }
        Function functionDecl(const std::string& mod,bool pub,bool bodyless) {
            Function f;
            f.module=mod;
            f.pub=pub;
            f.loc=expect("func").loc;
            f.name=ident();
            auto previousGenericNames=genericNames;
            if(eat("<")) {
                if(at(">"))fail("E_GENERIC_DECL","generic parameter list cannot be empty",cur().loc);
                do {
                    GenericParam gp; gp.loc=cur().loc; gp.name=ident();
                    if(genericNames.count(gp.name))fail("E_GENERIC_DECL","duplicate generic parameter: "+gp.name,gp.loc);
                    if(eat(":")){ gp.constraint=ident(); if(eat(".")) gp.constraint+="."+ident(); }   // `Codec` or `alias.Allocator` (a trait of an imported module)
                    f.generics.push_back(gp); genericNames.insert(gp.name);
                    if(f.generics.size()>16)fail("E_LIMIT","too many generic parameters",f.loc);
                } while(eat(","));
                expect(">");
            }
            expect("(");
            if(!at(")")) {
                do {
                    Param a;
                    a.loc=cur().loc;
                    // Receiver modes are contextual: preserving ordinary identifiers named
                    // read/mutate/consume is required for historical source compatibility.
                    if((at("read")||at("mutate")||at("consume"))&&p+2<t.size()&&t[p+2].s!=","&&t[p+2].s!=")") {
                        if(!f.params.empty())fail("E_METHOD_RECEIVER","receiver debe ser el primer parametro",a.loc);
                        a.receiverMode=cur().s;
                        p++;
                    }
                    a.name=ident();
                    a.type=type();
                    f.params.push_back(a);
                    
                }
                while(eat(","));
            }
            expect(")");
            f.result=type();
            if(eat("!")) {
                auto addcap=[&](const std::string& raw,Loc l){
                    if(raw=="pure") return;
                    if(raw=="io") { auto xs=legacyIoCapabilities(); f.capabilities.insert(xs.begin(),xs.end()); return; }
                    auto cap=canonicalCapability(raw);
                    if(!isKnownCapability(cap)) fail("E_CAPABILITY","capability no soportada: "+raw,l);
                    f.capabilities.insert(cap);
                };
                if(eat("{")) {
                    if(at("}")) fail("E_CAPABILITY","lista de capabilities vacia",cur().loc);
                    do { auto l=cur().loc; addcap(capabilityName(),l); } while(eat(","));
                    expect("}");
                } else {
                    auto l=cur().loc;
                    if(at("pure")||at("io")) { auto q=cur().s; p++; addcap(q,l); }
                    else addcap(capabilityName(),l);
                }
            }
            if(!bodyless)f.body=block();
            genericNames=std::move(previousGenericNames);
            return f;
        }
        void unit(Program& r,const std::string& mod,bool braced) {
            ModuleInfo mi;
            mi.name=mod;
            while(!at("<eof>")&&!(braced&&at("}"))) {
                if(eat("import")) {
                    Import i;
                    i.loc=cur().loc;
                    i.alias=ident();
                    if(braced) {
                        expect("=");
                        i.target=ident();
                    }
                    else {
                        if(!cur().str)fail("E_IMPORT","ruta relativa entre comillas requerida",cur().loc);
                        i.path=cur().s;
                        p++;
                    }
                    end();
                    mi.imports.push_back(i);
                    continue;
                }
                bool pub=eat("pub");
                bool packedStruct=false,opaqueStruct=false,externStruct=false;   // CP-07: `packed struct` / `opaque struct` (contextual: only before `struct`, in either order)
                for(;;) {
                    if(at("packed")&&p+1<t.size()&&!t[p+1].str&&(t[p+1].s=="struct"||t[p+1].s=="opaque")&&!packedStruct) { p++; packedStruct=true; continue; }
                    if(at("opaque")&&p+1<t.size()&&!t[p+1].str&&(t[p+1].s=="struct"||t[p+1].s=="packed")&&!opaqueStruct) { p++; opaqueStruct=true; continue; }
                    if(at("extern")&&p+1<t.size()&&!t[p+1].str&&t[p+1].s=="struct"&&!externStruct&&!packedStruct&&!opaqueStruct) { p++; externStruct=true; continue; }   // `extern struct` is not combined with packed/opaque
                    break;
                }
                if(at("const")&&p+1<t.size()&&!t[p+1].str&&!t[p+1].s.empty()&&(std::isalpha(static_cast<unsigned char>(t[p+1].s[0]))||t[p+1].s[0]=='_')) {
                    // CP-07 (spec/STATIC_DATA_CANDIDATE.md): const NAME Type = literal | array(literal, ...)  (contextual keyword: it only means something at the start of an item).
                    // It is a pure function without parameters whose body is the constant; the uses of NAME are calls, so no representation learns a new form and the optimizer places the data.
                    Function cf; cf.module=mod; cf.pub=pub; cf.loc=cur().loc; p++; cf.name=ident(); cf.result=type(); expect("=");
                    Expr init=expr();
                    std::function<bool(const Expr&)> constant=[&](const Expr& e)->bool{
                        if(e.kind==Expr::Number||e.kind==Expr::Boolean)return true;
                        if(e.kind==Expr::Unary&&e.text=="-"&&e.args.size()==1&&e.args[0].kind==Expr::Number)return true;
                        if(e.kind==Expr::Call&&e.text=="array"&&!e.args.empty()){ for(const auto& a:e.args)if(!constant(a))return false; return true; }
                        return false;
                    };
                    // MN-10 (limited compile-time evaluation): a SCALAR constant may be any pure expression (constants, arithmetic, pure functions, layout queries, target facts); the checker evaluates it
                    // while validating and refuses the program when it cannot be decided. Tables stay literal: computed tables are not part of 1.3.
                    if(!constant(init)&&!isInteger(cf.result)&&cf.result.kind!=Type::Bool)fail("E_CONST","una constante es un literal o array(literales): "+cf.name,cf.loc);
                    end();
                    Stmt cs; cs.kind=Stmt::Return; cs.loc=cf.loc; cs.expr=std::move(init); cf.body.push_back(std::move(cs)); cf.isConst=true;
                    r.functions.push_back(std::move(cf));
                    continue;
                }
                if(at("static_assert")&&p+1<t.size()&&!t[p+1].str&&t[p+1].s=="(") {
                    // CP-07 (spec/STATIC_ASSERT_CANDIDATE.md): static_assert(condition, "message") at module level. The condition is an ordinary pure expression (no capability, so no I/O and no authority:
                    // the checker already refuses an effect in a function that declares none); the checker evaluates it, with the evaluator's fuel and depth limits, and refuses the program when it is false.
                    if(pub)fail("E_STATIC_ASSERT","static_assert no es exportable",cur().loc);
                    Function sf; sf.module=mod; sf.pub=false; sf.loc=cur().loc; p++; expect("(");
                    Expr cond=expr(); expect(",");
                    if(!cur().str)fail("E_STATIC_ASSERT","static_assert requiere un mensaje entre comillas",cur().loc);
                    sf.assertMessage=cur().s; p++; expect(")"); end();
                    sf.name="static_assert_"+std::to_string(sf.loc.line)+"_"+std::to_string(sf.loc.column); sf.result=Type(Type::Bool); sf.isStaticAssert=true;
                    Stmt ss; ss.kind=Stmt::Return; ss.loc=sf.loc; ss.expr=std::move(cond); sf.body.push_back(std::move(ss));
                    r.staticAsserts.push_back(std::move(sf));
                    continue;
                }
                if(at("thread_local")) {
                    // CP-11: thread_local NAME Type = literal   (contextual keyword: it only means something at the start of an item)
                    if(pub)fail("E_THREAD_LOCAL","thread_local no es exportable: expongalo mediante funciones del módulo",cur().loc);
                    ThreadLocalDef d; d.loc=cur().loc; p++; d.name=ident(); d.module=mod; d.pub=false; d.type=type();
                    if(!isInteger(d.type))fail("E_THREAD_LOCAL","thread_local admite solo tipos enteros (u8..u64, i8..i64)",d.loc);
                    expect("=");
                    Expr init=expr();
                    const Expr* lit=&init;
                    if(init.kind==Expr::Unary&&init.text=="-"&&init.args.size()==1&&init.args[0].kind==Expr::Number) { d.negative=true; lit=&init.args[0]; }
                    if(lit->kind!=Expr::Number||isFloat(lit->annotation))fail("E_THREAD_LOCAL","el valor inicial de thread_local debe ser un literal entero constante",d.loc);
                    if(!(lit->annotation==d.type))fail("E_TYPE","el literal inicial de thread_local debe tener el tipo declarado (use el sufijo "+typeName(d.type)+")",d.loc);
                    d.magnitude=lit->value;
                    end();
                    r.threadLocals.push_back(std::move(d));
                    continue;
                }
                if(eat("trait")) {
                    TraitDef d; d.loc=cur().loc; d.name=ident(); d.module=mod; d.pub=pub;
                    // CP-05b: `trait Name { func m(x Self, ...) Result !caps }` declares static-dispatch method signatures.
                    auto previousGenericNames=genericNames; genericNames.insert("Self");
                    expect("{");
                    while(!at("}")) {
                        d.methods.push_back(functionDecl(mod,pub,true)); end();
                        if(d.methods.size()>32)fail("E_LIMIT","demasiados metodos de trait",d.loc);
                    }
                    expect("}"); genericNames=std::move(previousGenericNames);
                    r.traits.push_back(std::move(d));
                    continue;
                }
                if(eat("impl")) {
                    TraitImpl d; d.loc=cur().loc; d.trait=ident(); if(eat(".")) d.trait+="."+ident(); d.module=mod;
                    expect("for"); d.forType=type(); expect("{");
                    while(!at("}")) {
                        d.methods.push_back(functionDecl(mod,pub,false));
                        if(d.methods.size()>32)fail("E_LIMIT","demasiados metodos de impl",d.loc);
                    }
                    expect("}");
                    r.traitImpls.push_back(std::move(d));
                    continue;
                }
                if(eat("enum")) {
                    EnumDef d; d.loc=cur().loc; d.name=ident(); d.module=mod; d.pub=pub;
                    // CP-05: enum Name<T, U: Constraint> { A(T), B(U), C } is a template; only concrete specializations survive validation.
                    auto previousGenericNames=genericNames;
                    if(eat("<")) {
                        if(at(">"))fail("E_GENERIC_DECL","generic parameter list cannot be empty",cur().loc);
                        do {
                            GenericParam gp; gp.loc=cur().loc; gp.name=ident();
                            if(genericNames.count(gp.name))fail("E_GENERIC_DECL","duplicate generic parameter: "+gp.name,gp.loc);
                            if(eat(":")){ gp.constraint=ident(); if(eat(".")) gp.constraint+="."+ident(); }   // `Codec` or `alias.Allocator` (a trait of an imported module)
                            d.generics.push_back(gp); genericNames.insert(gp.name);
                            if(d.generics.size()>16)fail("E_LIMIT","too many generic parameters",d.loc);
                        } while(eat(","));
                        expect(">");
                    }
                    expect("{");
                    while(!at("}")) {
                        VariantDef v; v.loc=cur().loc; v.name=ident();
                        if(eat("(")){ v.hasPayload=true; v.payload=type(); expect(")"); }
                        d.variants.push_back(std::move(v));
                        if(d.variants.size()>OMNI_ENUM_MAX_VARIANTS)fail("E_LIMIT","demasiadas variantes enum: el tag de un enum es de un byte (maximo 256)",d.loc);
                        if(!eat(",")) end();
                    }
                    expect("}");
                    genericNames=std::move(previousGenericNames);
                    if(d.generics.empty()) { r.enums.push_back(std::move(d)); }
                    else { r.genericEnumTemplates.push_back(std::move(d)); }
                    continue;
                }
                if(eat("struct")) {
                    RecordDef d;
                    d.loc=cur().loc;
                    d.name=ident();
                    d.module=mod;
                    d.pub=pub;
                    d.packed=packedStruct;
                    d.opaque=opaqueStruct;
                    d.externC=externStruct;
                    // CP-05: struct Name<T, U: Constraint> { ... } is a template; only concrete specializations survive validation.
                    auto previousGenericNames=genericNames;
                    if(eat("<")) {
                        if(at(">"))fail("E_GENERIC_DECL","generic parameter list cannot be empty",cur().loc);
                        do {
                            GenericParam gp; gp.loc=cur().loc; gp.name=ident();
                            if(genericNames.count(gp.name))fail("E_GENERIC_DECL","duplicate generic parameter: "+gp.name,gp.loc);
                            if(eat(":")){ gp.constraint=ident(); if(eat(".")) gp.constraint+="."+ident(); }   // `Codec` or `alias.Allocator` (a trait of an imported module)
                            d.generics.push_back(gp); genericNames.insert(gp.name);
                            if(d.generics.size()>16)fail("E_LIMIT","too many generic parameters",d.loc);
                        } while(eat(","));
                        expect(">");
                    }
                    if(d.packed&&!d.generics.empty())fail("E_LAYOUT","packed struct no puede ser generico",d.loc);
                    if(d.externC&&!d.generics.empty())fail("E_LAYOUT","extern struct no puede ser generico",d.loc);
                    expect("{");
                    while(!at("}")) {
                        FieldDef f;
                        f.loc=cur().loc;
                        f.name=ident();
                        f.type=type();
                        d.fields.push_back(f);
                        if(!eat(","))end();
                    }
                    expect("}");
                    genericNames=std::move(previousGenericNames);
                    if(d.generics.empty()) {
                        r.records.push_back(std::move(d));
                    } else {
                        r.genericRecordTemplates.push_back(std::move(d));
                    }
                    continue;
                }
                // MN-07/13/16: linkage modifiers between `pub` and `func`, in any order, each at most once: export "sym" | extern "sym" | section ".name" | noinline
                std::string exportName,externName,sectionName; bool noInline=false;
                for(;;) {
                    const bool symbolAhead=p+1<t.size()&&t[p+1].str;
                    if(at("export")&&symbolAhead) { if(!exportName.empty())fail("E_LINKAGE","export repetido",cur().loc); p++; exportName=cur().s; if(exportName.empty())fail("E_LINKAGE","el nombre de export no puede ser vacio",cur().loc); p++; continue; }
                    if(at("extern")&&symbolAhead) { if(!externName.empty())fail("E_LINKAGE","extern repetido",cur().loc); p++; externName=cur().s; if(externName.empty())fail("E_LINKAGE","el nombre de extern no puede ser vacio",cur().loc); p++; continue; }
                    if(at("section")&&symbolAhead) { if(!sectionName.empty())fail("E_LINKAGE","section repetido",cur().loc); p++; sectionName=cur().s; if(sectionName.empty())fail("E_LINKAGE","el nombre de section no puede ser vacio",cur().loc); p++; continue; }
                    if(at("noinline")&&p+1<t.size()&&!t[p+1].str&&(t[p+1].s=="func"||t[p+1].s=="export"||t[p+1].s=="extern"||t[p+1].s=="section")) { if(noInline)fail("E_LINKAGE","noinline repetido",cur().loc); p++; noInline=true; continue; }
                    break;
                }
                Function f=functionDecl(mod,pub,!externName.empty());
                if(!externName.empty()) end();
                f.exportName=exportName; f.externName=externName; f.section=sectionName; f.noInline=noInline; f.isExtern=!externName.empty();
                if(f.linkage()&&!f.generics.empty())fail("E_LINKAGE","una funcion con atributos de enlace no puede ser generica: "+f.name,f.loc);
                if(f.isExtern&&(!f.exportName.empty()||!f.section.empty()||f.noInline))fail("E_LINKAGE","una funcion extern no se exporta, no tiene seccion y no se marca noinline: "+f.name,f.loc);
                if(f.generics.empty()) {
                    r.functions.push_back(std::move(f));
                } else {
                    r.genericTemplates.push_back(std::move(f));
                }
            }
            r.modules.push_back(std::move(mi));
        }
        public: explicit Parser(std::vector<Token>x):t(std::move(x)) {
        }
        Program run() {
            Program r;
            if(eat("bundle")) {
                r.bundled=true;
                r.module=ident();
                expect("{");
                while(!at("}")) {
                    expect("module");
                    auto n=ident();
                    expect("{");
                    unit(r,n,true);
                    expect("}");
                }
                expect("}");
                expect("<eof>");
            }
            else {
                expect("module");
                r.module=ident();
                eat(";");
                unit(r,r.module,false);
            }
            return r;
        }
    };
    Program parseParticle(const std::string&s) {
        validateUTF8(s);
        return Parser(Lexer(s).run()).run();
    }
    // The authoring text of a whole program, as a Wave22/OMC22 capsule carries it: several modules in one text. It is bounded by the memory budget like any other input, so it is read as a source is.
    Program parseParticleProgram(const std::string&s) {
        return parseParticle(s);
    }
    static void pb(std::ostringstream&,const std::vector<Stmt>&,int);
    static std::string pe(const Expr&e) {
        switch(e.kind) {
            case Expr::Number:{ auto t=e.type.kind!=Type::Unknown?e.type:e.annotation; if(isFloat(t))return formatFloatLiteral(t,e.value); auto n=std::to_string(e.value); return t.kind==Type::U32?n:n+typeName(t); }
            case Expr::Boolean:return e.value?"true":"false";
            case Expr::Text:return quote(e.text);
            case Expr::Ref:return e.text;
            case Expr::Join:return "join("+e.text+")";
            case Expr::Cancel:return "cancel("+e.text+")";
            case Expr::Deadline:return "deadline("+e.text+", "+pe(e.args.at(0))+")";
            case Expr::Channel:return "channel<"+typeName(e.annotation.parts.at(0))+">("+pe(e.args.at(0))+")";
            case Expr::Send:return "send("+e.text+", "+pe(e.args.at(0))+")";
            case Expr::Receive:return "receive("+e.text+")";
            case Expr::Close:return "close("+e.text+")";
            case Expr::Try:return "("+pe(e.args.at(0))+")?";
            case Expr::Call: {
                if(e.text=="index"&&e.args.size()==2)return "("+pe(e.args[0])+")["+pe(e.args[1])+"]";
                if((e.text=="range.exclusive"||e.text=="range.inclusive")&&e.args.size()==2)
                    return "("+pe(e.args[0])+").."+(e.text=="range.inclusive"?"=":"")+"("+pe(e.args[1])+")";
                std::string r;
                size_t begin=0;
                if(e.methodCall&&!e.args.empty()){ r="("+pe(e.args[0])+")::"+e.text; begin=1; }
                else r=e.text;
                if(!e.typeArgs.empty()){ r+="<"; for(size_t i=0;i<e.typeArgs.size();++i){ if(i)r+=", "; r+=typeName(e.typeArgs[i]); } r+=">"; }
                r+="(";
                for(size_t i=begin; i<e.args.size(); i++) {
                    if(i>begin)r+=", ";
                    r+=pe(e.args[i]);
                }
                return r+")";
            }
            case Expr::Unary:return "("+e.text+pe(e.args[0])+")";
            case Expr::Binary:return "("+pe(e.args[0])+" "+e.text+" "+pe(e.args[1])+")";
            case Expr::RecordInit: {
                std::string r=e.text;
                if(!e.typeArgs.empty()){ r+="<"; for(size_t i=0;i<e.typeArgs.size();++i){if(i)r+=",";r+=typeName(e.typeArgs[i]);}r+=">"; }
                r+=" { ";
                for(size_t i=0; i<e.args.size(); i++) {
                    if(i)r+=", ";
                    r+=e.names[i]+": "+pe(e.args[i]);
                }
                return r+" }";
            }
            case Expr::Variant: { std::string r=e.text+"("; if(!e.args.empty())r+=pe(e.args[0]); return r+")"; }
            case Expr::Field:return "("+pe(e.args[0])+")."+e.text;
            case Expr::Ok:case Expr::Err:return std::string(e.kind==Expr::Ok?"Ok":"Err")+"<"+typeName(e.annotation.parts[0])+", "+typeName(e.annotation.parts[1])+">("+pe(e.args[0])+")";
            case Expr::Some:return "Some<"+typeName(e.annotation.parts[0])+">("+pe(e.args[0])+")";
            case Expr::None:return "None<"+typeName(e.annotation.parts[0])+">()";
            case Expr::ClosureCall: {
                if(!e.closureBody)fail("E_PARTICLE","closure sin cuerpo",e.loc);
                std::ostringstream b;
                b<<"closure(";
                for(size_t i=0;i<e.closureParams.size();++i){if(i)b<<", ";b<<e.closureParams[i].name<<" "<<typeName(e.closureParams[i].type);}
                b<<") "<<typeName(e.annotation)<<" {\n";
                pb(b,*e.closureBody,1); b<<"}(";
                for(size_t i=0;i<e.args.size();++i){if(i)b<<", ";b<<pe(e.args[i]);}
                return b.str()+")";
            }
        }
        fail("E_INTERNAL","expresion desconocida");
    }
    static void pb(std::ostringstream&o,const std::vector<Stmt>&b,int n) {
        std::string i(static_cast<size_t>(n)*4u,' ');
        for(auto&s:b) {
            o<<i;
            switch(s.kind) {
                case Stmt::Let:case Stmt::Var:o<<(s.kind==Stmt::Let?"let ":"var ")<<s.name;
                if(s.declared!=Type::Unknown)o<<" "<<typeName(s.declared);
                o<<" = "<<pe(s.expr)<<";\n";
                break;
                case Stmt::Assign:o<<s.name<<" = "<<pe(s.expr)<<";\n";
                break;
                case Stmt::Return:o<<"return "<<pe(s.expr)<<";\n";
                break;
                case Stmt::TaskScope:o<<"task_scope {\n"; pb(o,s.body,n+1); o<<i<<"}\n"; break;
                case Stmt::Spawn:o<<"spawn "<<s.name<<" = "<<pe(s.expr)<<";\n"; break;
                case Stmt::Print:o<<"print("<<pe(s.expr)<<");\n";
                break;
                case Stmt::PrintText:o<<"print("<<quote(s.text)<<");\n";
                break;
                case Stmt::Destructure: {
                    o<<"let (";
                    for(size_t k=0;k<s.names.size();++k){ if(k)o<<", "; o<<s.names[k]; }
                    o<<") = "<<pe(s.expr)<<";\n";
                    break;
                }
                case Stmt::Break:o<<"break;\n"; break;
                case Stmt::Continue:o<<"continue;\n"; break;
                case Stmt::If:o<<"if "<<pe(s.expr)<<" {\n";
                pb(o,s.body,n+1);
                o<<i<<"}";
                if(!s.other.empty()) {
                    o<<" else {\n";
                    pb(o,s.other,n+1);
                    o<<i<<"}";
                }
                o<<"\n";
                break;
                case Stmt::Loop:o<<"for "<<pe(s.expr)<<" {\n";
                pb(o,s.body,n+1);
                o<<i<<"}\n";
                break;
                case Stmt::ForEach:o<<"for "<<s.name<<" in "<<pe(s.expr)<<" {\n";
                pb(o,s.body,n+1);
                o<<i<<"}\n";
                break;
                case Stmt::Match:o<<"match "<<pe(s.expr)<<" {\n"<<i<<"    Ok("<<s.name<<") {\n";
                pb(o,s.body,n+2);
                o<<i<<"    }\n"<<i<<"    Err("<<s.otherName<<") {\n";
                pb(o,s.other,n+2);
                o<<i<<"    }\n"<<i<<"}\n";
                break;
                case Stmt::MatchOption:o<<"match "<<pe(s.expr)<<" {\n"<<i<<"    Some("<<s.name<<") {\n";
                pb(o,s.body,n+2);
                o<<i<<"    }\n"<<i<<"    None {\n";
                pb(o,s.other,n+2);
                o<<i<<"    }\n"<<i<<"}\n";
                break;
                case Stmt::MatchEnum:o<<"match "<<pe(s.expr)<<" {\n";
                for(size_t a=0;a<s.arms.size();++a){ o<<i<<"    "<<s.armVariants[a]; if(!s.armNames[a].empty())o<<"("<<s.armNames[a]<<")"; o<<" {\n"; pb(o,s.arms[a],n+2); o<<i<<"    }\n"; }
                o<<i<<"}\n"; break;
            }
        }
    }
    std::string particle(const Program&p) {
        std::ostringstream o;
        bool bundle=p.modules.size()>1;
        if(bundle)o<<"bundle "<<p.module<<" {\n";
        for(auto&m:p.modules) {
            int n=bundle?1:0;
            std::string i(static_cast<size_t>(n)*4u,' ');
            o<<i<<"module "<<m.name<<(bundle?" {\n":"\n");
            if(bundle) {
                n++;
                i=std::string(static_cast<size_t>(n)*4u,' ');
            }
            for(auto&im:m.imports)o<<i<<"import "<<im.alias<<" = "<<im.target<<";\n";
            for(auto&d:p.threadLocals)if(d.module==m.name) {
                o<<"\n"<<i<<(d.pub?"pub ":"")<<"thread_local "<<d.name<<" "<<typeName(d.type)<<" = "<<(d.negative?"-":"")<<d.magnitude<<(d.type.kind==Type::U32?"":typeName(d.type))<<"\n";
            }
            for(auto&d:p.enums)if(d.module==m.name) {
                o<<"\n"<<i<<(d.pub?"pub ":"")<<"enum "<<d.name<<" {\n";
                for(auto&v:d.variants){ o<<i<<"    "<<v.name; if(v.hasPayload)o<<"("<<typeName(v.payload)<<")"; o<<",\n"; }
                o<<i<<"}\n";
            }
            for(auto&d:p.records)if(d.module==m.name) {
                o<<"\n"<<i<<(d.pub?"pub ":"")<<(d.packed?"packed ":"")<<(d.opaque?"opaque ":"")<<(d.externC?"extern ":"")<<"struct "<<d.name<<" {\n";
                for(auto&f:d.fields)o<<i<<"    "<<f.name<<" "<<typeName(f.type)<<";\n";
                o<<i<<"}\n";
            }
            for(auto&d:p.genericEnumTemplates)if(d.module==m.name) {
                o<<"\n"<<i<<(d.pub?"pub ":"")<<"enum "<<d.name<<"<";
                for(size_t gi=0;gi<d.generics.size();++gi){ if(gi)o<<","; o<<d.generics[gi].name; if(d.generics[gi].constraint!="Any")o<<":"<<d.generics[gi].constraint; }
                o<<"> {\n";
                for(auto&v:d.variants){ o<<i<<"    "<<v.name; if(v.hasPayload)o<<"("<<typeName(v.payload)<<")"; o<<",\n"; }
                o<<i<<"}\n";
            }
            for(auto&d:p.genericRecordTemplates)if(d.module==m.name) {
                o<<"\n"<<i<<(d.pub?"pub ":"")<<"struct "<<d.name<<"<";
                for(size_t gi=0;gi<d.generics.size();++gi){ if(gi)o<<","; o<<d.generics[gi].name; if(d.generics[gi].constraint!="Any")o<<":"<<d.generics[gi].constraint; }
                o<<"> {\n";
                for(auto&f:d.fields)o<<i<<"    "<<f.name<<" "<<typeName(f.type)<<";\n";
                o<<i<<"}\n";
            }
            auto printCaps=[&](const Function& f){
                o<<" !";
                if(f.capabilities.empty()) o<<"pure";
                else { o<<"{"; bool first=true; for(const auto& cap:f.capabilities){ if(!first)o<<","; first=false; o<<cap; } o<<"}"; }
            };
            auto printSignature=[&](const Function& f){
                o<<i<<"    func "<<f.name<<"(";
                for(size_t j=0;j<f.params.size();++j){ if(j)o<<", "; o<<f.params[j].name<<" "<<typeName(f.params[j].type); }
                o<<") "<<typeName(f.result); printCaps(f); o<<"\n";
            };
            for(auto&d:p.traits)if(d.module==m.name) {
                o<<"\n"<<i<<(d.pub?"pub ":"")<<"trait "<<d.name<<" {\n";
                for(auto&f:d.methods)printSignature(f);
                o<<i<<"}\n";
            }
            auto printFunction=[&](const Function& f) {
                if(f.isStaticAssert&&f.body.size()==1) { o<<"\n"<<i<<"static_assert("<<pe(f.body[0].expr)<<", "<<quote(f.assertMessage)<<")\n"; return; }
                if(f.isConst&&f.body.size()==1) { o<<"\n"<<i<<(f.pub?"pub ":"")<<"const "<<f.name<<" "<<typeName(f.result)<<" = "<<pe(f.body[0].expr)<<";\n"; return; }
                o<<"\n"<<i<<(f.pub?"pub ":"");
                if(!f.exportName.empty())o<<"export "<<quote(f.exportName)<<" ";
                if(f.isExtern)o<<"extern "<<quote(f.externName)<<" ";
                if(!f.section.empty())o<<"section "<<quote(f.section)<<" ";
                if(f.noInline)o<<"noinline ";
                o<<"func "<<f.name;
                if(!f.generics.empty()){ o<<"<"; for(size_t gi=0;gi<f.generics.size();++gi){ if(gi)o<<","; o<<f.generics[gi].name; if(f.generics[gi].constraint!="Any")o<<":"<<f.generics[gi].constraint; } o<<">"; }
                o<<"(";
                for(size_t j=0; j<f.params.size(); j++) {
                    if(j)o<<", ";
                    if(!f.params[j].receiverMode.empty())o<<f.params[j].receiverMode<<" ";
                    o<<f.params[j].name<<" "<<typeName(f.params[j].type);
                }
                o<<") "<<typeName(f.result)<<" !";
                if(f.capabilities.empty()) o<<"pure";
                else { o<<"{"; bool first=true; for(const auto& cap:f.capabilities){ if(!first)o<<","; first=false; o<<cap; } o<<"}"; }
                if(f.isExtern) { o<<"\n"; return; }
                o<<" {\n";
                pb(o,f.body,n+1);
                o<<i<<"}\n";
            };
            for(auto&d:p.traitImpls)if(d.module==m.name) {
                o<<"\n"<<i<<"impl "<<d.trait<<" for "<<typeName(d.forType)<<" {";
                for(auto&f:d.methods)printFunction(f);
                o<<i<<"}\n";
            }
            for(auto&f:p.genericTemplates)if(f.module==m.name)printFunction(f);
            for(auto&f:p.functions)if(f.module==m.name&&!f.generated)printFunction(f);
            for(auto&f:p.staticAsserts)if(f.module==m.name)printFunction(f);
            if(bundle)o<<"    }\n";
        }
        if(bundle)o<<"}\n";
        return o.str();
    }
}
