#include "omni.hpp"
namespace omni {
namespace {
struct Token { bool quoted=false; std::string text; };
const std::map<std::string,char>& codes(){
    static const std::map<std::string,char> m={
        {"omni-wave",'W'},{"entry",'E'},{"module",'M'},{"imports",'I'},{"func",'F'},
        {"visibility",'V'},{"private",'p'},{"public",'P'},{"params",'A'},{"result",'R'},
        {"effects",'X'},{"pure",'0'},{"block",'B'},{"return",'r'},{"let",'l'},{"var",'v'},
        {"set",'s'},{"call",'c'},{"ref",'f'},{"binary",'b'},{"if",'i'},{"while",'w'},
        {"for-each",'e'},{"struct",'S'},{"fields",'D'},{"enum",'N'},{"variants",'Z'},
        {"u8",'1'},{"u16",'2'},{"u32",'3'},{"u64",'4'},{"i8",'5'},{"i16",'6'},{"i32",'7'},{"i64",'8'},
        {"bool",'t'},{"Text",'T'},{"Bytes",'Y'}
    }; return m;
}
const std::map<char,std::string>& reverseCodes(){
    static const std::map<char,std::string> r=[](){std::map<char,std::string>x;for(const auto&kv:codes())x.emplace(kv.second,kv.first);return x;}();return r;
}
std::vector<Token> tokenize(const std::string& s){
    std::vector<Token> out; size_t i=0;
    while(i<s.size()){
        const unsigned char c=static_cast<unsigned char>(s[i]);
        if(std::isspace(c)){++i;continue;}
        if(s[i]=='('||s[i]==')'){out.push_back({false,std::string(1,s[i])});++i;continue;}
        if(s[i]=='"'){
            size_t j=i+1;bool escaped=false,closed=false;
            for(;j<s.size();++j){char z=s[j];if(escaped){escaped=false;continue;}if(z=='\\'){escaped=true;continue;}if(z=='"'){++j;closed=true;break;}}
            if(!closed)fail("E_ONME","cadena Wave truncada durante ONME");
            out.push_back({true,s.substr(i,j-i)});i=j;continue;
        }
        size_t j=i;while(j<s.size()&&!std::isspace(static_cast<unsigned char>(s[j]))&&s[j]!='('&&s[j]!=')')++j;
        out.push_back({false,s.substr(i,j-i)});i=j;
    }
    return out;
}
void putLen(std::ostringstream& o,char tag,const std::string& v){o<<tag<<v.size()<<':'<<v;}
std::string decodeStream(const std::string& s,size_t pos){
    std::vector<std::string> tokens;
    while(pos<s.size()){
        const unsigned char raw=static_cast<unsigned char>(s[pos]);if(std::isspace(raw)){++pos;continue;}
        const char tag=s[pos++];
        if(tag=='('||tag==')'){tokens.push_back(std::string(1,tag));continue;}
        if(tag=='!'){
            if(pos>=s.size())fail("E_ONME","opcode ONME truncado");
            const char code=s[pos++]; const auto it=reverseCodes().find(code);
            if(it==reverseCodes().end())fail("E_ONME","opcode ONME desconocido");
            tokens.push_back(it->second); continue;
        }
        if(tag!='A'&&tag!='Q')fail("E_ONME","token ONME desconocido");
        const size_t start=pos;while(pos<s.size()&&std::isdigit(static_cast<unsigned char>(s[pos])))++pos;
        if(start==pos||pos>=s.size()||s[pos]!=':')fail("E_ONME","longitud ONME invalida");
        uint64_t n=0;for(size_t k=start;k<pos;++k){n=n*10u+static_cast<unsigned>(s[k]-'0');if(n>s.size())fail("E_ONME","payload ONME truncado");}
        ++pos;if(n>static_cast<uint64_t>(s.size()-pos))fail("E_ONME","payload ONME truncado");tokens.push_back(s.substr(pos,static_cast<size_t>(n)));pos+=static_cast<size_t>(n);
    }
    std::ostringstream out;for(size_t i=0;i<tokens.size();++i){if(i)out<<' ';out<<tokens[i];}out<<'\n';return out.str();
}
std::string checkedHashLine(const std::string& line,char prefix,const std::string& label){
    const std::string start=std::string(1,prefix)+"sha256:";
    if(line.rfind(start,0)!=0||line.size()!=72u)fail("E_ONME",label+" invalida");
    const std::string h=line.substr(1);if(!std::all_of(h.begin()+7,h.end(),[](char c){return std::isxdigit(static_cast<unsigned char>(c))!=0;}))fail("E_ONME",label+" invalida");return h;
}
}

std::string onme(const Program& p){
    auto w=wave(p);Program executable=parseWave(w);validate(executable);
    // Only the ROOTS of the executable and of the authoring program are needed: each system memory lives for one expression, so the peak holds one of them, not four.
    const auto rootOf=[](const Program& q,IdentityProjection projection){ return buildSystemMemory(q,projection).epoch.systemRoot; };
    const auto execRoot=rootOf(executable,IdentityProjection::Current);const auto authorRoot=rootOf(p,IdentityProjection::Current);const auto tokens=tokenize(w);
    w.clear();w.shrink_to_fit();
    // ONME2 only when the historical projection gives the same roots. A program the certified compilers could not project at all (an identity left unresolved in the signature of a generic template) has no
    // historical identity to keep: it is written as ONME3.
    bool compatible=false;
    try{
        compatible=execRoot==rootOf(executable,IdentityProjection::Onme2Compatibility)&&authorRoot==rootOf(p,IdentityProjection::Onme2Compatibility);
    }catch(const Error& error){ if(error.code!="E_TYPE")throw; }
    const std::string version=compatible?"2":"3";
    std::ostringstream payload;
    for(const auto&t:tokens){if(!t.quoted&&(t.text=="("||t.text==")")){payload<<t.text;continue;}if(!t.quoted){const auto it=codes().find(t.text);if(it!=codes().end()){payload<<'!'<<it->second;continue;}}putLen(payload,t.quoted?'Q':'A',t.text);}
    payload<<'\n';const auto body=payload.str();
    const auto commitment="sha256:"+sha256("omni.onme-envelope/"+version+"\n"+execRoot+"\n"+authorRoot+"\n"+body);
    std::ostringstream out;out<<"ONME"<<version<<"\n"<<'R'<<execRoot<<"\n"<<'P'<<authorRoot<<"\n"<<'C'<<commitment<<"\n"<<body;return out.str();
}
Program parseONME(const std::string& s){
    validateUTF8(s);if(s.find('\0')!=std::string::npos)fail("E_ONME","ONME contiene NUL");
    const bool legacy=s.rfind("ONME2\n",0)==0;
    if(!legacy&&s.rfind("ONME3\n",0)!=0)fail("E_VERSION","cabecera ONME no soportada; ONME2/ONME3 requerido para lineage binding");
    const size_t e1=s.find('\n',6);if(e1==std::string::npos)fail("E_ONME","raiz ejecutable ONME truncada");const auto execRoot=checkedHashLine(s.substr(6,e1-6),'R',"raiz OSNMF ejecutable");
    const size_t s2=e1+1,e2=s.find('\n',s2);if(e2==std::string::npos)fail("E_ONME","lineage ONME truncado");const auto authorRoot=checkedHashLine(s.substr(s2,e2-s2),'P',"raiz OSNMF de autoria");
    const size_t s3=e2+1,e3=s.find('\n',s3);if(e3==std::string::npos)fail("E_ONME","commitment ONME truncado");const auto commitment=checkedHashLine(s.substr(s3,e3-s3),'C',"commitment ONME");
    const auto body=s.substr(e3+1);const std::string domain=legacy?"omni.onme-envelope/2\n":"omni.onme-envelope/3\n";
    const auto expected="sha256:"+sha256(domain+execRoot+"\n"+authorRoot+"\n"+body);
    if(commitment!=expected)fail("E_ONME","ONME envelope/authoring-lineage integrity mismatch");
    const auto waveText=decodeStream(s,e3+1);Program p=parseWave(waveText);validate(p);
    const auto projection=legacy?IdentityProjection::Onme2Compatibility:IdentityProjection::Current;
    if(buildSystemMemory(p,projection).epoch.systemRoot!=execRoot)fail("E_ONME","OSNMF executable root mismatch");
    return p;
}
std::string onmeStatsJson(const Program& p){
    const auto w=wave(p),o=onme(p);std::ostringstream x;x<<"{\n  \"schema\": \"omni.onme-stats/1\",\n  \"semantic_layer\": \"machine-semantic-projection\",\n  \"wire_replacement\": false,\n  \"wave_bytes\": "<<w.size()<<",\n  \"onme_bytes\": "<<o.size()<<",\n  \"ratio\": ";if(w.empty())x<<"null";else x<<std::fixed<<std::setprecision(4)<<(static_cast<double>(o.size())/static_cast<double>(w.size()));x<<",\n  \"round_trip\": \"required\",\n  \"roots\": \"executable-integrity + authoring-lineage\"\n}\n";return x.str();
}
}
