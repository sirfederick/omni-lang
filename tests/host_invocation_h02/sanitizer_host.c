#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <pthread.h>
#include "omni_invocation_v1.h"

static void fail(const char *step, uint32_t actual, uint32_t expected) {
    fprintf(stderr, "%s actual=%u expected=%u\n", step, actual, expected);
    exit(2);
}
static void expect(const char *step, uint32_t actual, uint32_t expected) {
    if (actual != expected) fail(step, actual, expected);
}
static void hex(const char *input, uint8_t *output, size_t size) {
    if (strlen(input) != size * 2) exit(3);
    for (size_t i=0; i<size; ++i) {
        unsigned value=0;
        if (sscanf(input+i*2, "%2x", &value) != 1) exit(3);
        output[i]=(uint8_t)value;
    }
}
static uint64_t deadline(void) {
    struct timespec t;
    if (clock_gettime(CLOCK_MONOTONIC,&t)) exit(3);
    return (uint64_t)t.tv_sec*1000000000ULL+(uint64_t)t.tv_nsec+5000000000ULL;
}
static uint32_t fuzz_word(uint32_t *state) {
    *state ^= *state << 13;
    *state ^= *state >> 17;
    *state ^= *state << 5;
    return *state;
}
static uint64_t open_module(const char *path, const char *artifact_hex,
                            const char *descriptor_hex) {
    uint8_t artifact[32], descriptor[32];
    uint64_t module = 0;
    hex(artifact_hex, artifact, sizeof artifact);
    hex(descriptor_hex, descriptor, sizeof descriptor);
    expect("open", omni_invocation_v1_module_open((const uint8_t *)path,
        (uint32_t)strlen(path), artifact, descriptor, &module), 0);
    return module;
}
static void request_header(uint8_t *frame, const char *signature_hex,
                           uint32_t payload_len, uint32_t count) {
    uint8_t signature[32];
    hex(signature_hex, signature, sizeof signature);
    memset(frame, 0, 56 + payload_len);
    memcpy(frame, "OMIV1\0\0\0", 8);
    frame[8] = 1;
    frame[12] = 1;
    memcpy(frame + 16, signature, sizeof signature);
    frame[48] = (uint8_t)payload_len;
    frame[52] = (uint8_t)count;
}
static void run_dynamic_echo(const char *path, const char *artifact_hex,
                             const char *descriptor_hex, const char *signature_hex,
                             const char *type_hex) {
    uint8_t type[32], trace[16] = {0};
    hex(type_hex, type, sizeof type);
    uint64_t module = open_module(path, artifact_hex, descriptor_hex);
    for (uint32_t value = 7; value <= 99; value += 92) {
        uint8_t frame[93];
        request_header(frame, signature_hex, 37, 1);
        frame[56] = 4;
        memcpy(frame + 57, type, sizeof type);
        memcpy(frame + 89, &value, sizeof value);
        uint64_t context = 0;
        expect("echo_create", omni_invocation_v1_invocation_create(module, frame,
            sizeof frame, NULL, 0, 0, deadline(), 67108864, 1048576, 0, trace,
            &context), 0);
        uint32_t effect = 99, length = 99, copied = 0;
        expect("echo_invoke", omni_invocation_v1_invoke(context, &effect, &length), 0);
        expect("echo_effect", effect, 0);
        expect("echo_length", length, 93);
        uint8_t output[93] = {0};
        expect("echo_read", omni_invocation_v1_result_read(context, output,
            sizeof output, &copied), 0);
        expect("echo_copy", copied, 93);
        uint32_t actual = 0;
        memcpy(&actual, output + 89, sizeof actual);
        expect("echo_value", actual, value);
        expect("echo_destroy", omni_invocation_v1_invocation_destroy(context), 0);
    }
    expect("echo_close", omni_invocation_v1_module_close(module), 0);
}
struct spin_call { uint64_t context; uint32_t status; uint32_t effect; uint32_t length; };
static void *run_spin(void *opaque) {
    struct spin_call *call = (struct spin_call *)opaque;
    call->status = omni_invocation_v1_invoke(call->context, &call->effect,
                                              &call->length);
    return NULL;
}
static void run_cross_thread_cancel(const char *path, const char *artifact_hex,
                                    const char *descriptor_hex, const char *signature_hex) {
    uint64_t module = open_module(path, artifact_hex, descriptor_hex);
    uint8_t trace[16] = {0};
    for (unsigned iteration = 0; iteration < 16; ++iteration) {
        uint8_t frame[56];
        request_header(frame, signature_hex, 0, 0);
        struct spin_call call = {0, 99, 99, 99};
        expect("spin_create", omni_invocation_v1_invocation_create(module, frame,
            sizeof frame, NULL, 0, 0, deadline(), 67108864, 1048576, 0, trace,
            &call.context), 0);
        pthread_t thread;
        if (pthread_create(&thread, NULL, run_spin, &call) != 0) exit(5);
        struct timespec pause = {0, 1000000};
        nanosleep(&pause, NULL);
        expect("spin_cancel", omni_invocation_v1_cancel(call.context), 0);
        if (pthread_join(thread, NULL) != 0) exit(5);
        expect("spin_cancelled", call.status, OMNI_INVOCATION_V1_CANCELLED);
        expect("spin_effect", call.effect, OMNI_INVOCATION_V1_EFFECT_NONE);
        expect("spin_length", call.length, 0);
        expect("spin_destroy", omni_invocation_v1_invocation_destroy(call.context), 0);
    }
    expect("spin_close", omni_invocation_v1_module_close(module), 0);
}
int main(int argc, char **argv) {
    if (argc != 14) return 3;
    uint8_t artifact[32],descriptor[32],signature[32],trace[16]={0};
    hex(argv[2],artifact,32);hex(argv[3],descriptor,32);
    hex(argv[4],signature,32);
    uint64_t module=0;
    expect("open",omni_invocation_v1_module_open((const uint8_t*)argv[1],
        (uint32_t)strlen(argv[1]),artifact,descriptor,&module),0);
    uint8_t frame[56]={0};
    memcpy(frame,"OMIV1\0\0\0",8);frame[8]=1;
    frame[12]=1;memcpy(frame+16,signature,32);
    for (unsigned i=0;i<512;++i) {
        uint64_t context=0;
        expect("create",omni_invocation_v1_invocation_create(module,frame,56,
            NULL,0,0,deadline(),67108864,1048576,0,trace,&context),0);
        uint32_t effect=99,length=99;
        expect("invoke",omni_invocation_v1_invoke(context,&effect,&length),0);
        expect("effect",effect,0);expect("length",length,93);
        uint8_t output[93]={0};uint32_t copied=99;
        expect("short_read",omni_invocation_v1_result_read(context,output,92,
            &copied),OMNI_INVOCATION_V1_LIMIT_EXCEEDED);
        expect("required",copied,93);
        expect("read",omni_invocation_v1_result_read(context,output,93,
            &copied),0);
        expect("copy",copied,93);
        expect("value",output[89],17);
        expect("destroy",omni_invocation_v1_invocation_destroy(context),0);
        expect("stale",omni_invocation_v1_invocation_destroy(context),
            OMNI_INVOCATION_V1_INVALID_HANDLE);
    }
    frame[0]='X';uint64_t invalid=0;
    expect("malformed",omni_invocation_v1_invocation_create(module,frame,56,
        NULL,0,0,deadline(),67108864,1048576,0,trace,&invalid),
        OMNI_INVOCATION_V1_MALFORMED_INPUT);
    expect("no_handle",invalid,0);
    /* H03 SEC-07: deterministic hostile decoder/handle corpus.  Every
       malformed candidate must fail before creating a live invocation. */
    uint32_t seed=0x4f4d4931u;
    for (unsigned i=0;i<4096;++i) {
        uint8_t hostile[56]; memcpy(hostile,frame,sizeof hostile);
        hostile[fuzz_word(&seed)%sizeof hostile]^=(uint8_t)(1u+(fuzz_word(&seed)&255u));
        uint64_t candidate=0;
        uint32_t status=omni_invocation_v1_invocation_create(module,hostile,
            (uint32_t)(fuzz_word(&seed)%57u),NULL,0,0,deadline(),67108864,
            1048576,0,trace,&candidate);
        if(status==OMNI_INVOCATION_V1_SEMANTIC_OK || candidate!=0) {
            fprintf(stderr,"fuzz decoder accepted hostile candidate status=%u handle=%llu\n",
                status,(unsigned long long)candidate);
            return 4;
        }
        uint64_t bogus=((uint64_t)fuzz_word(&seed)<<32)|fuzz_word(&seed);
        if((bogus&1u)==0)bogus|=1u;
        expect("fuzz stale cancel",omni_invocation_v1_cancel(bogus),
            OMNI_INVOCATION_V1_INVALID_HANDLE);
        uint32_t effect=0,length=0;
        expect("fuzz stale invoke",omni_invocation_v1_invoke(bogus,&effect,&length),
            OMNI_INVOCATION_V1_INVALID_HANDLE);
    }
    expect("close",omni_invocation_v1_module_close(module),0);
    run_dynamic_echo(argv[5], argv[6], argv[7], argv[8], argv[9]);
    run_cross_thread_cancel(argv[10], argv[11], argv[12], argv[13]);
    puts("ASAN_UBSAN_HOST_INVOCATION_PASS iterations=512 fuzz=4096 echo=2 cancel=16");
    return 0;
}
