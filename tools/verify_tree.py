#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Federico T. Begna
# SPDX-License-Identifier: MIT OR Apache-2.0
"""Check the publishable source tree without Git, builds or remote services."""
from __future__ import annotations
import argparse,ast,hashlib,json,os,pathlib,re,sys,tomllib,urllib.parse
ROOT=pathlib.Path(__file__).resolve().parents[1]
IGNORED={'build','dist','bin','.git','.omni-cert','node_modules','__pycache__','.venv'}

def public_files():
    for base,dirs,files in os.walk(ROOT):
        directory=pathlib.Path(base)
        dirs[:]=[d for d in dirs if d not in IGNORED and not (directory==ROOT/'docs' and d=='prompts')]
        for name in files:
            if name.startswith('.env'):continue
            yield directory/name

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--report',type=pathlib.Path);args=ap.parse_args()
    errors=[];files=list(public_files());paths={p.relative_to(ROOT).as_posix() for p in files}
    for required in ('DEVELOPMENT.md','spec/INDEX.md','spec/README.md','examples/README.md','tests/README.md','docs/language/CAPABILITY_STATUS.md','LICENSE-MIT','LICENSE-APACHE','REUSE.toml'):
        if required not in paths:errors.append('missing '+required)
    for prohibited in ('.git','README.md','README.es.md','docs/language/FEATURES.md','src','sdk','core','kernel'):
        if (ROOT/prohibited).exists():errors.append('reserved/unexpected '+prohibited)
    if (ROOT/'VERSION').read_text().strip()!='0.1.0.00':errors.append('product version')
    if json.loads((ROOT/'stdlib/omni.package.json').read_text())['version']!='0.8.4-alpha.8':errors.append('stdlib identity')
    sources=(ROOT/'tools/core_sources.txt').read_text().splitlines()
    if len(sources)!=21 or len(set(sources))!=21:errors.append('compiler must have 21 unique units')
    if len(list((ROOT/'compiler/src').glob('*.cpp')))!=23:errors.append('23 total native C++ units required')
    for path in sources:
        if not path.startswith('compiler/src/') or not (ROOT/path).is_file():errors.append('bad compiler unit '+path)
    secret=re.compile(r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----|gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,}|sk-[A-Za-z0-9]{32,}')
    private=re.compile(r'(?i)\b(?:synphoni|omni[ -]brain|jev|podias?|executionledger|bdel|bcl)\b|sirfederick/omni(?!-lang)|[A-Za-z]:\\(?:dev|Users)\\|/mnt/[a-z]/(?:dev|Users)/')
    manifests=[]
    for p in files:
        rel=p.relative_to(ROOT).as_posix();data=p.read_bytes()
        if p.is_symlink():errors.append('symlink '+rel)
        manifests.append({'path':rel,'sha256':hashlib.sha256(data).hexdigest()})
        try:text=data.decode('utf-8')
        except UnicodeDecodeError:
            if p.suffix not in {'.owire','.onme'}:errors.append('unclassified non-text '+rel)
            continue
        if secret.search(text):errors.append('secret pattern '+rel)
        # This file contains the detection vocabulary, not product references.
        if p.resolve()!=pathlib.Path(__file__).resolve() and private.search(text):errors.append('private reference '+rel)
        if p.suffix=='.py':
            try:ast.parse(text,filename=rel)
            except SyntaxError as e:errors.append(f'Python syntax {rel}: {e}')
        if p.suffix=='.md':
            # Ignore fenced examples; only actual Markdown links are checked.
            prose=re.sub(r'```[\s\S]*?```','',text)
            for target in re.findall(r'(?<!!)\[[^\]\n]+\]\(([^)]+)\)',prose):
                target=target.split(' "',1)[0].strip('<>')
                if re.match(r'\w+://|mailto:|#',target):continue
                path=urllib.parse.unquote(target.split('#',1)[0])
                if path and not (p.parent/path).exists():errors.append(f'broken link {rel}: {target}')
    if (ROOT/'REUSE.toml').exists():
        reuse=tomllib.loads((ROOT/'REUSE.toml').read_text())
        covered={p for row in reuse.get('annotations',[]) for p in row['path']}
        expected=paths-{'LICENSE-MIT','LICENSE-APACHE','REUSE.toml'}
        if expected-covered:errors.append('license annotations missing: '+','.join(sorted(expected-covered)))
        if covered-expected:errors.append('stale license annotations: '+','.join(sorted(covered-expected)))
    report={'schema':'omni.tree-check/1','status':'FAIL' if errors else 'PASS','public_files':len(files),'git_required':False,'checks':['structure','product and stdlib identities','native source list','privacy patterns','secrets patterns','Python syntax','Markdown relative paths','explicit license coverage'],'errors':errors,'files':manifests}
    if args.report:
        args.report.parent.mkdir(parents=True,exist_ok=True);args.report.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({k:v for k,v in report.items() if k!='files'},indent=2));return bool(errors)

if __name__=='__main__':sys.exit(main())
