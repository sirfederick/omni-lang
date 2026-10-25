#!/usr/bin/env python3
"""Fail-closed package and lock regression for the H02 host-entry profile."""
import hashlib
import json
import os
import pathlib
import shutil
import subprocess

ROOT = pathlib.Path(os.environ['OMNI_H02_EVIDENCE_ROOT'])
FIXTURE = pathlib.Path(__file__).resolve().parents[1] / 'fixtures' / 'host_invocation_h02'
DIST = ROOT / 'dist'
COMPILER = DIST / 'bin/omni'
CASES = ROOT / 'package-cases'
CASES.mkdir(parents=True, exist_ok=True)
results = []


def sha(data):
    return hashlib.sha256(data).hexdigest()


def run_case(name, mutate=None, entry='src/host.omni:zero', expect=0,
             package_arg=None, cwd=None):
    home = CASES / name
    home.mkdir(exist_ok=True)
    package = home / 'package'
    shutil.copytree(FIXTURE, package)
    if mutate:
        mutate(package, home)
    command = [str(COMPILER), 'build', str(package_arg or package),
               '--host-entry', entry, '-o', str(home / 'artifact.so'), '--offline']
    env = os.environ.copy()
    env['OMNI_HOME'] = str(DIST)
    env['LD_LIBRARY_PATH'] = str(DIST / 'runtime')
    process = subprocess.run(command, cwd=cwd or home, env=env,
                             capture_output=True, text=True)
    output = process.stdout + process.stderr
    passed = ((process.returncode == 0) if expect == 0 else
              (process.returncode != 0 and f'{expect}:' in output))
    results.append({'case': name, 'command': command, 'exit_code': process.returncode,
                    'expected': 'success' if expect == 0 else expect,
                    'passed': passed, 'output_sha256': sha(output.encode()),
                    'output_tail': output[-500:]})
    return home, package


run_case('valid_locked_package')
run_case('tampered_manifest', lambda p, h: (p / 'omni.package.json').write_text(
    (p / 'omni.package.json').read_text().replace('omni.host.probe', 'omni.host.tampered')),
    expect='E_PACKAGE_LOCK')
run_case('tampered_lock', lambda p, h: (p / 'omni.lock.json').write_text(
    (p / 'omni.lock.json').read_text() + ' '), expect='E_PACKAGE_LOCK')
run_case('missing_lock', lambda p, h: (p / 'omni.lock.json').unlink(), expect='E_PACKAGE_LOCK')
run_case('wrong_lock_schema', lambda p, h: (p / 'omni.lock.json').write_text(
    (p / 'omni.lock.json').read_text().replace('omni.lock/2', 'omni.lock/9')), expect='E_PACKAGE_LOCK')
run_case('mutated_semantic_source', lambda p, h: (p / 'src/host.omni').write_text(
    (p / 'src/host.omni').read_text() + '\n'), expect='E_PACKAGE_LOCK')
run_case('source_outside_root', entry='../escape.omni:zero', expect='E_PACKAGE_PATH')
run_case('traversal', entry='src/../src/host.omni:zero', expect='E_PACKAGE_PATH')
run_case('missing_host_entry', entry='src/host.omni:missing', expect='E_HOST_ENTRY')
run_case('unlocked_host_entry', lambda p, h: (p / 'src/new.omni').write_text(
    'module new\npub func zero() u32 !pure { return 0u32 }\n'),
    entry='src/new.omni:zero', expect='E_PACKAGE_LOCK')


def source_symlink(package, home):
    source = package / 'src/host.omni'
    external = home / 'external.omni'
    shutil.copy2(source, external)
    source.unlink()
    source.symlink_to(external)


run_case('symlink_escape', source_symlink, expect='E_PACKAGE_PATH')


def manifest_symlink(package, home):
    manifest = package / 'omni.package.json'
    external = home / 'external-manifest.json'
    shutil.copy2(manifest, external)
    manifest.unlink()
    manifest.symlink_to(external)


run_case('manifest_symlink', manifest_symlink, expect='E_PACKAGE_PATH')


def lock_symlink(package, home):
    lock = package / 'omni.lock.json'
    external = home / 'external-lock.json'
    shutil.copy2(lock, external)
    lock.unlink()
    lock.symlink_to(external)


run_case('lock_symlink', lock_symlink, expect='E_PACKAGE_PATH')


def root_symlink(package, home):
    (home / 'package-alias').symlink_to(package, target_is_directory=True)


home, package = run_case('root_symlink', root_symlink, expect='E_PACKAGE_PATH',
                         package_arg=CASES / 'root_symlink/package-alias')
run_case('offline_relocated', cwd=ROOT)

first = json.loads((CASES / 'valid_locked_package/artifact.so.omireceipt.json').read_text())
second = json.loads((CASES / 'offline_relocated/artifact.so.omireceipt.json').read_text())
deterministic = (first['signature_digest'] == second['signature_digest'] and
                 first['build_input_digest'] == second['build_input_digest'])
results.append({'case': 'deterministic_build_input', 'command': 'compare build receipts',
                'exit_code': 0 if deterministic else 1, 'expected': 'equal digests',
                'passed': deterministic, 'output_sha256':
                sha((first['build_input_digest'] + second['build_input_digest']).encode())})

report = {'schema': 'omni.h02-package-preflight/1', 'source_head':
          subprocess.run(['git','rev-parse','HEAD'],cwd=FIXTURE,check=True,capture_output=True,text=True).stdout.strip(),
          'compiler_sha256': sha(COMPILER.read_bytes()), 'cases': results,
          'passed': sum(case['passed'] for case in results), 'total': len(results)}
(ROOT / 'package_matrix_report.json').write_text(json.dumps(report, indent=2) + '\n')
print(json.dumps({'passed': report['passed'], 'total': report['total'],
                  'failures': [case['case'] for case in results if not case['passed']]}))
