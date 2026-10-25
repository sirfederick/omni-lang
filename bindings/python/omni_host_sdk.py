"""Thin ctypes binding for the public Omni Host SDK ABI v1.

This module intentionally exposes opaque handles and opaque OMI1 byte frames;
the canonical codec stays in the native Core library.
"""
from __future__ import annotations

import ctypes as c
from pathlib import Path


_U8, _U32, _U64 = c.c_uint8, c.c_uint32, c.c_uint64
_P8 = c.POINTER(_U8)


class HostSdkError(RuntimeError):
    pass


def _array(raw: bytes):
    return (_U8 * len(raw)).from_buffer_copy(raw) if raw else None


class HostSdk:
    def __init__(self, runtime_library: str | Path):
        self._lib = c.CDLL(str(runtime_library))
        self._bind('omni_host_sdk_v1_module_open', [_P8, _U32, _P8, _P8, c.POINTER(_U64)])
        self._bind('omni_host_sdk_v1_module_close', [_U64])
        self._bind('omni_host_sdk_v1_module_request_count', [_U64, c.POINTER(_U32)])
        self._bind('omni_host_sdk_v1_module_request_node', [_U64, _U32, c.POINTER(_U32)])
        self._bind('omni_host_sdk_v1_module_result_node', [_U64, c.POINTER(_U32)])
        self._bind('omni_host_sdk_v1_schema_node_kind', [_U64, _U32, c.POINTER(_U32)])
        self._bind('omni_host_sdk_v1_schema_node_typeid', [_U64, _U32, _P8])
        self._bind('omni_host_sdk_v1_schema_node_child_count', [_U64, _U32, c.POINTER(_U32)])
        self._bind('omni_host_sdk_v1_schema_node_child', [_U64, _U32, _U32, c.POINTER(_U32)])
        self._bind('omni_host_sdk_v1_schema_node_label_read', [_U64, _U32, _U32, _P8, _U32, c.POINTER(_U32)])
        self._bind('omni_host_sdk_v1_value_create', [_U64, _U32, c.POINTER(_U64)])
        self._bind('omni_host_sdk_v1_value_destroy', [_U64])
        self._bind('omni_host_sdk_v1_value_scalar_set', [_U64, _U64])
        self._bind('omni_host_sdk_v1_value_scalar_get', [_U64, c.POINTER(_U64)])
        self._bind('omni_host_sdk_v1_value_kind', [_U64, c.POINTER(_U32)])
        self._bind('omni_host_sdk_v1_value_typeid', [_U64, _P8])
        self._bind('omni_host_sdk_v1_value_data_set', [_U64, _P8, _U32])
        self._bind('omni_host_sdk_v1_value_data_read', [_U64, _P8, _U32, c.POINTER(_U32)])
        self._bind('omni_host_sdk_v1_value_discriminant_set', [_U64, _U32])
        self._bind('omni_host_sdk_v1_value_discriminant_get', [_U64, c.POINTER(_U32)])
        self._bind('omni_host_sdk_v1_value_child_count', [_U64, c.POINTER(_U32)])
        self._bind('omni_host_sdk_v1_value_child_set', [_U64, _U32, _U64])
        self._bind('omni_host_sdk_v1_value_child_get', [_U64, _U32, c.POINTER(_U64)])
        self._bind('omni_host_sdk_v1_request_encode', [_U64, c.POINTER(_U64), _U32, _P8, _U32, c.POINTER(_U32)])
        self._bind('omni_host_sdk_v1_result_decode', [_U64, _P8, _U32, c.POINTER(_U64)])

    def _bind(self, name, args):
        function = getattr(self._lib, name)
        function.argtypes, function.restype = args, _U32

    @staticmethod
    def _check(status: int) -> None:
        if status:
            raise HostSdkError(f'omni_host_sdk_v1 status={status}')

    def module_open(self, artifact: str | Path, artifact_sha256: bytes, descriptor_sha256: bytes) -> int:
        if len(artifact_sha256) != 32 or len(descriptor_sha256) != 32:
            raise ValueError('expected SHA-256 values')
        encoded = str(Path(artifact).resolve()).encode()
        module = _U64()
        self._check(self._lib.omni_host_sdk_v1_module_open(_array(encoded), len(encoded), _array(artifact_sha256), _array(descriptor_sha256), c.byref(module)))
        return module.value

    def module_close(self, module: int) -> None:
        self._check(self._lib.omni_host_sdk_v1_module_close(module))

    def request_count(self, module: int) -> int:
        count = _U32(); self._check(self._lib.omni_host_sdk_v1_module_request_count(module, c.byref(count))); return count.value

    def request_node(self, module: int, index: int) -> int:
        node = _U32(); self._check(self._lib.omni_host_sdk_v1_module_request_node(module, index, c.byref(node))); return node.value

    def result_node(self, module: int) -> int:
        node = _U32(); self._check(self._lib.omni_host_sdk_v1_module_result_node(module, c.byref(node))); return node.value

    def node_kind(self, module: int, node: int) -> int:
        kind = _U32(); self._check(self._lib.omni_host_sdk_v1_schema_node_kind(module, node, c.byref(kind))); return kind.value

    def node_typeid(self, module: int, node: int) -> bytes:
        result = (_U8 * 32)(); self._check(self._lib.omni_host_sdk_v1_schema_node_typeid(module, node, result)); return bytes(result)

    def node_label(self, module: int, node: int, index: int) -> str:
        size = _U32(); status = self._lib.omni_host_sdk_v1_schema_node_label_read(module, node, index, None, 0, c.byref(size))
        if status != 6: self._check(status)
        result = (_U8 * size.value)(); self._check(self._lib.omni_host_sdk_v1_schema_node_label_read(module, node, index, result, size.value, c.byref(size))); return bytes(result[:size.value]).decode('utf-8')

    def node_child_count(self, module: int, node: int) -> int:
        count = _U32(); self._check(self._lib.omni_host_sdk_v1_schema_node_child_count(module, node, c.byref(count))); return count.value

    def node_child(self, module: int, node: int, index: int) -> int:
        child = _U32(); self._check(self._lib.omni_host_sdk_v1_schema_node_child(module, node, index, c.byref(child))); return child.value

    def value_create(self, module: int, node: int) -> int:
        value = _U64(); self._check(self._lib.omni_host_sdk_v1_value_create(module, node, c.byref(value))); return value.value

    def value_destroy(self, value: int) -> None:
        self._check(self._lib.omni_host_sdk_v1_value_destroy(value))

    def scalar_set(self, value: int, bits: int) -> None:
        self._check(self._lib.omni_host_sdk_v1_value_scalar_set(value, bits))

    def scalar_get(self, value: int) -> int:
        bits = _U64(); self._check(self._lib.omni_host_sdk_v1_value_scalar_get(value, c.byref(bits))); return bits.value

    def value_kind(self, value: int) -> int:
        result = _U32(); self._check(self._lib.omni_host_sdk_v1_value_kind(value, c.byref(result))); return result.value

    def value_typeid(self, value: int) -> bytes:
        result = (_U8 * 32)(); self._check(self._lib.omni_host_sdk_v1_value_typeid(value, result)); return bytes(result)

    def data_set(self, value: int, data: bytes) -> None:
        self._check(self._lib.omni_host_sdk_v1_value_data_set(value, _array(data), len(data)))

    def data_get(self, value: int) -> bytes:
        size = _U32(); status = self._lib.omni_host_sdk_v1_value_data_read(value, None, 0, c.byref(size))
        if status != 6: self._check(status)
        result = (_U8 * size.value)(); self._check(self._lib.omni_host_sdk_v1_value_data_read(value, result, size.value, c.byref(size))); return bytes(result[:size.value])

    def discriminant_set(self, value: int, discriminant: int) -> None:
        self._check(self._lib.omni_host_sdk_v1_value_discriminant_set(value, discriminant))

    def discriminant_get(self, value: int) -> int:
        result = _U32(); self._check(self._lib.omni_host_sdk_v1_value_discriminant_get(value, c.byref(result))); return result.value

    def child_count(self, value: int) -> int:
        result = _U32(); self._check(self._lib.omni_host_sdk_v1_value_child_count(value, c.byref(result))); return result.value

    def child_set(self, parent: int, index: int, child: int) -> None:
        self._check(self._lib.omni_host_sdk_v1_value_child_set(parent, index, child))

    def child_get(self, parent: int, index: int) -> int:
        result = _U64(); self._check(self._lib.omni_host_sdk_v1_value_child_get(parent, index, c.byref(result))); return result.value

    def request_encode(self, module: int, values: list[int]) -> bytes:
        handles = (_U64 * len(values))(*values); copied = _U32()
        status = self._lib.omni_host_sdk_v1_request_encode(module, handles, len(values), None, 0, c.byref(copied))
        if status != 6:
            self._check(status)
        result = (_U8 * copied.value)()
        self._check(self._lib.omni_host_sdk_v1_request_encode(module, handles, len(values), result, copied.value, c.byref(copied)))
        return bytes(result[:copied.value])

    def result_decode(self, module: int, frame: bytes) -> int:
        value = _U64(); self._check(self._lib.omni_host_sdk_v1_result_decode(module, _array(frame), len(frame), c.byref(value))); return value.value
