#!/usr/bin/env python3
"""Prove that a verified module exposes only its validated OMIS1 schema bytes."""
from __future__ import annotations

import ctypes as c
import hashlib
import json
import os
from pathlib import Path


ROOT = Path(os.environ["OMNI_H02_EVIDENCE_ROOT"])
LIB = c.CDLL(str(ROOT / "dist/runtime/libomni_invocation_v1.so"))
U8, U32, U64, P8 = c.c_uint8, c.c_uint32, c.c_uint64, c.POINTER(c.c_uint8)
LIB.omni_invocation_v1_module_open.argtypes = [P8, U32, P8, P8, c.POINTER(U64)]
LIB.omni_invocation_v1_module_open.restype = U32
LIB.omni_invocation_v1_module_schema_read.argtypes = [U64, P8, U32, c.POINTER(U32)]
LIB.omni_invocation_v1_module_schema_read.restype = U32
LIB.omni_invocation_v1_module_close.argtypes = [U64]
LIB.omni_invocation_v1_module_close.restype = U32


def array(value: bytes):
    return (U8 * len(value)).from_buffer_copy(value) if value else None


def main() -> None:
    artifact = ROOT / "artifacts/echo_pair.so"
    receipt = json.loads(Path(str(artifact) + ".omireceipt.json").read_text(encoding="utf-8"))
    handle = U64()
    path = str(artifact).encode("utf-8")
    opened = LIB.omni_invocation_v1_module_open(
        array(path), len(path), array(bytes.fromhex(receipt["artifact_sha256"])),
        array(bytes.fromhex(receipt["descriptor_sha256"])), c.byref(handle)
    )
    checks: dict[str, bool] = {"module_open": opened == 0}
    length = U32()
    first = LIB.omni_invocation_v1_module_schema_read(handle, None, 0, c.byref(length)) if opened == 0 else opened
    checks["bounded_size_probe"] = first == 6 and length.value > 44
    schema = (U8 * length.value)()
    second = LIB.omni_invocation_v1_module_schema_read(handle, schema, length.value, c.byref(length)) if opened == 0 else opened
    payload = bytes(schema[:length.value])
    checks["schema_read"] = second == 0
    checks["schema_magic_version"] = payload[:8] == b"OMIS1\0\0\0" and payload[8:12] == b"\x01\0\0\0"
    checks["descriptor_signature_binding"] = payload[12:44] == bytes.fromhex(receipt["signature_digest"])
    checks["schema_not_omi1"] = payload[:5] != b"OMIV1"
    closed = LIB.omni_invocation_v1_module_close(handle) if opened == 0 else opened
    checks["module_close"] = closed == 0
    stale_length = U32()
    checks["stale_handle_denied"] = LIB.omni_invocation_v1_module_schema_read(handle, None, 0, c.byref(stale_length)) == 12
    report = {
        "schema": "omni.host-sdk-schema-probe/1",
        "status": "PASS" if all(checks.values()) else "FAIL",
        "checks": checks,
        "schema_sha256": hashlib.sha256(payload).hexdigest(),
        "artifact_sha256": receipt["artifact_sha256"],
        "descriptor_sha256": receipt["descriptor_sha256"],
    }
    (ROOT / "sdk_schema_report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, sort_keys=True))
    raise SystemExit(0 if report["status"] == "PASS" else 1)


if __name__ == "__main__":
    main()
