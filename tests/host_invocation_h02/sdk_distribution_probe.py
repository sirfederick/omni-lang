#!/usr/bin/env python3
"""Build twice and exercise an SDK extraction without a source checkout."""
from __future__ import annotations
import hashlib, json, os, pathlib, shutil, subprocess, sys

ROOT=pathlib.Path(os.environ['OMNI_H02_EVIDENCE_ROOT']); CORE=pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0,str(CORE/'tools')); from safe_tar import safe_extract
DIST=ROOT/'sdk-distribution'; DIST.mkdir(); compiler=ROOT/'dist/bin/omni'; runtime=ROOT/'dist/runtime/libomni_invocation_v1.so'; node=ROOT/'dist/node/omni_host_sdk.node'
def digest(path): return hashlib.sha256(path.read_bytes()).hexdigest()
def run(args, env=None):
    completed=subprocess.run(args,capture_output=True,text=True,env=env)
    if completed.returncode: raise RuntimeError(completed.stdout+completed.stderr)
    return completed.stdout
def main():
    one,two=DIST/'one.tar.gz',DIST/'two.tar.gz'
    package=[ 'python3',str(CORE/'tools/omni_sdk_package.py'),'--compiler',str(compiler),'--runtime',str(runtime),'--node',str(node)]
    run([*package,'--output',str(one)]); run([*package,'--output',str(two)]); assert one.read_bytes()==two.read_bytes()
    fresh=DIST/'fresh'; fresh.mkdir();
    safe_extract(one,fresh)  # validated members only, strict data filter (tools/safe_tar.py)
    sdk=next(fresh.iterdir()); env={**os.environ,'OMNI_HOME':str(sdk)}; installed=sdk/'bin/omni'
    doctor=json.loads(run([str(installed),'sdk','doctor'],env)); assert doctor['status']=='PASS'
    host=fresh/'portable-stdlib-consumer'; (host/'src').mkdir(parents=True)
    (host/'omni.package.json').write_text(json.dumps({'schema':'omni.package/1','name':'portable.std.consumer','version':'1.2.0','entry':'src/echo.omni','dependencies':{'omni.std':{'path':'../development-only-stdlib','version':'0.8.4-alpha.8'}}}),encoding='utf-8')
    (host/'src/echo.omni').write_text('module portable_std_consumer\npub func echo_pair(value u32) u32 { return value }\nfunc main() u32 { return 7u32 }\n',encoding='utf-8')
    resolution=json.loads(run([str(installed),'package','lock',str(host),'--offline'],env)); assert resolution['root']=='portable.std.consumer' and resolution['packages']==2
    lock=json.loads((host/'omni.lock.json').read_text(encoding='utf-8')); assert any(item['origin']=='sdk:omni.std@0.8.4-alpha.8' for item in lock['packages'])
    run([str(installed),'package','check',str(host),'--offline'],env)
    artifact=DIST/'fresh-host.so'; run([str(installed),'build',str(host),'--host-entry','src/echo.omni:echo_pair','--offline','-o',str(artifact)],env)
    receipt=json.loads(pathlib.Path(f'{artifact}.omireceipt.json').read_text())
    c_consumer=DIST/'fresh_c_consumer.c'; c_binary=DIST/'fresh_c_consumer'
    artifact_hash=','.join(f'0x{receipt["artifact_sha256"][index:index+2]}' for index in range(0,64,2))
    descriptor_hash=','.join(f'0x{receipt["descriptor_sha256"][index:index+2]}' for index in range(0,64,2))
    c_consumer.write_text(f'''#define _POSIX_C_SOURCE 200809L
#include <stdint.h>
#include <string.h>
#include <time.h>
#include <omni/omni_host_sdk_v1.h>
#include <omni_invocation_v1.h>
int main(void) {{
  static const uint8_t artifact_hash[32]={{{artifact_hash}}}, descriptor_hash[32]={{{descriptor_hash}}};
  const char *path="{artifact}"; omni_host_sdk_v1_module module=0; omni_host_sdk_v1_value value=0;
  uint32_t count=0,node=0,written=0; uint8_t frame[4096];
  if(omni_host_sdk_v1_module_open((const uint8_t*)path,(uint32_t)strlen(path),artifact_hash,descriptor_hash,&module)) return 1;
  if(omni_host_sdk_v1_module_request_count(module,&count)||count!=1||omni_host_sdk_v1_module_request_node(module,0,&node)) return 2;
  if(omni_host_sdk_v1_value_create(module,node,&value)||omni_host_sdk_v1_value_scalar_set(value,7)||omni_host_sdk_v1_request_encode(module,&value,1,frame,sizeof(frame),&written)||written==0) return 3;
  uint64_t raw=0,invocation=0,decoded=0,bits=0; uint32_t effect=0,length=0,copied=0;
  uint8_t response[4096],trace[16]={{0}}; struct timespec now;
  if(clock_gettime(CLOCK_MONOTONIC,&now)) return 5;
  uint64_t deadline=(uint64_t)now.tv_sec*1000000000ULL+(uint64_t)now.tv_nsec+5000000000ULL;
  if(omni_invocation_v1_module_open((const uint8_t*)path,(uint32_t)strlen(path),artifact_hash,descriptor_hash,&raw)) return 6;
  if(omni_invocation_v1_invocation_create(raw,frame,written,0,0,0,deadline,1048576,4096,0,trace,&invocation)) return 7;
  if(omni_invocation_v1_invoke(invocation,&effect,&length)||length>sizeof(response)) return 8;
  if(omni_invocation_v1_result_read(invocation,response,sizeof(response),&copied)||copied!=length) return 9;
  if(omni_host_sdk_v1_result_decode(module,response,copied,&decoded)||omni_host_sdk_v1_value_scalar_get(decoded,&bits)||bits!=7) return 10;
  if(omni_host_sdk_v1_value_destroy(decoded)||omni_invocation_v1_invocation_destroy(invocation)||omni_invocation_v1_module_close(raw)) return 11;
  if(omni_host_sdk_v1_value_destroy(value)||omni_host_sdk_v1_module_close(module)) return 4;
  return 0;
}}\n''',encoding='utf-8')
    run(['cc','-std=c11','-Werror','-I',str(sdk/'include'),'-I',str(sdk/'runtime'),str(c_consumer),'-L',str(sdk/'lib'),'-lomni_host_sdk_v1','-o',str(c_binary)],env)
    c_env={**env,'LD_LIBRARY_PATH':f"{sdk/'lib'}:{sdk/'runtime'}"}; run([str(c_binary)],c_env)
    generated=DIST/'generated.mjs'; run(['python3',str(sdk/'tools/omni_sdk_codegen.py'),'--language','typescript','--runtime',str(sdk/'runtime/libomni_invocation_v1.so'),'--artifact',str(artifact),'--artifact-sha256',receipt['artifact_sha256'],'--descriptor-sha256',receipt['descriptor_sha256'],'--output',str(generated)],env)
    report={'schema':'omni.sdk-distribution-probe/1','status':'PASS','deterministic_build':'PASS','asset_sha256':digest(one),'sdk_doctor':'PASS','portable_omni_std':'PASS','portable_package_resolution':'PASS','fresh_extracted_sdk':'PASS','fresh_c_consumer':'PASS','fresh_c_invocation_result':7,'source_checkout_dependency':'NONE for installed commands; packaging reads this source tree','host_artifact_sha256':digest(artifact),'generated_from_fresh_sdk':'PASS'}
    (ROOT/'sdk_distribution_report.json').write_text(json.dumps(report,indent=2)+'\n'); print(json.dumps(report,sort_keys=True))
if __name__=='__main__': main()
