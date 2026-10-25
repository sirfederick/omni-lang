#!/usr/bin/env python3
"""Current-semantics projection of the original 61-test Core corpus.
Historical source is imported unchanged; only explicitly superseded effect expectations are overridden.
"""
from __future__ import annotations
import importlib.util, os, pathlib
ROOT=pathlib.Path(__file__).resolve().parents[1]
HIST=ROOT/'reference/historical-tests/conformance.py'
spec=importlib.util.spec_from_file_location('omni_historical_core_corpus',HIST)
if spec is None or spec.loader is None: raise RuntimeError(f'cannot load {HIST}')
hist=importlib.util.module_from_spec(spec); spec.loader.exec_module(hist)
hist.ROOT=ROOT
hist.OMNI=pathlib.Path(os.environ.get('OMNI_TEST_BIN',ROOT/'bin/linux-x86_64/omni'))
# The historical helper cuts every compiler call at 10 s; a native `build` compiles the C runtime and takes longer on a loaded or just-started machine
# (gate r5: three cut-offs, nothing wrong with the compiler). The corpus stays untouched; calls run to the end and the matrix runner's per-executable
# timeout is the only bound, so a real failure shows its own output instead of a TimeoutExpired.
_historical_proc=hist.proc
def _patient_proc(*args,timeout=None): return _historical_proc(*args,timeout=None)
hist.proc=_patient_proc

class CurrentCoreCompat(hist.CoreTests):
    def test_pure_cannot_print(self):
        self.reject('module t func main() u32 !pure { print(1); return 0; }','E_CAPABILITY')
    def test_pure_cannot_call_io(self):
        # Declared-but-unused authority does not taint callers under minimum-required propagation.
        p=self.source('module t func f() u32 !io { return 1; } func main() u32 { return f(); }')
        r=hist.proc(hist.OMNI,'check',p); self.assertEqual(r.returncode,0,r.stderr)
    def test_unknown_effect(self):
        self.reject('module t func main() u32 !root { return 0; }','E_CAPABILITY')
    def test_input_limit(self):
        # Superseded (Adenda 015E, SDK 1.3): the inherited 1 MiB cap on a source file is retired. The size of a source is bounded by the memory budget of the host (E_BUDGET, tests/cp15_scale.py),
        # so a text of 1 MiB + 1 bytes is judged by what it says: here it is only whitespace, which has no `module`.
        self.reject(' '*1048577,'E_PARSE')
    def test_wave_effect_boundary(self):
        p=self.dir/'bad.owave';p.write_text('(omni-wave 1 (module agent) (func main (params) (result u32) (effects pure) (block (text "bad") (return (u32 0)))))')
        r=hist.proc(hist.OMNI,'check',p);self.assertEqual(r.returncode,2);self.assertIn(b'E_CAPABILITY',r.stderr)

if __name__=='__main__':
    import unittest
    unittest.main(verbosity=2)
