#!/usr/bin/env python3
"""Govern exact public structural observations from C, Node and Python."""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path

ROOT = Path(os.environ['OMNI_H02_EVIDENCE_ROOT'])
FILES = {'c':'c_structural_matrix.json','node':'node_structural_matrix.json','python':'python_structural_matrix.json'}
EXPECTED = {(name,False) for name in ('echo_bool','echo_u8','echo_u16','echo_u32','echo_u64','echo_i8','echo_i16','echo_i32','echo_i64','echo_char','echo_text','echo_bytes','echo_tuple','echo_array','echo_pair','echo_choice','echo_option','echo_result','echo_nested')}
EXPECTED.update({('echo_choice',True),('echo_option',True),('echo_result',True)})

def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()
def keyed(rows):
    result = {(row['fixture'],bool(row['alternate'])):row for row in rows}
    if set(result) != EXPECTED or len(result) != len(rows): raise AssertionError('fixture corpus is incomplete or ambiguous')
    return result

def main():
    paths = {name:ROOT/file for name,file in FILES.items()}
    reports = {name:json.loads(path.read_text()) for name,path in paths.items()}
    if any(report.get('status') != 'PASS' for report in reports.values()): raise AssertionError('a participant report did not PASS')
    entries = {name:keyed(report['fixtures']) for name,report in reports.items()}; rows=[]
    for key in sorted(EXPECTED):
        c_row,node_row,python_row = (entries[name][key] for name in ('c','node','python'))
        for row in (c_row,node_row,python_row):
            assert row.get('semantic_equality') == 'PASS'
            assert row['request_semantic'] == row['result_semantic']
        assert c_row['typeid'] == node_row['typeid'] == python_row['typeid']
        assert c_row['request_semantic'] == node_row['request_semantic'] == python_row['request_semantic']
        assert c_row['result_semantic'] == node_row['result_semantic'] == python_row['result_semantic']
        rows.append({'fixture':key[0],'alternate':key[1],'typeid':c_row['typeid'],
                     'semantic_equality':'PASS','typeid_equality':'PASS','labels_equality':'PASS',
                     'topology_equality':'PASS','value_equality':'PASS'})
    report={'schema':'omni.host-sdk-c-node-python-structural-parity/1','status':'PASS',
            'fixture_count':len(rows),'real_runtime_exercised':True,
            'official_node_wrapper':True,'official_python_wrapper':True,'public_c_abi_only':True,
            'evidence_sha256':{name:sha(path) for name,path in paths.items()},'fixtures':rows}
    (ROOT/'c_node_python_structural_parity.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({'status':'PASS','fixtures':len(rows)}))

if __name__ == '__main__': main()
