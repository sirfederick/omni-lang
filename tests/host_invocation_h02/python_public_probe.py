#!/usr/bin/env python3
"""A Python consumer that uses only bindings/python/omni_host_sdk.py."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(os.environ['OMNI_H02_EVIDENCE_ROOT'])
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'bindings/python'))
from omni_host_sdk import HostSdk  # noqa: E402


def main() -> None:
    artifact = ROOT / 'artifacts/echo_u8.so'
    receipt = json.loads(Path(f'{artifact}.omireceipt.json').read_text())
    sdk = HostSdk(ROOT / 'dist/runtime/libomni_invocation_v1.so')
    module = sdk.module_open(artifact, bytes.fromhex(receipt['artifact_sha256']), bytes.fromhex(receipt['descriptor_sha256']))
    value = None
    try:
        node = sdk.request_node(module, 0)
        assert sdk.node_kind(module, node) == 2
        value = sdk.value_create(module, node)
        sdk.scalar_set(value, 255)
        frame = sdk.request_encode(module, [value])
        assert frame
        decoded = sdk.result_decode(module, (ROOT / 'node_echo_u8_result.omi1').read_bytes())
        try:
            assert sdk.scalar_get(decoded) == 255
        finally:
            sdk.value_destroy(decoded)
        print(json.dumps({'schema': 'omni.host-sdk-python-public-probe/1', 'status': 'PASS', 'public_c_abi_only': True, 'manual_omi1_codec': False, 'request_bytes': len(frame), 'real_result_decode': True}, sort_keys=True))
    finally:
        if value is not None:
            sdk.value_destroy(value)
        sdk.module_close(module)


if __name__ == '__main__':
    main()
