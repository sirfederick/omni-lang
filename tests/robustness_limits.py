#!/usr/bin/env python3
"""Robustness limits found by audit 360: hostile or merely huge input must be refused with a diagnostic, never crash the compiler.

* A left-associative chain (a+b+c+..., a.x.x..., f()::g()::..., a[0][0]..., e???) is built by a loop in the parser, so the recursion bound did not
  limit the tree that the checker, evaluator and lowering then walk recursively: 20000 terms (140 KB, under the token limit) overflowed the stack.
  The parser now bounds the HEIGHT of the tree at 64 (the checker's own structural limit, which used to apply only after the recursion) and answers E_LIMIT.
* The JSON reader of omni.package.json recursed without a bound: a 900 KB manifest of nested objects overflowed the stack. It is bounded at 8 levels.
* How much stack one level costs depends on the build (a sanitizer build needs tens of KB). The compiler therefore runs on a thread with an explicit 256 MiB
  stack, so the bounds hold under the sanitizer build and under a tiny `ulimit -s`.
"""
from __future__ import annotations
import os
import pathlib
import resource
import subprocess
import tempfile
import unittest
from language_0_8_3_alpha8 import ROOT, OMNI

HEIGHT_LIMIT = 64


def chain(kind: str, n: int) -> str:
    if kind == 'sum':
        return 'module m\nfunc main() u32 { return 1u32' + ' + 1u32' * n + ' }\n'
    if kind == 'field':
        return 'module m\nstruct S { x u32 }\nfunc main() u32 { let a = S { x: 1u32 }\n return a' + '.x' * n + ' }\n'
    if kind == 'method':
        return 'module m\nfunc f(x u32) u32 { return x }\nfunc main() u32 { return 1u32' + '::f()' * n + ' }\n'
    if kind == 'index':
        return 'module m\nfunc main() u32 { let a = array(1u32)\n return a' + '[0u32]' * n + ' }\n'
    if kind == 'try':
        return 'module m\nfunc g() Result<u32,u32> { return Ok<u32,u32>(1u32) }\nfunc main() u32 { let r = g()' + '?' * n + '\n return 0u32 }\n'
    raise ValueError(kind)


def nested_calls(depth: int, chain_len: int) -> str:
    inner = '1u32' + ' + 1u32' * chain_len
    return 'module m\nfunc f(x u32) u32 { return x }\nfunc main() u32 { return ' + 'f(' * depth + inner + ')' * depth + ' }\n'


class RobustnessCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='omni-limits-')
        self.dir = pathlib.Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def run_omni(self, *args, stack_bytes=None, compiler_stack_kib=None, timeout=120):
        def limit():
            if stack_bytes:
                resource.setrlimit(resource.RLIMIT_STACK, (stack_bytes, stack_bytes))
        env = {**os.environ, 'OMNI_HOME': str(ROOT)}
        if compiler_stack_kib:
            env['OMNI_STACK_KIB'] = str(compiler_stack_kib)
        return subprocess.run([str(OMNI), *map(str, args)], capture_output=True, timeout=timeout, preexec_fn=limit, env=env)

    def write(self, name, text):
        path = self.dir / name
        path.write_text(text, encoding='utf-8')
        return path

    def assertRefusedNotCrashed(self, result, label):
        self.assertGreaterEqual(result.returncode, 0, f'{label}: killed by signal {-result.returncode}')
        self.assertEqual(result.returncode, 2, f'{label}: {result.stderr[-300:]}')
        self.assertIn(b'E_LIMIT', result.stderr, label)
        self.assertNotIn(b'Sanitizer', result.stderr, label)


class ExpressionHeightTests(RobustnessCase):
    KINDS = ('sum', 'field', 'method', 'index', 'try')

    def test_enormous_chains_are_a_diagnostic_not_a_crash(self):
        # the compiler thread gets only 2 MiB here, so the refusal must come from the parser's own bound and not from a stack large enough to hide its absence
        for kind in self.KINDS:
            program = self.write(f'{kind}.omni', chain(kind, 20000))
            for command in ('check', 'eval', 'emit-llvm'):
                with self.subTest(kind=kind, command=command):
                    extra = ('-o', self.dir / f'{kind}-{command}.ll') if command == 'emit-llvm' else ()
                    self.assertRefusedNotCrashed(self.run_omni(command, program, *extra, compiler_stack_kib=2048), f'{kind}/{command}')
        self.assertRefusedNotCrashed(self.run_omni('check', self.write('default-stack.omni', chain('sum', 20000))), 'default stack')

    def test_the_height_limit_is_the_structural_one_and_what_it_admits_runs_everywhere(self):
        # a chain of n terms has height n + 1 (the leaf counts): 63 terms are the largest admitted, 64 the first refused, as in the checker's own bound
        for kind in ('sum', 'method'):
            admitted = self.write(f'{kind}-ok.omni', chain(kind, HEIGHT_LIMIT - 1))
            refused = self.write(f'{kind}-no.omni', chain(kind, HEIGHT_LIMIT))
            with self.subTest(kind=kind):
                self.assertEqual(self.run_omni('check', admitted).returncode, 0, kind)
                evaluated = self.run_omni('eval', admitted)
                self.assertEqual(evaluated.returncode, HEIGHT_LIMIT if kind == 'sum' else 1, evaluated.stderr[-200:])
                emitted = self.run_omni('emit-llvm', admitted, '-o', self.dir / f'{kind}-ok.ll')
                self.assertEqual(emitted.returncode, 0, emitted.stderr[-300:])
                self.assertRefusedNotCrashed(self.run_omni('check', refused), kind)
                self.assertIn(b'expresion demasiado profunda', self.run_omni('check', refused).stderr)   # at parse time, before any pass recurses

    def test_nesting_and_chains_add_up_to_one_height(self):
        # nested calls and a chain share one height: 30 calls around a 33-term sum are height 64 (admitted), 31 are 65 and 60 + 60 are 121 (refused)
        admitted = self.write('nest-ok.omni', nested_calls(30, 33))
        self.assertEqual(self.run_omni('check', admitted).returncode, 0)
        self.assertEqual(self.run_omni('eval', admitted).returncode, 34)
        self.assertRefusedNotCrashed(self.run_omni('check', self.write('nest-no1.omni', nested_calls(31, 33))), 'nested 65')
        self.assertRefusedNotCrashed(self.run_omni('check', self.write('nest-no2.omni', nested_calls(60, 60))), 'nested 121')

    RECURSION = ('module m\nfunc f(n u32) u32 { if n == 0u32 { return 0u32 }\n return 1u32 + f(n - 1u32) }\n'
                 'func main() u32 { return f(120u32) }\n')

    def test_the_bounds_do_not_depend_on_the_callers_stack(self):
        # recursion to the evaluator's depth (128 calls) and the largest admitted tree on a 256 KiB caller stack: a sanitizer build needs tens of KB per
        # level, and no build is allowed to depend on `ulimit -s`; only the dedicated compiler thread makes this possible
        recursion = self.write('recursion.omni', self.RECURSION)
        admitted = self.write('small-stack.omni', chain('sum', HEIGHT_LIMIT - 1))
        for name, program, command, expected in (('recursion', recursion, 'eval', 120), ('tree/check', admitted, 'check', 0), ('tree/eval', admitted, 'eval', HEIGHT_LIMIT)):
            with self.subTest(name=name):
                done = self.run_omni(command, program, stack_bytes=256 << 10)
                self.assertGreaterEqual(done.returncode, 0, f'killed by signal {-done.returncode}')
                self.assertEqual(done.returncode, expected, done.stderr[-300:])

    def test_the_compiler_stack_can_be_set_and_a_bad_value_is_ignored(self):
        recursion = self.write('recursion2.omni', self.RECURSION)
        for value in ('65536', '524288'):
            with self.subTest(value=value):
                self.assertEqual(self.run_omni('eval', recursion, compiler_stack_kib=value).returncode, 120)
        # the override is really applied: 256 KiB is not enough for 120 nested evaluator calls, so the run must not complete
        small = self.run_omni('eval', recursion, compiler_stack_kib=256)
        self.assertNotEqual(small.returncode, 120)
        for value in ('abc', '0', '-5', '99999999999', '12x'):
            with self.subTest(bad=value):
                self.assertEqual(self.run_omni('eval', recursion, compiler_stack_kib=value).returncode, 120)    # ignored: the default stack applies


class HostPolicyEndpointParityTests(RobustnessCase):
    """The runtime read endpoints with sscanf (signs, spaces, trailing text, long octets) while the compiler used a strict parser: two grammars for one
    authority. Both must now accept and refuse exactly the same texts."""
    ACCEPTED = ('127.0.0.1:80', '0.0.0.0:1', '255.255.255.255:65535', '1.2.3.4:8080', '127.000.000.001:80', '10.0.0.1:080', '9.9.9.9:0000000080')
    REFUSED = (' 127.0.0.1:80', '+127.0.0.1:80', '127.0.0.1:+80', '127.0.0.1:80 ', '127.0.0.1:80x', '0127.0.0.1:80', '127.0.0.1:0', '127.0.0.1:65536',
               '127.0.0.1:99999999999', '1.2.3:80', '1.2.3.4.5:80', '256.0.0.1:80', '127.0.0.1', '127.0.0.1:', ':80', '-1.0.0.1:80', 'a.b.c.d:80',
               '127..0.1:80', 'localhost:80', '1.2.3.4:8 0')

    def test_runtime_and_compiler_agree_on_every_endpoint(self):
        program = self.write('policy.omni', 'module p\nfunc main() u32 { return 0u32 }\n')
        native = self.dir / 'policy-native'
        built = self.run_omni('build', program, '-o', native, '--cache-dir', self.dir / 'cache')
        self.assertEqual(built.returncode, 0, built.stderr)
        for text, accepted in [(t, True) for t in self.ACCEPTED] + [(t, False) for t in self.REFUSED]:
            policy = self.write('p.ohp', f'OHP1\ngeneration|1\nnot_after_tick|1000\ngrant|net.connect|{text}|4096\n')
            with self.subTest(endpoint=text, accepted=accepted):
                compiler = self.run_omni('host-policy', 'verify', policy)
                runtime = subprocess.run([str(native), '--omni-host-policy', str(policy)], capture_output=True)
                self.assertEqual(compiler.returncode == 0, accepted, ('compiler', compiler.stderr[-200:]))
                self.assertEqual(runtime.returncode == 0, accepted, ('runtime', runtime.returncode, runtime.stderr[-200:]))
                if not accepted:
                    self.assertIn(b'E_HOST_POLICY', runtime.stderr)


class PackageManifestTests(RobustnessCase):
    def package(self, dependencies):
        root = self.dir / 'pkg'
        (root / 'src').mkdir(parents=True, exist_ok=True)
        (root / 'src' / 'main.omni').write_text('module m\nfunc main() u32 { return 0u32 }\n', encoding='utf-8')
        extra = '' if dependencies is None else ',"dependencies":' + dependencies
        (root / 'omni.package.json').write_text('{"schema":"omni.package/1","name":"x","version":"0.1.0","entry":"src/main.omni"' + extra + '}', encoding='utf-8')
        return root

    def test_a_valid_manifest_still_locks_and_checks(self):
        root = self.package(None)
        self.assertEqual(self.run_omni('package', 'lock', root, '--offline').returncode, 0)
        self.assertEqual(self.run_omni('package', 'check', root, '--offline').returncode, 0)

    def test_deeply_nested_json_is_a_manifest_error_not_a_crash(self):
        for depth in (9, 100, 150000):
            root = self.package('{"a":' * depth + '{}' + '}' * depth)
            with self.subTest(depth=depth):
                done = self.run_omni('package', 'check', root, '--offline')
                self.assertGreaterEqual(done.returncode, 0, f'killed by signal {-done.returncode}')
                self.assertEqual(done.returncode, 2, done.stderr[-300:])
                self.assertIn(b'E_PACKAGE_MANIFEST', done.stderr)
                self.assertIn('demasiado profundo'.encode(), done.stderr)

    def test_nesting_within_the_bound_is_judged_by_the_schema_not_by_the_depth_guard(self):
        root = self.package('{"a":' * 6 + '{}' + '}' * 6)
        done = self.run_omni('package', 'check', root, '--offline')
        self.assertEqual(done.returncode, 2)
        self.assertIn(b'E_PACKAGE_MANIFEST', done.stderr)
        self.assertNotIn('demasiado profundo'.encode(), done.stderr)


if __name__ == '__main__':
    unittest.main()
