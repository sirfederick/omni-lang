#!/usr/bin/env python3
"""CP-15 scale: the compiler has no count or size limit inherited from an earlier version (Adenda 015E).

What bounds a program is the memory budget of the host (E_BUDGET, with figures), the width of a representation (an enum tag is one byte) and the structural depths. Every valid program that the checker accepts must
read back with the same semantics from Particle, Wave, Wire and ONME: the old counts were applied per layer, so a program could be written that could not be read."""
from __future__ import annotations
import json
import os
import pathlib
import shutil
import subprocess
import unittest
from cp15_projection import Case
from language_0_8_3_alpha8 import ROOT, OMNI


def run(*args, env=None, timeout=300):
    return subprocess.run([str(x) for x in args], capture_output=True, timeout=timeout, env={**os.environ, 'OMNI_HOME': str(ROOT), **(env or {})})


class ScaleCase(Case):
    def ok(self, *args, env=None) -> bytes:
        done = run(OMNI, *args, env=env)
        self.assertEqual(done.returncode, 0, (args[:2], done.stderr[-300:]))
        return done.stdout

    def reads_back_everywhere(self, src: pathlib.Path, label: str):
        """The program's own result and its OSNMF store are the same from every representation it can be written in."""
        reference = self.ok('memory', src)
        ident = json.loads(self.ok('manifest', src))['program_content_id']
        forms = {}
        forms['wave'] = self.dir / (label + '.owave')
        forms['wave'].write_bytes(self.ok('wave', src))
        forms['wire'] = self.dir / (label + '.owire')
        self.ok('pack', src, '-o', forms['wire'])
        forms['onme'] = self.dir / (label + '.onme')
        self.ok('onme', src, '-o', forms['onme'])
        for name, path in forms.items():
            done = run(OMNI, 'check', path)
            self.assertEqual(done.returncode, 0, (label, name, done.stderr[-300:]))
            self.assertEqual(self.ok('memory', path), reference, (label, name))
            self.assertEqual(json.loads(self.ok('manifest', path))['program_content_id'], ident, (label, name))
        return forms


class DeclarationsAreNotCountedTests(ScaleCase):
    def test_traits_impls_static_asserts_and_thread_locals_over_several_modules_read_back_everywhere(self):
        # F-1: these four were counted over the whole text of a capsule, so the source file passed and its Wave and Wire could not be read. Every number is above the old per-module limit.
        modules = 3
        for m in range(modules):
            parts = ['module m%d\n' % m]
            if m == 0:
                parts.append('pub func id<T>(x T) T { return x }\n')            # a generic function makes the program an authoring capsule (Wave22/OMC22) in every representation
            parts += ['trait Tr%d { func f(x Self) u32 }\n' % i for i in range(140)]
            parts += ['static_assert(1u32 == 1u32, "a%d")\n' % i for i in range(300)]
            parts += ['thread_local tl%d u32 = 0u32\n' % i for i in range(70)]
            parts += ['struct Q%d { a u32 }\nimpl Tr0 for Q%d { func f(x Q%d) u32 { return x.a } }\n' % (i, i, i) for i in range(280)]
            parts.append('pub func v() u32 { return %du32 }\n' % (m + 1))
            (self.dir / ('m%d.omni' % m)).write_text(''.join(parts), encoding='utf-8')
        src = self.source('app', 'module app\n' + ''.join('import m%d "m%d.omni"\n' % (m, m) for m in range(modules)) + 'func main() u32 { return m0.v() + m1.v() + m2.v() }\n')
        done = run(OMNI, 'eval', src)
        self.assertEqual(done.returncode, 6, done.stderr[-300:])
        self.reads_back_everywhere(src, 'f1')

    def test_a_non_capsule_program_with_thread_locals_and_linkage_over_several_modules_reads_back(self):
        # the Wire sections TLS1 and LNK1 belong to the whole program; they used the limit of one module
        modules = 6
        for m in range(modules):
            body = 'module t%d\n' % m + ''.join('thread_local tl%d u32 = 0u32\n' % i for i in range(40))
            body += ''.join('export "sym_%d_%d" func e%d() u32 { return %du32 }\n' % (m, i, i, i % 7) for i in range(60))
            body += 'pub func v() u32 { return %du32 }\n' % m
            (self.dir / ('t%d.omni' % m)).write_text(body, encoding='utf-8')
        src = self.source('app', 'module app\n' + ''.join('import t%d "t%d.omni"\n' % (m, m) for m in range(modules)) + 'func main() u32 { return t5.v() }\n')
        self.assertEqual(run(OMNI, 'eval', src).returncode, 5)
        self.reads_back_everywhere(src, 'tls')

    def test_a_module_may_have_more_functions_structs_enums_and_generics_than_the_old_limits_and_all_of_them_read_back(self):
        parts = ['module t\n']
        parts += ['pub struct S%d { a u32 }\n' % i for i in range(300)]
        parts += ['pub enum E%d { A, B }\n' % i for i in range(300)]
        parts += ['pub struct Box%d<T> { v T }\n' % i for i in range(80)]
        parts += ['pub enum Pick%d<T> { A(T), B }\n' % i for i in range(80)]
        parts += ['pub func g%d<T>(x T) T { return x }\n' % i for i in range(150)]
        parts += ['pub func h%d() u32 { return %du32 }\n' % (i, i % 5) for i in range(600)]
        parts.append('func main() u32 { return h599() + h1() }\n')
        src = self.source('big', ''.join(parts))
        self.assertEqual(run(OMNI, 'eval', src).returncode, 5)           # 599 % 5 == 4, 1 % 5 == 1
        self.reads_back_everywhere(src, 'big')

    def test_more_generic_specializations_than_the_old_limit_are_generated_and_read_back(self):
        count = 300
        parts = ['module t\nfunc id<T>(x T) T { return x }\n']
        parts += ['struct P%d { a u32 }\n' % i for i in range(count)]
        parts.append('func main() u32 {\n  var s u32 = 0u32\n')
        parts += ['  let r%d P%d = id<P%d>(P%d { a: %du32 })\n  s = s + r%d.a\n' % (i, i, i, i, i % 3, i) for i in range(count)]
        parts.append('  return s\n}\n')
        src = self.source('spec', ''.join(parts))
        self.assertEqual(run(OMNI, 'eval', src).returncode, (sum(i % 3 for i in range(count))) % 256)
        self.reads_back_everywhere(src, 'spec')

    def test_a_project_of_more_modules_than_the_old_limit_reads_back(self):
        count = 300
        for m in range(count):
            (self.dir / ('b%d.omni' % m)).write_text('module b%d\npub func q() u32 { return %du32 }\n' % (m, m % 9), encoding='utf-8')
        src = self.source('app', 'module app\n' + ''.join('import b%d "b%d.omni"\n' % (m, m) for m in range(count)) + 'func main() u32 { return b0.q() + b299.q() }\n')
        self.assertEqual(run(OMNI, 'eval', src).returncode, 0 + 299 % 9)
        self.reads_back_everywhere(src, 'mods')

    def test_two_files_that_declare_the_same_module_are_refused(self):
        (self.dir / 'a.omni').write_text('module dup\npub func f() u32 { return 1u32 }\n', encoding='utf-8')
        (self.dir / 'b.omni').write_text('module dup\npub func g() u32 { return 2u32 }\n', encoding='utf-8')
        src = self.source('app', 'module app\nimport a "a.omni"\nimport b "b.omni"\nfunc main() u32 { return a.f() }\n')
        done = run(OMNI, 'check', src)
        self.assertEqual(done.returncode, 2, done.stderr[-300:])
        self.assertIn(b'E_DUPLICATE', done.stderr)
        self.assertIn(b'dos archivos declaran el mismo modulo', done.stderr)      # the loader names it; the checker would only say that a module is duplicated

    def test_a_source_file_over_100000_tokens_and_over_1_mib_is_checked_and_evaluated(self):
        statements = 75000
        text = 'module t\nfunc main() u32 {\n  var s u32 = 0u32\n' + '  s = s + 1u32\n' * statements + '  return s\n}\n'
        self.assertGreater(len(text.encode()), 1024 * 1024)
        src = self.source('long', text)
        self.assertEqual(run(OMNI, 'check', src).returncode, 0)
        self.assertEqual(run(OMNI, 'eval', src, timeout=600).returncode, statements % 256)

    def test_a_function_with_more_than_256_locals_and_an_aggregate_of_more_than_1024_slots_reads_back(self):
        # the checker's flat-slot model refused both (256 locals, 1024 slots per aggregate, 4096 per frame) and no specification said so
        locals_ = 600
        text = 'module t\n' + 'func main() u32 {\n' + ''.join('  let a%d u32 = %du32\n' % (i, i % 3) for i in range(locals_)) + '  return a0 + a%d\n}\n' % (locals_ - 1)
        src = self.source('locals', text)
        self.assertEqual(run(OMNI, 'eval', src).returncode, (locals_ - 1) % 3)
        self.reads_back_everywhere(src, 'locals')
        fields = 1500
        wide = 'module t\nstruct Wide { %s }\nfunc main() u32 { let w = Wide { %s }\n  return w.x%d }\n' % (', '.join('x%d u32' % i for i in range(fields)), ', '.join('x%d: %du32' % (i, i % 90) for i in range(fields)), fields - 1)
        src = self.source('wide', wide)
        self.assertEqual(run(OMNI, 'eval', src).returncode, (fields - 1) % 90)
        self.reads_back_everywhere(src, 'wide')


class WidthsOfARepresentationTests(ScaleCase):
    def test_an_enum_has_up_to_256_variants_because_its_tag_is_one_byte(self):
        def enum(n):
            arms = ' '.join('V%d { return %du32 }' % (i, (i % 200) + 2) for i in range(1, n))
            return 'module t\nenum Big { %s }\nfunc pick() Big { return Big.V%d() }\nfunc main() u32 { let b = pick()\n  match b { V0 { return 1u32 } %s } }\n' % (', '.join('V%d' % i for i in range(n)), n - 1, arms)
        for n in (65, 255, 256):
            with self.subTest(variants=n):
                src = self.source('enum%d' % n, enum(n))
                self.assertEqual(run(OMNI, 'check', src).returncode, 0)
                self.assertEqual(run(OMNI, 'eval', src).returncode, ((n - 1) % 200 + 2) % 256)
                out = self.dir / ('enum%d.ll' % n)
                self.ok('emit-llvm', src, '-o', out)
                self.assertIn('switch i8', out.read_text())
                self.reads_back_everywhere(src, 'enum%d' % n)
        refused = run(OMNI, 'check', self.source('enum257', enum(257)))
        self.assertEqual(refused.returncode, 2)
        self.assertIn(b'E_LIMIT', refused.stderr)
        self.assertIn('un byte'.encode(), refused.stderr)

    def test_a_forged_wave_or_wire_with_257_variants_is_refused_by_each_reader_for_the_width_of_the_tag(self):
        def enum(n):
            arms = ' '.join('V%d { return %du32 }' % (i, (i % 200) + 2) for i in range(1, n))
            return 'module t\nenum Big { %s }\nfunc pick() Big { return Big.V%d() }\nfunc main() u32 { let b = pick()\n  match b { V0 { return 1u32 } %s } }\n' % (', '.join('V%d' % i for i in range(n)), n - 1, arms)
        src = self.source('e256', enum(256))
        wave = self.ok('wave', src).decode()
        self.assertEqual(wave.count('(V255)'), 1)
        forged = self.dir / 'e257.owave'
        forged.write_text(wave.replace('(V255)', '(V255) (V256)', 1))
        done = run(OMNI, 'check', forged)
        self.assertEqual(done.returncode, 2, done.stderr[-300:])
        self.assertIn(b'E_MATCH', done.stderr)
        self.assertIn(b'1..256', done.stderr)              # the checker's bound, not an arm that is missing
        packed = self.dir / 'e256.owire'
        self.ok('pack', src, '-o', packed)
        blob = packed.read_bytes()
        head = (3).to_bytes(4, 'little') + b'Big'
        at = blob.index(head) + len(head) + 1                # the flag, then the count of variants
        self.assertEqual(int.from_bytes(blob[at:at + 4], 'little'), 256)
        end = at + 4
        for i in range(256):
            end += 4 + len('V%d' % i) + 1
        entry = (4).to_bytes(4, 'little') + b'V256' + b'\x00'
        wire = self.dir / 'e257.owire'
        wire.write_bytes(blob[:at] + (257).to_bytes(4, 'little') + blob[at + 4:end] + entry + blob[end:])
        done = run(OMNI, 'check', wire)
        self.assertEqual(done.returncode, 2, done.stderr[-300:])
        self.assertIn(b'E_LIMIT', done.stderr)

    def test_fields_parameters_arguments_and_match_arms_have_no_count_limit(self):
        n = 300
        fields = 'module t\nstruct Wide { %s }\nfunc main() u32 { let w = Wide { %s }\n  return w.x%d }\n' % (', '.join('x%d u32' % i for i in range(n)), ', '.join('x%d: %du32' % (i, i % 100) for i in range(n)), n - 1)
        params = 'module t\nfunc f(%s) u32 { return a0 + a%d }\nfunc main() u32 { return f(%s) }\n' % (', '.join('a%d u32' % i for i in range(n)), n - 1, ', '.join('%du32' % (i % 3) for i in range(n)))
        for label, text, want in (('fields', fields, (n - 1) % 100), ('params', params, (n - 1) % 3)):
            with self.subTest(shape=label):
                src = self.source(label, text)
                self.assertEqual(run(OMNI, 'eval', src).returncode, want)
                self.ok('emit-llvm', src, '-o', self.dir / (label + '.ll'))
                self.reads_back_everywhere(src, label)


class BudgetTests(ScaleCase):
    """A hostile or merely enormous input ends in E_BUDGET, with the figures and how to change them; it leaves no artifact and it is never the kernel's OOM killer."""

    def big_source(self, name: str, structs: int) -> pathlib.Path:
        return self.source(name, 'module t\n' + ''.join('struct S%d { a u32, b u64, c u8, d u32 }\nfunc w%d(x u32) u32 { return x + %du32 }\n' % (i, i, i % 7) for i in range(structs)) + 'func main() u32 { return w0(1u32) }\n')

    def test_a_small_budget_refuses_with_figures_and_a_large_one_accepts_the_same_input(self):
        src = self.big_source('big', 20000)
        small = run(OMNI, 'check', src, env={'OMNI_MEMORY_MIB': '24'})
        self.assertEqual(small.returncode, 2, small.stderr[-300:])
        self.assertIn(b'E_BUDGET', small.stderr)
        self.assertIn(b'OMNI_MEMORY_MIB', small.stderr)
        self.assertIn(b'MiB', small.stderr)
        for value in ('2048', 'unlimited'):
            with self.subTest(budget=value):
                self.assertEqual(run(OMNI, 'check', src, env={'OMNI_MEMORY_MIB': value}).returncode, 0)

    def test_the_ceiling_is_exact_the_heap_never_passes_the_budget(self):
        # The heap is counted exactly and the compiler is single-threaded, so the peak measured with an unlimited budget is the peak of the run with any other budget.
        # A budget of that peak plus one MiB admits the run; a budget one MiB below refuses it: there is no tolerance between the two.
        import re
        src = self.big_source('calibrated', 20000)
        measured = run(OMNI, 'check', src, env={'OMNI_RESOURCE_REPORT': '1', 'OMNI_MEMORY_MIB': 'unlimited'})
        self.assertEqual(measured.returncode, 0)
        found = re.search(r'heap_peak_mib=(\d+) .* counting=(yes|no)', measured.stderr.decode())
        self.assertIsNotNone(found, measured.stderr)
        if found.group(2) != 'yes':
            self.skipTest('this build does not count the heap (sanitizer build): the budget is checked against the resident set')
        peak = int(found.group(1))
        self.assertGreater(peak, 64)
        for budget, accepted in ((peak + 1, True), (peak - 1, False), (peak * 99 // 100, False)):
            with self.subTest(budget_mib=budget, peak_mib=peak):
                done = run(OMNI, 'check', src, env={'OMNI_MEMORY_MIB': str(budget)})
                if accepted:
                    self.assertEqual(done.returncode, 0, done.stderr[-300:])
                else:
                    self.assertEqual(done.returncode, 2, done.stderr[-300:])
                    self.assertIn(b'E_BUDGET', done.stderr)
                    self.assertIn(b'cerca de', done.stderr)                       # where the allocator was: the last checkpoint passed
                    self.assertIn(('presupuesto %d MiB' % budget).encode(), done.stderr)

    def test_the_allocator_itself_refuses_what_a_phase_without_a_checkpoint_would_allocate(self):
        # Reading a Wire copies the file into a byte vector: no checkpoint lies between the read (which fits the budget) and the copy (which does not). Only the allocator can stop it.
        wire = self.dir / 'junk.owire'
        wire.write_bytes(b'OMCX' + (7).to_bytes(4, 'little') + b'\x00' * (40 * 1024 * 1024))
        done = run(OMNI, 'check', wire, env={'OMNI_MEMORY_MIB': '48'}, timeout=120)
        self.assertEqual(done.returncode, 2, done.stderr[-300:])
        self.assertIn(b'E_BUDGET', done.stderr)
        self.assertIn('la memoria se agoto'.encode(), done.stderr)
        self.assertNotIn(b'bad_alloc', done.stderr)

    def test_the_automatic_budget_follows_what_the_host_reports_and_an_explicit_one_replaces_it(self):
        # No percentage and no ceiling of the compiler: in the automatic mode the allocator refuses what the host says it cannot provide. OMNI_HOST_MEMORY_MIB stands for that report.
        import re
        src = self.big_source('auto', 20000)
        measured = run(OMNI, 'check', src, env={'OMNI_RESOURCE_REPORT': '1', 'OMNI_MEMORY_MIB': ''})
        self.assertEqual(measured.returncode, 0, measured.stderr[-300:])
        report = measured.stderr.decode()
        self.assertIn('origin="automatic', report)
        found = re.search(r'heap_peak_mib=(\d+) .* counting=(yes|no)', report)
        self.assertIsNotNone(found, report)
        if found.group(2) != 'yes':
            self.skipTest('this build does not count the heap (sanitizer build): the automatic mode is not enforced')
        peak = int(found.group(1))
        self.assertGreater(peak, 64)
        # the host can give a little more than the run needs: it is admitted; a little less: it is refused, and the refusal says what the host reported
        self.assertEqual(run(OMNI, 'check', src, env={'OMNI_MEMORY_MIB': '', 'OMNI_HOST_MEMORY_MIB': str(peak + 1)}).returncode, 0)
        refused = run(OMNI, 'check', src, env={'OMNI_MEMORY_MIB': '', 'OMNI_HOST_MEMORY_MIB': str(peak - 1)})
        self.assertEqual(refused.returncode, 2, refused.stderr[-300:])
        self.assertIn(b'E_BUDGET', refused.stderr)
        self.assertIn('el entorno informa'.encode(), refused.stderr)
        self.assertIn(b'OMNI_MEMORY_MIB', refused.stderr)                              # the way out: the caller fixes the budget
        # an explicit budget replaces what the host reports
        self.assertEqual(run(OMNI, 'check', src, env={'OMNI_HOST_MEMORY_MIB': '8', 'OMNI_MEMORY_MIB': str(peak + 1)}).returncode, 0)

    def test_an_address_space_limit_of_the_caller_is_part_of_what_the_host_can_give(self):
        import resource
        src = self.big_source('as', 80000)

        def limited():
            resource.setrlimit(resource.RLIMIT_AS, (900 << 20, 900 << 20))
        done = subprocess.run([str(OMNI), 'check', str(src)], capture_output=True, preexec_fn=limited, timeout=300,
                              env={**os.environ, 'OMNI_HOME': str(ROOT), 'OMNI_MEMORY_MIB': ''})
        self.assertGreaterEqual(done.returncode, 0, 'killed by signal %d' % -done.returncode)
        self.assertEqual(done.returncode, 2, done.stderr[-300:])
        self.assertIn(b'E_BUDGET', done.stderr)

    def test_a_refused_input_leaves_no_artifact_in_any_command(self):
        src = self.big_source('big2', 20000)
        for command, ext in (('wave', None), ('pack', 'owire'), ('onme', 'onme'), ('emit-llvm', 'll')):
            with self.subTest(command=command):
                out = self.dir / ('never.' + (ext or 'out'))
                args = [command, src] + (['-o', out] if ext else [])
                done = run(OMNI, *args, env={'OMNI_MEMORY_MIB': '24'})
                self.assertEqual(done.returncode, 2, done.stderr[-300:])
                self.assertIn(b'E_BUDGET', done.stderr)
                self.assertEqual(done.stdout, b'')
                self.assertFalse(out.exists())

    def test_an_input_that_cannot_even_be_held_is_refused_before_it_is_read(self):
        src = self.source('huge', 'module t\n' + '//' + 'a' * (8 * 1024 * 1024) + '\nfunc main() u32 { return 0u32 }\n')
        done = run(OMNI, 'check', src, env={'OMNI_MEMORY_MIB': '4'})
        self.assertEqual(done.returncode, 2)
        self.assertIn(b'E_BUDGET', done.stderr)
        self.assertIn(b'el archivo de entrada', done.stderr)
        automatic = run(OMNI, 'check', src, env={'OMNI_MEMORY_MIB': '', 'OMNI_HOST_MEMORY_MIB': '4'})
        self.assertEqual(automatic.returncode, 2)
        self.assertIn(b'E_BUDGET', automatic.stderr)
        self.assertIn(b'el archivo de entrada', automatic.stderr)
        self.assertIn('el entorno informa'.encode(), automatic.stderr)

    def test_the_budget_mode_is_reported_and_unlimited_means_unlimited(self):
        src = self.source('tiny', 'module t\nfunc main() u32 { return 0u32 }\n')
        done = run(OMNI, 'check', src, env={'OMNI_RESOURCE_REPORT': '1', 'OMNI_MEMORY_MIB': ''})
        self.assertEqual(done.returncode, 0)
        self.assertRegex(done.stderr.decode(), r'omni resources: heap_peak_mib=\d+ budget_mib=0 origin="automatic[^"]*"')
        explicit = run(OMNI, 'check', src, env={'OMNI_RESOURCE_REPORT': '1', 'OMNI_MEMORY_MIB': '777'})
        self.assertIn('budget_mib=777 origin="OMNI_MEMORY_MIB=777"', explicit.stderr.decode())
        ignored = run(OMNI, 'check', src, env={'OMNI_RESOURCE_REPORT': '1', 'OMNI_MEMORY_MIB': 'many'})    # an invalid value is ignored: the automatic mode applies
        self.assertEqual(ignored.returncode, 0)
        self.assertIn('origin="automatic', ignored.stderr.decode())
        unlimited = run(OMNI, 'check', src, env={'OMNI_RESOURCE_REPORT': '1', 'OMNI_MEMORY_MIB': 'unlimited'})
        self.assertIn('budget_mib=0 origin="OMNI_MEMORY_MIB=unlimited"', unlimited.stderr.decode())

    def test_the_work_budget_is_optional_and_comes_from_the_host(self):
        src = self.big_source('work', 20000)
        done = run(OMNI, 'check', src, env={'OMNI_WORK_SECONDS': '0.001'})
        self.assertEqual(done.returncode, 2, done.stderr[-200:])
        self.assertIn(b'E_BUDGET', done.stderr)
        self.assertEqual(run(OMNI, 'check', src, env={'OMNI_WORK_SECONDS': '600'}).returncode, 0)

    def test_a_chain_of_imports_is_bounded_by_the_stack_budget_not_by_a_count(self):
        count = 1500
        for i in range(count):
            nxt = 'import m%d "m%d.omni"\n' % (i + 1, i + 1) if i + 1 < count else ''
            body = 'pub func f() u32 { return m%d.f() }\n' % (i + 1) if i + 1 < count else 'pub func f() u32 { return 1u32 }\n'
            (self.dir / ('m%d.omni' % i)).write_text('module m%d\n%s%s' % (i, nxt, body), encoding='utf-8')
        src = self.source('app', 'module app\nimport m0 "m0.omni"\nfunc main() u32 { return m0.f() }\n')
        with_stack = run(OMNI, 'check', src, env={'OMNI_STACK_KIB': '256'}, timeout=120)
        self.assertGreaterEqual(with_stack.returncode, 0, 'killed by signal %d' % -with_stack.returncode)
        self.assertEqual(with_stack.returncode, 2, with_stack.stderr[-200:])
        self.assertIn(b'E_BUDGET', with_stack.stderr)
        self.assertIn(b'OMNI_STACK_KIB', with_stack.stderr)
        self.assertEqual(run(OMNI, 'check', src, timeout=120).returncode, 0)          # the default stack holds the whole chain


class HostileRepresentationTests(ScaleCase):
    def test_a_wire_whose_counts_exceed_its_bytes_is_refused_and_never_allocates_them(self):
        src = self.source('p', 'module t\nfunc main() u32 { return 7u32 }\n')
        wire = self.dir / 'p.owire'
        self.ok('pack', src, '-o', wire)
        good = wire.read_bytes()
        self.assertEqual(run(OMNI, 'check', wire).returncode, 0)
        # forge every 4-byte window in the first 64 bytes with the largest count: nothing may crash, hang or allocate what it announces
        seen = set()
        for at in range(8, min(64, len(good) - 4)):
            forged = good[:at] + b'\xff\xff\xff\xff' + good[at + 4:]
            bad = self.dir / 'bad.owire'
            bad.write_bytes(forged)
            done = run(OMNI, 'check', bad, timeout=60)
            self.assertGreaterEqual(done.returncode, 0, 'offset %d: killed by signal %d' % (at, -done.returncode))
            self.assertIn(done.returncode, (0, 2, 3), (at, done.stderr[-120:]))
            self.assertNotIn(b'bad_alloc', done.stderr)
            seen.add(b'mas elementos que bytes' in done.stderr)
        self.assertIn(True, seen)           # a count larger than what is left to read is refused for exactly that, before the elements are read

    def test_a_capsule_that_lies_about_its_length_is_refused(self):
        text = 'bundle app {\n    module app {\n        func main() u32 !pure {\n            return 0;\n        }\n    }\n}\n'
        body = text.encode()

        def wire(declared):
            return b'OMCX' + (22).to_bytes(4, 'little') + declared.to_bytes(4, 'little') + body
        self.assertEqual(run(OMNI, 'check', self.write_bytes('ok.owire', wire(len(body)))).returncode, 0)
        for label, blob in (('longer than the data', wire(len(body) + 1)), ('shorter than the data', wire(len(body) - 1)), ('the largest possible', wire(0xFFFFFFFF)),
                            ('trailing data', wire(len(body)) + b'\x00')):
            with self.subTest(case=label):
                done = run(OMNI, 'check', self.write_bytes('bad.owire', blob), timeout=60)
                self.assertEqual(done.returncode, 2, done.stderr[:120])
                self.assertEqual(done.stdout, b'')

    def write_bytes(self, name: str, blob: bytes) -> pathlib.Path:
        path = self.dir / name
        path.write_bytes(blob)
        return path


if __name__ == '__main__':
    unittest.main()
