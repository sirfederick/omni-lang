#!/usr/bin/env python3
"""Full real-runtime structural matrix through the official Python binding."""
from __future__ import annotations

import ctypes as c
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(os.environ['OMNI_H02_EVIDENCE_ROOT'])
CORE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(CORE / 'bindings/python'))
from omni_host_sdk import HostSdk, HostSdkError  # noqa: E402
from sdk_composite_probe import U8, U32, U64, arr, create, destroy, invoke, raw_close, raw_open, read  # noqa: E402

NAMES = ('echo_bool','echo_u8','echo_u16','echo_u32','echo_u64','echo_i8','echo_i16','echo_i32','echo_i64','echo_char','echo_text','echo_bytes','echo_tuple','echo_array','echo_pair','echo_choice','echo_option','echo_result','echo_nested')

# These are ABI v1 schema-node kinds, deliberately recorded numerically in the
# evidence too: the report is an observation of the public ABI, not a second
# schema interpretation.
KIND_NAMES = {
    1: 'Bool', 2: 'U8', 3: 'U16', 4: 'U32', 5: 'U64', 6: 'I8', 7: 'I16',
    8: 'I32', 9: 'I64', 10: 'Char', 11: 'Text', 12: 'Bytes', 13: 'Tuple',
    14: 'Array', 15: 'Record', 16: 'Enum', 17: 'Option', 18: 'Result',
}

def build(sdk, module, node, owned, alternate=False):
    kind = sdk.node_kind(module, node); value = sdk.value_create(module, node); owned.append(value)
    if kind <= 10: sdk.scalar_set(value, 0x1f642 if kind == 10 else 1)
    elif kind in (11, 12): sdk.data_set(value, 'Ω'.encode() if kind == 11 else b'\0\xffx')
    elif kind in (16, 17, 18):
        count = sdk.node_child_count(module, node); arm = 0 if alternate else (1 if kind == 16 and count > 1 else (1 if kind == 17 else 0)); sdk.discriminant_set(value, arm)
    else: arm = 0
    for index in range(sdk.child_count(value)):
        schema_index = 0 if kind == 14 else (arm if kind == 16 else index)
        child = build(sdk, module, sdk.node_child(module, node, schema_index), owned, alternate); sdk.child_set(value, index, child)
    return value


def _schema_child_index(kind, discriminant, value_index):
    """Map one materialized value child to its public schema child node.

    Arrays repeat their sole schema child; enum children are selected by their
    active discriminant.  The other composite ABI kinds use their positional
    public schema child.  This mirrors construction above while keeping the
    evidence traversal entirely through the C ABI exposed by the Python SDK.
    """
    if kind == 14:
        return 0
    if kind == 16:
        return discriminant
    return value_index


def normalize(sdk, module, node, value):
    """Return complete semantic ABI-visible value evidence and release views.

    Each temporary child is independently projected by value_child_get and
    destroyed after observation.  This both checks the ownership contract and
    prevents the matrix from retaining hidden references while module closure
    is asserted at the end of each fixture.
    """
    kind = sdk.node_kind(module, node)
    assert sdk.value_kind(value) == kind
    typeid = sdk.node_typeid(module, node)
    assert sdk.value_typeid(value) == typeid
    schema_child_count = sdk.node_child_count(module, node)
    labels = []
    for index in range(schema_child_count):
        try:
            labels.append(sdk.node_label(module, node, index))
        except HostSdkError:
            labels.append(None)
    result = {
        'kind': KIND_NAMES[kind],
        'kind_code': kind,
        'typeid': typeid.hex(),
        'labels': labels,
        'schema_child_count': schema_child_count,
    }
    if kind <= 10:
        result['scalar_bits'] = sdk.scalar_get(value)
    elif kind == 11:
        # UTF-8 is verified at the real codec boundary; retain an unambiguous
        # normalized representation for stable evidence.
        result['text'] = sdk.data_get(value).decode('utf-8')
    elif kind == 12:
        result['bytes_hex'] = sdk.data_get(value).hex()

    discriminant = None
    if kind in (16, 17, 18):
        discriminant = sdk.discriminant_get(value)
        result['discriminant'] = discriminant

    child_count = sdk.child_count(value)
    result['value_child_count'] = child_count
    children = []
    for index in range(child_count):
        child = sdk.child_get(value, index)
        try:
            child_node = sdk.node_child(
                module, node, _schema_child_index(kind, discriminant, index)
            )
            children.append(normalize(sdk, module, child_node, child))
        finally:
            sdk.value_destroy(child)
    result['children'] = children
    return result

def one(name, alternate=False):
    artifact = ROOT / f'artifacts/{name}.so'; receipt = json.loads(Path(f'{artifact}.omireceipt.json').read_text())
    sdk = HostSdk(ROOT / 'dist/runtime/libomni_invocation_v1.so'); module = sdk.module_open(artifact, bytes.fromhex(receipt['artifact_sha256']), bytes.fromhex(receipt['descriptor_sha256']))
    owned = []; raw = invocation = None
    try:
        root = sdk.request_node(module, 0); argument = build(sdk, module, root, owned, alternate)
        assert sdk.value_kind(argument) == sdk.node_kind(module, root) and sdk.value_typeid(argument) == sdk.node_typeid(module, root)
        request_semantic = normalize(sdk, module, root, argument)
        request = sdk.request_encode(module, [argument]); raw_handle = U64(); path = str(artifact).encode()
        assert raw_open(arr(path), len(path), arr(bytes.fromhex(receipt['artifact_sha256'])), arr(bytes.fromhex(receipt['descriptor_sha256'])), c.byref(raw_handle)) == 0; raw = raw_handle.value
        inv = U64(); trace = (U8 * 16)(); assert create(raw, arr(request), len(request), None, 0, 0, time.monotonic_ns()+5_000_000_000, 1_000_000, 65_536, 0, trace, c.byref(inv)) == 0; invocation = inv.value
        effect, length = U32(), U32(); assert invoke(invocation, c.byref(effect), c.byref(length)) == 0
        frame, copied = (U8 * length.value)(), U32(); assert read(invocation, frame, length.value, c.byref(copied)) == 0
        decoded = sdk.result_decode(module, bytes(frame[:copied.value])); owned.append(decoded)
        assert sdk.value_typeid(decoded) == sdk.node_typeid(module, root)
        result_semantic = normalize(sdk, module, root, decoded)
        assert result_semantic == request_semantic
        return {
            'fixture': name,
            'alternate': alternate,
            'request_bytes': len(request),
            'result_bytes': copied.value,
            'typeid': sdk.node_typeid(module, root).hex(),
            'request_semantic': request_semantic,
            'result_semantic': result_semantic,
            'semantic_equality': 'PASS',
        }
    finally:
        for value in reversed(owned):
            try: sdk.value_destroy(value)
            except Exception: pass
        if invocation is not None: assert destroy(invocation) == 0
        if raw is not None: assert raw_close(raw) == 0
        sdk.module_close(module)

def main():
    rows = [one(name) for name in NAMES] + [one(name, True) for name in ('echo_choice','echo_option','echo_result')]
    report = {'schema':'omni.host-sdk-python-structural-matrix/1','status':'PASS','real_runtime_exercised':True,'fixtures':rows}
    (ROOT/'python_structural_matrix.json').write_text(json.dumps(report, indent=2)+'\n'); print(json.dumps({'status':'PASS','fixtures':len(rows)}))

if __name__ == '__main__': main()
