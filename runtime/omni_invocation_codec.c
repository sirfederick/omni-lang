#include "omni_invocation_internal.h"
#include "omni_invocation_v1.h"
#include <stdint.h>
#include <stddef.h>
#include <string.h>

#define FRAME_MAX 1048576u
#define NODE_MAX 65536u
#define DEPTH_MAX 32u
static const uint8_t frame_magic[8]={'O','M','I','V','1',0,0,0};

extern uint64_t omni_text_new(const char *,uint32_t);
extern uint32_t omni_text_byte_len(uint64_t);
extern uint32_t omni_invocation_text_copy_v1(uint64_t,uint8_t *,uint32_t);
extern int omni_invocation_text_valid_v1(const uint8_t *,uint32_t);
extern uint64_t omni_invocation_bytes_new_v1(const uint8_t *,uint32_t);
extern uint32_t omni_bytes_len(uint64_t);
extern uint32_t omni_invocation_bytes_copy_v1(uint64_t,uint8_t *,uint32_t);

typedef struct {const uint8_t *b;uint32_t n,pos,nodes;} Reader;
typedef struct {uint8_t *b;uint32_t cap,pos,nodes;} Writer;
static uint32_t get(Reader *r,uint32_t n,uint64_t *out) {
    if(n>r->n-r->pos)return OMNI_INVOCATION_V1_MALFORMED_INPUT;
    uint64_t value=0;for(uint32_t i=0;i<n;i++)value|=(uint64_t)r->b[r->pos++]<<(8u*i);
    *out=value;return 0;
}
static uint32_t put(Writer *w,uint64_t value,uint32_t n) {
    if(n>w->cap-w->pos)return OMNI_INVOCATION_V1_LIMIT_EXCEEDED;
    for(uint32_t i=0;i<n;i++)w->b[w->pos++]=(uint8_t)(value>>(8u*i));
    return 0;
}
static uint32_t field(const OmniInvocationTypeV1 *t,uint32_t i,
                      const OmniInvocationTypeV1 **child,uint32_t *offset) {
    if(!t->children||!t->offsets||i>=t->item_count)return OMNI_INVOCATION_V1_RUNTIME_FAILURE;
    *child=t->children[i];*offset=t->offsets[i];
    if(*child&&(*offset>t->native_size||
        (*child)->native_size>t->native_size-*offset))return OMNI_INVOCATION_V1_RUNTIME_FAILURE;
    return 0;
}
static uint32_t decode_value(Reader *r,const OmniInvocationTypeV1 *t,
                             void *native,uint32_t depth) {
    if(!t||!native)return OMNI_INVOCATION_V1_RUNTIME_FAILURE;
    if(depth>DEPTH_MAX||++r->nodes>NODE_MAX)return OMNI_INVOCATION_V1_LIMIT_EXCEEDED;
    uint64_t x=0;uint32_t status=get(r,1,&x);if(status)return status;
    if(x!=t->tag||32u>r->n-r->pos||memcmp(r->b+r->pos,t->type_id,32)!=0)
        return OMNI_INVOCATION_V1_MALFORMED_INPUT;
    r->pos+=32;
    switch(t->tag){
        case 0x01:
            status=get(r,1,&x);if(status)return status;
            if(x>1||t->native_size<1)return OMNI_INVOCATION_V1_MALFORMED_INPUT;
            *(uint8_t*)native=(uint8_t)x;return 0;
        case 0x02:case 0x06:case 0x03:case 0x07:
        case 0x04:case 0x08:case 0x05:case 0x09:case 0x0a: {
            const uint32_t width=t->tag==0x02||t->tag==0x06?1u:
                t->tag==0x03||t->tag==0x07?2u:
                t->tag==0x04||t->tag==0x08||t->tag==0x0a?4u:8u;
            status=get(r,width,&x);if(status)return status;
            if(t->native_size<width)return OMNI_INVOCATION_V1_RUNTIME_FAILURE;
            if(t->tag==0x0a&&(x>0x10ffffu||(x>=0xd800u&&x<=0xdfffu)))
                return OMNI_INVOCATION_V1_MALFORMED_INPUT;
            memcpy(native,&x,width);return 0;
        }
        case 0x0b:case 0x0c: {
            status=get(r,4,&x);if(status)return status;
            if(x>r->n-r->pos||t->native_size<8)return OMNI_INVOCATION_V1_MALFORMED_INPUT;
            const uint32_t length=(uint32_t)x;const uint8_t *s=r->b+r->pos;
            if(t->tag==0x0b&&!omni_invocation_text_valid_v1(s,length))
                return OMNI_INVOCATION_V1_MALFORMED_INPUT;
            uint64_t h=t->tag==0x0b?omni_text_new((const char*)s,length):
                                      omni_invocation_bytes_new_v1(s,length);
            memcpy(native,&h,8);r->pos+=length;return 0;
        }
        case 0x0d:case 0x0f: {
            status=get(r,2,&x);if(status)return status;
            if(x!=t->item_count)return OMNI_INVOCATION_V1_MALFORMED_INPUT;
            for(uint32_t i=0;i<t->item_count;i++){
                const OmniInvocationTypeV1 *child=NULL;uint32_t offset=0;
                status=field(t,i,&child,&offset);if(status||!child)return OMNI_INVOCATION_V1_RUNTIME_FAILURE;
                status=decode_value(r,child,(uint8_t*)native+offset,depth+1);
                if(status)return status;
            }
            return 0;
        }
        case 0x0e: {
            status=get(r,4,&x);if(status)return status;
            if(x!=t->item_count||!t->children||!t->children[0]||
               (t->item_count&&t->element_stride>t->native_size/t->item_count))
                return OMNI_INVOCATION_V1_MALFORMED_INPUT;
            for(uint32_t i=0;i<t->item_count;i++){
                status=decode_value(r,t->children[0],
                    (uint8_t*)native+(size_t)i*t->element_stride,depth+1);
                if(status)return status;
            }
            return 0;
        }
        case 0x10: {
            status=get(r,2,&x);if(status)return status;
            if(x>=t->item_count||x>UINT8_MAX||t->native_size<1)
                return OMNI_INVOCATION_V1_MALFORMED_INPUT;
            const uint32_t variant=(uint32_t)x;*(uint8_t*)native=(uint8_t)variant;
            const OmniInvocationTypeV1 *child=NULL;uint32_t offset=0;
            status=field(t,variant,&child,&offset);if(status)return status;
            status=get(r,1,&x);if(status)return status;
            if(x!=(child?1u:0u))return OMNI_INVOCATION_V1_MALFORMED_INPUT;
            return child?decode_value(r,child,(uint8_t*)native+offset,depth+1):0;
        }
        case 0x11:case 0x12: {
            status=get(r,1,&x);if(status)return status;
            if(x>1||t->native_size<1)return OMNI_INVOCATION_V1_MALFORMED_INPUT;
            /* OMI1 Result uses 0=Ok, 1=Err; native Omni uses true=Ok. */
            *(uint8_t*)native=(uint8_t)(t->tag==0x12?(x==0u):x);
            if(t->tag==0x11&&!x)return 0;
            const uint32_t arm=t->tag==0x11?0u:(uint32_t)x;
            const OmniInvocationTypeV1 *child=NULL;uint32_t offset=0;
            status=field(t,arm,&child,&offset);
            return status||!child?OMNI_INVOCATION_V1_RUNTIME_FAILURE:
                decode_value(r,child,(uint8_t*)native+offset,depth+1);
        }
        default:return OMNI_INVOCATION_V1_RUNTIME_FAILURE;
    }
}
static uint32_t encode_value(Writer *w,const OmniInvocationTypeV1 *t,
                             const void *native,uint32_t depth) {
    if(!t||!native)return OMNI_INVOCATION_V1_RUNTIME_FAILURE;
    if(depth>DEPTH_MAX||++w->nodes>NODE_MAX)return OMNI_INVOCATION_V1_LIMIT_EXCEEDED;
    uint32_t status=put(w,t->tag,1);if(status)return status;
    if(32u>w->cap-w->pos)return OMNI_INVOCATION_V1_LIMIT_EXCEEDED;
    memcpy(w->b+w->pos,t->type_id,32);w->pos+=32;
    switch(t->tag){
        case 0x01: {
            if(t->native_size<1||*(const uint8_t*)native>1)return OMNI_INVOCATION_V1_RUNTIME_FAILURE;
            return put(w,*(const uint8_t*)native,1);
        }
        case 0x02:case 0x06:case 0x03:case 0x07:
        case 0x04:case 0x08:case 0x05:case 0x09:case 0x0a: {
            const uint32_t width=t->tag==0x02||t->tag==0x06?1u:
                t->tag==0x03||t->tag==0x07?2u:
                t->tag==0x04||t->tag==0x08||t->tag==0x0a?4u:8u;
            if(t->native_size<width)return OMNI_INVOCATION_V1_RUNTIME_FAILURE;
            uint64_t x=0;memcpy(&x,native,width);
            if(t->tag==0x0a&&(x>0x10ffffu||(x>=0xd800u&&x<=0xdfffu)))
                return OMNI_INVOCATION_V1_RUNTIME_FAILURE;
            return put(w,x,width);
        }
        case 0x0b:case 0x0c: {
            if(t->native_size<8)return OMNI_INVOCATION_V1_RUNTIME_FAILURE;
            uint64_t h=0;memcpy(&h,native,8);
            const uint32_t length=t->tag==0x0b?omni_text_byte_len(h):omni_bytes_len(h);
            status=put(w,length,4);if(status)return status;
            if(length>w->cap-w->pos)return OMNI_INVOCATION_V1_LIMIT_EXCEEDED;
            const uint32_t copied=t->tag==0x0b?
                omni_invocation_text_copy_v1(h,w->b+w->pos,length):
                omni_invocation_bytes_copy_v1(h,w->b+w->pos,length);
            if(copied!=length)return OMNI_INVOCATION_V1_RUNTIME_FAILURE;
            w->pos+=length;return 0;
        }
        case 0x0d:case 0x0f: {
            status=put(w,t->item_count,2);if(status)return status;
            for(uint32_t i=0;i<t->item_count;i++){
                const OmniInvocationTypeV1 *child=NULL;uint32_t offset=0;
                status=field(t,i,&child,&offset);if(status||!child)return OMNI_INVOCATION_V1_RUNTIME_FAILURE;
                status=encode_value(w,child,(const uint8_t*)native+offset,depth+1);
                if(status)return status;
            }
            return 0;
        }
        case 0x0e: {
            status=put(w,t->item_count,4);if(status)return status;
            if(!t->children||!t->children[0]||
               (t->item_count&&t->element_stride>t->native_size/t->item_count))
                return OMNI_INVOCATION_V1_RUNTIME_FAILURE;
            for(uint32_t i=0;i<t->item_count;i++){
                status=encode_value(w,t->children[0],
                    (const uint8_t*)native+(size_t)i*t->element_stride,depth+1);
                if(status)return status;
            }
            return 0;
        }
        case 0x10: {
            if(t->native_size<1)return OMNI_INVOCATION_V1_RUNTIME_FAILURE;
            const uint32_t variant=*(const uint8_t*)native;
            if(variant>=t->item_count)return OMNI_INVOCATION_V1_RUNTIME_FAILURE;
            const OmniInvocationTypeV1 *child=NULL;uint32_t offset=0;
            status=field(t,variant,&child,&offset);if(status)return status;
            status=put(w,variant,2);if(status)return status;
            status=put(w,child?1u:0u,1);if(status)return status;
            return child?encode_value(w,child,(const uint8_t*)native+offset,depth+1):0;
        }
        case 0x11:case 0x12: {
            if(t->native_size<1)return OMNI_INVOCATION_V1_RUNTIME_FAILURE;
            const uint32_t native_tag=*(const uint8_t*)native;
            if(native_tag>1)return OMNI_INVOCATION_V1_RUNTIME_FAILURE;
            const uint32_t arm=t->tag==0x12?(native_tag==0u):native_tag;
            status=put(w,arm,1);if(status||(!arm&&t->tag==0x11))return status;
            const uint32_t childIndex=t->tag==0x11?0u:arm;
            const OmniInvocationTypeV1 *child=NULL;uint32_t offset=0;
            status=field(t,childIndex,&child,&offset);
            return status||!child?OMNI_INVOCATION_V1_RUNTIME_FAILURE:
                encode_value(w,child,(const uint8_t*)native+offset,depth+1);
        }
        default:return OMNI_INVOCATION_V1_RUNTIME_FAILURE;
    }
}
uint32_t omni_invocation_decode_kind_v1(const uint8_t *frame,uint32_t frame_len,
        uint32_t expected_kind,
        const uint8_t signature[32],const OmniInvocationTypeV1 *const *types,
        void *const *values,uint32_t type_count) {
    if(!frame||!signature||(!types&&type_count)||(!values&&type_count))
        return OMNI_INVOCATION_V1_MALFORMED_INPUT;
    if(frame_len>FRAME_MAX)return OMNI_INVOCATION_V1_LIMIT_EXCEEDED;
    if(frame_len<56||memcmp(frame,frame_magic,8)!=0)return OMNI_INVOCATION_V1_MALFORMED_INPUT;
    Reader r={frame,frame_len,8,0};uint64_t x=0;
    uint32_t status=get(&r,4,&x);if(status)return status;
    if(x!=1)return OMNI_INVOCATION_V1_UNSUPPORTED_ABI;
    status=get(&r,4,&x);if(status)return status;
    if(x!=expected_kind||memcmp(frame+16,signature,32)!=0)return OMNI_INVOCATION_V1_MALFORMED_INPUT;
    r.pos=48;status=get(&r,4,&x);if(status)return status;
    if(x!=frame_len-56u)return OMNI_INVOCATION_V1_MALFORMED_INPUT;
    status=get(&r,4,&x);if(status)return status;
    if(x!=type_count)return OMNI_INVOCATION_V1_MALFORMED_INPUT;
    for(uint32_t i=0;i<type_count;i++){
        status=decode_value(&r,types[i],values[i],0);if(status)return status;
    }
    return r.pos==frame_len?0:OMNI_INVOCATION_V1_MALFORMED_INPUT;
}
uint32_t omni_invocation_decode_v1(const uint8_t *frame,uint32_t frame_len,
        const uint8_t signature[32],const OmniInvocationTypeV1 *const *types,
        void *const *values,uint32_t type_count) {
    return omni_invocation_decode_kind_v1(frame,frame_len,1,signature,types,values,type_count);
}
uint32_t omni_invocation_encode_v1(uint8_t *frame,uint32_t frame_capacity,
        const uint8_t signature[32],const OmniInvocationTypeV1 *type,
        const void *value,uint32_t *out_len) {
    if(!frame||!signature||!type||!value||!out_len)return OMNI_INVOCATION_V1_MALFORMED_INPUT;
    *out_len=0;if(frame_capacity>FRAME_MAX)frame_capacity=FRAME_MAX;
    if(frame_capacity<56)return OMNI_INVOCATION_V1_LIMIT_EXCEEDED;
    Writer w={frame,frame_capacity,0,0};memcpy(frame,frame_magic,8);w.pos=8;
    uint32_t status=put(&w,1,4);if(status)return status;
    status=put(&w,2,4);if(status)return status;
    memcpy(frame+16,signature,32);w.pos=48;
    status=put(&w,0,4);if(status)return status;
    status=put(&w,1,4);if(status)return status;
    status=encode_value(&w,type,value,0);if(status)return status;
    const uint32_t payload=w.pos-56u;
    for(uint32_t i=0;i<4;i++)frame[48+i]=(uint8_t)(payload>>(8u*i));
    *out_len=w.pos;return OMNI_INVOCATION_V1_SEMANTIC_OK;
}
