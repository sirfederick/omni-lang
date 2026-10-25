// Decode real runtime responses only through the official Node Host SDK addon.
import fs from 'node:fs';
import path from 'node:path';
import { createRequire } from 'node:module';
const root=process.env.OMNI_H02_EVIDENCE_ROOT; if (!root) throw new Error('OMNI_H02_EVIDENCE_ROOT is required');
const require=createRequire(import.meta.url); const sdk=require(path.join(root,'dist/node/omni_host_sdk.node'));
const source=JSON.parse(fs.readFileSync(path.join(root,'node_structural_encode.json'),'utf8')); const frames=path.join(root,'node_structural_frames');
const kindNames={1:'Bool',2:'U8',3:'U16',4:'U32',5:'U64',6:'I8',7:'I16',8:'I32',9:'I64',10:'Char',11:'Text',12:'Bytes',13:'Tuple',14:'Array',15:'Record',16:'Enum',17:'Option',18:'Result'};
function schemaIndex(kind,arm,index){ return kind===14?0:(kind===16?arm:index); }
function normalize(module,node,value) {
  const kind=sdk.nodeKind(module,node), typeid=Buffer.from(sdk.nodeTypeId(module,node));
  if(sdk.valueKind(value)!==kind || !Buffer.from(sdk.valueTypeId(value)).equals(typeid)) throw new Error('ABI kind/TypeID mismatch');
  const schemaChildCount=sdk.nodeChildCount(module,node), labels=[];
  for(let i=0;i<schemaChildCount;++i){try{labels.push(Buffer.from(sdk.nodeLabel(module,node,i)).toString('utf8'));}catch{labels.push(null);}}
  const out={kind:kindNames[kind],kind_code:kind,typeid:typeid.toString('hex'),labels,schema_child_count:schemaChildCount};
  if(kind<=10)out.scalar_bits=Number(sdk.scalarGet(value)); else if(kind===11)out.text=Buffer.from(sdk.dataGet(value)).toString('utf8'); else if(kind===12)out.bytes_hex=Buffer.from(sdk.dataGet(value)).toString('hex');
  let arm=null;if(kind===16||kind===17||kind===18){arm=sdk.discriminantGet(value);out.discriminant=arm;} const count=sdk.childCount(value);out.value_child_count=count;out.children=[];
  for(let i=0;i<count;++i){const child=sdk.childGet(value,i);try{out.children.push(normalize(module,sdk.nodeChild(module,node,schemaIndex(kind,arm,i)),child));}finally{sdk.valueDestroy(child);}}
  return out;
}
const fixtures=[];
for(const expected of source.fixtures){const {fixture:name,alternate}=expected;const key=`${name}-${alternate?'alternate':'primary'}`;const artifact=path.join(root,'artifacts',`${name}.so`);const receipt=JSON.parse(fs.readFileSync(`${artifact}.omireceipt.json`,'utf8'));const module=sdk.moduleOpen(artifact,Buffer.from(receipt.artifact_sha256,'hex'),Buffer.from(receipt.descriptor_sha256,'hex'));let decoded;
  try{const node=sdk.requestNode(module,0);decoded=sdk.resultDecode(module,fs.readFileSync(path.join(frames,`${key}.result.omi1`)));const resultSemantic=normalize(module,node,decoded);if(JSON.stringify(resultSemantic)!==JSON.stringify(expected.request_semantic))throw new Error(`semantic mismatch ${key}`);fixtures.push({fixture:name,alternate,request_bytes:expected.request_bytes,result_bytes:fs.statSync(path.join(frames,`${key}.result.omi1`)).size,typeid:Buffer.from(sdk.nodeTypeId(module,node)).toString('hex'),request_semantic:expected.request_semantic,result_semantic:resultSemantic,semantic_equality:'PASS'});}finally{if(decoded!==undefined)sdk.valueDestroy(decoded);sdk.moduleClose(module);}}
const report={schema:'omni.host-sdk-node-structural-matrix/1',status:'PASS',node_native_addon:true,public_c_abi_only:true,manual_omi1_codec:false,real_runtime_exercised:true,fixtures};fs.writeFileSync(path.join(root,'node_structural_matrix.json'),`${JSON.stringify(report,null,2)}\n`);console.log(JSON.stringify({status:'PASS',fixtures:fixtures.length}));
