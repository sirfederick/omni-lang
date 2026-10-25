#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Federico T. Begna
# SPDX-License-Identifier: MIT OR Apache-2.0
"""Current source/spec structural consistency. No Git or historical receipts required."""
from __future__ import annotations

from pathlib import Path

import json

import re

ROOT=Path(__file__).resolve().parents[1]

errors:list[str]=[]

version=(ROOT/'VERSION').read_text(encoding='utf-8').strip()

def read(rel:str)->str:
    return (ROOT/rel).read_text(encoding='utf-8')

grammar=read('spec/particle.ebnf')

header=read('compiler/src/omni.hpp')

formats=read('compiler/src/formats.cpp')

main=read('compiler/src/main.cpp')

caps=read('compiler/src/capabilities.cpp')

checker=read('compiler/src/check.cpp')

particle=read('compiler/src/particle.cpp')

ir=read('spec/IR_WAVE_WIRE_0_2.md')

identity=read('spec/TYPE_IDENTITY_0_2.md')

product=read('spec/PRODUCT_TYPES_LAYOUT_0_2.md')

views=read('spec/BORROWED_VIEWS_0_2.md')

abstraction=read('spec/GENERICS_ABSTRACTION_0_2.md')

l07=read('spec/LANGUAGE_0_7.md')

living=read('spec/LIVING_COMPUTATIONAL_SYSTEM_0_7.md')

osnmf=read('spec/OSNMF_0_7.md')

onme=read('spec/ONME_0_7.md')

ocap=read('spec/OCAP_0_7.md')

l08=read('spec/LANGUAGE_0_8.md')

data081=read('spec/DATA_LANGUAGE_0_8_1.md')

compat081=read('spec/COMPATIBILITY_0_8_1.md')

unicode081=read('spec/UNICODE_TEXT_0_8_1.md')

data_control081=read('spec/DATA_CONTROL_0_8_1.md')

range081=read('spec/RANGE_ITERATION_0_8_1.md')

a8freeze=read('spec/A8_RELEASE_ARCHITECTURE_FREEZE_0_8_2_TO_0_8_9.md')

concurrency85=read('spec/CONCURRENCY_0_8_5.md')

hosted86=read('spec/HOSTED_EFFECTS_FFI_0_8_6.md')

host_policy86=read('compiler/src/host_policy.cpp')

tooling87=read('spec/TOOLING_DX_OBSERVABILITY_0_8_7.md')

targets88=read('spec/TARGET_PROFILES_0_8_8.md')

hardening89=read('spec/RELEASE_HARDENING_0_8_9.md')

package_identity=read('spec/PACKAGE_LOCK_SOURCE_IDENTITY_1_0.md')

a93=read('spec/RUNTIME_HARDENING_0_9_3.md')

a94=read('spec/SYSTEMIC_DURABILITY_0_9_4.md')

a95=read('spec/HOST_INTEROP_PROFILE_0_9_5.md')

a96=read('spec/SECURITY_SUPPLY_CHAIN_0_9_6.md')

lsp87=read('tools/omni_lsp.py')

buildmeta87=read('compiler/src/buildmeta.cpp')

epoch82=read('spec/EPOCH_MONOTONICITY_0_8_2.md')

memory08=read('spec/MEMORY_AUTHORITY_0_8.md')

compat08=read('spec/COMPATIBILITY_0_8.md')

source_manifest=[
    x.strip()
    for x in read('tools/core_sources.txt').splitlines()
    if x.strip() and not x.lstrip().startswith('#')
]


# Coverage: SC-003
for name,text in (
    ('A8_RELEASE_ARCHITECTURE_FREEZE',a8freeze),
    ('EPOCH_MONOTONICITY_0_8_2',epoch82),
):
    if '0.8.2' not in text:
        errors.append(f'{name} A82 contract identity mismatch')


# Coverage: SC-004
if f'VERSION = "{version}"' not in header:
    errors.append('compiler VERSION mismatch')

kind_match=re.search(r'enum Kind:uint8_t\s*\{(.*?)\}\s*kind=',header,re.S)


# Coverage: SC-005
if not kind_match:
    errors.append('cannot parse Type::Kind')
else:
    raw=re.sub(r'//.*?$','',kind_match.group(1),flags=re.M)
    kinds=[x.strip() for x in raw.split(',') if x.strip()]

    def switch_body(signature:str)->str:
        try:
            start=header.index(signature)
            sw=header.index('switch(t.kind)',start)
            op=header.index('{',sw)
        except ValueError:
            return ''
        depth=1
        i=op+1
        while i<len(header) and depth:
            if header[i]=='{':
                depth+=1
            elif header[i]=='}':
                depth-=1
            i+=1
        return header[op+1:i-1] if depth==0 else ''

    for signature in ('inline std::string typeName','inline std::string canonicalTypeIdentity'):
        body=switch_body(signature)
        if not body:
            errors.append(f'cannot parse {signature} switch')
            continue
        cases=re.findall(r'case Type::([A-Za-z0-9_]+)',body)
        missing=[k for k in kinds if cases.count(k)==0]
        duplicates=[k for k in kinds if cases.count(k)>1]
        extra=sorted(set(cases)-set(kinds))
        if missing or duplicates or extra:
            errors.append(
                f'{signature} Type::Kind mismatch '
                f'missing={missing} duplicate={duplicates} extra={extra}'
            )


# Coverage: SC-006
for token in (
    '"Option"','"Some"','"None"','match_option',
    '"u8"','"u16"','"u64"','"i8"','"i64"',
    '+%','+|','enum_decl','enum_variant','match_enum','constructor_name',
    '"Tuple"','"Array"','"View"','"BorrowMut"','"f32"','"f64"','"Char"',
    'float_type','float_literal','destructuring','pattern_binding','loop_control','index_access','range_expression','"Range"',
    '"break"','"continue"',
    'generic_parameter_list','generic_constraint','for_each','method_call','"in"','"::"',
):
    if token not in grammar:
        errors.append(f'grammar missing {token}')


# Coverage: SC-007
for token in (
    'Wave11','OMC11','Wave12','OMC12','Wave13','OMC13','Wave14','OMC14','Wave15','OMC15','Wave16','OMC16','Wave17','OMC17','Wave18','OMC18','Wave19','OMC19','Wave20','OMC20','OMCX',
    'for-each','BorrowMut','persistent local loan','monomorph','f32','f64','Char','let-tuple','break','continue','Range<u32>','closure-call',
):
    if token not in ir:
        errors.append(f'IR spec missing {token}')


# Coverage: SC-008
for token in (
    'emittedVersion=emittedRepresentation(p,projection!=IdentityProjection::Onme2Compatibility)','OMCX','w.u32(emittedRepresentation(p))','a87Program(p,recursiveOptions)?21u:(a86Program(p)?20u:(a85Program(p)?19u:18u))','OMC18','OMC19','OMC20','OMC21','BorrowMut','ClosureCall','TaskScope','Spawn','Expr::Join','Expr::Deadline','Expr::Channel',
    'pendingCompositionType','typeContainsPending(p,t.parts[0],module)','typeRequiresConsumption(p,payload,module)','typeContainsPending(p,v.payload,en.module)','typeContainsPending(p,field.type,r.module)','typeContainsPending(p,field.type,rd.module)',
    'prestamos locales persistentes requieren Wave 12',
    'prestamos locales persistentes requieren OMC12',
    'f32/f64 requieren Wave 13','f32/f64 requieren OMC13',
    'Char requiere Wave 14','Char requiere OMC14',
    'Unicode scalar/Text API requiere Wave 14','Unicode scalar/Text API requiere OMC14',
    'statement A81.3 requiere Wave 15','statement A81.3 requiere OMC15',
    'wildcard pattern requiere Wave 15','wildcard pattern requiere OMC15',
    'Range requiere Wave 16','Range requiere OMC16',
    'range syntax requiere Wave 16','range syntax requiere OMC16',
    'closure-call requiere Wave 17',
    'Stmt::ForEach','Stmt::Destructure','Stmt::Break','Stmt::Continue',
):
    if token not in formats:
        errors.append(f'current writer/fence source missing {token}')


# Coverage: SC-009
for token in ('task_scope','spawn','join','cancel','deadline','channel<T>','Wave19','OMC19','E_TASK_TRANSFER','E_CHANNEL_CAPACITY'):
    if token not in concurrency85:
        errors.append(f'A85 concurrency contract missing {token}')


# Coverage: SC-010
for token in ('HostAuthority','process.spawn','net.connect','ffi.call','Wave20','OMC20','UNKNOWN_OUTCOME'):
    if token not in hosted86:
        errors.append(f'A86 hosted-effects contract missing {token}')


# Coverage: SC-011
for token in ('FROZEN_FOR_IMPLEMENTATION','REM-C04','REM-C05','REM-C06','REM-Q04',
              'PRE_DISPATCH','DISPATCHED','ACKNOWLEDGED','UNKNOWN_OUTCOME',
              'Wave20/OMC20','Identity != Observation != Authority'):
    if token not in a93:
        errors.append(f'A93 runtime-hardening contract missing {token}')


# Coverage: SC-012
for token in ('OSMC1','atomic *visibility*','store_bytes_read','full_store_hashed',
              'GAP_REQUIRES_RESNAPSHOT','durable overrides','OSM2/OSMI2'):
    if token not in a94:
        errors.append(f'A94 systemic-durability contract missing {token}')


# Coverage: SC-013
for token in ('fixed copy-only FFI', 'Node', 'Python', 'OCAP1', 'OHP1', 'UNKNOWN_OUTCOME',
              'never authority', 'real compiled C shared-library', 'No external provider claim'):
    if token not in a95:
        errors.append(f'A95 interop-profile contract missing {token}')


# Coverage: SC-014
for token in ('Authority and capability', 'Stale generation', 'Representation downgrade',
              'Package manifests and locks', 'deterministic machine-readable component', 'Secrets and bearer credentials',
              'not publisher authenticity', 'manufacture PASS'):
    if token not in a96:
        errors.append(f'A96 security/supply-chain contract missing {token}')

a93_test = ROOT / 'tests/language_0_9_3.py'

a93_matrix = ROOT / 'tests/corpus/a93/runtime_fault_matrix.json'


# Coverage: SC-015
if not a93_test.is_file():
    errors.append('A93 runtime-hardening executable test is missing')


# Coverage: SC-016
if not a93_matrix.is_file():
    errors.append('A93 runtime fault matrix is missing')
else:
    try:
        a93_rows = json.loads(a93_matrix.read_text(encoding='utf-8'))['scenarios']
        a93_ids = [row['id'] for row in a93_rows]
        if a93_ids != [f'A93-F{i:02d}' for i in range(1, 14)]:
            errors.append('A93 runtime fault matrix IDs are incomplete or out of order')
        for row in a93_rows:
            if row.get('phase') not in {'PRE_DISPATCH', 'DISPATCHED', 'ACKNOWLEDGED'}:
                errors.append(f"A93 runtime fault matrix invalid phase for {row.get('id')}")
            if not row.get('resource_oracle'):
                errors.append(f"A93 runtime fault matrix missing resource oracle for {row.get('id')}")
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        errors.append(f'invalid A93 runtime fault matrix: {exc}')

a94_test = ROOT / 'tests/language_0_9_4.py'

a94_matrix = ROOT / 'tests/corpus/a94/systemic_durability_matrix.json'


# Coverage: SC-017
if not a94_test.is_file():
    errors.append('A94 systemic-durability executable test is missing')


# Coverage: SC-018
if not a94_matrix.is_file():
    errors.append('A94 systemic durability matrix is missing')
else:
    try:
        a94_rows = json.loads(a94_matrix.read_text(encoding='utf-8'))['scenarios']
        if [row['id'] for row in a94_rows] != [f'A94-D{i:02d}' for i in range(1, 13)]:
            errors.append('A94 systemic durability matrix IDs are incomplete or out of order')
        if any(row.get('layer') not in {'L2', 'L3', 'L4'} or not row.get('oracle') for row in a94_rows):
            errors.append('A94 systemic durability matrix lacks a causal layer/oracle')
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        errors.append(f'invalid A94 systemic durability matrix: {exc}')

a95_test = ROOT / 'tests/language_0_9_5.py'

a95_matrix = ROOT / 'tests/corpus/a95/interop_profile_matrix.json'


# Coverage: SC-019
if not a95_test.is_file():
    errors.append('A95 interop-profile executable test is missing')


# Coverage: SC-020
if not a95_matrix.is_file():
    errors.append('A95 interop profile matrix is missing')
else:
    try:
        a95_rows = json.loads(a95_matrix.read_text(encoding='utf-8'))['scenarios']
        if [row['id'] for row in a95_rows] != [f'A95-I{i:02d}' for i in range(1, 11)]:
            errors.append('A95 interop profile matrix IDs are incomplete or out of order')
        if any(row.get('layer') not in {'L2', 'L3', 'L4'} or not row.get('oracle') or not row.get('evidence_class') for row in a95_rows):
            errors.append('A95 interop profile matrix lacks layer/evidence/oracle')
        for row in a95_rows:
            if row.get('evidence_class') in {'LOOPBACK_AND_OFFLINE', 'MOCK'} and 'live provider' in row.get('claim', '').lower():
                errors.append(f"A95 {row.get('id')} falsely upgrades loopback/mock provider evidence")
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        errors.append(f'invalid A95 interop profile matrix: {exc}')

a96_test = ROOT / 'tests/language_0_9_6.py'

a96_matrix = ROOT / 'tests/corpus/a96/security_supply_chain_matrix.json'

a96_tool = ROOT / 'tools/a96_security_supply_chain.py'


# Coverage: SC-021
if not a96_test.is_file() or not a96_tool.is_file():
    errors.append('A96 security/supply-chain executable gate is missing')


# Coverage: SC-022
if not a96_matrix.is_file():
    errors.append('A96 security/supply-chain matrix is missing')
else:
    try:
        a96_rows = json.loads(a96_matrix.read_text(encoding='utf-8'))['scenarios']
        if [row['id'] for row in a96_rows] != [f'A96-S{i:02d}' for i in range(1, 11)]:
            errors.append('A96 security/supply-chain matrix IDs are incomplete or out of order')
        if any(row.get('layer') not in {'L0','L1','L2','L3','L4'} or not row.get('attack') or not row.get('oracle') for row in a96_rows):
            errors.append('A96 security/supply-chain matrix lacks causal layer/attack/oracle')
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        errors.append(f'invalid A96 security/supply-chain matrix: {exc}')

a97_test = ROOT / 'tests/language_0_9_7.py'

a97_matrix = ROOT / 'tests/corpus/a97/operations_maintenance_matrix.json'

a97_tool = ROOT / 'tools/a97_operations_maintenance.py'


# Coverage: SC-023
if not a97_test.is_file() or not a97_tool.is_file():
    errors.append('A97 operations/maintenance executable gate is missing')


# Coverage: SC-024
if not a97_matrix.is_file():
    errors.append('A97 operations/maintenance matrix is missing')
else:
    try:
        a97_data = json.loads(a97_matrix.read_text(encoding='utf-8'))
        a97_rows = a97_data['scenarios']
        if a97_data.get('hard_max_seconds') != 1200:
            errors.append('A97 prerelease operational gate exceeds the 1200-second maximum')
        if [row['id'] for row in a97_rows] != [f'A97-O{i:02d}' for i in range(1, 8)]:
            errors.append('A97 operations/maintenance matrix IDs are incomplete or out of order')
        if any(row.get('layer') not in {'L0','L1','L2','L3','L4','L5'} or not row.get('boundary') or not row.get('oracle') for row in a97_rows):
            errors.append('A97 operations/maintenance matrix lacks causal layer/boundary/oracle')
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        errors.append(f'invalid A97 operations/maintenance matrix: {exc}')


# Coverage: SC-025
for token in ('OHP1','generation','not_after_tick','grant.max_bytes','E_HOST_POLICY','HostPolicy::allows'):
    if token not in host_policy86:
        errors.append(f'A86 host-policy implementation missing {token}')


# Coverage: SC-026
for token in ('process.spawn','ffi.call'):
    if token not in caps:
        errors.append(f'A86 capability registry missing {token}')


# Coverage: SC-027
for token in ('omni.diagnostic/1','--check','--write','Source maps','doctor --json','Tool output is evidence'):
    if token not in tooling87:
        errors.append(f'A87 tooling contract missing {token}')


# Coverage: SC-028
for token in ('textDocument/completion','textDocument/hover','textDocument/definition','textDocument/references','textDocument/rename'):
    if token not in lsp87:
        errors.append(f'A87 LSP implementation missing {token}')


# Coverage: SC-029
for token in ('omni.source-map/1','receiptSourcePath'):
    if token not in buildmeta87:
        errors.append(f'A87 provenance implementation missing {token}')


# Coverage: SC-030
for token in ('linux-x86_64-gnu','windows-x86_64-msvc','linux-aarch64-gnu','macos-aarch64','SUPPORTED','EXPERIMENTAL_NOT_RUN','omni target list --json','omni target probe --json'):
    if token not in targets88:
        errors.append(f'A88 target-profile contract missing {token}')


# Coverage: SC-031
for token in ('omni.target-matrix/1','omni.target-probe/1','linux-x86_64-gnu'):
    if token not in main:
        errors.append(f'A88 target registry implementation missing {token}')


# Coverage: SC-032
if 'target_id' not in buildmeta87:
    errors.append('A88 provenance missing target_id')


# Coverage: SC-033
for token in ('omni.release-hardening/1','Versioned malformed corpus','at least 60 observed seconds','Hashes provide integrity, not publisher authenticity'):
    if token not in hardening89:
        errors.append(f'A89 hardening contract missing {token}')


# Coverage: SC-034
for token in (
    'FROZEN_FOR_IMPLEMENTATION', 'IR-C03', 'RFC-0073', 'omni.lock/2',
    'omni.lock/1', 'semantic_source_sha256', 'src/', 'E_PACKAGE_LOCK',
    'symbolic link', 'never rewrites',
):
    if token not in package_identity:
        errors.append(f'package source-identity contract missing {token}')


# Coverage: SC-035
for token in ('semanticSourceHash', 'legacyTreeHash', 'omni.lock/2', 'lockSchema'):
    if token not in (ROOT/'compiler/src/packages.cpp').read_text(encoding='utf-8'):
        errors.append(f'package source-identity implementation missing {token}')

hardening_tool=read('tools/a89_hardening.py')


# Coverage: SC-036
for token in ('omni.release-hardening/1','omni.malformed-corpus/1','bounded-recovery-stress-not-prolonged-soak','dependency_inventory','cache_repair'):
    if token not in hardening_tool:
        errors.append(f'A89 hardening harness missing {token}')


# Coverage: SC-037
if 'reborrow requiere Wave18/OMC18' not in checker:
    errors.append('checker missing Wave18 reborrow fence')


# Coverage: SC-038
if 'cleanup estructurado requiere Wave18/OMC18' not in checker:
    errors.append('checker missing Wave18 structured-cleanup fence')


# Coverage: SC-039
if 'cleanupFrom' not in (ROOT / "compiler/src"/'llvm.cpp').read_text(encoding='utf-8'):
    errors.append('native backend missing structured-cleanup lowering')

runtime85=read('runtime/omni_runtime.c')

llvm85=read('compiler/src/llvm.cpp')


# Coverage: SC-040
for token in ('OmniRuntimeContext','active_context','omni_runtime_begin','omni_runtime_end'):
    if token not in runtime85:
        errors.append(f'A85 native RuntimeContext missing {token}')


# Coverage: SC-041
for token in ('@omni_runtime_begin','@omni_runtime_end'):
    if token not in llvm85:
        errors.append(f'A85 native entrypoint missing {token}')


# Coverage: SC-042
for token in (
    'explicit type arguments','monomorph','Integer','Plain',
    'Uniform Method Call Syntax','Array<T,N>','View<T>',
):
    if token not in abstraction:
        errors.append(f'abstraction spec missing {token}')


# Coverage: SC-043
for token in (
    'omni.type-descriptor/2','omni.type/1','legacy_descriptor_id',
    'omni.type-descriptor/1','layout_id','type_id',
):
    if token not in identity:
        errors.append(f'type identity doc missing {token}')


# Coverage: SC-044
for token in ('semanticTypeId','canonicalTypeIdentity'):
    if token not in header:
        errors.append(f'header missing canonical TypeID seam {token}')


# Coverage: SC-045
for token in ('std::string semanticTypeId','omni.type-descriptor/2','legacy_descriptor_id'):
    if token not in particle:
        errors.append(f'type descriptor implementation missing {token}')

osnmf_identity=read('compiler/src/osnmf.cpp')


# Coverage: SC-046
if 'return semanticTypeId(t)' not in osnmf_identity:
    errors.append('OSNMF does not consume the canonical semanticTypeId implementation')


# Coverage: SC-047
for token in ('type_identity_domain','canonical_identity_material','legacy_descriptor_schema','legacy_descriptor_identity_material'):
    if token not in particle:
        errors.append(f'type descriptor v2 migration surface missing {token}')


# Coverage: SC-048
for token in (
    'omni.layout-descriptor/1','canonical-little-endian-v1',
    'E_BOUNDS','Array<T,N>','Tuple<T',
):
    if token not in product:
        errors.append(f'product spec missing {token}')


# Coverage: SC-049
for token in ('E_VIEW_SOURCE','E_VIEW_MUTABLE','E_VIEW_ESCAPE','view.sub','zero-copy guarantee','OMCX'):
    if token not in views:
        errors.append(f'view spec missing {token}')


# Coverage: SC-050
for p in (ROOT/'spec').glob('*DEV*.md'):
    errors.append(f'historical/profile spec leaked into normative spec/: {p.name}')


# Coverage: SC-051
for token in (
    'Value != Resource != Authority','Borrow != pointer','Owned<T>','BorrowMut<T>',
    'Place','Origin','Loan','DropObligation','runtime Authority','statement granularity',
):
    if token not in memory08 and token not in l08:
        errors.append(f'Alpha8 memory/authority spec missing {token}')


# Coverage: SC-052
for token in ('Wave11','OMC11','Wave12','OMC12','OSM2','OSMI2','ONME2'):
    if token not in compat08:
        errors.append(f'Alpha8 compatibility spec missing {token}')


# Coverage: SC-053
for token in (
    'OwnershipLedger','OwnershipState','Uninitialized, Live, Moved, Dropped',
    'allOwnedHandled','LoanLedger','Place','Origin','Region',
    'loanConflicts','retireDeadLoans','registerLocalLoan',
    'E_BORROW_CONFLICT','E_BORROW_ESCAPE','E_BORROW_EXPIRED',
):
    if token not in checker:
        errors.append(f'Alpha8 checker missing {token}')


# Coverage: SC-054
for token in ('E_BORROW_CONFLICT','E_BORROW_ESCAPE','E_BORROW_EXPIRED','E_TASK_ORPHAN','E_TASK_TRANSFER','E_CHANNEL_CAPACITY','E_CHANNEL_CLOSED','E_DEADLINE'):
    if token not in main:
        errors.append(f'Alpha8 diagnostics registry missing {token}')


# Coverage: SC-056
for token in ('Wave13','OMC13','Wave14','OMC14','Wave15','OMC15','Wave16','OMC16','1..15','ONME2','OSM2','OSMI2'):
    if token not in compat081:
        errors.append(f'0.8.1 compatibility contract missing {token}')


# Coverage: SC-058
for token in (
    'Unicode scalar','text.equals','text.byte_len','text.scalar_len','text.scalar_at',
    'no embedded NUL','No implicit NFC','Grapheme',
):
    if token not in unicode081:
        errors.append(f'Unicode/Text contract missing {token}')


# Coverage: SC-059
for token in (
    'Tuple destructuring','Array<T,N>[i]','View<T>[i]','break','continue',
    'E_LOOP_CONTROL','Wave15','OMC15','Range semantics',
):
    if token not in data_control081:
        errors.append(f'A81.3 data/control contract missing {token}')


# Coverage: SC-060
for token in (
    'Range<u32>','0u32..10u32','0u32..=10u32','Array<T,N>','View<T>',
    'Iterator<T>','IntoIterator<T>','Value != Resource != Authority','Wave16','OMC16',
):
    if token not in range081:
        errors.append(f'A81.4 range/iterator contract missing {token}')

osnmf_src=read('compiler/src/osnmf.cpp')

onme_src=read('compiler/src/onme.cpp')


# Coverage: SC-066
for token in (
    'MemoryNucleus','NeuralEpoch','SystemMemory','CognitiveProposal',
    'buildSystemMemory','parseONME',
):
    if token not in header:
        errors.append(f'header missing inherited Alpha7 {token}')


# Coverage: SC-067
for token in (
    'omni.osnmf/1','OSM1','OSM2','OSMI2','omni.osmi-projection/2',
    'semanticTypeId(t)','runtime-observation','structural-sharing/cow-v1',
    'semantic-fact','stale cognitive proposal','omni.synaptic-scale/1',
    'OCAP1','external.egress',
):
    if token not in osnmf_src:
        errors.append(f'OSNMF implementation missing {token}')


# Coverage: SC-068
for token in (
    'ONME2','ONME3','omni.onme-envelope/2','omni.onme-envelope/3','authoring-lineage integrity mismatch',
    'OSNMF executable root mismatch','machine-semantic-projection',
):
    if token not in onme_src:
        errors.append(f'ONME implementation missing {token}')


# Coverage: SC-069
for token in (
    'omni memory','omni memory-pack','omni memory-query','omni memory-trace',
    'omni observe','omni proposal','omni proposal-merge','omni onme',
    'omni synapse-scale','omni cognition-offload','omni cognition-offload-run',
):
    if token not in main:
        errors.append(f'CLI missing {token}')


# Coverage: SC-070
for token in ('One persistent computational body','The body remembers','cryptographically verifiable'):
    if token not in living:
        errors.append(f'constitution missing {token}')


# Coverage: SC-071
for token in (
    'OCAP1','external.egress','deny-confidential-by-default',
    'CognitiveBudget','proposal != authority',
):
    if token not in ocap:
        errors.append(f'OCAP spec missing {token}')


# Coverage: SC-072
for forbidden in ('src/component.cpp','src/policy.cpp'):
    if (ROOT/forbidden).exists():
        errors.append(f'profile source leaked into Core src/: {forbidden}')


# Coverage: SC-073
for rel in source_manifest:
    if not (ROOT/rel).is_file():
        errors.append(f'core source manifest missing file: {rel}')
    if rel.startswith('profiles/'):
        errors.append(f'profile source in Core build manifest: {rel}')


# Coverage: SC-074
for token in ('inspect-policy','omni ecu','EcuPolicy','ComponentContract'):
    if token in main:
        errors.append(f'profile command/type leaked into Core main: {token}')


# Coverage: SC-075
for token in (
    'model.call','model.stream','tool.execute',
    'knowledge.read','memory.propose','memory.publish',
):
    if token in caps:
        errors.append(f'profile capability leaked into Core registry: {token}')


# Coverage: SC-076
for v in range(1,16):
    for ext in ('owave','owire'):
        if not (ROOT/'reference/compat'/f'legacy{v}.{ext}').is_file():
            errors.append(f'missing legacy{v}.{ext}')


# Coverage: SC-077
try:
    matrix=json.loads(read('tests/MATRIX.json'))
    if matrix.get('version')!=version:
        errors.append('test matrix version mismatch')
    listed={x for xs in matrix.get('groups',{}).values() for x in xs}
    current={f'tests/{p.name}' for p in (ROOT/'tests').glob('*.py')}
    # Historical files are inputs to the current compatibility adapter, which
    # explicitly separates four excluded publication-presence cases.
    adapted_inputs=set(matrix.get('adapter_inputs',[]))
    missing=sorted(current-listed-adapted_inputs)
    for required in adapted_inputs:
        if required not in current:
            errors.append('missing adapter input: '+required)
    stale=sorted(listed-current)
    if missing:
        errors.append('unlisted current tests: '+','.join(missing))
    if stale:
        errors.append('test matrix references missing tests: '+','.join(stale))
    alpha8=set(matrix.get('groups',{}).get('alpha8',[]))
    for required in (
        'tests/language_0_8_alpha8.py',
        'tests/memory_authority_differential.py',
    ):
        if required not in alpha8:
            errors.append(f'alpha8 matrix missing required gate: {required}')
    alpha81=set(matrix.get('groups',{}).get('alpha8_1',[]))
    for required in ('tests/language_0_8_1_alpha8.py','tests/float_differential.py','tests/unicode_differential.py','tests/data_control_differential.py','tests/range_differential.py'):
        if required not in alpha81:
            errors.append(f'0.8.1 matrix missing required gate: {required}')
    if 'tests/language_0_8_6_alpha8.py' not in set(matrix.get('groups',{}).get('a86',[])):
        errors.append('A86 matrix missing host-policy gate')
    if 'tests/language_0_8_7_alpha8.py' not in set(matrix.get('groups',{}).get('a87',[])):
        errors.append('A87 matrix missing tooling/DX gate')
    if 'tests/language_0_8_8_alpha8.py' not in set(matrix.get('groups',{}).get('a88',[])):
        errors.append('A88 matrix missing target-profile gate')
    if 'tests/language_0_8_9_alpha8.py' not in set(matrix.get('groups',{}).get('a89',[])):
        errors.append('A89 matrix missing release-hardening gate')
    if 'tests/language_0_9_2.py' not in set(matrix.get('groups',{}).get('a92',[])):
        errors.append('A92 matrix missing semantic-conformance gate')
    if 'tests/language_0_9_5.py' not in set(matrix.get('groups',{}).get('a95',[])):
        errors.append('A95 matrix missing interop-profile gate')
    if 'tests/language_0_9_6.py' not in set(matrix.get('groups',{}).get('a96',[])):
        errors.append('A96 matrix missing security/supply-chain gate')
    if 'tests/language_0_9_7.py' not in set(matrix.get('groups',{}).get('a97',[])):
        errors.append('A97 matrix missing operations/maintenance gate')
except Exception as exc:
    errors.append(f'invalid tests/MATRIX.json: {exc}')
result={'schema':'omni.spec-sync/1','product_version':version,'scope':'static source/spec and matrix consistency; NOT_RELEASED','core_source_count':len(source_manifest),'errors':errors,'status':'PASS' if not errors else 'FAIL'}
print(json.dumps(result,indent=2))
raise SystemExit(bool(errors))
