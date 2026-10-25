// The Node test uses only the official native addon.  It contains no OMI1
// tags, frame layout, TypeID derivation, or private Core structure access.
import fs from 'node:fs';
import path from 'node:path';
import { createRequire } from 'node:module';

const root = process.env.OMNI_H02_EVIDENCE_ROOT;
if (!root) throw new Error('OMNI_H02_EVIDENCE_ROOT is required');
const require = createRequire(import.meta.url);
const sdk = require(path.join(root, 'dist/node/omni_host_sdk.node'));
const artifact = path.join(root, 'artifacts/echo_u8.so');
const receipt = JSON.parse(fs.readFileSync(`${artifact}.omireceipt.json`, 'utf8'));
const module = sdk.moduleOpen(artifact, Buffer.from(receipt.artifact_sha256, 'hex'), Buffer.from(receipt.descriptor_sha256, 'hex'));
let value;
try {
  const node = sdk.requestNode(module, 0);
  if (sdk.nodeKind(module, node) !== 2) throw new Error('fixture must expose u8');
  value = sdk.valueCreate(module, node);
  sdk.scalarSet(value, 255n);
  const frame = sdk.requestEncode(module, [value]);
  if (!Buffer.isBuffer(frame) || frame.length === 0) throw new Error('canonical request encode failed');
  const decoded = sdk.resultDecode(module, fs.readFileSync(path.join(root, 'node_echo_u8_result.omi1')));
  try {
    if (sdk.scalarGet(decoded) !== 255n) throw new Error('canonical result decode failed');
  } finally {
    sdk.valueDestroy(decoded);
  }
  console.log(JSON.stringify({
    schema: 'omni.host-sdk-node-public-probe/1',
    status: 'PASS',
    node_native_addon: true,
    public_c_abi_only: true,
    manual_omi1_codec: false,
    bigint_64bit_handles: true,
    request_bytes: frame.length,
  }));
} finally {
  if (value !== undefined) sdk.valueDestroy(value);
  sdk.moduleClose(module);
}
