#!/usr/bin/env python3
"""Ownership checks for public child handles; no private SDK state is inspected."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(os.environ['OMNI_H02_EVIDENCE_ROOT'])
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'bindings/python'))
from omni_host_sdk import HostSdk, HostSdkError  # noqa: E402


def main() -> None:
    artifact = ROOT / 'artifacts/echo_pair.so'
    receipt = json.loads(Path(f'{artifact}.omireceipt.json').read_text())
    sdk = HostSdk(ROOT / 'dist/runtime/libomni_invocation_v1.so')
    module = sdk.module_open(artifact, bytes.fromhex(receipt['artifact_sha256']), bytes.fromhex(receipt['descriptor_sha256']))
    other_module = sdk.module_open(artifact, bytes.fromhex(receipt['artifact_sha256']), bytes.fromhex(receipt['descriptor_sha256']))
    parent = first = second = projected = replacement = other_child = wrong_child = None
    checks = {}
    try:
        root = sdk.request_node(module, 0)
        first_node, second_node = sdk.node_child(module, root, 0), sdk.node_child(module, root, 1)
        parent, first, second = sdk.value_create(module, root), sdk.value_create(module, first_node), sdk.value_create(module, second_node)
        other_child = sdk.value_create(other_module, sdk.node_child(other_module, sdk.request_node(other_module, 0), 0))
        wrong_child = sdk.value_create(module, root)
        sdk.scalar_set(first, 7); sdk.scalar_set(second, 9); sdk.child_set(parent, 0, first); sdk.child_set(parent, 1, second)
        projected = sdk.child_get(parent, 0)
        checks['module_close_with_live_values_rejected'] = False
        try: sdk.module_close(module)
        except HostSdkError: checks['module_close_with_live_values_rejected'] = True
        try: sdk.child_set(parent, 0, other_child); checks['cross_module_child_rejected'] = False
        except HostSdkError: checks['cross_module_child_rejected'] = True
        try: sdk.child_set(parent, 0, wrong_child); checks['wrong_schema_child_rejected'] = False
        except HostSdkError: checks['wrong_schema_child_rejected'] = True
        sdk.value_destroy(parent); parent = None
        checks['child_get_returns_independent_owned_handle'] = sdk.scalar_get(projected) == 7
        stale = projected; sdk.value_destroy(projected); projected = None
        # A new allocation after destruction must never revive the stale
        # capability, even if an implementation later recycles storage slots.
        replacement = sdk.value_create(module, first_node)
        try: sdk.scalar_get(stale); checks['stale_child_rejected'] = False
        except HostSdkError: checks['stale_child_rejected'] = True
        try: sdk.value_destroy(stale); checks['double_destroy_rejected'] = False
        except HostSdkError: checks['double_destroy_rejected'] = True
        try: sdk.value_destroy(0); checks['invalid_handle_rejected'] = False
        except HostSdkError: checks['invalid_handle_rejected'] = True
        print(json.dumps({'schema': 'omni.host-sdk-python-ownership/1', 'status': 'PASS' if all(checks.values()) else 'FAIL', 'ownership': 'INDEPENDENT_OWNED_HANDLE_COPY', 'checks': checks}, sort_keys=True))
        if not all(checks.values()): raise SystemExit(1)
    finally:
        for value in (projected, replacement, parent, first, second, wrong_child):
            if value is not None:
                try: sdk.value_destroy(value)
                except HostSdkError: pass
        sdk.module_close(module)
        if other_child is not None:
            try: sdk.value_destroy(other_child)
            except HostSdkError: pass
        sdk.module_close(other_module)


if __name__ == '__main__': main()
