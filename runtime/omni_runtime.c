/* Omni Language 0.2 runtime: bounded sequential hosted runtime, not an OS or sandbox. */
#ifndef _GNU_SOURCE
#define _GNU_SOURCE
#endif
#ifndef _XOPEN_SOURCE
#define _XOPEN_SOURCE 700
#endif
#include <stdint.h>
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <inttypes.h>
#include <string.h>
#include <math.h>
#include <float.h>
#include <errno.h>
#include <limits.h>
#include <unistd.h>
#include <fcntl.h>
#include <poll.h>
#include <signal.h>
#include <setjmp.h>
#include <sys/prctl.h>
#include <sys/wait.h>
#include <sys/syscall.h>
#include <time.h>
#include <arpa/inet.h>
#include <netinet/in.h>
#include <sys/socket.h>
#include <dlfcn.h>
#include "omni_invocation_internal.h"
#include "omni_invocation_v1.h"
#ifndef PATH_MAX
#define PATH_MAX 4096
#endif

typedef struct { uint64_t *items; uint32_t capacity,head,len; int live,closed; } OmniChannel;
typedef struct OmniAllocHeader OmniAllocHeader;
typedef struct { char *p; uint32_t n; } OmniTextSlot;
typedef struct { unsigned char *p; uint32_t n; } OmniBytesSlot;
/* `slots` marks a slot-bearing buffer (CP-01/CP-04, spec/OWNED_SLOTS_CANDIDATE.md): n/8 cells of 8 bytes, one occupancy byte per cell in `occ`, and `tag`, the
   canonical key of the one resource type the cells may own (compared exactly, never as a hash). A byte buffer has slots==0 and none of the three. */
typedef struct { unsigned char *p; uint32_t n,generation; int live; unsigned char *occ; uint32_t *cellgen; char *tag; int slots; uint32_t audit_id; } OmniBufferSlot;
#define OMNI_TEXT_SLOTS 4096u
#define OMNI_TEXT_TOTAL (16u*1024u*1024u)
#define OMNI_TEXT_VALUE_MAX (1024u*1024u)
#define OMNI_BYTES_SLOTS 4096u
#define OMNI_BYTES_TOTAL (16u*1024u*1024u)
#define OMNI_BYTES_VALUE_MAX (1024u*1024u)
#define OMNI_BUFFER_SLOTS 1024u
#define OMNI_HOST_GRANTS 64u
typedef struct { char capability[24]; char scope[PATH_MAX]; uint64_t max_bytes; } OmniHostGrant;
typedef struct {
    uint64_t fuel;
    uint64_t ticks,host_generation,host_not_after_tick;
    uint32_t depth;
    size_t output_bytes;
    uint32_t host_grant_count;
    int host_policy_loaded;
    uint64_t tooling_coverage[2048];
    OmniHostGrant host_grants[OMNI_HOST_GRANTS];
    OmniChannel channels[1024];
    OmniTextSlot text_slots[OMNI_TEXT_SLOTS];
    uint32_t text_count;
    size_t text_bytes;
    OmniBytesSlot bytes_slots[OMNI_BYTES_SLOTS];
    uint32_t bytes_count;
    size_t bytes_total;
    OmniBufferSlot buffer_slots[OMNI_BUFFER_SLOTS];
    size_t buffer_total;
    int invocation_mode;
    sigjmp_buf invocation_jump;
    const uint32_t *cancel_flag;
    uint64_t deadline_ns;
    uint64_t allocation_limit;
    uint64_t allocation_live;
    OmniAllocHeader *allocations;
    uint32_t fault_status;
    uint32_t effect_observation;
    int effect_uncertain_sticky;
    uint8_t trace_id[16];
    FILE *effect_file;
    int effect_fds[8];
    uint32_t effect_fd_count;
    pid_t effect_child;
    struct sigaction effect_old_sigpipe;
    int effect_sigpipe_override;
} OmniRuntimeContext;
/* The context allocation is per generated-program invocation.  The TLS pointer
   selects that invocation only; queues and task-adjacent state are not a
   process-global shared table. */
static _Thread_local OmniRuntimeContext *active_context;
/* Legacy direct runtime-C callers may use Text/Bytes/Buffer without begin/end.
   Hosted invocations never select this storage. */
static OmniRuntimeContext standalone_context;
static int standalone_cleanup_registered;
static void standalone_cleanup(void);
static void audit_report(void);
static _Noreturn void fault(const char *code) {
    if(active_context&&active_context->invocation_mode){
        active_context->fault_status=strcmp(code,"E_MEMORY")==0||
            strcmp(code,"E_TEXT_LIMIT")==0||strcmp(code,"E_BYTES_LIMIT")==0||
            strcmp(code,"E_LIMIT")==0?OMNI_INVOCATION_V1_LIMIT_EXCEEDED:
            strcmp(code,"E_HOST_POLICY")==0?OMNI_INVOCATION_V1_AUTHORITY_DENIED:
            strcmp(code,"E_INVOCATION_DEADLINE")==0?OMNI_INVOCATION_V1_DEADLINE_EXCEEDED:
            strcmp(code,"E_INVOCATION_CANCELLED")==0?OMNI_INVOCATION_V1_CANCELLED:
            OMNI_INVOCATION_V1_RUNTIME_FAILURE;
        siglongjmp(active_context->invocation_jump,1);
    }
    fflush(stdout);
    fprintf(stderr,"omni runtime %s\n",code);
    audit_report();   /* the context is not torn down on this path: say what was still live (OMNI_RESOURCE_AUDIT) */
    exit(70);
}
static int valid_utf8_no_nul(const unsigned char *s,size_t n);
static OmniRuntimeContext *context(void) { if(!active_context)fault("E_RUNTIME_CONTEXT"); return active_context; }
static OmniRuntimeContext *storage_context(void) {
    return active_context?active_context:&standalone_context;
}
static void invocation_effect_dispatched(void) {
    OmniRuntimeContext *c=context();
    if(!c->invocation_mode)return;
    if(c->effect_observation==OMNI_INVOCATION_V1_EFFECT_UNCERTAIN)
        c->effect_uncertain_sticky=1;
    c->effect_observation=OMNI_INVOCATION_V1_EFFECT_UNCERTAIN;
}
static void invocation_effect_acknowledged(void) {
    OmniRuntimeContext *c=context();
    if(c->invocation_mode&&!c->effect_uncertain_sticky)
        c->effect_observation=OMNI_INVOCATION_V1_EFFECT_ACKNOWLEDGED;
}
static void text_cleanup(void);
static void bytes_cleanup(void);
static void buffer_cleanup(void);
static void invocation_safe_point(OmniRuntimeContext *c);
#define text_slots (storage_context()->text_slots)
#define text_count (storage_context()->text_count)
#define text_bytes (storage_context()->text_bytes)
#define bytes_slots (storage_context()->bytes_slots)
#define bytes_count (storage_context()->bytes_count)
#define bytes_total (storage_context()->bytes_total)
#define buffer_slots (storage_context()->buffer_slots)
#define buffer_total (storage_context()->buffer_total)
struct OmniAllocHeader {
    OmniAllocHeader *next,*prev;
    size_t size;
    max_align_t alignment;
};
static void *invocation_raw_calloc(size_t count,size_t size) {return calloc(count,size);}
static void invocation_raw_free(void *p) {free(p);}
static void *invocation_malloc(size_t n) {
    OmniRuntimeContext *c=storage_context();
    if(!active_context&&!standalone_cleanup_registered){
        if(atexit(standalone_cleanup)!=0)fault("E_RUNTIME");
        standalone_cleanup_registered=1;
    }
    if(n==0)n=1;
    if(n>SIZE_MAX-sizeof(OmniAllocHeader)||
       (c->invocation_mode&&
        (c->allocation_live>c->allocation_limit||
         n+sizeof(OmniAllocHeader)>c->allocation_limit-c->allocation_live)))
        fault("E_LIMIT");
    OmniAllocHeader *h=(OmniAllocHeader*)malloc(sizeof(*h)+n);
    if(!h)fault("E_MEMORY");
    h->size=sizeof(*h)+n;h->prev=NULL;h->next=c->allocations;
    if(h->next)h->next->prev=h;
    c->allocations=h;
    c->allocation_live+=(uint64_t)h->size;
    return (void*)(h+1);
}
static void *invocation_calloc(size_t count,size_t size) {
    if(size!=0&&count>SIZE_MAX/size)fault("E_LIMIT");
    const size_t bytes=count*size;void *p=invocation_malloc(bytes);
    memset(p,0,bytes);return p;
}
static void invocation_free(void *p) {
    if(!p)return;
    OmniRuntimeContext *c=storage_context();OmniAllocHeader *h=((OmniAllocHeader*)p)-1;
    if(h->prev)h->prev->next=h->next;else c->allocations=h->next;
    if(h->next)h->next->prev=h->prev;
    c->allocation_live-=(uint64_t)h->size;
    free(h);
}
#define malloc(n) invocation_malloc(n)
#define calloc(n,s) invocation_calloc(n,s)
#define free(p) invocation_free(p)
void omni_tooling_visit(uint64_t id) {
    OmniRuntimeContext *c=context();
    if(id>=131072u)fault("E_INTERNAL");
    c->tooling_coverage[id/64u]|=((uint64_t)1u<<(id%64u));
}
static void tooling_coverage_write(OmniRuntimeContext *c) {
    const char *path=getenv("OMNI_COVERAGE_FILE");
    if(!path||!*path)return;
    if(strlen(path)>=PATH_MAX||path[0]!='/')fault("E_COVERAGE");
    int flags=O_WRONLY|O_CREAT|O_EXCL;
#ifdef O_NOFOLLOW
    flags|=O_NOFOLLOW;
#endif
    int fd=open(path,flags,0600);if(fd<0)fault("E_COVERAGE");
    const char header[]="OMNICOV1\n";
    if(write(fd,header,sizeof header-1)!=(ssize_t)(sizeof header-1)){close(fd);fault("E_COVERAGE");}
    for(uint64_t id=0;id<131072u;id++)if((c->tooling_coverage[id/64u]>>(id%64u))&1u){
        char line[32];int length=snprintf(line,sizeof line,"%" PRIu64 "\n",id);
        if(length<=0||write(fd,line,(size_t)length)!=(ssize_t)length){close(fd);fault("E_COVERAGE");}
    }
    if(fsync(fd)!=0||close(fd)!=0)fault("E_COVERAGE");
}
void omni_runtime_begin(void) {
    if(active_context)fault("E_RUNTIME_REENTRY");
    active_context=(OmniRuntimeContext*)invocation_raw_calloc(1,sizeof *active_context);
    if(!active_context)fault("E_MEMORY");
    active_context->fuel=1000000;
}
void omni_runtime_end(void) {
    OmniRuntimeContext *c=context();
    if(!c->invocation_mode)tooling_coverage_write(c);
    if(c->effect_sigpipe_override)(void)sigaction(SIGPIPE,&c->effect_old_sigpipe,NULL);
    if(c->effect_file)fclose(c->effect_file);
    for(uint32_t i=0;i<c->effect_fd_count;i++)close(c->effect_fds[i]);
    if(c->effect_child>0){
        (void)kill(c->effect_child,SIGKILL);
        int status=0;
        while(waitpid(c->effect_child,&status,0)<0&&errno==EINTR){}
    }
    text_cleanup();
    bytes_cleanup();
    buffer_cleanup();
    for(uint32_t i=0;i<1024;i++)free(c->channels[i].items);
    while(c->allocations){OmniAllocHeader *h=c->allocations;c->allocations=h->next;invocation_raw_free(h);}
    invocation_raw_free(c);
    active_context=NULL;
}
static void standalone_cleanup(void) {
    active_context=NULL;
    text_cleanup();bytes_cleanup();buffer_cleanup();
    while(standalone_context.allocations){
        OmniAllocHeader *h=standalone_context.allocations;
        standalone_context.allocations=h->next;invocation_raw_free(h);
    }
}
/* Fault recovery may jump past an effect's local cleanup. Track every live
   external resource in the invocation context and disarm it on normal close. */
static void effect_track_fd(int fd) {
    OmniRuntimeContext *c=active_context;
    if(!c||!c->invocation_mode||fd<0)return;
    if(c->effect_fd_count>=8)fault("E_LIMIT");
    c->effect_fds[c->effect_fd_count++]=fd;
}
static int effect_close(int fd) {
    OmniRuntimeContext *c=active_context;
    if(c&&c->invocation_mode)
        for(uint32_t i=0;i<c->effect_fd_count;i++)if(c->effect_fds[i]==fd){
            c->effect_fds[i]=c->effect_fds[--c->effect_fd_count];break;
        }
    return close(fd);
}
static int effect_pipe(int fds[2]) {
    if(active_context&&active_context->invocation_mode&&
       active_context->effect_fd_count>6)fault("E_LIMIT");
    const int status=pipe(fds);
    if(status==0){effect_track_fd(fds[0]);effect_track_fd(fds[1]);}
    return status;
}
static int effect_socket(int domain,int type,int protocol) {
    if(active_context&&active_context->invocation_mode&&
       active_context->effect_fd_count>=8)fault("E_LIMIT");
    const int fd=socket(domain,type,protocol);
    effect_track_fd(fd);return fd;
}
static FILE *effect_fopen(const char *path,const char *mode) {
    if(active_context&&active_context->invocation_mode&&active_context->effect_file)
        fault("E_RUNTIME_CONTEXT");
    FILE *file=fopen(path,mode);
    if(file&&active_context&&active_context->invocation_mode){
        active_context->effect_file=file;
    }
    return file;
}
static int effect_fclose(FILE *file) {
    if(active_context&&active_context->invocation_mode&&active_context->effect_file==file)
        active_context->effect_file=NULL;
    return fclose(file);
}
static pid_t effect_fork(void) {
    const pid_t child=fork();
    if(child>0&&active_context&&active_context->invocation_mode)
        active_context->effect_child=child;
    return child;
}
static pid_t effect_waitpid(pid_t child,int *status,int options) {
    const pid_t result=waitpid(child,status,options);
    if(result>0&&active_context&&active_context->invocation_mode&&
       active_context->effect_child==result)active_context->effect_child=0;
    return result;
}
#define close(fd) effect_close(fd)
#define pipe(fds) effect_pipe(fds)
#define socket(domain,type,protocol) effect_socket(domain,type,protocol)
#define fopen(path,mode) effect_fopen(path,mode)
#define fclose(file) effect_fclose(file)
#define fork() effect_fork()
#define waitpid(child,status,options) effect_waitpid(child,status,options)
static int parse_u64_strict(const char *raw,uint64_t *out) {
    if(!raw||!*raw||*raw=='-'||*raw=='+')return 0;
    errno=0; char *end=NULL; unsigned long long value=strtoull(raw,&end,10);
    if(errno||!end||*end!='\0'||value==0)return 0;
    *out=(uint64_t)value; return 1;
}
static int split4(char *line,char **parts) {
    parts[0]=line;
    for(int i=1;i<4;i++){char *bar=strchr(parts[i-1],'|');if(!bar)return 0;*bar='\0';parts[i]=bar+1;}
    return strchr(parts[3],'|')==NULL;
}
static int path_has_parent(const char *path) {
    return strcmp(path,"..")==0||strncmp(path,"../",3)==0||strstr(path,"/../")!=NULL||
           (strlen(path)>=3&&strcmp(path+strlen(path)-3,"/..")==0);
}
static int canonical_existing_path(const char *raw,char out[PATH_MAX]) {
    if(!raw||raw[0]!='/'||strcmp(raw,"/")==0||path_has_parent(raw))return 0;
    return realpath(raw,out)!=NULL&&strcmp(out,"/")!=0;
}
static int canonical_host_subject(const char *raw,int allow_missing,char out[PATH_MAX]) {
    if(!raw||raw[0]!='/'||path_has_parent(raw))return 0;
    if(realpath(raw,out))return strcmp(out,"/")!=0;
    if(!allow_missing)return 0;
    char copy[PATH_MAX],parent[PATH_MAX],resolved[PATH_MAX];
    size_t n=strlen(raw); if(n==0||n>=sizeof copy)return 0; memcpy(copy,raw,n+1);
    for(;;){
        char *slash=strrchr(copy,'/'); if(!slash)return 0;
        size_t suffix=(size_t)(slash-copy);
        if(slash==copy){
            if(!realpath("/",parent))return 0;
            int written=snprintf(resolved,sizeof resolved,"%s",raw);
            if(written<=0||(size_t)written>=sizeof resolved)return 0;
            memcpy(out,resolved,(size_t)written+1); return strcmp(out,"/")!=0;
        }
        *slash='\0';
        if(realpath(copy,parent)){
            int written=snprintf(resolved,sizeof resolved,"%s%s",parent,raw+suffix);
            if(written<=0||(size_t)written>=sizeof resolved)return 0;
            memcpy(out,resolved,(size_t)written+1); return strcmp(out,"/")!=0;
        }
    }
}
/* Same grammar as endpointScope in host_policy.cpp: four decimal octets of 1..3 digits (<= 255), ':' and a port of 1..10 digits with value 1..65535.
   No sign, no space, no trailing text: sscanf accepted all of those. */
static int numeric_endpoint(const char *raw) {
    const char *p=raw;
    for(int i=0;i<4;i++) {
        unsigned value=0; size_t digits=0;
        while(*p>='0'&&*p<='9'&&digits<4){value=value*10u+(unsigned)(*p-'0');++p;++digits;}
        if(digits==0||digits>3||value>255u)return 0;
        if(i<3){if(*p!='.')return 0;++p;}
    }
    if(*p!=':')return 0;
    ++p;
    size_t digits=0; unsigned long port=0;
    while(*p>='0'&&*p<='9'){if(++digits>10)return 0;port=port*10ul+(unsigned long)(*p-'0');++p;}
    return digits>0&&*p=='\0'&&port>0&&port<=65535ul;
}
static int host_capability(const char *cap) {
    return strcmp(cap,"fs.read")==0||strcmp(cap,"fs.write")==0||strcmp(cap,"process.spawn")==0||
           strcmp(cap,"net.connect")==0||strcmp(cap,"ffi.call")==0;
}
static int path_inside(const char *root,const char *candidate) {
    size_t n=strlen(root); return strncmp(root,candidate,n)==0&&(candidate[n]=='\0'||candidate[n]=='/');
}
static void configure_policy_file(FILE *policy) {
    OmniRuntimeContext *c=context();
    char line[PATH_MAX+128]; size_t total=0; unsigned line_no=0;
    while(fgets(line,sizeof line,policy)) {
        size_t n=strlen(line); total+=n; ++line_no;
        if(total>65536u||n==0||line[n-1]!='\n'||!valid_utf8_no_nul((const unsigned char*)line,n)) {fclose(policy);fault("E_HOST_POLICY");}
        line[--n]='\0'; if(n&&line[n-1]=='\r')line[--n]='\0'; if(n==0){fclose(policy);fault("E_HOST_POLICY");}
        if(line_no==1){if(strcmp(line,"OHP1")!=0){fclose(policy);fault("E_HOST_POLICY");}continue;}
        if(line_no==2){if(strncmp(line,"generation|",11)!=0||!parse_u64_strict(line+11,&c->host_generation)){fclose(policy);fault("E_HOST_POLICY");}continue;}
        if(line_no==3){if(strncmp(line,"not_after_tick|",15)!=0||!parse_u64_strict(line+15,&c->host_not_after_tick)){fclose(policy);fault("E_HOST_POLICY");}continue;}
        if(c->host_grant_count>=OMNI_HOST_GRANTS){fclose(policy);fault("E_HOST_POLICY");}
        char *part[4]; if(!split4(line,part)||strcmp(part[0],"grant")!=0||!host_capability(part[1])){fclose(policy);fault("E_HOST_POLICY");}
        uint64_t max_bytes=0; if(!parse_u64_strict(part[3],&max_bytes)||max_bytes>1048576u){fclose(policy);fault("E_HOST_POLICY");}
        char scope[PATH_MAX];
        if(strcmp(part[1],"net.connect")==0){if(!numeric_endpoint(part[2])||strlen(part[2])>=sizeof scope){fclose(policy);fault("E_HOST_POLICY");}strcpy(scope,part[2]);}
        else if(!canonical_existing_path(part[2],scope)){fclose(policy);fault("E_HOST_POLICY");}
        for(uint32_t i=0;i<c->host_grant_count;i++)if(strcmp(c->host_grants[i].capability,part[1])==0&&strcmp(c->host_grants[i].scope,scope)==0){fclose(policy);fault("E_HOST_POLICY");}
        OmniHostGrant *grant=&c->host_grants[c->host_grant_count++];
        if(strlen(part[1])>=sizeof grant->capability){fclose(policy);fault("E_HOST_POLICY");}
        strcpy(grant->capability,part[1]); strcpy(grant->scope,scope); grant->max_bytes=max_bytes;
    }
    if(ferror(policy)||fclose(policy)!=0||line_no<4||c->host_grant_count==0)fault("E_HOST_POLICY");
    c->host_policy_loaded=1;
}
void omni_runtime_configure(int argc,char **argv) {
    if(argc==1)return;
    if(argc!=3||strcmp(argv[1],"--omni-host-policy")!=0)fault("E_CLI");
    FILE *policy=fopen(argv[2],"rb");if(!policy)fault("E_HOST_POLICY");
    configure_policy_file(policy);
}
static void configure_policy_bytes(const uint8_t *policy,uint32_t length) {
    if(length==0)return;
    if(!policy||length>65536u)fault("E_HOST_POLICY");
    FILE *stream=fmemopen((void*)policy,length,"r");
    if(!stream)fault("E_HOST_POLICY");
    configure_policy_file(stream);
}
uint32_t omni_runtime_execute_invocation_v1(
    OmniModuleBodyV1 body,uint32_t mode,
    const uint8_t *request,uint32_t request_len,
    const uint8_t *policy,uint32_t policy_len,uint64_t policy_generation,
    uint64_t deadline_ns,uint64_t allocation_limit,
    const uint8_t trace_id[16],const uint32_t *cancel_flag,
    uint8_t *result,uint32_t result_capacity,
    uint32_t *result_len,uint32_t *effect_observation) {
    if(!body||!result_len||!effect_observation||!trace_id||!cancel_flag||
       (request_len&&!request)||(policy_len&&!policy))
        return OMNI_INVOCATION_V1_MALFORMED_INPUT;
    *result_len=0;*effect_observation=OMNI_INVOCATION_V1_EFFECT_NONE;
    if(active_context)return OMNI_INVOCATION_V1_BUSY;
    active_context=(OmniRuntimeContext*)invocation_raw_calloc(1,sizeof *active_context);
    if(!active_context)return OMNI_INVOCATION_V1_LIMIT_EXCEEDED;
    active_context->fuel=1000000;
    OmniRuntimeContext *c=active_context;
    c->invocation_mode=1;c->cancel_flag=cancel_flag;c->deadline_ns=deadline_ns;
    c->allocation_limit=allocation_limit;c->allocation_live=sizeof(*c);
    memcpy(c->trace_id,trace_id,16);
    if(c->allocation_live>allocation_limit){omni_runtime_end();return OMNI_INVOCATION_V1_LIMIT_EXCEEDED;}
    volatile uint32_t status=OMNI_INVOCATION_V1_RUNTIME_FAILURE;
    if(sigsetjmp(c->invocation_jump,1)==0){
        invocation_safe_point(c);
        configure_policy_bytes(policy,policy_len);
        if((policy_len==0&&policy_generation!=0)||
           (policy_len!=0&&(policy_generation==0||policy_generation!=c->host_generation)))
            fault("E_HOST_POLICY");
        status=body(mode,request,request_len,result,result_capacity,result_len);
        invocation_safe_point(c);
    }else{
        status=c->fault_status;
        *result_len=0;
    }
    *effect_observation=c->effect_observation;
    if(c->effect_observation==OMNI_INVOCATION_V1_EFFECT_UNCERTAIN&&
       status!=OMNI_INVOCATION_V1_SEMANTIC_OK&&status!=OMNI_INVOCATION_V1_SEMANTIC_ERR)
        status=OMNI_INVOCATION_V1_UNKNOWN_OUTCOME;
    omni_runtime_end();
    return status;
}
static int host_allowed(const char *capability,const char *subject,uint64_t bytes,int allow_missing) {
    OmniRuntimeContext *c=context(); if(!c->host_policy_loaded||c->host_generation==0||c->ticks>c->host_not_after_tick)return 0;
    char canonical[PATH_MAX];
    if(strcmp(capability,"net.connect")==0){if(!numeric_endpoint(subject)||strlen(subject)>=sizeof canonical)return 0;strcpy(canonical,subject);}
    else {
        int filesystem=strcmp(capability,"fs.read")==0||strcmp(capability,"fs.write")==0;
        if(filesystem){
            if(!subject||subject[0]!='/'||strcmp(subject,"/")==0||path_has_parent(subject))return 0;
            int lexical_candidate=0;
            for(uint32_t i=0;i<c->host_grant_count;i++){
                OmniHostGrant *grant=&c->host_grants[i];
                if(strcmp(grant->capability,capability)==0&&bytes<=grant->max_bytes&&path_inside(grant->scope,subject)){lexical_candidate=1;break;}
            }
            if(!lexical_candidate)return 0;
        }
        if(!canonical_host_subject(subject,allow_missing,canonical))return 0;
    }
    for(uint32_t i=0;i<c->host_grant_count;i++){
        OmniHostGrant *grant=&c->host_grants[i]; if(strcmp(grant->capability,capability)!=0||bytes>grant->max_bytes)continue;
        if(strcmp(capability,"fs.read")==0||strcmp(capability,"fs.write")==0){if(path_inside(grant->scope,canonical))return 1;}
        else if(strcmp(grant->scope,canonical)==0)return 1;
    }
    return 0;
}
static void invocation_safe_point(OmniRuntimeContext *c) {
    if(!c->invocation_mode)return;
    if(c->cancel_flag&&__atomic_load_n(c->cancel_flag,__ATOMIC_ACQUIRE))
        fault("E_INVOCATION_CANCELLED");
    struct timespec now;
    if(clock_gettime(CLOCK_MONOTONIC,&now)!=0)fault("E_INVOCATION_CLOCK");
    uint64_t current=(uint64_t)now.tv_sec*1000000000u+(uint64_t)now.tv_nsec;
    if(current>=c->deadline_ns)fault("E_INVOCATION_DEADLINE");
}
void omni_tick(void) { OmniRuntimeContext *c=context(); invocation_safe_point(c); if(c->fuel==0)fault("E_FUEL"); --c->fuel; ++c->ticks; }
void omni_enter(void) { OmniRuntimeContext *c=context(); invocation_safe_point(c); if(c->depth>=128)fault("E_DEPTH"); ++c->depth; }
void omni_leave(void) { OmniRuntimeContext *c=context(); if(c->depth==0)fault("E_INTERNAL"); --c->depth; }
uint64_t omni_channel_new(uint32_t capacity) {
    OmniRuntimeContext *c=context();
    if(capacity==0||capacity>1024) return 0;
    for(uint32_t i=0;i<1024;i++)if(!c->channels[i].live){
        uint64_t *items=(uint64_t*)calloc(capacity,sizeof(uint64_t)); if(!items)return 0;
        c->channels[i]=(OmniChannel){items,capacity,0,0,1,0}; return (uint64_t)i+1u;
    }
    return 0;
}
static OmniChannel *channel_get(uint64_t handle) {
    OmniRuntimeContext *c=context();
    if(handle==0||handle>1024||!c->channels[handle-1u].live)fault("E_CHANNEL_HANDLE");
    return &c->channels[handle-1u];
}
uint32_t omni_channel_send(uint64_t handle,uint64_t value) {
    OmniChannel *c=channel_get(handle); if(c->closed)return 2;
    if(c->len>=c->capacity)return 3;
    c->items[(c->head+c->len)%c->capacity]=value; ++c->len; return 0;
}
uint32_t omni_channel_receive(uint64_t handle,uint64_t *out_value) {
    OmniChannel *c=channel_get(handle); if(!out_value)fault("E_CHANNEL_OUT");
    if(c->len==0)return c->closed?1:3;
    *out_value=c->items[c->head]; c->head=(c->head+1u)%c->capacity; --c->len; return 0;
}
uint32_t omni_channel_close(uint64_t handle) { channel_get(handle)->closed=1; return 0; }
uint32_t omni_add(uint32_t a,uint32_t b) { uint64_t r=(uint64_t)a+b; if(r>UINT32_MAX)fault("E_OVERFLOW"); return (uint32_t)r; }
uint32_t omni_sub(uint32_t a,uint32_t b) { if(a<b)fault("E_OVERFLOW"); return a-b; }
uint32_t omni_mul(uint32_t a,uint32_t b) { uint64_t r=(uint64_t)a*b; if(r>UINT32_MAX)fault("E_OVERFLOW"); return (uint32_t)r; }
uint32_t omni_div(uint32_t a,uint32_t b) { if(!b)fault("E_DIVZERO"); return a/b; }
uint32_t omni_rem(uint32_t a,uint32_t b) { if(!b)fault("E_DIVZERO"); return a%b; }

#define DEF_UINT_OPS(T,N,MAXV) \
T omni_##N##_add(T a,T b){T r;if(__builtin_add_overflow(a,b,&r))fault("E_OVERFLOW");return r;} \
T omni_##N##_sub(T a,T b){T r;if(__builtin_sub_overflow(a,b,&r))fault("E_OVERFLOW");return r;} \
T omni_##N##_mul(T a,T b){T r;if(__builtin_mul_overflow(a,b,&r))fault("E_OVERFLOW");return r;} \
T omni_##N##_div(T a,T b){if(!b)fault("E_DIVZERO");return (T)(a/b);} \
T omni_##N##_rem(T a,T b){if(!b)fault("E_DIVZERO");return (T)(a%b);} \
T omni_##N##_sat_add(T a,T b){T r;return __builtin_add_overflow(a,b,&r)?(T)(MAXV):r;} \
T omni_##N##_sat_sub(T a,T b){T r;return __builtin_sub_overflow(a,b,&r)?(T)0:r;} \
T omni_##N##_sat_mul(T a,T b){T r;return __builtin_mul_overflow(a,b,&r)?(T)(MAXV):r;}

#define DEF_SINT_OPS(T,N,MINV,MAXV) \
T omni_##N##_add(T a,T b){T r;if(__builtin_add_overflow(a,b,&r))fault("E_OVERFLOW");return r;} \
T omni_##N##_sub(T a,T b){T r;if(__builtin_sub_overflow(a,b,&r))fault("E_OVERFLOW");return r;} \
T omni_##N##_mul(T a,T b){T r;if(__builtin_mul_overflow(a,b,&r))fault("E_OVERFLOW");return r;} \
T omni_##N##_div(T a,T b){if(!b)fault("E_DIVZERO");if(a==(T)(MINV)&&b==(T)-1)fault("E_OVERFLOW");return (T)(a/b);} \
T omni_##N##_rem(T a,T b){if(!b)fault("E_DIVZERO");if(a==(T)(MINV)&&b==(T)-1)fault("E_OVERFLOW");return (T)(a%b);} \
T omni_##N##_sat_add(T a,T b){T r;if(!__builtin_add_overflow(a,b,&r))return r;return a>=0?(T)(MAXV):(T)(MINV);} \
T omni_##N##_sat_sub(T a,T b){T r;if(!__builtin_sub_overflow(a,b,&r))return r;return (a>=0&&b<0)?(T)(MAXV):(T)(MINV);} \
T omni_##N##_sat_mul(T a,T b){T r;if(!__builtin_mul_overflow(a,b,&r))return r;return ((a<0)==(b<0))?(T)(MAXV):(T)(MINV);}

DEF_UINT_OPS(uint8_t,u8,UINT8_MAX)
DEF_UINT_OPS(uint16_t,u16,UINT16_MAX)
DEF_UINT_OPS(uint32_t,u32,UINT32_MAX)
DEF_UINT_OPS(uint64_t,u64,UINT64_MAX)
DEF_SINT_OPS(int8_t,i8,INT8_MIN,INT8_MAX)
DEF_SINT_OPS(int16_t,i16,INT16_MIN,INT16_MAX)
DEF_SINT_OPS(int32_t,i32,INT32_MIN,INT32_MAX)
DEF_SINT_OPS(int64_t,i64,INT64_MIN,INT64_MAX)

uint64_t omni_cast_int(uint64_t bits,uint32_t src_signed,uint32_t src_width,uint32_t dst_signed,uint32_t dst_width) {
    unsigned __int128 umask=src_width==64?(unsigned __int128)UINT64_MAX:(((unsigned __int128)1<<src_width)-1);
    unsigned __int128 raw=((unsigned __int128)bits)&umask;
    __int128 v;
    if(src_signed){
        if(src_width==64)v=(int64_t)bits;
        else { unsigned __int128 sign=(unsigned __int128)1<<(src_width-1); v=(raw&sign)?(__int128)(raw-((unsigned __int128)1<<src_width)):(__int128)raw; }
    } else v=(__int128)raw;
    if(dst_signed){
        __int128 min=dst_width==64?(__int128)INT64_MIN:-((__int128)1<<(dst_width-1));
        __int128 max=dst_width==64?(__int128)INT64_MAX:(((__int128)1<<(dst_width-1))-1);
        if(v<min||v>max)fault("E_CAST_RANGE");
    } else {
        unsigned __int128 max=dst_width==64?(unsigned __int128)UINT64_MAX:(((unsigned __int128)1<<dst_width)-1);
        if(v<0||(unsigned __int128)v>max)fault("E_CAST_RANGE");
    }
    if(dst_width==64)return (uint64_t)v;
    return ((uint64_t)v)&((UINT64_C(1)<<dst_width)-1);
}

uint64_t omni_cast_float_to_int(double value,uint32_t dst_signed,uint32_t dst_width) {
    if(!isfinite(value))fault("E_CAST_RANGE");
    long double v=(long double)value;
    if(dst_signed){
        long double minv,maxv;
        if(dst_width==64){ minv=(long double)INT64_MIN; maxv=(long double)INT64_MAX; }
        else {
            uint64_t mag=UINT64_C(1)<<(dst_width-1);
            minv=-(long double)mag;
            maxv=(long double)(mag-1u);
        }
        if(v<minv||v>maxv)fault("E_CAST_RANGE");
        int64_t out=(int64_t)v;
        if(dst_width==64)return (uint64_t)out;
        return ((uint64_t)out)&((UINT64_C(1)<<dst_width)-1);
    }
    long double maxv=dst_width==64?(long double)UINT64_MAX:(long double)((UINT64_C(1)<<dst_width)-1u);
    if(v<0.0L||v>maxv)fault("E_CAST_RANGE");
    uint64_t out=(uint64_t)v;
    if(dst_width==64)return out;
    return out&((UINT64_C(1)<<dst_width)-1);
}

void omni_print_text(const char *s,uint32_t n) {
    OmniRuntimeContext *c=context();
    if((size_t)n+1>1048576-c->output_bytes)fault("E_OUTPUT_LIMIT");
    if((n&&fwrite(s,1,n,stdout)!=n)||fputc('\n',stdout)==EOF)fault("E_IO");
    c->output_bytes+=(size_t)n+1;
}
void omni_print_u32(uint32_t n) { char buf[16]; int len=snprintf(buf,sizeof buf,"%" PRIu32,n); if(len<0)fault("E_IO"); omni_print_text(buf,(uint32_t)len); }
void omni_print_u64(uint64_t n) { char buf[32]; int len=snprintf(buf,sizeof buf,"%" PRIu64,n); if(len<0)fault("E_IO"); omni_print_text(buf,(uint32_t)len); }
void omni_print_i64(int64_t n) { char buf[32]; int len=snprintf(buf,sizeof buf,"%" PRId64,n); if(len<0)fault("E_IO"); omni_print_text(buf,(uint32_t)len); }
void omni_print_f32(float n) { char buf[64]; int len=snprintf(buf,sizeof buf,"%.9g",(double)n); if(len<0||(size_t)len>=sizeof buf)fault("E_IO"); omni_print_text(buf,(uint32_t)len); }
void omni_print_f64(double n) { char buf[96]; int len=snprintf(buf,sizeof buf,"%.17g",n); if(len<0||(size_t)len>=sizeof buf)fault("E_IO"); omni_print_text(buf,(uint32_t)len); }
void omni_print_bool(uint32_t b) { omni_print_text(b?"true":"false",b?4u:5u); }

/* Text values belong to the current invocation context. */

static void text_cleanup(void) {
    for(uint32_t i=0;i<text_count;i++){ free(text_slots[i].p); text_slots[i].p=NULL; text_slots[i].n=0; }
    text_count=0; text_bytes=0;
}
static int valid_utf8_no_nul(const unsigned char *s,size_t n) {
    size_t i=0;
    while(i<n){
        unsigned c=s[i++]; if(c==0)return 0; if(c<0x80)continue;
        unsigned cp,min; int k;
        if((c&0xe0)==0xc0){k=1;cp=c&0x1f;min=0x80;}
        else if((c&0xf0)==0xe0){k=2;cp=c&0x0f;min=0x800;}
        else if((c&0xf8)==0xf0){k=3;cp=c&0x07;min=0x10000;}
        else return 0;
        while(k--){ if(i>=n)return 0; unsigned d=s[i++]; if((d&0xc0)!=0x80)return 0; cp=(cp<<6)|(d&0x3f); }
        if(cp<min||cp>0x10ffff||(cp>=0xd800&&cp<=0xdfff))return 0;
    }
    return 1;
}
int omni_invocation_text_valid_v1(const uint8_t *s,uint32_t n) {
    return (n==0||s!=NULL)&&valid_utf8_no_nul(s,n);
}
static uint64_t text_alloc(const char *p,uint32_t n) {
    if(n>OMNI_TEXT_VALUE_MAX)fault("E_TEXT_LIMIT");
    if(text_count>=OMNI_TEXT_SLOTS || text_bytes+(size_t)n+1>OMNI_TEXT_TOTAL)fault("E_MEMORY");
    if(!valid_utf8_no_nul((const unsigned char*)p,n))fault("E_UTF8");
    char *q=(char*)malloc((size_t)n+1); if(!q)fault("E_MEMORY");
    if(n)memcpy(q,p,n); q[n]='\0';
    text_slots[text_count]=(OmniTextSlot){q,n}; text_bytes+=(size_t)n+1; return (uint64_t)(++text_count);
}
static OmniTextSlot text_get(uint64_t h) {
    if(h==0 || h>text_count || text_slots[h-1].p==NULL)fault("E_TEXT_HANDLE");
    return text_slots[h-1];
}
uint64_t omni_text_new(const char *p,uint32_t n) { return text_alloc(p,n); }
uint32_t omni_invocation_text_copy_v1(uint64_t h,uint8_t *out,uint32_t cap) {
    OmniTextSlot t=text_get(h);if(cap<t.n||(!out&&t.n))return UINT32_MAX;
    if(t.n)memcpy(out,t.p,t.n);return t.n;
}
uint32_t omni_text_len(uint64_t h) { return text_get(h).n; } /* legacy byte length */
static int unicode_scalar_valid(uint32_t cp) {
    return cp<=0x10ffffu && !(cp>=0xd800u&&cp<=0xdfffu);
}
static int utf8_next_scalar(const unsigned char *s,uint32_t n,uint32_t *io_pos,uint32_t *out_cp) {
    uint32_t p=*io_pos; if(p>=n)return 0;
    unsigned c=s[p++],cp,min; int k;
    if(c<0x80u){*io_pos=p;*out_cp=c;return 1;}
    if((c&0xe0u)==0xc0u){k=1;cp=c&0x1fu;min=0x80u;}
    else if((c&0xf0u)==0xe0u){k=2;cp=c&0x0fu;min=0x800u;}
    else if((c&0xf8u)==0xf0u){k=3;cp=c&0x07u;min=0x10000u;}
    else return -1;
    while(k--){ if(p>=n)return -1; unsigned x=s[p++]; if((x&0xc0u)!=0x80u)return -1; cp=(cp<<6)|(x&0x3fu); }
    if(cp<min||!unicode_scalar_valid(cp))return -1;
    *io_pos=p;*out_cp=cp;return 1;
}
static uint32_t utf8_encode_scalar(uint32_t cp,unsigned char out[4]) {
    if(!unicode_scalar_valid(cp))return 0;
    if(cp<=0x7fu){out[0]=(unsigned char)cp;return 1;}
    if(cp<=0x7ffu){out[0]=(unsigned char)(0xc0u|(cp>>6));out[1]=(unsigned char)(0x80u|(cp&0x3fu));return 2;}
    if(cp<=0xffffu){out[0]=(unsigned char)(0xe0u|(cp>>12));out[1]=(unsigned char)(0x80u|((cp>>6)&0x3fu));out[2]=(unsigned char)(0x80u|(cp&0x3fu));return 3;}
    out[0]=(unsigned char)(0xf0u|(cp>>18));out[1]=(unsigned char)(0x80u|((cp>>12)&0x3fu));out[2]=(unsigned char)(0x80u|((cp>>6)&0x3fu));out[3]=(unsigned char)(0x80u|(cp&0x3fu));return 4;
}
uint32_t omni_char_from_u32(uint32_t cp,uint32_t *out_cp) {
    if(!out_cp)return 2; *out_cp=0;
    if(!unicode_scalar_valid(cp))return 1;
    *out_cp=cp; return 0;
}
uint32_t omni_char_codepoint(uint32_t cp) { if(!unicode_scalar_valid(cp))fault("E_CHAR_RANGE"); return cp; }
void omni_print_char(uint32_t cp) {
    unsigned char buf[4]; uint32_t n=utf8_encode_scalar(cp,buf); if(!n)fault("E_CHAR_RANGE");
    omni_print_text((const char*)buf,n);
}
uint32_t omni_text_byte_len(uint64_t h) { return text_get(h).n; }
uint32_t omni_text_equal(uint64_t a,uint64_t b) {
    OmniTextSlot x=text_get(a),y=text_get(b);
    return x.n==y.n && (x.n==0u || memcmp(x.p,y.p,x.n)==0);
}
uint32_t omni_text_scalar_len(uint64_t h) {
    OmniTextSlot t=text_get(h); uint32_t p=0,count=0,cp=0;
    while(p<t.n){ int r=utf8_next_scalar((const unsigned char*)t.p,t.n,&p,&cp); if(r<=0)fault("E_UTF8"); if(count==UINT32_MAX)fault("E_LIMIT"); ++count; }
    return count;
}
uint32_t omni_text_scalar_at(uint64_t h,uint32_t index,uint32_t *out_cp) {
    if(!out_cp)return 2; *out_cp=0;
    OmniTextSlot t=text_get(h); uint32_t p=0,count=0,cp=0;
    while(p<t.n){
        int r=utf8_next_scalar((const unsigned char*)t.p,t.n,&p,&cp); if(r<=0)fault("E_UTF8");
        if(count++==index){*out_cp=cp;return 0;}
    }
    return 1;
}
uint32_t omni_text_from_char(uint32_t cp,uint64_t *out_h) {
    if(!out_h)return 2; *out_h=0;
    if(!unicode_scalar_valid(cp))return 1;
    if(cp==0u)return 1; /* Text invariant: embedded NUL remains forbidden. */
    unsigned char buf[4]; uint32_t n=utf8_encode_scalar(cp,buf); if(!n)return 1;
    *out_h=text_alloc((const char*)buf,n); return 0;
}

uint64_t omni_text_concat(uint64_t a,uint64_t b) {
    OmniTextSlot x=text_get(a), y=text_get(b);
    if((uint64_t)x.n+y.n>OMNI_TEXT_VALUE_MAX)fault("E_TEXT_LIMIT");
    size_t n=(size_t)x.n+y.n; char *tmp=(char*)malloc(n?n:1); if(!tmp)fault("E_MEMORY");
    if(x.n)memcpy(tmp,x.p,x.n); if(y.n)memcpy(tmp+x.n,y.p,y.n);
    uint64_t h=text_alloc(tmp,(uint32_t)n); free(tmp); return h;
}
void omni_print_dyn_text(uint64_t h) { OmniTextSlot t=text_get(h); omni_print_text(t.p,t.n); }

/* Recoverable file errors: 0 OK, 1 open/path, 2 read/write, 3 size, 4 invalid UTF-8. */
uint32_t omni_file_read_text(uint64_t path_h,uint64_t *out_h) {
    if(!out_h)return 2; *out_h=0;
    OmniTextSlot path=text_get(path_h);
    if(!host_allowed("fs.read",path.p,0,1))return 1;
    FILE *f=fopen(path.p,"rb"); if(!f)return 3;
    if(fseek(f,0,SEEK_END)!=0){fclose(f);return 4;}
    long z=ftell(f); if(z<0){fclose(f);return 4;} if((unsigned long)z>OMNI_TEXT_VALUE_MAX){fclose(f);return 5;}
    if(!host_allowed("fs.read",path.p,(uint64_t)z,0)){fclose(f);return 1;}
    if(fseek(f,0,SEEK_SET)!=0){fclose(f);return 4;}
    size_t n=(size_t)z; char *buf=(char*)malloc(n?n:1); if(!buf){fclose(f);fault("E_MEMORY");}
    if(n && fread(buf,1,n,f)!=n){free(buf);fclose(f);return 4;} if(fclose(f)!=0){free(buf);return 4;}
    if(!valid_utf8_no_nul((const unsigned char*)buf,n)){free(buf);return 2;}
    *out_h=text_alloc(buf,(uint32_t)n); free(buf); return 0;
}
uint32_t omni_file_write_text(uint64_t path_h,uint64_t text_h) {
    OmniTextSlot path=text_get(path_h), text=text_get(text_h);
    if(!host_allowed("fs.write",path.p,text.n,1))return 1;
    FILE *f=fopen(path.p,"wb"); if(!f)return 3;
    if(text.n && fwrite(text.p,1,text.n,f)!=text.n){fclose(f);return 4;}
    if(fflush(f)!=0 || fclose(f)!=0)return 4;
    return 0;
}

/* Inherited restricted Resource/Buffer proving subset.
   Bytes are immutable values. Buffer is an owned mutable resource represented by an opaque
   slot+generation handle; no pointer value is exposed to Omni source or component contracts. */
/* Bytes values belong to the current invocation context. */
static void bytes_cleanup(void){ for(uint32_t i=0;i<bytes_count;i++){free(bytes_slots[i].p);bytes_slots[i].p=NULL;bytes_slots[i].n=0;} bytes_count=0;bytes_total=0; }
static uint64_t bytes_alloc(const unsigned char *p,uint32_t n){
    if(n>OMNI_BYTES_VALUE_MAX)fault("E_BYTES_LIMIT");
    if(bytes_count>=OMNI_BYTES_SLOTS || bytes_total+(size_t)n>OMNI_BYTES_TOTAL)fault("E_MEMORY");
    unsigned char *q=(unsigned char*)malloc(n?n:1); if(!q)fault("E_MEMORY"); if(n)memcpy(q,p,n);
    bytes_slots[bytes_count]=(OmniBytesSlot){q,n}; bytes_total+=n; return (uint64_t)(++bytes_count);
}
static OmniBytesSlot bytes_get(uint64_t h){ if(h==0||h>bytes_count||bytes_slots[h-1].p==NULL)fault("E_BYTES_HANDLE"); return bytes_slots[h-1]; }
uint64_t omni_invocation_bytes_new_v1(const uint8_t *p,uint32_t n) {return bytes_alloc(p,n);}
uint32_t omni_invocation_bytes_copy_v1(uint64_t h,uint8_t *out,uint32_t cap) {
    OmniBytesSlot b=bytes_get(h);if(cap<b.n||(!out&&b.n))return UINT32_MAX;
    if(b.n)memcpy(out,b.p,b.n);return b.n;
}
uint64_t omni_bytes_from_text(uint64_t text_h){ OmniTextSlot t=text_get(text_h); return bytes_alloc((const unsigned char*)t.p,t.n); }
uint32_t omni_bytes_len(uint64_t h){ return bytes_get(h).n; }
uint64_t omni_bytes_concat(uint64_t a,uint64_t b){ OmniBytesSlot x=bytes_get(a),y=bytes_get(b); if((uint64_t)x.n+y.n>OMNI_BYTES_VALUE_MAX)fault("E_BYTES_LIMIT"); size_t n=(size_t)x.n+y.n; unsigned char *tmp=(unsigned char*)malloc(n?n:1); if(!tmp)fault("E_MEMORY"); if(x.n)memcpy(tmp,x.p,x.n); if(y.n)memcpy(tmp+x.n,y.p,y.n); uint64_t h=bytes_alloc(tmp,(uint32_t)n); free(tmp); return h; }
uint32_t omni_bytes_to_text(uint64_t h,uint64_t *out_h){ if(!out_h)return 2;*out_h=0;OmniBytesSlot b=bytes_get(h); if(!valid_utf8_no_nul(b.p,b.n))return 1; *out_h=text_alloc((const char*)b.p,b.n); return 0; }

/* A86 hosted filesystem errors: 0 OK, 1 denied, 2 invalid, 3 not found,
   4 I/O failure, 5 declared/policy size limit.  Authority is checked both
   before opening and after the concrete byte count is known. */
uint32_t omni_host_read(uint64_t path_h,uint32_t max_bytes,uint64_t *out_h) {
    if(!out_h)return 2; *out_h=0;
    if(max_bytes==0)return 2;
    if(max_bytes>OMNI_BYTES_VALUE_MAX)return 5;
    OmniTextSlot path=text_get(path_h);
    if(!host_allowed("fs.read",path.p,0,1))return 1;
    invocation_safe_point(context());
    invocation_effect_dispatched();
    FILE *f=fopen(path.p,"rb"); if(!f)return errno==ENOENT?3u:4u;
    if(fseek(f,0,SEEK_END)!=0){fclose(f);return 4;}
    long z=ftell(f); if(z<0){fclose(f);return 4;}
    if((unsigned long)z>max_bytes||(unsigned long)z>OMNI_BYTES_VALUE_MAX){fclose(f);return 5;}
    if(!host_allowed("fs.read",path.p,(uint64_t)z,1)){fclose(f);return 1;}
    if(fseek(f,0,SEEK_SET)!=0){fclose(f);return 4;}
    size_t n=(size_t)z; unsigned char *buf=(unsigned char*)malloc(n?n:1);
    if(!buf){fclose(f);fault("E_MEMORY");}
    if(n&&fread(buf,1,n,f)!=n){free(buf);fclose(f);return 4;}
    if(fclose(f)!=0){free(buf);return 4;}
    invocation_effect_acknowledged();
    *out_h=bytes_alloc(buf,(uint32_t)n); free(buf);return 0;
}
uint32_t omni_host_write(uint64_t path_h,uint64_t bytes_h,uint32_t *out_written) {
    if(!out_written)return 2; *out_written=0;
    OmniTextSlot path=text_get(path_h); OmniBytesSlot bytes=bytes_get(bytes_h);
    if(!host_allowed("fs.write",path.p,bytes.n,1))return 1;
    invocation_safe_point(context());
    invocation_effect_dispatched();
    FILE *f=fopen(path.p,"wb"); if(!f)return errno==ENOENT?3u:4u;
    if(bytes.n&&fwrite(bytes.p,1,bytes.n,f)!=bytes.n){fclose(f);return 4;}
    if(fflush(f)!=0||fclose(f)!=0)return 4;
    *out_written=bytes.n;invocation_effect_acknowledged();return 0;
}

static uint64_t host_now_ms(void){struct timespec t;if(clock_gettime(CLOCK_MONOTONIC,&t)!=0)return 0;return (uint64_t)t.tv_sec*1000u+(uint64_t)t.tv_nsec/1000000u;}
static int host_remaining_ms(uint64_t end){
    OmniRuntimeContext *c=active_context;
    if(c&&c->invocation_mode){
        if(c->cancel_flag&&__atomic_load_n(c->cancel_flag,__ATOMIC_ACQUIRE))return 0;
        const uint64_t invocation_end=c->deadline_ns/1000000u;
        if(invocation_end<end)end=invocation_end;
    }
    const uint64_t now=host_now_ms(),remaining=now>=end?0:end-now;
    if(remaining==0)return 0;
    /* Wake periodically so cross-thread cancellation is observed while blocked. */
    return remaining>50u?50:(int)remaining;
}
static int host_wait_fd(int fd,short events,uint64_t end){
    for(;;){int wait_ms=host_remaining_ms(end);if(wait_ms==0)return 0;struct pollfd p={fd,events,0};int result=poll(&p,1,wait_ms);if(result>0)return (p.revents&(events|POLLHUP))!=0;if(result==0)continue;if(errno!=EINTR)return 0;}
}
static int host_write_exact(int fd,const unsigned char *data,size_t size,uint64_t end){
    size_t offset=0;while(offset<size){if(!host_wait_fd(fd,POLLOUT,end))return 0;ssize_t n=write(fd,data+offset,size-offset);if(n>0)offset+=(size_t)n;else if(n<0&&(errno==EINTR||errno==EAGAIN||errno==EWOULDBLOCK))continue;else return 0;}return 1;
}
static int host_read_exact(int fd,unsigned char *data,size_t size,uint64_t end){
    size_t offset=0;while(offset<size){if(!host_wait_fd(fd,POLLIN,end))return 0;ssize_t n=read(fd,data+offset,size-offset);if(n>0)offset+=(size_t)n;else if(n<0&&(errno==EINTR||errno==EAGAIN||errno==EWOULDBLOCK))continue;else return 0;}return 1;
}
static void host_put_u32(unsigned char *p,uint32_t value){p[0]=(unsigned char)value;p[1]=(unsigned char)(value>>8);p[2]=(unsigned char)(value>>16);p[3]=(unsigned char)(value>>24);}
static uint32_t host_get_u32(const unsigned char *p){return (uint32_t)p[0]|((uint32_t)p[1]<<8)|((uint32_t)p[2]<<16)|((uint32_t)p[3]<<24);}
static void host_kill_reap(pid_t child){if(child<=0)return;(void)kill(child,SIGKILL);int status=0;while(waitpid(child,&status,0)<0&&errno==EINTR){}}
static int host_wait_child(pid_t child,uint64_t end,int *status){
    for(;;){pid_t result=waitpid(child,status,WNOHANG);if(result==child)return 1;if(result<0&&errno!=EINTR)return 0;if(host_remaining_ms(end)==0)return 0;struct timespec pause={0,1000000};while(nanosleep(&pause,&pause)<0&&errno==EINTR){}}
}

uint32_t omni_host_process(uint64_t adapter_h,uint64_t payload_h,uint32_t max_bytes,uint32_t deadline_ticks,uint64_t *out_h){
    static const unsigned char request_magic[8]={'O','M','N','I','H','P','1',0};
    static const unsigned char response_magic[8]={'O','M','N','I','H','R','1',0};
    if(!out_h)return 2;*out_h=0;
    OmniTextSlot adapter=text_get(adapter_h);OmniBytesSlot payload=bytes_get(payload_h);
    if(max_bytes==0)return 2;if(max_bytes>OMNI_BYTES_VALUE_MAX||payload.n>OMNI_BYTES_VALUE_MAX)return 5;if(deadline_ticks==0)return 6;
    uint64_t authority_bytes=payload.n>max_bytes?payload.n:max_bytes;
    if(!host_allowed("process.spawn",adapter.p,authority_bytes,0))return 1;
    if(adapter.n>4096u)return 2;
    invocation_safe_point(context());
    int input_pipe[2],output_pipe[2];if(pipe(input_pipe)!=0)return 4;if(pipe(output_pipe)!=0){close(input_pipe[0]);close(input_pipe[1]);return 4;}
    int all_fds[4]={input_pipe[0],input_pipe[1],output_pipe[0],output_pipe[1]};for(int i=0;i<4;i++){int flags=fcntl(all_fds[i],F_GETFD);if(flags>=0)(void)fcntl(all_fds[i],F_SETFD,flags|FD_CLOEXEC);}
    long open_max=sysconf(_SC_OPEN_MAX);if(open_max<64)open_max=64;
    invocation_effect_dispatched();
    pid_t child=fork();
    if(child<0){for(int i=0;i<4;i++)close(all_fds[i]);return 4;}
    if(child==0){
        if(dup2(input_pipe[0],STDIN_FILENO)<0||dup2(output_pipe[1],STDOUT_FILENO)<0)_exit(126);
#ifdef SYS_close_range
        if(syscall(SYS_close_range,3u,~0u,0)<0)
#endif
            for(long fd=3;fd<open_max;fd++)close((int)fd);
        execl(adapter.p,adapter.p,"--omni-host-process-v1",(char*)NULL);_exit(errno==ENOENT?127:126);
    }
    close(input_pipe[0]);close(output_pipe[1]);
    int flags=fcntl(input_pipe[1],F_GETFL);if(flags>=0)(void)fcntl(input_pipe[1],F_SETFL,flags|O_NONBLOCK);flags=fcntl(output_pipe[0],F_GETFL);if(flags>=0)(void)fcntl(output_pipe[0],F_SETFL,flags|O_NONBLOCK);
    struct sigaction old_pipe,ignore_pipe;memset(&ignore_pipe,0,sizeof ignore_pipe);ignore_pipe.sa_handler=SIG_IGN;sigemptyset(&ignore_pipe.sa_mask);int restore_pipe=sigaction(SIGPIPE,&ignore_pipe,&old_pipe)==0;
    if(restore_pipe&&context()->invocation_mode){context()->effect_old_sigpipe=old_pipe;context()->effect_sigpipe_override=1;}
    uint64_t end=host_now_ms()+deadline_ticks;
    size_t request_size=20u+(size_t)adapter.n+payload.n;unsigned char *request=(unsigned char*)malloc(request_size);if(!request){close(input_pipe[1]);close(output_pipe[0]);host_kill_reap(child);if(restore_pipe)(void)sigaction(SIGPIPE,&old_pipe,NULL);fault("E_MEMORY");}
    memcpy(request,request_magic,8);host_put_u32(request+8,adapter.n);host_put_u32(request+12,max_bytes);host_put_u32(request+16,payload.n);memcpy(request+20,adapter.p,adapter.n);if(payload.n)memcpy(request+20+adapter.n,payload.p,payload.n);
    int sent=host_write_exact(input_pipe[1],request,request_size,end);free(request);close(input_pipe[1]);if(restore_pipe){(void)sigaction(SIGPIPE,&old_pipe,NULL);if(context()->invocation_mode)context()->effect_sigpipe_override=0;}
    if(!sent){close(output_pipe[0]);host_kill_reap(child);return 10;}
    unsigned char header[20];if(!host_read_exact(output_pipe[0],header,sizeof header,end)){
        int early_status=0;if(host_wait_child(child,end,&early_status)){close(output_pipe[0]);if(WIFEXITED(early_status)&&WEXITSTATUS(early_status)==127)return 3;return WIFEXITED(early_status)&&WEXITSTATUS(early_status)==0?8:9;}
        close(output_pipe[0]);host_kill_reap(child);return 10;
    }
    if(memcmp(header,response_magic,8)!=0){close(output_pipe[0]);host_kill_reap(child);return 8;}
    uint32_t identity_size=host_get_u32(header+8),status_code=host_get_u32(header+12),response_size=host_get_u32(header+16);
    if(identity_size!=adapter.n||identity_size>4096u||response_size>max_bytes||response_size>OMNI_BYTES_VALUE_MAX||(status_code!=0&&status_code!=9)){close(output_pipe[0]);host_kill_reap(child);return response_size>max_bytes?5:8;}
    unsigned char *identity=(unsigned char*)malloc(identity_size?identity_size:1);unsigned char *response=(unsigned char*)malloc(response_size?response_size:1);if(!identity||!response){free(identity);free(response);close(output_pipe[0]);host_kill_reap(child);fault("E_MEMORY");}
    int valid=host_read_exact(output_pipe[0],identity,identity_size,end)&&memcmp(identity,adapter.p,identity_size)==0&&host_read_exact(output_pipe[0],response,response_size,end);free(identity);
    if(!valid){free(response);close(output_pipe[0]);host_kill_reap(child);return 8;}
    int child_status=0;if(!host_wait_child(child,end,&child_status)){free(response);close(output_pipe[0]);host_kill_reap(child);return 10;}
    unsigned char surplus;ssize_t extra=read(output_pipe[0],&surplus,1);close(output_pipe[0]);
    if(extra>0){free(response);return 8;}if(!WIFEXITED(child_status)){free(response);return 9;}if(WEXITSTATUS(child_status)==127){free(response);return 3;}if(WEXITSTATUS(child_status)!=0){free(response);return 9;}if(status_code!=0){free(response);return status_code;}
    invocation_effect_acknowledged();
    *out_h=bytes_alloc(response,response_size);free(response);return 0;
}

uint32_t omni_host_tcp(uint64_t endpoint_h,uint64_t payload_h,uint32_t max_bytes,uint32_t deadline_ticks,uint64_t *out_h){
    if(!out_h)return 2;*out_h=0;OmniTextSlot endpoint=text_get(endpoint_h);OmniBytesSlot payload=bytes_get(payload_h);
    if(max_bytes==0)return 2;if(max_bytes>OMNI_BYTES_VALUE_MAX||payload.n>OMNI_BYTES_VALUE_MAX)return 5;if(deadline_ticks==0)return 6;
    if(!numeric_endpoint(endpoint.p))return 2;uint64_t authority_bytes=payload.n>max_bytes?payload.n:max_bytes;if(!host_allowed("net.connect",endpoint.p,authority_bytes,0))return 1;
    invocation_safe_point(context());
    const char *colon=strrchr(endpoint.p,':');if(!colon||colon==endpoint.p)return 2;size_t host_len=(size_t)(colon-endpoint.p);if(host_len>=64u)return 2;char host[64];memcpy(host,endpoint.p,host_len);host[host_len]='\0';
    unsigned long port_raw=strtoul(colon+1,NULL,10);struct sockaddr_in address;memset(&address,0,sizeof address);address.sin_family=AF_INET;address.sin_port=htons((uint16_t)port_raw);if(inet_pton(AF_INET,host,&address.sin_addr)!=1)return 2;
    int fd=socket(AF_INET,SOCK_STREAM,0);if(fd<0)return 4;int flags=fcntl(fd,F_GETFD);if(flags>=0)(void)fcntl(fd,F_SETFD,flags|FD_CLOEXEC);flags=fcntl(fd,F_GETFL);if(flags>=0)(void)fcntl(fd,F_SETFL,flags|O_NONBLOCK);
    uint64_t end=host_now_ms()+deadline_ticks;
    invocation_effect_dispatched();
    if(connect(fd,(const struct sockaddr*)&address,sizeof address)<0){if(errno!=EINPROGRESS){close(fd);return 4;}if(!host_wait_fd(fd,POLLOUT,end)){close(fd);return 6;}int error=0;socklen_t size=sizeof error;if(getsockopt(fd,SOL_SOCKET,SO_ERROR,&error,&size)!=0||error!=0){close(fd);return 4;}}
    size_t sent=0;while(sent<payload.n){if(!host_wait_fd(fd,POLLOUT,end)){close(fd);return 10;}ssize_t n=send(fd,payload.p+sent,payload.n-sent,MSG_NOSIGNAL);if(n>0)sent+=(size_t)n;else if(n<0&&(errno==EINTR||errno==EAGAIN||errno==EWOULDBLOCK))continue;else{close(fd);return sent?10:4;}}
    if(shutdown(fd,SHUT_WR)!=0){close(fd);return payload.n?10:4;}
    unsigned char *response=(unsigned char*)malloc(max_bytes?max_bytes:1);if(!response){close(fd);fault("E_MEMORY");}size_t used=0;unsigned char buffer[4096];
    for(;;){if(!host_wait_fd(fd,POLLIN,end)){free(response);close(fd);return 10;}ssize_t n=recv(fd,buffer,sizeof buffer,0);if(n==0)break;if(n<0){if(errno==EINTR||errno==EAGAIN||errno==EWOULDBLOCK)continue;free(response);close(fd);return 10;}if(used+(size_t)n>max_bytes){free(response);close(fd);return 5;}memcpy(response+used,buffer,(size_t)n);used+=(size_t)n;}
    close(fd);invocation_effect_acknowledged();
    *out_h=bytes_alloc(response,(uint32_t)used);free(response);return 0;
}

typedef uint32_t (*OmniFfiV1)(uint32_t,const uint8_t*,uint32_t,uint8_t*,uint32_t,uint32_t*);
uint32_t omni_host_ffi(uint64_t library_h,uint64_t payload_h,uint32_t max_bytes,uint64_t *out_h){
    if(!out_h)return 2;*out_h=0;OmniTextSlot library=text_get(library_h);OmniBytesSlot payload=bytes_get(payload_h);
    if(max_bytes==0)return 2;if(max_bytes>OMNI_BYTES_VALUE_MAX||payload.n>OMNI_BYTES_VALUE_MAX)return 5;uint64_t authority_bytes=payload.n>max_bytes?payload.n:max_bytes;if(!host_allowed("ffi.call",library.p,authority_bytes,0))return 1;
    invocation_safe_point(context());
    unsigned char *child_output=(unsigned char*)malloc(max_bytes);
    int channel[2];if(pipe(channel)!=0){free(child_output);return 4;}long open_max=sysconf(_SC_OPEN_MAX);if(open_max<64)open_max=64;
    invocation_effect_dispatched();
    pid_t child=fork();if(child<0){free(child_output);close(channel[0]);close(channel[1]);return 4;}
    if(child==0){
        /* untrusted native code runs in a copy of this process: a crash must not dump that copy, nor hold the report behind a dump handler */
        (void)prctl(PR_SET_DUMPABLE,0,0,0,0);
        close(channel[0]);int out=channel[1];if(out!=3){if(dup2(out,3)<0)_exit(126);close(out);out=3;}
#ifdef SYS_close_range
        if(syscall(SYS_close_range,4u,~0u,0)<0)
#endif
            for(long fd=4;fd<open_max;fd++)close((int)fd);
        uint32_t code=8,output_size=0;
        void *handle=dlopen(library.p,RTLD_NOW|RTLD_LOCAL);if(handle){void *symbol=dlsym(handle,"omni_ffi_v1");if(symbol){OmniFfiV1 function=NULL;memcpy(&function,&symbol,sizeof function);uint32_t status=function(1u,payload.p,payload.n,child_output,max_bytes,&output_size);code=status==0?0:9;if(output_size>max_bytes)code=5;}(void)dlclose(handle);}
        unsigned char header[8];host_put_u32(header,code);host_put_u32(header+4,code==0?output_size:0);int written=host_write_exact(out,header,sizeof header,host_now_ms()+5000u)&&(code!=0||host_write_exact(out,child_output,output_size,host_now_ms()+5000u));free(child_output);close(out);_exit(written?0:126);
    }
    free(child_output);
    close(channel[1]);uint64_t end=host_now_ms()+5000u;unsigned char header[8];if(!host_read_exact(channel[0],header,sizeof header,end)){int status=0;if(host_wait_child(child,end,&status)){close(channel[0]);return 9;}close(channel[0]);host_kill_reap(child);return 10;}
    uint32_t code=host_get_u32(header),size=host_get_u32(header+4);if((code!=0&&code!=5&&code!=8&&code!=9)||size>max_bytes||size>OMNI_BYTES_VALUE_MAX){close(channel[0]);host_kill_reap(child);return 8;}
    unsigned char *response=(unsigned char*)malloc(size?size:1);if(!response){close(channel[0]);host_kill_reap(child);fault("E_MEMORY");}if(!host_read_exact(channel[0],response,size,end)){free(response);close(channel[0]);host_kill_reap(child);return 8;}
    int status=0;if(!host_wait_child(child,end,&status)){free(response);close(channel[0]);host_kill_reap(child);return 10;}unsigned char surplus;ssize_t extra=read(channel[0],&surplus,1);close(channel[0]);if(extra>0||!WIFEXITED(status)||WEXITSTATUS(status)!=0){free(response);return 9;}if(code){free(response);return code;}invocation_effect_acknowledged();*out_h=bytes_alloc(response,size);free(response);return 0;
}

#define OMNI_BUFFER_TOTAL (16u*1024u*1024u)
#define OMNI_BUFFER_VALUE_MAX (1024u*1024u)
#define OMNI_SLOT_CELL 8u
#define OMNI_SLOT_META 5u   /* per cell besides the 8 bytes: 1 occupancy byte + a 4-byte generation */
uint32_t omni_buffer_release(uint64_t h);
/* CP-03 (spec/CLEANUP_FAILURE_CANDIDATE.md). OMNI_FAIL_AT=N fails the N-th acquisition point (buffer alloc/grow, slots alloc/grow, counted in the order the
   operations are called) with the host out-of-memory outcome 3. OMNI_RESOURCE_AUDIT=1 prints "audit acq|rel <n>" per acquisition/release (n numbers the acquisitions
   from 1) and, when the buffers are cleaned up, "audit summary acquired=A released=R live=L": a leak is live>0, never the net of A and R alone. */
static int audit_on=-1; static uint32_t fail_at,fail_seen,audit_acq,audit_rel;
static void audit_init(void){ if(audit_on>=0)return; const char *a=getenv("OMNI_RESOURCE_AUDIT"); audit_on=(a&&a[0]=='1'&&a[1]==0); const char *f=getenv("OMNI_FAIL_AT"); fail_at=0; if(f&&*f){char *e=NULL;unsigned long v=strtoul(f,&e,10);if(e&&*e==0&&v<=0xffffffffUL)fail_at=(uint32_t)v;} }
static int acquisition_fails(void){ audit_init(); if(!fail_at)return 0; return ++fail_seen==fail_at; }
static void audit_event(const char *what,uint32_t id){ if(audit_on>0)fprintf(stderr,"audit %s %u\n",what,id); }
static uint32_t gen_max_value;
static uint32_t slot_gen_max(void){ if(!gen_max_value){const char *g=getenv("OMNI_SLOT_GEN_MAX");unsigned long v=UINT32_MAX;if(g&&*g){char *e=NULL;unsigned long x=strtoul(g,&e,10);if(e&&*e==0&&x>=2&&x<=UINT32_MAX)v=x;}gen_max_value=(uint32_t)v;} return gen_max_value; }
static int audit_reported;
static void audit_report(void){ audit_init(); if(audit_on>0&&!audit_reported){uint32_t live=0;audit_reported=1;for(uint32_t i=0;i<OMNI_BUFFER_SLOTS;i++)live+=buffer_slots[i].live!=0;fprintf(stderr,"audit summary acquired=%u released=%u live=%u\n",audit_acq,audit_rel,live);} }
static void buffer_cleanup(void){ audit_report(); audit_reported=0;audit_acq=0;audit_rel=0;fail_seen=0;
    for(uint32_t i=0;i<OMNI_BUFFER_SLOTS;i++){if(buffer_slots[i].live){free(buffer_slots[i].p);free(buffer_slots[i].occ);free(buffer_slots[i].cellgen);free(buffer_slots[i].tag);}buffer_slots[i].p=NULL;buffer_slots[i].occ=NULL;buffer_slots[i].cellgen=NULL;buffer_slots[i].tag=NULL;buffer_slots[i].slots=0;buffer_slots[i].n=0;buffer_slots[i].live=0;}buffer_total=0; }
static uint64_t buffer_handle(uint32_t slot,uint32_t gen){return ((uint64_t)gen<<32)|(uint64_t)(slot+1u);}
/* A handle the runtime never issued is E_RESOURCE_HANDLE. A handle that was issued and is no longer live is a release done too early: releasing it again is
   E_RESOURCE_DOUBLE_RELEASE, any other use is E_RESOURCE_STALE_USE. */
static OmniBufferSlot *buffer_get_op(uint64_t h,int releasing){ uint32_t raw=(uint32_t)(h&0xffffffffu); uint32_t gen=(uint32_t)(h>>32); if(raw==0||raw>OMNI_BUFFER_SLOTS)fault("E_RESOURCE_HANDLE"); OmniBufferSlot *s=&buffer_slots[raw-1]; if(gen==0||gen>s->generation)fault("E_RESOURCE_HANDLE"); if(!s->live||s->generation!=gen)fault(releasing?"E_RESOURCE_DOUBLE_RELEASE":"E_RESOURCE_STALE_USE"); return s; }
static OmniBufferSlot *buffer_get(uint64_t h){ return buffer_get_op(h,0); }
static uint32_t buffer_alloc_impl(uint32_t n,uint64_t *out_h);
uint32_t omni_buffer_alloc(uint32_t n,uint64_t *out_h){ if(!out_h)return 3;*out_h=0; if(acquisition_fails())return 3; return buffer_alloc_impl(n,out_h); }
static uint32_t buffer_alloc_impl(uint32_t n,uint64_t *out_h){
    if(!out_h)return 3;*out_h=0; if(n>OMNI_BUFFER_VALUE_MAX)return 1; if(buffer_total+(size_t)n>OMNI_BUFFER_TOTAL)return 2;
    uint32_t slot=OMNI_BUFFER_SLOTS; for(uint32_t i=0;i<OMNI_BUFFER_SLOTS;i++)if(!buffer_slots[i].live){slot=i;break;} if(slot==OMNI_BUFFER_SLOTS)return 2;
    unsigned char *p=(unsigned char*)calloc(n?n:1,1); if(!p)return 3; OmniBufferSlot *s=&buffer_slots[slot]; s->generation++; if(s->generation==0)s->generation=1; s->p=p;s->n=n;s->live=1;s->occ=NULL;s->cellgen=NULL;s->tag=NULL;s->slots=0;buffer_total+=n;
    s->audit_id=++audit_acq; audit_event("acq",s->audit_id);
    *out_h=buffer_handle(slot,s->generation); return 0;
}
uint32_t omni_buffer_len(uint64_t h){return buffer_get(h)->n;}
/* Outcome 8: the buffer is slot-bearing; its cells hold resources and are never visible as bytes. */
uint32_t omni_buffer_read_u8(uint64_t h,uint32_t index,uint32_t *out){if(!out)return 2;*out=0;OmniBufferSlot *s=buffer_get(h); if(s->slots)return 8; if(index>=s->n)return 1;*out=s->p[index];return 0;}
uint32_t omni_buffer_read_u32le(uint64_t h,uint32_t index,uint32_t *out){if(!out)return 2;*out=0;OmniBufferSlot *s=buffer_get(h); if(s->slots)return 8; if(index>s->n||4u>s->n-index)return 1;*out=(uint32_t)s->p[index]|((uint32_t)s->p[index+1]<<8)|((uint32_t)s->p[index+2]<<16)|((uint32_t)s->p[index+3]<<24);return 0;}
uint32_t omni_buffer_read_u64le(uint64_t h,uint32_t index,uint64_t *out){if(!out)return 2;*out=0;OmniBufferSlot *s=buffer_get(h); if(s->slots)return 8; if(index>s->n||8u>s->n-index)return 1;uint64_t v=0;for(uint32_t k=0;k<8;++k)v|=(uint64_t)s->p[index+k]<<(8*k);*out=v;return 0;}
uint32_t omni_buffer_write_u32le(uint64_t h,uint32_t index,uint32_t value){OmniBufferSlot *s=buffer_get(h); if(s->slots)return 8; if(index>s->n||4u>s->n-index)return 1;for(uint32_t k=0;k<4;++k)s->p[index+k]=(unsigned char)((value>>(8*k))&255u);return 0;}
uint32_t omni_buffer_write_u64le(uint64_t h,uint32_t index,uint64_t value){OmniBufferSlot *s=buffer_get(h); if(s->slots)return 8; if(index>s->n||8u>s->n-index)return 1;for(uint32_t k=0;k<8;++k)s->p[index+k]=(unsigned char)((value>>(8*k))&255u);return 0;}
uint32_t omni_buffer_write_u8(uint64_t h,uint32_t index,uint32_t value){OmniBufferSlot *s=buffer_get(h); if(s->slots)return 8; if(index>=s->n||value>255)return 1;s->p[index]=(unsigned char)value;return 0;}
/* CP-04 growth: same owner, same handle, strictly larger. Outcome codes follow omni_buffer_alloc (1 per-buffer limit, 2 budget, 3 host OOM) and
   4 for a shrink request. A failure leaves the buffer, its contents and the accounted total exactly as they were; new bytes are zero. */
uint32_t omni_buffer_grow(uint64_t h,uint32_t n,uint32_t *out){
    if(!out)return 3;*out=0; OmniBufferSlot *s=buffer_get(h);
    if(s->slots)return 8;
    if(acquisition_fails())return 3;
    if(n<s->n)return 4; if(n>OMNI_BUFFER_VALUE_MAX)return 1;
    if(n==s->n){*out=n;return 0;}
    if(buffer_total-(size_t)s->n+(size_t)n>OMNI_BUFFER_TOTAL)return 2;
    unsigned char *p=(unsigned char*)calloc(n,1); if(!p)return 3;
    if(s->n)memcpy(p,s->p,s->n);
    free(s->p); buffer_total+=(size_t)(n-s->n); s->p=p; s->n=n; *out=n; return 0;
}
uint32_t omni_buffer_zero(uint64_t h,uint32_t offset,uint32_t len){OmniBufferSlot *s=buffer_get(h); if(s->slots)return 8; if(offset>s->n||len>s->n-offset)return 1; if(len)memset(s->p+offset,0,len); return 0;}
uint32_t omni_buffer_freeze(uint64_t h,uint64_t *out_h){if(!out_h)return 2;*out_h=0;OmniBufferSlot *s=buffer_get_op(h,1); if(s->slots){omni_buffer_release(h);return 8;} /* freeze consumes the buffer: an empty one is freed (nothing is frozen), an occupied one is the E_SLOT_OCCUPIED fault */ uint64_t b=bytes_alloc(s->p,s->n); buffer_total-=s->n;free(s->p);s->p=NULL;s->n=0;s->live=0;++audit_rel;audit_event("rel",s->audit_id);*out_h=b;return 0;}
/* Freeing a slot-bearing buffer that still owns resources would lose them silently: it is a fault, not a release (slots.release refuses instead). */
uint32_t omni_buffer_release(uint64_t h){
    OmniBufferSlot *s=buffer_get_op(h,1);
    if(s->slots){ for(uint32_t i=0;i<s->n/OMNI_SLOT_CELL;++i)if(s->occ[i])fault("E_SLOT_OCCUPIED"); buffer_total-=(s->n/OMNI_SLOT_CELL)*OMNI_SLOT_META; free(s->occ); s->occ=NULL; free(s->cellgen); s->cellgen=NULL; free(s->tag); s->tag=NULL; s->slots=0; }
    buffer_total-=s->n;free(s->p);s->p=NULL;s->n=0;s->live=0;++audit_rel;audit_event("rel",s->audit_id);return 0;
}

/* CP-01/CP-04 owned slots (spec/OWNED_SLOTS_CANDIDATE.md). Cell outcomes: put 0 stored, 1 occupied, 2 index out of range, 3 not a slot buffer of this tag;
   take 0 taken, 1 empty, 2 range, 3 foreign; state 0 empty, 1 occupied, 2 range, 3 foreign. alloc/grow: 1 per-buffer limit, 2 budget, 3 host out of memory, 4 shrink,
   8 not a slot buffer. The 64-bit value is the resource handle moved in by the caller and moved out to the next owner; Omni code never sees it as an integer. */
static uint32_t slots_occupied(const OmniBufferSlot *s){uint32_t c=0;for(uint32_t i=0;i<s->n/OMNI_SLOT_CELL;++i)c+=s->occ[i]!=0;return c;}
static OmniBufferSlot *slots_get(uint64_t h,const char *tag){OmniBufferSlot *s=buffer_get(h);return (s->slots&&s->tag&&tag&&strcmp(s->tag,tag)==0)?s:NULL;}
uint32_t omni_slots_alloc(const char *tag,uint32_t cells,uint64_t *out_h){
    if(!out_h)return 3;*out_h=0; if(!tag)return 3;
    if(acquisition_fails())return 3;
    if(cells>OMNI_BUFFER_VALUE_MAX/OMNI_SLOT_CELL)return 1;
    if(buffer_total+(size_t)cells*(OMNI_SLOT_CELL+OMNI_SLOT_META)>OMNI_BUFFER_TOTAL)return 2;
    uint64_t h=0; uint32_t r=buffer_alloc_impl(cells*OMNI_SLOT_CELL,&h); if(r)return r;
    OmniBufferSlot *s=buffer_get(h);
    unsigned char *occ=(unsigned char*)calloc(cells?cells:1,1); uint32_t *cg=(uint32_t*)malloc(sizeof(uint32_t)*(cells?cells:1)); size_t keylen=strlen(tag)+1u; char *key=(char*)malloc(keylen); /* same allocator as every free() in this file (invocation_malloc/invocation_free) */
    if(!occ||!cg||!key){free(occ);free(cg);free(key);omni_buffer_release(h);return 3;}
    for(uint32_t k=0;k<cells;++k)cg[k]=1u;   /* generations start at 1: 0 is "no such cell" */
    memcpy(key,tag,keylen);
    s->occ=occ;s->cellgen=cg;s->tag=key;s->slots=1;buffer_total+=(size_t)cells*OMNI_SLOT_META;*out_h=h;return 0;
}
uint32_t omni_slots_len(uint64_t h){OmniBufferSlot *s=buffer_get(h);return s->slots?s->n/OMNI_SLOT_CELL:0u;}
uint32_t omni_slots_count(uint64_t h){OmniBufferSlot *s=buffer_get(h);return s->slots?slots_occupied(s):0u;}
uint32_t omni_slots_state(uint64_t h,const char *tag,uint32_t i){OmniBufferSlot *s=slots_get(h,tag);if(!s)return 3;if(i>=s->n/OMNI_SLOT_CELL)return 2;if(s->occ[i])return 1u;return s->cellgen[i]>=slot_gen_max()?4u:0u;}
/* CP-06: the generation of a cell (spec/CALLBACK_REGISTRY_HOSTED_CANDIDATE.md). It starts at 1 and every take of the cell raises it; an empty cell whose generation reached the
   maximum is state 4 (exhausted) and accepts no further put, so an old (cell, generation) token can never match a later occupant. 0 = no such cell (out of range or a foreign type). */
uint32_t omni_slots_gen(uint64_t h,const char *tag,uint32_t i){OmniBufferSlot *s=slots_get(h,tag);if(!s||i>=s->n/OMNI_SLOT_CELL)return 0u;return s->cellgen[i];}
uint32_t omni_slots_put(uint64_t h,const char *tag,uint32_t i,uint64_t v){
    uint32_t st=omni_slots_state(h,tag,i); if(st!=0)return st;
    OmniBufferSlot *s=buffer_get(h); for(uint32_t k=0;k<OMNI_SLOT_CELL;++k)s->p[(size_t)i*OMNI_SLOT_CELL+k]=(unsigned char)((v>>(8*k))&255u);
    s->occ[i]=1;return 0;
}
uint32_t omni_slots_take(uint64_t h,const char *tag,uint32_t i,uint64_t *out){
    if(!out)return 3;*out=0; uint32_t st=omni_slots_state(h,tag,i); if(st!=1)return st==0?1u:st;
    OmniBufferSlot *s=buffer_get(h); uint64_t v=0; for(uint32_t k=0;k<OMNI_SLOT_CELL;++k)v|=(uint64_t)s->p[(size_t)i*OMNI_SLOT_CELL+k]<<(8*k);
    memset(s->p+(size_t)i*OMNI_SLOT_CELL,0,OMNI_SLOT_CELL); s->occ[i]=0; if(s->cellgen[i]<slot_gen_max())s->cellgen[i]++; *out=v; return 0;
}
/* The element is lent, not moved: its value stays in the cell. An empty or foreign cell is a program fault, as an out-of-range index is. */
uint64_t omni_slots_borrow(uint64_t h,const char *tag,uint32_t i){
    OmniBufferSlot *s=slots_get(h,tag); if(!s||i>=s->n/OMNI_SLOT_CELL||!s->occ[i])fault("E_SLOT_STATE");
    uint64_t v=0; for(uint32_t k=0;k<OMNI_SLOT_CELL;++k)v|=(uint64_t)s->p[(size_t)i*OMNI_SLOT_CELL+k]<<(8*k); return v;
}
uint32_t omni_slots_grow(uint64_t h,uint32_t cells,uint32_t *out){
    if(!out)return 3;*out=0; OmniBufferSlot *s=buffer_get(h); if(!s->slots)return 8;
    if(acquisition_fails())return 3;
    uint32_t old=s->n/OMNI_SLOT_CELL; if(cells<old)return 4; if(cells>OMNI_BUFFER_VALUE_MAX/OMNI_SLOT_CELL)return 1;
    if(cells==old){*out=cells;return 0;}
    size_t add=(size_t)(cells-old)*(OMNI_SLOT_CELL+OMNI_SLOT_META); if(buffer_total+add>OMNI_BUFFER_TOTAL)return 2;
    unsigned char *p=(unsigned char*)calloc((size_t)cells*OMNI_SLOT_CELL,1),*o=(unsigned char*)calloc(cells,1); uint32_t *g=(uint32_t*)malloc(sizeof(uint32_t)*cells); if(!p||!o||!g){free(p);free(o);free(g);return 3;}
    memcpy(p,s->p,s->n);memcpy(o,s->occ,old);memcpy(g,s->cellgen,sizeof(uint32_t)*old);for(uint32_t k=old;k<cells;++k)g[k]=1u;
    free(s->p);free(s->occ);free(s->cellgen);s->p=p;s->occ=o;s->cellgen=g;s->n=cells*OMNI_SLOT_CELL;buffer_total+=add;*out=cells;return 0;
}
/* 0 released, 1 refused because a cell is still occupied (nothing freed), 3 not a slot buffer. */
uint32_t omni_slots_release(uint64_t h){OmniBufferSlot *s=buffer_get_op(h,1);if(!s->slots)return 3;if(slots_occupied(s))return 1;return omni_buffer_release(h);}

void omni_trap_bounds(void) { fault("E_BOUNDS"); }
