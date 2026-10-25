#!/usr/bin/env python3
"""Build the thin N-API addon against the public Host SDK ABI only."""
from __future__ import annotations

import argparse
import pathlib
import subprocess


ROOT = pathlib.Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--runtime-dir', type=pathlib.Path, required=True)
    parser.add_argument('--output', type=pathlib.Path, required=True)
    parser.add_argument('--node-include', type=pathlib.Path, default=pathlib.Path('/usr/include/node'))
    args = parser.parse_args()
    if not (args.runtime_dir / 'libomni_invocation_v1.so').is_file():
        parser.error('--runtime-dir must contain libomni_invocation_v1.so')
    if not (args.node_include / 'node_api.h').is_file():
        parser.error('--node-include must contain node_api.h')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    command = [
        'c++', '-std=c++20', '-O2', '-fPIC', '-shared', '-Wall', '-Wextra',
        '-Wpedantic', '-Werror', '-Wshadow', '-Wconversion', '-Wsign-conversion',
        '-DNODE_GYP_MODULE_NAME=omni_host_sdk', f'-I{args.node_include}',
        f'-I{ROOT / "include"}', str(ROOT / 'bindings/node/omni_host_sdk_node.cpp'),
        f'-L{args.runtime_dir}', '-lomni_invocation_v1', '-Wl,-rpath,$ORIGIN/../runtime',
        '-o', str(args.output),
    ]
    subprocess.run(command, check=True)


if __name__ == '__main__':
    main()
