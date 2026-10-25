#!/usr/bin/env python3
"""Structural matrix through the public C Host SDK ABI v1.

ctypes is only the test harness transport.  Every operation below calls the
published C ABI; it does not inspect a private runtime type or parse OMI1.
"""
from __future__ import annotations

import ctypes as c
import json
import os
import time
from pathlib import Path

from sdk_composite_probe import U8, U32, U64, arr, create, destroy, invoke, raw_close, raw_open, read

ROOT = Path(os.environ['OMNI_H02_EVIDENCE_ROOT'])
LIB = c.CDLL(str(ROOT / 'dist/runtime/libomni_invocation_v1.so'))
NAMES = ('echo_bool', 'echo_u8', 'echo_u16', 'echo_u32', 'echo_u64', 'echo_i8',
         'echo_i16', 'echo_i32', 'echo_i64', 'echo_char', 'echo_text', 'echo_bytes',
         'echo_tuple', 'echo_array', 'echo_pair', 'echo_choice', 'echo_option',
         'echo_result', 'echo_nested')
KIND_NAMES = {1:'Bool', 2:'U8', 3:'U16', 4:'U32', 5:'U64', 6:'I8', 7:'I16',
              8:'I32', 9:'I64', 10:'Char', 11:'Text', 12:'Bytes', 13:'Tuple',
              14:'Array', 15:'Record', 16:'Enum', 17:'Option', 18:'Result'}

P8 = c.POINTER(U8)
def fn(name, args):
    function = getattr(LIB, name); function.argtypes = args; function.restype = U32; return function

open_sdk = fn('omni_host_sdk_v1_module_open', [P8,U32,P8,P8,c.POINTER(U64)])
close_sdk = fn('omni_host_sdk_v1_module_close', [U64])
request_node = fn('omni_host_sdk_v1_module_request_node', [U64,U32,c.POINTER(U32)])
node_kind = fn('omni_host_sdk_v1_schema_node_kind', [U64,U32,c.POINTER(U32)])
node_typeid = fn('omni_host_sdk_v1_schema_node_typeid', [U64,U32,P8])
node_child_count = fn('omni_host_sdk_v1_schema_node_child_count', [U64,U32,c.POINTER(U32)])
node_child = fn('omni_host_sdk_v1_schema_node_child', [U64,U32,U32,c.POINTER(U32)])
node_label = fn('omni_host_sdk_v1_schema_node_label_read', [U64,U32,U32,P8,U32,c.POINTER(U32)])
value_create = fn('omni_host_sdk_v1_value_create', [U64,U32,c.POINTER(U64)])
value_destroy = fn('omni_host_sdk_v1_value_destroy', [U64])
value_kind = fn('omni_host_sdk_v1_value_kind', [U64,c.POINTER(U32)])
value_typeid = fn('omni_host_sdk_v1_value_typeid', [U64,P8])
scalar_set = fn('omni_host_sdk_v1_value_scalar_set', [U64,U64])
scalar_get = fn('omni_host_sdk_v1_value_scalar_get', [U64,c.POINTER(U64)])
data_set = fn('omni_host_sdk_v1_value_data_set', [U64,P8,U32])
data_read = fn('omni_host_sdk_v1_value_data_read', [U64,P8,U32,c.POINTER(U32)])
disc_set = fn('omni_host_sdk_v1_value_discriminant_set', [U64,U32])
disc_get = fn('omni_host_sdk_v1_value_discriminant_get', [U64,c.POINTER(U32)])
value_child_count = fn('omni_host_sdk_v1_value_child_count', [U64,c.POINTER(U32)])
value_child_set = fn('omni_host_sdk_v1_value_child_set', [U64,U32,U64])
value_child_get = fn('omni_host_sdk_v1_value_child_get', [U64,U32,c.POINTER(U64)])
encode = fn('omni_host_sdk_v1_request_encode', [U64,c.POINTER(U64),U32,P8,U32,c.POINTER(U32)])
decode = fn('omni_host_sdk_v1_result_decode', [U64,P8,U32,c.POINTER(U64)])

def get_kind(module, node):
    out=U32(); assert node_kind(module,node,c.byref(out)) == 0; return out.value
def get_typeid(module, node):
    out=(U8*32)(); assert node_typeid(module,node,out) == 0; return bytes(out)
def get_node_count(module, node):
    out=U32(); assert node_child_count(module,node,c.byref(out)) == 0; return out.value
def get_node_child(module, node, index):
    out=U32(); assert node_child(module,node,index,c.byref(out)) == 0; return out.value
def get_value_kind(value):
    out=U32(); assert value_kind(value,c.byref(out)) == 0; return out.value
def get_value_typeid(value):
    out=(U8*32)(); assert value_typeid(value,out) == 0; return bytes(out)
def get_value_count(value):
    out=U32(); assert value_child_count(value,c.byref(out)) == 0; return out.value
def label(module, node, index):
    size=U32(); status=node_label(module,node,index,None,0,c.byref(size))
    if status != 6: return None
    out=(U8*size.value)(); assert node_label(module,node,index,out,size.value,c.byref(size)) == 0
    return bytes(out[:size.value]).decode('utf-8')
def scalar(value):
    out=U64(); assert scalar_get(value,c.byref(out)) == 0; return out.value
def data(value):
    size=U32(); assert data_read(value,None,0,c.byref(size)) == 6
    out=(U8*size.value)(); assert data_read(value,out,size.value,c.byref(size)) == 0; return bytes(out[:size.value])
def discriminant(value):
    out=U32(); assert disc_get(value,c.byref(out)) == 0; return out.value
def schema_index(kind, arm, index): return 0 if kind == 14 else (arm if kind == 16 else index)

def build(module, node, owned, alternate=False):
    kind=get_kind(module,node); out=U64(); assert value_create(module,node,c.byref(out)) == 0; value=out.value; owned.append(value)
    if kind <= 10: assert scalar_set(value,0x1f642 if kind == 10 else 1) == 0
    elif kind in (11,12):
        payload='Ω'.encode() if kind == 11 else b'\0\xffx'; assert data_set(value,arr(payload),len(payload)) == 0
    arm=0
    if kind in (16,17,18):
        count=get_node_count(module,node); arm=0 if alternate else (1 if kind == 16 and count > 1 else (1 if kind == 17 else 0)); assert disc_set(value,arm) == 0
    for index in range(get_value_count(value)):
        child=build(module,get_node_child(module,node,schema_index(kind,arm,index)),owned,alternate)
        assert value_child_set(value,index,child) == 0
    return value

def normalize(module, node, value):
    kind=get_kind(module,node); typeid=get_typeid(module,node)
    assert get_value_kind(value) == kind and get_value_typeid(value) == typeid
    node_count=get_node_count(module,node)
    result={'kind':KIND_NAMES[kind], 'kind_code':kind, 'typeid':typeid.hex(),
            'labels':[label(module,node,index) for index in range(node_count)],
            'schema_child_count':node_count}
    if kind <= 10: result['scalar_bits']=scalar(value)
    elif kind == 11: result['text']=data(value).decode('utf-8')
    elif kind == 12: result['bytes_hex']=data(value).hex()
    arm=None
    if kind in (16,17,18): arm=discriminant(value); result['discriminant']=arm
    count=get_value_count(value); result['value_child_count']=count; children=[]
    for index in range(count):
        child=U64(); assert value_child_get(value,index,c.byref(child)) == 0
        try: children.append(normalize(module,get_node_child(module,node,schema_index(kind,arm,index)),child.value))
        finally: assert value_destroy(child.value) == 0
    result['children']=children
    return result

def one(name, alternate=False):
    artifact=ROOT/f'artifacts/{name}.so'; receipt=json.loads(Path(f'{artifact}.omireceipt.json').read_text())
    path=str(artifact).encode(); module=U64(); assert open_sdk(arr(path),len(path),arr(bytes.fromhex(receipt['artifact_sha256'])),arr(bytes.fromhex(receipt['descriptor_sha256'])),c.byref(module)) == 0
    owned=[]; raw=None; invocation=None
    try:
        root=U32(); assert request_node(module.value,0,c.byref(root)) == 0
        argument=build(module.value,root.value,owned,alternate); request_semantic=normalize(module.value,root.value,argument)
        handles=(U64*1)(argument); needed=U32(); assert encode(module.value,handles,1,None,0,c.byref(needed)) == 6
        request=(U8*needed.value)(); assert encode(module.value,handles,1,request,needed.value,c.byref(needed)) == 0
        raw_handle=U64(); assert raw_open(arr(path),len(path),arr(bytes.fromhex(receipt['artifact_sha256'])),arr(bytes.fromhex(receipt['descriptor_sha256'])),c.byref(raw_handle)) == 0; raw=raw_handle.value
        invocation_handle=U64(); trace=(U8*16)(); assert create(raw,request,needed.value,None,0,0,time.monotonic_ns()+5_000_000_000,1_000_000,65_536,0,trace,c.byref(invocation_handle)) == 0; invocation=invocation_handle.value
        effect,length=U32(),U32(); assert invoke(invocation,c.byref(effect),c.byref(length)) == 0
        frame=(U8*length.value)(); copied=U32(); assert read(invocation,frame,length.value,c.byref(copied)) == 0
        decoded=U64(); assert decode(module.value,frame,copied.value,c.byref(decoded)) == 0; owned.append(decoded.value)
        result_semantic=normalize(module.value,root.value,decoded.value); assert result_semantic == request_semantic
        return {'fixture':name,'alternate':alternate,'request_bytes':needed.value,'result_bytes':copied.value,
                'typeid':get_typeid(module.value,root.value).hex(),'request_semantic':request_semantic,
                'result_semantic':result_semantic,'semantic_equality':'PASS'}
    finally:
        for value in reversed(owned): assert value_destroy(value) == 0
        if invocation is not None: assert destroy(invocation) == 0
        if raw is not None: assert raw_close(raw) == 0
        assert close_sdk(module.value) == 0

def main():
    rows=[one(name) for name in NAMES]+[one(name,True) for name in ('echo_choice','echo_option','echo_result')]
    report={'schema':'omni.host-sdk-c-structural-matrix/1','status':'PASS','real_runtime_exercised':True,
            'public_c_abi_only':True,'fixtures':rows}
    (ROOT/'c_structural_matrix.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({'status':'PASS','fixtures':len(rows)}))

if __name__ == '__main__': main()
