#ifndef OMNI_INVOCATION_INTERNAL_H
#define OMNI_INVOCATION_INTERNAL_H

#include <stdint.h>

/* Private contract shared by one compiler build and its matching runtime. */
typedef struct OmniInvocationTypeV1 {
    uint8_t tag;
    uint8_t type_id[32];
    uint32_t native_size;
    uint32_t item_count;
    uint32_t element_stride;
    const struct OmniInvocationTypeV1 *const *children;
    const uint32_t *offsets;
} OmniInvocationTypeV1;

typedef uint32_t (*OmniModuleEntryV1)(
    uint32_t mode, const uint8_t *request, uint32_t request_len,
    const uint8_t *policy, uint32_t policy_len, uint64_t policy_generation,
    uint64_t deadline_ns, uint64_t allocation_limit,
    const uint8_t trace_id[16], const uint32_t *cancel_flag,
    uint8_t *result, uint32_t result_capacity,
    uint32_t *result_len, uint32_t *effect_observation);

typedef uint32_t (*OmniModuleBodyV1)(
    uint32_t mode, const uint8_t *request, uint32_t request_len,
    uint8_t *result, uint32_t result_capacity, uint32_t *result_len);

uint32_t omni_runtime_execute_invocation_v1(
    OmniModuleBodyV1 body, uint32_t mode,
    const uint8_t *request, uint32_t request_len,
    const uint8_t *policy, uint32_t policy_len, uint64_t policy_generation,
    uint64_t deadline_ns, uint64_t allocation_limit,
    const uint8_t trace_id[16], const uint32_t *cancel_flag,
    uint8_t *result, uint32_t result_capacity,
    uint32_t *result_len, uint32_t *effect_observation);

uint32_t omni_invocation_decode_v1(
    const uint8_t *frame, uint32_t frame_len, const uint8_t signature[32],
    const OmniInvocationTypeV1 *const *types, void *const *values,
    uint32_t type_count);
uint32_t omni_invocation_decode_kind_v1(
    const uint8_t *frame, uint32_t frame_len, uint32_t expected_kind,
    const uint8_t signature[32], const OmniInvocationTypeV1 *const *types,
    void *const *values, uint32_t type_count);
uint32_t omni_invocation_encode_v1(
    uint8_t *frame, uint32_t frame_capacity, const uint8_t signature[32],
    const OmniInvocationTypeV1 *type, const void *value,
    uint32_t *out_len);

#endif
