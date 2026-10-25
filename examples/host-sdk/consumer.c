/* SPDX-FileCopyrightText: 2026 Federico T. Begna
 * SPDX-License-Identifier: MIT OR Apache-2.0 */
#define _POSIX_C_SOURCE 200809L
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <time.h>
#include <omni/omni_host_sdk_v1.h>
#include <omni_invocation_v1.h>

static int digest(const char *hex, uint8_t bytes[32]) {
    if (strlen(hex) != 64) return 1;
    for (unsigned index = 0; index < 32; ++index) {
        unsigned value;
        if (sscanf(hex + index * 2, "%2x", &value) != 1) return 1;
        bytes[index] = (uint8_t)value;
    }
    return 0;
}

int main(int argc, char **argv) {
    if (argc != 4 && argc != 5) {
        fprintf(stderr, "usage: consumer ARTIFACT ARTIFACT_SHA256 DESCRIPTOR_SHA256 [RESPONSE_FILE]\n");
        return 2;
    }
    uint8_t artifact_hash[32], descriptor_hash[32], request[4096], response[4096], trace[16] = {0};
    if (digest(argv[2], artifact_hash) || digest(argv[3], descriptor_hash)) return 3;
    uint64_t sdk = 0, argument = 0, module = 0, invocation = 0, decoded = 0, result = 0;
    uint32_t node = 0, written = 0, effect = 0, length = 0, copied = 0;
    struct timespec now;
    if (clock_gettime(CLOCK_MONOTONIC, &now)) return 4;
    uint64_t deadline = (uint64_t)now.tv_sec * 1000000000ULL + (uint64_t)now.tv_nsec + 5000000000ULL;
    uint32_t path_length = (uint32_t)strlen(argv[1]);
    if (omni_host_sdk_v1_module_open((const uint8_t *)argv[1], path_length, artifact_hash, descriptor_hash, &sdk)) return 5;
    if (omni_host_sdk_v1_module_request_node(sdk, 0, &node) ||
        omni_host_sdk_v1_value_create(sdk, node, &argument) ||
        omni_host_sdk_v1_value_scalar_set(argument, 255) ||
        omni_host_sdk_v1_request_encode(sdk, &argument, 1, request, sizeof(request), &written)) return 6;
    if (omni_invocation_v1_module_open((const uint8_t *)argv[1], path_length, artifact_hash, descriptor_hash, &module) ||
        omni_invocation_v1_invocation_create(module, request, written, NULL, 0, 0, deadline, 1048576, 4096, 0, trace, &invocation) ||
        omni_invocation_v1_invoke(invocation, &effect, &length) ||
        omni_invocation_v1_result_read(invocation, response, sizeof(response), &copied)) return 7;
    if (omni_host_sdk_v1_result_decode(sdk, response, copied, &decoded) ||
        omni_host_sdk_v1_value_scalar_get(decoded, &result) || result != 255) return 8;
    if (argc == 5) {
        FILE *file = fopen(argv[4], "wb");
        if (!file) return 10;
        size_t saved = fwrite(response, 1, copied, file);
        int closed = fclose(file);
        if (saved != copied || closed) return 10;
    }
    if (omni_host_sdk_v1_value_destroy(decoded) || omni_host_sdk_v1_value_destroy(argument) ||
        omni_invocation_v1_invocation_destroy(invocation) || omni_invocation_v1_module_close(module) ||
        omni_host_sdk_v1_module_close(sdk)) return 9;
    puts("C: echo_u8(255) = 255 (real invocation)");
    return 0;
}
