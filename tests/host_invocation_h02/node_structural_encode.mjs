// Structural construction and request encoding through the official Node addon.
// OMI1 frames remain opaque Buffers created by Core's C ABI implementation.
import fs from 'node:fs';
import path from 'node:path';
import { createRequire } from 'node:module';

const root = process.env.OMNI_H02_EVIDENCE_ROOT;
if (!root) throw new Error('OMNI_H02_EVIDENCE_ROOT is required');
const require = createRequire(import.meta.url);
const sdk = require(path.join(root, 'dist/node/omni_host_sdk.node'));
const names = ['echo_bool','echo_u8','echo_u16','echo_u32','echo_u64','echo_i8','echo_i16','echo_i32','echo_i64','echo_char','echo_text','echo_bytes','echo_tuple','echo_array','echo_pair','echo_choice','echo_option','echo_result','echo_nested'];
const kindNames = {1:'Bool',2:'U8',3:'U16',4:'U32',5:'U64',6:'I8',7:'I16',8:'I32',9:'I64',10:'Char',11:'Text',12:'Bytes',13:'Tuple',14:'Array',15:'Record',16:'Enum',17:'Option',18:'Result'};
const frames = path.join(root, 'node_structural_frames');
fs.mkdirSync(frames, { recursive: true });

function schemaIndex(kind, arm, index) { return kind === 14 ? 0 : (kind === 16 ? arm : index); }
function typeid(buffer) { return Buffer.from(buffer).toString('hex'); }
function build(module, node, owned, alternate) {
  const kind = sdk.nodeKind(module, node); const value = sdk.valueCreate(module, node); owned.push(value);
  if (kind <= 10) sdk.scalarSet(value, kind === 10 ? 0x1f642n : 1n);
  else if (kind === 11 || kind === 12) sdk.dataSet(value, kind === 11 ? Buffer.from('Ω') : Buffer.from([0, 255, 120]));
  let arm = 0;
  if (kind === 16 || kind === 17 || kind === 18) {
    const count = sdk.nodeChildCount(module, node);
    arm = alternate ? 0 : (kind === 16 && count > 1 ? 1 : (kind === 17 ? 1 : 0));
    sdk.discriminantSet(value, arm);
  }
  for (let index = 0; index < sdk.childCount(value); ++index) {
    const child = build(module, sdk.nodeChild(module, node, schemaIndex(kind, arm, index)), owned, alternate);
    sdk.childSet(value, index, child);
  }
  return value;
}
function normalize(module, node, value) {
  const kind = sdk.nodeKind(module, node); const nodeTypeId = sdk.nodeTypeId(module, node);
  if (sdk.valueKind(value) !== kind || !Buffer.from(sdk.valueTypeId(value)).equals(Buffer.from(nodeTypeId))) throw new Error('ABI kind/TypeID mismatch');
  const schemaChildCount = sdk.nodeChildCount(module, node); const labels = [];
  for (let index = 0; index < schemaChildCount; ++index) {
    try { labels.push(Buffer.from(sdk.nodeLabel(module, node, index)).toString('utf8')); } catch { labels.push(null); }
  }
  const result = { kind: kindNames[kind], kind_code: kind, typeid: typeid(nodeTypeId), labels, schema_child_count: schemaChildCount };
  if (kind <= 10) result.scalar_bits = Number(sdk.scalarGet(value));
  else if (kind === 11) result.text = Buffer.from(sdk.dataGet(value)).toString('utf8');
  else if (kind === 12) result.bytes_hex = Buffer.from(sdk.dataGet(value)).toString('hex');
  let arm = null;
  if (kind === 16 || kind === 17 || kind === 18) { arm = sdk.discriminantGet(value); result.discriminant = arm; }
  const count = sdk.childCount(value); result.value_child_count = count; result.children = [];
  for (let index = 0; index < count; ++index) {
    const child = sdk.childGet(value, index);
    try { result.children.push(normalize(module, sdk.nodeChild(module, node, schemaIndex(kind, arm, index)), child)); }
    finally { sdk.valueDestroy(child); }
  }
  return result;
}
function one(name, alternate = false) {
  const artifact = path.join(root, 'artifacts', `${name}.so`);
  const receipt = JSON.parse(fs.readFileSync(`${artifact}.omireceipt.json`, 'utf8'));
  const module = sdk.moduleOpen(artifact, Buffer.from(receipt.artifact_sha256, 'hex'), Buffer.from(receipt.descriptor_sha256, 'hex'));
  const owned = [];
  try {
    const node = sdk.requestNode(module, 0); const argument = build(module, node, owned, alternate);
    const semantic = normalize(module, node, argument); const request = sdk.requestEncode(module, [argument]);
    const key = `${name}-${alternate ? 'alternate' : 'primary'}`;
    fs.writeFileSync(path.join(frames, `${key}.request.omi1`), request);
    return { fixture: name, alternate, request_bytes: request.length, typeid: typeid(sdk.nodeTypeId(module, node)), request_semantic: semantic };
  } finally {
    for (const value of owned.reverse()) sdk.valueDestroy(value);
    sdk.moduleClose(module);
  }
}
const fixtures = names.map((name) => one(name)).concat(['echo_choice','echo_option','echo_result'].map((name) => one(name, true)));
const report = { schema: 'omni.host-sdk-node-structural-encode/1', status: 'PASS', node_native_addon: true, public_c_abi_only: true, manual_omi1_codec: false, fixtures };
fs.writeFileSync(path.join(root, 'node_structural_encode.json'), `${JSON.stringify(report, null, 2)}\n`);
console.log(JSON.stringify({ status: 'PASS', fixtures: fixtures.length }));
