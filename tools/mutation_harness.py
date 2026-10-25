#!/usr/bin/env python3
"""Mutation harness: independent mutants, run in parallel, each recompiling only the translation unit it changes.

usage: mutation_harness.py SPEC.json [SPEC.json ...] --report REPORT.json [--parallel N] [--only TEXT ...] [--object-cache DIR] [--timeout S] [--baseline-jobs N] [--mutant-jobs N]

A SPEC is a JSON list of mutants:
  {"name": "R1 grow permits shrink", "file": "runtime/omni_runtime.c", "old": "exact text", "new": "replacement",
   "tests": ["tests/cp04_dynamic_storage.py", "StorageLibraryTests"]}          (`tests`: a suite and, optionally, the unittest classes to run)

Every mutant works in a private copy of the tree; the text must occur at least once (the first occurrence is replaced) or the mutant is reported NOT_APPLIED.
A change under src/ rebuilds the compiler through build_compiler.py --object-cache, so only the changed unit is recompiled; any other change reuses the
baseline compiler and the mutated copy supplies the runtime, libraries and tests. A mutant that does not build, does not apply or crashes the harness is never
reported as killed. KILLED means the suite failed or errored (a FAIL/ERROR line names the test that saw the defect); SURVIVED means it passed; EQUIVALENT is a survivor with an `equivalent` reason in its spec.
A time-out (TIMEOUT) and an exit that names no failing test or ends by a signal (INSTRUMENTAL) are NOT kills: under memory or CPU pressure they prove nothing about the defect, so they count as not killed
and are repeated with --only. `--parallel` limits the mutants in flight; the compiler builds have their own width: `--baseline-jobs` (the reference compiler, default 6) and `--mutant-jobs` (each mutant
of src/, default 2) - on a machine with little memory lower both, not only --parallel.
Only the mutants selected with --only are (re)run and their rows replace the previous ones in the report, which is how one failed or surviving case is repeated
without the others.
"""
from __future__ import annotations
import argparse, concurrent.futures, hashlib, json, os, pathlib, shutil, subprocess, sys, tempfile, time

CORE = pathlib.Path(__file__).resolve().parents[1]
COPY_SKIP = ('bin', 'reference', 'evidence', '__pycache__')


def copy_tree(source: pathlib.Path, destination: pathlib.Path) -> None:
    destination.mkdir(parents=True)
    for entry in source.iterdir():
        if entry.name in COPY_SKIP:
            continue
        if entry.is_dir():
            shutil.copytree(entry, destination / entry.name, ignore=shutil.ignore_patterns('__pycache__'))
        else:
            shutil.copy(entry, destination / entry.name)


def build(root: pathlib.Path, output: pathlib.Path, cache: pathlib.Path, jobs: int) -> tuple[bool, str]:
    done = subprocess.run([sys.executable, '-B', str(root / 'tools/build_compiler.py'), '--output', str(output), '--jobs', str(jobs), '--quiet',
                           '--object-cache', str(cache)], capture_output=True, text=True, cwd=root)
    return done.returncode == 0, done.stderr[-400:]


def verify_baseline(root: pathlib.Path, binary: pathlib.Path, mutants: list[dict], timeout: int) -> dict:
    """Every selected test must pass unmutated before any kill can count."""
    results = []
    env = {**os.environ, 'OMNI_TEST_BIN': str(binary), 'OMNI_HOME': str(root), 'PYTHONDONTWRITEBYTECODE': '1'}
    for tests in sorted({tuple(spec['tests']) for spec in mutants}):
        try:
            done = subprocess.run([sys.executable, '-B', *tests], cwd=root, env=env,
                                  capture_output=True, text=True, timeout=timeout)
            result = {'tests': list(tests), 'returncode': done.returncode, 'status': 'PASS' if done.returncode == 0 else 'FAIL',
                      'output_sha256': hashlib.sha256((done.stdout + done.stderr).encode()).hexdigest(),
                      'output': done.stdout + done.stderr}
        except (OSError, subprocess.TimeoutExpired) as error:
            result = {'tests': list(tests), 'status': 'FAIL', 'error': type(error).__name__}
        results.append(result)
    return {'schema': 'omni.clean-baseline/1', 'result': 'PASS' if all(r['status'] == 'PASS' for r in results) else 'FAIL',
            'compiler_sha256': hashlib.sha256(binary.read_bytes()).hexdigest(), 'suites': results}


def run_one(spec: dict, baseline: pathlib.Path, cache: pathlib.Path, timeout: int, mutant_jobs: int = 2) -> dict:
    started = time.time()
    with tempfile.TemporaryDirectory(prefix='omni-mutant-') as tmp:
        root = pathlib.Path(tmp) / 'core' / 'omni-language'
        copy_tree(CORE, root)
        target = root / spec['file']
        if not target.is_file():
            return {'verdict': 'NOT_APPLIED', 'detail': f'no such file: {spec["file"]}', 'seconds': 0}
        text = target.read_text(encoding='utf-8')
        if spec['old'] not in text:
            return {'verdict': 'NOT_APPLIED', 'detail': 'the text to replace does not occur', 'seconds': 0}
        target.write_text(text.replace(spec['old'], spec['new'], 1), encoding='utf-8')
        binary = baseline
        if spec['file'].startswith('src/'):
            binary = pathlib.Path(tmp) / 'omni'
            ok, error = build(root, binary, cache, mutant_jobs)
            if not ok:
                return {'verdict': 'BUILD_FAILED', 'detail': error, 'seconds': round(time.time() - started)}
        suite, *classes = spec['tests']
        env = {**os.environ, 'OMNI_TEST_BIN': str(binary), 'OMNI_HOME': str(root), 'PYTHONDONTWRITEBYTECODE': '1'}
        try:
            run = subprocess.run([sys.executable, '-B', suite, *classes], cwd=root, env=env, capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            return {'verdict': 'TIMEOUT', 'detail': f'no verdict after {timeout}s: a time-out is not a kill (it may be resource pressure); repeat it', 'seconds': round(time.time() - started)}
        failed = sorted({line.split()[1] for line in run.stderr.splitlines() if line.startswith(('FAIL:', 'ERROR:'))})
        if run.returncode == 0:
            if spec.get('equivalent'):   # a survivor that has been proved to change no behaviour, with the reason; it is reported, never counted as a kill
                return {'verdict': 'EQUIVALENT', 'detail': spec['equivalent'], 'seconds': round(time.time() - started)}
            return {'verdict': 'SURVIVED', 'detail': '', 'seconds': round(time.time() - started)}
        if run.returncode < 0 or not failed:
            tail = ' '.join(run.stderr.strip().splitlines()[-3:])[:200]
            return {'verdict': 'INSTRUMENTAL', 'detail': f'abnormal exit (rc={run.returncode}) that names no failing test: not a kill; {tail}', 'seconds': round(time.time() - started)}
        return {'verdict': 'KILLED', 'detail': ','.join(failed), 'seconds': round(time.time() - started)}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('specs', nargs='+', type=pathlib.Path)
    ap.add_argument('--report', type=pathlib.Path, required=True)
    ap.add_argument('--parallel', type=int, default=3)
    ap.add_argument('--only', nargs='*', default=[])
    ap.add_argument('--object-cache', type=pathlib.Path, default=pathlib.Path(os.environ.get('OMNI_OBJECT_CACHE', pathlib.Path.home() / '.cache/omni-objects')))
    ap.add_argument('--timeout', type=int, default=1500)
    ap.add_argument('--baseline-jobs', type=int, default=6, help='compile jobs of the reference compiler build')
    ap.add_argument('--mutant-jobs', type=int, default=2, help='compile jobs of each mutant of src/')
    args = ap.parse_args()
    mutants = [m for path in args.specs for m in json.loads(path.read_text(encoding='utf-8'))]
    names = [m['name'] for m in mutants]
    if len(set(names)) != len(names):
        ap.error('duplicate mutant names')
    chosen = [m for m in mutants if not args.only or any(item in m['name'] for item in args.only)]
    if not chosen:
        ap.error('no mutant selected')
    args.object_cache.mkdir(parents=True, exist_ok=True)
    baseline = args.object_cache / 'baseline-omni'
    with tempfile.TemporaryDirectory(prefix='omni-baseline-') as tmp:   # unchanged units come from the cache, so this costs a link when nothing changed
        root = pathlib.Path(tmp) / 'core' / 'omni-language'
        copy_tree(CORE, root)
        ok, error = build(root, baseline, args.object_cache, max(1, args.baseline_jobs))
        if not ok:
            print('baseline build failed:', error)
            return 2
        clean = verify_baseline(root, baseline, chosen, args.timeout)
        clean['spec_sha256'] = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in args.specs}
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.with_suffix('.baseline.json').write_text(json.dumps(clean, indent=2), encoding='utf-8')
        print('CLEAN_BASELINE=' + clean['result'], flush=True)
        if clean['result'] != 'PASS':
            print('No mutants started: the unmutated test baseline is red.', flush=True)
            return 2
    results = json.loads(args.report.read_text(encoding='utf-8')) if args.report.exists() else {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.parallel) as pool:
        futures = {pool.submit(run_one, m, baseline, args.object_cache, args.timeout, max(1, args.mutant_jobs)): m for m in chosen}
        for future in concurrent.futures.as_completed(futures):
            name = futures[future]['name']
            results[name] = future.result()
            print(f'{name}: {results[name]["verdict"]} {results[name]["detail"][:110]} ({results[name]["seconds"]}s)', flush=True)
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(json.dumps(results, indent=1, sort_keys=True), encoding='utf-8')
    live = {name: row for name, row in results.items() if name in names}   # rows of mutants that no longer exist in the specs are history, not verdicts
    equivalent = sorted(name for name, row in live.items() if row['verdict'] == 'EQUIVALENT')
    not_killed = {name: row['verdict'] for name, row in live.items() if row['verdict'] not in ('KILLED', 'EQUIVALENT')}
    print('TOTAL', len(live), 'KILLED', sum(row['verdict'] == 'KILLED' for row in live.values()), 'EQUIVALENT', equivalent, 'NOT_KILLED', not_killed)
    return 0 if not not_killed else 1


if __name__ == '__main__':
    raise SystemExit(main())
