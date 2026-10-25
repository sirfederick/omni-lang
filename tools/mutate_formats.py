#!/usr/bin/env python3
"""Bounded deterministic mutation campaign: validates inputs; never runs their programs."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import random
import subprocess
import tempfile

ROOT=Path(__file__).resolve().parents[1]

def main() -> int:
    parser=argparse.ArgumentParser()
    parser.add_argument('--binary',type=Path,default=ROOT/'bin/linux-x86_64/omni')
    parser.add_argument('--cases',type=int,default=1800)
    parser.add_argument('--seed',type=int,default=20260920)
    parser.add_argument('--report',type=Path,default=ROOT/'evidence/mutations.json')
    args=parser.parse_args()
    if not 1<=args.cases<=10000:parser.error('cases must be 1..10000')
    rng=random.Random(args.seed)
    with tempfile.TemporaryDirectory(prefix='omni-mutation-') as td:
        tmp=Path(td)
        env={**os.environ,'OMNI_HOME':str(ROOT)}
        def run(*argv):
            return subprocess.run([str(args.binary),*map(str,argv)],capture_output=True,timeout=5,env=env)
        seed_sources=[ROOT/'examples/observaciones/main.omni',ROOT/'examples/borrowed_views.omni',ROOT/'examples/generics_iteration.omni',ROOT/'examples/borrow_mut.omni',ROOT/'examples/floats.omni',ROOT/'examples/unicode_text.omni',ROOT/'examples/data_control.omni',ROOT/'examples/ranges.omni']
        seeds=[]
        for si,src in enumerate(seed_sources):
            wire=tmp/f'seed{si}.owire'
            r=run('pack',src,'-o',wire)
            if r.returncode:raise RuntimeError(r.stderr.decode())
            wav=run('wave',src);human=run('fmt',src);on=run('onme',src)
            if wav.returncode or human.returncode or on.returncode:raise RuntimeError('seed generation failed')
            store=tmp/f'seed{si}.omem'; packed=run('memory-pack',src,'-o',store)
            if packed.returncode:raise RuntimeError(packed.stderr.decode())
            index=Path(str(store)+'.idx'); proposal=tmp/f'seed{si}.oprop'
            pr=run('proposal',store,'--entity','main','--agent','mutation_agent','--note','bounded-proposal-seed','-o',proposal)
            if pr.returncode:raise RuntimeError(pr.stderr.decode())
            ocap=tmp/f'seed{si}.ocap'
            off=run('cognition-offload',src,'--provider','loopback','--grant','external.egress','--max-input-tokens','100000','--max-output-tokens','64','--max-cost-microunits','0','--max-latency-ms','1000','-o',ocap)
            if off.returncode:raise RuntimeError(off.stderr.decode())
            seeds.extend([('.owire',wire.read_bytes()),('.owave',wav.stdout),('.onme',on.stdout),('.omni',human.stdout),('.omem',store.read_bytes()),('.idx',index.read_bytes()),('.oprop',proposal.read_bytes()),('.ocap',ocap.read_bytes())])
        stats={'accepted':0,'rejected':0,'unexpected':[],'by_format':{},'by_operation':{}}
        for k in range(args.cases):
            ext,seed=seeds[k%len(seeds)];b=bytearray(seed);operation=rng.randrange(9)
            if operation==0:
                for _ in range(rng.randrange(1,5)):
                    n=rng.randrange(len(b));b[n]^=1<<rng.randrange(8)
            elif operation==1:
                n=rng.randrange(len(b));del b[n:n+rng.randrange(1,40)]
            elif operation==2:
                n=rng.randrange(len(b));b[n:n]=bytes(rng.randrange(256) for _ in range(rng.randrange(1,20)))
            elif operation==3:
                b=b[:rng.randrange(len(b))]
            elif operation==4:
                # Embedded NUL: catches accidental C-string semantics on text-facing parsers.
                n=rng.randrange(len(b)+1);b[n:n]=b'\x00'
            elif operation==5:
                # CR/LF injection: hostile line framing and parser-boundary case.
                n=rng.randrange(len(b)+1);b[n:n]=rng.choice((b'\r',b'\n',b'\r\n'))
            elif operation==6:
                # Invalid UTF-8 byte sequences. Binary Wire may legitimately contain these,
                # but textual Particle/Wave surfaces must fail closed when structurally affected.
                n=rng.randrange(len(b)+1);b[n:n]=rng.choice((b'\x80',b'\xc0\xaf',b'\xed\xa0\x80',b'\xf5\x80\x80\x80'))
            elif operation==7:
                # Duplicate/repeated segment pressure without unbounded allocation.
                if len(b):
                    start=rng.randrange(len(b)); end=min(len(b),start+rng.randrange(1,min(64,len(b)-start)+1))
                    n=rng.randrange(len(b)+1);b[n:n]=b[start:end]
            else:
                # Extreme-but-bounded length/trailing-data pressure.
                b.extend(bytes([rng.randrange(256)])*rng.randrange(128,1025))
            path=tmp/('mutated'+ext);path.write_bytes(b)
            try:
                if ext=='.omem':
                    result=run('memory-summary',path)
                elif ext=='.idx':
                    base_store=tmp/'indexed-query.omem'; canonical=tmp/'seed0.omem'; base_store.write_bytes(canonical.read_bytes()); Path(str(base_store)+'.idx').write_bytes(b)
                    result=run('memory-query',base_store,'--entity','main')
                elif ext=='.oprop':
                    canonical=tmp/'seed0.omem'; result=run('proposal-apply',canonical,'--proposal',path,'--grant','memory.write','-o',tmp/'proposal-mutated.omem','--force')
                elif ext=='.ocap':
                    result=run('cognition-offload-run',path)
                else:
                    result=run('check',path)
                key='accepted' if result.returncode==0 else 'rejected' if result.returncode==2 else 'unexpected'
                op_names=('bitflip','delete','insert_random','truncate','insert_nul','insert_crlf','invalid_utf8','duplicate_segment','extreme_trailing')
                op_name=op_names[operation]
                hostile_text_accept = ext in ('.omni','.owave','.onme','.omem','.idx','.oprop','.ocap') and op_name in ('insert_nul','invalid_utf8') and result.returncode==0
                if key=='unexpected' or hostile_text_accept:
                    if hostile_text_accept: key='unexpected'
                    stats['unexpected'].append({'case':k,'format':ext,'operation':op_name,'status':result.returncode,'reason':'hostile textual input accepted' if hostile_text_accept else 'unexpected return code','stderr':result.stderr[:2000].decode(errors='replace')})
                else:stats[key]+=1
                stats['by_format'].setdefault(ext,{'accepted':0,'rejected':0,'unexpected':0})[key]+=1
                stats['by_operation'].setdefault(op_name,{'accepted':0,'rejected':0,'unexpected':0})[key]+=1
            except subprocess.TimeoutExpired:
                stats['unexpected'].append({'case':k,'format':ext,'timeout':True})
        
        try: compiler_ref=str(args.binary.resolve().relative_to(ROOT.resolve()))
        except ValueError: compiler_ref='<external-test-binary>'
        report={'cases':args.cases,'seed':args.seed,'compiler':compiler_ref,'seed_sources':[str(x.relative_to(ROOT)) for x in seed_sources],**stats,
                'scope':'Bounded 0.8.1 validation of Particle/Wave16/OMC16/ONME2/OSM2/OSMI2/OMP1/OCAP1 surfaces, including BorrowMut/persistent-loan, IEEE float, Unicode scalar/Text and A81.3 data/control and A81.4 Range seed semantics; mutated programs are never executed.',
                'hostile_classes':['NUL','CR/LF','invalid UTF-8','truncation','duplicate segments','extreme bounded lengths','random bytes/bitflips'],
                'caveat':'Acceptance of a mutation can be legitimate: Wire is not authenticated. Finite campaign, not a security proof.'}
        args.report.write_text(json.dumps(report,indent=2)+'\n')
        print(json.dumps(report,indent=2))
        return 1 if stats['unexpected'] else 0

if __name__=='__main__':raise SystemExit(main())
