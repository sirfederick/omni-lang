#include "omni.hpp"

#include <cerrno>
#include <climits>
#include <csignal>
#include <fcntl.h>
#include <poll.h>
#include <sys/wait.h>
#include <sys/syscall.h>
#include <time.h>
#include <unistd.h>

namespace omni {
namespace {
constexpr uint32_t HOST_FRAME_LIMIT=1024u*1024u;
constexpr unsigned char REQUEST_MAGIC[8]={'O','M','N','I','H','P','1',0};
constexpr unsigned char RESPONSE_MAGIC[8]={'O','M','N','I','H','R','1',0};

uint64_t monotonicMs() {
    timespec now{};
    if(clock_gettime(CLOCK_MONOTONIC,&now)!=0)return 0;
    return static_cast<uint64_t>(now.tv_sec)*1000u+static_cast<uint64_t>(now.tv_nsec)/1000000u;
}

int remainingMs(uint64_t end) {
    const auto now=monotonicMs();
    if(now>=end)return 0;
    return static_cast<int>(std::min<uint64_t>(end-now,static_cast<uint64_t>(INT_MAX)));
}

void appendU32(std::string& out,uint32_t value) {
    for(unsigned shift=0;shift<32;shift+=8)out.push_back(static_cast<char>((value>>shift)&0xffu));
}

uint32_t readU32(const unsigned char* p) {
    return static_cast<uint32_t>(p[0])|(static_cast<uint32_t>(p[1])<<8)|
           (static_cast<uint32_t>(p[2])<<16)|(static_cast<uint32_t>(p[3])<<24);
}

bool waitReady(int fd,short events,uint64_t end) {
    for(;;) {
        pollfd item{fd,events,0};
        const int result=poll(&item,1,remainingMs(end));
        if(result>0)return (item.revents&(events|POLLHUP))!=0;
        if(result==0)return false;
        if(errno!=EINTR)return false;
    }
}

bool writeExact(int fd,const unsigned char* data,size_t size,uint64_t end) {
    size_t offset=0;
    while(offset<size) {
        if(!waitReady(fd,POLLOUT,end))return false;
        const auto n=write(fd,data+offset,size-offset);
        if(n>0)offset+=static_cast<size_t>(n);
        else if(n<0&&(errno==EINTR||errno==EAGAIN||errno==EWOULDBLOCK))continue;
        else return false;
    }
    return true;
}

bool readExact(int fd,unsigned char* data,size_t size,uint64_t end) {
    size_t offset=0;
    while(offset<size) {
        if(!waitReady(fd,POLLIN,end))return false;
        const auto n=read(fd,data+offset,size-offset);
        if(n>0)offset+=static_cast<size_t>(n);
        else if(n<0&&(errno==EINTR||errno==EAGAIN||errno==EWOULDBLOCK))continue;
        else return false;
    }
    return true;
}

void killAndReap(pid_t child) {
    if(child<=0)return;
    (void)kill(child,SIGKILL);
    int status=0;
    while(waitpid(child,&status,0)<0&&errno==EINTR) {}
}

bool waitForChild(pid_t child,uint64_t end,int& status) {
    for(;;) {
        const auto result=waitpid(child,&status,WNOHANG);
        if(result==child)return true;
        if(result<0&&errno!=EINTR)return false;
        if(remainingMs(end)==0)return false;
        timespec pause{0,1000000};
        while(nanosleep(&pause,&pause)<0&&errno==EINTR) {}
    }
}

struct SigpipeGuard {
    struct sigaction oldAction{};
    bool active=false;
    SigpipeGuard() {
        struct sigaction ignore{}; ignore.sa_handler=SIG_IGN; sigemptyset(&ignore.sa_mask);
        active=sigaction(SIGPIPE,&ignore,&oldAction)==0;
    }
    ~SigpipeGuard(){if(active)(void)sigaction(SIGPIPE,&oldAction,nullptr);}
};
}

HostProcessResult runHostProcess(const std::string& adapter,const std::string& payload,
                                 uint32_t maxBytes,uint32_t deadlineTicks) {
    if(adapter.empty()||adapter.find('\0')!=std::string::npos)return {2,{}};
    if(payload.size()>HOST_FRAME_LIMIT||maxBytes>HOST_FRAME_LIMIT)return {5,{}};
    if(maxBytes==0)return {2,{}};
    if(deadlineTicks==0)return {6,{}};
    if(adapter.size()>4096u)return {2,{}};

    int inputPipe[2]{-1,-1},outputPipe[2]{-1,-1};
    if(pipe(inputPipe)!=0)return {4,{}};
    if(pipe(outputPipe)!=0){close(inputPipe[0]);close(inputPipe[1]);return {4,{}};}
    for(const int fd:{inputPipe[0],inputPipe[1],outputPipe[0],outputPipe[1]})
        (void)fcntl(fd,F_SETFD,fcntl(fd,F_GETFD)|FD_CLOEXEC);
    const long openMax=std::max<long>(64,sysconf(_SC_OPEN_MAX));
    const pid_t child=fork();
    if(child<0){for(const int fd:{inputPipe[0],inputPipe[1],outputPipe[0],outputPipe[1]})close(fd);return {4,{}};}
    if(child==0) {
        if(dup2(inputPipe[0],STDIN_FILENO)<0||dup2(outputPipe[1],STDOUT_FILENO)<0)_exit(126);
#ifdef SYS_close_range
        if(syscall(SYS_close_range,3u,~0u,0)<0)
#endif
            for(long fd=3;fd<openMax;++fd)close(static_cast<int>(fd));
        execl(adapter.c_str(),adapter.c_str(),"--omni-host-process-v1",static_cast<char*>(nullptr));
        _exit(errno==ENOENT?127:126);
    }
    close(inputPipe[0]); close(outputPipe[1]);
    (void)fcntl(inputPipe[1],F_SETFL,fcntl(inputPipe[1],F_GETFL)|O_NONBLOCK);
    (void)fcntl(outputPipe[0],F_SETFL,fcntl(outputPipe[0],F_GETFL)|O_NONBLOCK);
    SigpipeGuard sigpipe;
    const uint64_t end=monotonicMs()+deadlineTicks;

    std::string request(reinterpret_cast<const char*>(REQUEST_MAGIC),sizeof REQUEST_MAGIC);
    appendU32(request,static_cast<uint32_t>(adapter.size()));
    appendU32(request,maxBytes);
    appendU32(request,static_cast<uint32_t>(payload.size()));
    request+=adapter; request+=payload;
    if(!writeExact(inputPipe[1],reinterpret_cast<const unsigned char*>(request.data()),request.size(),end)) {
        close(inputPipe[1]);close(outputPipe[0]);killAndReap(child);return {10,{}};
    }
    close(inputPipe[1]);

    unsigned char header[20]{};
    if(!readExact(outputPipe[0],header,sizeof header,end)) {
        int earlyStatus=0;
        if(waitForChild(child,end,earlyStatus)) {
            close(outputPipe[0]);
            if(WIFEXITED(earlyStatus)&&WEXITSTATUS(earlyStatus)==127)return {3,{}};
            return {WIFEXITED(earlyStatus)&&WEXITSTATUS(earlyStatus)==0?8u:9u,{}};
        }
        close(outputPipe[0]);killAndReap(child);return {10,{}};
    }
    if(!std::equal(std::begin(RESPONSE_MAGIC),std::end(RESPONSE_MAGIC),header)) {
        close(outputPipe[0]);killAndReap(child);return {8,{}};
    }
    const uint32_t identitySize=readU32(header+8),statusCode=readU32(header+12),payloadSize=readU32(header+16);
    if(identitySize!=adapter.size()||identitySize>4096u||payloadSize>maxBytes||payloadSize>HOST_FRAME_LIMIT||
       (statusCode!=0&&statusCode!=9)) {
        close(outputPipe[0]);killAndReap(child);return {payloadSize>maxBytes?5u:8u,{}};
    }
    std::string identity(identitySize,'\0'),response(payloadSize,'\0');
    if(!readExact(outputPipe[0],reinterpret_cast<unsigned char*>(identity.data()),identity.size(),end)||identity!=adapter||
       !readExact(outputPipe[0],reinterpret_cast<unsigned char*>(response.data()),response.size(),end)) {
        close(outputPipe[0]);killAndReap(child);return {8,{}};
    }
    int childStatus=0;
    if(!waitForChild(child,end,childStatus)){close(outputPipe[0]);killAndReap(child);return {10,{}};}
    unsigned char surplus=0; const auto extra=read(outputPipe[0],&surplus,1); close(outputPipe[0]);
    if(extra>0)return {8,{}};
    if(!WIFEXITED(childStatus))return {9,{}};
    if(WEXITSTATUS(childStatus)==127)return {3,{}};
    if(WEXITSTATUS(childStatus)!=0)return {9,{}};
    if(statusCode!=0)return {statusCode,{}};
    return {0,std::move(response)};
}
}
