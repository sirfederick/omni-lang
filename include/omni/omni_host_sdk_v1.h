#ifndef OMNI_HOST_SDK_V1_H
#define OMNI_HOST_SDK_V1_H

/*
 * Public Omni Host SDK ABI v1.  Handles are opaque process-local identities;
 * neither a verified TypeID nor a decoded value conveys authority.
 */
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

enum omni_host_sdk_v1_status {
    OMNI_HOST_SDK_V1_OK = 0,
    OMNI_HOST_SDK_V1_SEMANTIC_ERR = 1,
    OMNI_HOST_SDK_V1_MALFORMED_INPUT = 2,
    OMNI_HOST_SDK_V1_IDENTITY_MISMATCH = 3,
    OMNI_HOST_SDK_V1_UNSUPPORTED_ABI = 4,
    OMNI_HOST_SDK_V1_ENTRYPOINT_MISSING = 5,
    OMNI_HOST_SDK_V1_LIMIT_EXCEEDED = 6,
    OMNI_HOST_SDK_V1_AUTHORITY_DENIED = 7,
    OMNI_HOST_SDK_V1_DEADLINE_EXCEEDED = 8,
    OMNI_HOST_SDK_V1_CANCELLED = 9,
    OMNI_HOST_SDK_V1_RUNTIME_FAILURE = 10,
    OMNI_HOST_SDK_V1_UNKNOWN_OUTCOME = 11,
    OMNI_HOST_SDK_V1_INVALID_HANDLE = 12,
    OMNI_HOST_SDK_V1_BUSY = 13,
    OMNI_HOST_SDK_V1_POISONED = 14,
    OMNI_HOST_SDK_V1_ALREADY_TERMINAL = 15
};

enum omni_host_sdk_v1_kind {
    OMNI_HOST_SDK_V1_BOOL = 0x01, OMNI_HOST_SDK_V1_U8 = 0x02,
    OMNI_HOST_SDK_V1_U16 = 0x03, OMNI_HOST_SDK_V1_U32 = 0x04,
    OMNI_HOST_SDK_V1_U64 = 0x05, OMNI_HOST_SDK_V1_I8 = 0x06,
    OMNI_HOST_SDK_V1_I16 = 0x07, OMNI_HOST_SDK_V1_I32 = 0x08,
    OMNI_HOST_SDK_V1_I64 = 0x09, OMNI_HOST_SDK_V1_CHAR = 0x0a,
    OMNI_HOST_SDK_V1_TEXT = 0x0b, OMNI_HOST_SDK_V1_BYTES = 0x0c,
    OMNI_HOST_SDK_V1_TUPLE = 0x0d, OMNI_HOST_SDK_V1_ARRAY = 0x0e,
    OMNI_HOST_SDK_V1_RECORD = 0x0f, OMNI_HOST_SDK_V1_ENUM = 0x10,
    OMNI_HOST_SDK_V1_OPTION = 0x11, OMNI_HOST_SDK_V1_RESULT = 0x12
};

typedef uint64_t omni_host_sdk_v1_module;
typedef uint64_t omni_host_sdk_v1_value;

/* Open authenticates the artifact and OMID1 descriptor before accepting OMIS1. */
uint32_t omni_host_sdk_v1_module_open(const uint8_t *absolute_path, uint32_t path_len,
    const uint8_t expected_artifact_sha256[32],
    const uint8_t expected_descriptor_sha256[32], omni_host_sdk_v1_module *out_module);
uint32_t omni_host_sdk_v1_module_close(omni_host_sdk_v1_module module);

uint32_t omni_host_sdk_v1_module_schema_read(omni_host_sdk_v1_module module,
    uint8_t *output, uint32_t capacity, uint32_t *out_copied);
uint32_t omni_host_sdk_v1_module_request_count(omni_host_sdk_v1_module module,
    uint32_t *out_count);
uint32_t omni_host_sdk_v1_module_request_node(omni_host_sdk_v1_module module,
    uint32_t request_index, uint32_t *out_node);
uint32_t omni_host_sdk_v1_module_result_node(omni_host_sdk_v1_module module,
    uint32_t *out_node);
uint32_t omni_host_sdk_v1_schema_node_kind(omni_host_sdk_v1_module module,
    uint32_t node, uint32_t *out_kind);
uint32_t omni_host_sdk_v1_schema_node_typeid(omni_host_sdk_v1_module module,
    uint32_t node, uint8_t output_typeid[32]);
uint32_t omni_host_sdk_v1_schema_node_child_count(omni_host_sdk_v1_module module,
    uint32_t node, uint32_t *out_count);
uint32_t omni_host_sdk_v1_schema_node_child(omni_host_sdk_v1_module module,
    uint32_t node, uint32_t child_index, uint32_t *out_node);
uint32_t omni_host_sdk_v1_schema_node_label_read(omni_host_sdk_v1_module module,
    uint32_t node, uint32_t child_index, uint8_t *output, uint32_t capacity,
    uint32_t *out_copied);

/* Values are descriptor-bound: creation selects a verified schema node. */
uint32_t omni_host_sdk_v1_value_create(omni_host_sdk_v1_module module,
    uint32_t schema_node, omni_host_sdk_v1_value *out_value);
uint32_t omni_host_sdk_v1_value_destroy(omni_host_sdk_v1_value value);
uint32_t omni_host_sdk_v1_value_kind(omni_host_sdk_v1_value value, uint32_t *out_kind);
uint32_t omni_host_sdk_v1_value_typeid(omni_host_sdk_v1_value value,
    uint8_t output_typeid[32]);
/* Signed values accept their width-local or sign-extended two's-complement bits;
 * reads return the stable sign-extended representation. */
uint32_t omni_host_sdk_v1_value_scalar_set(omni_host_sdk_v1_value value, uint64_t bits);
uint32_t omni_host_sdk_v1_value_scalar_get(omni_host_sdk_v1_value value, uint64_t *out_bits);
uint32_t omni_host_sdk_v1_value_data_set(omni_host_sdk_v1_value value,
    const uint8_t *data, uint32_t length);
uint32_t omni_host_sdk_v1_value_data_read(omni_host_sdk_v1_value value,
    uint8_t *output, uint32_t capacity, uint32_t *out_copied);
/* Enum: variant index; Option: 0=None, 1=Some; Result: 0=Ok, 1=Err. */
uint32_t omni_host_sdk_v1_value_discriminant_set(omni_host_sdk_v1_value value,
    uint32_t discriminant);
uint32_t omni_host_sdk_v1_value_discriminant_get(omni_host_sdk_v1_value value,
    uint32_t *out_discriminant);
uint32_t omni_host_sdk_v1_value_child_count(omni_host_sdk_v1_value value,
    uint32_t *out_count);
uint32_t omni_host_sdk_v1_value_child_set(omni_host_sdk_v1_value parent,
    uint32_t child_index, omni_host_sdk_v1_value child);
uint32_t omni_host_sdk_v1_value_child_get(omni_host_sdk_v1_value parent,
    uint32_t child_index, omni_host_sdk_v1_value *out_child);

/* Both operations call Core's canonical OMI1 codec; no host codec is exposed. */
uint32_t omni_host_sdk_v1_request_encode(omni_host_sdk_v1_module module,
    const omni_host_sdk_v1_value *arguments, uint32_t argument_count,
    uint8_t *output, uint32_t capacity, uint32_t *out_copied);
uint32_t omni_host_sdk_v1_result_decode(omni_host_sdk_v1_module module,
    const uint8_t *frame, uint32_t frame_length, omni_host_sdk_v1_value *out_value);

#ifdef __cplusplus
}
#endif
#endif
