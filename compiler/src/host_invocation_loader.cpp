#include "host_invocation_descriptor.hpp"
#include "host_sdk_schema.hpp"
#include "../../runtime/omni_invocation_v1.h"
#include "../../runtime/omni_invocation_internal.h"
#include <atomic>
#include <algorithm>
#include <cerrno>
#include <cstring>
#include <dlfcn.h>
#include <elf.h>
#include <fcntl.h>
#include <linux/memfd.h>
#include <map>
#include <memory>
#include <mutex>
#include <set>
#include <string_view>
#include <sys/stat.h>
#include <sys/syscall.h>
#include <time.h>
#include <unistd.h>

#ifndef OMNI_INVOCATION_RUNTIME_BUILD_HEX
#error "The invocation runtime must be built with a canonical build identity"
#endif

namespace {
using omni::HostInvocationDescriptor;
using omni::InvocationHash;
constexpr size_t ARTIFACT_LIMIT=268435456u;
constexpr uint32_t FRAME_LIMIT=1048576u;
constexpr uint32_t POLICY_LIMIT=65536u;
constexpr uint32_t DIAGNOSTIC_LIMIT=16384u;
constexpr uint64_t ALLOCATION_LIMIT=67108864u;
constexpr uint64_t DEADLINE_LIMIT_NS=300000000000ull;

struct Module {
    uint64_t handle=0;
    int memfd=-1;
    void* dl=nullptr;
    OmniModuleEntryV1 entry=nullptr;
    HostInvocationDescriptor descriptor;
    std::vector<uint8_t> sdkSchema;
    uint32_t live=0;
    bool poisoned=false;
    ~Module(){if(dl)dlclose(dl);if(memfd>=0)close(memfd);}
};
struct Invocation {
    uint64_t handle=0,module=0;
    std::vector<uint8_t> request,policy,result;
    uint64_t generation=0,deadline=0,allocationLimit=0;
    uint32_t resultLimit=0,diagnosticLimit=0;
    uint8_t trace[16]{};
    uint32_t cancel=0;
    bool running=false,terminal=false,consumed=false;
    uint32_t status=OMNI_INVOCATION_V1_RUNTIME_FAILURE,effect=OMNI_INVOCATION_V1_EFFECT_NONE;
};
std::mutex registryMutex;
std::map<uint64_t,std::unique_ptr<Module>> modules;
std::map<uint64_t,std::unique_ptr<Invocation>> invocations;
uint64_t nextHandle=1;
std::atomic<bool> activeInvoke{false};

uint64_t newHandle(bool module){
    if(nextHandle>=UINT64_MAX/2u)return 0;
    const uint64_t serial=nextHandle++;
    return (serial<<1u)|(module?1u:0u);
}
#ifdef OMNI_INVOCATION_TESTING
/* Test-only fault injection. This symbol is absent from production builds. */
extern "C" uint32_t omni_invocation_v1_test_force_next_handle(uint64_t value){
    std::lock_guard guard(registryMutex);
    if(!modules.empty()||!invocations.empty())return OMNI_INVOCATION_V1_BUSY;
    nextHandle=value;
    return 0;
}
#endif
uint64_t monotonicNow(){
    timespec now{};
    if(clock_gettime(CLOCK_MONOTONIC,&now)!=0)return 0;
    return static_cast<uint64_t>(now.tv_sec)*1000000000ull+
           static_cast<uint64_t>(now.tv_nsec);
}
bool spanIn(size_t total,uint64_t offset,uint64_t length){
    return offset<=total&&length<=total-offset;
}
template<class T> bool objectAt(const std::vector<uint8_t>& bytes,uint64_t offset,T& value){
    if(!spanIn(bytes.size(),offset,sizeof(T)))return false;
    std::memcpy(&value,bytes.data()+offset,sizeof(T));return true;
}
std::vector<uint8_t> readFd(int fd,size_t limit){
    struct stat st{};
    if(fstat(fd,&st)!=0||!S_ISREG(st.st_mode)||st.st_size<=0||
       static_cast<uint64_t>(st.st_size)>limit)return {};
    std::vector<uint8_t> bytes(static_cast<size_t>(st.st_size));
    size_t used=0;
    while(used<bytes.size()){
        const ssize_t n=pread(fd,bytes.data()+used,bytes.size()-used,
                              static_cast<off_t>(used));
        if(n<=0){if(n<0&&errno==EINTR)continue;return {};}
        used+=static_cast<size_t>(n);
    }
    return bytes;
}
bool exactHash(const std::vector<uint8_t>& bytes,const uint8_t expected[32]){
    return omni::invocationHash(bytes)==InvocationHash{expected[0],expected[1],expected[2],expected[3],expected[4],expected[5],expected[6],expected[7],expected[8],expected[9],expected[10],expected[11],expected[12],expected[13],expected[14],expected[15],expected[16],expected[17],expected[18],expected[19],expected[20],expected[21],expected[22],expected[23],expected[24],expected[25],expected[26],expected[27],expected[28],expected[29],expected[30],expected[31]};
}
bool copyToMemfd(int fd,const std::vector<uint8_t>& bytes){
    size_t offset=0;
    while(offset<bytes.size()){
        const ssize_t n=write(fd,bytes.data()+offset,bytes.size()-offset);
        if(n<=0){if(n<0&&errno==EINTR)continue;return false;}
        offset+=static_cast<size_t>(n);
    }
    return fcntl(fd,F_ADD_SEALS,F_SEAL_SEAL|F_SEAL_SHRINK|F_SEAL_GROW|F_SEAL_WRITE)==0;
}
bool symbolFileRange(const std::vector<uint8_t>& bytes,const Elf64_Ehdr& eh,
                     uint64_t address,uint64_t length,uint64_t& fileOffset){
    for(uint16_t i=0;i<eh.e_phnum;i++){
        Elf64_Phdr ph{};
        if(!objectAt(bytes,eh.e_phoff+static_cast<uint64_t>(i)*eh.e_phentsize,ph))return false;
        if(ph.p_type!=PT_LOAD||address<ph.p_vaddr||length>ph.p_filesz||
           address-ph.p_vaddr>ph.p_filesz-length)continue;
        fileOffset=ph.p_offset+address-ph.p_vaddr;
        return spanIn(bytes.size(),fileOffset,length);
    }
    return false;
}
struct ElfSelection {
    uint64_t descriptorOffset=0,descriptorLength=0;
    uint64_t sdkSchemaOffset=0,sdkSchemaLength=0;
    bool entry=false,sdkSchema=false;
};
bool inspectElf(const std::vector<uint8_t>& bytes,ElfSelection& selected){
    Elf64_Ehdr eh{};
    if(!objectAt(bytes,0,eh)||std::memcmp(eh.e_ident,ELFMAG,SELFMAG)!=0||
       eh.e_ident[EI_CLASS]!=ELFCLASS64||eh.e_ident[EI_DATA]!=ELFDATA2LSB||
       eh.e_machine!=EM_X86_64||eh.e_type!=ET_DYN||
       eh.e_shentsize!=sizeof(Elf64_Shdr)||eh.e_phentsize!=sizeof(Elf64_Phdr)||
       eh.e_shnum==0||eh.e_phnum==0||
       !spanIn(bytes.size(),eh.e_shoff,static_cast<uint64_t>(eh.e_shnum)*eh.e_shentsize)||
       !spanIn(bytes.size(),eh.e_phoff,static_cast<uint64_t>(eh.e_phnum)*eh.e_phentsize))return false;
    Elf64_Phdr dynamic{};bool hasDynamic=false;
    for(uint16_t i=0;i<eh.e_phnum;i++){
        Elf64_Phdr ph{};
        if(!objectAt(bytes,eh.e_phoff+static_cast<uint64_t>(i)*eh.e_phentsize,ph))return false;
        if(ph.p_type==PT_TLS)return false;
        if(ph.p_type==PT_DYNAMIC){dynamic=ph;hasDynamic=true;}
        if(ph.p_type==PT_LOAD&&(!spanIn(bytes.size(),ph.p_offset,ph.p_filesz)||
           (ph.p_flags&PF_X&&ph.p_flags&PF_W)))return false;
    }
    if(!hasDynamic||!spanIn(bytes.size(),dynamic.p_offset,dynamic.p_filesz)||
       dynamic.p_filesz%sizeof(Elf64_Dyn)!=0)return false;
    uint64_t stringAddress=0,stringLength=0;
    std::vector<uint64_t> needed;
    bool dynamicEnded=false;
    for(uint64_t i=0;i<dynamic.p_filesz/sizeof(Elf64_Dyn);i++){
        Elf64_Dyn item{};
        if(!objectAt(bytes,dynamic.p_offset+i*sizeof item,item))return false;
        if(item.d_tag==DT_NULL){dynamicEnded=true;break;}
        if(item.d_tag==DT_INIT||item.d_tag==DT_FINI||
           item.d_tag==DT_INIT_ARRAY||item.d_tag==DT_FINI_ARRAY||
           item.d_tag==DT_PREINIT_ARRAY||item.d_tag==DT_RPATH||
           item.d_tag==DT_RUNPATH)return false;
        if(item.d_tag==DT_STRTAB)stringAddress=item.d_un.d_ptr;
        if(item.d_tag==DT_STRSZ)stringLength=item.d_un.d_val;
        if(item.d_tag==DT_NEEDED)needed.push_back(item.d_un.d_val);
    }
    if(!dynamicEnded||stringLength>FRAME_LIMIT)return false;
    uint64_t stringOffset=0;
    if(!symbolFileRange(bytes,eh,stringAddress,stringLength,stringOffset))return false;
    const std::set<std::string_view> allowed={"libomni_invocation_v1.so",
        "libc.so.6","libm.so.6","libdl.so.2"};
    for(const auto offset:needed){
        if(offset>=stringLength)return false;
        const auto* name=reinterpret_cast<const char*>(bytes.data()+stringOffset+offset);
        const size_t remaining=static_cast<size_t>(stringLength-offset);
        const void* end=std::memchr(name,0,remaining);
        if(!end||!allowed.count(std::string_view(name,
            static_cast<size_t>(static_cast<const char*>(end)-name))))return false;
    }
    uint32_t descriptorCount=0,entryCount=0,schemaCount=0;
    for(uint16_t i=0;i<eh.e_shnum;i++){
        Elf64_Shdr section{};
        if(!objectAt(bytes,eh.e_shoff+static_cast<uint64_t>(i)*eh.e_shentsize,section))return false;
        if(section.sh_type==SHT_INIT_ARRAY||section.sh_type==SHT_FINI_ARRAY)return false;
        if(section.sh_type!=SHT_DYNSYM)continue;
        if(section.sh_link>=eh.e_shnum||section.sh_entsize!=sizeof(Elf64_Sym)||
           !spanIn(bytes.size(),section.sh_offset,section.sh_size))return false;
        Elf64_Shdr strings{};
        if(!objectAt(bytes,eh.e_shoff+static_cast<uint64_t>(section.sh_link)*eh.e_shentsize,strings)||
           !spanIn(bytes.size(),strings.sh_offset,strings.sh_size))return false;
        for(uint64_t j=0;j<section.sh_size/section.sh_entsize;j++){
            Elf64_Sym symbol{};
            if(!objectAt(bytes,section.sh_offset+j*section.sh_entsize,symbol)||
               symbol.st_name>=strings.sh_size)return false;
            const auto* name=reinterpret_cast<const char*>(bytes.data()+strings.sh_offset+symbol.st_name);
            const size_t remaining=static_cast<size_t>(strings.sh_size-symbol.st_name);
            if(!std::memchr(name,0,remaining))return false;
            if(std::strcmp(name,"omni_module_v1_descriptor")==0){
                if(++descriptorCount!=1||symbol.st_size==0||
                   !symbolFileRange(bytes,eh,symbol.st_value,symbol.st_size,
                                    selected.descriptorOffset))return false;
                selected.descriptorLength=symbol.st_size;
            }else if(std::strcmp(name,"omni_module_host_sdk_v1_schema")==0){
                if(++schemaCount!=1||symbol.st_size==0||
                   !symbolFileRange(bytes,eh,symbol.st_value,symbol.st_size,
                                    selected.sdkSchemaOffset))return false;
                selected.sdkSchemaLength=symbol.st_size;selected.sdkSchema=true;
            }else if(std::strcmp(name,"omni_module_v1_entry")==0){
                if(++entryCount!=1||symbol.st_shndx==SHN_UNDEF||
                   ELF64_ST_TYPE(symbol.st_info)!=STT_FUNC)return false;
                selected.entry=true;
            }
        }
    }
    return descriptorCount==1;
}
uint32_t classifyDescriptorPrefix(std::span<const uint8_t> bytes){
    if(bytes.size()<16||std::memcmp(bytes.data(),"OMID1\0\0\0",8)!=0)
        return OMNI_INVOCATION_V1_IDENTITY_MISMATCH;
    const uint32_t version=uint32_t(bytes[8])|(uint32_t(bytes[9])<<8)|
        (uint32_t(bytes[10])<<16)|(uint32_t(bytes[11])<<24);
    if(version!=1)return OMNI_INVOCATION_V1_UNSUPPORTED_ABI;
    const uint32_t n=uint32_t(bytes[12])|(uint32_t(bytes[13])<<8)|
        (uint32_t(bytes[14])<<16)|(uint32_t(bytes[15])<<24);
    if(n>bytes.size()-16)return OMNI_INVOCATION_V1_IDENTITY_MISMATCH;
    return std::string_view(reinterpret_cast<const char*>(bytes.data()+16),n)==
        omni::INVOCATION_ABI_ID?0u:static_cast<uint32_t>(OMNI_INVOCATION_V1_UNSUPPORTED_ABI);
}
uint32_t policyCheck(const uint8_t* bytes,uint32_t length,uint64_t generation,
                     const HostInvocationDescriptor& descriptor){
    if(length==0)return generation==0?0u:static_cast<uint32_t>(OMNI_INVOCATION_V1_AUTHORITY_DENIED);
    if(generation==0||!bytes)return OMNI_INVOCATION_V1_AUTHORITY_DENIED;
    try{
        const auto policy=omni::parseHostPolicy(std::string(
            reinterpret_cast<const char*>(bytes),length));
        if(policy.generation!=generation)return OMNI_INVOCATION_V1_AUTHORITY_DENIED;
        for(const auto& grant:policy.grants)
            if(!std::binary_search(descriptor.effects.begin(),descriptor.effects.end(),
                                   grant.capability))
                return OMNI_INVOCATION_V1_AUTHORITY_DENIED;
        return 0;
    }catch(...){return OMNI_INVOCATION_V1_AUTHORITY_DENIED;}
}
}

extern "C" uint32_t omni_invocation_v1_module_open(
    const uint8_t* path,uint32_t pathLength,const uint8_t artifactHash[32],
    const uint8_t descriptorHash[32],uint64_t* outModule) {
    try{
        if(!outModule||!artifactHash||!descriptorHash||!path||pathLength==0||
           pathLength>4096)return OMNI_INVOCATION_V1_MALFORMED_INPUT;
        *outModule=0;
        const std::string name(reinterpret_cast<const char*>(path),pathLength);
        if(name[0]!='/'||name.find('\0')!=std::string::npos)
            return OMNI_INVOCATION_V1_MALFORMED_INPUT;
        const int source=open(name.c_str(),O_RDONLY|O_CLOEXEC|O_NOFOLLOW);
        if(source<0)return OMNI_INVOCATION_V1_IDENTITY_MISMATCH;
        struct stat st{};
        if(fstat(source,&st)!=0||!S_ISREG(st.st_mode)||st.st_size<=0){
            close(source);return OMNI_INVOCATION_V1_IDENTITY_MISMATCH;
        }
        if(static_cast<uint64_t>(st.st_size)>ARTIFACT_LIMIT){
            close(source);return OMNI_INVOCATION_V1_LIMIT_EXCEEDED;
        }
        auto artifact=readFd(source,ARTIFACT_LIMIT);
        close(source);
        if(artifact.empty()||!exactHash(artifact,artifactHash))
            return OMNI_INVOCATION_V1_IDENTITY_MISMATCH;
        ElfSelection selection;
        if(!inspectElf(artifact,selection))
            return OMNI_INVOCATION_V1_IDENTITY_MISMATCH;
        const auto descriptorBytes=std::span<const uint8_t>(
            artifact.data()+selection.descriptorOffset,
            static_cast<size_t>(selection.descriptorLength));
        if(!exactHash(std::vector<uint8_t>(descriptorBytes.begin(),descriptorBytes.end()),
                      descriptorHash))return OMNI_INVOCATION_V1_IDENTITY_MISMATCH;
        if(const auto code=classifyDescriptorPrefix(descriptorBytes);code)return code;
        HostInvocationDescriptor descriptor;
        try{descriptor=omni::decodeInvocationDescriptor(descriptorBytes,false);}
        catch(...){return OMNI_INVOCATION_V1_IDENTITY_MISMATCH;}
        if(descriptor.runtimeAbi!=omni::INVOCATION_RUNTIME_ABI_ID)
            return OMNI_INVOCATION_V1_UNSUPPORTED_ABI;
        if(descriptor.runtimeBuildHash!=
           omni::invocationHashHex(OMNI_INVOCATION_RUNTIME_BUILD_HEX))
            return OMNI_INVOCATION_V1_IDENTITY_MISMATCH;
        if(descriptor.signatureDigest!=omni::computeInvocationSignature(descriptor)||
           descriptor.buildInputDigest!=omni::computeInvocationBuildInput(descriptor))
            return OMNI_INVOCATION_V1_IDENTITY_MISMATCH;
        std::vector<uint8_t> sdkSchema;
        if(selection.sdkSchema){
            const auto schemaBytes=std::span<const uint8_t>(
                artifact.data()+selection.sdkSchemaOffset,
                static_cast<size_t>(selection.sdkSchemaLength));
            try{
                const auto schema=omni::decodeHostSdkSchema(schemaBytes);
                omni::validateHostSdkSchema(schema,descriptor);
            }catch(...){return OMNI_INVOCATION_V1_IDENTITY_MISMATCH;}
            sdkSchema.assign(schemaBytes.begin(),schemaBytes.end());
        }
        if(!selection.entry)return OMNI_INVOCATION_V1_ENTRYPOINT_MISSING;
        const int memfd=static_cast<int>(syscall(SYS_memfd_create,"omni-module-v1",
                                                  MFD_CLOEXEC|MFD_ALLOW_SEALING));
        if(memfd<0)return OMNI_INVOCATION_V1_RUNTIME_FAILURE;
        if(!copyToMemfd(memfd,artifact)){close(memfd);return OMNI_INVOCATION_V1_RUNTIME_FAILURE;}
        const std::string mempath="/proc/self/fd/"+std::to_string(memfd);
        void* library=dlopen(mempath.c_str(),RTLD_NOW|RTLD_LOCAL);
        if(!library){close(memfd);return OMNI_INVOCATION_V1_ENTRYPOINT_MISSING;}
        void* fixed=dlsym(library,"omni_module_v1_entry");
        if(!fixed){dlclose(library);close(memfd);return OMNI_INVOCATION_V1_ENTRYPOINT_MISSING;}
        OmniModuleEntryV1 entry=nullptr;
        static_assert(sizeof(entry)==sizeof(fixed));
        std::memcpy(&entry,&fixed,sizeof entry);
        auto module=std::make_unique<Module>();
        module->memfd=memfd;module->dl=library;module->entry=entry;
        module->descriptor=std::move(descriptor);
        module->sdkSchema=std::move(sdkSchema);
        std::lock_guard guard(registryMutex);
        module->handle=newHandle(true);
        if(!module->handle)return OMNI_INVOCATION_V1_LIMIT_EXCEEDED;
        *outModule=module->handle;
        modules.emplace(module->handle,std::move(module));
        return OMNI_INVOCATION_V1_SEMANTIC_OK;
    }catch(...){return OMNI_INVOCATION_V1_RUNTIME_FAILURE;}
}

extern "C" uint32_t omni_invocation_v1_invocation_create(
    uint64_t moduleHandle,const uint8_t* request,uint32_t requestLength,
    const uint8_t* policy,uint32_t policyLength,uint64_t generation,
    uint64_t deadline,uint64_t allocationLimit,uint32_t resultLimit,
    uint32_t diagnosticLimit,const uint8_t trace[16],uint64_t* outInvocation) {
    try{
        if(!outInvocation||!trace||(requestLength&&!request)||(policyLength&&!policy))
            return OMNI_INVOCATION_V1_MALFORMED_INPUT;
        *outInvocation=0;
        std::lock_guard guard(registryMutex);
        auto it=modules.find(moduleHandle);
        if(it==modules.end())return OMNI_INVOCATION_V1_INVALID_HANDLE;
        Module& module=*it->second;
        if(module.poisoned)return OMNI_INVOCATION_V1_POISONED;
        if(requestLength>FRAME_LIMIT||policyLength>POLICY_LIMIT||
           resultLimit==0||resultLimit>FRAME_LIMIT||
           diagnosticLimit>DIAGNOSTIC_LIMIT||
           allocationLimit==0||allocationLimit>ALLOCATION_LIMIT)
            return OMNI_INVOCATION_V1_LIMIT_EXCEEDED;
        const uint64_t now=monotonicNow();
        if(now==0||deadline<=now)return OMNI_INVOCATION_V1_DEADLINE_EXCEEDED;
        if(deadline-now>DEADLINE_LIMIT_NS)return OMNI_INVOCATION_V1_LIMIT_EXCEEDED;
        const uint64_t reserved=uint64_t(requestLength)+policyLength+resultLimit+
                                diagnosticLimit+sizeof(Invocation);
        if(reserved>=allocationLimit)return OMNI_INVOCATION_V1_LIMIT_EXCEEDED;
        auto invocation=std::make_unique<Invocation>();
        invocation->module=moduleHandle;
        if(requestLength)invocation->request.assign(request,request+requestLength);
        if(policyLength)invocation->policy.assign(policy,policy+policyLength);
        invocation->generation=generation;invocation->deadline=deadline;
        invocation->allocationLimit=allocationLimit-reserved;
        invocation->resultLimit=resultLimit;invocation->diagnosticLimit=diagnosticLimit;
        std::memcpy(invocation->trace,trace,16);
        uint32_t resultLength=0,effect=0;
        const uint32_t frameStatus=module.entry(0,invocation->request.data(),requestLength,
            nullptr,0,0,deadline,invocation->allocationLimit,invocation->trace,
            &invocation->cancel,nullptr,0,&resultLength,&effect);
        if(frameStatus!=0)return frameStatus;
        if(const auto policyStatus=policyCheck(policy,policyLength,generation,
                                               module.descriptor);policyStatus)return policyStatus;
        const uint32_t policyStatus=module.entry(0,invocation->request.data(),requestLength,
            invocation->policy.empty()?nullptr:invocation->policy.data(),policyLength,
            generation,deadline,invocation->allocationLimit,invocation->trace,
            &invocation->cancel,nullptr,0,&resultLength,&effect);
        if(policyStatus==OMNI_INVOCATION_V1_MALFORMED_INPUT)
            return OMNI_INVOCATION_V1_AUTHORITY_DENIED;
        if(policyStatus!=0)return policyStatus;
        invocation->handle=newHandle(false);
        if(!invocation->handle)return OMNI_INVOCATION_V1_LIMIT_EXCEEDED;
        const uint64_t handle=invocation->handle;
        invocations.emplace(handle,std::move(invocation));
        module.live++;
        *outInvocation=handle;
        return 0;
    }catch(...){return OMNI_INVOCATION_V1_RUNTIME_FAILURE;}
}

extern "C" uint32_t omni_invocation_v1_invoke(
    uint64_t handle,uint32_t* outEffect,uint32_t* outLength) {
    try{
        if(!outEffect||!outLength)return OMNI_INVOCATION_V1_MALFORMED_INPUT;
        *outEffect=OMNI_INVOCATION_V1_EFFECT_NONE;*outLength=0;
        Invocation* invocation=nullptr;
        OmniModuleEntryV1 entry=nullptr;
        {
            std::lock_guard guard(registryMutex);
            auto it=invocations.find(handle);
            if(it==invocations.end())return OMNI_INVOCATION_V1_INVALID_HANDLE;
            invocation=it->second.get();
            if(invocation->terminal)return OMNI_INVOCATION_V1_ALREADY_TERMINAL;
            if(invocation->running)return OMNI_INVOCATION_V1_BUSY;
            if(activeInvoke.exchange(true))return OMNI_INVOCATION_V1_BUSY;
            auto module=modules.find(invocation->module);
            if(module==modules.end()){activeInvoke=false;return OMNI_INVOCATION_V1_INVALID_HANDLE;}
            if(module->second->poisoned){activeInvoke=false;return OMNI_INVOCATION_V1_POISONED;}
            entry=module->second->entry;
            invocation->running=true;
        }
        uint32_t resultLength=0,effect=OMNI_INVOCATION_V1_EFFECT_NONE;
        uint32_t status=OMNI_INVOCATION_V1_RUNTIME_FAILURE;
        bool invariantFailure=false;
        std::vector<uint8_t> result(invocation->resultLimit);
        status=entry(1,invocation->request.data(),
            static_cast<uint32_t>(invocation->request.size()),
            invocation->policy.empty()?nullptr:invocation->policy.data(),
            static_cast<uint32_t>(invocation->policy.size()),invocation->generation,
            invocation->deadline,invocation->allocationLimit,invocation->trace,
            &invocation->cancel,result.data(),invocation->resultLimit,
            &resultLength,&effect);
        if(effect==OMNI_INVOCATION_V1_EFFECT_UNCERTAIN&&
           status!=OMNI_INVOCATION_V1_SEMANTIC_OK&&
           status!=OMNI_INVOCATION_V1_SEMANTIC_ERR)
            status=OMNI_INVOCATION_V1_UNKNOWN_OUTCOME;
        if(resultLength>invocation->resultLimit){
            status=OMNI_INVOCATION_V1_LIMIT_EXCEEDED;resultLength=0;
            invariantFailure=true;
        }
        if(status==OMNI_INVOCATION_V1_SEMANTIC_OK||
           status==OMNI_INVOCATION_V1_SEMANTIC_ERR){
            uint32_t checkedLength=0,checkedEffect=OMNI_INVOCATION_V1_EFFECT_NONE;
            const uint32_t verified=entry(2,result.data(),resultLength,
                nullptr,0,0,invocation->deadline,invocation->allocationLimit,
                invocation->trace,&invocation->cancel,nullptr,0,
                &checkedLength,&checkedEffect);
            if(verified!=OMNI_INVOCATION_V1_SEMANTIC_OK||
               checkedLength!=0||checkedEffect!=OMNI_INVOCATION_V1_EFFECT_NONE){
                invariantFailure=verified!=OMNI_INVOCATION_V1_DEADLINE_EXCEEDED&&
                    verified!=OMNI_INVOCATION_V1_CANCELLED&&
                    verified!=OMNI_INVOCATION_V1_LIMIT_EXCEEDED;
                if(checkedLength!=0||checkedEffect!=OMNI_INVOCATION_V1_EFFECT_NONE)
                    invariantFailure=true;
                status=verified==OMNI_INVOCATION_V1_DEADLINE_EXCEEDED||
                    verified==OMNI_INVOCATION_V1_CANCELLED||
                    verified==OMNI_INVOCATION_V1_LIMIT_EXCEEDED?
                    verified:static_cast<uint32_t>(OMNI_INVOCATION_V1_RUNTIME_FAILURE);
                if(effect==OMNI_INVOCATION_V1_EFFECT_UNCERTAIN)
                    status=OMNI_INVOCATION_V1_UNKNOWN_OUTCOME;
                resultLength=0;
            }
        }
        if(status==OMNI_INVOCATION_V1_SEMANTIC_OK||
           status==OMNI_INVOCATION_V1_SEMANTIC_ERR){
            result.resize(resultLength);invocation->result=std::move(result);
        }
        {
            std::lock_guard guard(registryMutex);
            invocation->status=status;invocation->effect=effect;
            invocation->running=false;invocation->terminal=true;
            if(invariantFailure){
                auto module=modules.find(invocation->module);
                if(module!=modules.end())module->second->poisoned=true;
            }
            activeInvoke=false;
        }
        *outEffect=effect;
        if(status==OMNI_INVOCATION_V1_SEMANTIC_OK||
           status==OMNI_INVOCATION_V1_SEMANTIC_ERR)
            *outLength=resultLength;
        return status;
    }catch(...){
        std::lock_guard guard(registryMutex);
        auto it=invocations.find(handle);
        if(it!=invocations.end()&&it->second->running){
            it->second->running=false;
            it->second->terminal=true;
            it->second->status=OMNI_INVOCATION_V1_RUNTIME_FAILURE;
        }
        activeInvoke=false;
        return OMNI_INVOCATION_V1_RUNTIME_FAILURE;
    }
}

extern "C" uint32_t omni_invocation_v1_cancel(uint64_t handle) {
    try{
        std::lock_guard guard(registryMutex);
        auto it=invocations.find(handle);
        if(it==invocations.end())return OMNI_INVOCATION_V1_INVALID_HANDLE;
        if(it->second->terminal)return OMNI_INVOCATION_V1_ALREADY_TERMINAL;
        __atomic_store_n(&it->second->cancel,1u,__ATOMIC_SEQ_CST);
        return 0;
    }catch(...){return OMNI_INVOCATION_V1_RUNTIME_FAILURE;}
}

extern "C" uint32_t omni_invocation_v1_result_read(
    uint64_t handle,uint8_t* output,uint32_t capacity,uint32_t* copied) {
    try{
        if(!copied||(capacity&&!output))return OMNI_INVOCATION_V1_MALFORMED_INPUT;
        *copied=0;
        std::lock_guard guard(registryMutex);
        auto it=invocations.find(handle);
        if(it==invocations.end())return OMNI_INVOCATION_V1_INVALID_HANDLE;
        Invocation& invocation=*it->second;
        if(!invocation.terminal||invocation.consumed||
           (invocation.status!=OMNI_INVOCATION_V1_SEMANTIC_OK&&
            invocation.status!=OMNI_INVOCATION_V1_SEMANTIC_ERR))
            return OMNI_INVOCATION_V1_INVALID_HANDLE;
        *copied=static_cast<uint32_t>(invocation.result.size());
        if(capacity<invocation.result.size())return OMNI_INVOCATION_V1_LIMIT_EXCEEDED;
        if(!invocation.result.empty())std::memcpy(output,invocation.result.data(),
                                                   invocation.result.size());
        invocation.result.clear();invocation.consumed=true;
        return 0;
    }catch(...){return OMNI_INVOCATION_V1_RUNTIME_FAILURE;}
}

extern "C" uint32_t omni_invocation_v1_module_schema_read(
    uint64_t handle,uint8_t* output,uint32_t capacity,uint32_t* copied) {
    try{
        if(!copied||(capacity&&!output))return OMNI_INVOCATION_V1_MALFORMED_INPUT;
        *copied=0;std::lock_guard guard(registryMutex);
        const auto it=modules.find(handle);
        if(it==modules.end())return OMNI_INVOCATION_V1_INVALID_HANDLE;
        const auto& schema=it->second->sdkSchema;
        if(schema.empty())return OMNI_INVOCATION_V1_UNSUPPORTED_ABI;
        *copied=static_cast<uint32_t>(schema.size());
        if(capacity<schema.size())return OMNI_INVOCATION_V1_LIMIT_EXCEEDED;
        std::memcpy(output,schema.data(),schema.size());return OMNI_INVOCATION_V1_SEMANTIC_OK;
    }catch(...){return OMNI_INVOCATION_V1_RUNTIME_FAILURE;}
}

extern "C" uint32_t omni_invocation_v1_diagnostic_read(
    uint64_t handle,uint8_t* output,uint32_t capacity,uint32_t* copied) {
    try{
        (void)output;(void)capacity;
        if(!copied)return OMNI_INVOCATION_V1_MALFORMED_INPUT;
        *copied=0;
        std::lock_guard guard(registryMutex);
        auto it=invocations.find(handle);
        if(it==invocations.end()||!it->second->terminal)
            return OMNI_INVOCATION_V1_INVALID_HANDLE;
        return 0;
    }catch(...){return OMNI_INVOCATION_V1_RUNTIME_FAILURE;}
}

extern "C" uint32_t omni_invocation_v1_invocation_destroy(uint64_t handle) {
    try{
        std::lock_guard guard(registryMutex);
        auto it=invocations.find(handle);
        if(it==invocations.end())return OMNI_INVOCATION_V1_INVALID_HANDLE;
        if(it->second->running)return OMNI_INVOCATION_V1_BUSY;
        auto module=modules.find(it->second->module);
        if(module==modules.end()||module->second->live==0)
            return OMNI_INVOCATION_V1_INVALID_HANDLE;
        module->second->live--;
        invocations.erase(it);
        return 0;
    }catch(...){return OMNI_INVOCATION_V1_RUNTIME_FAILURE;}
}

extern "C" uint32_t omni_invocation_v1_module_close(uint64_t handle) {
    try{
        std::lock_guard guard(registryMutex);
        auto it=modules.find(handle);
        if(it==modules.end())return OMNI_INVOCATION_V1_INVALID_HANDLE;
        if(it->second->live)return OMNI_INVOCATION_V1_BUSY;
        modules.erase(it);
        return 0;
    }catch(...){return OMNI_INVOCATION_V1_RUNTIME_FAILURE;}
}
