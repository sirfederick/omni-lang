#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Federico T. Begna
# SPDX-License-Identifier: MIT OR Apache-2.0
"""Encode a request and decode the prepared real runtime response."""
import json
import pathlib
import sys

root = pathlib.Path(sys.argv[1]).resolve()
sys.path.insert(0, str(root / 'dist/python'))
from omni_host_sdk import HostSdk

artifact = root / 'artifacts/echo_u8.so'
receipt = json.loads(pathlib.Path(str(artifact) + '.omireceipt.json').read_text())
sdk = HostSdk(root / 'dist/runtime/libomni_invocation_v1.so')
module = sdk.module_open(artifact, bytes.fromhex(receipt['artifact_sha256']), bytes.fromhex(receipt['descriptor_sha256']))
argument = result = None
try:
    argument = sdk.value_create(module, sdk.request_node(module, 0))
    sdk.scalar_set(argument, 255)
    assert sdk.request_encode(module, [argument])
    result = sdk.result_decode(module, (root / 'node_echo_u8_result.omi1').read_bytes())
    assert sdk.scalar_get(result) == 255
    print('Python: encoded 255; decoded runtime response = 255')
finally:
    if result is not None:
        sdk.value_destroy(result)
    if argument is not None:
        sdk.value_destroy(argument)
    sdk.module_close(module)
