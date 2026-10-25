#!/usr/bin/env python3
"""Deterministic generated Python/Node consumers over real Host SDK frames."""
from __future__ import annotations

import ctypes as c
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT=Path(os.environ['OMNI_H02_EVIDENCE_ROOT']); CORE=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(CORE/'bindings/python'))
from omni_host_sdk import HostSdk  # noqa: E402
from sdk_composite_probe import U8,U32,U64,arr,create,destroy,invoke as raw_invoke,raw_close,raw_open,read

ARTIFACT=ROOT/'artifacts/echo_pair.so'; RECEIPT=json.loads(Path(f'{ARTIFACT}.omireceipt.json').read_text())
U64_ARTIFACT=ROOT/'artifacts/echo_u64.so'; U64_RECEIPT=json.loads(Path(f'{U64_ARTIFACT}.omireceipt.json').read_text())
CHOICE_ARTIFACT=ROOT/'artifacts/echo_choice.so'; CHOICE_RECEIPT=json.loads(Path(f'{CHOICE_ARTIFACT}.omireceipt.json').read_text())
# `Choice { Empty, Full(u32) }`: the payload-less arm has a label but no schema child.
CHOICE_CASES=(({'tag':0},{'tag':0,'value':None}),({'tag':1,'value':9},{'tag':1,'value':9}))
BOOL_MATRIX_ARTIFACT=ROOT/'artifacts/echo_bool_matrix.so'; BOOL_MATRIX_RECEIPT=json.loads(Path(f'{BOOL_MATRIX_ARTIFACT}.omireceipt.json').read_text())
# Both Bool arms alongside U32/U64 in one record: a decode that coerces Bool to
# a number cannot hide behind a legal 0/1 integer value on either arm.
BOOL_MATRIX_REQUEST={'bool_false':False,'bool_true':True,'count_u32':4242,'count_u64':18446744073709551615}
RUNTIME=ROOT/'dist/runtime/libomni_invocation_v1.so'; OUT=ROOT/'generated'; OUT.mkdir()

def run(args):
    completed=subprocess.run(args,capture_output=True,text=True)
    if completed.returncode: raise RuntimeError(completed.stdout+completed.stderr)

def generate(language, suffix, artifact=ARTIFACT, receipt=RECEIPT):
    output=OUT/f'{language}{suffix}'
    run(['python3',str(CORE/'tools/omni_sdk_codegen.py'),'--language',language,'--runtime',str(RUNTIME),'--artifact',str(artifact),'--artifact-sha256',receipt['artifact_sha256'],'--descriptor-sha256',receipt['descriptor_sha256'],'--output',str(output)])
    return output

def invoke(frame: bytes, artifact=ARTIFACT, receipt=RECEIPT) -> bytes:
    path=str(artifact).encode(); module=U64(); invocation=None
    try:
        assert raw_open(arr(path),len(path),arr(bytes.fromhex(receipt['artifact_sha256'])),arr(bytes.fromhex(receipt['descriptor_sha256'])),c.byref(module)) == 0
        trace=(U8*16)(); handle=U64(); assert create(module.value,arr(frame),len(frame),None,0,0,time.monotonic_ns()+5_000_000_000,1_000_000,65_536,0,trace,c.byref(handle)) == 0; invocation=handle.value
        effect,length=U32(),U32(); assert raw_invoke(invocation,c.byref(effect),c.byref(length)) == 0
        result=(U8*length.value)(); copied=U32(); assert read(invocation,result,length.value,c.byref(copied)) == 0
        return bytes(result[:copied.value])
    finally:
        if invocation is not None: assert destroy(invocation) == 0
        if module.value: assert raw_close(module.value) == 0

def python_consumer(generated: Path):
    spec=importlib.util.spec_from_file_location('generated_host',generated); assert spec and spec.loader
    module_code=importlib.util.module_from_spec(spec); spec.loader.exec_module(module_code)
    sdk=HostSdk(RUNTIME); module=sdk.module_open(ARTIFACT,bytes.fromhex(RECEIPT['artifact_sha256']),bytes.fromhex(RECEIPT['descriptor_sha256']))
    try:
        host=module_code.GeneratedHost(sdk,module); request=host.encode_request({'left':7,'right':9}); result=host.decode_result(invoke(request))
        assert result == {'left':7,'right':9}; return request
    finally: sdk.module_close(module)

def node_consumer(generated: Path):
    request_path=OUT/'node.request.omi1'; result_path=OUT/'node.result.omi1'; runner=OUT/'node_consumer.mjs'
    runner.write_text(f'''import fs from 'node:fs';
import path from 'node:path';
import {{ createRequire }} from 'node:module';
import {{ GeneratedHost }} from {json.dumps(generated.as_uri())};
const root={json.dumps(str(ROOT))}; const require=createRequire(import.meta.url);
const sdk=require(path.join(root,'dist/node/omni_host_sdk.node')); const artifact=path.join(root,'artifacts/echo_pair.so');
const receipt=JSON.parse(fs.readFileSync(`${{artifact}}.omireceipt.json`,'utf8')); const module=sdk.moduleOpen(artifact,Buffer.from(receipt.artifact_sha256,'hex'),Buffer.from(receipt.descriptor_sha256,'hex'));
try {{ const host=new GeneratedHost(sdk,module); const request=host.encodeRequest({{left:7,right:9}}); fs.writeFileSync({json.dumps(str(request_path))},request); if(fs.existsSync({json.dumps(str(result_path))})) {{ const result=host.decodeResult(fs.readFileSync({json.dumps(str(result_path))})); if(JSON.stringify(result)!==JSON.stringify({{left:7,right:9}})) throw new Error('generated Node semantic result mismatch'); }} }} finally {{ sdk.moduleClose(module); }}
''',encoding='utf-8')
    run(['node',str(runner)]); request=request_path.read_bytes(); result_path.write_bytes(invoke(request)); run(['node',str(runner)])
    return request

def node_u64_consumer(generated: Path):
    request_path=OUT/'node.u64.request.omi1'; result_path=OUT/'node.u64.result.omi1'; runner=OUT/'node_u64_consumer.mjs'
    runner.write_text(f'''import fs from 'node:fs';
import path from 'node:path';
import {{ createRequire }} from 'node:module';
import {{ GeneratedHost }} from {json.dumps(generated.as_uri())};
const root={json.dumps(str(ROOT))}; const require=createRequire(import.meta.url);
const sdk=require(path.join(root,'dist/node/omni_host_sdk.node')); const artifact=path.join(root,'artifacts/echo_u64.so');
const receipt=JSON.parse(fs.readFileSync(`${{artifact}}.omireceipt.json`,'utf8')); const module=sdk.moduleOpen(artifact,Buffer.from(receipt.artifact_sha256,'hex'),Buffer.from(receipt.descriptor_sha256,'hex'));
try {{ const host=new GeneratedHost(sdk,module); const request=host.encodeRequest(18446744073709551615n); fs.writeFileSync({json.dumps(str(request_path))},request); if(fs.existsSync({json.dumps(str(result_path))})) {{ const result=host.decodeResult(fs.readFileSync({json.dumps(str(result_path))})); if(typeof result !== 'bigint' || result !== 18446744073709551615n) throw new Error('generated Node u64 bigint result mismatch'); }} }} finally {{ sdk.moduleClose(module); }}
''',encoding='utf-8')
    run(['node',str(runner)]); request=request_path.read_bytes(); result_path.write_bytes(invoke(request,U64_ARTIFACT,U64_RECEIPT)); run(['node',str(runner)])
    return request

def python_choice_consumer(generated: Path):
    spec=importlib.util.spec_from_file_location('generated_choice_host',generated); assert spec and spec.loader
    module_code=importlib.util.module_from_spec(spec); spec.loader.exec_module(module_code)
    assert module_code.SCHEMA['nodes'][str(module_code.SCHEMA['result'])]['children'][0] is None
    sdk=HostSdk(RUNTIME); module=sdk.module_open(CHOICE_ARTIFACT,bytes.fromhex(CHOICE_RECEIPT['artifact_sha256']),bytes.fromhex(CHOICE_RECEIPT['descriptor_sha256']))
    try:
        host=module_code.GeneratedHost(sdk,module); frames=[]
        for request,expected in CHOICE_CASES:
            frame=host.encode_request(request); result=invoke(frame,CHOICE_ARTIFACT,CHOICE_RECEIPT); assert host.decode_result(result) == expected; frames.append((frame,result))
        return frames
    finally: sdk.module_close(module)

def node_choice_consumer(generated: Path, frames):
    runner=OUT/'node_choice_consumer.mjs'
    for index,(request,result) in enumerate(frames):
        (OUT/f'choice.{index}.request.omi1').write_bytes(request); (OUT/f'choice.{index}.result.omi1').write_bytes(result)
    runner.write_text(f'''import fs from 'node:fs';
import path from 'node:path';
import {{ createRequire }} from 'node:module';
import {{ GeneratedHost }} from {json.dumps(generated.as_uri())};
const root={json.dumps(str(ROOT))}; const out={json.dumps(str(OUT))}; const require=createRequire(import.meta.url);
const sdk=require(path.join(root,'dist/node/omni_host_sdk.node')); const artifact=path.join(root,'artifacts/echo_choice.so');
const receipt=JSON.parse(fs.readFileSync(`${{artifact}}.omireceipt.json`,'utf8')); const module=sdk.moduleOpen(artifact,Buffer.from(receipt.artifact_sha256,'hex'),Buffer.from(receipt.descriptor_sha256,'hex'));
const cases={json.dumps([[request,expected] for request,expected in CHOICE_CASES])};
try {{ const host=new GeneratedHost(sdk,module); cases.forEach(([request,expected],index) => {{
  if(!Buffer.from(host.encodeRequest(request)).equals(fs.readFileSync(`${{out}}/choice.${{index}}.request.omi1`))) throw new Error('generated Node enum request differs from generated Python request');
  if(JSON.stringify(host.decodeResult(fs.readFileSync(`${{out}}/choice.${{index}}.result.omi1`)))!==JSON.stringify(expected)) throw new Error('generated Node enum result mismatch'); }}); }} finally {{ sdk.moduleClose(module); }}
''',encoding='utf-8')
    run(['node',str(runner)])

def python_bool_matrix_consumer(generated: Path):
    spec=importlib.util.spec_from_file_location('generated_bool_matrix_host',generated); assert spec and spec.loader
    module_code=importlib.util.module_from_spec(spec); spec.loader.exec_module(module_code)
    sdk=HostSdk(RUNTIME); module=sdk.module_open(BOOL_MATRIX_ARTIFACT,bytes.fromhex(BOOL_MATRIX_RECEIPT['artifact_sha256']),bytes.fromhex(BOOL_MATRIX_RECEIPT['descriptor_sha256']))
    try:
        host=module_code.GeneratedHost(sdk,module); request=host.encode_request(BOOL_MATRIX_REQUEST); result=host.decode_result(invoke(request,BOOL_MATRIX_ARTIFACT,BOOL_MATRIX_RECEIPT))
        # Exact-type checks: `False == 0` and `True == 1` in Python, so a bare
        # equality assertion would pass even with the pre-patch int-returning bug.
        assert type(result['bool_false']) is bool and result['bool_false'] is False,result
        assert type(result['bool_true']) is bool and result['bool_true'] is True,result
        assert type(result['count_u32']) is int and result['count_u32']==4242,result
        assert type(result['count_u64']) is int and result['count_u64']==18446744073709551615,result
        return request
    finally: sdk.module_close(module)

def node_bool_matrix_consumer(generated: Path):
    request_path=OUT/'node.bool_matrix.request.omi1'; result_path=OUT/'node.bool_matrix.result.omi1'; runner=OUT/'node_bool_matrix_consumer.mjs'
    runner.write_text(f'''import fs from 'node:fs';
import path from 'node:path';
import {{ createRequire }} from 'node:module';
import {{ GeneratedHost }} from {json.dumps(generated.as_uri())};
const root={json.dumps(str(ROOT))}; const require=createRequire(import.meta.url);
const sdk=require(path.join(root,'dist/node/omni_host_sdk.node')); const artifact=path.join(root,'artifacts/echo_bool_matrix.so');
const receipt=JSON.parse(fs.readFileSync(`${{artifact}}.omireceipt.json`,'utf8')); const module=sdk.moduleOpen(artifact,Buffer.from(receipt.artifact_sha256,'hex'),Buffer.from(receipt.descriptor_sha256,'hex'));
const request={{bool_false:false,bool_true:true,count_u32:4242,count_u64:18446744073709551615n}};
try {{ const host=new GeneratedHost(sdk,module); const frame=host.encodeRequest(request); fs.writeFileSync({json.dumps(str(request_path))},frame);
  if(fs.existsSync({json.dumps(str(result_path))})) {{
    const result=host.decodeResult(fs.readFileSync({json.dumps(str(result_path))}));
    // `false === 0` and `true === 1` are both false in JS, so a strict check
    // here is exact-type by construction; typeof is asserted explicitly too.
    if(typeof result.bool_false!=='boolean'||result.bool_false!==false) throw new Error('generated Node Bool false projection is not a real boolean: '+JSON.stringify(result));
    if(typeof result.bool_true!=='boolean'||result.bool_true!==true) throw new Error('generated Node Bool true projection is not a real boolean: '+JSON.stringify(result));
    if(typeof result.count_u32!=='number'||result.count_u32!==4242) throw new Error('generated Node U32 projection mismatch: '+JSON.stringify(result));
    if(typeof result.count_u64!=='bigint'||result.count_u64!==18446744073709551615n) throw new Error('generated Node U64 projection mismatch: '+String(result.count_u64));
  }}
}} finally {{ sdk.moduleClose(module); }}
''',encoding='utf-8')
    run(['node',str(runner)]); request=request_path.read_bytes(); result_path.write_bytes(invoke(request,BOOL_MATRIX_ARTIFACT,BOOL_MATRIX_RECEIPT)); run(['node',str(runner)])
    return request

def main():
    py1,py2=generate('python','.py'),generate('python','.again.py')
    ts1,ts2=generate('typescript','.mjs'),generate('typescript','.again.mjs')
    assert py1.read_bytes()==py2.read_bytes() and ts1.read_bytes()==ts2.read_bytes()
    u64_typescript=generate('typescript','.u64.mjs',U64_ARTIFACT,U64_RECEIPT)
    assert '@typedef {bigint}' in u64_typescript.read_text(encoding='utf-8')
    py_request=python_consumer(py1); node_request=node_consumer(ts1); node_u64_request=node_u64_consumer(u64_typescript)
    choice_frames=python_choice_consumer(generate('python','.choice.py',CHOICE_ARTIFACT,CHOICE_RECEIPT))
    choice_typescript=generate('typescript','.choice.mjs',CHOICE_ARTIFACT,CHOICE_RECEIPT); assert '{ tag: 0; value: null }' in choice_typescript.read_text(encoding='utf-8')
    node_choice_consumer(choice_typescript,choice_frames)
    bool_py1,bool_py2=generate('python','.bool_matrix.py',BOOL_MATRIX_ARTIFACT,BOOL_MATRIX_RECEIPT),generate('python','.bool_matrix.again.py',BOOL_MATRIX_ARTIFACT,BOOL_MATRIX_RECEIPT)
    bool_ts1,bool_ts2=generate('typescript','.bool_matrix.mjs',BOOL_MATRIX_ARTIFACT,BOOL_MATRIX_RECEIPT),generate('typescript','.bool_matrix.again.mjs',BOOL_MATRIX_ARTIFACT,BOOL_MATRIX_RECEIPT)
    assert bool_py1.read_bytes()==bool_py2.read_bytes() and bool_ts1.read_bytes()==bool_ts2.read_bytes()
    bool_python_request=python_bool_matrix_consumer(bool_py1); bool_node_request=node_bool_matrix_consumer(bool_ts1)
    assert bool_python_request==bool_node_request
    report={'schema':'omni.host-sdk-codegen-probe/1','status':'PASS','authenticated_schema_only':True,
            'manual_omi1_codec':False,'manual_typeid_hashing':False,'typescript_codegen':'PASS','python_codegen':'PASS',
            'deterministic':True,'generated_python_consumer':'PASS','generated_node_consumer':'PASS',
            'python_request_sha256':hashlib.sha256(py_request).hexdigest(),'node_request_sha256':hashlib.sha256(node_request).hexdigest(),
            'node_u64_request_sha256':hashlib.sha256(node_u64_request).hexdigest(),'typescript_bigint':'PASS',
            'payloadless_enum_variant':'PASS','enum_request_sha256':[hashlib.sha256(request).hexdigest() for request,_ in choice_frames],
            'bool_projection_typescript':'PASS','bool_projection_python':'PASS',
            'bool_matrix_request_sha256':hashlib.sha256(bool_python_request).hexdigest(),
            'real_runtime_exercised':True}
    (ROOT/'sdk_codegen_report.json').write_text(json.dumps(report,indent=2)+'\n'); print(json.dumps(report,sort_keys=True))

if __name__=='__main__': main()
