#include "omni.hpp"

#include <arpa/inet.h>
#include <cerrno>
#include <climits>
#include <fcntl.h>
#include <netinet/in.h>
#include <poll.h>
#include <sys/socket.h>
#include <time.h>
#include <unistd.h>

namespace omni {
namespace {
constexpr uint32_t HOST_TCP_LIMIT=1024u*1024u;

uint64_t tcpNowMs(){timespec t{};if(clock_gettime(CLOCK_MONOTONIC,&t)!=0)return 0;return static_cast<uint64_t>(t.tv_sec)*1000u+static_cast<uint64_t>(t.tv_nsec)/1000000u;}
int tcpRemaining(uint64_t end){const auto now=tcpNowMs();if(now>=end)return 0;return static_cast<int>(std::min<uint64_t>(end-now,static_cast<uint64_t>(INT_MAX)));}
bool tcpReady(int fd,short events,uint64_t end){for(;;){pollfd p{fd,events,0};const int r=poll(&p,1,tcpRemaining(end));if(r>0)return (p.revents&(events|POLLERR|POLLHUP))!=0;if(r==0)return false;if(errno!=EINTR)return false;}}

bool endpointAddress(const std::string& endpoint,sockaddr_in& address) {
    const auto colon=endpoint.rfind(':');
    if(colon==std::string::npos||colon==0||colon+1>=endpoint.size())return false;
    const auto host=endpoint.substr(0,colon),rawPort=endpoint.substr(colon+1);
    uint32_t port=0;const auto parsed=std::from_chars(rawPort.data(),rawPort.data()+rawPort.size(),port);
    if(parsed.ec!=std::errc()||parsed.ptr!=rawPort.data()+rawPort.size()||port==0||port>65535)return false;
    address={};address.sin_family=AF_INET;address.sin_port=htons(static_cast<uint16_t>(port));
    return inet_pton(AF_INET,host.c_str(),&address.sin_addr)==1;
}
}

HostTcpResult runHostTcp(const std::string& endpoint,const std::string& payload,
                         uint32_t maxBytes,uint32_t deadlineTicks) {
    if(maxBytes==0)return {2,{}};
    if(maxBytes>HOST_TCP_LIMIT||payload.size()>HOST_TCP_LIMIT)return {5,{}};
    if(deadlineTicks==0)return {6,{}};
    sockaddr_in address{};if(!endpointAddress(endpoint,address))return {2,{}};
    const int fd=socket(AF_INET,SOCK_STREAM,0);if(fd<0)return {4,{}};
    (void)fcntl(fd,F_SETFD,fcntl(fd,F_GETFD)|FD_CLOEXEC);
    (void)fcntl(fd,F_SETFL,fcntl(fd,F_GETFL)|O_NONBLOCK);
    const uint64_t end=tcpNowMs()+deadlineTicks;
    if(connect(fd,reinterpret_cast<const sockaddr*>(&address),sizeof address)<0) {
        if(errno!=EINPROGRESS){close(fd);return {4,{}};}
        if(!tcpReady(fd,POLLOUT,end)){close(fd);return {6,{}};}
        int error=0;socklen_t size=sizeof error;
        if(getsockopt(fd,SOL_SOCKET,SO_ERROR,&error,&size)!=0||error!=0){close(fd);return {4,{}};}
    }
    size_t sent=0;
    while(sent<payload.size()) {
        if(!tcpReady(fd,POLLOUT,end)){close(fd);return {10,{}};}
        const auto n=send(fd,payload.data()+sent,payload.size()-sent,MSG_NOSIGNAL);
        if(n>0)sent+=static_cast<size_t>(n);
        else if(n<0&&(errno==EINTR||errno==EAGAIN||errno==EWOULDBLOCK))continue;
        else {close(fd);return {sent?10u:4u,{}};}
    }
    if(shutdown(fd,SHUT_WR)!=0){close(fd);return {payload.empty()?4u:10u,{}};}
    std::string response;response.reserve(std::min<uint32_t>(maxBytes,4096u));
    unsigned char buffer[4096];
    for(;;) {
        if(!tcpReady(fd,POLLIN,end)){close(fd);return {10,{}};}
        const auto n=recv(fd,buffer,sizeof buffer,0);
        if(n==0)break;
        if(n<0){if(errno==EINTR||errno==EAGAIN||errno==EWOULDBLOCK)continue;close(fd);return {10,{}};}
        if(static_cast<uint64_t>(response.size())+static_cast<uint64_t>(n)>maxBytes){close(fd);return {5,{}};}
        response.append(reinterpret_cast<const char*>(buffer),static_cast<size_t>(n));
    }
    close(fd);return {0,std::move(response)};
}
}
