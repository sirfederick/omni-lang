#!/usr/bin/env python3
"""Build the matching Linux invocation loader and its canonical build identity."""
from __future__ import annotations

import argparse
import hashlib
import os
import pathlib
import shutil
import subprocess
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed

ROOT = pathlib.Path(__file__).resolve().parents[1]
WARN = ['-Wall', '-Wextra', '-Wpedantic', '-Werror', '-Wshadow',
        '-Wconversion', '-Wsign-conversion']
CXX_FLAGS = ['-std=c++20', '-O2', '-fPIC', *WARN]
C_FLAGS = ['-std=c11', '-O2', '-fPIC', '-Wall', '-Wextra', '-Werror']
LINK_FLAGS = ['-shared', '-Wl,-soname,libomni_invocation_v1.so',
              '-lcrypto', '-ldl', '-pthread']


def sources():
    listing = (ROOT / 'tools/core_sources.txt').read_text().splitlines()
    return [ROOT / line.strip() for line in listing
            if line.strip() and not line.lstrip().startswith('#')
            and line.strip() != 'compiler/src/main.cpp']


def identity_inputs(native, runtime):
    """All local build inputs, including headers shared by translation units."""
    headers = [path for directory in ('compiler/src', 'runtime', 'include')
               for suffix in ('*.h', '*.hpp')
               for path in (ROOT / directory).rglob(suffix)]
    return sorted(set([*native, *runtime, *headers,
                       ROOT / 'tools/core_sources.txt',
                       ROOT / 'tools/build_invocation_loader.py']))


def hash_identity_inputs(digest, paths):
    for path in paths:
        name = path.relative_to(ROOT).as_posix().encode()
        content = hashlib.sha256(path.read_bytes()).digest()
        digest.update(len(name).to_bytes(4, 'little') + name + content)


def run(command):
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError(f'{command[0]} failed:\n{result.stdout}{result.stderr}')
    return result.stdout


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=pathlib.Path, required=True)
    parser.add_argument('--jobs', type=int, default=3)
    parser.add_argument('--sanitizers', action='store_true',
                        help='instrument this test build with ASan and UBSan')
    parser.add_argument('--testing', action='store_true',
                        help='build test-only handle fault instrumentation')
    args = parser.parse_args()
    if args.jobs < 1 or args.jobs > 16:
        parser.error('--jobs must be 1..16')
    cxx = os.environ.get('CXX', 'c++')
    cc = os.environ.get('CC', 'clang')
    instrumentation = (['-g1', '-fsanitize=address,undefined',
                        '-fno-omit-frame-pointer'] if args.sanitizers else [])
    cxx_flags = [*CXX_FLAGS, *instrumentation,
                 *(['-DOMNI_INVOCATION_TESTING=1'] if args.testing else [])]
    c_flags = [*C_FLAGS, *instrumentation]
    link_flags = [*LINK_FLAGS, *instrumentation]
    # The public host SDK links to this runtime ABI.  It deliberately is not
    # part of the compiler executable, which has no invocation runtime link.
    native = sources() + [ROOT / 'compiler/src/host_invocation_loader.cpp',
                          ROOT / 'compiler/src/host_sdk_public.cpp']
    runtime = [ROOT / 'runtime/omni_runtime.c',
               ROOT / 'runtime/omni_invocation_codec.c']
    digest = hashlib.sha256(b'omni.module-invoke.runtime-build/1\n')
    hash_identity_inputs(digest, identity_inputs(native, runtime))
    tool_hashes = {}
    for label, command in [('cxx', cxx), ('cc', cc)]:
        resolved = shutil.which(command)
        if resolved is None:
            raise RuntimeError(f'{command} is unavailable')
        tool_hashes[label] = hashlib.sha256(pathlib.Path(resolved).resolve().read_bytes()).digest()
        version = run([command, '--version']).encode()
        digest.update(label.encode() + b'\0' + len(version).to_bytes(4, 'little') + version)
        digest.update(tool_hashes[label])
    for label, flags in [('cxx-flags', cxx_flags), ('c-flags', c_flags),
                         ('link-flags', link_flags)]:
        encoded = label.encode()
        digest.update(len(encoded).to_bytes(4, 'little') + encoded)
        for flag in flags:
            encoded = flag.encode()
            digest.update(len(encoded).to_bytes(4, 'little') + encoded)
    build_id = digest.hexdigest()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='omni-invocation-loader-') as temp:
        temp = pathlib.Path(temp)
        pairs = [(src, temp / f'cpp-{i}.o', cxx,
                  [*cxx_flags, f'-DOMNI_INVOCATION_RUNTIME_BUILD_HEX="{build_id}"'])
                 for i, src in enumerate(native)]
        pairs += [(src, temp / f'c-{i}.o', cc,
                   c_flags)
                  for i, src in enumerate(runtime)]

        def compile_one(pair):
            src, obj, compiler, flags = pair
            run([compiler, *flags, '-c', str(src), '-o', str(obj)])
            return obj

        with ThreadPoolExecutor(max_workers=args.jobs) as pool:
            objects = list(pool.map(compile_one, pairs))
        run([cxx, *link_flags[:2], *map(str, objects), *link_flags[2:],
             '-o', str(args.output)])
    (args.output.parent / 'omni_invocation_build_id.txt').write_text(build_id + '\n')
    (args.output.parent / 'omni_invocation_backend_sha256.txt').write_text(
        tool_hashes['cc'].hex() + '\n')
    print(build_id)


if __name__ == '__main__':
    main()
