#!/usr/bin/env python3
"""CP-08 row 8.3 / MN-08 (spec/RAW_BOUNDARY_CANDIDATE.md): the raw boundary is formal, localized and visible.

FORMAL      every operation that leaves the language's guarantees (raw memory, atomics, I/O ports, CPU control, system gates) belongs to ONE capability of the registry; without it the program does not
            compile (E_CAPABILITY, naming the capability), and with exactly it the program checks. The catalogue is the table below and the one in the specification: operation -> capability.
LOCALIZED   `omni capabilities` separates what a function does ITSELF (`direct_required`) from what it only reaches through a call (`required`): the boundary is the set of functions whose direct
            list names a raw capability, and a caller of such a function is not part of it. A function that declares a capability it never needs is reported as `excess`.
VISIBLE     the same fact is in the registry (`omni capability registry`: category target-*, risk critical, not delegable, not serializable): authority never leaves the program.
"""
from __future__ import annotations
import json
import unittest
from cp02_borrowed_containers import ContainerCase
from language_0_8_3_alpha8 import OMNI, proc

W = 'struct W { v u32 }\n'

#            label                              snippet                                                              capabilities that make it compile (and only them)
CATALOGUE = [
    ('raw.load8',          '  let v u32 = raw.load8(4096u64)\n',                                          ['memory.raw']),
    ('raw.load32',         '  let v u32 = raw.load32(4096u64)\n',                                         ['memory.raw']),
    ('raw.load64',         '  let v u64 = raw.load64(4096u64)\n',                                         ['memory.raw']),
    ('raw.store8',         '  let v u32 = raw.store8(4096u64, 1u32)\n',                                   ['memory.raw']),
    ('raw.store32',        '  let v u32 = raw.store32(4096u64, 1u32)\n',                                  ['memory.raw']),
    ('raw.store64',        '  let v u32 = raw.store64(4096u64, 1u64)\n',                                  ['memory.raw']),
    ('raw.read<R>',        '  let v W = raw.read<W>(4096u64)\n',                                          ['memory.raw']),
    ('raw.write<R>',       '  let v u32 = raw.write<W>(4096u64, W { v: 1u32 })\n',                        ['memory.raw']),
    ('atomic.load32',      '  let v u32 = atomic.load32(4096u64, 4u32)\n',                                ['memory.atomic']),
    ('atomic.store32',     '  let v u32 = atomic.store32(4096u64, 1u32, 4u32)\n',                         ['memory.atomic']),
    ('atomic.fetch_add32', '  let v u32 = atomic.fetch_add32(4096u64, 1u32, 4u32)\n',                     ['memory.atomic']),
    ('port.in8',           '  let v u32 = port.in8(96u32)\n',                                             ['port.io']),
    ('port.out32',         '  let v u32 = port.out32(244u32, 1u32)\n',                                    ['port.io']),
    ('cpu.cpuid',          '  let v u32 = cpu.cpuid(1u32, 1u32)\n',                                       ['cpu.control']),
    ('cpu.read_cr64',      '  let v u64 = cpu.read_cr64(2u32)\n',                                         ['cpu.control']),
    ('cpu.trap3',          '  let v u64 = cpu.trap3(40u32, 0u64, 0u64, 0u64)\n',                          ['cpu.syscall']),
]


class RawBoundaryTests(ContainerCase):
    def source(self, text, name='program.omni'):
        path = self.dir / name
        path.write_text('module t\n' + text, encoding='utf-8')
        return path

    def test_every_raw_operation_needs_its_capability_and_only_that_one(self):
        for label, snippet, caps in CATALOGUE:
            with self.subTest(label):
                bare = proc(OMNI, 'check', self.source(W + 'func main() u32 {\n' + snippet + '  return 0u32\n}\n', 'bare.omni'))
                self.assertEqual(bare.returncode, 2, (label, bare.stderr))
                self.assertIn(b'E_CAPABILITY', bare.stderr, label)
                self.assertTrue(any(c.encode() in bare.stderr for c in caps), (label, bare.stderr))
                granted = proc(OMNI, 'check', self.source(W + 'func main() u32 !{%s} {\n' % ','.join(caps) + snippet + '  return 0u32\n}\n', 'granted.omni'))
                self.assertEqual(granted.returncode, 0, (label, granted.stderr))
                # a capability that is not the one of the operation does not make it compile
                for other in ('memory.raw', 'memory.atomic', 'port.io', 'cpu.control', 'cpu.syscall'):
                    if other in caps:
                        continue
                    wrong = proc(OMNI, 'check', self.source(W + 'func main() u32 !{%s} {\n' % other + snippet + '  return 0u32\n}\n', 'wrong.omni'))
                    self.assertEqual(wrong.returncode, 2, (label, other, wrong.stderr))
                    self.assertIn(b'E_CAPABILITY', wrong.stderr, (label, other))

    def test_the_boundary_is_the_set_of_functions_that_do_the_raw_operation_themselves(self):
        path = self.source(
            W + 'func touch() u32 !{memory.raw} { return raw.load8(4096u64) }\n'
            'func relay() u32 !{memory.raw} { return touch() }\n'
            'func pure_helper(x u32) u32 { return x + 1u32 }\n'
            'func over() u32 !{memory.raw,port.io} { return raw.load8(4096u64) }\n'
            'func main() u32 !{memory.raw,port.io} { return relay() + pure_helper(over()) }\n')
        done = proc(OMNI, 'capabilities', path)
        self.assertEqual(done.returncode, 0, done.stderr)
        report = {f['function']: f for f in json.loads(done.stdout)['functions']}
        raw_classes = {'memory.raw', 'memory.atomic', 'memory.tls', 'memory.pcpu', 'port.io', 'cpu.control', 'cpu.syscall'}
        boundary = sorted(k for k, f in report.items() if raw_classes & set(f['direct_required']))
        self.assertEqual(boundary, ['t.over', 't.touch'])
        self.assertEqual(report['t.touch']['direct_required'], ['memory.raw'])
        self.assertEqual(report['t.relay']['direct_required'], [])           # it reaches the boundary through a call; it is not part of it
        self.assertEqual(report['t.relay']['required'], ['memory.raw'])
        self.assertEqual(report['t.main']['direct_required'], [])
        self.assertEqual(report['t.pure_helper']['required'], [])
        self.assertEqual(report['t.over']['excess'], ['port.io'])            # an authority the function declares and never uses is visible too

    def test_the_registry_marks_raw_authority_as_critical_local_and_not_delegable(self):
        done = proc(OMNI, 'capability', 'registry')
        self.assertEqual(done.returncode, 0, done.stderr)
        registry = {c['id']: c for c in json.loads(done.stdout)['capabilities']}
        for cap in ('memory.raw', 'memory.atomic', 'port.io', 'cpu.control'):
            entry = registry[cap]
            self.assertEqual(entry['risk_class'], 'critical', cap)
            self.assertFalse(entry['delegable'], cap)
            self.assertFalse(entry['serializable'], cap)
            self.assertTrue(entry['category'].startswith('target-'), cap)


if __name__ == '__main__':
    unittest.main()
