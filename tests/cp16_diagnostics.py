#!/usr/bin/env python3
"""CP-16.2: the catalog of diagnostics agrees with EVERY producer, not only with the lines of the compiler that happen to say `fail(`.

A producer is any file that can print a code to a user: the compiler sources and headers, the C runtime of a compiled program, the public headers and the Python tools. A code that a producer names and the
catalog (`omni diagnostics`) does not is a defect; the set of known gaps is empty and may only grow by an explicit, reviewed decision. The categories are part of the surface of `omni.diagnostic/1`: a user-facing
fault must not say `internal`."""
from __future__ import annotations
import json
import os
import pathlib
import re
import subprocess
import tempfile
import unittest
from language_0_8_3_alpha8 import ROOT, OMNI

PRODUCERS = ('src/*.cpp', 'src/*.hpp', 'runtime/*.c', 'runtime/*.h', 'include/**/*.h', 'include/**/*.hpp', 'tools/*.py')
# a code as a literal (`"E_X"`, `'E_X'`) or at the start of a printed message (`"E_X: ...`)
LITERAL = re.compile(r"""['"](E_[A-Z][A-Z0-9_]*[A-Z0-9])(?:['"]|:)""")
# `code.rfind("E_RESULT",0)==0` tests a PREFIX of a family; it names no code
PREFIX = re.compile(r'rfind\(\s*"E_[A-Z0-9_]+"\s*,\s*0\s*\)')
KNOWN_UNREGISTERED: frozenset[str] = frozenset()
CATEGORIES = {'lexical', 'syntax', 'flow', 'names', 'types', 'memory-resource', 'capability', 'representation', 'toolchain', 'runtime', 'tooling', 'internal'}


def catalog() -> dict[str, str]:
    done = subprocess.run([str(OMNI), 'diagnostics'], capture_output=True, env={**os.environ, 'OMNI_HOME': str(ROOT)})
    return {entry['code']: entry['category'] for entry in json.loads(done.stdout)['codes']}


def produced() -> dict[str, list[str]]:
    found: dict[str, list[str]] = {}
    for pattern in PRODUCERS:
        for path in sorted(ROOT.glob(pattern)):
            for number, line in enumerate(path.read_text(encoding='utf-8', errors='replace').splitlines(), 1):
                for code in LITERAL.findall(PREFIX.sub('', line)):
                    found.setdefault(code, []).append('%s:%d' % (path.relative_to(ROOT), number))
    return found


class CatalogAgreesWithProducersTests(unittest.TestCase):
    def test_every_code_a_producer_names_is_in_the_catalog(self):
        registry = set(catalog())
        emitted = produced()
        missing = {code: where[:2] for code, where in emitted.items() if code not in registry and code not in KNOWN_UNREGISTERED}
        self.assertEqual(missing, {}, 'a producer names a code the catalog does not have')
        self.assertEqual({c for c in KNOWN_UNREGISTERED if c in registry or c not in emitted}, set(), 'ratchet: delete the known gaps that are closed')
        self.assertGreater(len(emitted), 150)            # the scan really reads the producers

    def test_the_scan_covers_the_files_that_were_outside_the_previous_ratchet(self):
        files = {w.split(':')[0] for where in produced().values() for w in where}
        for expected in ('compiler/src/omni.hpp', 'compiler/src/main.cpp', 'runtime/omni_runtime.c'):
            self.assertIn(expected, files)

    def test_the_catalog_is_free_of_duplicates_and_every_category_is_known(self):
        done = subprocess.run([str(OMNI), 'diagnostics'], capture_output=True, env={**os.environ, 'OMNI_HOME': str(ROOT)})
        codes = [entry['code'] for entry in json.loads(done.stdout)['codes']]
        self.assertEqual(len(codes), len(set(codes)))
        self.assertTrue(set(catalog().values()) <= CATEGORIES)
        delta = json.loads((ROOT / 'spec/CORE_1_3_0_0_PUBLIC_DELTA_CANDIDATE.json').read_text())['diagnostics']
        self.assertEqual(delta['count_to'], len(codes), 'published diagnostic count must match the real registry')
        self.assertEqual(delta['count_from'] + len(delta['added_codes']) - len(delta['removed_codes']), delta['count_to'])

    def test_a_user_facing_fault_does_not_say_internal(self):
        by = catalog()
        internal = {code for code, category in by.items() if category == 'internal'}
        self.assertEqual(internal, {'E_INTERNAL', 'E_GENERIC_INTERNAL', 'E_INTERNAL_OR_IO'})
        pinned = {'E_CALL': 'names', 'E_BUDGET': 'tooling', 'E_ONME': 'representation', 'E_OSNMF': 'representation', 'E_EPOCH': 'tooling', 'E_QUERY': 'tooling', 'E_COGNITION': 'tooling',
                  'E_MEMORY': 'runtime', 'E_IO': 'runtime', 'E_RUNTIME_REENTRY': 'runtime', 'E_INVOCATION_DEADLINE': 'runtime', 'E_BYTES_HANDLE': 'runtime', 'E_CHANNEL_OUT': 'runtime'}
        self.assertEqual({code: by.get(code) for code in pinned}, pinned)


class ExhaustedBudgetIsAStructuredDiagnosticTests(unittest.TestCase):
    def test_the_json_diagnostic_of_an_exhausted_budget_is_in_the_catalog_with_its_category(self):
        with tempfile.TemporaryDirectory(prefix='omni-cp16-') as tmp:
            src = pathlib.Path(tmp) / 'big.omni'
            src.write_text('module t\n' + ''.join('struct S%d { a u32, b u64 }\nfunc w%d(x u32) u32 { return x + %du32 }\n' % (i, i, i % 7) for i in range(3000)) + 'func main() u32 { return w0(1u32) }\n')
            done = subprocess.run([str(OMNI), 'check', str(src), '--diagnostic-format', 'json'], capture_output=True, env={**os.environ, 'OMNI_HOME': str(ROOT), 'OMNI_MEMORY_MIB': '2'})
            self.assertEqual(done.returncode, 2, done.stderr[-300:])
            diagnostic = json.loads(done.stderr)
            self.assertEqual(diagnostic['schema'], 'omni.diagnostic/1')
            self.assertEqual(diagnostic['code'], 'E_BUDGET')
            self.assertEqual(diagnostic['category'], 'tooling')
            self.assertIn('OMNI_MEMORY_MIB', diagnostic['message'])
            self.assertIn(diagnostic['code'], catalog())


if __name__ == '__main__':
    unittest.main()
