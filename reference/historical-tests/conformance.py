#!/usr/bin/env python3
"""Executable conformance corpus; all work is confined to temporary directories."""
from __future__ import annotations
import json, os, pathlib, random, subprocess, tempfile, unittest
ROOT = pathlib.Path(__file__).resolve().parents[1]
OMNI = pathlib.Path(os.environ.get('OMNI_TEST_BIN', ROOT / 'bin/linux-x86_64/omni'))

def proc(*args: object, timeout: int = 10) -> subprocess.CompletedProcess:
    return subprocess.run([str(x) for x in args], capture_output=True, timeout=timeout)

def program(body: str, helpers: str = '') -> str:
    return f'module corpus\n{helpers}\nfunc main() u32 !io {{ {body} }}\n'

class CoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='omni-conformance-')
        self.dir = pathlib.Path(self.tmp.name)
    def tearDown(self):
        self.tmp.cleanup()
    def source(self, text: str, name: str = 'source.omni') -> pathlib.Path:
        path = self.dir/name; path.write_text(text, encoding='utf-8'); return path
    def differential(self, text: str, stdout: bytes, status: int = 0, err: bytes = b''):
        src = self.source(text)
        ref = proc(OMNI, 'eval', src)
        self.assertEqual((ref.returncode, ref.stdout, ref.stderr), (status, stdout, err))
        for opt in ('0','2'):
            binary = self.dir/f'app-{opt}'
            built = proc(OMNI, 'build', src, '-o', binary, '--opt', opt)
            self.assertEqual(built.returncode, 0, built.stderr.decode())
            self.assertEqual(binary.read_bytes()[:4], b'\x7fELF')
            native = proc(binary)
            self.assertEqual((native.returncode,native.stdout,native.stderr),(status,stdout,err))
    def reject(self, text: str, code: str):
        r = proc(OMNI,'check',self.source(text))
        self.assertEqual(r.returncode,2,r.stderr.decode())
        self.assertIn(code.encode(),r.stderr)
    def test_native_hola_and_recursion(self):
        self.differential((ROOT/'examples/hola.omni').read_text(),b'Hola, Omni\n720\n')
    def test_native_loop_mutation(self):
        self.differential((ROOT/'examples/sumatoria.omni').read_text(),b'55\n')
    def test_native_branch_return_then_continuation(self):
        self.differential(program('print(f(2)); print(f(8)); return 0;', 'func f(n u32) u32 { if n < 5 { return n + 1; } return n * 2; }'),b'3\n16\n')
    def test_native_branch_mutation(self):
        self.differential(program('var a = 3; if a == 3 { a = 9; } else { a = 0; } print(a); return 0;'),b'9\n')
    def test_native_short_circuit(self):
        self.differential(program('print(false && (1 / 0 == 0)); print(true || (1 / 0 == 0)); print((true && false) || true); return 0;'), b'false\ntrue\ntrue\n')
    def test_native_boolean_calls(self):
        self.differential(program('print(f(false)); print(f(true)); return 0;', 'func f(x bool) bool { return !x; }'),b'true\nfalse\n')
    def test_native_left_to_right_arguments(self):
        self.differential(program('print(sum(f(1), f(2))); return 0;', 'func f(x u32) u32 !io { print(x); return x; } func sum(a u32,b u32) u32 { return a+b; }'),b'1\n2\n3\n')
    def test_native_checked_add(self):
        self.differential(program('return 4294967295 + 1;'),b'',70,b'omni runtime E_OVERFLOW\n')
    def test_native_checked_sub(self):
        self.differential(program('return 0 - 1;'),b'',70,b'omni runtime E_OVERFLOW\n')
    def test_native_checked_multiply(self):
        self.differential(program('return 65536 * 65536;'),b'',70,b'omni runtime E_OVERFLOW\n')
    def test_native_divzero(self):
        self.differential(program('print("antes"); return 7 / 0;'),b'antes\n',70,b'omni runtime E_DIVZERO\n')
    def test_native_modzero(self):
        self.differential(program('return 7 % 0;'),b'',70,b'omni runtime E_DIVZERO\n')
    def test_native_wrapping(self):
        self.differential(program('print(4294967295 +% 2); return 0;'),b'1\n')
    def test_native_utf8_and_escape(self):
        self.differential(program('print("café 😀\\tfin"); print(""); return 0;'), 'café 😀\tfin\n\n'.encode())
    def test_native_fuel_limit(self):
        self.differential(program('for true { } return 0;'),b'',70,b'omni runtime E_FUEL\n')
    def test_native_recursion_limit(self):
        self.differential(program('return f();','func f() u32 { return f(); }'),b'',70,b'omni runtime E_DEPTH\n')
    def test_native_exit_code(self):
        self.differential(program('return 259;'),b'',3)
    def test_native_independent_random_arithmetic(self):
        rng = random.Random(20260918); lines=[]; expected=[]
        for _ in range(100):
            a,b,c = (rng.randrange(0,10000) for _ in range(3))
            divisor=rng.randrange(1,100)
            lines.append(f'print(({a} * {b} + {c}) / {divisor});')
            expected.append(str((a*b+c)//divisor))
        self.differential(program(' '.join(lines)+' return 0;'),('\n'.join(expected)+'\n').encode())
    def test_particle_wave_wire_roundtrip(self):
        src=self.source((ROOT/'examples/hola.omni').read_text())
        human=proc(OMNI,'fmt',src); self.assertEqual(human.returncode,0)
        wav=proc(OMNI,'wave',src); self.assertEqual(wav.returncode,0)
        wf=self.dir/'program.owave';wf.write_bytes(wav.stdout)
        self.assertEqual(proc(OMNI,'fmt',wf).stdout,human.stdout)
        wi=self.dir/'program.owire';self.assertEqual(proc(OMNI,'pack',wf,'-o',wi).returncode,0)
        self.assertEqual(proc(OMNI,'fmt',wi).stdout,human.stdout)
        self.assertEqual(proc(OMNI,'wave',wi).stdout,wav.stdout)
        self.assertEqual(proc(OMNI,'run',wi).stdout,b'Hola, Omni\n720\n')
    def test_wave_direct_authorship(self):
        w='(omni-wave 1 (module agent) (func main (params) (result u32) (effects io) (block (print (binary "+" (u32 40) (u32 2))) (return (u32 0)))))'
        p=self.dir/'agent.owave';p.write_text(w)
        r=proc(OMNI,'run',p);self.assertEqual((r.returncode,r.stdout),(0,b'42\n'),r.stderr)
    def test_wave_undeclared_operation(self):
        p=self.dir/'bad.owave';p.write_text('(omni-wave 1 (module agent) (func main (params) (result u32) (effects pure) (block (return (mystery 4)))))')
        r=proc(OMNI,'check',p);self.assertEqual(r.returncode,2);self.assertIn(b'E_WAVE',r.stderr)
    def test_wave_effect_boundary(self):
        p=self.dir/'bad.owave';p.write_text('(omni-wave 1 (module agent) (func main (params) (result u32) (effects pure) (block (text "bad") (return (u32 0)))))')
        r=proc(OMNI,'check',p);self.assertEqual(r.returncode,2);self.assertIn(b'E_EFFECT',r.stderr)
    def test_wire_every_truncation_rejected(self):
        p=self.source(program('return 0;')); f=self.dir/'p.owire';proc(OMNI,'pack',p,'-o',f)
        full=f.read_bytes()
        for i in range(len(full)):
            f.write_bytes(full[:i]);r=proc(OMNI,'check',f);self.assertEqual(r.returncode,2,(i,r.stderr))
    def test_wire_trailer_rejected(self):
        p=self.source(program('return 0;')); f=self.dir/'p.owire';proc(OMNI,'pack',p,'-o',f);f.write_bytes(f.read_bytes()+b'0')
        r=proc(OMNI,'check',f);self.assertEqual(r.returncode,2);self.assertIn(b'E_WIRE',r.stderr)
    def test_wire_length_bomb(self):
        f=self.dir/'p.owire';f.write_bytes(b'OMC1\xff\xff\xff\xff');r=proc(OMNI,'check',f);self.assertEqual(r.returncode,2);self.assertIn(b'E_LIMIT',r.stderr)
    def test_unknown_function(self):self.reject(program('return absent();'),'E_CALL')
    def test_wrong_arity(self):self.reject(program('return f();','func f(x u32) u32 { return x; }'),'E_ARITY')
    def test_wrong_return_type(self):self.reject(program('return true;'),'E_TYPE')
    def test_wrong_argument_type(self):self.reject(program('return f(false);','func f(x u32) u32 { return x; }'),'E_TYPE')
    def test_read_before_definition(self):self.reject(program('let x = y; let y = 1; return x;'),'E_UNDEFINED')
    def test_block_scope(self):self.reject(program('if true { let x=1; } return x;'),'E_UNDEFINED')
    def test_immutable_let(self):self.reject(program('let x=1; x=2; return x;'),'E_IMMUTABLE')
    def test_immutable_parameter(self):self.reject(program('return f(1);','func f(x u32) u32 { x=2; return x; }'),'E_IMMUTABLE')
    def test_shadow_forbidden(self):self.reject(program('let x=1; if true { let x=2; } return x;'),'E_DUPLICATE')
    def test_duplicate_function(self):self.reject(program('return 0;','func main() u32 { return 0; }'),'E_DUPLICATE')
    def test_pure_cannot_print(self):self.reject('module t func main() u32 !pure { print(1); return 0; }','E_EFFECT')
    def test_pure_cannot_call_io(self):self.reject('module t func f() u32 !io { return 1; } func main() u32 { return f(); }','E_EFFECT')
    def test_unknown_effect(self):self.reject('module t func main() u32 !root { return 0; }','E_EFFECT')
    def test_missing_return(self):self.reject(program('if true { return 1; }'),'E_RETURN')
    def test_unreachable(self):self.reject(program('return 1; return 0;'),'E_UNREACHABLE')
    def test_numeric_condition(self):self.reject(program('if 1 { return 1; } else { return 0; }'),'E_TYPE')
    def test_literal_overflow(self):self.reject(program('return 4294967296;'),'E_OVERFLOW_LITERAL')
    def test_bad_literal(self):self.reject(program('return 1abc;'),'E_NUMBER')
    def test_bad_escape(self):self.reject(program('print("\\z"); return 0;'),'E_STRING')
    def test_truncated_source(self):self.reject('module t func main() u32 { return 0;','E_PARSE')
    def test_unknown_type(self):self.reject('module t func main() string { return 0; }','E_TYPE')
    def test_utf8_rejected(self):
        f=self.dir/'bad.omni';f.write_bytes(b'\xff');r=proc(OMNI,'check',f);self.assertEqual(r.returncode,2);self.assertIn(b'E_UTF8',r.stderr)
    def test_input_limit(self):self.reject(' '*1048577,'E_LIMIT')
    def test_expression_depth_limit(self):self.reject(program('return '+'('*193+'1'+')'*193+';'),'E_LIMIT')
    def test_existing_binary_preserved_on_invalid_program(self):
        f=self.source(program('return absent();'));dest=self.dir/'app';dest.write_bytes(b'old-program')
        r=proc(OMNI,'build',f,'-o',dest,'--force');self.assertEqual(r.returncode,2);self.assertEqual(dest.read_bytes(),b'old-program')
    def test_existing_binary_preserved_on_backend_failure(self):
        f=self.source(program('return 0;'));dest=self.dir/'app';dest.write_bytes(b'old-program')
        r=subprocess.run([str(OMNI),'build',str(f),'-o',str(dest),'--force'],env={**os.environ,'OMNI_CLANG':'/bin/false'},capture_output=True)
        self.assertEqual(r.returncode,2);self.assertEqual(dest.read_bytes(),b'old-program')
    def test_refuse_overwrite_by_default(self):
        f=self.source(program('return 0;'));dest=self.dir/'app';dest.write_bytes(b'old')
        r=proc(OMNI,'build',f,'-o',dest);self.assertEqual(r.returncode,2);self.assertIn(b'E_EXISTS',r.stderr)
    def test_refuse_source_overwrite(self):
        f=self.source(program('return 0;'));r=proc(OMNI,'build',f,'-o',f,'--force');self.assertEqual(r.returncode,2);self.assertIn(b'E_FILE',r.stderr)
    def test_paths_with_spaces_and_shell_characters(self):
        f=self.source(program('print(42); return 0;'),'source ; $.omni');dest=self.dir/'app ; $'
        r=proc(OMNI,'build',f,'-o',dest);self.assertEqual(r.returncode,0,r.stderr);self.assertEqual(proc(dest).stdout,b'42\n')
    def test_language_test_command(self):
        r=proc(OMNI,'test',ROOT/'examples/contratos_puros.omni');self.assertEqual(r.returncode,0,r.stderr);self.assertIn(b'2 tests passed',r.stdout)
    def test_missing_main_build(self):
        f=self.source('module m func library() u32 { return 7; }');self.assertEqual(proc(OMNI,'check',f).returncode,0)
        r=proc(OMNI,'build',f,'-o',self.dir/'app');self.assertEqual(r.returncode,2);self.assertIn(b'E_ENTRY',r.stderr)
    def test_main_wrong_shape(self):
        f=self.source('module m func main(x u32) u32 { return x; }');r=proc(OMNI,'build',f,'-o',self.dir/'app');self.assertEqual(r.returncode,2);self.assertIn(b'E_ENTRY',r.stderr)
    def test_deep_format_roundtrip(self):
        # The printer adds parentheses; raw parse depth must not break canonical IR.
        expr='1'
        for _ in range(45): expr='1 + ('+expr+')'
        p=self.source(program('print('+expr+'); return 0;'))
        f=proc(OMNI,'fmt',p);self.assertEqual(f.returncode,0,f.stderr)
        p.write_bytes(f.stdout);g=proc(OMNI,'fmt',p)
        self.assertEqual(g.returncode,0,g.stderr);self.assertEqual(g.stdout,f.stdout)
    def test_wave_control_byte_rejected(self):
        p=self.dir/'bad.owave';p.write_bytes(b'(omni-wave 1 (module agent) (func main (params) (result u32) (effects io) (block (text "\x01") (return (u32 0)))))')
        r=proc(OMNI,'check',p);self.assertEqual(r.returncode,2);self.assertIn(b'E_STRING',r.stderr)
    def test_native_output_limit(self):
        # A bounded example: last print would exceed the common output limit.
        text='x'*4096
        src=program('var i=0; for i < 256 { print("'+text+'"); i=i+1; } return 0;')
        self.differential(src,((text+'\n')*255).encode(),70,b'omni runtime E_OUTPUT_LIMIT\n')
    def test_format_idempotence(self):
        f=self.source((ROOT/'examples/sumatoria.omni').read_text());first=proc(OMNI,'fmt',f);f.write_bytes(first.stdout);self.assertEqual(proc(OMNI,'fmt',f).stdout,first.stdout)

if __name__=='__main__':
    suite=unittest.defaultTestLoader.loadTestsFromTestCase(CoreTests)
    result=unittest.TextTestRunner(verbosity=2).run(suite)
    report={'suite':'Omni compiler dev.1 conformance','tests':result.testsRun,'failures':len(result.failures),'errors':len(result.errors),'skipped':len(result.skipped),'native_target':'x86_64-unknown-linux-gnu','native_optimizations':['O0','O2'],'random_arithmetic_cases':100,'seed':20260918,'windows_executed':False,'note':'Finite tests; not a proof of language-wide safety, correctness or production readiness.'}
    (ROOT/'evidence/conformance.json').write_text(json.dumps(report,indent=2)+'\n')
    raise SystemExit(0 if result.wasSuccessful() else 1)
