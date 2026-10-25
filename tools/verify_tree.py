#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Federico T. Begna
# SPDX-License-Identifier: MIT OR Apache-2.0
"""Validate publishable sources in a checkout, worktree, or source export."""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import pathlib
import re
import sys
import tomllib
import urllib.parse

from build_invocation_loader import SDK_ONLY_SOURCES

ROOT = pathlib.Path(__file__).resolve().parents[1]
IGNORED = {'.git', 'build', 'dist', 'bin', '.omni-cert', 'node_modules', '__pycache__', '.venv'}
PRIVATE_DOCS = {'prompts', 'promts'}
SECRET = re.compile(r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----|gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,}|sk-[A-Za-z0-9]{32,}')
PRIVATE = re.compile(r'(?i)\b(?:synphoni|omni[ -]brain|jev|podias?|executionledger|bdel|bcl)\b|sirfederick/omni(?!-lang)|[A-Za-z]:\\(?:dev|Users)\\|/mnt/[a-z]/(?:dev|Users)/')


def public_files(root=None):
    root = pathlib.Path(root or ROOT)
    for base, directories, files in os.walk(root):
        directory = pathlib.Path(base)
        directories[:] = [name for name in directories if name not in IGNORED
                          and not (directory == root / 'docs' and name in PRIVATE_DOCS)]
        for name in files:
            if name == '.git' or (name.startswith('.env') and name != '.env.example'):
                continue
            yield directory / name


def markdown_anchors(text):
    """GitHub-style IDs for the plain headings used in this repository."""
    anchors = set(re.findall(r'(?:id|name)=["\']([^"\']+)["\']', text))
    counts = {}
    for heading in re.findall(r'^#{1,6}\s+(.+?)\s*#*$', text, re.M):
        slug = re.sub(r'[^\w\- ]', '', heading.lower()).replace(' ', '-')
        index = counts.get(slug, 0)
        counts[slug] = index + 1
        anchors.add(slug if not index else f'{slug}-{index}')
    return anchors


def check_links(path, text):
    prose = re.sub(r'```[\s\S]*?```', '', text)
    targets = re.findall(r'!?\[[^\]\n]+\]\(([^)]+)\)', prose)
    targets += re.findall(r'(?:href|src)=["\']([^"\']+)["\']', prose)
    errors = []
    for target in targets:
        target = target.split(' "', 1)[0].strip('<>')
        if re.match(r'\w+://|mailto:', target):
            continue
        relative, _, fragment = urllib.parse.unquote(target).partition('#')
        destination = path.parent / relative if relative else path
        if not destination.exists():
            errors.append(f'broken link {path.name}: {target}')
        elif fragment and destination.suffix == '.md':
            content = text if destination == path else destination.read_text(encoding='utf-8')
            if fragment not in markdown_anchors(content):
                errors.append(f'broken anchor {path.name}: {target}')
    return errors


def check_sources(root):
    errors = []
    sources = [line.strip() for line in (root / 'tools/core_sources.txt').read_text(encoding='utf-8').splitlines()
               if line.strip() and not line.lstrip().startswith('#')]
    if not sources or len(set(sources)) != len(sources):
        errors.append('canonical compiler sources must be nonempty and unique')
    if 'compiler/src/main.cpp' not in sources:
        errors.append('compiler CLI entry missing from canonical sources')
    if set(sources) & set(SDK_ONLY_SOURCES):
        errors.append('SDK-only unit included in compiler executable')
    for relative in [*sources, *SDK_ONLY_SOURCES]:
        path = pathlib.PurePosixPath(relative)
        if (path.is_absolute() or '..' in path.parts or not relative.startswith('compiler/src/')
                or path.suffix != '.cpp' or not (root / relative).is_file()):
            errors.append('bad native unit ' + relative)
    actual = {p.relative_to(root).as_posix() for p in (root / 'compiler/src').rglob('*.cpp')}
    unlisted = actual - set(sources) - set(SDK_ONLY_SOURCES)
    if unlisted:
        errors.append('native units lack compiler/SDK responsibility: ' + ','.join(sorted(unlisted)))
    return errors


def verify(root=None):
    root = pathlib.Path(root or ROOT)
    files = list(public_files(root))
    paths = {p.relative_to(root).as_posix() for p in files}
    errors = []
    required = ('README.md', 'DEVELOPMENT.md', 'spec/INDEX.md', 'spec/README.md', 'examples/README.md',
                'tests/README.md', 'docs/language/CAPABILITY_STATUS.md', 'LICENSE-MIT', 'LICENSE-APACHE', 'REUSE.toml')
    errors += ['missing ' + name for name in required if name not in paths]
    try:
        version = (root / 'VERSION').read_text(encoding='utf-8').strip()
        if not re.fullmatch(r'\d+\.\d+\.\d+\.\d+', version):
            errors.append('invalid product version')
        stdlib = json.loads((root / 'stdlib/omni.package.json').read_text(encoding='utf-8'))
        if stdlib.get('name') != 'omni.std' or not stdlib.get('version'):
            errors.append('invalid independent stdlib identity')
        errors += check_sources(root)
    except (OSError, ValueError) as error:
        errors.append('source configuration: ' + str(error))
    manifest = []
    for path in files:
        relative = path.relative_to(root).as_posix()
        if path.is_symlink():
            errors.append('symlink ' + relative)
            continue
        data = path.read_bytes()
        manifest.append({'path': relative, 'sha256': hashlib.sha256(data).hexdigest()})
        try:
            text = data.decode('utf-8')
        except UnicodeDecodeError:
            # Immutable binary representation fixtures have their own readers
            # and semantic tests; text scans cannot interpret their payloads.
            if path.suffix not in {'.owire', '.onme'}:
                errors.append('unclassified non-text ' + relative)
            continue
        if SECRET.search(text):
            errors.append('secret pattern ' + relative)
        # Detection vocabulary is expected only in this implementation itself.
        if relative != 'tools/verify_tree.py' and PRIVATE.search(text):
            errors.append('private reference ' + relative)
        if path.suffix == '.py':
            try:
                ast.parse(text, filename=relative)
            except SyntaxError as error:
                errors.append(f'Python syntax {relative}: {error}')
        if path.suffix == '.md':
            errors += check_links(path, text)
    try:
        reuse = tomllib.loads((root / 'REUSE.toml').read_text(encoding='utf-8'))
        covered = {name for row in reuse.get('annotations', []) for name in row['path']}
        expected = paths - {'LICENSE-MIT', 'LICENSE-APACHE', 'REUSE.toml'}
        if expected - covered:
            errors.append('license annotations missing: ' + ','.join(sorted(expected - covered)))
        if covered - expected:
            errors.append('stale license annotations: ' + ','.join(sorted(covered - expected)))
    except (OSError, ValueError) as error:
        errors.append('license configuration: ' + str(error))
    return {'schema': 'omni.tree-check/1', 'status': 'FAIL' if errors else 'PASS',
            'public_files': len(files), 'git_required': False, 'errors': errors, 'files': manifest}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=pathlib.Path, default=ROOT)
    parser.add_argument('--report', type=pathlib.Path)
    args = parser.parse_args(argv)
    report = verify(args.root)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({key: value for key, value in report.items() if key != 'files'}, indent=2))
    return report['status'] != 'PASS'


if __name__ == '__main__':
    sys.exit(main())
