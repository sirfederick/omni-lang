#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Federico T. Begna
# SPDX-License-Identifier: MIT OR Apache-2.0
"""Run real application examples with disposable path substitutions and grants."""
import json, os, pathlib, shutil, subprocess
ROOT=pathlib.Path(__file__).resolve().parents[1]
OUT=ROOT/'build/application-examples'
OMNI=ROOT/'build/dev/omni'

def main():
    OUT.mkdir(parents=True,exist_ok=True)
    env=dict(os.environ,OMNI_HOME=str(ROOT))
    rows=[]
    def run(args, expected=0):
        p=subprocess.run([str(x) for x in args],capture_output=True,text=True,env=env,cwd=OUT)
        row={'command':[str(x) for x in args],'exit_code':p.returncode,'expected':expected,'stdout':p.stdout,'stderr':p.stderr}
        rows.append(row)
        assert p.returncode==expected, row
    for name in ('data-cli','recovery-service'):
        package=OUT/name
        shutil.copytree(ROOT/'examples/applications'/name,package,dirs_exist_ok=True)
        inputs=package/'input';outputs=package/'output'
        inputs.mkdir(exist_ok=True);outputs.mkdir(exist_ok=True)
        data=inputs/'data.txt';data.write_text('hello world',encoding='utf-8')
        result=outputs/'result.txt';state=outputs/'state.txt';state.write_bytes(b'')
        source=package/'src/main.omni'
        text=source.read_text().replace('__INPUT__',str(data)).replace('__OUTPUT__',str(result)).replace('__STATE__',str(state))
        source.write_text(text,encoding='utf-8')
        policy=package/'policy.ohp'
        policy.write_text(f'OHP1\ngeneration|1\nnot_after_tick|100000\ngrant|fs.read|{inputs}|4096\ngrant|fs.read|{outputs}|4096\ngrant|fs.write|{outputs}|4096\n')
        run([OMNI,'host-policy','verify',policy])
        run([OMNI,'package','lock',package,'--offline'])
        run([OMNI,'package','check',package,'--offline'])
        native=package/'program'
        run([OMNI,'build',source,'-o',native])
        if name=='data-cli':
            run([native,'--omni-host-policy',policy])
            assert result.read_bytes()==b'records=2;class=accepted\n'
        else:
            run([native,'--omni-host-policy',policy]);assert state.read_bytes()==b'generation=1'
            run([native,'--omni-host-policy',policy]);assert state.read_bytes()==b'generation=2'
    (OUT/'report.json').write_text(json.dumps({'status':'PASS','applications':2,'oracles':['data output bytes','recovery generation 1','recovery generation 2'],'commands':rows},indent=2)+'\n')
    print('PASS: data-cli output and recovery-service two generations, real native executables')

if __name__=='__main__':main()
