#include "omni.hpp"

#include <cerrno>
#include <climits>
#include <cstring>
#include <dlfcn.h>
#include <fcntl.h>
#include <poll.h>
#include <sys/prctl.h>
#include <sys/wait.h>
#include <sys/syscall.h>
#include <time.h>
#include <unistd.h>

namespace omni {
namespace {
constexpr uint32_t HOST_FFI_LIMIT=1024u*1024u;
constexpr uint32_t HOST_FFI_TIMEOUT_MS=5000u;
using OmniFfiV1=uint32_t(*)(uint32_t,const uint8_t*,uint32_t,uint8_t*,uint32_t,uint32_t*);

uint64_t ffiNowMs(){timespec t{};if(clock_gettime(CLOCK_MONOTONIC,&t)!=0)return 0;return static_cast<uint64_t>(t.tv_sec)*1000u+static_cast<uint64_t>(t.tv_nsec)/1000000u;}
int ffiRemaining(uint64_t end){const auto now=ffiNowMs();if(now>=end)return 0;return static_cast<int>(std::min<uint64_t>(end-now,static_cast<uint64_t>(INT_MAX)));}
bool ffiReady(int fd,uint64_t end){for(;;){pollfd p{fd,POLLIN,0};const int r=poll(&p,1,ffiRemaining(end));if(r>0)return (p.revents&(POLLIN|POLLHUP))!=0;if(r==0)return false;if(errno!=EINTR)return false;}}
bool ffiRead(int fd,unsigned char* data,size_t size,uint64_t end){size_t used=0;while(used<size){if(!ffiReady(fd,end))return false;const auto n=read(fd,data+used,size-used);if(n>0)used+=static_cast<size_t>(n);else if(n<0&&errno==EINTR)continue;else return false;}return true;}
bool ffiWrite(int fd,const unsigned char* data,size_t size){size_t used=0;while(used<size){const auto n=write(fd,data+used,size-used);if(n>0)used+=static_cast<size_t>(n);else if(n<0&&errno==EINTR)continue;else return false;}return true;}
void putU32(unsigned char* p,uint32_t value){p[0]=static_cast<unsigned char>(value);p[1]=static_cast<unsigned char>(value>>8);p[2]=static_cast<unsigned char>(value>>16);p[3]=static_cast<unsigned char>(value>>24);}
uint32_t getU32(const unsigned char* p){return static_cast<uint32_t>(p[0])|(static_cast<uint32_t>(p[1])<<8)|(static_cast<uint32_t>(p[2])<<16)|(static_cast<uint32_t>(p[3])<<24);}
void ffiReap(pid_t child){if(child<=0)return;(void)kill(child,SIGKILL);int status=0;while(waitpid(child,&status,0)<0&&errno==EINTR){}}
bool ffiWait(pid_t child,uint64_t end,int& status){for(;;){const auto r=waitpid(child,&status,WNOHANG);if(r==child)return true;if(r<0&&errno!=EINTR)return false;if(ffiRemaining(end)==0)return false;timespec pause{0,1000000};while(nanosleep(&pause,&pause)<0&&errno==EINTR){}}}
}

HostFfiResult runHostFfi(const std::string& library,const std::string& payload,uint32_t maxBytes) {
    if(library.empty()||library.find('\0')!=std::string::npos||maxBytes==0)return {2,{}};
    if(payload.size()>HOST_FFI_LIMIT||maxBytes>HOST_FFI_LIMIT)return {5,{}};
    int channel[2];if(pipe(channel)!=0)return {4,{}};
    const long openMax=std::max<long>(64,sysconf(_SC_OPEN_MAX));
    const pid_t child=fork();
    if(child<0){close(channel[0]);close(channel[1]);return {4,{}};}
    if(child==0) {
        // The child loads untrusted native code inside a copy of this process. If that code crashes, a core dump would write out the copy (including policy
        // and source data) and, with a dump handler such as apport or wsl-capture-crash, hold the failure report past the deadline. The child is not dumpable.
        (void)prctl(PR_SET_DUMPABLE,0,0,0,0);
        close(channel[0]);
        int out=channel[1];
        if(out!=3){if(dup2(out,3)<0)_exit(126);close(out);out=3;}
#ifdef SYS_close_range
        if(syscall(SYS_close_range,4u,~0u,0)<0)
#endif
            for(long fd=4;fd<openMax;++fd)close(static_cast<int>(fd));
        uint32_t code=8,outputSize=0;
        std::vector<unsigned char> output(maxBytes);
        void* handle=dlopen(library.c_str(),RTLD_NOW|RTLD_LOCAL);
        if(handle) {
            void* symbol=dlsym(handle,"omni_ffi_v1");
            if(symbol) {
                OmniFfiV1 function=nullptr;
                static_assert(sizeof function==sizeof symbol);
                std::memcpy(&function,&symbol,sizeof function);
                try {
                    const uint32_t status=function(1u,reinterpret_cast<const uint8_t*>(payload.data()),static_cast<uint32_t>(payload.size()),output.data(),maxBytes,&outputSize);
                    code=status==0?0u:9u;
                    if(outputSize>maxBytes)code=5;
                } catch(...) { code=9; outputSize=0; }
            }
            (void)dlclose(handle);
        }
        unsigned char header[8];putU32(header,code);putU32(header+4,code==0?outputSize:0u);
        const bool written=ffiWrite(out,header,sizeof header)&&(code!=0||ffiWrite(out,output.data(),outputSize));
        close(out);_exit(written?0:126);
    }
    close(channel[1]);const uint64_t end=ffiNowMs()+HOST_FFI_TIMEOUT_MS;
    unsigned char header[8];
    if(!ffiRead(channel[0],header,sizeof header,end)) {
        int status=0;if(ffiWait(child,end,status)){close(channel[0]);return {9,{}};}
        close(channel[0]);ffiReap(child);return {10,{}};
    }
    const uint32_t code=getU32(header),size=getU32(header+4);
    if((code!=0&&code!=5&&code!=8&&code!=9)||size>maxBytes||size>HOST_FFI_LIMIT){close(channel[0]);ffiReap(child);return {8,{}};}
    std::string response(size,'\0');
    if(!ffiRead(channel[0],reinterpret_cast<unsigned char*>(response.data()),response.size(),end)){close(channel[0]);ffiReap(child);return {8,{}};}
    int status=0;if(!ffiWait(child,end,status)){close(channel[0]);ffiReap(child);return {10,{}};}
    unsigned char surplus=0;const auto extra=read(channel[0],&surplus,1);close(channel[0]);
    if(extra>0||!WIFEXITED(status)||WEXITSTATUS(status)!=0)return {9,{}};
    if(code)return {code,{}};
    return {0,std::move(response)};
}
}
