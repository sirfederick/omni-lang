#!/usr/bin/env python3
"""CP-01: pending ownership of Option<Record>, including recursive leaves.

The allocation oracle exceeds the runtime's 1024 handle limit; success requires
cleanup, rather than merely accepting a program with the right static type.
"""
from __future__ import annotations
import os
import pathlib
import json
import hashlib
import tempfile
import unittest
from language_0_8_3_alpha8 import ROOT, OMNI, proc


class OptionOwningRecordTests(unittest.TestCase):
    DECL = ('struct Leaf { buf Resource<Buffer>, tag u32 }\n'
            'struct Owned { leaf Leaf, spare Resource<Buffer> }\n')
    SLOT = (DECL + 'func slot(make bool) Option<Owned> !{memory.write} {\n'
            '  if make {\n'
            '    let a = buffer.alloc(4u32)\n    match a {\n    Ok(x) {\n'
            '      let b = buffer.alloc(2u32)\n      match b {\n      Ok(y) {\n'
            '        let r = Owned { leaf: Leaf { buf: move(x), tag: 36u32 }, spare: move(y) }\n'
            '        return Some<Owned>(move(r))\n'
            '      } Err(code) { return None<Owned>() }\n      }\n'
            '    } Err(code) { return None<Owned>() }\n    }\n  }\n'
            '  return None<Owned>()\n}\n')
    FINISH = ('func finish(o Option<Owned>) u32 !{memory.read} {\n'
              '  match o { Some(r) { return r.leaf.tag + buffer.len(borrow(r.leaf.buf))'
              ' + buffer.len(borrow(r.spare)) } None { return 0u32 } }\n}\n')

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='omni-option-record-')
        self.dir = pathlib.Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def source(self, text, name='program.omni'):
        path = self.dir / name
        path.write_text('module t\n' + text, encoding='utf-8')
        return path

    def both(self, path, expected=42):
        evaluated = proc(OMNI, 'eval', path)
        self.assertEqual(evaluated.returncode, expected, evaluated.stderr)
        native = self.dir / (path.name + '-native')
        built = proc(OMNI, 'build', path, '-o', native, '--cache-dir', self.dir/'cache')
        self.assertEqual(built.returncode, 0, built.stderr)
        executed = proc(native)
        self.assertEqual(executed.returncode, expected, executed.stderr)

    def rejected(self, text, code):
        path = self.source(text, 'bad.omni')
        checked = proc(OMNI, 'check', path)
        self.assertEqual(checked.returncode, 2, checked.stderr)
        self.assertIn(code, checked.stderr)
        output = self.dir/'never'
        built = proc(OMNI, 'build', path, '-o', output, '--cache-dir', self.dir/'cache')
        self.assertEqual(built.returncode, 2, built.stderr)
        self.assertFalse(output.exists())

    def test_call_return_some_none_and_nested_record_cleanup(self):
        self.both(self.source(self.SLOT + self.FINISH +
            'func main() u32 !{memory.read,memory.write} {\n'
            '  let o = slot(true)\n  let a = finish(o)\n'
            '  return a + finish(slot(false))\n}\n'))

    def test_cleanup_exceeds_slot_capacity_on_continue_break_and_return(self):
        self.both(self.source(self.SLOT + self.FINISH +
            'func early(o Option<Owned>) u32 {\n'
            '  match o { Some(r) { return 1u32 } None { return 0u32 } }\n}\n'
            'func main() u32 !{memory.read,memory.write} {\n'
            '  var i u32 = 0u32\n  var done u32 = 0u32\n'
            '  for i < 3000u32 {\n    i = i + 1u32\n'
            '    let o = slot(true)\n    match o {\n'
            '      Some(r) {\n        done = done + 1u32\n'
            '        if i < 1500u32 { continue }\n        break\n'
            '      } None { return 2u32 }\n    }\n  }\n'
            '  for i < 4500u32 {\n    i = i + 1u32\n'
            '    done = done + early(slot(true))\n  }\n'
            '  if done == 4500u32 { return finish(slot(true)) }\n'
            '  return 3u32\n}\n'))

    def test_pending_laws_and_no_implicit_discard(self):
        cases = (
            ('let o = slot(true)\nreturn 0u32', b'E_RESULT_UNHANDLED'),
            ('let o = slot(false)\nreturn 0u32', b'E_RESULT_UNHANDLED'),
            ('var o = slot(true)\nreturn 0u32', b'E_RESULT_MUTABLE'),
            ('let o = slot(true)\nlet a = finish(o)\nreturn finish(o)', b'E_RESULT_MOVED'),
            ('let o = slot(true)\nmatch o { Some(_) { return 0u32 } None { return 0u32 } }', b'E_RESOURCE_UNCONSUMED'),
            ('let o = slot(true)\nif true { let a = finish(o) }\nreturn 0u32', b'E_RESULT_FLOW'),
            ('let o = slot(true)\nvar i u32 = 0u32\nfor i < 2u32 { let a = finish(o)\ni = i + 1u32 }\nreturn 0u32', b'E_RESULT_FLOW'),
            ('let o = slot(true)\nreturn closure(x u32) u32 { return finish(o) }(0u32)', b'E_CLOSURE_CAPTURE'),
        )
        for body, code in cases:
            with self.subTest(body=body):
                self.rejected(self.SLOT + self.FINISH +
                    'func main() u32 !{memory.read,memory.write} {\n' + body + '\n}\n', code)

    def test_nested_containers_remain_fail_closed(self):
        for ty, code in (('Option<Option<Owned>>', b'E_RESULT_UNHANDLED'),
                         ('Result<Option<Owned>,u32>', b'E_RESULT_UNHANDLED'),
                         ('Tuple<u32,Option<Owned>>', b'E_RESULT_UNHANDLED'),
                         ('Array<Option<Owned>,2>', b'E_RESULT_UNHANDLED')):   # CP-01: Array is an owning product like Tuple; the pending law applies
            with self.subTest(type=ty):
                self.rejected(self.DECL + f'func f(o {ty}) u32 {{ return 0u32 }}\n'
                    'func main() u32 { return 0u32 }\n', code)
        self.rejected(self.DECL + 'struct Hidden { o Option<Owned> }\n'
            'func bad(h Hidden) u32 { return 0u32 }\nfunc main() u32 { return 0u32 }\n', b'E_RESULT_UNHANDLED')

    def test_copy_record_option_remains_copy(self):
        self.both(self.source('struct Plain { n u32 }\n'
            'func f(o Option<Plain>) u32 { match o { Some(p) { return p.n } None { return 0u32 } } }\n'
            'func main() u32 { let o = Some<Plain>(Plain { n: 21u32 })\nreturn f(o) + f(o) }\n'))

    def test_generic_record_payload_moves_and_roundtrips(self):
        path = self.source('struct Box<T> { value T }\n'
            'func main() u32 !{memory.read,memory.write} {\n'
            '  let a = buffer.alloc(42u32)\n  match a { Ok(b) {\n'
            '    let r = Box<Resource<Buffer>> { value: move(b) }\n'
            '    let o = Some<Box<Resource<Buffer>>>(move(r))\n'
            '    match o { Some(p) { return buffer.len(borrow(p.value)) } None { return 1u32 } }\n'
            '  } Err(code) { return code } }\n}\n')
        self.both(path)
        wave = proc(OMNI, 'wave', path)
        self.assertEqual(wave.returncode, 0, wave.stderr)
        artifact = self.dir/'generic.owave'
        artifact.write_bytes(wave.stdout)
        self.both(artifact)

    def test_closure_free_places_cannot_hide_owning_or_mutable_roots(self):
        for body in ('return buffer.len(borrow(r.leaf.buf)) + x',
                     'return r.leaf.tag + x',
                     'let done = buffer.release(move(r.leaf.buf))\nreturn done + x'):
            with self.subTest(body=body):
                self.rejected(self.SLOT + 'func main() u32 !{memory.read,memory.write} {\n'
                    '  let o = slot(true)\n  match o { Some(r) {\n'
                    '    return closure(x u32) u32 { ' + body + ' }(0u32)\n'
                    '  } None { return 1u32 } }\n}\n', b'E_CLOSURE_CAPTURE')
        self.rejected('func main() u32 { var p u32 = 1u32\n'
            '  let y = closure(x u32) u32 { p = 40u32\nreturn x }(2u32)\n'
            '  return p + y\n}\n', b'E_CLOSURE_CAPTURE')
        for prepare, access in (('', 'borrow(b)'), ('let reader = borrow(b)\n', 'borrow(reader)')):
            self.rejected('func main() u32 !{memory.read,memory.write} {\n'
                '  let a = buffer.alloc(4u32)\n  match a { Ok(b) {\n' + prepare +
                '    return closure(x u32) u32 { return buffer.len(' + access + ') + x }(38u32)\n'
                '  } Err(code) { return code } }\n}\n', b'E_CLOSURE_CAPTURE')

    def test_copy_record_field_capture_and_wide_closure_result(self):
        self.both(self.source('struct Plain { n u32 }\nfunc main() u32 {\n'
            '  let p = Plain { n: 40u32 }\n'
            '  return closure(x u32) u32 { return p.n + x }(2u32)\n}\n', 'copy-capture.omni'))
        self.both(self.source('func main() u32 {\n'
            '  let value = closure(x u64) u64 { return x + 2u64 }(40u64)\n'
            '  if value == 42u64 { return 42u32 }\n  return 1u32\n}\n', 'wide-result.omni'))

    def test_closure_result_cannot_forge_ownership_or_mismatch_its_annotation(self):
        for result, value, code in (
            ('Resource<Buffer>', '1u32', b'E_CLOSURE_CAPTURE'),
            ('Borrow<Buffer>', '1u32', b'E_CLOSURE_CAPTURE'),
            ('Result<u32,u32>', '1u32', b'E_CLOSURE_CAPTURE'),
            ('u64', '42u32', b'E_TYPE'), ('u32', '42u64', b'E_TYPE'),
        ):
            with self.subTest(result=result, value=value):
                self.rejected('func main() u32 {\n  let value = closure() ' + result +
                    ' { return ' + value + ' }()\n  return 0u32\n}\n', code)

    def test_copy_projection_bound_outside_owning_payload_is_safe_capture(self):
        self.both(self.source(self.SLOT +
            'func main() u32 !{memory.read,memory.write} {\n'
            '  let o = slot(true)\n  match o { Some(r) {\n'
            '    let n = r.leaf.tag + buffer.len(borrow(r.leaf.buf)) + buffer.len(borrow(r.spare))\n'
            '    return closure(x u32) u32 { return n + x }(0u32)\n'
            '  } None { return 1u32 } }\n}\n'))

    def test_aggregate_transfer_rejects_live_loan_and_reused_leaves(self):
        prefix = ('struct Leaf { buf Resource<Buffer> }\n'
            'func main() u32 !{memory.read,memory.write} {\n'
            '  let a = buffer.alloc(1u32)\n  match a { Ok(b) {\n'
            '    let r = Leaf { buf: move(b) }\n')
        suffix = '\n  } Err(code) { return code } }\n}\n'
        cases = (
            ('let loan = borrow(r.buf)\nlet o = Some<Leaf>(move(r))\n'
             'return buffer.len(loan)', b'E_BORROW_CONFLICT'),
            ('let o = Some<Leaf>(move(r))\nreturn buffer.len(borrow(r.buf))', b'E_RESOURCE_MOVED'),
            ('let gone = buffer.release(move(r.buf))\nlet o = Some<Leaf>(move(r))\n'
             'return gone', b'E_RESOURCE_MOVED'),
            ('let o = Some<Leaf>(r)\nreturn 0u32', b'E_RESOURCE_ACCESS'),
        )
        for body, code in cases:
            with self.subTest(body=body):
                self.rejected(prefix + body + suffix, code)

    def test_fence_and_roundtrips_preserve_ownership(self):
        path = self.source(self.SLOT + self.FINISH +
            'func main() u32 !{memory.read,memory.write} { return finish(slot(true)) }\n')
        wave = proc(OMNI, 'wave', path)
        self.assertEqual(wave.returncode, 0, wave.stderr)
        self.assertTrue(wave.stdout.startswith(b'(omni-wave 21'))
        text = self.dir/'o.owave'
        text.write_bytes(wave.stdout)
        wire = self.dir/'o.owire'
        self.assertEqual(proc(OMNI, 'pack', path, '-o', wire).returncode, 0)
        onme = self.dir/'o.onme'
        self.assertEqual(proc(OMNI, 'onme', path, '-o', onme).returncode, 0)
        memory = proc(OMNI, 'memory', path)
        self.assertEqual(memory.returncode, 0, memory.stderr)
        for artifact in (text, wire, onme):
            with self.subTest(artifact=artifact.name):
                self.assertEqual(proc(OMNI, 'wave', artifact).stdout, wave.stdout)
                projection = proc(OMNI, 'memory', artifact)
                self.assertEqual(projection.returncode, 0, projection.stderr)
                self.assertEqual(projection.stdout, memory.stdout)
                self.both(artifact)
        text.write_bytes(wave.stdout.replace(b'(omni-wave 21', b'(omni-wave 20', 1))
        raw = bytearray(wire.read_bytes()); raw[4] = 20; wire.write_bytes(raw)
        for artifact in (text, wire):
            checked = proc(OMNI, 'check', artifact)
            self.assertEqual(checked.returncode, 2, checked.stderr)
            self.assertIn(b'E_VERSION', checked.stderr)

    def test_signature_only_owning_option_is_fenced(self):
        path = self.source(self.DECL + 'func consume(o Option<Owned>) u32 {\n'
            '  match o { Some(r) { return 1u32 } None { return 0u32 } }\n}\n'
            'func main() u32 { return 0u32 }\n')
        wave = proc(OMNI, 'wave', path)
        self.assertEqual(wave.returncode, 0, wave.stderr)
        self.assertTrue(wave.stdout.startswith(b'(omni-wave 21'))
        old = self.dir/'old.owave'
        old.write_bytes(wave.stdout.replace(b'(omni-wave 21', b'(omni-wave 20', 1))
        checked = proc(OMNI, 'check', old)
        self.assertEqual(checked.returncode, 2, checked.stderr)
        self.assertIn(b'E_VERSION', checked.stderr)

    def test_import_alias_uses_canonical_record_ownership(self):
        (self.dir/'payload.omni').write_text('module payload\n'
            'pub struct Owned { buf Resource<Buffer> }\n', encoding='utf-8')
        path = self.source('import alias "payload.omni"\n'
            'func take(o Option<alias.Owned>) u32 !{memory.read} {\n'
            '  match o { Some(p) { return buffer.len(borrow(p.buf)) } None { return 0u32 } }\n}\n'
            'func main() u32 !{memory.read,memory.write} {\n'
            '  let a = buffer.alloc(42u32)\n  match a { Ok(b) {\n'
            '    return take(Some<alias.Owned>(alias.Owned { buf: move(b) }))\n'
            '  } Err(code) { return code } }\n}\n')
        self.both(path)
        wave = proc(OMNI, 'wave', path)
        self.assertEqual(wave.returncode, 0, wave.stderr)
        artifact = self.dir/'import.owave'
        artifact.write_bytes(wave.stdout)
        self.both(artifact)
        artifact.write_bytes(wave.stdout.replace(b'(omni-wave 21', b'(omni-wave 20', 1))
        checked = proc(OMNI, 'check', artifact)
        self.assertEqual(checked.returncode, 2, checked.stderr)
        self.assertIn(b'E_VERSION', checked.stderr)

    def test_forged_wave_cannot_copy_mutate_or_discard_ownership(self):
        path = self.source(self.SLOT + self.FINISH +
            'func main() u32 !{memory.read,memory.write} {\n'
            '  let o = slot(true)\n  let fresh = slot(false)\n'
            '  let a = finish(o)\n  return a + finish(fresh)\n}\n')
        wave = proc(OMNI, 'wave', path)
        self.assertEqual(wave.returncode, 0, wave.stderr)
        for before, after, code in (
            (b'(call finish (ref fresh))', b'(call finish (ref o))', b'E_RESULT_MOVED'),
            (b'(let o infer', b'(var o infer', b'E_RESULT_MUTABLE'),
            (b'(some r (block', b'(some _ (block', b'E_RESOURCE_UNCONSUMED'),
        ):
            with self.subTest(diagnostic=code):
                self.assertIn(before, wave.stdout)
                forged = self.dir/'forged.owave'
                forged.write_bytes(wave.stdout.replace(before, after, 1))
                checked = proc(OMNI, 'check', forged)
                self.assertEqual(checked.returncode, 2, checked.stderr)
                self.assertIn(code, checked.stderr)
                output = self.dir/'forged.owire'
                packed = proc(OMNI, 'pack', forged, '-o', output)
                self.assertEqual(packed.returncode, 2, packed.stderr)
                self.assertFalse(output.exists())

    def test_owning_field_requires_explicit_transfer_in_every_value_context(self):
        prefix = (self.DECL + 'struct Box { payload Leaf }\n'
                  'func take(b Resource<Buffer>) u32 !{memory.write} { return buffer.release(move(b)) }\n'
                  'func main() u32 !{memory.read,memory.write} {\n'
                  ' let a = buffer.alloc(42u32)\n match a { Ok(b) {\n'
                  ' let p = Box { payload: Leaf { buf: move(b), tag: 42u32 } }\n')
        for body in (
            'let alias = p.payload.buf; return buffer.len(borrow(alias))',
            'let alias = p.payload; return alias.tag',
            'return take(p.payload.buf)',
            'let o = Some<Leaf>(p.payload); match o { Some(q) { return q.tag } None { return 0u32 } }',
            'let copy = Box { payload: p.payload }; return copy.payload.tag',
            'let loan = borrow_mut(p.payload.buf); let alias = p.payload.buf; return buffer.len(loan)',
        ):
            with self.subTest(body=body):
                self.rejected(prefix + body + '\n } Err(code) { return code } }\n}\n', b'E_RESOURCE_ACCESS')

    def test_forged_field_value_cannot_bypass_explicit_move(self):
        source = self.source('struct Leaf { buf Resource<Buffer> }\n'
            'func take(b Resource<Buffer>) u32 !{memory.write} { return buffer.release(move(b)) }\n'
            'func main() u32 !{memory.write} { let a = buffer.alloc(1u32)\n'
            ' match a { Ok(b) { let p = Leaf { buf: move(b) }\n'
            ' return take(move(p.buf)) } Err(code) { return code } }\n}\n')
        encoded = proc(OMNI, 'wave', source)
        self.assertEqual(encoded.returncode, 0, encoded.stderr)
        explicit = b'(call move (field (ref p) buf))'
        self.assertIn(explicit, encoded.stdout)
        forged = self.dir/'field-copy.owave'
        forged.write_bytes(encoded.stdout.replace(explicit, b'(field (ref p) buf)', 1))
        for command in ('check', 'pack', 'build'):
            output = self.dir/f'forged-{command}'
            result = proc(OMNI, command, forged, *([] if command == 'check' else ['-o', output]))
            self.assertEqual(result.returncode, 2, result.stderr)
            self.assertIn(b'E_RESOURCE_ACCESS', result.stderr)
            self.assertFalse(output.exists())

    def test_owning_temporary_projection_cannot_abandon_resource(self):
        self.rejected(self.DECL +
            'func make() Leaf !{memory.write} {\n'
            ' let a = buffer.alloc(1u32)\n match a { Ok(b) { return Leaf { buf: move(b), tag: 42u32 } }\n'
            ' Err(code) { return make() } }\n}\n'
            'func main() u32 !{memory.write} { return make().tag }\n', b'E_RESOURCE_ACCESS')

    def test_explicit_nested_field_move_and_copy_projection_remain_valid(self):
        self.both(self.source(self.DECL + 'struct Box { payload Leaf }\n'
            'func main() u32 !{memory.read,memory.write} {\n'
            ' let a = buffer.alloc(2u32)\n match a { Ok(b) {\n'
            ' let p = Box { payload: Leaf { buf: move(b), tag: 40u32 } }\n'
            ' let n = p.payload.tag\n let q = move(p.payload)\n'
            ' return n + buffer.len(borrow(q.buf))\n } Err(code) { return code } }\n}\n'))
        self.both(self.source('struct Copy { n u32 }\n'
            'func make() Copy { return Copy { n: 42u32 } }\n'
            'func main() u32 { return make().n }\n', 'copy.omni'))

    def test_function_content_identity_includes_complete_body(self):
        for record in ('Plain', 'Owned'):
            nodes = []
            for literal in (1, 2):
                text = ('struct Plain { n u32 }\n' + self.DECL +
                    f'func f(o Option<{record}>) u32 {{\n'
                    f'  match o {{ Some(p) {{ return {literal}u32 }} None {{ return 0u32 }} }}\n}}\n'
                    'func main() u32 { return 0u32 }\n')
                memory = proc(OMNI, 'memory', self.source(text))
                self.assertEqual(memory.returncode, 0, memory.stderr)
                nodes.append(next(n for n in json.loads(memory.stdout)['nuclei']
                                  if n['kind'] == 'function' and n['name'] == 'f'))
            with self.subTest(record=record):
                self.assertNotEqual(nodes[0]['content_id'], nodes[1]['content_id'])
                for field in ('id', 'contract_id', 'type_id'):
                    self.assertEqual(nodes[0][field], nodes[1][field], field)

    def test_template_and_generated_function_content_is_not_statement_count(self):
        cases = (
            ('func f<T>(v Option<T>) Option<T> {\n'
             '  let marker = LITERALu32\n  let x = v?\n  return Some<T>(x)\n}\n'
             'func main() u32 { return 0u32 }\n', 'function-template'),
            ('struct Plain { n u32 }\nfunc f<T>(v Option<T>) u32 {\n'
             '  match v { Some(p) { return LITERALu32 } None { return 0u32 } }\n}\n'
             'func main() u32 { return f<Plain>(None<Plain>()) }\n', 'function'),
        )
        for source, kind in cases:
            nodes = []
            for literal in (1, 2):
                memory = proc(OMNI, 'memory', self.source(source.replace('LITERAL', str(literal))))
                self.assertEqual(memory.returncode, 0, memory.stderr)
                found = [n for n in json.loads(memory.stdout)['nuclei']
                         if n['kind'] == kind and n['name'] != 'main']
                self.assertEqual(len(found), 1, found)
                nodes.append(found[0])
            with self.subTest(kind=kind):
                self.assertNotEqual(nodes[0]['content_id'], nodes[1]['content_id'])

    def test_lowered_closure_body_is_included_in_function_identity(self):
        nodes = []
        for literal in (1, 2):
            source = ('func main() u32 { return closure(x u32) u32 { return x + '
                      + str(literal) + 'u32 }(40u32) }\n')
            path = self.source(source)
            memory = proc(OMNI, 'memory', path)
            self.assertEqual(memory.returncode, 0, memory.stderr)
            helpers = [n for n in json.loads(memory.stdout)['nuclei']
                       if n['kind'] == 'function' and n['name'] != 'main']
            self.assertEqual(len(helpers), 1)
            nodes.append(helpers[0])
            wave = proc(OMNI, 'wave', path)
            self.assertEqual(wave.returncode, 0, wave.stderr)
            artifact = self.dir/f'closure-{literal}.owave'
            artifact.write_bytes(wave.stdout)
            wire = self.dir/f'closure-{literal}.owire'
            onme = self.dir/f'closure-{literal}.onme'
            self.assertEqual(proc(OMNI, 'pack', path, '-o', wire).returncode, 0)
            self.assertEqual(proc(OMNI, 'onme', path, '-o', onme).returncode, 0)
            for derived in (artifact, wire, onme):
                projected = proc(OMNI, 'memory', derived)
                self.assertEqual(projected.returncode, 0, projected.stderr)
                self.assertEqual(projected.stdout, memory.stdout)
        self.assertNotEqual(nodes[0]['content_id'], nodes[1]['content_id'])
        for field in ('id', 'contract_id', 'type_id'):
            self.assertEqual(nodes[0][field], nodes[1][field], field)

    def test_onme_recomputed_commitment_cannot_bypass_validation_or_root(self):
        source = self.source(self.SLOT + self.FINISH +
            'func main() u32 !{memory.read,memory.write} {\n'
            '  let o = slot(true)\n  let fresh = slot(false)\n'
            '  let a = finish(o)\n  return a + finish(fresh)\n}\n')
        artifact = self.dir/'valid.onme'
        encoded = proc(OMNI, 'onme', source, '-o', artifact)
        self.assertEqual(encoded.returncode, 0, encoded.stderr)
        magic, root, author, commitment, body = artifact.read_bytes().split(b'\n', 4)
        self.assertEqual(magic, b'ONME3')
        self.assertIn(b'A5:fresh', body)
        offset = body.rindex(b'A5:fresh')
        forged_body = body[:offset] + b'A1:o' + body[offset+len(b'A5:fresh'):]
        forged_root = root[:-1] + (b'0' if root[-1:] != b'0' else b'1')
        for chosen_root, chosen_body, code in (
            (root, forged_body, b'E_RESULT_MOVED'),
            (forged_root, body, b'E_ONME'),
        ):
            material = b'omni.onme-envelope/3\n' + chosen_root[1:] + b'\n' + author[1:] + b'\n' + chosen_body
            committed = b'Csha256:' + hashlib.sha256(material).hexdigest().encode()
            forged = self.dir/'forged.onme'
            forged.write_bytes(b'\n'.join((magic, chosen_root, author, committed, chosen_body)))
            checked = proc(OMNI, 'check', forged)
            self.assertEqual(checked.returncode, 2, checked.stderr)
            self.assertIn(code, checked.stderr)
            output = self.dir/'forged-native'
            built = proc(OMNI, 'build', forged, '-o', output)
            self.assertEqual(built.returncode, 2, built.stderr)
            self.assertIn(code, built.stderr)
            self.assertFalse(output.exists())

    def test_legacy_onme2_fixture_and_algorithm_fences(self):
        for name in ('closure', 'copy_record', 'generic_try'):
            with self.subTest(legacy=name):
                legacy = ROOT/f'tests/corpus/core13/onme2_{name}_345.onme'
                origin = legacy.with_suffix('.omni')
                receipt = json.loads(legacy.with_suffix('.json').read_text(encoding='utf-8-sig'))
                self.assertEqual(hashlib.sha256(legacy.read_bytes()).hexdigest(), receipt['artifact_sha256'])
                self.assertEqual(hashlib.sha256(origin.read_bytes()).hexdigest(), receipt['source_sha256'])
                self.both(legacy, receipt['expected_eval'])
                expected = proc(OMNI, 'memory', origin)
                actual = proc(OMNI, 'memory', legacy)
                self.assertEqual(expected.returncode, 0, expected.stderr)
                self.assertEqual(actual.returncode, 0, actual.stderr)
                self.assertEqual(actual.stdout, expected.stdout)
        fixture = ROOT/'tests/corpus/core13/onme2_closure_345.onme'
        source = fixture.with_suffix('.omni')
        metadata = json.loads(fixture.with_suffix('.json').read_text(encoding='utf-8-sig'))
        self.assertEqual(hashlib.sha256(fixture.read_bytes()).hexdigest(), metadata['artifact_sha256'])
        self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), metadata['source_sha256'])
        current = proc(OMNI, 'memory', source)
        restored = proc(OMNI, 'memory', fixture)
        self.assertEqual(current.returncode, 0, current.stderr)
        self.assertEqual(restored.returncode, 0, restored.stderr)
        self.assertEqual(restored.stdout, current.stdout)
        encoded = self.dir/'current.onme'
        self.assertEqual(proc(OMNI, 'onme', source, '-o', encoded).returncode, 0)
        self.assertTrue(encoded.read_bytes().startswith(b'ONME3\n'))
        for payload, version in ((encoded.read_bytes(), b'2'), (fixture.read_bytes(), b'3')):
            _, root, author, _, body = payload.split(b'\n', 4)
            material = b'omni.onme-envelope/' + version + b'\n' + root[1:] + b'\n' + author[1:] + b'\n' + body
            commitment = b'Csha256:' + hashlib.sha256(material).hexdigest().encode()
            relabelled = self.dir/'wrong-algorithm.onme'
            relabelled.write_bytes(b'\n'.join((b'ONME'+version, root, author, commitment, body)))
            checked = proc(OMNI, 'check', relabelled)
            self.assertEqual(checked.returncode, 2, checked.stderr)
            self.assertIn(b'E_ONME', checked.stderr)
        unknown = self.dir/'unknown.onme'
        unknown.write_bytes(encoded.read_bytes().replace(b'ONME3\n', b'ONME4\n', 1))
        checked = proc(OMNI, 'check', unknown)
        self.assertEqual(checked.returncode, 2, checked.stderr)
        self.assertIn(b'E_VERSION', checked.stderr)


class NominalRecordOwnershipTests(unittest.TestCase):
    setUp = OptionOwningRecordTests.setUp
    tearDown = OptionOwningRecordTests.tearDown
    source = OptionOwningRecordTests.source
    both = OptionOwningRecordTests.both
    rejected = OptionOwningRecordTests.rejected
    TOKEN = ('struct Tok { h u64 }\n'
             'func mint() Resource<Tok> { return resource.seal(Tok { h: 38u64 }) }\n'
             'func eat(t Resource<Tok>) u32 { let r = resource.unseal(move(t)); return u32(r.h) }\n')
    HOLDER = 'struct Holder { token Resource<Tok> }\n'

    def test_nominal_generic_record_moves_through_enum_option_and_formats(self):
        source = self.source(self.TOKEN +
            'struct Box<T> { item T }\n'
            'struct Owned { nested Box<Resource<Tok>>, buf Resource<Buffer> }\n'
            'enum State { Empty, Full(Owned) }\n'
            'func option(s State) Option<Owned> { match s {\n'
            ' Full(p) { return Some<Owned>(move(p)) } Empty { return None<Owned>() } } }\n'
            'func make() State !{memory.write} { let a = buffer.alloc(4u32)\n'
            ' match a { Ok(b) { let t = mint()\n'
            ' return State.Full(Owned { nested: Box<Resource<Tok>> { item: move(t) }, buf: move(b) })\n'
            ' } Err(code) { return State.Empty() } } }\n'
            'func main() u32 !{memory.read,memory.write} { let o = option(make())\n'
            ' match o { Some(p) { let n = eat(move(p.nested.item))\n'
            ' return n + buffer.len(borrow(p.buf)) } None { return 1u32 } } }\n')
        self.both(source)
        expected = proc(OMNI, 'memory', source)
        self.assertEqual(expected.returncode, 0, expected.stderr)
        wave = proc(OMNI, 'wave', source)
        self.assertEqual(wave.returncode, 0, wave.stderr)
        wp = self.dir/'nominal.owave'
        wp.write_bytes(wave.stdout)
        wire, onme = self.dir/'nominal.owire', self.dir/'nominal.onme'
        for command, output in (('pack', wire), ('onme', onme)):
            encoded = proc(OMNI, command, source, '-o', output)
            self.assertEqual(encoded.returncode, 0, encoded.stderr)
        for representation in (wp, wire, onme):
            self.both(representation)
            memory = proc(OMNI, 'memory', representation)
            self.assertEqual(memory.returncode, 0, memory.stderr)
            self.assertEqual(memory.stdout, expected.stdout)

    def test_live_nominal_fields_are_checked_on_every_structured_exit(self):
        prefix = self.TOKEN + self.HOLDER
        for body in ('return 0u32', 'if true { return 0u32 } return eat(move(h.token))'):
            self.rejected(prefix + 'func main() u32 { let t = mint()\n'
                ' let h = Holder { token: move(t) }\n' + body + '\n}\n', b'E_RESOURCE_UNCONSUMED')
        for control in ('break', 'continue'):
            self.rejected(prefix + 'func main() u32 { var i u32 = 0u32\n'
                ' for i < 1u32 { let t = mint(); let h = Holder { token: move(t) }\n'
                ' i = i + 1u32\n' + control + '\n } return 0u32 }\n', b'E_RESOURCE_UNCONSUMED')
        self.rejected(prefix + 'func f(h Holder) u32 { return 0u32 }\n'
            'func main() u32 { return 0u32 }\n', b'E_RESOURCE_UNCONSUMED')

    def test_nominal_field_move_copy_and_loan_rules_are_not_relaxed(self):
        prefix = self.TOKEN + self.HOLDER + 'func main() u32 { let t = mint()\n let h = Holder { token: move(t) }\n'
        for body, code in (
            ('let a = eat(move(h.token)); return eat(move(h.token)) + a', b'E_RESOURCE_MOVED'),
            ('let alias = h.token; return eat(move(alias))', b'E_RESOURCE_ACCESS'),
            ('let loan = borrow(h.token); let a = eat(move(h.token)); let raw = resource.peek(loan); return a + u32(raw.h)', b'E_BORROW_CONFLICT'),
        ):
            with self.subTest(body=body):
                self.rejected(prefix + body + '\n}\n', code)

    def test_mixed_nominal_and_buffer_cleanup_does_not_leak_or_cross_release(self):
        self.both(self.source(self.TOKEN +
            'struct Mixed { token Resource<Tok>, buf Resource<Buffer> }\n'
            'func main() u32 !{memory.read,memory.write} { var i u32 = 0u32; var total u32 = 0u32\n'
            ' for i < 3000u32 { let a = buffer.alloc(4u32)\n'
            ' match a { Ok(b) { let t = mint(); let p = Mixed { token: move(t), buf: move(b) }\n'
            ' total = total + eat(move(p.token)) + buffer.len(borrow(p.buf))\n'
            ' } Err(code) { return 1u32 } } i = i + 1u32 }\n'
            ' return total - 126000u32 + 42u32 }\n'))

    def test_unused_nominal_field_declaration_has_wave_and_wire_fences(self):
        source = self.source('struct Tok { h u64 }\n' + self.HOLDER +
            'func main() u32 { return 42u32 }\n')
        wave = proc(OMNI, 'wave', source)
        self.assertEqual(wave.returncode, 0, wave.stderr)
        self.assertTrue(wave.stdout.startswith(b'(omni-wave 21'))
        wire = self.dir/'valid.owire'
        self.assertEqual(proc(OMNI, 'pack', source, '-o', wire).returncode, 0)
        self.assertEqual(wire.read_bytes()[:8], b'OMCX\x15\x00\x00\x00')
        for suffix, payload in (
            ('owave', wave.stdout.replace(b'(omni-wave 21', b'(omni-wave 20', 1)),
            ('owire', b'OMCX\x14\x00\x00\x00' + wire.read_bytes()[8:]),
        ):
            forged = self.dir/f'old.{suffix}'
            forged.write_bytes(payload)
            checked = proc(OMNI, 'check', forged)
            self.assertEqual(checked.returncode, 2, checked.stderr)
            self.assertIn(b'E_VERSION', checked.stderr)

    def test_projected_nominal_handle_does_not_grant_declaring_module_authority(self):
        (self.dir/'tokens.omni').write_text('module tokens\n'
            'pub struct Tok { h u64 }\npub struct Holder { token Resource<Tok> }\n'
            'pub func mint() Holder { let t = resource.seal(Tok { h: 42u64 })\n'
            ' return Holder { token: move(t) } }\n'
            'pub func consume(h Holder) u32 { let raw = resource.unseal(move(h.token))\n'
            ' return u32(raw.h) }\n', encoding='utf-8')
        self.both(self.source('import api "tokens.omni"\n'
            'func main() u32 { let h = api.mint(); return api.consume(move(h)) }\n'))
        self.rejected('import api "tokens.omni"\n'
            'func main() u32 { let h = api.mint(); let raw = resource.unseal(move(h.token))\n'
            ' return u32(raw.h) }\n', b'E_RESOURCE_PRIVATE')


class NestedPendingSumTests(unittest.TestCase):
    setUp = OptionOwningRecordTests.setUp
    tearDown = OptionOwningRecordTests.tearDown
    source = OptionOwningRecordTests.source
    both = OptionOwningRecordTests.both
    rejected = OptionOwningRecordTests.rejected
    COPY = ('func finish(v Option<Result<u32,u32>>) u32 { match v {\n'
            ' Some(r) { match r { Ok(n) { return n } Err(n) { return n } } }\n'
            ' None { return 0u32 } } }\n')
    FLOW = ('enum Inner { Empty, Full(Result<Option<Resource<Buffer>>,u32>) }\n'
            'func make(code u32) Option<Inner> !{memory.write} {\n'
            ' if code == 1u32 { return None<Inner>() }\n'
            ' if code == 2u32 { return Some<Inner>(Inner.Empty()) }\n'
            ' if code == 3u32 { return Some<Inner>(Inner.Full(Ok<Option<Resource<Buffer>>,u32>(None<Resource<Buffer>>()))) }\n'
            ' if code == 4u32 { return Some<Inner>(Inner.Full(Err<Option<Resource<Buffer>>,u32>(0u32))) }\n'
            ' let a = buffer.alloc(42u32)\n match a { Ok(b) {\n'
            ' return Some<Inner>(Inner.Full(Ok<Option<Resource<Buffer>>,u32>(Some<Resource<Buffer>>(move(b)))))\n'
            ' } Err(allocation_error) { return Some<Inner>(Inner.Full(Err<Option<Resource<Buffer>>,u32>(allocation_error))) } } }\n'
            'func finish(v Option<Inner>) u32 !{memory.read} { match v {\n'
            ' Some(inner) { match inner { Empty { return 0u32 } Full(r) { match r {\n'
            ' Ok(o) { match o { Some(b) { return buffer.len(borrow(b)) } None { return 0u32 } } }\n'
            ' Err(code) { return code } } } } } None { return 0u32 } } }\n')

    def test_recursive_resource_payloads_and_all_empty_paths_roundtrip(self):
        source = self.source(self.FLOW + 'func main() u32 !{memory.read,memory.write} {\n'
            ' return finish(make(0u32)) + finish(make(1u32)) + finish(make(2u32))\n'
            ' + finish(make(3u32)) + finish(make(4u32)) }\n')
        self.both(source)
        memory = proc(OMNI, 'memory', source)
        self.assertEqual(memory.returncode, 0, memory.stderr)
        wave = proc(OMNI, 'wave', source)
        self.assertEqual(wave.returncode, 0, wave.stderr)
        wp = self.dir/'nested.owave'; wp.write_bytes(wave.stdout)
        wire, onme = self.dir/'nested.owire', self.dir/'nested.onme'
        for command, output in (('pack', wire), ('onme', onme)):
            result = proc(OMNI, command, source, '-o', output)
            self.assertEqual(result.returncode, 0, result.stderr)
        for representation in (wp, wire, onme):
            self.both(representation)
            projected = proc(OMNI, 'memory', representation)
            self.assertEqual(projected.returncode, 0, projected.stderr)
            self.assertEqual(projected.stdout, memory.stdout)

    def test_nested_payload_cleanup_exceeds_handle_capacity(self):
        self.both(self.source(self.FLOW +
            'func main() u32 !{memory.read,memory.write} { var i u32 = 0u32\n'
            ' for i < 3000u32 { let n = finish(make(0u32))\n'
            ' if n != 42u32 { return 1u32 } let empty = finish(make(3u32))\n'
            ' if empty != 0u32 { return 2u32 } i = i + 1u32 } return 42u32 }\n'))

    def test_copy_result_payload_still_requires_consumption_at_every_layer(self):
        prefix = self.COPY + 'func main() u32 { let v = Some<Result<u32,u32>>(Ok<u32,u32>(42u32))\n'
        for body, code in (
            ('return 0u32', b'E_RESULT_UNHANDLED'),
            ('match v { Some(r) { return 0u32 } None { return 0u32 } }', b'E_RESULT_UNHANDLED'),
            ('match v { Some(_) { return 0u32 } None { return 0u32 } }', b'E_RESOURCE_UNCONSUMED'),
            ('let a = finish(v); return a + finish(v)', b'E_RESULT_MOVED'),
            ('let a = tuple(v); return 0u32', b'E_RESULT_UNHANDLED'),
            ('return closure() u32 { return finish(v) }()', b'E_CLOSURE_CAPTURE'),
        ):
            with self.subTest(body=body): self.rejected(prefix + body + '\n}\n', code)
        self.rejected(self.COPY + 'func main() u32 { var v = None<Result<u32,u32>>()\n'
            ' return finish(v) }\n', b'E_RESULT_MUTABLE')
        self.rejected('struct Hidden { v Option<Result<u32,u32>> }\n'
            'func bad(h Hidden) u32 { return 0u32 }\nfunc main() u32 { return 0u32 }\n', b'E_RESULT_UNHANDLED')
        self.both(self.source(self.COPY + 'func main() u32 {\n'
            ' return finish(Some<Result<u32,u32>>(Ok<u32,u32>(42u32))) + finish(None<Result<u32,u32>>()) }\n'))

    def test_nominal_record_and_resource_error_remain_explicitly_consumed(self):
        prefix = NominalRecordOwnershipTests.TOKEN + NominalRecordOwnershipTests.HOLDER
        prefix += ('func finish(v Result<Option<Holder>,Resource<Tok>>) u32 { match v {\n'
                   ' Ok(o) { match o { Some(h) { return eat(move(h.token)) } None { return 0u32 } } }\n'
                   ' Err(t) { return eat(move(t)) } } }\n')
        self.both(self.source(prefix + 'func main() u32 { let a = mint(); let b = mint()\n'
            ' let x = finish(Ok<Option<Holder>,Resource<Tok>>(Some<Holder>(Holder { token: move(a) })))\n'
            ' let y = finish(Err<Option<Holder>,Resource<Tok>>(move(b)))\n'
            ' if x == 38u32 && y == 38u32 { return 42u32 } return 1u32 }\n'))
        error_prefix = (NominalRecordOwnershipTests.TOKEN + NominalRecordOwnershipTests.HOLDER +
            'func finish(v Result<u32,Option<Holder>>) u32 { match v { Ok(n) { return n }\n'
            ' Err(o) { match o { Some(h) { return eat(move(h.token)) } None { return 0u32 } } } } }\n')
        self.both(self.source(error_prefix + 'func main() u32 { let t = mint()\n'
            ' return finish(Err<u32,Option<Holder>>(Some<Holder>(Holder { token: move(t) }))) + 4u32 }\n',
            'pending-error.omni'))
        self.rejected(NominalRecordOwnershipTests.TOKEN + NominalRecordOwnershipTests.HOLDER +
            'func bad(v Result<u32,Option<Holder>>) u32 { match v { Ok(n) { return n }\n'
            ' Err(o) { return 0u32 } } }\nfunc main() u32 { return 0u32 }\n', b'E_RESULT_UNHANDLED')
        self.rejected(prefix + 'func main() u32 { let t = mint()\n'
            ' let v = Err<Option<Holder>,Resource<Tok>>(move(t))\n'
            ' match v { Ok(o) { return finish(Ok<Option<Holder>,Resource<Tok>>(o)) }\n'
            ' Err(e) { return 0u32 } } }\n', b'E_RESOURCE_UNCONSUMED')

    def test_generic_and_import_alias_derive_pending_without_resource_leaves(self):
        source = ('enum Wrap<T> { Full(T), Empty }\n'
            'func adapt<T>(v Wrap<T>) Option<T> { match v {\n'
            ' Full(x) { return Some<T>(x) } Empty { return None<T>() } } }\n' + self.COPY +
            'func main() u32 { return finish(adapt<Result<u32,u32>>(Wrap.Full<Result<u32,u32>>(Ok<u32,u32>(42u32)))) }\n')
        self.both(self.source(source, 'generic.omni'))
        (self.dir/'types.omni').write_text('module types\npub enum Msg { Empty, Value(Result<u32,u32>) }\n', encoding='utf-8')
        self.both(self.source('import api "types.omni"\nfunc main() u32 {\n'
            ' let v = api.Msg.Value(Ok<u32,u32>(42u32))\n'
            ' match v { Empty { return 0u32 } Value(r) { match r {\n'
            ' Ok(n) { return n } Err(n) { return n } } } } }\n', 'alias.omni'))

    def test_nested_try_preserves_both_error_paths_and_resource_transfer(self):
        self.both(self.source(
            'func peel(v Result<Result<Resource<Buffer>,u32>,u32>) Result<Resource<Buffer>,u32> {\n'
            ' let inner = v?\n let b = inner?\n return Ok<Resource<Buffer>,u32>(move(b)) }\n'
            'func observe(v Result<Result<Resource<Buffer>,u32>,u32>) u32 !{memory.read} {\n'
            ' let r = peel(v)\n match r { Ok(b) { return buffer.len(borrow(b)) } Err(code) { return code } } }\n'
            'func main() u32 !{memory.read,memory.write} {\n'
            ' return observe(Ok<Result<Resource<Buffer>,u32>,u32>(buffer.alloc(20u32)))\n'
            ' + observe(Err<Result<Resource<Buffer>,u32>,u32>(12u32))\n'
            ' + observe(Ok<Result<Resource<Buffer>,u32>,u32>(Err<Resource<Buffer>,u32>(10u32))) }\n'))

    def test_nested_pending_fences_and_forged_wave_fail_closed(self):
        declaration = self.source('enum Msg { Value(Result<u32,u32>), Empty }\nfunc main() u32 { return 42u32 }\n', 'decl.omni')
        wave = proc(OMNI, 'wave', declaration)
        self.assertEqual(wave.returncode, 0, wave.stderr)
        self.assertTrue(wave.stdout.startswith(b'(omni-wave 21'))
        wire = self.dir/'decl.owire'
        self.assertEqual(proc(OMNI, 'pack', declaration, '-o', wire).returncode, 0)
        self.assertEqual(wire.read_bytes()[:8], b'OMCX\x15\x00\x00\x00')
        for suffix, payload in (('owave', wave.stdout.replace(b'(omni-wave 21', b'(omni-wave 20', 1)),
                                ('owire', b'OMCX\x14\x00\x00\x00' + wire.read_bytes()[8:])):
            bad = self.dir/f'old.{suffix}'; bad.write_bytes(payload)
            checked = proc(OMNI, 'check', bad)
            self.assertEqual(checked.returncode, 2, checked.stderr)
            self.assertIn(b'E_VERSION', checked.stderr)
        source = self.source(self.COPY + 'func main() u32 {\n'
            ' let a = Some<Result<u32,u32>>(Ok<u32,u32>(42u32))\n let b = None<Result<u32,u32>>()\n'
            ' let first = finish(a)\n return first + finish(b) }\n')
        encoded = proc(OMNI, 'wave', source)
        self.assertEqual(encoded.returncode, 0, encoded.stderr)
        self.assertIn(b'(call finish (ref b))', encoded.stdout)
        forged = self.dir/'replay.owave'
        forged.write_bytes(encoded.stdout.replace(b'(call finish (ref b))', b'(call finish (ref a))', 1))
        output = self.dir/'never.owire'
        for command, args in (('check', []), ('pack', ['-o', output])):
            checked = proc(OMNI, command, forged, *args)
            self.assertEqual(checked.returncode, 2, checked.stderr)
            self.assertIn(b'E_RESULT_MOVED', checked.stderr)
        self.assertFalse(output.exists())


class PendingRecordFieldTests(unittest.TestCase):
    setUp = OptionOwningRecordTests.setUp
    tearDown = OptionOwningRecordTests.tearDown
    source = OptionOwningRecordTests.source
    both = OptionOwningRecordTests.both
    rejected = OptionOwningRecordTests.rejected
    COPY = ('struct Pair { a Result<u32,u32>, b Result<u32,u32>, tag u32 }\n'
            'func make() Pair { return Pair { a: Ok<u32,u32>(20u32), b: Err<u32,u32>(22u32), tag: 5u32 } }\n'
            'func number(r Result<u32,u32>) u32 { match r { Ok(n) { return n } Err(n) { return n } } }\n'
            'func finish(p Pair) u32 { let a = number(p.a); let tag = p.tag; let b = number(p.b)\n'
            ' if tag == 5u32 { return a + b } return 1u32 }\n')
    MIXED = (NominalRecordOwnershipTests.TOKEN +
        'struct Box<T> { value T }\n'
        'struct Owner { child Box<Option<Result<Resource<Buffer>,u32>>>, spare Resource<Buffer>, token Resource<Tok> }\n'
        'func make(fail u32) Result<Owner,u32> !{memory.write} {\n'
        ' var first_size u32 = 3u32; if fail == 1u32 { first_size = 16777217u32 }\n'
        ' let a = buffer.alloc(first_size)\n match a { Ok(first) {\n'
        ' var second_size u32 = 1u32; if fail == 2u32 { second_size = 16777217u32 }\n'
        ' let b = buffer.alloc(second_size)\n match b { Ok(second) { let t = mint()\n'
        ' if fail == 3u32 { let code = eat(move(t)); return Err<Owner,u32>(code) }\n'
        ' return Ok<Owner,u32>(Owner { child: Box<Option<Result<Resource<Buffer>,u32>>> { value: Some<Result<Resource<Buffer>,u32>>(Ok<Resource<Buffer>,u32>(move(first))) }, spare: move(second), token: move(t) })\n'
        ' } Err(second_error) { return Err<Owner,u32>(second_error) } }\n'
        ' } Err(first_error) { return Err<Owner,u32>(first_error) } } }\n'
        'func finish(p Owner) u32 !{memory.read} { let t = eat(move(p.token))\n'
        ' let n = buffer.len(borrow(p.spare)); let o = p.child.value\n'
        ' match o { Some(r) { match r { Ok(b) { return t + n + buffer.len(borrow(b)) }\n'
        ' Err(code) { return code } } } None { return 0u32 } } }\n'
        'func observe(fail u32) u32 !{memory.read,memory.write} { let r = make(fail)\n'
        ' match r { Ok(p) { return finish(move(p)) } Err(code) { return code } } }\n')

    def test_no_resource_record_transfers_by_field_whole_record_and_sum(self):
        self.both(self.source(self.COPY +
            'struct Wrap { inner Pair }\nenum Env { Full(Wrap), Empty }\n'
            'func take(e Env) u32 { match e { Full(w) { return finish(move(w.inner)) } Empty { return 0u32 } } }\n'
            'func main() u32 { return take(Env.Full(Wrap { inner: make() })) + take(Env.Empty()) }\n'))

    def test_generic_mixed_record_fields_roundtrip_without_duplicate_cleanup(self):
        source = self.source(self.MIXED +
            'func main() u32 !{memory.read,memory.write} { return observe(0u32) }\n')
        self.both(source)
        expected = proc(OMNI, 'memory', source)
        self.assertEqual(expected.returncode, 0, expected.stderr)
        wave = proc(OMNI, 'wave', source)
        self.assertEqual(wave.returncode, 0, wave.stderr)
        wp = self.dir/'fields.owave'; wp.write_bytes(wave.stdout)
        wire, onme = self.dir/'fields.owire', self.dir/'fields.onme'
        for command, output in (('pack', wire), ('onme', onme)):
            result = proc(OMNI, command, source, '-o', output)
            self.assertEqual(result.returncode, 0, result.stderr)
        for representation in (wp, wire, onme):
            self.both(representation)
            actual = proc(OMNI, 'memory', representation)
            self.assertEqual(actual.returncode, 0, actual.stderr)
            self.assertEqual(actual.stdout, expected.stdout)

    def test_partial_construction_failure_and_normal_cleanup_exceed_handle_limit(self):
        self.both(self.source(self.MIXED +
            'func main() u32 !{memory.read,memory.write} { var i u32 = 0u32\n'
            ' for i < 1200u32 { let first = observe(1u32); let second = observe(2u32); let third = observe(3u32)\n'
            ' if first == 0u32 || second == 0u32 || third != 38u32 { return 1u32 }\n'
            ' let done = observe(0u32); if done != 42u32 { return 2u32 } i = i + 1u32 } return 42u32 }\n'))

    def test_pending_fields_cannot_be_replayed_abandoned_or_moved_partially(self):
        prefix = self.COPY + 'func main() u32 { let p = make()\n'
        for body, code in (
            ('return p.tag', b'E_RESULT_UNHANDLED'),
            ('let a = number(p.a); return number(p.a) + a', b'E_RESULT_MOVED'),
            ('let a = number(p.a); return a', b'E_RESULT_UNHANDLED'),
            ('let a = number(p.a); let q = move(p); return finish(move(q)) + a', b'E_RESULT_MOVED'),
            ('if true { let a = number(p.a) } return finish(move(p))', b'E_RESOURCE_FLOW'),
            ('var i u32 = 0u32; for i < 1u32 { let a = number(p.a); i = i + 1u32 } return finish(move(p))', b'E_RESOURCE_FLOW'),
        ):
            with self.subTest(body=body): self.rejected(prefix + body + '\n}\n', code)

    def test_no_resource_pending_record_cannot_hide_in_copy_contexts(self):
        prefix = self.COPY
        cases = (
            ('let p = make(); let alias = p; return finish(move(alias))', b'E_RESOURCE_ACCESS'),
            ('var p = make(); return finish(move(p))', b'E_RESOURCE_MUTABLE'),
            ('let x = array(make()); return 0u32', b'E_RESULT_UNHANDLED'),   # CP-01: allowed as an owning Array, but its pending fields must be handled
            ('let p = make(); return closure() u32 { return p.tag }()', b'E_CLOSURE_CAPTURE'),
            ('return make().tag', b'E_RESOURCE_ACCESS'),
            ('let v = Some<Pair>(make()); match v { Some(_) { return 0u32 } None { return 0u32 } }', b'E_RESOURCE_UNCONSUMED'),
        )
        for body, code in cases:
            with self.subTest(body=body): self.rejected(prefix + 'func main() u32 { ' + body + ' }\n', code)
        self.rejected(prefix + 'func bad(v Array<Pair,2>) u32 { return 0u32 }\n'
            'func main() u32 { return 0u32 }\n', b'E_RESULT_UNHANDLED')

    def test_unused_declaration_fence_and_forged_field_replay(self):
        declaration = self.source('struct P { result Result<u32,u32> }\n'
            'func main() u32 { return 42u32 }\n', 'decl.omni')
        wave = proc(OMNI, 'wave', declaration)
        self.assertEqual(wave.returncode, 0, wave.stderr)
        self.assertTrue(wave.stdout.startswith(b'(omni-wave 21'))
        wire = self.dir/'decl.owire'
        self.assertEqual(proc(OMNI, 'pack', declaration, '-o', wire).returncode, 0)
        for suffix, payload in (('owave', wave.stdout.replace(b'(omni-wave 21', b'(omni-wave 20', 1)),
                                ('owire', b'OMCX\x14\x00\x00\x00' + wire.read_bytes()[8:])):
            forged = self.dir/f'old.{suffix}'; forged.write_bytes(payload)
            result = proc(OMNI, 'check', forged)
            self.assertEqual(result.returncode, 2, result.stderr)
            self.assertIn(b'E_VERSION', result.stderr)
        source = self.source(self.COPY + 'func main() u32 { return finish(make()) }\n')
        encoded = proc(OMNI, 'wave', source)
        self.assertEqual(encoded.returncode, 0, encoded.stderr)
        self.assertIn(b'(field (ref p) b)', encoded.stdout)
        forged = self.dir/'replay.owave'
        forged.write_bytes(encoded.stdout.replace(b'(field (ref p) b)', b'(field (ref p) a)', 1))
        output = self.dir/'never.owire'
        for command, args in (('check', []), ('pack', ['-o', output])):
            result = proc(OMNI, command, forged, *args)
            self.assertEqual(result.returncode, 2, result.stderr)
            self.assertIn(b'E_RESULT_MOVED', result.stderr)
        self.assertFalse(output.exists())





class OwningTupleTests(unittest.TestCase):
    setUp = OptionOwningRecordTests.setUp
    tearDown = OptionOwningRecordTests.tearDown
    source = OptionOwningRecordTests.source
    both = OptionOwningRecordTests.both
    rejected = OptionOwningRecordTests.rejected
    MAKE = ('func make() Tuple<Resource<Buffer>,u32> !{memory.write} { '
            'let r = buffer.alloc(4u32); match r { Ok(b) { return tuple(move(b),38u32) } '
            'Err(code) { let q = buffer.alloc(0u32); match q { Ok(b) { return tuple(move(b),code) } Err(e) { return make() } } } } }\n')
    FINISH = ('func finish(p Tuple<Resource<Buffer>,u32>) u32 !{memory.read} { '
              'return buffer.len(borrow(tuple.get(p,0u32))) + tuple.get(p,1u32) }\n')

    def test_nested_product_whole_moves_return_and_cleanup(self):
        self.both(self.source(self.MAKE + self.FINISH +
            'struct Box { v Tuple<Resource<Buffer>,u32> }\n'
            'func pass(p Tuple<Resource<Buffer>,u32>) Tuple<Resource<Buffer>,u32> { return move(p) }\n'
            'func main() u32 !{memory.read,memory.write} { var i u32 = 0u32; '
            'for i < 1200u32 { let b = Box { v: pass(make()) }; let p = move(b.v); '
            'let n = finish(move(p)); if n != 42u32 { return 1u32 } i = i + 1u32 } return 42u32 }\n'))

    def test_pending_tuple_destructure_and_nested_nominal_elements(self):
        self.both(self.source(NominalRecordOwnershipTests.TOKEN +
            'func main() u32 { let t = mint(); let p = tuple(Ok<u32,u32>(4u32),tuple(move(t),0u32)); '
            'let (r, q) = move(p); let (token, zero) = move(q); let n = eat(move(token)); '
            'match r { Ok(k) { return n + k + zero } Err(k) { return k } } }\n'))

    def test_owning_tuple_cannot_copy_mutate_capture_or_replay(self):
        for body, code in (
            ('let p = make(); let q = p; return 0u32', b'E_RESOURCE_ACCESS'),
            ('var p = make(); return 0u32', b'E_RESOURCE_MUTABLE'),
            ('let p = make(); return closure() u32 { return tuple.get(p,1u32) }()', b'E_CLOSURE_CAPTURE'),
            ('let p = make(); let q = move(p); return finish(move(p))', b'E_RESOURCE_MOVED'),
            ('return tuple.get(make(),1u32)', b'E_RESOURCE_ACCESS'),
            ('let p = make(); let (_, n) = move(p); return n', b'E_RESOURCE_UNCONSUMED'),
            ('let p = make(); let a = array.fill(move(p),2u32); return 0u32', b'E_PRODUCT_LINEAR'),   # duplicating an owning value
        ):
            with self.subTest(body=body):
                self.rejected(self.MAKE+self.FINISH+'func main() u32 !{memory.read,memory.write} { '+body+' }\n', code)
        self.rejected('func main() u32 { let p = tuple(Ok<u32,u32>(42u32)); return 0u32 }\n', b'E_RESULT_UNHANDLED')
        self.rejected('func number(r Result<u32,u32>) u32 { match r { Ok(n) { return n } Err(n) { return n } } }\n'
            'func main() u32 { let p = tuple(Ok<u32,u32>(42u32)); let n = number(tuple.get(p,0u32)); '
            'return n + number(tuple.get(p,0u32)) }\n', b'E_RESULT_MOVED')

    def test_representation_roundtrips_preserve_ownership_and_memory(self):
        p=self.source(self.MAKE+self.FINISH+'func main() u32 !{memory.read,memory.write} { return finish(make()) }\n')
        self.both(p)
        expected=proc(OMNI,'memory',p)
        self.assertEqual(expected.returncode,0,expected.stderr)
        wave=proc(OMNI,'wave',p); self.assertEqual(wave.returncode,0,wave.stderr)
        self.assertTrue(wave.stdout.startswith(b'(omni-wave 21'))
        wp=self.dir/'tuple.owave'; wp.write_bytes(wave.stdout)
        representations=[wp]
        for command,ext in (('pack','owire'),('onme','onme')):
            output=self.dir/('tuple.'+ext)
            result=proc(OMNI,command,p,'-o',output)
            self.assertEqual(result.returncode,0,result.stderr); representations.append(output)
        for representation in representations:
            self.both(representation)
            actual=proc(OMNI,'memory',representation)
            self.assertEqual(actual.returncode,0,actual.stderr)
            self.assertEqual(actual.stdout,expected.stdout)

    def test_owning_tuple_cannot_hide_under_legacy_versions(self):
        programs=(self.MAKE+self.FINISH+'func main() u32 !{memory.read,memory.write} { return finish(make()) }\n',
                  'struct Unused { p Tuple<Result<u32,u32>> }\nfunc main() u32 { return 42u32 }\n',
                  'func main() u32 { let p = tuple(Ok<u32,u32>(42u32)); let r = tuple.get(p,0u32); match r { Ok(n) { return n } Err(n) { return n } } }\n')
        for i,program in enumerate(programs):
            p=self.source(program,f'fence{i}.omni'); wave=proc(OMNI,'wave',p)
            self.assertEqual(wave.returncode,0,wave.stderr)
            self.assertTrue(wave.stdout.startswith(b'(omni-wave 21'))
            out=self.dir/f'fence{i}.owire'
            result=proc(OMNI,'pack',p,'-o',out); self.assertEqual(result.returncode,0,result.stderr)
            for ext,payload in (('owave',wave.stdout.replace(b'(omni-wave 21',b'(omni-wave 20',1)),
                                ('owire',b'OMCX\x14\x00\x00\x00'+out.read_bytes()[8:])):
                forged=self.dir/f'forged{i}.{ext}'; forged.write_bytes(payload)
                result=proc(OMNI,'check',forged)
                self.assertEqual(result.returncode,2,result.stderr); self.assertIn(b'E_VERSION',result.stderr)


class OwningArrayTests(unittest.TestCase):
    """CP-01: Array<T,N> whose element owns a Resource or a pending sum (N <= 16). Literal indices are Places; the
    cleanup oracle runs 1200 iterations, above the runtime's 1024 handle limit, so a leak or a double release fails."""
    setUp = OptionOwningRecordTests.setUp
    tearDown = OptionOwningRecordTests.tearDown
    source = OptionOwningRecordTests.source
    both = OptionOwningRecordTests.both
    rejected = OptionOwningRecordTests.rejected
    A3 = 'Array<Resource<Buffer>,3>'
    MAKE = ('func make() Array<Resource<Buffer>,3> !{memory.write} {\n'
            '  let a = buffer.alloc(4u32)\n  match a { Ok(x) {\n'
            '    let b = buffer.alloc(5u32)\n    match b { Ok(y) {\n'
            '      let c = buffer.alloc(6u32)\n'
            '      match c { Ok(z) { return array(move(x), move(y), move(z)) } Err(code) { return make() } }\n'
            '    } Err(code) { return make() } }\n  } Err(code) { return make() } }\n}\n')
    TOTAL = ('func total(a Array<Resource<Buffer>,3>) u32 !{memory.read} {\n'
             '  return buffer.len(borrow(a[0u32])) + buffer.len(borrow(a[1u32])) + buffer.len(borrow(a[2u32])) + array.len(a)\n}\n'
             'func pass(a Array<Resource<Buffer>,3>) Array<Resource<Buffer>,3> { return move(a) }\n')
    MAIN = 'func main() u32 !{memory.read,memory.write} { '

    def test_whole_array_moves_projection_borrow_and_cleanup_exceed_handle_limit(self):
        self.both(self.source(self.MAKE + self.TOTAL + self.MAIN + 'var i u32 = 0u32\n'
            '  for i < 1200u32 { let a = pass(make()); let n = total(move(a)); if n != 18u32 { return 1u32 } i = i + 1u32 }\n'
            '  return 42u32 }\n'))

    def test_literal_element_moves_leave_the_other_elements_to_cleanup(self):
        self.both(self.source(self.MAKE + self.MAIN + 'var i u32 = 0u32\n'
            '  for i < 1200u32 {\n    let a = make()\n    let freed = buffer.release(move(a[1u32]))\n'
            '    let n = buffer.len(borrow(a[0u32])) + buffer.len(borrow(a[2u32]))\n'
            '    if n != 10u32 { return 1u32 }\n    if freed != 0u32 { return 2u32 }\n    i = i + 1u32 }\n'
            '  return 42u32 }\n'))

    def test_nested_owning_arrays_records_and_tuples_move_whole_and_by_part(self):
        self.both(self.source(self.MAKE + self.TOTAL +
            'struct Box { items Array<Resource<Buffer>,3>, tag u32 }\n'
            'func unbox(b Box) u32 !{memory.read} { return total(move(b.items)) + b.tag }\n'
            'func main() u32 !{memory.read,memory.write} { var i u32 = 0u32\n'
            '  for i < 1200u32 {\n    let b = Box { items: make(), tag: 24u32 }\n    let c = move(b)\n'
            '    let p = tuple(move(c), 0u32)\n    let (d, z) = move(p)\n'
            '    let n = unbox(move(d))\n    if n != 42u32 + z { return 1u32 }\n    i = i + 1u32 }\n'
            '  return 42u32 }\n', 'nested.omni'))

    def test_array_of_owning_products_is_moved_and_cleaned_per_leaf(self):
        self.both(self.source(
            'struct Slot { buf Resource<Buffer>, tag u32 }\n'
            'func slot(tag u32) Slot !{memory.write} { let r = buffer.alloc(2u32); match r { Ok(b) { return Slot { buf: move(b), tag: tag } } Err(code) { return slot(tag) } } }\n'
            'func pair() Array<Slot,2> !{memory.write} { return array(slot(10u32), slot(11u32)) }\n'
            'func sum(a Array<Slot,2>) u32 !{memory.read} { return a[0u32].tag + a[1u32].tag + buffer.len(borrow(a[1u32].buf)) }\n'
            'func main() u32 !{memory.read,memory.write} { var i u32 = 0u32\n'
            '  for i < 1200u32 { let a = pair(); let b = move(a); if sum(move(b)) != 23u32 { return 1u32 } i = i + 1u32 }\n'
            '  return 42u32 }\n'))

    def test_pending_elements_transfer_through_literal_places(self):
        self.both(self.source(
            'func pick(o Option<Resource<Buffer>>) u32 !{memory.read} { match o { Some(b) { return buffer.len(borrow(b)) } None { return 0u32 } } }\n'
            'func number(r Result<u32,u32>) u32 { match r { Ok(n) { return n } Err(n) { return n } } }\n'
            'func main() u32 !{memory.read,memory.write} { var i u32 = 0u32\n'
            '  for i < 1200u32 {\n    let r = buffer.alloc(7u32)\n    match r { Ok(x) {\n'
            '      let a = array(Some<Resource<Buffer>>(move(x)), None<Resource<Buffer>>())\n'
            '      let k = array(Ok<u32,u32>(30u32), Err<u32,u32>(12u32))\n'
            '      let n = pick(a[0u32]) + pick(a[1u32]) + number(k[0u32]) + number(k[1u32])\n'
            '      if n != 49u32 { return 1u32 }\n    } Err(code) { return code } }\n    i = i + 1u32 }\n'
            '  return 42u32 }\n'))

    def test_nominal_resources_in_an_array_must_each_be_consumed_explicitly(self):
        tok = NominalRecordOwnershipTests.TOKEN
        self.both(self.source(tok + 'func main() u32 { let a = array(mint(), mint()); let x = eat(move(a[0u32])); '
                              'let y = eat(move(a[1u32])); return x + y }\n'), expected=76)
        self.rejected(tok + 'func main() u32 { let a = array(mint(), mint()); let x = eat(move(a[0u32])); return x }\n', b'E_RESOURCE_UNCONSUMED')
        self.rejected(tok + 'func main() u32 { let a = array(mint(), mint()); return 0u32 }\n', b'E_RESOURCE_UNCONSUMED')
        self.rejected(tok + 'func main() u32 { let a = array(mint(), mint()); let x = eat(move(a[0u32])); let y = eat(move(a[0u32])); return x + y }\n', b'E_RESOURCE_MOVED')

    def test_owning_array_laws_reject_copy_dynamic_index_replay_and_hidden_discard(self):
        pre = self.MAKE + self.TOTAL + 'func main() u32 !{memory.read,memory.write} { '
        for body, code in (
            ('let a = make(); let q = a; return 0u32', b'E_RESOURCE_ACCESS'),
            ('var a = make(); return 0u32', b'E_RESOURCE_MUTABLE'),
            ('let a = make(); let i = 1u32; return buffer.len(borrow(a[i]))', b'E_ARRAY_OWNING_INDEX'),
            ('let a = make(); return buffer.len(borrow(a[3u32]))', b'E_BOUNDS'),
            ('let a = make(); let b = move(a[0u32]); return buffer.len(borrow(a[0u32]))', b'E_RESOURCE_MOVED'),
            ('let a = make(); let b = move(a[0u32]); let c = move(a); return 0u32', b'E_RESOURCE_MOVED'),
            ('let a = make(); let b = move(a); return total(move(a))', b'E_RESOURCE_MOVED'),
            ('let a = make(); return closure() u32 { return array.len(a) }()', b'E_CLOSURE_CAPTURE'),
            ('let a = make(); let f = array.fill(move(a[0u32]),2u32); return 0u32', b'E_PRODUCT_LINEAR'),
            ('let a = make(); let v = view(a); return 0u32', b'E_VIEW_SOURCE'),
            ('let a = make(); for x in move(a) { } return 0u32', b'E_ITERABLE'),
            ('let a = make(); let i = 1u32; let b = move(a[i]); return 0u32', b'E_ARRAY_OWNING_INDEX'),
            ('let a = make(); let i = 1u32; let n = a[i]; return 0u32', b'E_ARRAY_OWNING_INDEX'),
            ('return buffer.len(borrow(make()[0u32]))', b'E_PLACE'),
            ('let b = make()[0u32]; return 0u32', b'E_RESOURCE_ACCESS'),
            ('return array.len(make())', b'E_RESOURCE_ACCESS'),
            ('let a = make(); let r = buffer.alloc(1u32); match r { Ok(x) { let c = array.with(move(a),0u32,move(x)); return 0u32 } Err(e) { return e } }', b'E_PRODUCT_LINEAR'),
        ):
            with self.subTest(body=body):
                self.rejected(pre + body + ' }\n', code)
        for text, code in (('func f(a Array<Resource<Buffer>,17>) u32 { return 0u32 }\nfunc main() u32 { return 0u32 }\n', b'E_LIMIT'),
                           ('func f(a Array<Borrow<Buffer>,2>) u32 { return 0u32 }\nfunc main() u32 { return 0u32 }\n', b'E_PRODUCT_LINEAR')):
            with self.subTest(text=text):
                self.rejected(text, code)

    def test_failure_at_each_construction_point_releases_the_elements_already_acquired(self):
        # An allocation of 16777217 bytes exceeds the 16 MiB budget: it fails at the chosen element after the earlier ones
        # were acquired. 1200 x 3 failing runs exceed the handle limit, so any leaked element exhausts the table.
        self.both(self.source(self.TOTAL +
            'func size(f u32, at u32, ok u32) u32 { if f == at { return 16777217u32 } return ok }\n'
            'func build(f u32) Result<Array<Resource<Buffer>,3>,u32> !{memory.write} {\n'
            '  let a = buffer.alloc(size(f, 1u32, 4u32))\n  match a { Ok(x) {\n'
            '    let b = buffer.alloc(size(f, 2u32, 5u32))\n    match b { Ok(y) {\n'
            '      let c = buffer.alloc(size(f, 3u32, 6u32))\n'
            '      match c { Ok(z) { return Ok<Array<Resource<Buffer>,3>,u32>(array(move(x), move(y), move(z))) }\n'
            '        Err(code) { return Err<Array<Resource<Buffer>,3>,u32>(code) } }\n'
            '    } Err(code) { return Err<Array<Resource<Buffer>,3>,u32>(code) } }\n'
            '  } Err(code) { return Err<Array<Resource<Buffer>,3>,u32>(code) } }\n}\n'
            'func observe(f u32) u32 !{memory.read,memory.write} { let r = build(f)\n'
            '  match r { Ok(a) { return total(move(a)) } Err(code) { return code + 1000u32 } } }\n'
            'func main() u32 !{memory.read,memory.write} { var i u32 = 0u32\n'
            '  for i < 1200u32 {\n    if observe(0u32) != 18u32 { return 1u32 }\n'
            '    if observe(1u32) < 1000u32 { return 2u32 }\n    if observe(2u32) < 1000u32 { return 3u32 }\n'
            '    if observe(3u32) < 1000u32 { return 4u32 }\n    i = i + 1u32 }\n'
            '  let probe = buffer.alloc(8u32)\n  match probe { Ok(p) { let n = buffer.len(borrow(p)); return n + 34u32 } Err(code) { return 5u32 } } }\n'))

    def test_structured_exits_after_a_partial_move_release_only_what_is_still_owned(self):
        self.both(self.source(self.MAKE +
            'func early(skip u32) u32 !{memory.read,memory.write} {\n  let a = make()\n'
            '  let freed = buffer.release(move(a[2u32]))\n  if skip == 1u32 { return freed + 1u32 }\n'
            '  return buffer.len(borrow(a[0u32])) + buffer.len(borrow(a[1u32])) + freed\n}\n'
            'func main() u32 !{memory.read,memory.write} { var i u32 = 0u32; var seen u32 = 0u32\n'
            '  for i < 3000u32 {\n    i = i + 1u32\n    let a = make()\n    let freed = buffer.release(move(a[1u32]))\n'
            '    let e = early(i - (i / 2u32) * 2u32)\n'
            '    if e != 1u32 { if e != 9u32 { return 1u32 } }\n    if freed != 0u32 { return 2u32 }\n'
            '    if i < 1500u32 { continue }\n    seen = seen + 1u32\n    if i > 2000u32 { break }\n  }\n'
            '  return seen - 502u32 + 42u32 }\n'), expected=42)

    def test_loans_on_elements_conflict_by_place_and_stay_disjoint_otherwise(self):
        pre = (self.MAKE + 'func two(x Borrow<Buffer>, y Resource<Buffer>) u32 !{memory.read,memory.write} '
               '{ return buffer.len(x) + buffer.release(move(y)) }\n'
               'func mixed(x BorrowMut<Buffer>, y Borrow<Buffer>) u32 !{memory.read,memory.write} { return buffer.len(y) }\n'
               'func main() u32 !{memory.read,memory.write} { ')
        for body, code in (
            ('let a = make(); let b = borrow(a[0u32]); let m = move(a[0u32]); return buffer.len(b)', b'E_BORROW_CONFLICT'),
            ('let a = make(); let b = borrow(a[0u32]); let c = move(a); return buffer.len(b)', b'E_BORROW_CONFLICT'),
            ('let a = make(); return mixed(borrow_mut(a[1u32]), borrow(a[1u32]))', b'E_BORROW_CONFLICT'),
            ('let a = make(); return two(borrow(a[0u32]), move(a[0u32]))', b'E_BORROW_CONFLICT'),
            ('let a = make(); return two(borrow(a[0u32]), move(a[1u32])) + buffer.len(borrow(a[1u32]))', b'E_RESOURCE_MOVED'),
            ('let a = make(); var i u32 = 0u32; for i < 2u32 { let f = buffer.release(move(a[0u32])); i = i + 1u32 } return 0u32', b'E_RESOURCE_FLOW'),
        ):
            with self.subTest(body=body):
                self.rejected(pre + body + ' }\n', code)
        self.both(self.source(pre + 'let a = make(); let x = borrow(a[0u32]); let y = borrow(a[0u32]); let z = borrow(a[1u32]); '
                              'let n = buffer.len(x) + buffer.len(y) + buffer.len(z); let f = buffer.release(move(a[2u32])); return n + f + 29u32 }\n'), expected=42)

    def test_pending_array_elements_cannot_be_replayed_or_abandoned(self):
        head = ('func pick(o Option<Resource<Buffer>>) u32 !{memory.read} { match o { Some(b) { return buffer.len(borrow(b)) } None { return 0u32 } } }\n'
                'func main() u32 !{memory.read} { let a = array(None<Resource<Buffer>>(), None<Resource<Buffer>>())\n')
        self.rejected(head + ' return pick(a[0u32])\n}\n', b'E_RESULT_UNHANDLED')
        self.rejected(head + ' return pick(a[0u32]) + pick(a[0u32]) + pick(a[1u32])\n}\n', b'E_RESULT_MOVED')
        self.rejected(head + ' let c = a[0u32]; return pick(a[1u32])\n}\n', b'E_RESULT_UNHANDLED')

    def test_representation_roundtrips_preserve_ownership_and_memory(self):
        p = self.source(self.MAKE + self.TOTAL + self.MAIN + 'let a = pass(make()); return total(move(a)) + 24u32 }\n')
        self.both(p, expected=42)
        expected = proc(OMNI, 'memory', p)
        self.assertEqual(expected.returncode, 0, expected.stderr)
        wave = proc(OMNI, 'wave', p); self.assertEqual(wave.returncode, 0, wave.stderr)
        self.assertTrue(wave.stdout.startswith(b'(omni-wave 21'))
        wp = self.dir/'array.owave'; wp.write_bytes(wave.stdout)
        representations = [wp]
        for command, ext in (('pack', 'owire'), ('onme', 'onme')):
            output = self.dir/('array.'+ext)
            result = proc(OMNI, command, p, '-o', output)
            self.assertEqual(result.returncode, 0, result.stderr); representations.append(output)
        for representation in representations:
            self.both(representation)
            actual = proc(OMNI, 'memory', representation)
            self.assertEqual(actual.returncode, 0, actual.stderr)
            self.assertEqual(actual.stdout, expected.stdout)

    def test_owning_array_cannot_hide_under_legacy_versions(self):
        programs = (self.MAKE + self.TOTAL + self.MAIN + 'let a = make(); return total(move(a)) }\n',
                    'struct Unused { a Array<Result<u32,u32>,2> }\nfunc main() u32 { return 42u32 }\n',
                    # only the Array arm of the declaration fence can see this one: Resource<Buffer> is neither nominal nor pending
                    'struct Unused { a Array<Resource<Buffer>,2> }\nfunc main() u32 { return 42u32 }\n',
                    'func main() u32 { let a = array(Ok<u32,u32>(42u32)); match a[0u32] { Ok(n) { return n } Err(n) { return n } } }\n')
        for i, program in enumerate(programs):
            p = self.source(program, f'fence{i}.omni'); wave = proc(OMNI, 'wave', p)
            self.assertEqual(wave.returncode, 0, wave.stderr)
            self.assertTrue(wave.stdout.startswith(b'(omni-wave 21'))
            out = self.dir/f'fence{i}.owire'
            result = proc(OMNI, 'pack', p, '-o', out); self.assertEqual(result.returncode, 0, result.stderr)
            for ext, payload in (('owave', wave.stdout.replace(b'(omni-wave 21', b'(omni-wave 20', 1)),
                                 ('owire', b'OMCX\x14\x00\x00\x00'+out.read_bytes()[8:])):
                forged = self.dir/f'forged{i}.{ext}'; forged.write_bytes(payload)
                result = proc(OMNI, 'check', forged)
                self.assertEqual(result.returncode, 2, result.stderr); self.assertIn(b'E_VERSION', result.stderr)

    @unittest.skipUnless(os.environ.get('OMNI_BASELINE_BIN'), 'needs OMNI_BASELINE_BIN (compiler of the parent commit)')
    def test_programs_without_owning_arrays_emit_byte_identical_artifacts(self):
        programs = (
            'func main() u32 { let a = array(10u32, 20u32, 12u32); let b = array.with(a, 1u32, 0u32); var i u32 = 0u32; var s u32 = 0u32\n'
            '  for i < 3u32 { s = s + a[i] + b[i]; i = i + 1u32 }\n  for x in b { s = s + x }\n  let v = view(a); return s + view.len(v) + array.len(array.fill(1u32, 4u32)) }\n',
            'struct P { a u32, b Array<u32,4> }\nfunc main() u32 { let p = P { a: 1u32, b: array.fill(2u32, 4u32) }; let t = tuple(p.b, 3u32); return p.b[0u32] + tuple.get(t, 1u32) }\n',
        )
        baseline = os.environ['OMNI_BASELINE_BIN']
        for index, program in enumerate(programs):
            path = self.source(program, f'plain{index}.omni')
            for command in (('emit-llvm', '-o'), ('wave',), ('pack', '-o')):
                outputs = []
                for binary in (OMNI, baseline):
                    out = self.dir / f'plain{index}.{command[0]}.{"new" if binary == OMNI else "old"}'
                    out.unlink(missing_ok=True)
                    args = [binary, command[0], path] + ([command[1], out] if len(command) > 1 else [])
                    result = proc(*args)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    outputs.append(out.read_bytes() if len(command) > 1 else result.stdout)
                self.assertEqual(outputs[0].replace(b'1.3.0.0', b'X'), outputs[1].replace(b'1.3.0.0', b'X'), (index, command))
    @unittest.skipUnless(os.environ.get('OMNI_ARRAY_PARENT_BIN'), 'needs OMNI_ARRAY_PARENT_BIN (compiler of the parent of the owning-Array increment)')
    def test_the_compiler_before_the_owning_array_increment_rejects_what_it_admits(self):
        # Specific to ONE historical commit (the parent of the increment). It used to share OMNI_BASELINE_BIN with the byte-identity test above, which
        # made that test fail for any later baseline: the generic identity check and this historical statement are now separate.
        owning = self.source(self.MAKE + self.TOTAL + self.MAIN + 'return 0u32 }\n', 'owning.omni')
        self.assertEqual(proc(OMNI, 'check', owning).returncode, 0)
        refused = proc(os.environ['OMNI_ARRAY_PARENT_BIN'], 'check', owning)
        self.assertEqual(refused.returncode, 2)
        self.assertIn(b'E_PRODUCT_LINEAR', refused.stderr)

    def test_plain_arrays_keep_value_semantics_and_dynamic_indexing(self):
        self.both(self.source(
            'func main() u32 { let a = array(10u32, 20u32, 12u32); var i u32 = 0u32; var s u32 = 0u32\n'
            '  for i < 3u32 { s = s + a[i]; i = i + 1u32 }\n'
            '  let b = array.with(a, 1u32, 0u32); let f = array.fill(1u32, 4u32)\n'
            '  for x in b { s = s + x - x }\n  return s + array.len(f) - 4u32 }\n'))


class ProjectedCallLoanTests(unittest.TestCase):
    setUp = OptionOwningRecordTests.setUp
    tearDown = OptionOwningRecordTests.tearDown
    source = OptionOwningRecordTests.source
    both = OptionOwningRecordTests.both
    rejected = OptionOwningRecordTests.rejected
    PREFIX = ('struct Pair { a Resource<Buffer>, b Resource<Buffer> }\n'
        'func use(b Borrow<Buffer>, n u32) u32 !{memory.read} { return buffer.len(b) + n }\n'
        'func edit(b BorrowMut<Buffer>, n u32) u32 !{memory.read} { return buffer.len(b) + n }\n'
        'func main() u32 !{memory.read,memory.write} { let a = buffer.alloc(42u32); match a { Ok(x) { '
        'let b = buffer.alloc(1u32); match b { Ok(y) { ')
    SUFFIX = ' } Err(code) { return code } } } Err(code) { return code } } }\n'

    def test_nested_release_cannot_invalidate_earlier_projected_argument(self):
        for init,field in (('let p = Pair { a: move(x), b: move(y) };','p.a'),
                           ('let p = tuple(move(x),move(y));','tuple.get(p,0u32)')):
            for call,borrow in (('use','borrow'),('edit','borrow_mut')):
                with self.subTest(field=field,call=call):
                    self.rejected(self.PREFIX+init+f'return {call}({borrow}({field}),buffer.release(move({field})))'+self.SUFFIX,b'E_BORROW_CONFLICT')

    def test_whole_owner_move_also_overlaps_a_projected_call_loan(self):
        prefix=self.PREFIX.replace('func main()', 'func drop(p Pair) u32 !{memory.read} { return buffer.len(borrow(p.a)) }\nfunc main()')
        self.rejected(prefix+'let p = Pair { a: move(x), b: move(y) }; return use(borrow(p.a),drop(move(p)))'+self.SUFFIX,b'E_BORROW_CONFLICT')

    def test_disjoint_projected_arguments_and_shared_aliases_are_valid(self):
        for i,(init,first,second) in enumerate((
            ('let p = Pair { a: move(x), b: move(y) };','p.a','p.b'),
            ('let p = tuple(move(x),move(y));','tuple.get(p,0u32)','tuple.get(p,1u32)'))):
            self.both(self.source(self.PREFIX+init+f'return use(borrow({first}),buffer.release(move({second})))'+self.SUFFIX,f'disjoint{i}.omni'))
        prefix=self.PREFIX.replace('func main()', 'func pair(a BorrowMut<Buffer>, b BorrowMut<Buffer>) u32 !{memory.read} { return buffer.len(a) }\nfunc main()')
        self.both(self.source(prefix+'let p = Pair { a: move(x), b: move(y) }; return pair(borrow_mut(p.a),borrow_mut(p.b))'+self.SUFFIX,'exclusive.omni'))
        self.both(self.source('func twice(a Borrow<Buffer>, b Borrow<Buffer>) u32 !{memory.read} { return buffer.len(a) + buffer.len(b) }\n'
            'func main() u32 !{memory.read,memory.write} { let r = buffer.alloc(21u32); match r { Ok(b) { '
            'let p = tuple(move(b)); return twice(borrow(tuple.get(p,0u32)),borrow(tuple.get(p,0u32))) } Err(e) { return e } } }\n','shared.omni'))


if __name__ == '__main__':
    unittest.main()
