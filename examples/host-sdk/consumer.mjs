// SPDX-FileCopyrightText: 2026 Federico T. Begna
// SPDX-License-Identifier: MIT OR Apache-2.0
// The runtime response is prepared by the real invocation fixture, not invented.
import fs from 'node:fs';
import path from 'node:path';
import { createRequire } from 'node:module';

const root = path.resolve(process.argv[2]);
const sdk = createRequire(import.meta.url)(path.join(root, 'dist/node/omni_host_sdk.node'));
const artifact = path.join(root, 'artifacts/echo_u8.so');
const receipt = JSON.parse(fs.readFileSync(`${artifact}.omireceipt.json`, 'utf8'));
const module = sdk.moduleOpen(artifact, Buffer.from(receipt.artifact_sha256, 'hex'), Buffer.from(receipt.descriptor_sha256, 'hex'));
let argument;
let result;
try {
  argument = sdk.valueCreate(module, sdk.requestNode(module, 0));
  sdk.scalarSet(argument, 255n);
  const request = sdk.requestEncode(module, [argument]);
  if (request.length === 0) throw new Error('empty request');
  result = sdk.resultDecode(module, fs.readFileSync(path.join(root, 'node_echo_u8_result.omi1')));
  if (sdk.scalarGet(result) !== 255n) throw new Error('unexpected value');
  console.log('Node: encoded 255; decoded runtime response = 255');
} finally {
  if (result !== undefined) sdk.valueDestroy(result);
  if (argument !== undefined) sdk.valueDestroy(argument);
  sdk.moduleClose(module);
}
