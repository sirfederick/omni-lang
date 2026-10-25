#!/usr/bin/env python3
"""Generate thin Python or TypeScript Host SDK projections from an OMIS1 module.

The generator deliberately obtains all structure through the public Host SDK
ABI after module_open has authenticated the artifact, descriptor and schema.
It never parses OMI1/OMIS1 bytes, hashes TypeIDs, or reaches private Core
layouts.  Generated source carries only ABI-observed schema metadata and calls
the official binding supplied by the SDK at runtime.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# A source checkout keeps the binding under bindings/python, while the
# portable SDK installs it under python.  The generator is itself part of the
# SDK, so both layouts are first-party layouts rather than a host dependency.
for binding_dir in (ROOT / 'bindings/python', ROOT / 'python'):
    if binding_dir.is_dir():
        sys.path.insert(0, str(binding_dir))
from omni_host_sdk import HostSdk, HostSdkError  # noqa: E402

KIND = {
    1: 'Bool', 2: 'U8', 3: 'U16', 4: 'U32', 5: 'U64', 6: 'I8', 7: 'I16',
    8: 'I32', 9: 'I64', 10: 'Char', 11: 'Text', 12: 'Bytes', 13: 'Tuple',
    14: 'Array', 15: 'Record', 16: 'Enum', 17: 'Option', 18: 'Result',
}
TS_SCALAR = {1:'boolean',2:'number',3:'number',4:'number',5:'bigint',6:'number',
             7:'number',8:'number',9:'bigint',10:'number',11:'string',12:'Uint8Array'}
PY_SCALAR = {1:'bool',2:'int',3:'int',4:'int',5:'int',6:'int',7:'int',8:'int',
             9:'int',10:'int',11:'str',12:'bytes'}


def read_label(sdk: HostSdk, module: int, node: int, index: int) -> str | None:
    try:
        return sdk.node_label(module, node, index)
    except HostSdkError:
        return None


def read_child(sdk: HostSdk, module: int, node: int, kind: int, index: int) -> int | None:
    # A payload-less Enum variant is a labelled arm without a schema child.  The
    # frozen ABI reports that absence as a rejected child lookup, so it is the
    # only lookup whose rejection is structure rather than an error.
    try:
        return sdk.node_child(module, node, index)
    except HostSdkError:
        if kind == 16:
            return None
        raise


def snapshot(sdk: HostSdk, module: int, roots: list[int], result: int) -> dict:
    seen: dict[int, dict] = {}

    def visit(node: int) -> None:
        if node in seen:
            return
        kind = sdk.node_kind(module, node)
        count = sdk.node_child_count(module, node)
        children = [read_child(sdk, module, node, kind, index) for index in range(count)]
        seen[node] = {
            'kind': kind,
            'kind_name': KIND[kind],
            'typeid': sdk.node_typeid(module, node).hex(),
            'labels': [read_label(sdk, module, node, index) for index in range(count)],
            'children': children,
        }
        for child in children:
            if child is not None:
                visit(child)

    for root in [*roots, result]:
        visit(root)
    return {'schema': 'omni.sdk-generated-schema/1', 'roots': roots, 'result': result,
            'nodes': {str(node): seen[node] for node in sorted(seen)}}


def identifier(value: str, fallback: str) -> str:
    candidate = ''.join(ch if ch.isalnum() or ch == '_' else '_' for ch in value)
    if not candidate or candidate[0].isdigit():
        candidate = fallback
    return candidate


def ts_type(nodes: dict[str, dict], node: int, seen: set[int] | None = None) -> str:
    seen = set() if seen is None else seen
    if node in seen:
        return f'Node{node}'
    seen.add(node)
    meta = nodes[str(node)]; kind = meta['kind']; children = meta['children']
    if kind <= 12:
        return TS_SCALAR[kind]
    if kind == 13:
        return '[' + ', '.join(ts_type(nodes, child, seen.copy()) for child in children) + ']'
    if kind == 14:
        return f'Array<{ts_type(nodes, children[0], seen.copy())}>'
    if kind == 15:
        fields = []
        for index, child in enumerate(children):
            fields.append(f'{identifier(meta["labels"][index] or "", "f" + str(index))}: {ts_type(nodes, child, seen.copy())}')
        return '{ ' + '; '.join(fields) + ' }'
    if kind == 16:
        variants = []
        for index, child in enumerate(children):
            variants.append(f'{{ tag: {index}; value: {"null" if child is None else ts_type(nodes, child, seen.copy())} }}')
        return ' | '.join(variants) or '{ tag: number; value?: never }'
    if kind == 17:
        return f'null | {{ tag: 1; value: {ts_type(nodes, children[0], seen.copy())} }}'
    if kind == 18:
        return f'{{ tag: 0; ok: {ts_type(nodes, children[0], seen.copy())} }} | {{ tag: 1; err: {ts_type(nodes, children[1], seen.copy())} }}'
    raise ValueError(f'unsupported kind {kind}')


def py_type(nodes: dict[str, dict], node: int, seen: set[int] | None = None) -> str:
    seen = set() if seen is None else seen
    if node in seen:
        return 'object'
    seen.add(node)
    meta = nodes[str(node)]; kind = meta['kind']; children = meta['children']
    if kind <= 12:
        return PY_SCALAR[kind]
    if kind == 13:
        return 'tuple[' + ', '.join(py_type(nodes, child, seen.copy()) for child in children) + ']'
    if kind == 14:
        return f'list[{py_type(nodes, children[0], seen.copy())}]'
    if kind == 15:
        return 'dict[str, object]'
    if kind == 16:
        return 'dict[str, object]'
    if kind == 17:
        return f'{py_type(nodes, children[0], seen.copy())} | None'
    if kind == 18:
        return 'dict[str, object]'
    raise ValueError(f'unsupported kind {kind}')


def python_literal(meta: dict) -> str:
    # The indented JSON form is already a Python literal except for an absent
    # child, which always occupies a list line of its own.
    return re.sub(r'(?m)^(\s*)null(,?)$', r'\g<1>None\g<2>', json.dumps(meta, sort_keys=True, indent=2))


def python_source(meta: dict) -> str:
    nodes = meta['nodes']; roots = meta['roots']
    aliases = '\n'.join(f'Node{node} = {py_type(nodes, int(node))}' for node in sorted(nodes, key=int))
    request_params = ', '.join(f'value{index}: Node{node}' for index, node in enumerate(roots))
    request_values = ', '.join(f'value{index}' for index in range(len(roots)))
    return f'''# Generated by omni_sdk_codegen.py; do not hand-edit.
# This file contains no OMI1 codec and no TypeID hashing.
from __future__ import annotations
from typing import Any
from omni_host_sdk import HostSdk

SCHEMA = {python_literal(meta)}
{aliases}

class GeneratedHost:
    def __init__(self, sdk: HostSdk, module: int):
        self.sdk, self.module = sdk, module
        for node, expected in SCHEMA['nodes'].items():
            if sdk.node_typeid(module, int(node)).hex() != expected['typeid']:
                raise ValueError('authenticated module schema TypeID mismatch')

    @staticmethod
    def _index(kind: int, arm: int | None, index: int) -> int:
        return 0 if kind == 14 else (arm if kind == 16 else index)

    def _build(self, node: int, value: Any, owned: list[int]) -> int:
        meta = SCHEMA['nodes'][str(node)]; kind = meta['kind']; handle = self.sdk.value_create(self.module, node); owned.append(handle)
        if kind <= 10: self.sdk.scalar_set(handle, int(value))
        elif kind == 11: self.sdk.data_set(handle, value.encode('utf-8'))
        elif kind == 12: self.sdk.data_set(handle, bytes(value))
        arm = None
        if kind == 16:
            arm = int(value['tag']); self.sdk.discriminant_set(handle, arm); payloads = [value.get('value')]
        elif kind == 17:
            arm = 0 if value is None else 1; self.sdk.discriminant_set(handle, arm); payloads = [] if value is None else [value]
        elif kind == 18:
            arm = int(value['tag']); self.sdk.discriminant_set(handle, arm); payloads = [value['ok'] if arm == 0 else value['err']]
        elif kind == 15:
            payloads = [value[label or f'f{{index}}'] for index, label in enumerate(meta['labels'])]
        elif kind in (13, 14): payloads = list(value)
        else: payloads = []
        for index in range(self.sdk.child_count(handle)):
            child_node = meta['children'][self._index(kind, arm, index)]
            child = self._build(child_node, payloads[index], owned); self.sdk.child_set(handle, index, child)
        return handle

    def encode_request(self{', ' + request_params if request_params else ''}) -> bytes:
        owned: list[int] = []
        try:
            values = [{request_values}]
            handles = [self._build(node, value, owned) for node, value in zip(SCHEMA['roots'], values)]
            return self.sdk.request_encode(self.module, handles)
        finally:
            for handle in reversed(owned): self.sdk.value_destroy(handle)

    def _project(self, node: int, handle: int) -> Any:
        meta = SCHEMA['nodes'][str(node)]; kind = meta['kind']
        if self.sdk.value_kind(handle) != kind or self.sdk.value_typeid(handle).hex() != meta['typeid']: raise ValueError('decoded value/schema mismatch')
        # scalar_get always returns the raw 64-bit bits; Bool is the one scalar
        # kind whose declared Python type (bool) differs from that raw int.
        if kind == 1: return bool(self.sdk.scalar_get(handle))
        if kind <= 10: return self.sdk.scalar_get(handle)
        if kind == 11: return self.sdk.data_get(handle).decode('utf-8')
        if kind == 12: return self.sdk.data_get(handle)
        arm = self.sdk.discriminant_get(handle) if kind in (16,17,18) else None
        values = []
        for index in range(self.sdk.child_count(handle)):
            child = self.sdk.child_get(handle, index)
            try: values.append(self._project(meta['children'][self._index(kind, arm, index)], child))
            finally: self.sdk.value_destroy(child)
        if kind == 13: return tuple(values)
        if kind == 14: return values
        if kind == 15: return {{(label or f'f{{index}}'): values[index] for index, label in enumerate(meta['labels'])}}
        if kind == 16: return {{'tag': arm, 'value': values[0] if values else None}}
        if kind == 17: return None if arm == 0 else values[0]
        if kind == 18: return {{'tag': arm, 'ok' if arm == 0 else 'err': values[0]}}
        raise ValueError('unsupported generated kind')

    def decode_result(self, frame: bytes) -> Node{meta['result']}:
        handle = self.sdk.result_decode(self.module, frame)
        try: return self._project(SCHEMA['result'], handle)
        finally: self.sdk.value_destroy(handle)
'''


def typescript_source(meta: dict) -> str:
    nodes = meta['nodes']
    aliases = '\n'.join(f'/** @typedef {{{ts_type(nodes, int(node))}}} Node{node} */'
                        for node in sorted(nodes, key=int))
    roots = meta['roots']
    request_params_doc = ' '.join(f'@param {{Node{node}}} value{index}' for index, node in enumerate(roots))
    request_params = ', '.join(f'value{index}' for index in range(len(roots)))
    request_values = ', '.join(f'value{index}' for index in range(len(roots)))
    return f'''// Generated by omni_sdk_codegen.py; do not hand-edit.
// @ts-check
// TypeScript checks these JSDoc declarations; u64/i64 remain bigint.  The
// executable ESM remains directly consumable by Node without a second codec.
import {{ Buffer }} from 'node:buffer';
export const SCHEMA = {json.dumps(meta, sort_keys=True, indent=2)};
{aliases}

export class GeneratedHost {{
  /** @param {{any}} sdk @param {{bigint}} module */
  constructor(sdk, module) {{
    this.sdk = sdk; this.module = module;
    for (const [node, expected] of Object.entries(SCHEMA.nodes)) {{
      if (Buffer.from(sdk.nodeTypeId(module, Number(node))).toString('hex') !== expected.typeid) throw new Error('authenticated module schema TypeID mismatch');
    }}
  }}
  /** @param {{number}} kind @param {{number|null}} arm @param {{number}} index */
  index(kind, arm, index) {{ return kind === 14 ? 0 : (kind === 16 ? arm : index); }}
  /** @param {{number}} node @param {{any}} value @param {{bigint[]}} owned */
  build(node, value, owned) {{
    const meta = SCHEMA.nodes[String(node)]; const kind = meta.kind; const handle = this.sdk.valueCreate(this.module, node); owned.push(handle);
    if (kind <= 10) this.sdk.scalarSet(handle, BigInt(value)); else if (kind === 11) this.sdk.dataSet(handle, Buffer.from(value, 'utf8')); else if (kind === 12) this.sdk.dataSet(handle, Buffer.from(value));
    let arm = null; let payloads = [];
    if (kind === 16) {{ arm = Number(value.tag); this.sdk.discriminantSet(handle, arm); payloads = [value.value]; }}
    else if (kind === 17) {{ arm = value === null ? 0 : 1; this.sdk.discriminantSet(handle, arm); payloads = value === null ? [] : [value]; }}
    else if (kind === 18) {{ arm = Number(value.tag); this.sdk.discriminantSet(handle, arm); payloads = [arm === 0 ? value.ok : value.err]; }}
    else if (kind === 15) payloads = meta.labels.map((label, i) => value[label ?? `f${{i}}`]);
    else if (kind === 13 || kind === 14) payloads = Array.from(value);
    for (let i = 0; i < this.sdk.childCount(handle); ++i) {{ const child = this.build(meta.children[this.index(kind, arm, i)], payloads[i], owned); this.sdk.childSet(handle, i, child); }}
    return handle;
  }}
  /** {request_params_doc} */
  encodeRequest({request_params}) {{
    const values = [{request_values}], owned = [];
    try {{ return this.sdk.requestEncode(this.module, SCHEMA.roots.map((node, i) => this.build(node, values[i], owned))); }}
    finally {{ for (const value of owned.reverse()) this.sdk.valueDestroy(value); }}
  }}
  /** @param {{number}} node @param {{bigint}} handle */
  project(node, handle) {{
    const meta = SCHEMA.nodes[String(node)], kind = meta.kind; if (this.sdk.valueKind(handle) !== kind || Buffer.from(this.sdk.valueTypeId(handle)).toString('hex') !== meta.typeid) throw new Error('decoded value/schema mismatch');
    // scalarGet always returns the raw 64-bit bits as a BigInt; Bool is the one
    // scalar kind whose declared TypeScript type (boolean) differs from that.
    if (kind === 1) return this.sdk.scalarGet(handle) !== 0n;
    if (kind <= 10) {{ const scalar = this.sdk.scalarGet(handle); return (kind === 5 || kind === 10) ? scalar : Number(scalar); }} if (kind === 11) return Buffer.from(this.sdk.dataGet(handle)).toString('utf8'); if (kind === 12) return this.sdk.dataGet(handle);
    const arm = (kind === 16 || kind === 17 || kind === 18) ? this.sdk.discriminantGet(handle) : null; const values = [];
    for (let i = 0; i < this.sdk.childCount(handle); ++i) {{ const child = this.sdk.childGet(handle, i); try {{ values.push(this.project(meta.children[this.index(kind, arm, i)], child)); }} finally {{ this.sdk.valueDestroy(child); }} }}
    if (kind === 13) return values; if (kind === 14) return values; if (kind === 15) return Object.fromEntries(meta.labels.map((label, i) => [label ?? `f${{i}}`, values[i]]));
    if (kind === 16) return {{tag: arm, value: values.length ? values[0] : null}}; if (kind === 17) return arm === 0 ? null : values[0]; if (kind === 18) return arm === 0 ? {{tag: arm, ok: values[0]}} : {{tag: arm, err: values[0]}}; throw new Error('unsupported generated kind');
  }}
  /** @param {{Buffer}} frame @returns {{Node{meta['result']}}} */
  decodeResult(frame) {{ const handle = this.sdk.resultDecode(this.module, frame); try {{ return this.project(SCHEMA.result, handle); }} finally {{ this.sdk.valueDestroy(handle); }} }}
}}
'''


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--language', choices=('python', 'typescript'), required=True)
    parser.add_argument('--runtime', type=Path, required=True)
    parser.add_argument('--artifact', type=Path, required=True)
    parser.add_argument('--artifact-sha256', required=True)
    parser.add_argument('--descriptor-sha256', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    artifact_sha, descriptor_sha = bytes.fromhex(args.artifact_sha256), bytes.fromhex(args.descriptor_sha256)
    if len(artifact_sha) != 32 or len(descriptor_sha) != 32:
        parser.error('hashes must be SHA-256 hex')
    sdk = HostSdk(args.runtime); module = sdk.module_open(args.artifact, artifact_sha, descriptor_sha)
    try:
        roots = [sdk.request_node(module, index) for index in range(sdk.request_count(module))]
        meta = snapshot(sdk, module, roots, sdk.result_node(module))
    finally:
        sdk.module_close(module)
    source = python_source(meta) if args.language == 'python' else typescript_source(meta)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(source, encoding='utf-8', newline='\n')
    print(json.dumps({'schema':'omni.sdk-codegen/1','status':'PASS','language':args.language,
                      'output':str(args.output),'nodes':len(meta['nodes']),'roots':len(meta['roots'])}, sort_keys=True))


if __name__ == '__main__':
    main()
