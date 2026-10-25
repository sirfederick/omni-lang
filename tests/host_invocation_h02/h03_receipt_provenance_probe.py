#!/usr/bin/env python3
"""H03 SEC-05 deployment receipt provenance verifier.

The loader deliberately does not consume a receipt.  This probe models the
separate deployment/release verifier frozen by H01A: it binds a receipt to the
exact ELF and its embedded canonical OMID1 descriptor, and proves that a
tampered receipt cannot supply trusted expected identities to module_open.
"""
import copy
import hashlib
import json
import os
import pathlib
import struct

ROOT = pathlib.Path(os.environ['OMNI_H03_EVIDENCE_ROOT'])
OUT = ROOT / 'receipt-provenance'
OUT.mkdir(exist_ok=True)
ARTIFACT = ROOT / 'artifacts' / 'echo.so'
RECEIPT_PATH = pathlib.Path(str(ARTIFACT) + '.omireceipt.json')

def sha(data):
    return hashlib.sha256(data).hexdigest()

def descriptor(raw, expected):
    magic = b'OMID1\0\0\0'
    for start in range(len(raw)):
        if not raw.startswith(magic, start):
            continue
        pos = start + len(magic)
        try:
            def take(size):
                nonlocal pos
                if size < 0 or pos + size > len(raw):
                    raise ValueError('truncated')
                data = raw[pos:pos + size]
                pos += size
                return data
            def u32(): return struct.unpack('<I', take(4))[0]
            def text(): return take(u32()).decode('utf-8')
            fields = {'descriptor_format_version': u32(), 'abi_identifier': text(),
                      'package_origin': text(), 'package_name': text(),
                      'package_version': text(), 'manifest_sha256': take(32).hex(),
                      'semantic_source_sha256': take(32).hex(),
                      'selected_module_path': text(), 'selected_function': text()}
            fields['parameter_type_ids'] = [take(32).hex() for _ in range(u32())]
            fields['return_type_id'] = take(32).hex()
            fields['effect_set'] = [text() for _ in range(u32())]
            fields['target_id'] = text()
            fields['core_runtime_abi_id'] = text()
            fields['core_runtime_build_sha256'] = take(32).hex()
            fields['compiler_sha256'] = take(32).hex()
            fields['build_profile_id'] = text()
            fields['lock_sha256'] = take(32).hex()
            fields['signature_digest'] = take(32).hex()
            fields['build_input_digest'] = take(32).hex()
        except (UnicodeDecodeError, ValueError, struct.error):
            continue
        body = raw[start:pos]
        if sha(body) == expected:
            return fields, body
    raise AssertionError('receipt descriptor was not found canonically')

raw = ARTIFACT.read_bytes()
receipt = json.loads(RECEIPT_PATH.read_text())
fields, body = descriptor(raw, receipt['descriptor_sha256'])
expected = {
    'abi_identifier': fields['abi_identifier'],
    'build_profile_id': fields['build_profile_id'],
    'compiler_sha256': fields['compiler_sha256'],
    'core_runtime_build_sha256': fields['core_runtime_build_sha256'],
    'package_origin': fields['package_origin'],
    'package_name': fields['package_name'],
    'package_version': fields['package_version'],
    'manifest_sha256': fields['manifest_sha256'],
    'semantic_source_sha256': fields['semantic_source_sha256'],
    'lock_sha256': fields['lock_sha256'],
    'selected_host_entry': f"{fields['selected_module_path']}:{fields['selected_function']}",
    'parameter_type_ids': fields['parameter_type_ids'],
    'return_type_id': fields['return_type_id'],
    'signature_digest': fields['signature_digest'],
    'build_input_digest': fields['build_input_digest'],
    'descriptor_sha256': sha(body),
    'artifact_sha256': sha(raw),
}

def verify(candidate):
    return (candidate.get('schema') == 'omni.module-invoke.build-receipt/1' and
            all(candidate.get(name) == value for name, value in expected.items()))

checks = []
def check(name, actual, expected_value=True):
    checks.append({'case_id': 'SEC-05', 'name': name, 'actual': actual,
                   'expected': expected_value, 'passed': actual == expected_value})

check('receipt_matches_verified_artifact_and_descriptor', verify(receipt))
for field in ('artifact_sha256', 'descriptor_sha256', 'compiler_sha256',
              'core_runtime_build_sha256', 'semantic_source_sha256', 'lock_sha256',
              'selected_host_entry', 'build_profile_id', 'build_input_digest'):
    tampered = copy.deepcopy(receipt)
    value = tampered[field]
    tampered[field] = ('0' if value[0] != '0' else '1') + value[1:]
    check(f'tampered_{field}_rejected', verify(tampered), False)

report = {'schema': 'omni.core-host-03-receipt-provenance/1',
          'artifact': str(ARTIFACT), 'artifact_sha256': sha(raw),
          'receipt_sha256': sha(RECEIPT_PATH.read_bytes()),
          'descriptor_sha256': sha(body), 'checks': checks,
          'passed': sum(item['passed'] for item in checks), 'total': len(checks)}
(OUT / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
print(json.dumps({'passed': report['passed'], 'total': report['total']}))
raise SystemExit(0 if report['passed'] == report['total'] else 1)
