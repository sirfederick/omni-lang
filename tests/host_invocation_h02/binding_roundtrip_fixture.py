#!/usr/bin/env python3
"""Produce one real runtime response for the public Node/Python decode probes."""
from __future__ import annotations

import json
import os
import sys
import time
import ctypes as c
from pathlib import Path

ROOT = Path(os.environ['OMNI_H02_EVIDENCE_ROOT'])
CORE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(CORE / 'bindings/python'))
from omni_host_sdk import HostSdk  # noqa: E402
from sdk_composite_probe import U8, U32, U64, arr, create, destroy, invoke, raw_close, raw_open, read  # noqa: E402


def main() -> None:
    artifact = ROOT / 'artifacts/echo_u8.so'
    receipt = json.loads(Path(f'{artifact}.omireceipt.json').read_text())
    sdk = HostSdk(ROOT / 'dist/runtime/libomni_invocation_v1.so')
    module = sdk.module_open(artifact, bytes.fromhex(receipt['artifact_sha256']), bytes.fromhex(receipt['descriptor_sha256']))
    request_value = decoded_value = None
    raw = invocation = None
    try:
        node = sdk.request_node(module, 0)
        request_value = sdk.value_create(module, node)
        sdk.scalar_set(request_value, 255)
        request = sdk.request_encode(module, [request_value])
        raw_handle = U64()
        encoded_path = str(artifact).encode()
        assert raw_open(arr(encoded_path), len(encoded_path), arr(bytes.fromhex(receipt['artifact_sha256'])), arr(bytes.fromhex(receipt['descriptor_sha256'])), c.byref(raw_handle)) == 0
        raw = raw_handle.value
        invocation_handle = U64(); trace = (U8 * 16)()
        assert create(raw, arr(request), len(request), None, 0, 0, time.monotonic_ns() + 5_000_000_000, 1_000_000, 65_536, 0, trace, c.byref(invocation_handle)) == 0
        invocation = invocation_handle.value
        effect, length = U32(), U32(); assert invoke(invocation, c.byref(effect), c.byref(length)) == 0
        response, copied = (U8 * length.value)(), U32(); assert read(invocation, response, length.value, c.byref(copied)) == 0
        result = bytes(response[:copied.value]); (ROOT / 'node_echo_u8_result.omi1').write_bytes(result)
        decoded_value = sdk.result_decode(module, result)
        assert sdk.scalar_get(decoded_value) == 255
        print(json.dumps({'schema': 'omni.host-sdk-binding-roundtrip/1', 'status': 'PASS', 'real_runtime_exercised': True, 'public_c_decode': True, 'result_bytes': len(result)}, sort_keys=True))
    finally:
        if decoded_value is not None: sdk.value_destroy(decoded_value)
        if request_value is not None: sdk.value_destroy(request_value)
        if invocation is not None: assert destroy(invocation) == 0
        if raw is not None: assert raw_close(raw) == 0
        sdk.module_close(module)


if __name__ == '__main__':
    main()
