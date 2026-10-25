#ifndef OMNI_INVOCATION_V1_H
#define OMNI_INVOCATION_V1_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

enum omni_invocation_v1_status {
    OMNI_INVOCATION_V1_SEMANTIC_OK = 0,
    OMNI_INVOCATION_V1_SEMANTIC_ERR = 1,
    OMNI_INVOCATION_V1_MALFORMED_INPUT = 2,
    OMNI_INVOCATION_V1_IDENTITY_MISMATCH = 3,
    OMNI_INVOCATION_V1_UNSUPPORTED_ABI = 4,
    OMNI_INVOCATION_V1_ENTRYPOINT_MISSING = 5,
    OMNI_INVOCATION_V1_LIMIT_EXCEEDED = 6,
    OMNI_INVOCATION_V1_AUTHORITY_DENIED = 7,
    OMNI_INVOCATION_V1_DEADLINE_EXCEEDED = 8,
    OMNI_INVOCATION_V1_CANCELLED = 9,
    OMNI_INVOCATION_V1_RUNTIME_FAILURE = 10,
    OMNI_INVOCATION_V1_UNKNOWN_OUTCOME = 11,
    OMNI_INVOCATION_V1_INVALID_HANDLE = 12,
    OMNI_INVOCATION_V1_BUSY = 13,
    OMNI_INVOCATION_V1_POISONED = 14,
    OMNI_INVOCATION_V1_ALREADY_TERMINAL = 15
};

enum omni_invocation_v1_effect_observation {
    OMNI_INVOCATION_V1_EFFECT_NONE = 0,
    OMNI_INVOCATION_V1_EFFECT_ACKNOWLEDGED = 1,
    OMNI_INVOCATION_V1_EFFECT_UNCERTAIN = 2
};

uint32_t omni_invocation_v1_module_open(
    const uint8_t *absolute_path, uint32_t path_len,
    const uint8_t expected_artifact_sha256[32],
    const uint8_t expected_descriptor_sha256[32], uint64_t *out_module);
uint32_t omni_invocation_v1_invocation_create(
    uint64_t module, const uint8_t *request_frame, uint32_t request_len,
    const uint8_t *ohp1_policy, uint32_t policy_len,
    uint64_t expected_policy_generation, uint64_t absolute_deadline_ns,
    uint64_t allocation_limit, uint32_t result_limit,
    uint32_t diagnostic_limit, const uint8_t trace_id[16],
    uint64_t *out_invocation);
uint32_t omni_invocation_v1_invoke(
    uint64_t invocation, uint32_t *out_effect_observation,
    uint32_t *out_result_frame_length);
uint32_t omni_invocation_v1_cancel(uint64_t invocation);
uint32_t omni_invocation_v1_result_read(
    uint64_t invocation, uint8_t *output, uint32_t capacity,
    uint32_t *out_copied);
uint32_t omni_invocation_v1_module_schema_read(
    uint64_t module, uint8_t *output, uint32_t capacity,
    uint32_t *out_copied);
uint32_t omni_invocation_v1_diagnostic_read(
    uint64_t invocation, uint8_t *output, uint32_t capacity,
    uint32_t *out_copied);
uint32_t omni_invocation_v1_invocation_destroy(uint64_t invocation);
uint32_t omni_invocation_v1_module_close(uint64_t module);

#ifdef __cplusplus
}
#endif
#endif
