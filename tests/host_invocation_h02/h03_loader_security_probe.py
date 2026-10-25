#!/usr/bin/env python3
"""H03 SEC-04 and SEC-08: hostile artifact paths and ELF load barriers."""
import ctypes as c
import hashlib
import json
import os
import pathlib
import shutil
import struct
import subprocess
import threading

ROOT = pathlib.Path(os.environ['OMNI_H03_EVIDENCE_ROOT'])
OUT = ROOT / 'loader-security'
LIBRARY = ROOT / 'dist/runtime/libomni_invocation_v1.so'


def sha_bytes(value):
    return hashlib.sha256(value).hexdigest()


def sha(path):
    return sha_bytes(path.read_bytes())


def descriptor_region(raw, expected):
    magic = b'OMID1\0\0\0'
    for start in range(len(raw)):
        if not raw.startswith(magic, start):
            continue
        pos = start + 12
        try:
            def take(count):
                nonlocal pos
                if count < 0 or pos + count > len(raw):
                    raise ValueError()
                result = raw[pos:pos + count]
                pos += count
                return result
            def string():
                return take(struct.unpack('<I', take(4))[0])
            for _ in range(4): string()
            take(64); string(); string()
            take(struct.unpack('<I', take(4))[0] * 32 + 32)
            for _ in range(struct.unpack('<I', take(4))[0]): string()
            string(); string(); take(64); string(); take(96)
        except (ValueError, struct.error):
            continue
        candidate = raw[start:pos]
        if sha_bytes(candidate) == expected:
            return candidate
    raise RuntimeError('canonical descriptor not found')


def main():
    if OUT.exists():
        raise SystemExit('loader security evidence already exists')
    OUT.mkdir()
    source = ROOT / 'artifacts/zero.so'
    receipt = json.loads(pathlib.Path(str(source) + '.omireceipt.json').read_text())
    raw = source.read_bytes()
    descriptor = descriptor_region(raw, receipt['descriptor_sha256'])
    library = c.CDLL(str(LIBRARY))
    U8, U32, U64 = c.c_uint8, c.c_uint32, c.c_uint64
    P8 = c.POINTER(U8)
    library.omni_invocation_v1_module_open.argtypes = [P8, U32, P8, P8, c.POINTER(U64)]
    library.omni_invocation_v1_module_open.restype = U32
    library.omni_invocation_v1_module_close.argtypes = [U64]
    library.omni_invocation_v1_module_close.restype = U32
    def array(value): return (U8 * len(value)).from_buffer_copy(value)
    def opening(path, artifact_hash, descriptor_hash):
        handle = U64(); encoded = str(path).encode()
        status = library.omni_invocation_v1_module_open(
            array(encoded), len(encoded), array(bytes.fromhex(artifact_hash)),
            array(bytes.fromhex(descriptor_hash)), c.byref(handle))
        if status == 0 and library.omni_invocation_v1_module_close(handle):
            raise RuntimeError('accepted binding could not close')
        return status, handle.value
    rows = []
    def check(name, observed, expected):
        rows.append({'name': name, 'observed': observed, 'expected': expected,
                     'passed': observed == expected})

    # O_NOFOLLOW rejects the path before it can be replaced by a different file.
    symlink = OUT / 'zero-link.so'
    symlink.symlink_to(source)
    check('symlink_rejected', opening(symlink, receipt['artifact_sha256'],
          receipt['descriptor_sha256']), (3, 0))

    # Race an exact artifact with a distinct valid ELF. A successful open can
    # only have copied the exact expected bytes; every other observation fails.
    alternate = ROOT / 'artifacts/echo.so'
    raced = OUT / 'raced.so'
    left, right = OUT / 'left.so', OUT / 'right.so'
    shutil.copy2(source, left); shutil.copy2(alternate, right); shutil.copy2(left, raced)
    stop = threading.Event()
    def replace_loop():
        while not stop.is_set():
            for candidate in (left, right):
                staging = OUT / 'staging.so'
                shutil.copy2(candidate, staging)
                os.replace(staging, raced)
    thread = threading.Thread(target=replace_loop)
    thread.start()
    statuses = []
    try:
        for _ in range(128):
            status, handle = opening(raced, receipt['artifact_sha256'], receipt['descriptor_sha256'])
            statuses.append((status, handle != 0))
    finally:
        stop.set(); thread.join(timeout=5)
    check('replacement_race_no_toctou', all(status in (0, 3) and (status == 0) == live
          for status, live in statuses), True)

    # A self-contained ELF with an init array must be rejected before dlopen;
    # the constructor would otherwise write this sentinel.
    sentinel = OUT / 'constructor-ran'
    descriptor_c = ','.join(str(value) for value in descriptor)
    source_c = OUT / 'constructor.c'
    source_c.write_text('''#include <fcntl.h>
#include <stdint.h>
#include <unistd.h>
__attribute__((visibility("default"))) const uint8_t omni_module_v1_descriptor[]={DESCRIPTOR};
__attribute__((constructor)) static void forbidden(void){int f=open("SENTINEL",O_CREAT|O_WRONLY,0600);if(f>=0){write(f,"x",1);close(f);}}
__attribute__((visibility("default"))) uint32_t omni_module_v1_entry(uint32_t a,const uint8_t*b,uint32_t c,const uint8_t*d,uint32_t e,uint64_t f,uint64_t g,uint64_t h,const uint8_t i[16],const uint32_t*j,uint8_t*k,uint32_t l,uint32_t*m,uint32_t*n){(void)a;(void)b;(void)c;(void)d;(void)e;(void)f;(void)g;(void)h;(void)i;(void)j;(void)k;(void)l;*m=0;*n=0;return 0;}
'''.replace('DESCRIPTOR', descriptor_c).replace('SENTINEL', str(sentinel)))
    constructor = OUT / 'constructor.so'
    command = ['clang', '--target=x86_64-unknown-linux-gnu', '-O2', '-shared', '-fPIC',
               '-fvisibility=hidden', '-nostartfiles', str(source_c), '-o', str(constructor)]
    result = subprocess.run(command, capture_output=True, text=True)
    check('constructor_fixture_build', result.returncode, 0)
    if result.returncode == 0:
        check('constructor_rejected_before_execution',
              (opening(constructor, sha(constructor), sha_bytes(descriptor)), sentinel.exists()),
              ((3, 0), False))
    report = {'schema': 'omni.core-host-03-loader-security/1',
              'source_artifact_sha256': sha(source), 'loader_sha256': sha(LIBRARY),
              'checks': rows, 'passed': sum(row['passed'] for row in rows), 'total': len(rows)}
    (OUT / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({'passed': report['passed'], 'total': report['total']}))
    return 0 if report['passed'] == report['total'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
