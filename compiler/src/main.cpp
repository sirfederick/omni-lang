#include "omni.hpp"
#include "tooling_bindings.hpp"
#include "sdk_tooling.hpp"
#include <pthread.h>
#include "host_invocation_build.hpp"
#include "host_invocation_codegen.hpp"
#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <new>
#include <random>
#ifdef _WIN32
#include <windows.h>
#include <process.h>
#else
#include <fcntl.h>
#include <spawn.h>
#include <sys/resource.h>
#include <sys/utsname.h>
#include <sys/wait.h>
#include <unistd.h>
#include <cerrno>
extern char **environ;
#endif
namespace fs=std::filesystem;
using namespace omni;
namespace  {
    constexpr const char* TARGET_ID="linux-x86_64-gnu";
    std::string targetMatrixJson() {
        return std::string("{\n  \"schema\": \"omni.target-matrix/1\",\n  \"language_version\": ")+quote(VERSION)+
            ",\n  \"targets\": [\n"
            "    {\"id\":\"linux-x86_64-gnu\",\"state\":\"SUPPORTED\",\"reason\":\"Linux host profile; distribution certification pending\"},\n"
            "    {\"id\":\"windows-x86_64-msvc\",\"state\":\"EXPERIMENTAL_NOT_RUN\",\"reason\":\"native MSVC toolchain and runner unavailable\"},\n"
            "    {\"id\":\"linux-aarch64-gnu\",\"state\":\"EXPERIMENTAL_NOT_RUN\",\"reason\":\"admitted AArch64 runner unavailable\"},\n"
            "    {\"id\":\"macos-aarch64\",\"state\":\"EXPERIMENTAL_NOT_RUN\",\"reason\":\"native macOS runner unavailable\"}\n"
            "  ]\n}\n";
    }
    std::string targetProbeJson() {
#ifdef _WIN32
        const char* os="windows"; const char* abi="msvc";
#else
        const char* os="linux"; const char* abi="gnu";
#endif
#if defined(__x86_64__) || defined(_M_X64)
        const char* arch="x86_64";
#elif defined(__aarch64__) || defined(_M_ARM64)
        const char* arch="aarch64";
#else
        const char* arch="unknown";
#endif
        std::string kernel="unavailable";
#ifndef _WIN32
        struct utsname u{}; if(uname(&u)==0)kernel=std::string(u.sysname)+" "+u.release+" "+u.machine;
#endif
        const bool supported=std::string(os)=="linux"&&std::string(arch)=="x86_64"&&std::string(abi)=="gnu";
        uint16_t endianValue=1; const char* byteOrder=*reinterpret_cast<unsigned char*>(&endianValue)==1?"little":"big";
        std::ostringstream out;
        out<<"{\n  \"schema\": \"omni.target-probe/1\",\n  \"language_version\": "<<quote(VERSION)<<",\n"
           <<"  \"target_id\": "<<quote(supported?TARGET_ID:"unknown")<<",\n  \"os\": "<<quote(os)<<",\n"
           <<"  \"architecture\": "<<quote(arch)<<",\n  \"abi\": "<<quote(abi)<<",\n"
           <<"  \"byte_order\": "<<quote(byteOrder)<<",\n  \"pointer_bits\": "<<(sizeof(void*)*8)<<",\n"
           <<"  \"kernel\": "<<quote(kernel)<<",\n  \"compiler_family\": "
#if defined(__clang__)
           <<quote("clang")
#elif defined(__GNUC__)
           <<quote("gcc-compatible")
#elif defined(_MSC_VER)
           <<quote("msvc")
#else
           <<quote("unknown")
#endif
           <<",\n  \"supported\": "<<(supported?"true":"false")<<"\n}\n";
        return out.str();
    }
    TargetFacts factsForProfile(const std::string& profile,const std::string& isa){
        TargetFacts facts;
        if(profile=="baremetal-x86_64"){facts.hosted=false;facts.features.clear();if(isa=="sse2")facts.features.insert("sse2");}
        else if(profile=="baremetal-i386-boot"){facts.arch="i386";facts.pointerWidth=32;facts.hosted=false;facts.features.clear();}
        return facts;
    }
    struct RunObservation {
        int exitCode=0,signal=0;
        uint64_t durationNs=0,userNs=0,systemNs=0,maxRssKb=0;
        bool outputTruncated=false;
        std::string output;
    };
    RunObservation runObserved(const std::vector<std::string>& argv) {
#ifdef _WIN32
        (void)argv;
        fail("E_TARGET_UNVALIDATED","profile/coverage requieren ejecucion Linux validada");
#else
        int fds[2];if(pipe(fds)!=0)fail("E_TOOL","pipe de observacion fallo");
        posix_spawn_file_actions_t actions;posix_spawn_file_actions_init(&actions);
        posix_spawn_file_actions_adddup2(&actions,fds[1],STDOUT_FILENO);
        posix_spawn_file_actions_adddup2(&actions,fds[1],STDERR_FILENO);
        posix_spawn_file_actions_addclose(&actions,fds[0]);posix_spawn_file_actions_addclose(&actions,fds[1]);
        std::vector<char*> args;for(auto& item:argv)args.push_back(const_cast<char*>(item.c_str()));args.push_back(nullptr);
        pid_t pid;const auto start=std::chrono::steady_clock::now();
        const int error=posix_spawnp(&pid,args[0],&actions,nullptr,args.data(),environ);
        posix_spawn_file_actions_destroy(&actions);close(fds[1]);
        if(error){close(fds[0]);fail("E_TOOL","no se pudo ejecutar artefacto observado");}
        RunObservation observation;char buffer[4096];
        for(;;){const ssize_t count=read(fds[0],buffer,sizeof buffer);if(count>0){const auto n=static_cast<size_t>(count);if(observation.output.size()<OMNI_TEXT_VALUE_LIMIT_BYTES){const auto room=OMNI_TEXT_VALUE_LIMIT_BYTES-observation.output.size();observation.output.append(buffer,std::min(n,room));if(n>room)observation.outputTruncated=true;}else observation.outputTruncated=true;}else if(count<0&&errno==EINTR)continue;else break;}
        close(fds[0]);int status=0;struct rusage usage{};while(wait4(pid,&status,0,&usage)<0){if(errno!=EINTR)fail("E_TOOL","wait4 fallo");}
        const auto end=std::chrono::steady_clock::now();
        observation.durationNs=static_cast<uint64_t>(std::chrono::duration_cast<std::chrono::nanoseconds>(end-start).count());
        observation.userNs=static_cast<uint64_t>(usage.ru_utime.tv_sec)*1000000000u+static_cast<uint64_t>(usage.ru_utime.tv_usec)*1000u;
        observation.systemNs=static_cast<uint64_t>(usage.ru_stime.tv_sec)*1000000000u+static_cast<uint64_t>(usage.ru_stime.tv_usec)*1000u;
        observation.maxRssKb=static_cast<uint64_t>(usage.ru_maxrss);
        if(WIFEXITED(status))observation.exitCode=WEXITSTATUS(status);else if(WIFSIGNALED(status)){observation.signal=WTERMSIG(status);observation.exitCode=128+observation.signal;}else observation.exitCode=255;
        return observation;
#endif
    }
    struct ScopedEnvironment {
        std::string name;std::optional<std::string> previous;
        ScopedEnvironment(std::string key,const std::string& value):name(std::move(key)) {
            if(const char* old=std::getenv(name.c_str()))previous=old;
#ifdef _WIN32
            if(_putenv_s(name.c_str(),value.c_str())!=0)fail("E_TOOL","no se pudo configurar entorno de tooling");
#else
            if(setenv(name.c_str(),value.c_str(),1)!=0)fail("E_TOOL","no se pudo configurar entorno de tooling");
#endif
        }
        ~ScopedEnvironment(){
#ifdef _WIN32
            (void)_putenv_s(name.c_str(),previous?previous->c_str():"");
#else
            if(previous)(void)setenv(name.c_str(),previous->c_str(),1);else (void)unsetenv(name.c_str());
#endif
        }
    };
    int launch(const std::vector<std::string>& argv)  {
        std::vector<char*> args;
        for(auto& a:argv)args.push_back(const_cast<char*>(a.c_str()));
        args.push_back(nullptr);
#ifdef _WIN32
        auto r=_spawnvp(_P_WAIT,args[0],args.data());
        if(r<0)fail("E_TOOL","no se pudo ejecutar: "+argv[0]);
        return static_cast<int>(r);
#else
        pid_t pid;
        int err=posix_spawnp(&pid,args[0],nullptr,nullptr,args.data(),environ);
        if(err)fail("E_TOOL","no se pudo ejecutar: "+argv[0]+" ("+std::to_string(err)+")");
        int status=0;
        while(waitpid(pid,&status,0)<0)  {
            if(errno!=EINTR)fail("E_TOOL","waitpid fallo");
        }
        return WIFEXITED(status)?WEXITSTATUS(status):128+(WIFSIGNALED(status)?WTERMSIG(status):0);
#endif
    }

    std::string capture(const std::vector<std::string>& argv)  {
#ifdef _WIN32
        (void)argv;
        return "windows-backend-unvalidated";
#else
        int fds[2];
        if(pipe(fds)!=0)fail("E_TOOL","pipe fallo");
        posix_spawn_file_actions_t acts;
        posix_spawn_file_actions_init(&acts);
        posix_spawn_file_actions_adddup2(&acts,fds[1],STDOUT_FILENO);
        posix_spawn_file_actions_adddup2(&acts,fds[1],STDERR_FILENO);
        posix_spawn_file_actions_addclose(&acts,fds[0]);
        posix_spawn_file_actions_addclose(&acts,fds[1]);
        std::vector<char*> args;
        for(auto& a:argv)args.push_back(const_cast<char*>(a.c_str()));
        args.push_back(nullptr);
        pid_t pid;
        int err=posix_spawnp(&pid,args[0],&acts,nullptr,args.data(),environ);
        posix_spawn_file_actions_destroy(&acts);
        close(fds[1]);
        if(err){ close(fds[0]); fail("E_TOOL","no se pudo ejecutar backend: "+argv[0]); }
        std::string out; char buf[4096];
        for(;;){ ssize_t n=read(fds[0],buf,sizeof(buf)); if(n>0){ out.append(buf,static_cast<size_t>(n)); if(out.size()>65536){ close(fds[0]); fail("E_TOOL","identidad de backend demasiado grande"); } } else break; }
        close(fds[0]);
        int status=0; while(waitpid(pid,&status,0)<0){ if(errno!=EINTR)fail("E_TOOL","waitpid fallo"); }
        if(!WIFEXITED(status)||WEXITSTATUS(status)!=0)fail("E_TOOL","backend no disponible: "+argv[0]);
        return out;
#endif
    }
    fs::path defaultCacheDir() {
        if(auto p=std::getenv("OMNI_CACHE_DIR"))return fs::absolute(p);
        if(auto p=std::getenv("XDG_CACHE_HOME"))return fs::absolute(p)/"omni";
        if(auto p=std::getenv("HOME"))return fs::absolute(p)/".cache/omni";
        return fs::temp_directory_path()/"omni-cache";
    }
    struct BuildResult { bool cacheHit=false; std::string key; fs::path cacheEntry; };
    struct Scratch  {
        fs::path path;
        explicit Scratch(const fs::path& parent)  {
            std::random_device rd;
            for(int i=0; i<50; i++)  {
                auto name=".omni-tmp-"+std::to_string(rd())+"-"+std::to_string(rd());
                path=parent/name;
                std::error_code e;
                if(fs::create_directory(path,e))  {
                    fs::permissions(path,fs::perms::owner_all,fs::perm_options::replace);
                    return;
                }
            }
            fail("E_FILE","no se pudo crear directorio temporal privado");
        }
        ~Scratch()  {
            std::error_code e;
            fs::remove_all(path,e);
        }
    };
    void write(const fs::path& p,const std::string& data)  {
        if(fs::is_symlink(p)||fs::is_directory(p))fail("E_FILE","salida no puede ser enlace/directorio: "+p.string());
        std::ofstream f(p,std::ios::binary|std::ios::trunc);
        if(data.size()>static_cast<size_t>(std::numeric_limits<std::streamsize>::max()))fail("E_LIMIT","salida demasiado grande: "+p.string());
        if(!f||!f.write(data.data(),static_cast<std::streamsize>(data.size()))||!f.flush())fail("E_FILE","no se pudo escribir: "+p.string());
    }
    void syncFile(const fs::path& p) {
#ifdef _WIN32
        HANDLE h=CreateFileW(p.wstring().c_str(),GENERIC_READ,FILE_SHARE_READ,nullptr,OPEN_EXISTING,FILE_ATTRIBUTE_NORMAL,nullptr);
        if(h==INVALID_HANDLE_VALUE||!FlushFileBuffers(h)){if(h!=INVALID_HANDLE_VALUE)CloseHandle(h);fail("E_DURABILITY","no se pudo sincronizar archivo: "+p.string());}
        CloseHandle(h);
#else
        const int fd=::open(p.c_str(),O_RDONLY|O_CLOEXEC);
        if(fd<0||::fsync(fd)!=0){if(fd>=0)::close(fd);fail("E_DURABILITY","no se pudo sincronizar archivo: "+p.string());}
        ::close(fd);
#endif
    }
    void syncDirectory(const fs::path& p) {
#ifndef _WIN32
        const auto dir=p.empty()?fs::path("."):p;
        const int fd=::open(dir.c_str(),O_RDONLY|O_DIRECTORY|O_CLOEXEC);
        if(fd<0||::fsync(fd)!=0){if(fd>=0)::close(fd);fail("E_DURABILITY","no se pudo sincronizar directorio: "+dir.string());}
        ::close(fd);
#else
        (void)p;
#endif
    }
    void durableWrite(const fs::path& p,const std::string& data){write(p,data);syncFile(p);}
    void replaceFile(const fs::path& from,const fs::path& to) {
        if(fs::is_symlink(to)||fs::is_directory(to))fail("E_DURABILITY","destino de publicacion no regular: "+to.string());
#ifdef _WIN32
        if(!MoveFileExW(from.wstring().c_str(),to.wstring().c_str(),MOVEFILE_REPLACE_EXISTING|MOVEFILE_WRITE_THROUGH))fail("E_DURABILITY","no se pudo publicar archivo: "+to.string());
#else
        if(::rename(from.c_str(),to.c_str())!=0)fail("E_DURABILITY","no se pudo publicar archivo: "+to.string());
#endif
        syncDirectory(to.parent_path());
    }
    std::vector<std::string> fields(const std::string& s,char delimiter) {
        std::vector<std::string> result;size_t start=0;
        while(true){const auto end=s.find(delimiter,start);if(end==std::string::npos){result.push_back(s.substr(start));break;}result.push_back(s.substr(start,end-start));start=end+1u;}
        return result;
    }
    std::map<std::string,std::string> parseDurabilityRecord(const std::string& text,const std::string& schema) {
        validateUTF8(text);std::istringstream in(text);std::string line;
        if(!std::getline(in,line)||line!=schema)fail("E_DURABILITY","schema de publicacion invalido");
        std::map<std::string,std::string> values;std::string body;bool ended=false;
        while(std::getline(in,line)){
            if(line.empty())continue;
            if(ended)fail("E_DURABILITY","contenido posterior a integridad");
            const auto splitAt=line.find('|');if(splitAt==std::string::npos)fail("E_DURABILITY","registro de publicacion invalido");
            const auto key=line.substr(0,splitAt);const auto value=line.substr(splitAt+1u);
            if(key=="integrity"){
                if(value!="sha256:"+sha256("omni."+std::string(schema=="OSMC1"?"osmc/1":"osmt/1")+"\n"+body))fail("E_DURABILITY","integridad de publicacion invalida");
                ended=true;continue;
            }
            if(!values.emplace(key,value).second)fail("E_DURABILITY","campo de publicacion duplicado");
            body+=line+"\n";
        }
        if(!ended)fail("E_DURABILITY","registro de publicacion incompleto");
        return values;
    }
    std::pair<std::string,std::string> storeEpochAndProjection(const std::string& store) {
        std::istringstream in(store);std::string header,epoch;
        if(!std::getline(in,header)||header!="OSM2"||!std::getline(in,epoch))fail("E_OSNMF","publicacion requiere OSM2");
        const auto parts=fields(epoch,'|');if(parts.size()!=10u||parts[0]!="E")fail("E_OSNMF","epoch OSM2 invalido");
        return {parts[2],parts[9]};
    }
    std::string commitRecord(const std::string& store,const std::string& index) {
        const auto identity=storeEpochAndProjection(store);std::ostringstream body;
        body<<"store_sha256|sha256:"<<sha256(store)<<"\nstore_bytes|"<<store.size()<<"\nindex_sha256|sha256:"<<sha256(index)<<"\nindex_bytes|"<<index.size()<<"\nepoch|"<<identity.first<<"\nprojection_root|"<<identity.second<<"\n";
        const auto b=body.str();return "OSMC1\n"+b+"integrity|sha256:"+sha256("omni.osmc/1\n"+b)+"\n";
    }
    bool safeSiblingName(const std::string& name){return !name.empty()&&fs::path(name).filename()==fs::path(name)&&name.find("..") == std::string::npos;}
    void maybeRecoverSnapshotPublication(const fs::path& store) {
        const fs::path txn=store.string()+".txn";if(!fs::exists(txn))return;
        if(fs::is_symlink(txn)||!fs::is_regular_file(txn))fail("E_DURABILITY","transaction record no regular");
        const auto values=parseDurabilityRecord(readUtf8TextBounded(txn,65536u),"OSMT1");
        const fs::path index=store.string()+".idx",commit=store.string()+".commit";
        const auto parent=store.parent_path();
        auto required=[&](const std::string& key)->const std::string&{const auto it=values.find(key);if(it==values.end()||it->second.empty())fail("E_DURABILITY","transaction record sin "+key);return it->second;};
        const auto& storeTmpName=required("store_temp");const auto& indexTmpName=required("index_temp");const auto& commitTmpName=required("commit_temp");
        if(!safeSiblingName(storeTmpName)||!safeSiblingName(indexTmpName)||!safeSiblingName(commitTmpName))fail("E_DURABILITY","ruta temporal no segura");
        auto recoverOne=[&](const fs::path& final,const fs::path& staged,const std::string& expected){
            if(fs::exists(final)&&!fs::is_symlink(final)&&fs::is_regular_file(final)&&"sha256:"+sha256File(final)==expected)return;
            if(fs::is_symlink(staged)||!fs::is_regular_file(staged)||"sha256:"+sha256File(staged)!=expected)fail("E_DURABILITY","publicacion incompleta sin recuperacion exacta: "+final.string());
            replaceFile(staged,final);
        };
        recoverOne(store,parent/storeTmpName,required("store_sha256"));
        recoverOne(index,parent/indexTmpName,required("index_sha256"));
        recoverOne(commit,parent/commitTmpName,required("commit_sha256"));
        fs::remove(txn);syncDirectory(parent);
    }
    void validateFullSnapshotPublication(const fs::path& store) {
        const fs::path commit=store.string()+".commit";if(!fs::exists(commit))return;
        const fs::path index=store.string()+".idx";
        for(const auto& path:{store,index,commit})if(fs::is_symlink(path)||!fs::is_regular_file(path))fail("E_DURABILITY","snapshot publicado contiene ruta no regular: "+path.string());
        const auto values=parseDurabilityRecord(readUtf8TextBounded(commit,65536u),"OSMC1");
        auto required=[&](const std::string& key)->const std::string&{const auto it=values.find(key);if(it==values.end()||it->second.empty())fail("E_DURABILITY","OSMC1 sin "+key);return it->second;};
        if("sha256:"+sha256File(store)!=required("store_sha256")||"sha256:"+sha256File(index)!=required("index_sha256"))fail("E_DURABILITY","snapshot store/index/commit incoherente");
        if(std::to_string(fs::file_size(store))!=required("store_bytes")||std::to_string(fs::file_size(index))!=required("index_bytes"))fail("E_DURABILITY","snapshot size/commit incoherente");
    }
    void publishSnapshot(const fs::path& store,const std::string& storeText,bool force) {
        const fs::path index=store.string()+".idx",commit=store.string()+".commit",txn=store.string()+".txn";
        for(const auto& path:{store,index,commit,txn})if(fs::is_symlink(path)||fs::is_directory(path))fail("E_FILE","salida de snapshot no regular: "+path.string());
        if(!force&&(fs::exists(store)||fs::exists(index)||fs::exists(commit)||fs::exists(txn)))fail("E_EXISTS","snapshot o metadata existente; use --force");
        if(fs::exists(txn))maybeRecoverSnapshotPublication(store);
        const auto indexText=systemMemoryIndex(storeText);const auto commitText=commitRecord(storeText,indexText);
        std::random_device rd;const auto token=std::to_string(static_cast<unsigned long long>(rd()))+"-"+std::to_string(static_cast<unsigned long long>(rd()));
        const auto parent=store.parent_path();const auto base=store.filename().string()+".omni-publish-"+token;
        const fs::path storeTmp=parent/(base+".store"),indexTmp=parent/(base+".index"),commitTmp=parent/(base+".commit");
        durableWrite(storeTmp,storeText);durableWrite(indexTmp,indexText);durableWrite(commitTmp,commitText);
        std::ostringstream body;body<<"store_temp|"<<storeTmp.filename().string()<<"\nindex_temp|"<<indexTmp.filename().string()<<"\ncommit_temp|"<<commitTmp.filename().string()<<"\nstore_sha256|sha256:"<<sha256(storeText)<<"\nindex_sha256|sha256:"<<sha256(indexText)<<"\ncommit_sha256|sha256:"<<sha256(commitText)<<"\n";
        const auto b=body.str();durableWrite(txn,"OSMT1\n"+b+"integrity|sha256:"+sha256("omni.osmt/1\n"+b)+"\n");syncDirectory(parent);
        auto inject=[&](const char* phase){const auto value=std::getenv("OMNI_TEST_OSNMF_PUBLISH_FAULT");if(value&&std::string(value)==phase)std::_Exit(86);};
        inject("after_transaction");replaceFile(storeTmp,store);inject("after_store");replaceFile(indexTmp,index);inject("after_index");replaceFile(commitTmp,commit);inject("after_commit");
        fs::remove(txn);syncDirectory(parent);
    }
    fs::path root(const char* arg0)  {
        if(auto r=std::getenv("OMNI_HOME"))return fs::absolute(r);
#ifndef _WIN32
        std::error_code ec;
        auto exe=fs::read_symlink("/proc/self/exe",ec);
        if(!ec)  {
            auto p=exe.parent_path();
            for(int i=0; i<5&&!p.empty(); i++,p=p.parent_path())if(fs::exists(p/"runtime/omni_runtime.c"))return p;
        }
#endif
        auto p=fs::absolute(arg0).parent_path();
        for(int i=0; i<5&&!p.empty(); i++,p=p.parent_path())if(fs::exists(p/"runtime/omni_runtime.c"))return p;
        return fs::current_path();
    }
    std::string compilerArtifactHash() {
#if defined(__linux__)
        std::error_code ec; auto exe=fs::read_symlink("/proc/self/exe",ec);
        if(ec||exe.empty())fail("E_TOOL","no se pudo resolver identidad del compilador en /proc/self/exe");
        return sha256File(exe);
#else
        return "unvalidated-platform";
#endif
    }
    BuildResult build(const Program& p,const fs::path& dest,const fs::path& runtime,const std::string& clang,const std::string& opt,bool force,bool useCache,const fs::path& cacheRoot)  {
#if !defined(__linux__) || !defined(__x86_64__)
        (void)p;(void)dest;(void)runtime;(void)clang;(void)opt;(void)force;(void)useCache;(void)cacheRoot;
        fail("E_TARGET_UNVALIDATED","esta entrega solo valida build nativo Linux x86-64");
#else
        requireMain(p);
        const std::string target=TARGET_ID;
        auto output=fs::absolute(dest);
        if(fs::exists(output)&&!force)fail("E_EXISTS","salida existente; use otra ruta o --force");
        if(fs::is_directory(output)||fs::is_symlink(output))fail("E_FILE","salida no puede ser directorio ni enlace");
        if(!fs::is_directory(output.parent_path()))fail("E_FILE","carpeta de salida inexistente");
        if(!fs::is_regular_file(runtime))fail("E_TOOL","runtime no encontrado; defina OMNI_HOME o --runtime");
        const auto backendIdentity=capture({clang,"--version"});
        const auto compilerHash=compilerArtifactHash();
        BuildResult result; result.key=buildKey(p,runtime,compilerHash,backendIdentity,opt,target);
        result.cacheEntry=fs::absolute(cacheRoot)/"build-v1"/result.key/"app";
        auto digestPath=result.cacheEntry.parent_path()/"artifact.sha256";
        if(useCache&&!fs::is_symlink(result.cacheEntry)&&!fs::is_symlink(digestPath)&&fs::is_regular_file(result.cacheEntry)&&fs::is_regular_file(digestPath)){
            auto expected=readUtf8Text(digestPath); while(!expected.empty()&&(expected.back()=='\n'||expected.back()=='\r'))expected.pop_back();
            if(expected==sha256File(result.cacheEntry)){
                Scratch temp(output.parent_path());
                fs::copy_file(result.cacheEntry,temp.path/"app",fs::copy_options::overwrite_existing);
                fs::permissions(temp.path/"app",fs::status(result.cacheEntry).permissions());
                fs::rename(temp.path/"app",output);
                result.cacheHit=true;
                write(fs::path(output.string()+".ometa.json"),artifactReceipt(p,output,result.key,runtime,compilerHash,backendIdentity,opt,target,true));
                write(fs::path(output.string()+".omap.json"),sourceMapJson(p,output));
                return result;
            }
        }
        Scratch temp(output.parent_path());
        write(temp.path/"program.ll",emitLLVM(p));
        int status=launch({clang,"--target=x86_64-unknown-linux-gnu","-O"+opt,(temp.path/"program.ll").string(),fs::absolute(runtime).string(),"-ldl","-o",(temp.path/"app").string()});
        if(status!=0)fail("E_BACKEND","Clang rechazo la construccion; salida previa conservada");
        if(!fs::exists(temp.path/"app"))fail("E_BACKEND","no se genero ejecutable");
        fs::rename(temp.path/"app",output);
        if(useCache){
            std::error_code ec; fs::create_directories(result.cacheEntry.parent_path(),ec);
            if(ec)fail("E_CACHE","no se pudo crear cache local: "+ec.message());
            auto tmp=result.cacheEntry.parent_path()/"app.tmp";
            fs::copy_file(output,tmp,fs::copy_options::overwrite_existing,ec);
            if(ec)fail("E_CACHE","no se pudo publicar artefacto en cache: "+ec.message());
            fs::permissions(tmp,fs::status(output).permissions(),ec);
            fs::rename(tmp,result.cacheEntry,ec);
            if(ec && !fs::exists(result.cacheEntry))fail("E_CACHE","no se pudo finalizar artefacto en cache: "+ec.message());
            write(digestPath,sha256File(result.cacheEntry)+"\n");
        }
        write(fs::path(output.string()+".ometa.json"),artifactReceipt(p,output,result.key,runtime,compilerHash,backendIdentity,opt,target,false));
        write(fs::path(output.string()+".omap.json"),sourceMapJson(p,output));
        return result;
#endif
    }
    fs::path fixedHostBackend() {
#if !defined(__linux__) || !defined(__x86_64__)
        fail("E_TARGET_UNVALIDATED","host invocation requires linux-x86_64-gnu");
#else
        const char* path=std::getenv("PATH");
        if(!path)fail("E_TOOL","PATH is unavailable for host backend");
        std::istringstream entries(path);
        std::string directory;
        while(std::getline(entries,directory,':')){
            if(directory.empty())continue;
            const auto candidate=fs::path(directory)/"clang";
            std::error_code ec;
            if(fs::is_regular_file(candidate,ec)&&access(candidate.c_str(),X_OK)==0)
                return fs::canonical(candidate);
        }
        fail("E_TOOL","clang backend is unavailable");
#endif
    }
    void buildHostInvocation(const fs::path& packageRoot,const std::string& hostEntry,
                             const fs::path& dest,const fs::path& compilerRoot,bool force) {
#if !defined(__linux__) || !defined(__x86_64__)
        (void)packageRoot;(void)hostEntry;(void)dest;(void)compilerRoot;(void)force;
        fail("E_TARGET_UNVALIDATED","host invocation requires linux-x86_64-gnu");
#else
        const auto runtimeRoot=compilerRoot/"runtime";
        const auto loader=runtimeRoot/"libomni_invocation_v1.so";
        if(!fs::is_regular_file(loader)||fs::is_symlink(loader))
            fail("E_TOOL","matching invocation loader is unavailable");
        const auto output=fs::absolute(dest);
        if(output.extension()!=".so"||!fs::is_directory(output.parent_path())||
           fs::is_symlink(output)||fs::is_directory(output))
            fail("E_FILE","host artifact must be a regular .so path");
        if(fs::exists(output)&&!force)fail("E_EXISTS","host artifact already exists");
        const auto compilerHash=invocationHashHex(compilerArtifactHash());
        const auto buildIdPath=runtimeRoot/"omni_invocation_build_id.txt";
        if(!fs::is_regular_file(buildIdPath)||fs::is_symlink(buildIdPath))
            fail("E_TOOL","matching invocation runtime build identity is unavailable");
        auto buildId=readUtf8TextBounded(buildIdPath,128);
        while(!buildId.empty()&&(buildId.back()=='\n'||buildId.back()=='\r'))buildId.pop_back();
        const auto runtimeHash=invocationHashHex(buildId);
        const auto backendIdPath=runtimeRoot/"omni_invocation_backend_sha256.txt";
        if(!fs::is_regular_file(backendIdPath)||fs::is_symlink(backendIdPath))
            fail("E_TOOL","matching invocation backend identity is unavailable");
        auto backendHash=readUtf8TextBounded(backendIdPath,128);
        while(!backendHash.empty()&&(backendHash.back()=='\n'||backendHash.back()=='\r'))
            backendHash.pop_back();
        const auto clangPath=fixedHostBackend();
        if(invocationHashHex(backendHash)!=invocationHashHex(sha256File(clangPath)))
            fail("E_TOOL","clang backend differs from invocation runtime build");
        auto selected=selectHostBuild(packageRoot,hostEntry,compilerHash,runtimeHash,
                                      bundledStandardLibrary(compilerRoot));
        for(const auto& source:selected.program.sources) {
            std::error_code ec;
            if(fs::equivalent(output,source,ec))fail("E_FILE","host artifact overwrites source");
        }
        Scratch scratch(output.parent_path());
        const auto descriptor=encodeInvocationDescriptor(selected.descriptor);
        const auto descriptorHash=invocationHash(descriptor);
        write(scratch.path/"module.ll",emitLLVMHost(selected.program,selected.functionKey));
        write(scratch.path/"module.c",hostInvocationWrapperC(selected));
        const auto built=scratch.path/"module.so";
        const int status=launch({clangPath.string(),"--target=x86_64-unknown-linux-gnu","-O2",
            "-shared","-fPIC","-fvisibility=hidden","-nostartfiles",
            "-Wl,-z,relro,-z,now","-I",runtimeRoot.string(),
            (scratch.path/"module.ll").string(),(scratch.path/"module.c").string(),
            "-L",runtimeRoot.string(),"-lomni_invocation_v1",
            "-o",built.string()});
        if(status!=0||!fs::is_regular_file(built))fail("E_BACKEND","host artifact build failed");
        fs::rename(built,output);
        write(fs::path(output.string()+".omireceipt.json"),
              hostBuildReceiptJson(selected,output,descriptorHash));
#endif
    }
    std::string diagnosticCategory(const std::string& code) {
        if(code=="E_LEX"||code=="E_STRING"||code=="E_NUMBER"||code=="E_UTF8") return "lexical";
        if(code=="E_PARSE"||code=="E_MATCH") return "syntax";
        if(code=="E_MATCH_NON_EXHAUSTIVE"||code=="E_MATCH_DUPLICATE"||code=="E_MATCH_VARIANT"||code=="E_MATCH_BINDING") return "flow";
        if(code=="E_NAME"||code=="E_UNDEFINED"||code=="E_CALL"||code=="E_DUPLICATE"||code=="E_MODULE"||code.rfind("E_IMPORT",0)==0||code=="E_VISIBILITY") return "names";
        if(code=="E_TYPE"||code=="E_ARITY"||code=="E_FIELDS"||code=="E_RETURN"||code=="E_LAYOUT_CYCLE"||code=="E_ARRAY_LENGTH"||code=="E_ARRAY_EMPTY"||code=="E_TUPLE_INDEX"||code=="E_PRODUCT_LINEAR"||code=="E_VIEW_SOURCE"||code=="E_VIEW_MUTABLE"||code=="E_ASYNC_UNSUPPORTED"||code=="E_GENERIC_ARGS"||code=="E_GENERIC_DECL"||code=="E_GENERIC_CONSTRAINT"||code=="E_GENERIC_TARGET"||code=="E_TRAIT"||code=="E_TRAIT_COHERENCE"||code=="E_ITERABLE"||code=="E_PATTERN"||code=="E_PATTERN_ARITY"||code=="E_INDEX_TYPE"||code=="E_RANGE_TYPE"||code.rfind("E_TASK_",0)==0||code=="E_CHANNEL_TYPE"||code=="E_CHANNEL_PROFILE") return "types";
        if(code.rfind("E_RESULT",0)==0||code=="E_IMMUTABLE"||code=="E_UNREACHABLE"||code=="E_LOOP_CONTROL") return "flow";
        if(code.rfind("E_RESOURCE",0)==0||code.rfind("E_BORROW",0)==0||code=="E_REBORROW_KIND"||code=="E_PLACE"||code=="E_VIEW_ESCAPE"||code=="E_BYTES_LIMIT"||code=="E_TEXT_LIMIT") return "memory-resource";
        if(code.rfind("E_CAPABILITY",0)==0||code=="E_EFFECT"||code=="E_HOST_POLICY"||code=="E_AUTHORITY") return "capability";
        if(code=="E_WAVE"||code=="E_WIRE"||code=="E_VERSION"||code=="E_IR"||code=="E_ONME"||code=="E_OSNMF") return "representation";
        if(code=="E_FILE"||code=="E_EXISTS"||code=="E_CACHE"||code=="E_TOOL"||code=="E_BACKEND"||code=="E_TARGET_UNVALIDATED") return "toolchain";
        if(code=="E_OVERFLOW"||code=="E_OVERFLOW_LITERAL"||code=="E_CAST_RANGE"||code=="E_DIVZERO"||code=="E_BOUNDS"||code=="E_FUEL"||code=="E_DEPTH"||code=="E_OUTPUT_LIMIT"||code.rfind("E_CHANNEL_",0)==0||code=="E_DEADLINE"||code=="E_IO"||code=="E_MEMORY"||code=="E_BYTES_HANDLE"||code=="E_TEXT_HANDLE"||code.rfind("E_RUNTIME",0)==0||code.rfind("E_INVOCATION_",0)==0) return "runtime";
        if(code=="E_CLI"||code=="E_ENTRY"||code=="E_TEST"||code=="E_LIMIT"||code=="E_FORMAT"||code=="E_COVERAGE"||code=="E_HOST_ENTRY"||code=="E_BUDGET"||code=="E_EPOCH"||code=="E_QUERY"||code=="E_COGNITION") return "tooling";
        if(code=="E_TRY_CONTEXT"||code=="E_TRY_ORDER"||code=="E_TRY_POSITION") return "flow";
        if(code=="E_TRAIT_METHOD") return "types";
        if(code=="E_TRAIT_EFFECT") return "capability";
        if(code=="E_CLOSURE_CAPTURE") return "memory-resource";
        if(code=="E_CLOSURE"||code=="E_CLOSURE_RETURN"||code=="E_METHOD_RECEIVER") return "types";
        if(code=="E_PARTICLE") return "syntax";
        if(code=="E_CHAR_RANGE") return "runtime";
        if(code=="E_DURABILITY"||code.rfind("E_PACKAGE_",0)==0) return "toolchain";
        if(code=="E_HOST_SDK_SCHEMA"||code=="E_OMID_IDENTITY"||code.rfind("E_OMI_",0)==0) return "representation";
        // Generalizable target primitives; validation is recorded for this distribution.
        if(code=="E_ARRAY_OWNING_INDEX") return "memory-resource";
        if(code=="E_ATOMIC_ALIGN"||code=="E_TARGET_HALT") return "runtime";
        if(code=="E_ATOMIC_OP"||code=="E_ATOMIC_ORDER"||code=="E_THREAD_LOCAL"||code=="E_LAYOUT"||code=="E_SLOTS"||code=="E_OPAQUE"||code=="E_CONST"||code=="E_STATIC_ASSERT"||code=="E_TARGET"||code=="E_SIMD") return "types";
        if(code=="E_LINKAGE") return "toolchain";
        if(code=="E_SLOT_OCCUPIED"||code=="E_SLOT_STATE"||code=="E_RESOURCE_DOUBLE_RELEASE"||code=="E_RESOURCE_STALE_USE") return "runtime";   // owned slots (OWNED_SLOTS_CANDIDATE.md): faults of the typed slot buffers
        if(code=="E_EXCEPTION_HANDLER"||code=="E_SERVICE_BINDING"||code=="E_TARGET_PROFILE"||code=="E_THREAD_ENTRY") return "toolchain";
        return "internal";
    }
    std::string sourceUri(const std::string& source) {
        if(source.empty())return "";
        std::error_code ec;
        auto path=fs::weakly_canonical(fs::absolute(source),ec);
        if(ec)path=fs::absolute(source,ec);
        auto text=path.generic_string();
        std::ostringstream encoded;
        encoded<<"file://";
        for(const char raw:text) {
            const auto c=static_cast<unsigned char>(raw);
            if(std::isalnum(c)||c=='/'||c==':'||c=='-'||c=='_'||c=='.'||c=='~')encoded<<static_cast<char>(c);
            else encoded<<'%'<<std::uppercase<<std::hex<<std::setw(2)<<std::setfill('0')<<static_cast<unsigned>(c)<<std::nouppercase<<std::dec;
        }
        return encoded.str();
    }
    std::optional<size_t> diagnosticScalarColumn(const std::string& source,size_t line,size_t byteColumn) {
        // Loc is the Particle lexer's byte position. Render the promised scalar
        // coordinate without changing AST/representation identities. A decoded
        // representation's synthetic source location is not an original span.
        if(!line||!byteColumn||fs::path(source).extension()!=".omni")return std::nullopt;
        std::ifstream text(source,std::ios::binary);
        for(size_t n=1;n<line&&text;++n)text.ignore(std::numeric_limits<std::streamsize>::max(),'\n');
        size_t scalar=1;
        for(size_t n=1;n<byteColumn;++n) {
            const int raw=text.get();
            if(raw==std::char_traits<char>::eof()||raw=='\n')return std::nullopt;
            if((static_cast<unsigned>(raw)&0xc0u)!=0x80u)++scalar;
        }
        if(!text)return std::nullopt;
        const int next=text.peek();
        if(next!=std::char_traits<char>::eof()&&(static_cast<unsigned>(next)&0xc0u)==0x80u)return std::nullopt;
        return scalar;
    }
    std::string diagnosticJson(const Error& e,const std::string& fallbackSource) {
        const auto source=e.source.empty()?fallbackSource:e.source;
        const auto scalarColumn=diagnosticScalarColumn(source,e.line,e.column);
        std::ostringstream o;
        o<<"{\n  \"schema\": \"omni.diagnostic/1\",\n"
         <<"  \"severity\": \"error\",\n"
         <<"  \"category\": "<<quote(diagnosticCategory(e.code))<<",\n"
         <<"  \"code\": "<<quote(e.code)<<",\n"
         <<"  \"message\": "<<quote(e.what())<<",\n"
         <<"  \"source\": "<<quote(source)<<",\n"
         <<"  \"source_uri\": "<<quote(sourceUri(source))<<",\n"
         <<"  \"span\": ";
        if(scalarColumn)o<<"{\"line\": "<<e.line<<", \"column\": "<<*scalarColumn<<", \"coordinate\": \"unicode-scalar-1-based\"}";
        else o<<"null";
        if(e.semanticContext){
            const auto& context=*e.semanticContext;
            o<<",\n  \"symbol_id\": "<<(context.symbolId.empty()?"null":quote(context.symbolId))
             <<",\n  \"symbol\": "<<(context.symbol.empty()?"null":quote(context.symbol))
             <<",\n  \"owner\": "<<(context.owner.empty()?"null":quote(context.owner))
             <<",\n  \"place\": ";
            if(context.placeRoot<0)o<<"null";
            else{
                o<<"{\"root_binding\":"<<context.placeRoot<<",\"projections\":[";
                for(size_t i=0;i<context.projections.size();++i){if(i)o<<',';o<<context.projections[i];}
                o<<"]}";
            }
            o<<",\n  \"active_loan\": ";
            if(context.loanBinding<0)o<<"null";
            else o<<"{\"binding\":"<<context.loanBinding<<",\"origin_binding\":"<<context.loanOrigin
                  <<",\"kind\":"<<quote(context.loanKind)<<"}";
            o<<",\n  \"constraint\": "<<quote(context.constraint)<<",\n  \"required_fix_classes\": [";
            for(size_t i=0;i<context.fixClasses.size();++i){if(i)o<<',';o<<quote(context.fixClasses[i]);}
            o<<']';
            if(!context.requiredCapability.empty())o<<",\n  \"required_capability\": "<<quote(context.requiredCapability);
        }
        if(std::any_of(e.related.begin(),e.related.end(),[&](const auto& r){
            return diagnosticScalarColumn(r.loc.file.empty()?source:r.loc.file,r.loc.line,r.loc.column).has_value();
        })) {
            // CP-16: additive optional field; absent for diagnostics without a secondary location (output unchanged).
            o<<",\n  \"related\": [";
            bool first=true;
            for(const auto& r:e.related) {
                const auto relatedSource=r.loc.file.empty()?source:r.loc.file;
                const auto relatedColumn=diagnosticScalarColumn(relatedSource,r.loc.line,r.loc.column);
                if(!relatedColumn)continue;
                o<<(first?"":",")<<"\n    {\"role\": "<<quote(r.role)<<", \"note\": "<<quote(r.note)<<", \"source\": "<<quote(relatedSource)
                 <<", \"source_uri\": "<<quote(sourceUri(relatedSource))<<", \"span\": {\"line\": "<<r.loc.line<<", \"column\": "<<*relatedColumn
                 <<", \"coordinate\": \"unicode-scalar-1-based\"}}";
                first=false;
            }
            o<<"\n  ]";
        }
        bool exactProposal=false;
        if(!e.replacement.empty()&&e.line&&e.column&&fs::path(source).extension()==".omni") {
            // Synthetic locations and missing/changed source never invent an
            // edit range. Inspect only the proposed token without loading input.
            std::ifstream text(source,std::ios::binary);
            for(size_t line=1;line<e.line&&text;++line)text.ignore(std::numeric_limits<std::streamsize>::max(),'\n');
            for(size_t column=1;column<e.column&&text;++column) {
                const int c=text.get();
                if(c=='\n'||c==std::char_traits<char>::eof()){text.setstate(std::ios::failbit);break;}
            }
            exactProposal=static_cast<bool>(text);
            for(char raw:e.expected)if(text.get()!=static_cast<int>(static_cast<unsigned char>(raw)))exactProposal=false;
        }
        if(exactProposal) {
            o<<",\n  \"fixits\": [{\"source_uri\": "<<quote(sourceUri(source))
             <<", \"line\": "<<e.line<<", \"column\": "<<e.column
             <<", \"coordinate\": \"utf8-byte-1-based\", \"expected\": "<<quote(e.expected)
             <<", \"replacement\": "<<quote(e.replacement)<<"}]";
        }
        o<<"\n}\n";
        return o.str();
    }
    const std::vector<std::string>& stableDiagnosticCodes() {
        static const std::vector<std::string> codes={
            "E_ARITY","E_ARRAY_EMPTY","E_ARRAY_LENGTH","E_ASYNC_UNSUPPORTED","E_BACKEND","E_BORROW_CONFLICT","E_BORROW_ESCAPE","E_BORROW_EXPIRED","E_BOUNDS","E_BYTES_LIMIT","E_CACHE","E_CALL",
            "E_AUTHORITY","E_CAPABILITY","E_CAPABILITY_EXCESS","E_CAST_RANGE","E_CLI","E_COVERAGE","E_DEPTH","E_DIVZERO","E_DUPLICATE","E_EFFECT","E_ENTRY","E_EXISTS","E_FIELDS","E_FILE","E_FUEL","E_HOST_POLICY",
            "E_GENERIC_ARGS","E_GENERIC_CONSTRAINT","E_GENERIC_DECL","E_GENERIC_INTERNAL","E_GENERIC_TARGET","E_TRAIT","E_TRAIT_COHERENCE","E_IMMUTABLE","E_IMPORT","E_IMPORT_CYCLE","E_IMPORT_PATH","E_INDEX_TYPE","E_INTERNAL","E_IR","E_ITERABLE","E_LAYOUT_CYCLE","E_LEX","E_LIMIT","E_LOOP_CONTROL","E_MATCH","E_MATCH_BINDING","E_MATCH_DUPLICATE",
            "E_MATCH_NON_EXHAUSTIVE","E_MATCH_VARIANT","E_MODULE","E_NAME","E_NUMBER","E_ONME","E_PATTERN","E_PATTERN_ARITY","E_RANGE_TYPE","E_OSNMF","E_EPOCH","E_QUERY","E_COGNITION","E_FORMAT","E_OUTPUT_LIMIT","E_OVERFLOW","E_OVERFLOW_LITERAL","E_PARSE","E_PRODUCT_LINEAR",
            "E_PLACE","E_REBORROW_KIND","E_RESOURCE_ACCESS","E_RESOURCE_FLOW","E_RESOURCE_HANDLE","E_RESOURCE_LEAK","E_RESOURCE_MOVED","E_RESOURCE_MUTABLE","E_RESOURCE_TYPE","E_RESULT_FLOW","E_RESULT_MOVED",
            "E_RESULT_MUTABLE","E_RESULT_UNHANDLED","E_RETURN","E_STRING","E_TARGET_UNVALIDATED","E_TEST","E_TEXT_LIMIT","E_TOOL","E_TUPLE_INDEX","E_TYPE","E_UNDEFINED",
            "E_TASK_HANDLE","E_TASK_HANDLE_CONSUMED","E_TASK_HANDLE_ESCAPE","E_TASK_ORPHAN","E_TASK_SCOPE","E_TASK_TRANSFER",
            "E_CHANNEL_CAPACITY","E_CHANNEL_CLOSED","E_CHANNEL_HANDLE","E_CHANNEL_HANDLE_ESCAPE","E_CHANNEL_PROFILE","E_CHANNEL_TYPE","E_DEADLINE",
            "E_UNREACHABLE","E_UTF8","E_VERSION","E_VIEW_ESCAPE","E_VIEW_MUTABLE","E_VIEW_SOURCE","E_VISIBILITY","E_WAVE","E_WIRE",
            "E_CHAR_RANGE","E_CLOSURE","E_CLOSURE_CAPTURE","E_CLOSURE_RETURN","E_METHOD_RECEIVER","E_PARTICLE","E_DURABILITY","E_HOST_ENTRY","E_HOST_SDK_SCHEMA",
            "E_OMID_IDENTITY","E_OMI_LIMIT","E_OMI_MALFORMED","E_OMI_TYPE","E_OMI_VERSION",
            "E_PACKAGE_CYCLE","E_PACKAGE_LOCK","E_PACKAGE_MANIFEST","E_PACKAGE_OFFLINE","E_PACKAGE_PATH","E_PACKAGE_RESOLVE",
            "E_TRAIT_METHOD","E_TRAIT_EFFECT","E_TRY_CONTEXT","E_TRY_ORDER","E_TRY_POSITION",
            "E_ATOMIC_ALIGN","E_ATOMIC_OP","E_ATOMIC_ORDER","E_EXCEPTION_HANDLER","E_RESOURCE_PRIVATE","E_RESOURCE_UNCONSUMED",
            "E_SERVICE_BINDING","E_TARGET_HALT","E_TARGET_PROFILE","E_THREAD_ENTRY","E_THREAD_LOCAL","E_LAYOUT","E_ARRAY_OWNING_INDEX",
            "E_SLOTS","E_SLOT_OCCUPIED","E_SLOT_STATE","E_RESOURCE_DOUBLE_RELEASE","E_RESOURCE_STALE_USE","E_OPAQUE","E_CONST","E_STATIC_ASSERT","E_TARGET","E_LINKAGE","E_SIMD",
            // CP-16.2: producers that were outside the catalog: the resource budget (E_BUDGET), the driver's last-resort fault, and the faults of the C runtime of a compiled program
            "E_BUDGET","E_INTERNAL_OR_IO","E_BYTES_HANDLE","E_CHANNEL_OUT","E_INVOCATION_CANCELLED","E_INVOCATION_CLOCK","E_INVOCATION_DEADLINE","E_IO","E_MEMORY","E_RUNTIME","E_RUNTIME_CONTEXT",
            "E_RUNTIME_REENTRY","E_TEXT_HANDLE"
        };
        return codes;
    }
    void usage()  {
        std::cout<<"Omni Language "<<VERSION<<" (general-purpose alpha)\n"
        <<"  omni host-policy verify POLICY.ohp\n"
        <<"  omni host-policy allows POLICY.ohp CAPABILITY SUBJECT BYTES TICK GENERATION\n"
        <<"  omni package check|lock PACKAGE_ROOT [--offline]\n"
        <<"  omni sdk doctor\n"
        <<"  omni lsp --workspace DIRECTORY\n"
        <<"  omni check FILE [--deny-excess-capabilities] [--diagnostic-format text|json] [--bindings-json]\n"
        <<"  omni admit FILE    (static hypothetical snapshot: YES/NO, no execution or persistent output)\n"
        <<"  omni fmt FILE [--check|--write]\n  omni deps FILE\n  omni manifest FILE\n  omni hash FILE\n"
        <<"  omni wave FILE\n  omni inspect FILE\n  omni onme FILE [-o FILE.onme]\n  omni onme-stats FILE\n"
        <<"  omni memory FILE\n  omni memory-pack FILE -o FILE.omem\n  omni memory-summary FILE.omem\n  omni memory-query FILE.omem --entity NAME|--capability CAP|--kind KIND|--calls FUNCTION\n"
        <<"  omni memory-trace FILE.omem --entity NAME [--depth N]\n  omni memory-impact FILE.omem --entity NAME\n  omni memory-pulse CURRENT.omem --against PREVIOUS.omem\n"
        <<"  omni proposal FILE.omem --entity NAME --agent ID --note TEXT -o FILE.oprop\n  omni proposal-apply FILE.omem --proposal FILE.oprop --grant memory.write -o NEXT.omem\n  omni proposal-merge FILE.omem --proposal A.oprop --proposal B.oprop [...] --grant memory.write -o NEXT.omem\n"
        <<"  omni observe FILE [-o SNAPSHOT.omem] [--against PREVIOUS.omem]\n  omni graph FILE\n  omni summary FILE\n  omni trace FILE --entity NAME [--depth N]\n  omni impact FILE --entity NAME\n  omni pulse FILE [--against PREVIOUS]\n"
        <<"  omni query FILE --entity NAME|--capability CAP|--kind KIND|--calls FUNCTION\n  omni cognition FILE [--selector ENTITY|system]\n"
        <<"  omni synapse-scale FILE --entity ARCHETYPE --instances N [--overrides N]\n"
        <<"  omni cognition-offload FILE [--selector ENTITY|system] --provider ID --grant external.egress --max-input-tokens N --max-output-tokens N --max-cost-microunits N --max-latency-ms N -o REQUEST.ocap\n"
        <<"  omni cognition-offload-run REQUEST.ocap\n"
        <<"  omni pack FILE -o FILE.owire\n  omni unpack FILE.owire\n  omni emit-llvm FILE [-o FILE.ll]\n  omni eval FILE [--host-policy POLICY.ohp]\n  omni test FILE\n"
        <<"  omni profile FILE [-o REPORT.json] [--host-policy POLICY.ohp]\n  omni coverage FILE [-o REPORT.json] [--host-policy POLICY.ohp]\n"
        <<"  omni build FILE -o EXECUTABLE [--opt 0|2] [--force] [--no-cache] [--cache-dir DIR]     (ordinary executable build; FILE needs main)\n"
        <<"  omni build PACKAGE_ROOT --host-entry MODULE:FUNCTION -o ARTIFACT.so --offline           (host-entry build; loadable module, no main)\n"
        <<"  omni run FILE [--opt 0|2] [--no-cache] [--cache-dir DIR] [--host-policy POLICY.ohp]\n"
        <<"  omni cache stats|clear [--cache-dir DIR]\n  omni type describe TYPE\n  omni type layout TYPE\n  omni doctor [--json]\n"
        <<"  omni target list|probe --json\n"
        <<"  omni context --target TARGET --for llm [--target-isa gpr|sse2]\n"
        <<"  omni component FILE [--target-profile PROFILE] [--target-isa gpr|sse2] [--diagnostic-format text|json]\n"
        <<"Input: .omni / .owave / .owire / .onme. OSNMF and ONME are Core representations; cognition is optional.\n"
        <<"Native target currently tested: Linux x86-64 + Clang. ECU remains a separate frozen profile.\n";
    }
}
static int omniMain(int argc,char** argv)  {
    std::string cmd=argc>1?argv[1]:"help",input;
    const bool admissionMode=cmd=="admit";
    if(admissionMode)cmd="check";
    bool diagnosticJsonMode=false;
    try  {
        if(cmd=="help"||cmd=="--help"||cmd=="-h")  {
            usage();
            return 0;
        }
        if(cmd=="--version"||cmd=="version")  {
            std::cout<<"omni "<<VERSION<<"\n";
            return 0;
        }
        if(cmd=="context"){
            std::string target,purpose,isa="gpr";bool isaGiven=false;
            for(int i=2;i<argc;++i){
                const std::string option=argv[i];
                if((option!="--target"&&option!="--for"&&option!="--target-isa")||i+1>=argc)
                    fail("E_CLI","uso: omni context --target TARGET --for llm [--target-isa gpr|sse2]");
                const std::string value=argv[++i];
                if(option=="--target"){if(!target.empty())fail("E_CLI","target duplicado");target=value;}
                else if(option=="--for"){if(!purpose.empty())fail("E_CLI","proposito duplicado");purpose=value;}
                else{if(isaGiven)fail("E_CLI","ISA duplicada");isaGiven=true;isa=value;}
            }
            if(target.empty()||purpose!="llm")fail("E_CLI","context requiere --target TARGET --for llm");
            if(target!=TARGET_ID&&target!="baremetal-x86_64"&&target!="baremetal-i386-boot")
                fail("E_TARGET_UNVALIDATED","contexto de target no admitido: "+target);
            if((isa!="gpr"&&isa!="sse2")||(isaGiven&&target==TARGET_ID)||(target=="baremetal-i386-boot"&&isa=="sse2"))
                fail("E_TARGET_PROFILE","ISA no admitida por el perfil del contexto");
            setTargetFacts(factsForProfile(target==TARGET_ID?"":target,isa));
            std::cout<<targetContextJson(root(argv[0]),target);return 0;
        }
        if(cmd=="target") {
            if(argc!=4||std::string(argv[3])!="--json")fail("E_CLI","uso: omni target list|probe --json");
            const std::string action=argv[2];
            if(action=="list"){std::cout<<targetMatrixJson();return 0;}
            if(action=="probe"){std::cout<<targetProbeJson();return 0;}
            fail("E_CLI","accion target desconocida: "+action);
        }
        if(cmd=="diagnostics") {
            std::cout<<"{\n  \"schema\": \"omni.diagnostics-registry/1\",\n  \"codes\": [";
            bool first=true; for(const auto& code:stableDiagnosticCodes()){ if(!first)std::cout<<","; first=false; std::cout<<"{\"code\":"<<quote(code)<<",\"category\":"<<quote(diagnosticCategory(code))<<"}"; }
            std::cout<<"]\n}\n"; return 0;
        }
        if(cmd=="type") {
            if(argc==4&&std::string(argv[2])=="describe") { std::cout<<typeDescriptorJson(parseType(argv[3])); return 0; }
            if(argc==4&&std::string(argv[2])=="layout") { std::cout<<layoutDescriptorJson(parseType(argv[3])); return 0; }
            fail("E_CLI","uso: omni type describe|layout TYPE");
        }
        if(cmd=="failures") {
            std::cout<<"{\n  \"schema\": \"omni.failure/1\",\n  \"kinds\": ["; bool first=true;
            for(auto k:{FailureKind::CompileError,FailureKind::ValidationError,FailureKind::CapabilityDenied,FailureKind::DeadlineExceeded,FailureKind::Cancelled,FailureKind::ResourceExhausted,FailureKind::Trap}){if(!first)std::cout<<",";first=false;std::cout<<"{\"name\":"<<quote(failureName(k))<<",\"code\":"<<(int)k<<"}";} std::cout<<"]\n}\n"; return 0;
        }
        if(cmd=="capability") {
            if(argc==3&&std::string(argv[2])=="registry") { std::cout<<capabilityRegistryJson(); return 0; }
            fail("E_CLI","uso: omni capability registry");
        }
        if(cmd=="host-policy") {
            if(argc==4&&std::string(argv[2])=="verify") {
                const auto policy=parseHostPolicy(readUtf8TextBounded(argv[3],65536u));
                std::cout<<hostPolicySummaryJson(policy); return 0;
            }
            if(argc==9&&std::string(argv[2])=="allows") {
                auto parseNumber=[](const char* raw){
                    uint64_t value=0; const std::string text(raw);
                    const auto parsed=std::from_chars(text.data(),text.data()+text.size(),value);
                    if(parsed.ec!=std::errc()||parsed.ptr!=text.data()+text.size())fail("E_CLI","numero host-policy invalido");
                    return value;
                };
                const auto policy=parseHostPolicy(readUtf8TextBounded(argv[3],65536u));
                const bool allowed=policy.allows(argv[4],argv[5],parseNumber(argv[6]),parseNumber(argv[7]),parseNumber(argv[8]));
                std::cout<<"{\n  \"schema\": \"omni.host-authority-decision/1\",\n  \"allowed\": "<<(allowed?"true":"false")<<"\n}\n";
                return 0;
            }
            fail("E_CLI","uso: omni host-policy verify POLICY.ohp | allows POLICY.ohp CAPABILITY SUBJECT BYTES TICK GENERATION");
        }
        if(cmd=="package") {
            if(argc<4)fail("E_CLI","uso: omni package check|lock PACKAGE_ROOT [--offline]");
            const std::string action=argv[2]; const fs::path packageRoot=argv[3];
            bool offline=false;
            for(int i=4;i<argc;++i) { const std::string arg=argv[i]; if(arg=="--offline") offline=true; else fail("E_CLI","opcion package desconocida: "+arg); }
            if(action!="check"&&action!="lock")fail("E_CLI","accion package desconocida: "+action);
            std::cout<<packageCommand(action,packageRoot,offline,
                                      bundledStandardLibrary(root(argv[0]))); return 0;
        }
        if(cmd=="sdk") {
            if(argc!=3||std::string(argv[2])!="doctor")fail("E_CLI","uso: omni sdk doctor");
            const auto sdkRoot=root(argv[0]); const auto script=sdkRoot/"tools/omni_sdk_doctor.py";
            if(!fs::is_regular_file(script)||fs::is_symlink(script))fail("E_TOOL","SDK doctor no disponible");
            return launch({"python3","-B",script.string(),"--sdk-root",sdkRoot.string()});
        }
        std::string clang=std::getenv("OMNI_CLANG")?std::getenv("OMNI_CLANG"):"clang";
        auto rt=root(argv[0])/"runtime/omni_runtime.c";
        if(cmd=="lsp") {
            if(argc!=4||std::string(argv[2])!="--workspace")fail("E_CLI","uso: omni lsp --workspace DIRECTORY");
            const fs::path workspace=fs::weakly_canonical(fs::absolute(argv[3]));
            if(!fs::is_directory(workspace)||fs::is_symlink(workspace))fail("E_FILE","workspace LSP debe ser directorio regular");
            const auto script=root(argv[0])/"tools/omni_lsp.py";
            if(!fs::is_regular_file(script)||fs::is_symlink(script))fail("E_TOOL","servidor LSP no disponible");
            return launch({"python3","-B",script.string(),"--compiler",fs::absolute(argv[0]).string(),"--workspace",workspace.string()});
        }
        if(cmd=="doctor")  {
            if(argc>3||(argc==3&&std::string(argv[2])!="--json"))fail("E_CLI","uso: omni doctor [--json]");
            const bool json=argc==3;
            auto probe=[&](const std::vector<std::string>& command){try{const auto result=runObserved(command);return std::make_pair(result.exitCode==0,result.output);}catch(const Error&){return std::make_pair(false,std::string());}};
            const auto backend=probe({clang,"--version"});const auto python=probe({"python3","--version"});const bool runtime=fs::is_regular_file(rt)&&!fs::is_symlink(rt);
            if(json){
                std::cout<<"{\n  \"schema\": \"omni.doctor/1\",\n  \"language_version\": "<<quote(VERSION)<<",\n"
                         <<"  \"target_profile\": \"linux-x86_64-gnu\",\n"
                         <<"  \"runtime\": {\"status\": \""<<(runtime?"PASS":"MISSING")<<"\", \"sha256\": "<<(runtime?quote(sha256File(rt)):"null")<<"},\n"
                         <<"  \"backend\": {\"status\": \""<<(backend.first?"PASS":"MISSING")<<"\", \"identity_sha256\": "<<(backend.first?quote(sha256(backend.second)):"null")<<"},\n"
                         <<"  \"python_lsp\": {\"status\": \""<<(python.first?"PASS":"MISSING")<<"\", \"identity_sha256\": "<<(python.first?quote(sha256(python.second)):"null")<<"},\n"
                         <<"  \"status\": \""<<(runtime&&backend.first&&python.first?"PASS":"ACTION_REQUIRED")<<"\",\n"
                         <<"  \"actions\": [";bool first=true;if(!runtime){std::cout<<quote("install the governed Omni runtime payload");first=false;}if(!backend.first){if(!first)std::cout<<',';std::cout<<quote("install a compatible clang backend");first=false;}if(!python.first){if(!first)std::cout<<',';std::cout<<quote("install Python 3 for the A87 LSP profile");}std::cout<<"]\n}\n";
            } else {
                std::cout<<"Omni "<<VERSION<<"\nRuntime: "<<(runtime?"PASS":"MISSING")<<"\nBackend: "<<(backend.first?"PASS":"MISSING")<<"\nPython LSP: "<<(python.first?"PASS":"MISSING")<<"\n";
            }
            return runtime&&backend.first&&python.first?0:2;
        }
        if(cmd=="cache") {
            if(argc<3)fail("E_CLI","cache requiere stats o clear");
            std::string action=argv[2]; fs::path cacheRoot=defaultCacheDir();
            for(int i=3;i<argc;i++){
                std::string a=argv[i];
                if(a=="--cache-dir"&&i+1<argc)cacheRoot=fs::absolute(argv[++i]);
                else fail("E_CLI","opcion cache desconocida/incompleta: "+a);
            }
            auto buildRoot=cacheRoot/"build-v1";
            if(action=="clear"){
                std::error_code ec; auto n=fs::remove_all(buildRoot,ec); if(ec)fail("E_CACHE","no se pudo limpiar cache: "+ec.message());
                std::cout<<"Cache build-v1 limpiada: "<<n<<" entradas filesystem\n"; return 0;
            }
            if(action=="stats"){
                uint64_t files=0,bytes=0,entries=0; std::error_code ec;
                if(fs::exists(buildRoot,ec)){
                    for(auto&d:fs::directory_iterator(buildRoot,ec))if(d.is_directory()){ entries++; for(auto&f:fs::directory_iterator(d.path(),ec))if(f.is_regular_file()){files++;bytes+=f.file_size();} }
                }
                if(ec)fail("E_CACHE","no se pudo inspeccionar cache: "+ec.message());
                std::cout<<"{\n  \"schema\": \"omni.cache-stats/1\",\n  \"root\": "<<quote(cacheRoot.string())<<",\n  \"entries\": "<<entries<<",\n  \"files\": "<<files<<",\n  \"bytes\": "<<bytes<<"\n}\n"; return 0;
            }
            fail("E_CLI","accion cache desconocida: "+action);
        }
        const std::set<std::string> commands=  {
            "component","capabilities","deps","manifest","hash","check","fmt","wave","inspect","onme","onme-stats","memory","memory-pack","memory-summary","memory-query","memory-trace","memory-impact","memory-pulse","proposal","proposal-apply","proposal-merge","observe","graph","summary","trace","impact","pulse","query","cognition","synapse-scale","cognition-offload","cognition-offload-run","pack","unpack","emit-llvm","eval","test","profile","coverage","build","run"
        };
        if(!commands.count(cmd))fail("E_CLI","comando desconocido: "+cmd);
        if(argc<3)fail("E_CLI","falta archivo de entrada");
        input=argv[2];
        fs::path out,cacheRoot=defaultCacheDir(),hostPolicyPath;
        std::string hostEntry;
        bool hostOffline=false,explicitOpt=false,explicitRuntime=false;
        std::string opt="0";
        bool force=false,useCache=true,explainCaps=false,denyExcess=false,formatCheck=false,formatWrite=false,bindingsJson=false;
        std::string against,queryMode,queryValue,selector="system",agent,note,provider,targetProfile,serviceModule,entrySection,exceptionHandler,threadEntry; bool exceptionResume=false,ring3Support=false,exceptionSaveFpu=false,targetIsaGiven=false; std::string targetIsa="gpr"; uint32_t isrExtraVector=0,isrCount=32; uint64_t entryAddress=0,entryStack=0,entryHandoff=0; uint32_t depth=4; uint64_t instances=0,overrides=0; CognitiveBudget cognitiveBudget; std::set<std::string> grants; std::vector<std::string> proposalPaths;
        for(int i=3; i<argc; i++)  {
            std::string a=argv[i];
            if((a=="-o"||a=="--opt"||a=="--runtime"||a=="--cache-dir"||a=="--host-policy"||a=="--host-entry")&&i+1<argc)  {
                auto v=std::string(argv[++i]);
                if(a=="-o")out=v;
                else if(a=="--opt"){opt=v;explicitOpt=true;}
                else if(a=="--runtime"){rt=v;explicitRuntime=true;}
                else if(a=="--cache-dir")cacheRoot=fs::absolute(v);
                else if(a=="--host-entry")hostEntry=v;
                else hostPolicyPath=fs::absolute(v);
            }
            else if(a=="--offline")hostOffline=true;
            else if(a=="--force")force=true;
            else if(a=="--check")formatCheck=true;
            else if(a=="--write")formatWrite=true;
            else if(a=="--no-cache")useCache=false;
            else if(a=="--explain")explainCaps=true;
            else if(a=="--deny-excess-capabilities")denyExcess=true;
            else if(a=="--diagnostic-format"&&i+1<argc) { auto v=std::string(argv[++i]); if(v=="json")diagnosticJsonMode=true; else if(v!="text")fail("E_CLI","--diagnostic-format debe ser text o json"); }
            else if(a=="--bindings-json") bindingsJson=true;
            else if(a=="--against"&&i+1<argc) against=argv[++i];
            else if((a=="--entity"||a=="--capability"||a=="--kind"||a=="--calls")&&i+1<argc) { queryMode=a.substr(2); queryValue=argv[++i]; }
            else if(a=="--depth"&&i+1<argc) { try { const auto v=std::stoul(argv[++i]); if(v>16u)fail("E_QUERY","--depth maximo 16"); depth=static_cast<uint32_t>(v); } catch(const Error&) { throw; } catch(...) { fail("E_CLI","--depth invalido"); } }
            else if(a=="--selector"&&i+1<argc) selector=argv[++i];
            else if(a=="--agent"&&i+1<argc) agent=argv[++i];
            else if(a=="--note"&&i+1<argc) note=argv[++i];
            else if(a=="--proposal"&&i+1<argc) proposalPaths.push_back(argv[++i]);
            else if(a=="--grant"&&i+1<argc) grants.insert(canonicalCapability(argv[++i]));
            else if(a=="--provider"&&i+1<argc) provider=argv[++i];
            else if(a=="--target-profile"&&i+1<argc) targetProfile=argv[++i];
            else if(a=="--service-module"&&i+1<argc) serviceModule=argv[++i];
            else if(a=="--entry-section"&&i+1<argc) entrySection=argv[++i];
            else if(a=="--exception-handler"&&i+1<argc) exceptionHandler=argv[++i];
            else if(a=="--exception-resume") exceptionResume=true;
            else if(a=="--ring3-support") ring3Support=true;
            else if(a=="--exception-save-fpu") exceptionSaveFpu=true;
            else if(a=="--target-isa"&&i+1<argc) { targetIsa=argv[++i]; targetIsaGiven=true; }
            else if(a=="--thread-entry"&&i+1<argc) threadEntry=argv[++i];
            else if(a=="--isr-count"&&i+1<argc) { auto raw=std::string(argv[++i]); try { size_t used=0; auto v=std::stoul(raw,&used); if(used!=raw.size()||v<32||v>128)fail("E_CLI","--isr-count invalido (32..128)"); isrCount=static_cast<uint32_t>(v); } catch(const Error&) { throw; } catch(...) { fail("E_CLI","--isr-count invalido"); } }
            else if(a=="--isr-extra-vector"&&i+1<argc) { auto raw=std::string(argv[++i]); try { size_t used=0; auto v=std::stoul(raw,&used); if(used!=raw.size()||v<32||v>255)fail("E_CLI","--isr-extra-vector invalido (32..255)"); isrExtraVector=static_cast<uint32_t>(v); } catch(const Error&) { throw; } catch(...) { fail("E_CLI","--isr-extra-vector invalido"); } }
            else if(a=="--entry-handoff-store"&&i+1<argc) { try { size_t used=0; auto raw=std::string(argv[++i]); entryHandoff=std::stoull(raw,&used); if(used!=raw.size()||entryHandoff==0||entryHandoff>4294967295ull)fail("E_CLI","--entry-handoff-store invalido"); } catch(const Error&) { throw; } catch(...) { fail("E_CLI","--entry-handoff-store invalido"); } }
            else if(a=="--entry-stack"&&i+1<argc) { try { size_t used=0; auto raw=std::string(argv[++i]); entryStack=std::stoull(raw,&used); if(used!=raw.size())fail("E_CLI","--entry-stack invalido"); } catch(const Error&) { throw; } catch(...) { fail("E_CLI","--entry-stack invalido"); } }
            else if(a=="--entry-address"&&i+1<argc) { try { size_t used=0; auto raw=std::string(argv[++i]); entryAddress=std::stoull(raw,&used); if(used!=raw.size())fail("E_CLI","--entry-address invalido"); } catch(const Error&) { throw; } catch(...) { fail("E_CLI","--entry-address invalido"); } }
            else if((a=="--instances"||a=="--overrides"||a=="--max-input-tokens"||a=="--max-output-tokens"||a=="--max-cost-microunits"||a=="--max-latency-ms")&&i+1<argc) {
                uint64_t v=0; try { size_t used=0; auto raw=std::string(argv[++i]); auto parsed=std::stoull(raw,&used); if(used!=raw.size())fail("E_CLI","valor numerico invalido"); v=static_cast<uint64_t>(parsed); } catch(const Error&) { throw; } catch(...) { fail("E_CLI","valor numerico invalido"); }
                if(a=="--instances")instances=v; else if(a=="--overrides")overrides=v; else if(a=="--max-input-tokens")cognitiveBudget.maxInputTokens=v; else if(a=="--max-output-tokens")cognitiveBudget.maxOutputTokens=v; else if(a=="--max-cost-microunits")cognitiveBudget.maxCostMicrounits=v; else cognitiveBudget.maxLatencyMs=v;
            }
            else fail("E_CLI","opcion desconocida/incompleta: "+a);
        }
        if(opt!="0"&&opt!="2")fail("E_CLI","opt debe ser 0 o 2");
        if(!hostEntry.empty()) {
            if(cmd!="build"||!hostOffline||out.empty()||explicitOpt||explicitRuntime||
               cacheRoot!=defaultCacheDir())
                fail("E_CLI","host-entry requires build PACKAGE_ROOT --offline -o ARTIFACT.so with fixed profile");
            buildHostInvocation(input,hostEntry,out,root(argv[0]),force);
            return 0;
        }
        if(hostOffline)fail("E_CLI","--offline requires --host-entry for build");
        if((formatCheck||formatWrite)&&cmd!="fmt")fail("E_CLI","--check/--write solo validos para fmt");
        if(formatCheck&&formatWrite)fail("E_CLI","fmt admite --check o --write, no ambos");
        if(!out.empty()&&cmd!="build"&&cmd!="pack"&&cmd!="emit-llvm"&&cmd!="onme"&&cmd!="memory-pack"&&cmd!="observe"&&cmd!="proposal"&&cmd!="proposal-apply"&&cmd!="proposal-merge"&&cmd!="cognition-offload"&&cmd!="profile"&&cmd!="coverage")fail("E_CLI","-o no soportado para este comando");
        if((!useCache||cacheRoot!=defaultCacheDir())&&cmd!="build"&&cmd!="run")fail("E_CLI","opciones de cache solo validas para build/run");
        if(explainCaps&&cmd!="capabilities")fail("E_CLI","--explain solo valido para capabilities");
        if(denyExcess&&cmd!="check")fail("E_CLI","--deny-excess-capabilities solo valido para check");
        if(diagnosticJsonMode&&cmd!="check"&&cmd!="component")fail("E_CLI","--diagnostic-format solo valido para check/component");
        if(bindingsJson&&(cmd!="check"||admissionMode))fail("E_CLI","--bindings-json solo valido para check");
        if(!against.empty()&&cmd!="pulse"&&cmd!="observe"&&cmd!="memory-pulse")fail("E_CLI","--against solo valido para pulse/observe/memory-pulse");
        if(cmd=="memory-pulse"&&against.empty())fail("E_CLI","memory-pulse requiere --against PREVIOUS.omem");
        const bool queryCommand=cmd=="query"||cmd=="memory-query"||cmd=="trace"||cmd=="memory-trace"||cmd=="impact"||cmd=="memory-impact"||cmd=="proposal"||cmd=="synapse-scale";
        if((!queryMode.empty()||!queryValue.empty())&&!queryCommand)fail("E_CLI","opciones de query no validas para este comando");
        if(queryCommand&&(queryMode.empty()||queryValue.empty()))fail("E_CLI","comando requiere selector de query");
        if((cmd=="trace"||cmd=="memory-trace"||cmd=="impact"||cmd=="memory-impact"||cmd=="proposal"||cmd=="synapse-scale")&&queryMode!="entity")fail("E_CLI","trace/impact/proposal requieren --entity VALUE");
        if(depth!=4u&&cmd!="trace"&&cmd!="memory-trace")fail("E_CLI","--depth solo valido para trace/memory-trace");
        if(selector!="system"&&cmd!="cognition"&&cmd!="cognition-offload")fail("E_CLI","--selector solo valido para cognition/cognition-offload");
        if((!agent.empty()||!note.empty())&&cmd!="proposal")fail("E_CLI","--agent/--note solo validos para proposal");
        if(!proposalPaths.empty()&&cmd!="proposal-apply"&&cmd!="proposal-merge")fail("E_CLI","--proposal solo valido para proposal-apply/proposal-merge");
        if(!grants.empty()&&cmd!="proposal-apply"&&cmd!="proposal-merge"&&cmd!="cognition-offload")fail("E_CLI","--grant no valido para este comando");
        if(cmd=="proposal"&&(agent.empty()||note.empty()||out.empty()))fail("E_CLI","proposal requiere --entity, --agent, --note y -o");
        if(cmd=="proposal-apply"&&(proposalPaths.size()!=1u||out.empty()))fail("E_CLI","proposal-apply requiere exactamente un --proposal y -o");
        if(cmd=="proposal-merge"&&(proposalPaths.size()<2u||out.empty()))fail("E_CLI","proposal-merge requiere al menos dos --proposal y -o");
        if(cmd=="synapse-scale"&&instances==0)fail("E_CLI","synapse-scale requiere --instances N");
        const bool anyCognitiveBudget=cognitiveBudget.maxInputTokens||cognitiveBudget.maxOutputTokens||cognitiveBudget.maxCostMicrounits||cognitiveBudget.maxLatencyMs;
        if(exceptionResume&&exceptionHandler.empty())fail("E_CLI","--exception-resume requiere --exception-handler");
        if(targetIsaGiven&&targetIsa!="gpr"&&targetIsa!="sse2")fail("E_CLI","--target-isa invalido (gpr|sse2)");
        if(exceptionSaveFpu&&!exceptionResume)fail("E_CLI","--exception-save-fpu requiere --exception-resume");
        if(((targetIsaGiven&&cmd!="component")||exceptionSaveFpu)&&cmd!="emit-llvm")fail("E_CLI","--target-isa/--exception-save-fpu no admitidos por este comando");
        if((targetIsaGiven||exceptionSaveFpu)&&targetProfile.empty())fail("E_CLI","--target-isa/--exception-save-fpu requieren --target-profile");
        if(!targetProfile.empty()&&cmd!="emit-llvm"&&cmd!="component")fail("E_CLI","--target-profile solo valido para emit-llvm/component");
        if((!serviceModule.empty()||!entrySection.empty()||entryAddress!=0||entryStack!=0||entryHandoff!=0||!exceptionHandler.empty()||exceptionResume||ring3Support||isrExtraVector!=0||isrCount!=32||!threadEntry.empty())&&cmd!="emit-llvm")fail("E_CLI","opciones del emisor solo validas para emit-llvm");
        if(cmd=="component"&&(!targetProfile.empty()&&targetProfile!="baremetal-x86_64"&&targetProfile!="baremetal-i386-boot"))fail("E_TARGET_PROFILE","perfil de componente no admitido");
        if(cmd=="component"&&targetProfile=="baremetal-i386-boot"&&targetIsa=="sse2")fail("E_TARGET_PROFILE","i386 bootstrap no admite SSE2");
        if(cmd=="emit-llvm"&&targetProfile.empty()&&(!serviceModule.empty()||!entrySection.empty()))fail("E_CLI","--service-module/--entry-section requieren --target-profile");
        if((!provider.empty()||anyCognitiveBudget)&&cmd!="cognition-offload")fail("E_CLI","provider/budget solo validos para cognition-offload");
        if(cmd=="cognition-offload"&&(provider.empty()||out.empty()))fail("E_CLI","cognition-offload requiere --provider y -o");
        if((instances||overrides)&&cmd!="synapse-scale")fail("E_CLI","--instances/--overrides solo validos para synapse-scale");
        if(!hostPolicyPath.empty()&&cmd!="eval"&&cmd!="run"&&cmd!="observe"&&cmd!="profile"&&cmd!="coverage")fail("E_CLI","--host-policy solo valido para eval/run/observe/profile/coverage");
        std::optional<HostPolicy> hostPolicy;
        if(!hostPolicyPath.empty())hostPolicy=parseHostPolicy(readUtf8TextBounded(hostPolicyPath,65536u));
        if(!out.empty()&&fs::weakly_canonical(fs::absolute(input))==fs::weakly_canonical(fs::absolute(out)))fail("E_FILE","no se permite sobrescribir la fuente");
        if(cmd=="cognition-offload-run") { const auto envelope=parseCognitiveOffloadEnvelope(readUtf8Text(input)); std::cout<<runCognitiveOffloadAdapterJson(envelope); return 0; }
        if((cmd=="cognition"||cmd=="cognition-offload")&&fs::path(input).extension()==".omem") {
            maybeRecoverSnapshotPublication(input);validateFullSnapshotPublication(input);
            const auto stored=parseSystemMemoryStore(readUtf8Text(input));
            if(cmd=="cognition") { std::cout<<cognitiveProjectionJson(stored,selector); return 0; }
            if(fs::exists(out)&&!force)fail("E_EXISTS","OCAP envelope existente; use --force");
            if(fs::is_symlink(out)||fs::is_directory(out))fail("E_FILE","salida OCAP no regular");
            const auto envelope=makeCognitiveOffloadEnvelope(stored,selector,provider,cognitiveBudget,grants);
            write(out,serializeCognitiveOffloadEnvelope(envelope)); std::cout<<cognitiveOffloadSummaryJson(envelope); return 0;
        }
        if(cmd=="memory-summary"||cmd=="memory-query"||cmd=="memory-trace"||cmd=="memory-impact"||cmd=="memory-pulse"||cmd=="proposal"||cmd=="proposal-apply"||cmd=="proposal-merge") {
            maybeRecoverSnapshotPublication(input);
            if(cmd=="memory-pulse") { maybeRecoverSnapshotPublication(against);validateFullSnapshotPublication(input);validateFullSnapshotPublication(against);const auto current=parseSystemMemoryStore(readUtf8Text(input)); const auto previous=parseSystemMemoryStore(readUtf8Text(against)); std::cout<<neuralPulseJson(current,&previous); return 0; }
            if(cmd=="memory-trace"||cmd=="memory-impact") { const fs::path idxPath=fs::path(input).string()+".idx"; if(fs::is_regular_file(idxPath)&&!fs::is_symlink(idxPath)){const auto idxText=readUtf8Text(idxPath);if(idxText.rfind("OSMI2\n",0)==0){if(cmd=="memory-trace")std::cout<<traceSystemMemoryIndexedFileJson(input,idxText,queryValue,depth);else std::cout<<impactSystemMemoryIndexedFileJson(input,idxText,queryValue);return 0;}if(idxText.rfind("OSMI1\n",0)!=0)fail("E_VERSION","OSNMF index sidecar version no soportada");} validateFullSnapshotPublication(input);const auto stored=parseSystemMemoryStore(readUtf8Text(input)); if(cmd=="memory-trace")std::cout<<traceSystemMemoryJson(stored,queryValue,depth);else std::cout<<impactSystemMemoryJson(stored,queryValue);return 0; }
            if(cmd=="proposal") { validateFullSnapshotPublication(input);const auto stored=parseSystemMemoryStore(readUtf8Text(input)); const auto proposal=makeCognitiveProposal(stored,queryValue,agent,note); if(fs::exists(out)&&!force)fail("E_EXISTS","proposal existente; use --force"); if(fs::is_symlink(out)||fs::is_directory(out))fail("E_FILE","salida proposal no regular"); write(out,serializeCognitiveProposal(proposal)); std::cout<<cognitiveProposalSummaryJson(proposal); return 0; }
            if(cmd=="proposal-apply") { validateFullSnapshotPublication(input);const auto stored=parseSystemMemoryStore(readUtf8Text(input)); const auto proposal=parseCognitiveProposal(readUtf8TextBounded(proposalPaths.front(),65536u)); const auto next=applyCognitiveProposal(stored,proposal,grants); const auto text=systemMemoryStore(next);publishSnapshot(out,text,force); std::cout<<"{\n  \"schema\": \"omni.cognitive-commit/1\",\n  \"proposal_id\": "<<quote(proposal.id)<<",\n  \"base_epoch\": "<<quote(stored.epoch.id)<<",\n  \"epoch\": "<<quote(next.epoch.id)<<",\n  \"epoch_sequence\": "<<next.epoch.sequence<<",\n  \"authority_gate\": \"memory.write\",\n  \"semantic_authority\": \"ai-inferred\",\n  \"executable_mutation\": false,\n  \"pulse_generated\": true\n}\n"; return 0; }
            if(cmd=="proposal-merge") { validateFullSnapshotPublication(input);const auto stored=parseSystemMemoryStore(readUtf8Text(input)); std::vector<CognitiveProposal> proposals; proposals.reserve(proposalPaths.size()); std::set<std::string> agents; for(const auto& path:proposalPaths){auto proposal=parseCognitiveProposal(readUtf8TextBounded(path,65536u));agents.insert(proposal.agent);proposals.push_back(std::move(proposal));} const auto next=applyCognitiveProposalBatch(stored,proposals,grants); const auto text=systemMemoryStore(next);publishSnapshot(out,text,force);std::cout<<"{\n  \"schema\": \"omni.cognitive-merge/1\",\n  \"proposal_count\": "<<proposals.size()<<",\n  \"agent_count\": "<<agents.size()<<",\n  \"base_epoch\": "<<quote(stored.epoch.id)<<",\n  \"epoch\": "<<quote(next.epoch.id)<<",\n  \"epoch_sequence\": "<<next.epoch.sequence<<",\n  \"conflict_detection\": \"deterministic\",\n  \"consensus_is_truth\": false,\n  \"authority_gate\": \"memory.write\",\n  \"transactional_publication\": true\n}\n"; return 0; }
            if(cmd=="memory-query") { const fs::path idxPath=fs::path(input).string()+".idx"; if(fs::is_regular_file(idxPath)&&!fs::is_symlink(idxPath)){const auto idxText=readUtf8Text(idxPath);if(idxText.rfind("OSMI2\n",0)==0){std::cout<<querySystemMemoryIndexedFileJson(input,idxText,queryMode,queryValue);return 0;}if(idxText.rfind("OSMI1\n",0)!=0)fail("E_VERSION","OSNMF index sidecar version no soportada");} }
            validateFullSnapshotPublication(input);const auto stored=parseSystemMemoryStore(readUtf8Text(input)); if(cmd=="memory-summary")std::cout<<systemMemorySummaryJson(stored);else std::cout<<querySystemMemoryJson(stored,queryMode,queryValue); return 0;
        }
        setTargetFacts(factsForProfile(targetProfile,targetIsa));
        auto p=load(input,bundledStandardLibrary(root(argv[0])));
        if(!out.empty())for(auto& source:p.sources) {
            std::error_code ec;
            bool same=fs::exists(out)&&fs::equivalent(out,source,ec);
            if(same||fs::weakly_canonical(fs::absolute(out))==source)fail("E_FILE","no se permite sobrescribir un archivo del proyecto");
        }
        if(cmd=="capabilities") { std::cout<<capabilitiesJson(p,explainCaps); return 0; }
        if(cmd=="deps")  {
            std::cout<<"{\n  \"entry\": "<<quote(p.module)<<",\n  \"build_mode\": \"whole-program\",\n  \"build_cache\": \"content-addressed-v1\",\n  \"modules\": [";
            for(size_t j=0; j<p.modules.size(); j++) {
                auto& m=p.modules[j];
                if(j)std::cout<<",";
                std::cout<<"\n    {\"name\": "<<quote(m.name)<<", \"imports\": [";
                for(size_t k=0; k<m.imports.size(); k++) {
                    auto& i=m.imports[k];
                    if(k)std::cout<<",";
                    std::cout<<"{\"alias\": "<<quote(i.alias)<<", \"target\": "<<quote(i.target)<<"}";
                }
                std::cout<<"]}";
            }
            std::cout<<"\n  ],\n  \"source_files\": [";
            for(size_t j=0; j<p.sources.size(); j++) {
                if(j)std::cout<<",";
                std::cout<<quote(p.sources[j].string());
            }
            std::cout<<"]\n}\n";
            return 0;
        }
        if(cmd=="component") { std::cout<<componentContractJson(p,targetProfile.empty()?TARGET_ID:targetProfile); return 0; }
        if(cmd=="manifest") { std::cout<<programManifest(p); return 0; }
        if(cmd=="hash") { std::cout<<compactOmniHash(p)<<"\n"; return 0; }
        if(cmd=="memory") { std::cout<<memoryJson(p); return 0; }
        if(cmd=="memory-pack") { if(out.empty())fail("E_CLI","memory-pack requiere -o"); const auto store=systemMemoryStore(p);publishSnapshot(out,store,force);return 0; }
        if(cmd=="observe") { requireMain(p); const auto r=evaluate(p,"main",{},hostPolicy?&*hostPolicy:nullptr); std::optional<SystemMemory> previous; uint64_t seq=1; if(!against.empty()){maybeRecoverSnapshotPublication(against);previous=parseSystemMemoryStore(readUtf8Text(against));seq=advanceEpochSequence(previous->epoch.sequence);} const auto observed=buildObservedSystemMemory(p,r,seq); if(!out.empty()){const auto text=systemMemoryStore(observed);publishSnapshot(out,text,force);}std::cout<<runtimeObservationJson(p,r,seq,previous?&*previous:nullptr);return 0; }
        if(cmd=="graph") { std::cout<<graphJson(p); return 0; }
        if(cmd=="summary") { std::cout<<systemSummaryJson(p); return 0; }
        if(cmd=="trace") { std::cout<<traceSystemJson(p,queryValue,depth); return 0; }
        if(cmd=="impact") { std::cout<<impactSystemJson(p,queryValue); return 0; }
        if(cmd=="query") { std::cout<<querySystemJson(p,queryMode,queryValue); return 0; }
        if(cmd=="cognition") { std::cout<<cognitiveProjectionJson(p,selector); return 0; }
        if(cmd=="synapse-scale") { std::cout<<synapticScaleBenchmarkJson(p,queryValue,instances,overrides); return 0; }
        if(cmd=="cognition-offload") { if(fs::exists(out)&&!force)fail("E_EXISTS","OCAP envelope existente; use --force"); if(fs::is_symlink(out)||fs::is_directory(out))fail("E_FILE","salida OCAP no regular"); const auto envelope=makeCognitiveOffloadEnvelope(p,selector,provider,cognitiveBudget,grants); write(out,serializeCognitiveOffloadEnvelope(envelope)); std::cout<<cognitiveOffloadSummaryJson(envelope); return 0; }
        if(cmd=="pulse") { if(against.empty())std::cout<<neuralPulseJson(p,nullptr);else{auto old=load(against,bundledStandardLibrary(root(argv[0])));std::cout<<neuralPulseJson(p,&old);}return 0; }
        if(cmd=="onme-stats") { std::cout<<onmeStatsJson(p); return 0; }
        if(cmd=="onme") { const auto text=onme(p);if(out.empty())std::cout<<text;else{if(fs::exists(out)&&!force)fail("E_EXISTS","archivo existente; use --force");write(out,text);}return 0; }
        if(cmd=="check")  {
            if(denyExcess) {
                std::vector<std::string> offenders;
                for(const auto& f:p.functions) if(!f.excessCapabilities.empty()) {
                    std::ostringstream x;
                    x<<f.module<<"."<<f.name<<":";
                    bool first=true;
                    for(const auto& cap:f.excessCapabilities){ if(!first)x<<","; first=false; x<<cap; }
                    offenders.push_back(x.str());
                }
                if(!offenders.empty()) {
                    std::ostringstream msg;
                    msg<<"capabilities declaradas pero no requeridas: ";
                    for(size_t i=0;i<offenders.size();++i){ if(i)msg<<"; "; msg<<offenders[i]; }
                    fail("E_CAPABILITY_EXCESS",msg.str());
                }
            }
            if(admissionMode)std::cout<<"{\"schema\":\"omni.admission/1\",\"verdict\":\"YES\",\"diagnostic\":null}\n";
            else if(bindingsJson)std::cout<<bindingIndexJson(p);
            else std::cout<<"OK: "<<p.functions.size()<<" functions, Omni Language "<<VERSION<<" general-purpose alpha\n";
            return 0;
        }
        if(cmd=="fmt"||cmd=="unpack")  {
            const auto formatted=particle(p);
            if(cmd=="fmt"&&formatCheck) {
                if(p.sources.size()!=1u)fail("E_FORMAT","fmt --check requiere una fuente individual");
                if(readUtf8Text(input)!=formatted)fail("E_FORMAT","fuente no esta en formato canonico");
                return 0;
            }
            if(cmd=="fmt"&&formatWrite) {
                if(p.sources.size()!=1u)fail("E_FORMAT","fmt --write requiere una fuente individual");
                const fs::path source=input;
                if(fs::is_symlink(source)||!fs::is_regular_file(source))fail("E_FILE","fmt --write requiere archivo regular, no enlace");
                if(readUtf8Text(source)==formatted)return 0;
                Scratch temp(fs::absolute(source).parent_path());
                const auto staged=temp.path/"formatted.omni";
                write(staged,formatted);
                std::error_code ec;
                fs::permissions(staged,fs::status(source).permissions(),ec);
                if(ec)fail("E_FILE","no se pudieron preservar permisos de fuente");
                fs::rename(staged,source,ec);
                if(ec)fail("E_FILE","no se pudo publicar formato atomico: "+ec.message());
                return 0;
            }
            std::cout<<formatted;
            return 0;
        }
        if(cmd=="wave"||cmd=="inspect")  {
            std::cout<<wave(p);
            return 0;
        }
        if(cmd=="pack"||cmd=="emit-llvm")  {
            std::string s;
            if(cmd=="pack")  {
                if(out.empty())fail("E_CLI","pack requiere -o");
                auto b=wire(p);
                s.assign(b.begin(),b.end());
            }
            else if(!targetProfile.empty()) {
                TargetProfile tp; tp.name=targetProfile; tp.serviceModule=serviceModule; tp.entrySection=entrySection; tp.entryAddress=entryAddress; tp.entryStack=entryStack; tp.entryHandoffStore=entryHandoff; tp.exceptionHandler=exceptionHandler; tp.exceptionResume=exceptionResume; tp.ring3Support=ring3Support; tp.isrExtraVector=isrExtraVector; tp.isrCount=isrCount; tp.threadEntry=threadEntry;
                if(targetProfile=="baremetal-x86_64"){ tp.triple="x86_64-unknown-none-elf"; tp.provider=true; }
                else if(targetProfile=="baremetal-i386-boot"){ tp.triple="i386-unknown-none-elf"; tp.provider=false; tp.pvhNote=true; }
                else fail("E_TARGET_PROFILE","perfil de destino desconocido: "+targetProfile);
                if(tp.serviceModule.empty())fail("E_CLI","--target-profile requiere --service-module");
                if((targetIsa!="gpr"||exceptionSaveFpu)&&targetProfile!="baremetal-x86_64")fail("E_TARGET_PROFILE","--target-isa sse2/--exception-save-fpu requieren el perfil baremetal-x86_64");
                if(exceptionSaveFpu&&targetIsa!="sse2")fail("E_TARGET_PROFILE","--exception-save-fpu requiere --target-isa sse2");
                tp.isa=targetIsa; tp.exceptionSaveFpu=exceptionSaveFpu;
                s=emitLLVMTarget(p,tp);
            }
            else s=emitLLVM(p);
            if(out.empty())std::cout<<s;
            else  {
                if(fs::exists(out)&&!force)fail("E_EXISTS","archivo existente; use --force");
                if(fs::is_symlink(out)||fs::is_directory(out))fail("E_FILE","salida no regular");
                write(out,s);
            }
            return 0;
        }
        if(cmd=="eval")  {
            requireMain(p);
            auto r=evaluate(p,"main",{},hostPolicy?&*hostPolicy:nullptr);
            std::cout<<r.output;
            return r.result&255;
        }
        if(cmd=="test")  {
            int n=0;
            for(auto& f:p.functions)if(f.name.rfind("test_",0)==0)  {
                if(!f.params.empty()||f.result!=Type::Bool||f.effectful())fail("E_TEST","test debe ser () bool !pure");
                auto r=evaluate(p,f.key);
                if(!r.result)fail("E_TEST","fallo: "+f.name);
                std::cout<<"PASS "<<f.name<<"\n";
                n++;
            }
            if(!n)fail("E_TEST","no hay funciones test_");
            std::cout<<n<<" tests passed (reference evaluator)\n";
            return 0;
        }
        if(cmd=="profile"||cmd=="coverage") {
            Scratch temporary(fs::temp_directory_path());
            const auto binary=temporary.path/"app";
            (void)build(p,binary,rt,clang,opt,false,false,temporary.path/"cache");
            std::optional<ScopedEnvironment> coverageEnvironment;
            const auto coveragePath=temporary.path/"coverage.omnicov";
            if(cmd=="coverage")coverageEnvironment.emplace("OMNI_COVERAGE_FILE",coveragePath.string());
            std::vector<std::string> arguments={binary.string()};
            if(!hostPolicyPath.empty()){arguments.push_back("--omni-host-policy");arguments.push_back(hostPolicyPath.string());}
            const auto observed=runObserved(arguments);
            std::ostringstream report;
            if(cmd=="profile") {
                report<<"{\n  \"schema\": \"omni.native-profile/1\",\n"
                      <<"  \"language_version\": "<<quote(VERSION)<<",\n"
                      <<"  \"target_id\": \"linux-x86_64-gnu\",\n"
                      <<"  \"program_content_id\": \"sha256:"<<sha256(wave(p))<<"\",\n"
                      <<"  \"artifact_sha256\": \""<<sha256File(binary)<<"\",\n"
                      <<"  \"compiler_sha256\": \""<<compilerArtifactHash()<<"\",\n"
                      <<"  \"exit_code\": "<<observed.exitCode<<",\n  \"signal\": "<<observed.signal<<",\n"
                      <<"  \"wall_nanoseconds\": "<<observed.durationNs<<",\n"
                      <<"  \"user_nanoseconds\": "<<observed.userNs<<",\n"
                      <<"  \"system_nanoseconds\": "<<observed.systemNs<<",\n"
                      <<"  \"max_rss_kib\": "<<observed.maxRssKb<<",\n"
                      <<"  \"captured_output_bytes\": "<<observed.output.size()<<",\n"
                      <<"  \"captured_output_sha256\": \""<<sha256(observed.output)<<"\",\n"
                      <<"  \"output_truncated\": "<<(observed.outputTruncated?"true":"false")<<",\n"
                      <<"  \"payload_recorded\": false\n}\n";
            } else {
                if(!fs::is_regular_file(coveragePath)||fs::is_symlink(coveragePath))fail("E_COVERAGE","native coverage artifact missing");
                std::istringstream inputCoverage(readUtf8Text(coveragePath));std::string line;
                if(!std::getline(inputCoverage,line)||line!="OMNICOV1")fail("E_COVERAGE","native coverage header invalid");
                std::set<size_t> visited;
                while(std::getline(inputCoverage,line)){if(line.empty())continue;size_t id=0;const auto parsed=std::from_chars(line.data(),line.data()+line.size(),id);if(parsed.ec!=std::errc()||parsed.ptr!=line.data()+line.size()||id>=p.functions.size())fail("E_COVERAGE","native coverage region invalid");visited.insert(id);}
                report<<"{\n  \"schema\": \"omni.native-coverage/1\",\n"
                      <<"  \"language_version\": "<<quote(VERSION)<<",\n"
                      <<"  \"target_id\": \"linux-x86_64-gnu\",\n"
                      <<"  \"program_content_id\": \"sha256:"<<sha256(wave(p))<<"\",\n"
                      <<"  \"artifact_sha256\": \""<<sha256File(binary)<<"\",\n"
                      <<"  \"source_map_schema\": \"omni.source-map/1\",\n"
                      <<"  \"granularity\": \"function-entry\",\n"
                      <<"  \"exit_code\": "<<observed.exitCode<<",\n"
                      <<"  \"visited_regions\": "<<visited.size()<<",\n  \"total_regions\": "<<p.functions.size()<<",\n"
                      <<"  \"regions\": [";
                bool first=true;for(const auto id:visited){const auto& function=p.functions[id];if(!first)report<<",";first=false;report<<"{\"id\":"<<id<<",\"module\":"<<quote(function.module)<<",\"name\":"<<quote(function.name)<<",\"source\":"<<quote(fs::path(function.loc.file).filename().string())<<",\"line\":"<<function.loc.line<<",\"column\":"<<function.loc.column<<"}";}
                report<<"],\n  \"captured_output_sha256\": \""<<sha256(observed.output)<<"\",\n  \"payload_recorded\": false\n}\n";
            }
            if(out.empty())std::cout<<report.str();else{if(fs::exists(out)&&!force)fail("E_EXISTS","reporte existente; use --force");write(out,report.str());}
            return 0;
        }
        if(cmd=="build")  {
            if(out.empty())fail("E_CLI","build requiere -o");
            auto br=build(p,out,rt,clang,opt,force,useCache,cacheRoot);
            std::cout<<"Built: "<<fs::absolute(out).string()<<" [cache "<<(br.cacheHit?"hit":"miss")<<"]\n";
            return 0;
        }
        Scratch temp(fs::temp_directory_path());
        auto bin=temp.path/"app";
        build(p,bin,rt,clang,opt,false,useCache,cacheRoot);
        if(hostPolicyPath.empty())return launch({bin.string()});
        return launch({bin.string(),"--omni-host-policy",hostPolicyPath.string()});
    }
    catch(const Error& e)  {
        if(admissionMode&&e.code!="E_CLI") {
            std::cout<<"{\"schema\":\"omni.admission/1\",\"verdict\":\"NO\",\"diagnostic\":"<<diagnosticJson(e,input)<<"}\n";
            return 2;
        }
        if(cmd=="eval"&&(e.code=="E_OVERFLOW"||e.code=="E_DIVZERO"||e.code=="E_FUEL"||e.code=="E_DEPTH"||e.code=="E_OUTPUT_LIMIT"))  {
            std::cout<<e.output;
            std::cerr<<"omni runtime "<<e.code<<"\n";
            return 70;
        }
        if(diagnosticJsonMode) std::cerr<<diagnosticJson(e,input);
        else {
            std::cerr<<e.code<<": "<<(e.source.empty()?input:e.source);
            const auto primaryColumn=diagnosticScalarColumn(e.source.empty()?input:e.source,e.line,e.column);
            if(primaryColumn)std::cerr<<":"<<e.line<<":"<<*primaryColumn;
            std::cerr<<": "<<e.what()<<"\n";
            for(const auto& r:e.related) {   // secondary locations use the same coordinate as the primary
                const auto relatedSource=r.loc.file.empty()?(e.source.empty()?input:e.source):r.loc.file;
                const auto relatedColumn=diagnosticScalarColumn(relatedSource,r.loc.line,r.loc.column);
                std::cerr<<"  nota ("<<r.role<<"): "<<relatedSource;
                if(relatedColumn)std::cerr<<":"<<r.loc.line<<":"<<*relatedColumn;
                std::cerr<<": "<<r.note<<"\n";
            }
        }
        return 2;
    }
    catch(const std::bad_alloc&) {
        // the counting allocator refused an allocation that would take the heap past the budget (or the host itself had no memory left): the same structured fault as a checkpoint's
        const auto& account=resourceAccount();
        std::ostringstream why;
        why<<"la memoria se agoto cerca de "<<account.phase.load()<<" (pico de "<<(account.peak.load()>>20)<<" MiB retenidos";
        if(account.limit.load()!=0)why<<", presupuesto "<<(account.limit.load()>>20)<<" MiB: "<<account.origin<<"); suba OMNI_MEMORY_MIB, libere memoria del host o divida el proyecto";
        else why<<"; el entorno informa "<<(account.lastAvail.load()>>20)<<" MiB disponibles: "<<account.origin<<"); libere memoria del host, fije OMNI_MEMORY_MIB o divida el proyecto";
        Error budget("E_BUDGET",why.str());
        if(admissionMode)std::cout<<"{\"schema\":\"omni.admission/1\",\"verdict\":\"NO\",\"diagnostic\":"<<diagnosticJson(budget,input)<<"}\n";
        else if(diagnosticJsonMode)std::cerr<<diagnosticJson(budget,input);
        else std::cerr<<"E_BUDGET: "<<budget.what()<<"\n";
        return 2;
    }
    catch(const std::exception& e)  {
        std::cerr<<"E_INTERNAL_OR_IO: "<<e.what()<<"\n";
        return 3;
    }
}

// ---- The resource budget of the process (Adenda 015E) ----------------------------------------------------------------------------------------------------------------
// The compiler is not limited by counts inherited from earlier versions, and it does not impose a fraction of the machine on itself. There are two modes:
//  * EXPLICIT: OMNI_MEMORY_MIB=n fixes the budget. The heap, counted exactly (every operator new/delete passes through the counter below), never passes it; the allocator refuses the allocation that would.
//    `0` or `unlimited` removes the budget. A reserve for the other tenants of the host is the policy of whoever starts the compiler, and this is how it is expressed.
//  * AUTOMATIC (the default): no ceiling is imposed. Every time the heap has grown by a step (a sampling interval, not a limit) the allocator asks the host what it can still give, and it refuses an
//    allocation that the host has said it cannot provide. What the host can give is MemAvailable, bounded by the headroom of the cgroup and of an address-space limit if the caller set one;
//    OMNI_HOST_MEMORY_MIB replaces the reading for hosts whose /proc is not representative (and for tests).
// Three measures are kept apart: the heap the compiler holds (counted), the resident set of the process (what a build without counting is checked against) and the limits of the environment (cgroup, address space).
// The phases of the compiler also check at their own checkpoints and record where they were, so a refusal says where. A build with AddressSanitizer keeps the sanitizer's own allocator: it does not count,
// an explicit budget is checked against the resident set and the automatic mode is not enforced.
#if defined(__SANITIZE_ADDRESS__)
#define OMNI_NO_COUNTING_ALLOCATOR 1
#endif
#if defined(__has_feature)
#if __has_feature(address_sanitizer)
#define OMNI_NO_COUNTING_ALLOCATOR 1
#endif
#endif
#ifndef _WIN32
namespace {
    // Reads a small file without allocating (the allocator itself calls this): returns the bytes read.
    std::size_t readSmall(const char* path,char* buffer,std::size_t size) {
        const int fd=open(path,O_RDONLY);
        if(fd<0)return 0;
        const ssize_t got=read(fd,buffer,size-1);
        close(fd);
        if(got<=0)return 0;
        buffer[got]='\0';
        return static_cast<std::size_t>(got);
    }
    std::uint64_t numberAfter(const char* text,const char* key) {
        const char* at=std::strstr(text,key);
        return at?std::strtoull(at+std::strlen(key),nullptr,10):0ull;
    }
    // What the host can still give this process, in bytes, while the compiler holds `live` bytes of heap. UINT64_MAX when the host cannot be read: nothing is enforced.
    std::uint64_t hostAvailableBytes(std::uint64_t live) {
        char text[4096];
        if(const char* raw=std::getenv("OMNI_HOST_MEMORY_MIB")) {
            char* end=nullptr;
            const unsigned long long mib=std::strtoull(raw,&end,10);
            if(end!=raw&&*end=='\0'&&mib>0ull) {
                const std::uint64_t total=static_cast<std::uint64_t>(mib)<<20;
                return total>live?total-live:0ull;
            }
        }
        if(!readSmall("/proc/meminfo",text,sizeof text))return UINT64_MAX;
        std::uint64_t best=numberAfter(text,"MemAvailable:")*1024ull;
        if(best==0ull)return UINT64_MAX;
        if(readSmall("/sys/fs/cgroup/memory.max",text,sizeof text)&&std::strncmp(text,"max",3)!=0) {
            const std::uint64_t limit=std::strtoull(text,nullptr,10);
            char current[64];
            const std::uint64_t used=readSmall("/sys/fs/cgroup/memory.current",current,sizeof current)?std::strtoull(current,nullptr,10):0ull;
            best=std::min<std::uint64_t>(best,limit>used?limit-used:0ull);
        }
        struct rlimit as {};
        if(getrlimit(RLIMIT_AS,&as)==0&&as.rlim_cur!=RLIM_INFINITY&&readSmall("/proc/self/status",text,sizeof text)) {
            const std::uint64_t mapped=numberAfter(text,"VmSize:")*1024ull;
            best=std::min<std::uint64_t>(best,as.rlim_cur>mapped?static_cast<std::uint64_t>(as.rlim_cur)-mapped:0ull);
        }
        return best;
    }
}
#else
namespace { std::uint64_t hostAvailableBytes(std::uint64_t) { return UINT64_MAX; } }
#endif
#ifndef OMNI_NO_COUNTING_ALLOCATOR
namespace {
    constexpr std::size_t kHeapHeader=16;                  // keeps the 16-byte alignment of malloc and holds the size of the block
    constexpr std::uint64_t kSampleStep=1ull<<20;          // how much the heap grows before the host is asked again: a sampling interval, not a limit
    inline void* countedAllocate(std::size_t n) {
        auto& a=omni::resourceAccount();
        const auto limit=a.limit.load(std::memory_order_relaxed);
        if(limit==0&&a.automatic.load(std::memory_order_relaxed)&&a.hostAvailable) {
            const std::uint64_t before=a.live.load(std::memory_order_relaxed);
            std::uint64_t grown=before>a.sampleLive.load(std::memory_order_relaxed)?before-a.sampleLive.load(std::memory_order_relaxed):0ull;
            if(grown>=kSampleStep||n>=kSampleStep) {
                a.sampleAvail.store(a.hostAvailable(before),std::memory_order_relaxed);
                a.sampleLive.store(before,std::memory_order_relaxed);
                grown=0ull;
            }
            const std::uint64_t available=a.sampleAvail.load(std::memory_order_relaxed);
            if(grown+n>available) {
                a.lastAvail.store(available,std::memory_order_relaxed);
                throw std::bad_alloc();
            }
        }
        const std::uint64_t now=a.live.fetch_add(n,std::memory_order_relaxed)+n;
        if(limit&&now>limit) {
            a.live.fetch_sub(n,std::memory_order_relaxed);
            throw std::bad_alloc();
        }
        void* raw=std::malloc(n+kHeapHeader);
        if(!raw) {
            a.live.fetch_sub(n,std::memory_order_relaxed);
            throw std::bad_alloc();
        }
        *static_cast<std::size_t*>(raw)=n;
        if(now>a.peak.load(std::memory_order_relaxed))a.peak.store(now,std::memory_order_relaxed);
        return static_cast<char*>(raw)+kHeapHeader;
    }
    inline void countedFree(void* p) noexcept {
        if(!p)return;
        void* raw=static_cast<char*>(p)-kHeapHeader;
        omni::resourceAccount().live.fetch_sub(*static_cast<std::size_t*>(raw),std::memory_order_relaxed);
        std::free(raw);
    }
}
void* operator new(std::size_t n) { return countedAllocate(n); }
void* operator new[](std::size_t n) { return countedAllocate(n); }
void* operator new(std::size_t n,const std::nothrow_t&) noexcept { try { return countedAllocate(n); } catch(...) { return nullptr; } }
void* operator new[](std::size_t n,const std::nothrow_t&) noexcept { try { return countedAllocate(n); } catch(...) { return nullptr; } }
void operator delete(void* p) noexcept { countedFree(p); }
void operator delete[](void* p) noexcept { countedFree(p); }
void operator delete(void* p,std::size_t) noexcept { countedFree(p); }
void operator delete[](void* p,std::size_t) noexcept { countedFree(p); }
void operator delete(void* p,const std::nothrow_t&) noexcept { countedFree(p); }
void operator delete[](void* p,const std::nothrow_t&) noexcept { countedFree(p); }
#endif
namespace {
    void initResourceBudget() {
        auto& a=omni::resourceAccount();
#ifndef OMNI_NO_COUNTING_ALLOCATOR
        a.counting.store(true);
#endif
        if(const char* raw=std::getenv("OMNI_WORK_SECONDS")) {
            char* end=nullptr;
            const double seconds=std::strtod(raw,&end);
            if(end!=raw&&*end=='\0'&&seconds>0.0)
                a.deadlineNs.store(std::chrono::duration_cast<std::chrono::nanoseconds>(std::chrono::steady_clock::now().time_since_epoch()).count()+static_cast<std::int64_t>(seconds*1e9));
        }
        if(const char* raw=std::getenv("OMNI_MEMORY_MIB")) {
            const std::string value(raw);
            if(value=="0"||value=="unlimited") {
                a.origin="OMNI_MEMORY_MIB=unlimited";
                return;
            }
            char* end=nullptr;
            const unsigned long long mib=std::strtoull(raw,&end,10);
            if(end!=raw&&*end=='\0'&&mib>0ull&&mib<(1ull<<40)) {
                a.limit.store(static_cast<std::uint64_t>(mib)<<20);
                a.origin="OMNI_MEMORY_MIB="+value;
                return;
            }
        }
        a.hostAvailable=&hostAvailableBytes;
        a.automatic.store(true);
#ifdef OMNI_NO_COUNTING_ALLOCATOR
        a.origin="automatic: the memory the host reports available (not enforced in a build that does not count the heap)";
#else
        a.origin="automatic: the memory the host reports available when it is needed";
#endif
    }
    std::size_t g_compilerStackBytes=0;
}

// The compiler walks source trees recursively (checker, evaluator, lowering). The parser bounds nesting and tree height (192), but how much stack a
// level costs depends on the build: a sanitizer build uses tens of KB per level. All of the work therefore runs on a thread with a stack that is large
// and explicit, so the documented bounds hold for every build and do not depend on the caller's `ulimit -s` (audit 360: stack-overflow crashes).
namespace {
struct MainCall { int argc; char** argv; int rc; };
void* mainThread(void* p) {
    auto* call=static_cast<MainCall*>(p);
    char base=0;
    auto& account=omni::resourceAccount();
    account.stackBase=reinterpret_cast<std::uintptr_t>(&base);      // the stack budget (stackGuard) is measured from here
    account.stackBytes=g_compilerStackBytes;
    call->rc=omniMain(call->argc,call->argv);
    return nullptr;
}
}
int main(int argc,char** argv) {
    MainCall call{argc,argv,0};
    // OMNI_STACK_KIB overrides the default (256 MiB) within 256 KiB .. 4 GiB; it exists so that the depth bounds can be tested without relying on the stack
    // being large enough to hide a missing bound. An invalid value is ignored.
    size_t kStackBytes=static_cast<size_t>(256)<<20;
    if(const char* raw=std::getenv("OMNI_STACK_KIB")) {
        char* end=nullptr;
        const unsigned long long kib=std::strtoull(raw,&end,10);
        if(end!=raw&&*end=='\0'&&kib>=256ull&&kib<=4194304ull)kStackBytes=static_cast<size_t>(kib)<<10;
    }
    g_compilerStackBytes=kStackBytes;
    initResourceBudget();
    const auto report=[]{
        if(std::getenv("OMNI_RESOURCE_REPORT")) {
            const auto& a=omni::resourceAccount();
            std::cerr<<"omni resources: heap_peak_mib="<<(a.peak.load()>>20)<<" budget_mib="<<(a.limit.load()>>20)<<" origin=\""<<a.origin<<"\" counting="<<(a.counting.load()?"yes":"no")<<"\n";
        }
    };
    pthread_attr_t attr;
    pthread_t thread;
    if(pthread_attr_init(&attr)==0) {
        if(pthread_attr_setstacksize(&attr,kStackBytes)==0&&pthread_create(&thread,&attr,mainThread,&call)==0) {
            pthread_attr_destroy(&attr);
            pthread_join(thread,nullptr);
            report();
            return call.rc;
        }
        pthread_attr_destroy(&attr);
    }
    return omniMain(argc,argv);   // no thread available (restricted environment): run on the caller's stack as before
}
