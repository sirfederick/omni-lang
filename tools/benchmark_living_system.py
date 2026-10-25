#!/usr/bin/env python3
from __future__ import annotations
import argparse,json,os,pathlib,subprocess,tempfile,time
ROOT=pathlib.Path(__file__).resolve().parents[1]
OMNI=pathlib.Path(os.environ.get('OMNI_TEST_BIN',ROOT/'bin/linux-x86_64/omni'))
def run(args,timeout=180):
 t=time.perf_counter();p=subprocess.run([str(OMNI),*map(str,args)],capture_output=True,timeout=timeout,env={**os.environ,'OMNI_HOME':str(ROOT)});return p,time.perf_counter()-t
def checked(args,timeout=180):
 p,t=run(args,timeout)
 if p.returncode:raise SystemExit(p.stderr.decode(errors='replace'))
 return p,t
def main():
 ap=argparse.ArgumentParser();ap.add_argument('--modules',type=int,default=100);ap.add_argument('--functions-per-module',type=int,default=100);ap.add_argument('--synaptic-instances',type=int,default=1_000_000);ap.add_argument('--synaptic-overrides',type=int,default=1024);ap.add_argument('--report',type=pathlib.Path);a=ap.parse_args()
 if a.modules<1 or a.functions_per_module<1 or a.modules*a.functions_per_module>200000:ap.error('bounded benchmark supports 1..200000 functions')
 if a.synaptic_instances<1 or a.synaptic_instances>10_000_000 or a.synaptic_overrides<0 or a.synaptic_overrides>a.synaptic_instances:ap.error('invalid synaptic scale')
 with tempfile.TemporaryDirectory(prefix='omni-living-bench-') as td:
  d=pathlib.Path(td);imports=[]
  for m in range(a.modules):
   name=f'm{m:04d}';lines=[f'module {name}']+[f'pub func f{f:05d}() u32 {{ return {f%251}u32 }}' for f in range(a.functions_per_module)];(d/f'{name}.omni').write_text('\n'.join(lines)+'\n')
   if m:imports.append(f'import x{m:04d} "m{m:04d}.omni"')
  entry=d/'m0000.omni';entry.write_text('module m0000\n'+'\n'.join(imports)+'\nstruct Product { id u32 }\n'+'\n'.join(f'pub func f{f:05d}() u32 {{ return {f%251}u32 }}' for f in range(a.functions_per_module))+'\nfunc main() u32 { return f00000() }\n')
  source_files=sorted(d.glob('*.omni'));source_bytes=sum(x.stat().st_size for x in source_files)
  summary,ts=checked(['summary',entry]);data=json.loads(summary.stdout)
  store=d/'system.omem';_,tp=checked(['memory-pack',entry,'-o',store])
  q,tq=checked(['memory-query',store,'--entity','main']);qj=json.loads(q.stdout)
  tr,ttr=checked(['memory-trace',store,'--entity','main','--depth','2']);trj=json.loads(tr.stdout)
  im,tim=checked(['memory-impact',store,'--entity','f00000']);imj=json.loads(im.stdout)
  on,tone=checked(['onme-stats',entry]);onj=json.loads(on.stdout)
  sc,tsc=checked(['synapse-scale',entry,'--entity','Product','--instances',a.synaptic_instances,'--overrides',a.synaptic_overrides]);scj=json.loads(sc.stdout)
  req=d/'system.ocap';off,toff=checked(['cognition-offload',store,'--provider','loopback','--grant','external.egress','--max-input-tokens','5000000','--max-output-tokens','128','--max-cost-microunits','0','--max-latency-ms','5000','-o',req]);offj=json.loads(off.stdout)
  rr,trun=checked(['cognition-offload-run',req]);rrj=json.loads(rr.stdout)
  result={
   'schema':'omni.living-benchmark/3','language_version':subprocess.check_output([str(OMNI),'--version'],text=True).strip().split()[-1],
   'modules':a.modules,'declared_functions':a.modules*a.functions_per_module+1,'source_files':len(source_files),'source_bytes':source_bytes,
   'nuclei':data['nuclei'],'synapses':data['synapses'],'bindings':data['bindings'],
   'systemic_logical_entities':data['nuclei']+scj['logical_instances'],
   'summary_seconds':round(ts,6),'osnmf_store_pack_seconds':round(tp,6),'persisted_targeted_query_seconds':round(tq,6),
   'persisted_trace_seconds':round(ttr,6),'persisted_impact_seconds':round(tim,6),'osnmf_store_bytes':store.stat().st_size,
   'onme_stats_seconds':round(tone,6),'synaptic_scale_seconds':round(tsc,6),'cognitive_offload_prepare_seconds':round(toff,6),'cognitive_offload_loopback_seconds':round(trun,6),
   'source_scan_avoidance':{'query_source_files_scanned':qj['source_files_scanned'],'trace_source_files_scanned':trj['source_files_scanned'],'impact_source_files_scanned':imj['source_files_scanned'],'trace_full_store_parsed':trj['full_store_parsed'],'impact_full_store_parsed':imj['full_store_parsed']},
   'synaptic_scale':scj,'cognitive_offload':offj,'cognitive_result':rrj,'summary':data,'onme':onj,
   'acceptance':{'modules_ge_100':a.modules>=100,'functions_ge_10000':a.modules*a.functions_per_module+1>=10000,'logical_entities_ge_100000':data['nuclei']+scj['logical_instances']>=100000,'million_synaptic_instances':scj['logical_instances']>=1000000,'no_source_scan_for_indexed_introspection':qj['source_files_scanned']==0 and trj['source_files_scanned']==0 and imj['source_files_scanned']==0,'bounded_synaptic_materialization':not scj['full_population_materialized'],'offline_cognitive_adapter':not rrj['external_network_used'],'source_free_cognitive_offload':offj['source_files_scanned']==0 and rrj['source_files_scanned']==0},
   'claim':'measurement on this host only; not a portability or SLA guarantee'
  }
  text=json.dumps(result,indent=2)+'\n';print(text,end='')
  if a.report:a.report.parent.mkdir(parents=True,exist_ok=True);a.report.write_text(text)
if __name__=='__main__':main()
