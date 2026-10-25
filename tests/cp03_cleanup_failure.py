#!/usr/bin/env python3
"""CP-03 (spec/CLEANUP_FAILURE_CANDIDATE.md): the order of cleanup, the fallible close, a failure injected at every acquisition point, and an oracle that tells a
leak from a double release from a premature release.

Everything that runs Omni runs twice, in the evaluator and natively, and the two have to agree: the exit code, and (where an audit is asked for) the whole
audit stream. The oracle is validated twice: on Omni programs (which can only be clean or a typed failure, because the checker refuses the rest) and on the C
runtime driven directly with the misuses the checker would never let an Omni program write.
"""
from __future__ import annotations
import os
import re
import subprocess
import unittest
from cp01_owned_slots import SeqCase, TOK
from cp02_borrowed_containers import ContainerCase
from language_0_8_3_alpha8 import ROOT, OMNI, proc

P = 65521


def digest(results):
    """The CloseReport.trace of `seq.close_all` for the results of the closes, in closing order: ('ok', n) or ('err', code)."""
    t = 0
    for kind, v in results:
        t = (t * 7 + (v % P)) % P if kind == 'ok' else (t * 7 + (v % P) + 1) % P
    return t


def audit_lines(stderr: bytes):
    return [l for l in stderr.decode('utf-8', 'replace').splitlines() if l.startswith('audit ')]


def classify(stderr: bytes) -> str:
    """The oracle: a verdict that is NOT derived from acquired - released alone."""
    text = stderr.decode('utf-8', 'replace')
    if 'E_RESOURCE_DOUBLE_RELEASE' in text:
        return 'DOUBLE_RELEASE'
    if 'E_RESOURCE_STALE_USE' in text or 'E_SLOT_OCCUPIED' in text:
        return 'PREMATURE_RELEASE'
    if 'E_RESOURCE_HANDLE' in text:
        return 'FORGED_HANDLE'
    live = re.search(r'live=(\d+)', text)
    if live and int(live.group(1)) > 0:
        return 'LEAK'
    rel = re.findall(r'audit rel (\d+)', text)
    acq = re.findall(r'audit acq (\d+)', text)
    if sorted(rel) != sorted(acq):
        return 'LEAK' if len(rel) < len(acq) else 'DOUBLE_RELEASE'
    return 'CLEAN'


class CleanupCase(SeqCase):
    def run_both(self, path, env=None):
        """(evaluator result, native result) of a program, each as (returncode, stderr), with `env` added to the environment."""
        extra = {'OMNI_HOME': str(ROOT), **(env or {})}
        merged = {**os.environ, **extra}
        evaluated = subprocess.run([str(OMNI), 'eval', str(path)], capture_output=True, timeout=180, env=merged)
        native = self.dir / (path.name + '-native')
        key = (str(path), path.read_bytes())
        if getattr(self, '_native_built', None) != key:   # the executable of one program is built once and run under every environment
            built = self.build_native(path, native)
            self.assertEqual(built.returncode, 0, built.stderr)
            self._native_built = key
        executed = subprocess.run([str(native)], capture_output=True, timeout=180, env=merged)
        return (evaluated.returncode, evaluated.stderr), (executed.returncode, executed.stderr)


class CleanupOrderTests(CleanupCase):
    def test_automatic_cleanup_runs_in_reverse_order_of_declaration_on_every_exit_path(self):
        # acquisitions are numbered from 1 in the order they happen; a release names the acquisition it frees
        programs = {
            'return inside a loop, three buffers live': (
                'func main() u32 !{memory.read,memory.write} {\n  let a = buffer.alloc(4u32)\n  match a { Ok(x) {\n    let b = buffer.alloc(4u32)\n'
                '    match b { Ok(y) {\n      let c = buffer.alloc(4u32)\n      match c { Ok(z) {\n        var i u32 = 0u32\n        for i < 3u32 {\n'
                '          if i == 1u32 { return 42u32 }\n          i = i + 1u32\n        }\n        return 1u32\n      } Err(e) { return 90u32 } }\n'
                '    } Err(e) { return 91u32 } }\n  } Err(e) { return 92u32 } }\n}\n',
                ['acq 1', 'acq 2', 'acq 3', 'rel 3', 'rel 2', 'rel 1']),
            'continue and break leave a loop body with two buffers live': (
                'func main() u32 !{memory.read,memory.write} {\n  var i u32 = 0u32\n  for i < 4u32 {\n    let a = buffer.alloc(4u32)\n    match a { Ok(x) {\n'
                '      let b = buffer.alloc(4u32)\n      match b { Ok(y) {\n        i = i + 1u32\n        if i == 2u32 { continue }\n        if i == 3u32 { break }\n'
                '      } Err(e) { return 90u32 } }\n    } Err(e) { return 91u32 } }\n  }\n  return 42u32\n}\n',
                ['acq 1', 'acq 2', 'rel 2', 'rel 1', 'acq 3', 'acq 4', 'rel 4', 'rel 3', 'acq 5', 'acq 6', 'rel 6', 'rel 5']),
            'a consumed buffer is not released again': (
                'func main() u32 !{memory.read,memory.write} {\n  let a = buffer.alloc(4u32)\n  match a { Ok(x) {\n    let b = buffer.alloc(4u32)\n'
                '    match b { Ok(y) {\n      let z u32 = buffer.release(move(x))\n      return 42u32\n    } Err(e) { return 91u32 } }\n  } Err(e) { return 92u32 } }\n}\n',
                ['acq 1', 'acq 2', 'rel 1', 'rel 2']),
            'freezing a byte buffer consumes it once': (
                'func main() u32 !{memory.read,memory.write} {\n  let a = buffer.alloc(4u32)\n  match a { Ok(x) {\n    let f = buffer.freeze(move(x))\n'
                '    match f { Ok(bytes) { return 42u32 } Err(e) { return 1u32 } }\n  } Err(e) { return 92u32 } }\n}\n',
                ['acq 1', 'rel 1']),
            'freezing an empty slot buffer releases it': (
                TOK + 'func main() u32 !{memory.read,memory.write} {\n  let a = slots.alloc<Tok>(1u32)\n  match a { Ok(b) {\n    let f = buffer.freeze(move(b))\n'
                '    match f { Ok(bytes) { return 1u32 } Err(e) { if e == 8u32 { return 42u32 }\n      return 2u32 } }\n  } Err(e) { return 90u32 } }\n}\n',
                ['acq 1', 'rel 1']),
            'a sequence is released after its last element': (
                TOK + 'func main() u32 !{memory.read,memory.write} {\n  let c = seq.new<Tok>(2u32)\n  match c { Ok(s) {\n'
                '    let r = seq.push<Tok>(borrow_mut(s), mint(1u64))\n    match r { Ok(i) { } Err(back) { let z u64 = eat(move(back)) } }\n'
                '    let d u32 = seq.destroy<Tok>(move(s))\n    if d != 1u32 { return 1u32 }\n    return 42u32\n  } Err(e) { return e } }\n}\n',
                ['acq 1', 'rel 1']),
        }
        for label, (body, expected) in programs.items():
            with self.subTest(label):
                path = self.source(body, 'order.omni')
                ev, nat = self.run_both(path, {'OMNI_RESOURCE_AUDIT': '1'})
                self.assertEqual(ev[0], 42, ev[1])
                self.assertEqual(nat[0], 42, nat[1])
                summary = 'audit summary acquired=%d released=%d live=0' % (len(expected) // 2, len(expected) // 2)
                for who, (rc, err) in (('evaluator', ev), ('native', nat)):
                    self.assertEqual(audit_lines(err), ['audit ' + e for e in expected] + [summary], who)
                self.assertEqual(classify(ev[1]), 'CLEAN')

    def test_a_sequence_is_closed_last_to_first_and_its_buffer_is_released_after_the_last_element(self):
        # each Tok is closed in the order the digest records: the digest of 5,4,3,2,1 is not the digest of 1,2,3,4,5
        self.assertNotEqual(digest([('ok', 1)] * 4 + [('err', 33)]), digest([('err', 33)] + [('ok', 1)] * 4))
        self.both(self.source(CLOSE_TOK({3: 33}) +
            FILL +
            'func main() u32 !{memory.read,memory.write} {\n  let c = seq.new<Tok>(0u32)\n  match c { Ok(s) {\n    let code u32 = fill(borrow_mut(s), 5u64)\n'
            '    let rep seq.CloseReport = seq.close_all<Tok>(move(s))\n    if code != 0u32 { return code }\n'
            '    if rep.trace != %du32 { return 50u32 }\n    return 42u32\n  } Err(e) { return e } }\n}\n' % digest([('ok', 1), ('ok', 1), ('err', 33), ('ok', 1), ('ok', 1)])))


def CLOSE_TOK(failing, weights=None):
    """`impl seq.Close for Tok`: finish consumes the element and fails with the mapped code for the listed ids; the ids in `weights` return Ok(weight), the rest Ok(1)."""
    body = ''.join('    if r.h == %du64 { return Err<u32,u32>(%du32) }\n' % (i, c) for i, c in failing.items())
    body += ''.join('    if r.h == %du64 { return Ok<u32,u32>(%du32) }\n' % (i, w) for i, w in (weights or {}).items())
    return (TOK.split('impl seq.Dispose')[0] +
            'impl seq.Close for Tok { func finish(x Resource<Tok>) Result<u32,u32> !{memory.write} {\n'
            '    let r Tok = resource.unseal(move(x))\n' + body + '    return Ok<u32,u32>(1u32)\n  } }\n')


FILL = ('func fill(v BorrowMut<seq.Seq<Tok>>, n u64) u32 !{memory.read,memory.write} {\n  var i u64 = 1u64\n  for i <= n {\n'
        '    let g = seq.reserve<Tok>(borrow_mut(v))\n    match g { Ok(c) { } Err(e) { return 100u32 + e } }\n'
        '    let r = seq.push<Tok>(borrow_mut(v), mint(i))\n    match r { Ok(k) { } Err(back) { let z u64 = eat(move(back))\n      return 200u32 } }\n'
        '    i = i + 1u64\n  }\n  return 0u32\n}\n')



def report_checks(closed, failed, first, trace):
    return ('    if rep.closed != %du32 { return 51u32 }\n    if rep.failed != %du32 { return 52u32 }\n'
            '    if rep.first != %du32 { return 53u32 }\n    if rep.trace != %du32 { return 54u32 }\n' % (closed, failed, first, trace))


class FallibleCloseTests(CleanupCase):
    def run_close(self, failing, count, closed, failed, first, results, weights=None):
        self.both(self.source(CLOSE_TOK(failing, weights) + FILL +
            'func main() u32 !{memory.read,memory.write} {\n  let c = seq.new<Tok>(0u32)\n  match c { Ok(s) {\n    let code u32 = fill(borrow_mut(s), %du64)\n'
            '    let rep seq.CloseReport = seq.close_all<Tok>(move(s))\n    if code != 0u32 { return code }\n' % count +
            report_checks(closed, failed, first, digest(results)) + '    return 42u32\n  } Err(e) { return e } }\n}\n'))

    def test_a_failing_close_keeps_its_error_and_every_other_element_is_still_closed(self):
        # ids 1..5 are closed 5,4,3,2,1; id 3 fails with 33
        self.run_close({3: 33}, 5, 5, 1, 33, [('ok', 1), ('ok', 2), ('err', 33), ('ok', 1), ('ok', 1)], {4: 2})

    def test_with_several_failures_the_first_in_closing_order_is_kept_and_all_are_counted(self):
        # closing order 5,4,3,2,1: id 4 (44) fails before id 2 (22)
        self.run_close({4: 44, 2: 22}, 5, 5, 2, 44, [('ok', 3), ('err', 44), ('ok', 1), ('err', 22), ('ok', 1)], {5: 3})

    def test_every_element_failing_still_closes_them_all(self):
        self.run_close({1: 11, 2: 12, 3: 13}, 3, 0, 3, 13, [('err', 13), ('err', 12), ('err', 11)])

    def test_an_empty_sequence_reports_nothing(self):
        self.run_close({}, 0, 0, 0, 0, [])

    def test_the_error_of_a_close_is_a_value_the_caller_receives_and_the_element_is_gone(self):
        # a close that fails returns its code; the element was consumed either way, so closing it again is refused by the checker
        self.both(self.source(CLOSE_TOK({7: 77}) +
            'func main() u32 !{memory.write} {\n  let r = seq.Close.finish<Tok>(mint(7u64))\n'
            '  match r { Ok(n) { return 1u32 } Err(code) { if code == 77u32 { return 42u32 } return 2u32 } }\n}\n'))
        self.rejected(CLOSE_TOK({}) +
            'func main() u32 !{memory.write} {\n  let x = mint(7u64)\n  let r = seq.Close.finish<Tok>(move(x))\n  let q = seq.Close.finish<Tok>(move(x))\n  return 0u32\n}\n',
            b'E_RESOURCE_MOVED')

    def test_nothing_closes_an_element_behind_the_programs_back(self):
        # a Resource whose type has a fallible close is never dropped by cleanup: leaving it unconsumed does not compile
        self.rejected(CLOSE_TOK({}) + 'func main() u32 !{memory.write} {\n  let x = mint(7u64)\n  return 0u32\n}\n', b'E_RESOURCE_UNCONSUMED')
        self.rejected(CLOSE_TOK({}) +
            'func main() u32 !{memory.read,memory.write} {\n  let c = seq.new<Tok>(1u32)\n  match c { Ok(s) {\n    return 0u32\n  } Err(e) { return e } }\n}\n',
            b'E_RESOURCE_UNCONSUMED')

    def test_the_ending_of_a_sequence_is_chosen_by_the_trait_the_element_implements(self):
        # Tok implements Dispose only: close_all needs Close; destroy needs Dispose
        self.rejected(TOK +
            'func main() u32 !{memory.read,memory.write} {\n  let c = seq.new<Tok>(1u32)\n  match c { Ok(s) {\n    let rep seq.CloseReport = seq.close_all<Tok>(move(s))\n'
            '    return 0u32\n  } Err(e) { return e } }\n}\n', b'E_GENERIC_CONSTRAINT')
        self.rejected(CLOSE_TOK({}) +
            'func main() u32 !{memory.read,memory.write} {\n  let c = seq.new<Tok>(1u32)\n  match c { Ok(s) {\n    let d u32 = seq.destroy<Tok>(move(s))\n'
            '    return d\n  } Err(e) { return e } }\n}\n', b'E_GENERIC_CONSTRAINT')


# A sequence of blobs: each blob owns a buffer that is allocated and then grown, so a build crosses four kinds of acquisition point
BLOBC = ('struct Blob { b Resource<Buffer> }\n'
         'func blob(n u32, tag u32) Result<Resource<Blob>,u32> !{memory.write} {\n  let a = buffer.alloc(n)\n'
         '  match a { Ok(buf) {\n    let g = buffer.grow(borrow_mut(buf), n + 4u32)\n'
         '    match g {\n      Ok(m) {\n        let w = buffer.write_u32le(borrow_mut(buf), 0u32, tag)\n        match w { Ok(k) { } Err(e) { } }\n'
         '        let i Blob = Blob { b: move(buf) }\n        return Ok<Resource<Blob>,u32>(resource.seal(move(i)))\n      }\n'
         '      Err(e) { let z u32 = buffer.release(move(buf))\n        return Err<Resource<Blob>,u32>(e + 20u32) }\n    }\n'
         '  } Err(e) { return Err<Resource<Blob>,u32>(e + 10u32) } }\n}\n'
         # the tag lives in the first four bytes of the element's own buffer; an odd tag makes the close fail AFTER the buffer was released
         'impl seq.Close for Blob { func finish(x Resource<Blob>) Result<u32,u32> !{memory.read,memory.write} {\n'
         '  let i Blob = resource.unseal(move(x))\n  var tag u32 = 9999u32\n  let t = buffer.read_u32le(borrow(i.b), 0u32)\n  match t { Ok(v) { tag = v } Err(e) { } }\n'
         '  let z u32 = buffer.release(move(i.b))\n'
         '  if tag % 2u32 == 1u32 { return Err<u32,u32>(tag + 50u32) }\n  return Ok<u32,u32>(1u32)\n} }\n')
SWEEP = (BLOBC +
         'func build(s BorrowMut<seq.Seq<Blob>>, n u32) u32 !{memory.read,memory.write} {\n  var i u32 = 0u32\n  for i < n {\n    let b = blob(4u32, i)\n'
         '    match b { Ok(x) {\n      let g = seq.reserve<Blob>(borrow_mut(s))\n'
         '      match g { Ok(c) { } Err(e) {\n        let r = seq.Close.finish<Blob>(move(x))\n        match r { Ok(k) { } Err(k) { } }\n        return 30u32 + e } }\n'
         '      let p = seq.push<Blob>(borrow_mut(s), move(x))\n'
         '      match p { Ok(k) { } Err(back) {\n        let r = seq.Close.finish<Blob>(move(back))\n        match r { Ok(k) { } Err(k) { } }\n        return 99u32 } }\n'
         '    } Err(e) { return e } }\n    i = i + 1u32\n  }\n  return 0u32\n}\n'
         'func main() u32 !{memory.read,memory.write} {\n  let c = seq.new<Blob>(0u32)\n  match c { Ok(s) {\n    let code u32 = build(borrow_mut(s), 5u32)\n'
         '    let rep seq.CloseReport = seq.close_all<Blob>(move(s))\n    if code != 0u32 { return code }\n'
         '    if rep.closed != 3u32 { return 61u32 }\n    if rep.failed != 2u32 { return 62u32 }\n    if rep.first != 53u32 { return 63u32 }\n    return 42u32\n'
         '  } Err(e) { return 50u32 + e } }\n}\n')
# the acquisition points in the order they happen, and the code the program returns when that one fails (outcome 3 plus the site base)
SITE_NEW, SITE_BLOB_ALLOC, SITE_BLOB_GROW, SITE_RESERVE = 53, 13, 23, 33
POINTS = [SITE_NEW] + [SITE_BLOB_ALLOC, SITE_BLOB_GROW, SITE_RESERVE] + [SITE_BLOB_ALLOC, SITE_BLOB_GROW] * 3 + [SITE_BLOB_ALLOC, SITE_BLOB_GROW, SITE_RESERVE]


class FaultAuditTests(CleanupCase):
    def test_a_fault_leaves_the_audit_showing_what_was_still_live_and_both_engines_agree(self):
        # freeing a buffer that still owns a resource is a fault: the program stops with the cell occupied, the audit says one buffer is live, and the oracle
        # classifies it as a premature release of the container (not as a leak, not as clean)
        path = self.source(TOK +
            'func main() u32 !{memory.read,memory.write} {\n  let a = slots.alloc<Tok>(1u32)\n'
            '  match a { Ok(b) {\n    let p = slots.put<Tok>(borrow_mut(b), 0u32, mint(1u64))\n    match p { Ok(i) { } Err(back) { let z u64 = eat(move(back)) } }\n'
            '    return 0u32\n  } Err(e) { return e } }\n}\n', 'occupied.omni')
        ev, nat = self.run_both(path, {'OMNI_RESOURCE_AUDIT': '1'})
        for who, (rc, err) in (('evaluator', ev), ('native', nat)):
            self.assertNotEqual(rc, 0, who)
            self.assertIn(b'E_SLOT_OCCUPIED', err, who)
            self.assertEqual(classify(err), 'PREMATURE_RELEASE', who)
        self.assertEqual(audit_lines(ev[1]), ['audit acq 1', 'audit summary acquired=1 released=0 live=1'])
        self.assertEqual(audit_lines(nat[1]), audit_lines(ev[1]))


class InjectedFailureTests(CleanupCase):
    def test_a_failure_injected_at_every_acquisition_point_leaves_no_leak_no_double_release_and_a_typed_exit(self):
        path = self.source(SWEEP, 'sweep.omni')
        seen = set()
        for n in range(1, len(POINTS) + 2):
            with self.subTest(fail_at=n):
                ev, nat = self.run_both(path, {'OMNI_FAIL_AT': str(n), 'OMNI_RESOURCE_AUDIT': '1'})
                expected = POINTS[n - 1] if n <= len(POINTS) else 42
                self.assertEqual(ev[0], expected, ev[1])
                self.assertEqual(nat[0], expected, nat[1])
                # both engines make the same acquisitions and releases in the same order, and none is left over
                self.assertEqual(audit_lines(ev[1]), audit_lines(nat[1]))
                self.assertEqual(classify(ev[1]), 'CLEAN', ev[1])
                self.assertEqual(classify(nat[1]), 'CLEAN', nat[1])
                if n <= len(POINTS):
                    seen.add(expected)
        # the sweep reached every kind of point in the catalogue: slots.alloc, buffer.alloc, buffer.grow and slots.grow
        self.assertEqual(seen, {SITE_NEW, SITE_BLOB_ALLOC, SITE_BLOB_GROW, SITE_RESERVE})

    def test_without_an_injection_the_whole_build_runs_and_is_clean(self):
        path = self.source(SWEEP, 'sweep.omni')
        ev, nat = self.run_both(path, {'OMNI_RESOURCE_AUDIT': '1'})
        self.assertEqual((ev[0], nat[0]), (42, 42), (ev[1], nat[1]))
        self.assertEqual(audit_lines(ev[1]), audit_lines(nat[1]))
        self.assertIn('audit summary acquired=6 released=6 live=0', audit_lines(ev[1]))

    def test_an_unset_zero_or_malformed_injection_value_injects_nothing(self):
        path = self.source(SWEEP, 'sweep.omni')
        for value in ('0', '', 'x', '1x', '-1'):
            with self.subTest(value=value):
                ev, nat = self.run_both(path, {'OMNI_FAIL_AT': value})
                self.assertEqual((ev[0], nat[0]), (42, 42))


HARNESS = r'''
#include <stdint.h>
#include <stdio.h>
#include <string.h>
uint32_t omni_buffer_alloc(uint32_t n, uint64_t *out);
uint32_t omni_buffer_release(uint64_t h);
uint32_t omni_buffer_len(uint64_t h);
uint32_t omni_slots_alloc(const char *tag, uint32_t cells, uint64_t *out);
uint32_t omni_slots_put(uint64_t h, const char *tag, uint32_t i, uint64_t v);
uint32_t omni_slots_take(uint64_t h, const char *tag, uint32_t i, uint64_t *out);
uint32_t omni_slots_release(uint64_t h);
uint32_t omni_buffer_freeze(uint64_t h, uint64_t *out);
int main(int argc, char **argv) {
    const char *s = argv[1]; uint64_t a = 0, b = 0, c = 0, v = 0;
    if (!strcmp(s, "clean")) { omni_buffer_alloc(4, &a); omni_buffer_release(a); return 0; }
    if (!strcmp(s, "leak")) { omni_buffer_alloc(4, &a); return 0; }
    if (!strcmp(s, "leak_one_of_three")) { omni_buffer_alloc(4, &a); omni_buffer_alloc(4, &b); omni_buffer_alloc(4, &c); omni_buffer_release(a); omni_buffer_release(c); return 0; }
    if (!strcmp(s, "double_release")) { omni_buffer_alloc(4, &a); omni_buffer_release(a); omni_buffer_release(a); return 0; }
    if (!strcmp(s, "use_after_release")) { omni_buffer_alloc(4, &a); omni_buffer_release(a); omni_buffer_len(a); return 0; }
    if (!strcmp(s, "use_after_release_slot_reused")) { omni_buffer_alloc(4, &a); omni_buffer_release(a); omni_buffer_alloc(4, &b); omni_buffer_len(a); return 0; }
    if (!strcmp(s, "double_release_slot_reused")) { omni_buffer_alloc(4, &a); omni_buffer_release(a); omni_buffer_alloc(4, &b); omni_buffer_release(a); return 0; }
    if (!strcmp(s, "double_slots_release")) { omni_slots_alloc("T", 1, &a); omni_slots_release(a); omni_slots_release(a); return 0; }
    if (!strcmp(s, "double_freeze")) { omni_buffer_alloc(4, &a); omni_buffer_freeze(a, &v); omni_buffer_freeze(a, &v); return 0; }
    if (!strcmp(s, "use_after_freeze")) { omni_buffer_alloc(4, &a); omni_buffer_freeze(a, &v); omni_buffer_len(a); return 0; }
    if (!strcmp(s, "forged_zero")) { omni_buffer_len(0); return 0; }
    if (!strcmp(s, "forged_range")) { omni_buffer_len(99999); return 0; }
    if (!strcmp(s, "forged_generation")) { omni_buffer_alloc(4, &a); omni_buffer_len((a & 0xffffffffu) | (99ull << 32)); return 0; }
    if (!strcmp(s, "container_with_an_owner_released")) { omni_slots_alloc("T", 2, &a); omni_slots_put(a, "T", 0, 5); omni_buffer_release(a); return 0; }
    if (!strcmp(s, "container_refuses_while_occupied")) {
        omni_slots_alloc("T", 2, &a); omni_slots_put(a, "T", 0, 5);
        if (omni_slots_release(a) != 1) return 11;
        if (omni_slots_take(a, "T", 0, &v) != 0 || v != 5) return 12;
        return omni_slots_release(a) == 0 ? 0 : 13;
    }
    if (!strcmp(s, "injected")) { uint32_t r1 = omni_buffer_alloc(4, &a); uint32_t r2 = omni_buffer_alloc(4, &b); if (!r1) omni_buffer_release(a); if (!r2) omni_buffer_release(b); return (int)(r1 * 10 + r2); }
    return 99;
}
'''


class ResourceOracleTests(unittest.TestCase):
    """The oracle on the C runtime driven directly: the misuses an Omni program cannot write, each classified as what it is."""
    @classmethod
    def setUpClass(cls):
        import tempfile
        cls.tmp = tempfile.TemporaryDirectory(prefix='omni-cp03-')
        src = os.path.join(cls.tmp.name, 'oracle.c')
        with open(src, 'w', encoding='utf-8') as f:
            f.write(HARNESS)
        cls.exe = os.path.join(cls.tmp.name, 'oracle')
        flags = ['-O1', '-g'] + (['-fsanitize=address,undefined', '-fno-omit-frame-pointer'] if os.environ.get('OMNI_NATIVE_SANITIZE') == '1' else [])
        built = subprocess.run(['clang', *flags, src, str(ROOT / 'runtime' / 'omni_runtime.c'), '-o', cls.exe, '-lcrypto'], capture_output=True, timeout=300)
        assert built.returncode == 0, built.stderr

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def run_scenario(self, name, env=None):
        merged = {**os.environ, 'OMNI_RESOURCE_AUDIT': '1', **(env or {})}
        done = subprocess.run([self.exe, name], capture_output=True, timeout=60, env=merged)
        return done.returncode, done.stderr

    def test_each_misuse_is_classified_as_what_it_is(self):
        cases = [
            ('clean', 0, 'CLEAN'),
            ('leak', 0, 'LEAK'),
            ('leak_one_of_three', 0, 'LEAK'),
            ('double_release', 70, 'DOUBLE_RELEASE'),
            ('use_after_release', 70, 'PREMATURE_RELEASE'),
            ('use_after_release_slot_reused', 70, 'PREMATURE_RELEASE'),
            ('double_release_slot_reused', 70, 'DOUBLE_RELEASE'),
            ('double_slots_release', 70, 'DOUBLE_RELEASE'),
            ('double_freeze', 70, 'DOUBLE_RELEASE'),
            ('use_after_freeze', 70, 'PREMATURE_RELEASE'),
            ('forged_zero', 70, 'FORGED_HANDLE'),
            ('forged_range', 70, 'FORGED_HANDLE'),
            ('forged_generation', 70, 'FORGED_HANDLE'),
            ('container_with_an_owner_released', 70, 'PREMATURE_RELEASE'),
            ('container_refuses_while_occupied', 0, 'CLEAN'),
        ]
        for name, rc, verdict in cases:
            with self.subTest(name):
                got_rc, err = self.run_scenario(name)
                self.assertEqual(got_rc, rc, err)
                self.assertEqual(classify(err), verdict, err)

    def test_the_specific_fault_is_named_not_a_generic_handle_error(self):
        for name, code in (('double_release', b'E_RESOURCE_DOUBLE_RELEASE'), ('use_after_release', b'E_RESOURCE_STALE_USE'),
                           ('double_release_slot_reused', b'E_RESOURCE_DOUBLE_RELEASE'), ('use_after_release_slot_reused', b'E_RESOURCE_STALE_USE'),
                           ('forged_generation', b'E_RESOURCE_HANDLE'), ('container_with_an_owner_released', b'E_SLOT_OCCUPIED')):
            with self.subTest(name):
                self.assertIn(code, self.run_scenario(name)[1])

    def test_a_net_zero_total_is_not_enough(self):
        # one acquisition, one release: acquired == released, yet the run used the buffer after releasing it
        rc, err = self.run_scenario('use_after_release')
        self.assertIn(b'acquired=1 released=1 live=0', err)
        self.assertEqual(classify(err), 'PREMATURE_RELEASE')
        # three acquisitions, two releases: one leak, even though two of the three are balanced
        rc, err = self.run_scenario('leak_one_of_three')
        self.assertIn(b'acquired=3 released=2 live=1', err)

    def test_the_injection_fails_exactly_the_requested_acquisition(self):
        self.assertEqual(self.run_scenario('injected')[0], 0)
        self.assertEqual(self.run_scenario('injected', {'OMNI_FAIL_AT': '1'})[0], 30)
        self.assertEqual(self.run_scenario('injected', {'OMNI_FAIL_AT': '2'})[0], 3)
        self.assertEqual(self.run_scenario('injected', {'OMNI_FAIL_AT': '3'})[0], 0)


if __name__ == '__main__':
    unittest.main()
