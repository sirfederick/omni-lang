#include "sdk_tooling.hpp"

namespace omni {
namespace fs=std::filesystem;
namespace {
struct J { enum K { Str, Obj, Arr, Other }; K kind=Str; std::string s; std::map<std::string,J> o; std::vector<J> a; };
class Json {
    const std::string& in; size_t p=0;
    void ws(){while(p<in.size()&&(in[p]==' '||in[p]=='\n'||in[p]=='\r'||in[p]=='\t'))++p;}
    [[noreturn]] void bad(){fail("E_PACKAGE_MANIFEST","JSON package invalido");}
    uint32_t hex4(){
        if(in.size()-p<4)bad();
        uint32_t code=0;
        const auto parsed=std::from_chars(in.data()+p,in.data()+p+4,code,16);
        if(parsed.ec!=std::errc()||parsed.ptr!=in.data()+p+4)bad();
        p+=4;
        return code;
    }
    std::string string(){
        if(p>=in.size()||in[p++]!='\"')bad();
        std::string r;
        while(p<in.size()) { char c=in[p++]; if(c=='\"')return r; if(static_cast<unsigned char>(c)<0x20)bad();
            if(c!='\\'){r+=c;continue;} if(p>=in.size())bad(); char e=in[p++];
            if(e=='\"'||e=='\\'||e=='/')r+=e; else if(e=='b')r+='\b'; else if(e=='f')r+='\f'; else if(e=='n')r+='\n'; else if(e=='r')r+='\r'; else if(e=='t')r+='\t';
            else if(e=='u'){
                auto code=hex4();
                if(code>=0xd800u&&code<=0xdbffu){
                    if(in.size()-p<2||in[p]!='\\'||in[p+1]!='u')bad();
                    p+=2;const auto low=hex4();
                    if(low<0xdc00u||low>0xdfffu)bad();
                    code=0x10000u+((code-0xd800u)<<10u)+(low-0xdc00u);
                } else if(code>=0xdc00u&&code<=0xdfffu)bad();
                if(code<0x80u)r+=static_cast<char>(code);
                else if(code<0x800u){r+=static_cast<char>(0xc0u|(code>>6u));r+=static_cast<char>(0x80u|(code&0x3fu));}
                else if(code<0x10000u){r+=static_cast<char>(0xe0u|(code>>12u));r+=static_cast<char>(0x80u|((code>>6u)&0x3fu));r+=static_cast<char>(0x80u|(code&0x3fu));}
                else{r+=static_cast<char>(0xf0u|(code>>18u));r+=static_cast<char>(0x80u|((code>>12u)&0x3fu));r+=static_cast<char>(0x80u|((code>>6u)&0x3fu));r+=static_cast<char>(0x80u|(code&0x3fu));}
            } else bad();
        } bad();
    }
    size_t nodes=0;
    int depth=0;   // bounded protocol nesting, not a source declaration/count limit
    struct Depth { int& d; explicit Depth(int& x):d(x){ if(++d>8)fail("E_PACKAGE_MANIFEST","JSON package demasiado profundo"); } ~Depth(){ --d; } };
    J value(){Depth guard(depth);if((++nodes&1023u)==0u)budgetCheck("el JSON de paquetes/SDK"); ws(); if(p>=in.size())bad(); if(in[p]=='\"'){J r;r.s=string();return r;}
        if(in[p]=='['){++p;J r;r.kind=J::Arr;ws();if(p<in.size()&&in[p]==']'){++p;return r;}
            for(;;){r.a.push_back(value());ws();if(p>=in.size())bad();if(in[p]==']'){++p;return r;}if(in[p++]!=',')bad();}}
        if(in[p]!='{'){
            J r;r.kind=J::Other;
            for(const std::string literal:{"true","false","null"})if(in.compare(p,literal.size(),literal)==0){p+=literal.size();r.s=literal;return r;}
            const auto start=p;
            if(in[p]=='-')++p;
            if(p>=in.size())bad();
            if(in[p]=='0')++p;
            else{if(in[p]<'1'||in[p]>'9')bad();while(p<in.size()&&in[p]>='0'&&in[p]<='9')++p;}
            if(p<in.size()&&in[p]=='.'){++p;const auto digits=p;while(p<in.size()&&in[p]>='0'&&in[p]<='9')++p;if(p==digits)bad();}
            if(p<in.size()&&(in[p]=='e'||in[p]=='E')){++p;if(p<in.size()&&(in[p]=='+'||in[p]=='-'))++p;const auto digits=p;while(p<in.size()&&in[p]>='0'&&in[p]<='9')++p;if(p==digits)bad();}
            r.s=in.substr(start,p-start);return r;
        }
        ++p; J r; r.kind=J::Obj; ws(); if(p<in.size()&&in[p]=='}'){++p;return r;}
        for(;;){ws(); auto k=string(); ws(); if(p>=in.size()||in[p++]!=':')bad(); auto v=value(); if(!r.o.emplace(k,std::move(v)).second)bad(); ws(); if(p>=in.size())bad(); if(in[p]=='}'){++p;return r;} if(in[p++]!=',')bad();}
    }
public: explicit Json(const std::string& s):in(s){} J run(){auto r=value();ws();if(p!=in.size())bad();return r;}
};
const J& field(const J& o,const std::string& k,bool required=true){auto i=o.o.find(k);if(i==o.o.end()){if(required)fail("E_PACKAGE_MANIFEST","campo package faltante: "+k); static J none;return none;}return i->second;}
std::string text(const J& o,const std::string& k){auto&v=field(o,k);if(v.kind!=J::Str)fail("E_PACKAGE_MANIFEST","campo package no string: "+k);return v.s;}
bool nameOk(const std::string& s){if(s.empty()||s.front()=='.'||s.back()=='.')return false; for(char c:s)if(!(std::islower(static_cast<unsigned char>(c))||std::isdigit(static_cast<unsigned char>(c))||c=='.'||c=='-'))return false; return true;}
bool versionOk(const std::string& s){int dots=0;bool digit=false;for(char c:s){if(std::isdigit(static_cast<unsigned char>(c)))digit=true;else if(c=='.')++dots;else if(c=='-'&&dots==2)return digit;else return false;}return digit&&dots==2;}
bool safeRel(const std::string& s){fs::path p(s);return !s.empty()&&!p.is_absolute()&&!p.has_root_name();}
bool sourceEntryOk(const std::string& s){
    if(!safeRel(s))return false;
    auto p=fs::path(s).lexically_normal();
    for(const auto& part:p)if(part=="..")return false;
    const auto normalized=p.generic_string();
    return normalized.rfind("src/",0)==0&&normalized.size()>4&&p.extension()==".omni";
}
bool inside(const fs::path& root,const fs::path& path){auto a=root.begin(),b=path.begin();for(;a!=root.end();++a,++b)if(b==path.end()||*a!=*b)return false;return true;}
void noSymlink(const fs::path& p){fs::path q;for(auto&x:fs::absolute(p).lexically_normal()){q/=x;std::error_code e;if(fs::is_symlink(fs::symlink_status(q,e)))fail("E_PACKAGE_PATH","enlace simbolico no admitido: "+q.string());}}
struct P { fs::path root; std::string origin,name,version,entry,manifestHash,sourceHash,legacySourceHash; std::map<std::string,std::pair<std::string,std::string>> deps; };
std::string hashEntries(std::vector<std::pair<std::string,std::string>> files){std::sort(files.begin(),files.end());std::string c;for(auto&f:files)c+=f.first+"\n"+f.second+"\n";return sha256(c);}
std::string legacyTreeHash(const fs::path& root){std::vector<std::pair<std::string,std::string>> files;std::error_code ec;for(fs::recursive_directory_iterator i(root,fs::directory_options::none,ec),e;i!=e;i.increment(ec)){if(ec)fail("E_PACKAGE_PATH","no se pudo recorrer package");auto p=i->path();if(fs::is_symlink(i->symlink_status()))fail("E_PACKAGE_PATH","enlace simbolico no admitido: "+p.string());auto rel=p.lexically_relative(root).generic_string();if(i->is_directory()&&(rel=="bin"||rel==".omni-cert"||rel==".cache")){i.disable_recursion_pending();continue;}if(i->is_regular_file()&&rel!="omni.lock.json")files.emplace_back(rel,sha256File(p));}return hashEntries(std::move(files));}
std::string semanticSourceHash(const fs::path& root){
    auto source=root/"src"; std::error_code ec;
    if(fs::is_symlink(fs::symlink_status(source,ec))||!fs::is_directory(source,ec))fail("E_PACKAGE_PATH","source package invalido: "+source.string());
    std::vector<std::pair<std::string,std::string>> files;
    for(fs::recursive_directory_iterator i(source,fs::directory_options::none,ec),e;i!=e;i.increment(ec)){
        if(ec)fail("E_PACKAGE_PATH","no se pudo recorrer source package");
        auto p=i->path();
        if(fs::is_symlink(i->symlink_status()))fail("E_PACKAGE_PATH","enlace simbolico no admitido: "+p.string());
        if(i->is_regular_file()&&p.extension()==".omni")files.emplace_back(p.lexically_relative(root).generic_string(),sha256File(p));
    }
    return hashEntries(std::move(files));
}
P readPackage(const fs::path& root,const std::string& origin){noSymlink(root);if(!fs::is_directory(root))fail("E_PACKAGE_PATH","package root invalido: "+root.string());auto mf=root/"omni.package.json";if(!fs::is_regular_file(mf))fail("E_PACKAGE_MANIFEST","manifest ausente: "+mf.string());auto j=Json(readUtf8Text(mf)).run();if(j.kind!=J::Obj)fail("E_PACKAGE_MANIFEST","manifest debe ser objeto");for(auto&[k,v]:j.o)if(k!="schema"&&k!="name"&&k!="version"&&k!="entry"&&k!="dependencies")fail("E_PACKAGE_MANIFEST","campo manifest desconocido: "+k);P p; p.root=fs::weakly_canonical(root);p.origin=origin;p.name=text(j,"name");p.version=text(j,"version");p.entry=text(j,"entry");if(text(j,"schema")!="omni.package/1"||!nameOk(p.name)||!versionOk(p.version))fail("E_PACKAGE_MANIFEST","identidad package invalida");if(!sourceEntryOk(p.entry))fail("E_PACKAGE_PATH","entry package fuera de src o invalido");if(!fs::is_regular_file(p.root/p.entry))fail("E_PACKAGE_PATH","entry package ausente");auto di=j.o.find("dependencies");if(di!=j.o.end()){if(di->second.kind!=J::Obj)fail("E_PACKAGE_MANIFEST","dependencies debe ser objeto");for(auto&[n,d]:di->second.o){if(!nameOk(n)||d.kind!=J::Obj||d.o.size()!=2||d.o.count("path")!=1||d.o.count("version")!=1)fail("E_PACKAGE_MANIFEST","dependency invalida: "+n);auto path=text(d,"path"),ver=text(d,"version");if(!safeRel(path)||!versionOk(ver))fail("E_PACKAGE_MANIFEST","dependency path/version invalida: "+n);p.deps[n]={path,ver};}}p.manifestHash=sha256File(mf);p.sourceHash=semanticSourceHash(p.root);p.legacySourceHash=legacyTreeHash(p.root);return p;}
std::string esc(const std::string&s){return quote(s);}
std::string lockText(const std::vector<P>& ps,const std::string& schema){std::ostringstream o;o<<"{\n  \"schema\": "<<esc(schema)<<",\n  \"packages\": [";for(size_t i=0;i<ps.size();++i){auto&p=ps[i];if(i)o<<',';const auto& source=schema=="omni.lock/1"?p.legacySourceHash:p.sourceHash;o<<"\n    {\"origin\":"<<esc(p.origin)<<",\"name\":"<<esc(p.name)<<",\"version\":"<<esc(p.version)<<",\"manifest_sha256\":"<<esc(p.manifestHash)<<",\"source_sha256\":"<<esc(source)<<"}";}return o<<"\n  ]\n}\n",o.str();}
}
std::map<std::string,std::string> sdkContractTexts(const fs::path& sdkRoot,const std::vector<std::string>& requested){
    noSymlink(sdkRoot);
    const auto root=fs::weakly_canonical(fs::absolute(sdkRoot));
    const auto inventory=root/"metadata/omni-sdk.json";
    noSymlink(inventory);
    std::optional<std::map<std::string,std::string>> hashes;
    if(fs::exists(inventory)){
        const auto metadata=Json(readUtf8Text(inventory)).run();
        if(metadata.kind!=J::Obj||text(metadata,"schema")!="omni.sdk-distribution/1")
            fail("E_PACKAGE_MANIFEST","inventario del SDK invalido");
        const auto& components=field(metadata,"components");
        if(components.kind!=J::Arr)fail("E_PACKAGE_MANIFEST","componentes del SDK deben ser una lista");
        hashes.emplace();size_t count=0;
        for(const auto& component:components.a){
            if((++count&1023u)==0u)budgetCheck("el inventario de contratos del SDK");
            if(component.kind!=J::Obj)fail("E_PACKAGE_MANIFEST","componente del SDK invalido");
            const auto name=text(component,"path");const fs::path relative(name);
            if(name.find('\0')!=std::string::npos||!safeRel(name)||relative.generic_string()!=name)
                fail("E_PACKAGE_PATH","ruta de componente del SDK invalida");
            for(const auto& part:relative)if(part==".."||part==".")fail("E_PACKAGE_PATH","componente del SDK fuera de raiz");
            if(!hashes->emplace(name,text(component,"sha256")).second)
                fail("E_PACKAGE_MANIFEST","componente duplicado en el inventario del SDK");
        }
    }
    std::map<std::string,std::string> result;
    for(const auto& name:requested){
        budgetCheck("los contratos del SDK");
        const fs::path relative(name);
        if(!safeRel(name)||relative.generic_string()!=name)fail("E_PACKAGE_PATH","ruta de contrato invalida");
        for(const auto& part:relative)if(part==".."||part==".")fail("E_PACKAGE_PATH","contrato fuera del SDK");
        const auto path=root/relative;noSymlink(path);
        if(hashes&&!hashes->count(name))fail("E_PACKAGE_MANIFEST","contrato no inventariado en el SDK: "+name);
        const auto contents=readUtf8Text(path);
        if(hashes&&hashes->at(name)!=sha256(contents))fail("E_PACKAGE_LOCK","contrato no coincide con el inventario del SDK: "+name);
        result.emplace(name,contents);
    }
    return result;
}
fs::path bundledStandardLibrary(const fs::path& sdkRoot){
    budgetCheck("los metadatos del SDK");
    noSymlink(sdkRoot);
    const auto root=fs::weakly_canonical(fs::absolute(sdkRoot));
    const auto inventory=root/"metadata/omni-sdk.json";
    noSymlink(inventory);
    auto stdManifest=[](const std::string& contents){
        const auto value=Json(contents).run();
        if(value.kind!=J::Obj||text(value,"schema")!="omni.package/1")
            fail("E_PACKAGE_MANIFEST","manifest de biblioteca del SDK invalido");
        const auto name=text(value,"name");
        if(name=="omni.std"&&!versionOk(text(value,"version")))
            fail("E_PACKAGE_MANIFEST","version de stdlib del SDK invalida");
        return name=="omni.std";
    };
    if(!fs::exists(inventory)){
        const auto development=root/"stdlib/omni.package.json";
        noSymlink(development);
        if(!fs::is_regular_file(development))return {};
        if(!stdManifest(readUtf8Text(development)))fail("E_PACKAGE_MANIFEST","stdlib de desarrollo no identifica omni.std");
        return development.parent_path();
    }
    try{
        const auto metadata=Json(readUtf8Text(inventory)).run();
        if(metadata.kind!=J::Obj||text(metadata,"schema")!="omni.sdk-distribution/1")
            fail("E_PACKAGE_MANIFEST","inventario del SDK invalido");
        const auto& components=field(metadata,"components");
        if(components.kind!=J::Arr)fail("E_PACKAGE_MANIFEST","componentes del SDK deben ser una lista");
        fs::path selected;
        size_t count=0;
        for(const auto& component:components.a){
            if((++count&1023u)==0u)budgetCheck("los metadatos del SDK");
            if(component.kind!=J::Obj)fail("E_PACKAGE_MANIFEST","componente del SDK invalido");
            const auto name=text(component,"path");
            const fs::path relative(name);
            if(name.find('\0')!=std::string::npos||relative.empty()||relative.is_absolute()||relative.has_root_name())
                fail("E_PACKAGE_PATH","ruta de componente del SDK invalida");
            for(const auto& part:relative)if(part==".."||part==".")fail("E_PACKAGE_PATH","componente del SDK fuera de raiz");
            if(*relative.begin()!="packages"||relative.filename()!="omni.package.json")continue;
            const auto manifest=root/relative;
            noSymlink(manifest);
            if(!inside(root,fs::weakly_canonical(manifest))||!fs::is_regular_file(manifest))
                fail("E_PACKAGE_PATH","manifest de componente del SDK ausente o fuera de raiz");
            const auto contents=readUtf8Text(manifest);
            if(text(component,"sha256")!=sha256(contents))fail("E_PACKAGE_LOCK","manifest de stdlib no coincide con inventario del SDK");
            if(!stdManifest(contents))continue;
            if(!selected.empty())fail("E_PACKAGE_MANIFEST","inventario del SDK tiene stdlib ambigua");
            selected=manifest.parent_path();
        }
        if(selected.empty())fail("E_PACKAGE_MANIFEST","inventario del SDK no identifica omni.std");
        return selected;
    }catch(Error& error){if(error.source.empty())error.source=inventory.string();throw;}
}
std::string packageCommand(const std::string& action,const fs::path& input,bool offline,
        const fs::path& bundledStdlib){
    if(!offline)fail("E_PACKAGE_OFFLINE","A84 package resolver exige --offline");
    auto root=fs::weakly_canonical(fs::absolute(input));
    const auto workspace=root.parent_path().parent_path();
    std::error_code error;
    const auto bundled=fs::is_directory(bundledStdlib,error)&&!error
        ? fs::weakly_canonical(bundledStdlib) : fs::path{};
    std::vector<P> ps;
    std::set<fs::path> active,seen;
    std::string rootName;
    std::function<void(const fs::path&,const std::string&,const std::string&,bool)> visit;
    visit=[&](const fs::path& requested,const std::string& origin,const std::string& expected,
              bool fromBundledStdlib){
        const auto candidate=fs::weakly_canonical(requested);
        if(!inside(workspace,candidate)&&(!fromBundledStdlib||candidate!=bundled))
            fail("E_PACKAGE_PATH","dependency fuera del workspace");
        if(active.count(candidate))fail("E_PACKAGE_CYCLE","ciclo de dependencias");
        if(seen.count(candidate))return;
        active.insert(candidate);
        auto package=readPackage(candidate,origin);
        if(candidate==root)rootName=package.name;
        if(!expected.empty()&&package.version!=expected)
            fail("E_PACKAGE_RESOLVE","version dependency no satisfecha");
        for(auto&[name,dependency]:package.deps){
            const auto declared=package.root/dependency.first;
            const bool useBundled=name=="omni.std"&&!fs::exists(declared)&&!bundled.empty();
            visit(useBundled?bundled:declared,
                  useBundled?"sdk:omni.std@"+dependency.second:
                      package.root.lexically_relative(root).generic_string()+"/"+dependency.first,
                  dependency.second,useBundled);
        }
        active.erase(candidate);seen.insert(candidate);ps.push_back(std::move(package));
    };
    visit(root,"local:.","",false);
    std::sort(ps.begin(),ps.end(),[](const P&a,const P&b){return std::tie(a.origin,a.name,a.version)<std::tie(b.origin,b.name,b.version);});
    auto lock=lockText(ps,"omni.lock/2");auto legacyLock=lockText(ps,"omni.lock/1");auto lp=root/"omni.lock.json";std::string lockSchema="omni.lock/2";
    if(action=="lock"){if(fs::exists(lp)&&fs::is_symlink(lp))fail("E_PACKAGE_PATH","lock simbolico no admitido");std::ofstream f(lp,std::ios::binary|std::ios::trunc);if(!f)fail("E_FILE","no se pudo escribir lock");f<<lock;if(!f)fail("E_FILE","no se pudo finalizar lock");}
    else {if(!fs::is_regular_file(lp))fail("E_PACKAGE_LOCK","lock ausente o drift detectado");auto existing=readUtf8Text(lp);if(existing==lock)lockSchema="omni.lock/2";else if(existing==legacyLock)lockSchema="omni.lock/1";else fail("E_PACKAGE_LOCK","lock ausente o drift detectado");}
    std::ostringstream out;out<<"{\n  \"schema\": \"omni.package-resolution/1\",\n  \"root\": "<<quote(rootName)<<",\n  \"lock_schema\": "<<quote(lockSchema)<<",\n  \"lock_verified\": true,\n  \"packages\": "<<ps.size()<<"\n}\n";return out.str();
}
HostPackageIdentity lockedHostPackage(const fs::path& input,const fs::path& bundledStdlib){
    const auto requested=fs::absolute(input).lexically_normal();
    noSymlink(requested);
    const auto root=fs::weakly_canonical(requested);
    noSymlink(root/"omni.package.json");
    noSymlink(root/"omni.lock.json");
    const auto resolution=packageCommand("check",root,true,bundledStdlib);
    if(resolution.find("\"lock_schema\": \"omni.lock/2\"")==std::string::npos)
        fail("E_PACKAGE_LOCK","host entry requires omni.lock/2");
    const auto p=readPackage(root,"local:.");
    return {p.origin,p.name,p.version,p.manifestHash,p.sourceHash,
            sha256File(root/"omni.lock.json")};
}
fs::path lockedDependencySource(const fs::path& importer,const std::string& name,const fs::path& bundledStdlib){
    const auto file=fs::weakly_canonical(fs::absolute(importer));
    fs::path pkg;
    for(auto d=file.parent_path();;d=d.parent_path()){
        if(fs::is_regular_file(d/"omni.package.json")){pkg=d;break;}
        if(d==d.parent_path())break;
    }
    if(pkg.empty())fail("E_IMPORT_PATH","import de dependencia fuera de todo package: @"+name);
    if(!inside(pkg/"src",file))fail("E_IMPORT_PATH","el archivo que importa una dependencia debe estar bajo src/ de su package");
    const auto manifest=readPackage(pkg,"local:.");
    const auto dependency=manifest.deps.find(name);
    if(dependency==manifest.deps.end())fail("E_IMPORT_PATH","dependencia no declarada en el manifest: @"+name);
    (void)packageCommand("check",pkg,true,bundledStdlib);   // the lock of the whole closure must still match its bytes
    const auto declared=pkg/dependency->second.first;
    const bool useBundled=name=="omni.std"&&!fs::exists(declared)&&!bundledStdlib.empty()&&fs::is_directory(bundledStdlib);
    const auto src=fs::weakly_canonical(useBundled?bundledStdlib:declared)/"src";
    noSymlink(src);
    if(!fs::is_directory(src))fail("E_PACKAGE_PATH","la dependencia no tiene src/: "+name);
    return src;
}
fs::path lockedHostSource(const fs::path& input,const std::string& modulePath,
        const fs::path& bundledStdlib){
    const fs::path relative(modulePath);
    if(!sourceEntryOk(modulePath)||relative.generic_string()!=relative.lexically_normal().generic_string())
        fail("E_PACKAGE_PATH","unsafe host entry module path");
    for(const auto& part:relative)if(part==".."||part==".")
        fail("E_PACKAGE_PATH","unsafe host entry module path");
    const auto requested=fs::absolute(input).lexically_normal();
    noSymlink(requested);
    const auto root=fs::weakly_canonical(requested);
    (void)lockedHostPackage(root,bundledStdlib);
    const auto path=root/relative;
    noSymlink(path);
    if(!fs::is_regular_file(path))fail("E_PACKAGE_PATH","host entry source absent");
    return path;
}
}
