import fs from 'node:fs';
import path from 'node:path';
import { createRequire } from 'node:module';

const root = process.env.OMNI_H02_EVIDENCE_ROOT;
if (!root) throw new Error('OMNI_H02_EVIDENCE_ROOT is required');
const require = createRequire(import.meta.url);
const sdk = require(path.join(root, 'dist/node/omni_host_sdk.node'));
const artifact = path.join(root, 'artifacts/echo_pair.so');
const receipt = JSON.parse(fs.readFileSync(`${artifact}.omireceipt.json`, 'utf8'));
const module = sdk.moduleOpen(artifact, Buffer.from(receipt.artifact_sha256, 'hex'), Buffer.from(receipt.descriptor_sha256, 'hex'));
const otherModule = sdk.moduleOpen(artifact, Buffer.from(receipt.artifact_sha256, 'hex'), Buffer.from(receipt.descriptor_sha256, 'hex'));
let parent; let first; let second; let projected; let replacement; let otherChild; let wrongChild;
const denied = (callback) => { try { callback(); return false; } catch { return true; } };
try {
  const rootNode = sdk.requestNode(module, 0);
  const firstNode = sdk.nodeChild(module, rootNode, 0);
  const secondNode = sdk.nodeChild(module, rootNode, 1);
  parent = sdk.valueCreate(module, rootNode);
  first = sdk.valueCreate(module, firstNode); second = sdk.valueCreate(module, secondNode);
  otherChild = sdk.valueCreate(otherModule, sdk.nodeChild(otherModule, sdk.requestNode(otherModule, 0), 0));
  wrongChild = sdk.valueCreate(module, rootNode);
  sdk.scalarSet(first, 7n); sdk.scalarSet(second, 9n);
  sdk.childSet(parent, 0, first); sdk.childSet(parent, 1, second);
  projected = sdk.childGet(parent, 0);
  const checks = { module_busy_with_live_values: denied(() => sdk.moduleClose(module)), cross_module_child_rejected: denied(() => sdk.childSet(parent, 0, otherChild)), wrong_schema_child_rejected: denied(() => sdk.childSet(parent, 0, wrongChild)) };
  sdk.valueDestroy(parent); parent = undefined;
  checks.child_survives_parent_destroy = sdk.scalarGet(projected) === 7n;
  const stale = projected; sdk.valueDestroy(projected); projected = undefined;
  // Exercise stale-handle rejection after a fresh allocation too; recycled
  // storage must not turn a destroyed handle into authority over a new value.
  replacement = sdk.valueCreate(module, firstNode);
  checks.stale_child_rejected = denied(() => sdk.scalarGet(stale));
  checks.double_destroy_rejected = denied(() => sdk.valueDestroy(stale));
  if (!Object.values(checks).every(Boolean)) throw new Error(JSON.stringify(checks));
  console.log(JSON.stringify({ schema: 'omni.host-sdk-node-ownership/1', status: 'PASS', ownership: 'INDEPENDENT_OWNED_HANDLE_COPY', checks }));
} finally {
  for (const value of [projected, replacement, parent, first, second, wrongChild]) if (value !== undefined) { try { sdk.valueDestroy(value); } catch {} }
  sdk.moduleClose(module);
  if (otherChild !== undefined) { try { sdk.valueDestroy(otherChild); } catch {} }
  sdk.moduleClose(otherModule);
}
