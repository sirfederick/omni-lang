#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import os
import pathlib
import re
import shutil
import subprocess
import tempfile
import unittest

ROOT=pathlib.Path(__file__).resolve().parents[1]
OMNI=pathlib.Path(os.environ.get('OMNI_TEST_BIN',ROOT/'bin/linux-x86_64/omni'))


def proc(*args:object,timeout:int=15)->subprocess.CompletedProcess[bytes]:
    return subprocess.run([str(x) for x in args],capture_output=True,timeout=timeout,
                          env={**os.environ,'OMNI_HOME':str(ROOT)})


class A83RootReborrowTests(unittest.TestCase):
    def setUp(self)->None:
        self.tmp=tempfile.TemporaryDirectory(prefix='omni-a83-')
        self.dir=pathlib.Path(self.tmp.name)

    def tearDown(self)->None:
        self.tmp.cleanup()

    def source(self,text:str)->pathlib.Path:
        path=self.dir/'program.omni'
        path.write_text(text,encoding='utf-8')
        return path

    def test_mutable_to_shared_reborrow_is_shorter_and_differential(self)->None:
        source=self.source('''module t
func main() u32 !{memory.read,memory.write} {
  let allocated Result<Resource<Buffer>,u32> = buffer.alloc(2u32)
  match allocated {
    Ok(buf) {
      let parent = borrow_mut(buf)
      let child = borrow(parent)
      let n = buffer.len(child)
      let released = buffer.release(move(buf))
      return n + released
    }
    Err(code) { return code }
  }
}
''')
        checked=proc(OMNI,'check',source)
        self.assertEqual(checked.returncode,0,checked.stderr)
        wave=proc(OMNI,'wave',source)
        self.assertEqual(wave.returncode,0,wave.stderr)
        self.assertTrue(wave.stdout.startswith(b'(omni-wave 18'))
        wire=self.dir/'reborrow.owire'
        packed=proc(OMNI,'pack',source,'-o',wire)
        self.assertEqual(packed.returncode,0,packed.stderr)
        raw=wire.read_bytes()
        self.assertEqual(raw[:8],b'OMCX\x12\x00\x00\x00')
        self.assertEqual(proc(OMNI,'check',wire).returncode,0)
        old_wave=self.dir/'reborrow-as-wave17.owave'
        old_wave.write_bytes(wave.stdout.replace(b'(omni-wave 18',b'(omni-wave 17',1))
        downgraded_wave=proc(OMNI,'check',old_wave)
        self.assertEqual(downgraded_wave.returncode,2,downgraded_wave.stderr)
        self.assertIn(b'E_VERSION',downgraded_wave.stderr)
        old_wire=self.dir/'reborrow-as-omc17.owire'
        old_wire.write_bytes(raw[:4]+(17).to_bytes(4,'little')+raw[8:])
        downgraded_wire=proc(OMNI,'check',old_wire)
        self.assertEqual(downgraded_wire.returncode,2,downgraded_wire.stderr)
        self.assertIn(b'E_VERSION',downgraded_wire.stderr)
        evaluated=proc(OMNI,'eval',source)
        self.assertEqual((evaluated.returncode,evaluated.stdout),(2,b''),evaluated.stderr)
        output=self.dir/'native'
        built=proc(OMNI,'build',source,'-o',output)
        self.assertEqual(built.returncode,0,built.stderr)
        native=proc(output)
        self.assertEqual((native.returncode,native.stdout),(2,b''),native.stderr)

    def test_shared_to_exclusive_reborrow_fails_closed(self)->None:
        source=self.source('''module t
func consume(child Borrow<Buffer>, parent BorrowMut<Buffer>) u32 !{memory.read} { return buffer.len(child) }
func main() u32 !{memory.read,memory.write} {
  let allocated Result<Resource<Buffer>,u32> = buffer.alloc(1u32)
  match allocated {
    Ok(buf) {
      let parent = borrow(buf)
      let child = borrow_mut(parent)
      return 0u32
    }
    Err(code) { return code }
  }
}
''')
        result=proc(OMNI,'check',source)
        self.assertEqual(result.returncode,2,result.stderr)
        self.assertIn(b'E_REBORROW_KIND',result.stderr)

    def test_parent_is_suspended_while_child_is_live(self)->None:
        source=self.source('''module t
func main() u32 !{memory.read,memory.write} {
  let allocated Result<Resource<Buffer>,u32> = buffer.alloc(1u32)
  match allocated {
    Ok(buf) {
      let parent = borrow_mut(buf)
      let child = borrow(parent)
      let n = consume(child,parent)
      let released = buffer.release(move(buf))
      return n + released
    }
    Err(code) { return code }
  }
}
''')
        result=proc(OMNI,'check',source)
        self.assertEqual(result.returncode,2,result.stderr)
        self.assertIn(b'E_BORROW_CONFLICT',result.stderr)

    def test_borrow_temporary_remains_a_place_error(self)->None:
        source=self.source('''module t
func id(x Resource<Buffer>) Resource<Buffer> !{memory.write} { return move(x) }
func main() u32 !{memory.read,memory.write} {
  let allocated Result<Resource<Buffer>,u32> = buffer.alloc(1u32)
  match allocated {
    Ok(buf) {
      let invalid = borrow(id(move(buf)))
      return 0u32
    }
    Err(code) { return code }
  }
}
''')
        result=proc(OMNI,'check',source)
        self.assertEqual(result.returncode,2,result.stderr)
        self.assertIn(b'E_PLACE',result.stderr)

    def test_proven_sibling_field_places_are_disjoint_and_differential(self)->None:
        source=self.source('''module t
struct Pair { left Resource<Buffer>, right Resource<Buffer> }
func main() u32 !{memory.read,memory.write} {
  let first Result<Resource<Buffer>,u32> = buffer.alloc(1u32)
  match first {
    Ok(left) {
      let second Result<Resource<Buffer>,u32> = buffer.alloc(2u32)
      match second {
        Ok(right) {
          let pair = Pair { left: move(left), right: move(right) }
          let write = borrow_mut(pair.left)
          let read = borrow(pair.right)
          let n = buffer.len(read)
          let released_left = buffer.release(move(pair.left))
          let released_right = buffer.release(move(pair.right))
          return n + released_left + released_right
        }
        Err(code) {
          let released = buffer.release(move(left))
          return code + released
        }
      }
    }
    Err(code) { return code }
  }
}
''')
        checked=proc(OMNI,'check',source)
        self.assertEqual(checked.returncode,0,checked.stderr)
        wave=proc(OMNI,'wave',source)
        self.assertEqual(wave.returncode,0,wave.stderr)
        self.assertTrue(wave.stdout.startswith(b'(omni-wave 18'))
        wire=self.dir/'fields.owire'
        packed=proc(OMNI,'pack',source,'-o',wire)
        self.assertEqual(packed.returncode,0,packed.stderr)
        raw=wire.read_bytes()
        self.assertEqual(raw[:8],b'OMCX\x12\x00\x00\x00')
        self.assertEqual(proc(OMNI,'check',wire).returncode,0)
        old_wave=self.dir/'fields-as-wave17.owave'
        old_wave.write_bytes(wave.stdout.replace(b'(omni-wave 18',b'(omni-wave 17',1))
        downgraded_wave=proc(OMNI,'check',old_wave)
        self.assertEqual(downgraded_wave.returncode,2,downgraded_wave.stderr)
        self.assertIn(b'E_VERSION',downgraded_wave.stderr)
        old_wire=self.dir/'fields-as-omc17.owire'
        old_wire.write_bytes(raw[:4]+(17).to_bytes(4,'little')+raw[8:])
        downgraded_wire=proc(OMNI,'check',old_wire)
        self.assertEqual(downgraded_wire.returncode,2,downgraded_wire.stderr)
        self.assertIn(b'E_VERSION',downgraded_wire.stderr)
        evaluated=proc(OMNI,'eval',source)
        self.assertEqual((evaluated.returncode,evaluated.stdout),(2,b''),evaluated.stderr)
        output=self.dir/'native-fields'
        built=proc(OMNI,'build',source,'-o',output)
        self.assertEqual(built.returncode,0,built.stderr)
        native=proc(output)
        self.assertEqual((native.returncode,native.stdout),(2,b''),native.stderr)

    def test_overlapping_field_loans_and_cleanup_fail_closed(self)->None:
        source=self.source('''module t
struct Box { item Resource<Buffer> }
func main() u32 !{memory.read,memory.write} {
  let allocated Result<Resource<Buffer>,u32> = buffer.alloc(1u32)
  match allocated {
    Ok(item) {
      let box = Box { item: move(item) }
      let shared = borrow(box.item)
      let exclusive = borrow_mut(box.item)
      return buffer.len(shared)
    }
    Err(code) { return code }
  }
}
''')
        result=proc(OMNI,'check',source)
        self.assertEqual(result.returncode,2,result.stderr)
        self.assertIn(b'E_BORROW_CONFLICT',result.stderr)

    def test_field_cleanup_cannot_overlap_a_live_descendant_loan(self)->None:
        source=self.source('''module t
struct Box { item Resource<Buffer> }
func main() u32 !{memory.read,memory.write} {
  let allocated Result<Resource<Buffer>,u32> = buffer.alloc(1u32)
  match allocated {
    Ok(item) {
      let box = Box { item: move(item) }
      let shared = borrow(box.item)
      let released = buffer.release(move(box.item))
      return buffer.len(shared) + released
    }
    Err(code) { return code }
  }
}
''')
        result=proc(OMNI,'check',source)
        self.assertEqual(result.returncode,2,result.stderr)
        self.assertIn(b'E_BORROW_CONFLICT',result.stderr)

    def test_resource_record_cannot_be_copied_outside_a_proven_field_place(self)->None:
        source=self.source('''module t
struct Box { item Resource<Buffer> }
func main() u32 !{memory.read,memory.write} {
  let allocated Result<Resource<Buffer>,u32> = buffer.alloc(1u32)
  match allocated {
    Ok(item) {
      let box = Box { item: move(item) }
      let copied = box
      return 0u32
    }
    Err(code) { return code }
  }
}
''')
        result=proc(OMNI,'check',source)
        self.assertEqual(result.returncode,2,result.stderr)
        self.assertIn(b'E_RESOURCE_ACCESS',result.stderr)

    def test_field_ownership_requires_equal_continuing_branch_state(self)->None:
        source=self.source('''module t
struct Box { item Resource<Buffer> }
func main() u32 !{memory.write} {
  let allocated Result<Resource<Buffer>,u32> = buffer.alloc(1u32)
  match allocated {
    Ok(item) {
      let box = Box { item: move(item) }
      if true {
        let released = buffer.release(move(box.item))
      } else {
        let unchanged = 0u32
      }
      return 0u32
    }
    Err(code) { return code }
  }
}
''')
        result=proc(OMNI,'check',source)
        self.assertEqual(result.returncode,2,result.stderr)
        self.assertIn(b'E_RESOURCE_FLOW',result.stderr)

    def test_field_ownership_can_discharge_on_each_continuing_branch(self)->None:
        source=self.source('''module t
struct Box { item Resource<Buffer> }
func main() u32 !{memory.write} {
  let allocated Result<Resource<Buffer>,u32> = buffer.alloc(1u32)
  match allocated {
    Ok(item) {
      let box = Box { item: move(item) }
      if true {
        let released = buffer.release(move(box.item))
      } else {
        let released = buffer.release(move(box.item))
      }
      return 0u32
    }
    Err(code) { return code }
  }
}
''')
        result=proc(OMNI,'check',source)
        self.assertEqual(result.returncode,0,result.stderr)

    def test_reborrow_cannot_be_relabelled_as_wave17(self)->None:
        source=self.source('''module t
func main() u32 !{memory.read,memory.write} {
  let allocated Result<Resource<Buffer>,u32> = buffer.alloc(1u32)
  match allocated {
    Ok(buf) {
      let parent = borrow_mut(buf)
      let child = borrow(parent)
      let n = buffer.len(child)
      let released = buffer.release(move(buf))
      return n + released
    }
    Err(code) { return code }
  }
}
''')
        canonical=proc(OMNI,'wave',source)
        self.assertEqual(canonical.returncode,0,canonical.stderr)
        relabelled=self.dir/'reborrow-as-wave17.owave'
        relabelled.write_bytes(canonical.stdout.replace(b'(omni-wave 18',b'(omni-wave 17',1))
        result=proc(OMNI,'check',relabelled)
        self.assertEqual(result.returncode,2,result.stderr)
        self.assertIn(b'E_VERSION',result.stderr)

    def test_structured_cleanup_on_return_and_fallthrough_is_differential(self)->None:
        source=self.source('''module t
func main() u32 !{memory.write} {
  let first Result<Resource<Buffer>,u32> = buffer.alloc(1u32)
  match first {
    Ok(buf) {
      let marker = 1u32
    }
    Err(code) { return code }
  }
  let second Result<Resource<Buffer>,u32> = buffer.alloc(1u32)
  match second {
    Ok(buf) { return 7u32 }
    Err(code) { return code }
  }
}
''')
        checked=proc(OMNI,'check',source)
        self.assertEqual(checked.returncode,0,checked.stderr)
        evaluated=proc(OMNI,'eval',source)
        self.assertEqual((evaluated.returncode,evaluated.stdout),(7,b''),evaluated.stderr)
        output=self.dir/'native-structured-cleanup'
        built=proc(OMNI,'build',source,'-o',output)
        self.assertEqual(built.returncode,0,built.stderr)
        native=proc(output)
        self.assertEqual((native.returncode,native.stdout),(7,b''),native.stderr)

    def test_structured_cleanup_on_break_and_continue_is_differential(self)->None:
        source=self.source('''module t
func main() u32 !{memory.write} {
  let values Array<u32,3> = array(1u32,2u32,3u32)
  var total u32 = 0u32
  for x in values {
    let allocated Result<Resource<Buffer>,u32> = buffer.alloc(1u32)
    match allocated {
      Ok(buf) {
        if x==1u32 { continue }
        if x==3u32 { break }
        total = total + x
      }
      Err(code) { return code }
    }
  }
  return total
}
''')
        checked=proc(OMNI,'check',source)
        self.assertEqual(checked.returncode,0,checked.stderr)
        evaluated=proc(OMNI,'eval',source)
        self.assertEqual((evaluated.returncode,evaluated.stdout),(2,b''),evaluated.stderr)
        output=self.dir/'native-loop-cleanup'
        built=proc(OMNI,'build',source,'-o',output)
        self.assertEqual(built.returncode,0,built.stderr)
        native=proc(output)
        self.assertEqual((native.returncode,native.stdout),(2,b''),native.stderr)

    def test_projected_record_cleanup_runs_once_on_return(self)->None:
        source=self.source('''module t
struct Pair { left Resource<Buffer>, right Resource<Buffer> }
func main() u32 !{memory.write} {
  let first Result<Resource<Buffer>,u32> = buffer.alloc(1u32)
  match first {
    Ok(left) {
      let second Result<Resource<Buffer>,u32> = buffer.alloc(1u32)
      match second {
        Ok(right) {
          let pair = Pair { left: move(left), right: move(right) }
          return 9u32
        }
        Err(code) { return code }
      }
    }
    Err(code) { return code }
  }
}
''')
        checked=proc(OMNI,'check',source)
        self.assertEqual(checked.returncode,0,checked.stderr)
        evaluated=proc(OMNI,'eval',source)
        self.assertEqual((evaluated.returncode,evaluated.stdout),(9,b''),evaluated.stderr)
        output=self.dir/'native-record-cleanup'
        built=proc(OMNI,'build',source,'-o',output)
        self.assertEqual(built.returncode,0,built.stderr)
        native=proc(output)
        self.assertEqual((native.returncode,native.stdout),(9,b''),native.stderr)

    def test_cleanup_bearing_wave17_payload_is_rejected(self)->None:
        source=self.source('''module t
func main() u32 !{memory.write} {
  let allocated Result<Resource<Buffer>,u32> = buffer.alloc(1u32)
  match allocated {
    Ok(buf) { return 0u32 }
    Err(code) { return code }
  }
}
''')
        canonical=proc(OMNI,'wave',source)
        self.assertEqual(canonical.returncode,0,canonical.stderr)
        relabelled=self.dir/'cleanup-as-wave17.owave'
        relabelled.write_bytes(canonical.stdout.replace(b'(omni-wave 18',b'(omni-wave 17',1))
        result=proc(OMNI,'check',relabelled)
        self.assertEqual(result.returncode,2,result.stderr)
        self.assertIn(b'E_VERSION',result.stderr)


class A83BorrowConflictNoBypassTests(unittest.TestCase):
    """OMNI-CORE-DX-DIAGNOSTIC-FABRIC-001 slice 1.

    One existing Core obligation (call-argument loan conflict, E_BORROW_CONFLICT)
    must stop every load path before any artifact is produced. The negative is
    the positive plus the minimal edit that reaches the rule; it is also
    admitted as .owave (textual edit of the canonical wave) and .owire (golden
    bytes, see NEG_OWIRE_*), because the frontend cannot emit an invalid
    machine form.
    """

    POSITIVE='''module t
func consume(child Borrow<Buffer>) u32 !{memory.read} { return buffer.len(child) }
func main() u32 !{memory.read,memory.write} {
  let allocated Result<Resource<Buffer>,u32> = buffer.alloc(2u32)
  match allocated {
    Ok(buf) {
      let parent = borrow_mut(buf)
      let child = borrow(parent)
      let n = consume(child)
      let released = buffer.release(move(buf))
      return n + released + 40u32
    }
    Err(code) { return code }
  }
}
'''
    NEGATIVE=POSITIVE.replace('func consume(child Borrow<Buffer>)','func consume(child Borrow<Buffer>, parent BorrowMut<Buffer>)').replace('consume(child)','consume(child,parent)')
    # Produced once by parsing NEGATIVE without validate() and serialising with the
    # production wire(); the same driver reproduced the positive wire byte-for-byte.
    NEG_OWIRE_SHA256='26e54314fdcb0e48c259962c8c1d3a0bc6387856034ce521db2a341e06dfb8b6'
    NEG_OWIRE_HEX=(
        '4f4d43581200000001000000740100000001000000740000000000000000000000000200000007000000636f6e73756d',
        '650003000000753332010000000b0000006d656d6f72792e726561640200000000000000050000006368696c640e0000',
        '00426f72726f773c4275666665723e0000000006000000706172656e7411000000426f72726f774d75743c4275666665',
        '723e0100000003030a0000006275666665722e6c656e0100000002050000006368696c64040000006d61696e00030000',
        '00753332020000000b0000006d656d6f72792e726561640c0000006d656d6f72792e7772697465000000000200000000',
        '09000000616c6c6f63617465641c000000526573756c743c5265736f757263653c4275666665723e2c7533323e030c00',
        '00006275666665722e616c6c6f630100000000030000007533320200000000000000080209000000616c6c6f63617465',
        '6403000000627566050000000006000000706172656e7405000000696e666572030a000000626f72726f775f6d757401',
        '000000020300000062756600050000006368696c6405000000696e6665720306000000626f72726f7701000000020600',
        '0000706172656e7400010000006e05000000696e6665720307000000636f6e73756d650200000002050000006368696c',
        '640206000000706172656e74000800000072656c656173656405000000696e666572030e0000006275666665722e7265',
        '6c656173650100000003040000006d6f76650100000002030000006275660305010000002b0200000005010000002b02',
        '00000002010000006e020800000072656c65617365640003000000753332280000000000000004000000636f64650100',
        '0000030204000000636f6465',
    )
    CODE=b'E_BORROW_CONFLICT'
    LOAD_ONLY=('check','wave','hash','manifest','capabilities','deps','memory','graph','summary',
               'onme-stats','pulse','cognition','emit-llvm','fmt','eval','observe','test','run','profile','coverage')
    WRITERS=('pack','onme','memory-pack','emit-llvm','build')

    def setUp(self)->None:
        self.tmp=tempfile.TemporaryDirectory(prefix='omni-a83-nobypass-')
        self.dir=pathlib.Path(self.tmp.name)
        self.pos=self.dir/'pos.omni'; self.pos.write_text(self.POSITIVE,encoding='utf-8')
        self.neg=self.dir/'neg.omni'; self.neg.write_text(self.NEGATIVE,encoding='utf-8')
        canonical=proc(OMNI,'wave',self.pos); self.assertEqual(canonical.returncode,0,canonical.stderr)
        edited=(canonical.stdout
                .replace(b'(params (child Borrow<Buffer>))',b'(params (child Borrow<Buffer>) (parent BorrowMut<Buffer>))',1)
                .replace(b'(call consume (ref child))',b'(call consume (ref child) (ref parent))',1))
        self.assertNotEqual(edited,canonical.stdout)
        self.pos_wave=self.dir/'pos.owave'; self.pos_wave.write_bytes(canonical.stdout)
        self.neg_wave=self.dir/'neg.owave'; self.neg_wave.write_bytes(edited)
        wire=bytes.fromhex(''.join(self.NEG_OWIRE_HEX))
        self.assertEqual(hashlib.sha256(wire).hexdigest(),self.NEG_OWIRE_SHA256)
        self.neg_wire=self.dir/'neg.owire'; self.neg_wire.write_bytes(wire)
        self.pos_wire=self.dir/'pos.owire'
        self.assertEqual(proc(OMNI,'pack',self.pos,'-o',self.pos_wire).returncode,0)

    def tearDown(self)->None:
        self.tmp.cleanup()

    def rejected(self,result:subprocess.CompletedProcess[bytes],label:str)->None:
        self.assertEqual(result.returncode,2,f'{label}: {result.stderr!r}')
        self.assertIn(self.CODE,result.stderr,label)
        self.assertEqual(result.stdout,b'',label)

    def test_valid_program_is_accepted_on_every_representation_with_evaluator_native_parity(self)->None:
        for path in (self.pos,self.pos_wave,self.pos_wire):
            self.assertEqual(proc(OMNI,'check',path).returncode,0,path.name)
            self.assertEqual(proc(OMNI,'eval',path).returncode,42,path.name)
        native=self.dir/'pos-native'
        built=proc(OMNI,'build',self.pos,'-o',native,'--cache-dir',self.dir/'cache-parity')
        self.assertEqual(built.returncode,0,built.stderr)
        self.assertEqual(proc(native).returncode,42)

    def test_invalid_program_is_rejected_by_every_load_path_without_artifact(self)->None:
        for path in (self.neg,self.neg_wave,self.neg_wire):
            for command in self.LOAD_ONLY:
                self.rejected(proc(OMNI,command,path),f'{command} {path.name}')
            for command in self.WRITERS:
                previous=self.dir/f'previous-{command}.out'
                sibling=pathlib.Path(str(previous)+'.ometa.json')
                previous.write_bytes(b'PREVIOUS'); before=previous.read_bytes()
                self.rejected(proc(OMNI,command,path,'-o',previous,'--force'),f'{command} -o {path.name}')
                self.assertEqual(previous.read_bytes(),before,f'{command} {path.name} replaced prior output')
                self.assertFalse(sibling.exists(),f'{command} {path.name} produced receipt for rejected input')
                previous.unlink()

    def test_safety_verdict_is_not_changed_by_any_accepted_option(self)->None:
        for options in (('--force',),('--no-cache',),('--opt','2'),('--force','--no-cache','--opt','2')):
            output=self.dir/'never-built'
            self.rejected(proc(OMNI,'build',self.neg,'-o',output,*options),f'build {options}')
            self.assertFalse(output.exists())
        for options in (('--deny-excess-capabilities',),('--diagnostic-format','text')):
            self.assertEqual(proc(OMNI,'check',self.neg,*options).returncode,2)
        as_json=proc(OMNI,'check',self.neg,'--diagnostic-format','json')
        self.assertEqual(as_json.returncode,2)
        record=json.loads(as_json.stderr)
        self.assertEqual((record['schema'],record['code'],record['category'],record['severity']),
                         ('omni.diagnostic/1','E_BORROW_CONFLICT','memory-resource','error'))
        self.assertEqual((record['span']['line'],record['span']['column']),(9,15))

    def test_build_cache_never_admits_the_invalid_program(self)->None:
        cache=self.dir/'cache'
        first=proc(OMNI,'build',self.pos,'-o',self.dir/'p1','--cache-dir',cache)
        self.assertEqual(first.returncode,0,first.stderr); self.assertIn(b'[cache miss]',first.stdout)
        second=proc(OMNI,'build',self.pos,'-o',self.dir/'p2','--cache-dir',cache)
        self.assertEqual(second.returncode,0,second.stderr); self.assertIn(b'[cache hit]',second.stdout)
        keys=sorted(p.name for p in (cache/'build-v1').iterdir())
        kept=(self.dir/'p1').read_bytes()
        for path in (self.neg,self.neg_wave,self.neg_wire):
            absent=self.dir/f'n-{path.name}'
            self.rejected(proc(OMNI,'build',path,'-o',absent,'--cache-dir',cache),f'cache {path.name}')
            self.assertFalse(absent.exists())
            self.rejected(proc(OMNI,'build',path,'-o',self.dir/'p1','--cache-dir',cache,'--force'),f'cache force {path.name}')
            self.assertEqual((self.dir/'p1').read_bytes(),kept)
            self.rejected(proc(OMNI,'run',path,'--cache-dir',cache),f'run {path.name}')
        self.assertEqual(sorted(p.name for p in (cache/'build-v1').iterdir()),keys)


class A83DiagnosticRegistryRatchetTests(unittest.TestCase):
    """Every code the compiler can emit is registered, or is a named known gap.

    The known set is empty and may only grow by an explicit, reviewed decision;
    a new unregistered emitter fails the test. CATEGORIES pins the compatibility
    surface chosen when slice 1b registered the previously missing codes.
    """

    KNOWN_UNREGISTERED:frozenset[str]=frozenset()
    CATEGORIES={
        'E_CHAR_RANGE':'runtime','E_CLOSURE':'types','E_CLOSURE_CAPTURE':'memory-resource','E_CLOSURE_RETURN':'types',
        'E_METHOD_RECEIVER':'types','E_PARTICLE':'syntax','E_DURABILITY':'toolchain','E_HOST_ENTRY':'tooling',
        'E_HOST_SDK_SCHEMA':'representation','E_OMID_IDENTITY':'representation','E_OMI_LIMIT':'representation',
        'E_OMI_MALFORMED':'representation','E_OMI_TYPE':'representation','E_OMI_VERSION':'representation',
        'E_PACKAGE_CYCLE':'toolchain','E_PACKAGE_LOCK':'toolchain','E_PACKAGE_MANIFEST':'toolchain',
        'E_PACKAGE_OFFLINE':'toolchain','E_PACKAGE_PATH':'toolchain','E_PACKAGE_RESOLVE':'toolchain',
    }

    def test_formerly_unregistered_codes_have_a_stable_non_internal_category(self)->None:
        by={entry['code']:entry['category'] for entry in json.loads(proc(OMNI,'diagnostics').stdout)['codes']}
        self.assertEqual({code:by.get(code) for code in self.CATEGORIES},self.CATEGORIES)

    def test_emitted_codes_are_registered_or_known_gaps(self)->None:
        registry={entry['code'] for entry in json.loads(proc(OMNI,'diagnostics').stdout)['codes']}
        emitted:set[str]=set()
        for source in sorted((ROOT / "compiler/src").glob('*.cpp')):
            for line in source.read_text(encoding='utf-8').splitlines():
                if 'fail(' in line or 'Error(' in line or 'throw' in line:
                    emitted.update(re.findall(r'"(E_[A-Z0-9_]+)"',line))
        unregistered=emitted-registry
        self.assertEqual(unregistered-self.KNOWN_UNREGISTERED,set(),'new emitted code without registry entry')
        self.assertEqual(self.KNOWN_UNREGISTERED-unregistered,set(),'ratchet: delete codes that are now registered')


class A83BorrowReturnRegionTests(unittest.TestCase):
    """CP-02a (spec/BORROW_RETURN_REGIONS_CANDIDATE.md): a returned borrow is tied to one borrowed parameter."""

    LEND='func lend(b Borrow<Buffer>) Borrow<Buffer> !{memory.read} { return b }\n'
    LEND_MUT='func lendm(b BorrowMut<Buffer>) BorrowMut<Buffer> !{memory.read,memory.write} { return b }\n'

    @staticmethod
    def main_with(body:str)->str:
        return ('func main() u32 !{memory.read,memory.write} {\n'
                '  let first Result<Resource<Buffer>,u32> = buffer.alloc(3u32)\n'
                '  match first {\n    Ok(buf) {\n'+body+'    }\n    Err(code) { return code }\n  }\n}\n')

    def setUp(self)->None:
        self.tmp=tempfile.TemporaryDirectory(prefix='omni-a83-region-')
        self.dir=pathlib.Path(self.tmp.name)

    def tearDown(self)->None:
        self.tmp.cleanup()

    def source(self,text:str,name:str='program.omni')->pathlib.Path:
        path=self.dir/name
        path.write_text('module t\n'+text,encoding='utf-8')
        return path

    def rejected(self,text:str,code:bytes)->None:
        result=proc(OMNI,'check',self.source(text))
        self.assertEqual(result.returncode,2,result.stderr)
        self.assertIn(code,result.stderr)
        output=self.dir/'never'
        built=proc(OMNI,'build',self.dir/'program.omni','-o',output,'--cache-dir',self.dir/'cache')
        self.assertEqual(built.returncode,2,built.stderr)
        self.assertFalse(output.exists())

    def test_returned_borrow_is_accepted_with_evaluator_native_parity_and_wave21(self)->None:
        shared=self.LEND+self.main_with('      let v = lend(borrow(buf))\n      let n = buffer.len(v)\n'
                                        '      let r = buffer.release(move(buf))\n      return n + r + 40u32\n')
        reborrowed=self.LEND+self.main_with('      let a = borrow(buf)\n      let v = lend(a)\n      let n = buffer.len(v)\n'
                                            '      let r = buffer.release(move(buf))\n      return n + r + 40u32\n')
        exclusive=self.LEND_MUT+self.main_with('      let w = lendm(borrow_mut(buf))\n      let n = buffer.len(borrow(w))\n'
                                               '      let r = buffer.release(move(buf))\n      return n + r + 40u32\n')
        for index,text in enumerate((shared,reborrowed,exclusive)):
            path=self.source(text,f'ok{index}.omni')
            self.assertEqual(proc(OMNI,'check',path).returncode,0,text)
            self.assertEqual(proc(OMNI,'eval',path).returncode,43,text)
            native=self.dir/f'native{index}'
            built=proc(OMNI,'build',path,'-o',native,'--cache-dir',self.dir/'cache')
            self.assertEqual(built.returncode,0,built.stderr)
            self.assertEqual(proc(native).returncode,43)
            wave=proc(OMNI,'wave',path); self.assertTrue(wave.stdout.startswith(b'(omni-wave 21'))
            wire=self.dir/f'ok{index}.owire'; self.assertEqual(proc(OMNI,'pack',path,'-o',wire).returncode,0)
            self.assertEqual(wire.read_bytes()[:8],b'OMCX\x15\x00\x00\x00')
            self.assertEqual(proc(OMNI,'eval',wire).returncode,43)

    def test_programs_without_returned_borrows_keep_their_representation(self)->None:
        path=self.source('func main() u32 { return 7u32 }\n')
        self.assertTrue(proc(OMNI,'wave',path).stdout.startswith(b'(omni-wave 18'))

    def test_wave21_and_omc21_cannot_be_relabelled_as_older(self)->None:
        path=self.source(self.LEND+self.main_with('      let v = lend(borrow(buf))\n      let r = buffer.release(move(buf))\n      return r\n'))
        wave=proc(OMNI,'wave',path).stdout
        old_wave=self.dir/'old.owave'; old_wave.write_bytes(wave.replace(b'(omni-wave 21',b'(omni-wave 20',1))
        result=proc(OMNI,'check',old_wave); self.assertEqual(result.returncode,2); self.assertIn(b'E_VERSION',result.stderr)
        wire=self.dir/'new.owire'; self.assertEqual(proc(OMNI,'pack',path,'-o',wire).returncode,0)
        raw=bytearray(wire.read_bytes()); raw[4]=20
        old_wire=self.dir/'old.owire'; old_wire.write_bytes(bytes(raw))
        result=proc(OMNI,'check',old_wire); self.assertEqual(result.returncode,2); self.assertIn(b'E_VERSION',result.stderr)

    def test_region_contract_violations_are_rejected_without_artifact(self)->None:
        cases=(
            ('two region sources','func pick(a Borrow<Buffer>, b Borrow<Buffer>) Borrow<Buffer> !{memory.read} { return a }\n',b'E_BORROW_ESCAPE'),
            ('no region source','func none(x u32) Borrow<Buffer> !{memory.read} { return x }\n',b'E_BORROW_ESCAPE'),
            ('kind mismatch','func up(b Borrow<Buffer>) BorrowMut<Buffer> !{memory.read} { return b }\n',b'E_BORROW_ESCAPE'),
            ('return through call',self.LEND+'func again(b Borrow<Buffer>) Borrow<Buffer> !{memory.read} { return lend(b) }\n',b'E_BORROW_ESCAPE'),
            # BORROW_RETURN_REGIONS_CANDIDATE.md §2.2: returning a local is E_BORROW_ESCAPE. It used to read E_BORROW_EXPIRED only because `borrow(parameter)` itself was
            # rejected (a parameter had no ledger entry); a parameter can now be reborrowed and the escape is diagnosed for what it is.
            ('return local reborrow','func bad(b Borrow<Buffer>) Borrow<Buffer> !{memory.read} {\n  let local = borrow(b)\n  return local\n}\n',b'E_BORROW_ESCAPE'),
            ('nested call position',self.LEND+self.main_with('      let n = buffer.len(lend(borrow(buf)))\n      let r = buffer.release(move(buf))\n      return n + r\n'),b'E_BORROW_ESCAPE'),
            ('release while live',self.LEND+self.main_with('      let v = lend(borrow(buf))\n      let r = buffer.release(move(buf))\n      return buffer.len(v) + r\n'),b'E_BORROW_CONFLICT'),
            ('reader during exclusive',self.LEND_MUT+self.main_with('      let w = lendm(borrow_mut(buf))\n      let s = borrow(buf)\n      let n = buffer.len(borrow(w))\n      let r = buffer.release(move(buf))\n      return n + r + buffer.len(s)\n'),b'E_BORROW_CONFLICT'),
        )
        for label,text,code in cases:
            with self.subTest(label):
                self.rejected(text,code)

    def test_borrowmut_exclusivity_is_enforced_for_the_whole_returned_region(self)->None:
        cases=(
            ('second borrow_mut while live',self.LEND_MUT+self.main_with('      let w = lendm(borrow_mut(buf))\n      let x = borrow_mut(buf)\n      let n = buffer.len(borrow(w))\n      let r = buffer.release(move(buf))\n      return n + r\n'),b'E_BORROW_CONFLICT'),
            ('shared returned borrow blocks writer',self.LEND+self.main_with('      let v = lend(borrow(buf))\n      let x = borrow_mut(buf)\n      let n = buffer.len(v)\n      let r = buffer.release(move(buf))\n      return n + r\n'),b'E_BORROW_CONFLICT'),
            ('parent borrow suspended by returned child',self.LEND_MUT+self.main_with('      let a = borrow_mut(buf)\n      let w = lendm(a)\n      let n = buffer.len(borrow(a))\n      let m = buffer.len(borrow(w))\n      let r = buffer.release(move(buf))\n      return n + m + r\n'),b'E_BORROW_CONFLICT'),
            ('shared parent cannot yield exclusive child',self.LEND_MUT+self.main_with('      let a = borrow(buf)\n      let w = lendm(a)\n      let r = buffer.release(move(buf))\n      return r\n'),b'E_TYPE'),
        )
        for label,text,code in cases:
            with self.subTest(label):
                self.rejected(text,code)

    def test_exclusive_region_ends_at_last_use_and_the_origin_is_usable_again(self)->None:
        text=self.LEND_MUT+self.main_with('      let w = lendm(borrow_mut(buf))\n      let n = buffer.len(borrow(w))\n'
                                          '      let again = borrow_mut(buf)\n      let m = buffer.len(borrow(again))\n'
                                          '      let r = buffer.release(move(buf))\n      return n + m + r + 40u32\n')
        path=self.source(text); self.assertEqual(proc(OMNI,'check',path).returncode,0)
        self.assertEqual(proc(OMNI,'eval',path).returncode,46)
        native=self.dir/'native'; self.assertEqual(proc(OMNI,'build',path,'-o',native,'--cache-dir',self.dir/'cache').returncode,0)
        self.assertEqual(proc(native).returncode,46)


class A83BitIntrinsicTests(unittest.TestCase):
    """CP-07 (spec/BIT_INTRINSICS_CANDIDATE.md): integer bit intrinsics, evaluator/native parity, Wave21 fence."""

    def setUp(self)->None:
        self.tmp=tempfile.TemporaryDirectory(prefix='omni-a83-bit-')
        self.dir=pathlib.Path(self.tmp.name)

    def tearDown(self)->None:
        self.tmp.cleanup()

    def source(self,body:str,name:str='program.omni')->pathlib.Path:
        path=self.dir/name
        path.write_text('module t\nfunc main() u32 {\n'+body+'}\n',encoding='utf-8')
        return path

    def run_both(self,path:pathlib.Path)->tuple[int,int]:
        evaluated=proc(OMNI,'eval',path)
        native=self.dir/(path.stem+'-native')
        built=proc(OMNI,'build',path,'-o',native,'--cache-dir',self.dir/'cache')
        self.assertEqual(built.returncode,0,built.stderr)
        return evaluated.returncode,proc(native).returncode

    def test_values_match_python_oracle_in_evaluator_and_native(self)->None:
        def mask(bits:int)->int: return (1<<bits)-1
        cases=[]
        for ty,bits in (('u8',8),('u16',16),('u32',32),('u64',64)):
            a,b=0xCC&mask(bits),0xAA&mask(bits)
            top=1<<(bits-1)
            cases+=[
                (f'bit.and({a}{ty},{b}{ty})',ty,a&b),(f'bit.or({a}{ty},{b}{ty})',ty,a|b),(f'bit.xor({a}{ty},{b}{ty})',ty,a^b),
                (f'bit.not({a}{ty})',ty,~a&mask(bits)),(f'bit.shl({top|1}{ty},1u32)',ty,((top|1)<<1)&mask(bits)),
                (f'bit.shr({top|1}{ty},{bits-1}u32)',ty,1),(f'bit.shl(1{ty},{bits-1}u32)',ty,top),
            ]
        cases+=[('bit.shr(-128i8,7u32)','i8',-1),('bit.shr(-8i32,1u32)','i32',-4),('bit.shr(-9223372036854775807i64,62u32)','i64',-2),
                ('bit.not(0i16)','i16',-1),('bit.and(-1i64,1099511627776i64)','i64',1099511627776)]
        for index,(expr,ty,expected) in enumerate(cases):
            with self.subTest(expr):
                path=self.source(f'  let v {ty} = {expr}\n  if v == {expected}{ty} {{ return 42u32 }}\n  return 1u32\n',f'c{index}.omni')
                self.assertEqual(self.run_both(path),(42,42),expr)

    def test_shl_discards_bits_that_leave_the_width_before_any_widening(self)->None:
        path=self.source('  let narrow u8 = bit.shl(129u8,1u32)\n  let wide u16 = u16(narrow)\n  if wide == 2u16 { return 42u32 }\n  return 1u32\n')
        self.assertEqual(self.run_both(path),(42,42))

    def test_representation_is_wave21_only_when_an_intrinsic_is_used(self)->None:
        used=self.source('  let v u8 = bit.not(1u8)\n  if v == 254u8 { return 42u32 }\n  return 1u32\n')
        self.assertTrue(proc(OMNI,'wave',used).stdout.startswith(b'(omni-wave 21'))
        wire=self.dir/'used.owire'; self.assertEqual(proc(OMNI,'pack',used,'-o',wire).returncode,0)
        self.assertEqual(wire.read_bytes()[:8],b'OMCX\x15\x00\x00\x00'); self.assertEqual(proc(OMNI,'eval',wire).returncode,42)
        old_wave=self.dir/'old.owave'; old_wave.write_bytes(proc(OMNI,'wave',used).stdout.replace(b'(omni-wave 21',b'(omni-wave 20',1))
        result=proc(OMNI,'check',old_wave); self.assertEqual(result.returncode,2); self.assertIn(b'E_VERSION',result.stderr)
        raw=bytearray(wire.read_bytes()); raw[4]=20; old_wire=self.dir/'old.owire'; old_wire.write_bytes(bytes(raw))
        result=proc(OMNI,'check',old_wire); self.assertEqual(result.returncode,2); self.assertIn(b'E_VERSION',result.stderr)
        plain=self.source('  return 7u32\n','plain.omni')
        self.assertTrue(proc(OMNI,'wave',plain).stdout.startswith(b'(omni-wave 18'))

    def test_shift_count_out_of_range_is_rejected_statically_or_traps(self)->None:
        literal=self.source('  let v u8 = bit.shl(1u8,8u32)\n  return 0u32\n','literal.omni')
        result=proc(OMNI,'check',literal); self.assertEqual(result.returncode,2); self.assertIn(b'E_BOUNDS',result.stderr)
        dynamic=self.source('  let n u32 = 64u32\n  let v u64 = bit.shl(1u64,n)\n  return 0u32\n','dynamic.omni')
        self.assertEqual(proc(OMNI,'check',dynamic).returncode,0)
        evaluated=proc(OMNI,'eval',dynamic); self.assertNotEqual(evaluated.returncode,0); self.assertIn(b'E_BOUNDS',evaluated.stderr)
        native=self.dir/'dynamic-native'
        self.assertEqual(proc(OMNI,'build',dynamic,'-o',native,'--cache-dir',self.dir/'cache').returncode,0)
        trapped=proc(native); self.assertNotEqual(trapped.returncode,0); self.assertIn(b'E_BOUNDS',trapped.stderr)

    def test_shift_count_boundary_for_every_integer_width(self)->None:
        for ty,width in (('u8',8),('u16',16),('u32',32),('u64',64),('i8',8),('i16',16),('i32',32),('i64',64)):
            for op in ('shl','shr'):
                with self.subTest(f'{op} {ty}'):
                    for count in (width,width+1,4294967295):
                        literal=self.source(f'  let v {ty} = bit.{op}(1{ty},{count}u32)\n  return 0u32\n',f'lit-{ty}-{op}-{count}.omni')
                        result=proc(OMNI,'check',literal)
                        self.assertEqual(result.returncode,2,(ty,op,count)); self.assertIn(b'E_BOUNDS',result.stderr)
                    last=self.source(f'  let n u32 = {width-1}u32\n  let v {ty} = bit.{op}(1{ty},n)\n  if v == v {{ return 42u32 }}\n  return 1u32\n',f'last-{ty}-{op}.omni')
                    self.assertEqual(self.run_both(last),(42,42))
                    over=self.source(f'  let n u32 = {width}u32\n  let v {ty} = bit.{op}(1{ty},n)\n  return 0u32\n',f'over-{ty}-{op}.omni')
                    self.assertEqual(proc(OMNI,'check',over).returncode,0)
                    evaluated=proc(OMNI,'eval',over); self.assertNotEqual(evaluated.returncode,0); self.assertIn(b'E_BOUNDS',evaluated.stderr)
                    native=self.dir/f'over-{ty}-{op}-native'
                    self.assertEqual(proc(OMNI,'build',over,'-o',native,'--cache-dir',self.dir/'cache').returncode,0)
                    trapped=proc(native); self.assertNotEqual(trapped.returncode,0); self.assertIn(b'E_BOUNDS',trapped.stderr)

    def test_shr_of_sign_bit_differs_between_signed_and_unsigned_types(self)->None:
        for ty,literal,expected in (('i8','-128i8','-1i8'),('u8','128u8','1u8'),('i64','-9223372036854775807i64','-1i64'),('u64','9223372036854775809u64','1u64')):
            with self.subTest(ty):
                path=self.source(f'  let v {ty} = bit.shr({literal},{63 if "64" in ty else 7}u32)\n  if v == {expected} {{ return 42u32 }}\n  return 1u32\n',f'sign-{ty}.omni')
                self.assertEqual(self.run_both(path),(42,42))

    def test_bit_programs_round_trip_through_every_representation(self)->None:
        text='  let a u64 = bit.shl(1u64,40u32)\n  let b u64 = bit.or(a,255u64)\n  let c u64 = bit.shr(b,40u32)\n  if c == 1u64 { return 42u32 }\n  return 1u32\n'
        path=self.source(text); wave=proc(OMNI,'wave',path); self.assertEqual(wave.returncode,0)
        owave=self.dir/'rt.owave'; owave.write_bytes(wave.stdout)
        self.assertEqual(proc(OMNI,'wave',owave).stdout,wave.stdout)                    # wave -> wave is idempotent
        wire=self.dir/'rt.owire'; self.assertEqual(proc(OMNI,'pack',path,'-o',wire).returncode,0)
        self.assertEqual(proc(OMNI,'wave',wire).stdout,wave.stdout)                     # wire -> wave equals source -> wave
        rewire=self.dir/'rt2.owire'; self.assertEqual(proc(OMNI,'pack',owave,'-o',rewire).returncode,0)
        self.assertEqual(rewire.read_bytes(),wire.read_bytes())                         # wave -> wire equals source -> wire
        onme=self.dir/'rt.onme'; self.assertEqual(proc(OMNI,'onme',path,'-o',onme).returncode,0)
        self.assertEqual(proc(OMNI,'wave',onme).stdout,wave.stdout)                     # ONME carries the same executable semantics
        for artifact in (path,owave,wire,onme): self.assertEqual(proc(OMNI,'eval',artifact).returncode,42,artifact.name)
        raw=bytearray(wire.read_bytes()); raw[4]=23; future=self.dir/'future.owire'; future.write_bytes(bytes(raw))
        result=proc(OMNI,'check',future); self.assertEqual(result.returncode,2); self.assertIn(b'E_VERSION',result.stderr)

    def test_returned_borrow_programs_round_trip_through_every_representation(self)->None:
        text=('module t\nfunc lend(b Borrow<Buffer>) Borrow<Buffer> !{memory.read} { return b }\n'
              'func main() u32 !{memory.read,memory.write} {\n  let first Result<Resource<Buffer>,u32> = buffer.alloc(3u32)\n  match first {\n'
              '    Ok(buf) {\n      let v = lend(borrow(buf))\n      let n = buffer.len(v)\n      let r = buffer.release(move(buf))\n      return n + r + 40u32\n    }\n'
              '    Err(code) { return code }\n  }\n}\n')
        path=self.dir/'rb.omni'; path.write_text(text,encoding='utf-8')
        wave=proc(OMNI,'wave',path); owave=self.dir/'rb.owave'; owave.write_bytes(wave.stdout)
        self.assertEqual(proc(OMNI,'wave',owave).stdout,wave.stdout)
        wire=self.dir/'rb.owire'; self.assertEqual(proc(OMNI,'pack',path,'-o',wire).returncode,0)
        self.assertEqual(proc(OMNI,'wave',wire).stdout,wave.stdout)
        rewire=self.dir/'rb2.owire'; self.assertEqual(proc(OMNI,'pack',owave,'-o',rewire).returncode,0)
        self.assertEqual(rewire.read_bytes(),wire.read_bytes())
        onme=self.dir/'rb.onme'; self.assertEqual(proc(OMNI,'onme',path,'-o',onme).returncode,0)
        self.assertEqual(proc(OMNI,'wave',onme).stdout,wave.stdout)
        for artifact in (path,owave,wire,onme): self.assertEqual(proc(OMNI,'eval',artifact).returncode,43,artifact.name)

    def test_type_and_arity_errors_produce_no_artifact(self)->None:
        cases=(('mismatched widths','  let v u16 = bit.and(1u8,1u16)\n  return 0u32\n',b'E_TYPE'),
               ('bool operand','  let v bool = bit.and(true,false)\n  return 0u32\n',b'E_TYPE'),
               ('float operand','  let v f32 = bit.not(1.0f32)\n  return 0u32\n',b'E_TYPE'),
               ('shift count not u32','  let v u8 = bit.shl(1u8,1u8)\n  return 0u32\n',b'E_TYPE'),
               ('arity','  let v u8 = bit.not(1u8,2u8)\n  return 0u32\n',b'E_ARITY'))
        for label,body,code in cases:
            with self.subTest(label):
                path=self.source(body); result=proc(OMNI,'check',path)
                self.assertEqual(result.returncode,2,result.stderr); self.assertIn(code,result.stderr)
                output=self.dir/'never'
                self.assertEqual(proc(OMNI,'build',path,'-o',output,'--cache-dir',self.dir/'cache').returncode,2)
                self.assertFalse(output.exists())


class A83OptionResourceTests(unittest.TestCase):
    """CP-01a (spec/OPTION_RESOURCE_CANDIDATE.md): Option<Resource<Buffer>> is a linear, match-consumed value."""

    SLOT=('func slot(make bool) Option<Resource<Buffer>> !{memory.write} {\n'
          '  if make {\n    let first Result<Resource<Buffer>,u32> = buffer.alloc(3u32)\n    match first {\n'
          '      Ok(buf) { return Some<Resource<Buffer>>(move(buf)) }\n      Err(code) { return None<Resource<Buffer>>() }\n    }\n  }\n'
          '  return None<Resource<Buffer>>()\n}\n')

    def setUp(self)->None:
        self.tmp=tempfile.TemporaryDirectory(prefix='omni-a83-optres-')
        self.dir=pathlib.Path(self.tmp.name)

    def tearDown(self)->None:
        self.tmp.cleanup()

    def source(self,text:str,name:str='program.omni')->pathlib.Path:
        path=self.dir/name
        path.write_text('module t\n'+text,encoding='utf-8')
        return path

    def both(self,path:pathlib.Path)->tuple[int,int]:
        evaluated=proc(OMNI,'eval',path)
        native=self.dir/(path.stem+'-native')
        built=proc(OMNI,'build',path,'-o',native,'--cache-dir',self.dir/'cache')
        self.assertEqual(built.returncode,0,built.stderr)
        return evaluated.returncode,proc(native).returncode

    def rejected(self,text:str,code:bytes)->None:
        path=self.source(text,'bad.omni'); result=proc(OMNI,'check',path)
        self.assertEqual(result.returncode,2,result.stderr); self.assertIn(code,result.stderr,result.stderr)
        output=self.dir/'never'
        self.assertEqual(proc(OMNI,'build',path,'-o',output,'--cache-dir',self.dir/'cache').returncode,2)
        self.assertFalse(output.exists())

    def test_some_and_none_paths_match_with_evaluator_native_parity(self)->None:
        text=self.SLOT+('func main() u32 !{memory.read,memory.write} {\n'
                        '  let a = slot(true)\n  var total u32 = 0u32\n'
                        '  match a {\n    Some(r) { total = total + buffer.len(borrow(r)) }\n    None { total = total + 100u32 }\n  }\n'
                        '  let b = slot(false)\n'
                        '  match b {\n    Some(r) { total = total + 100u32 }\n    None { total = total + 20u32 }\n  }\n'
                        '  return total + 19u32\n}\n')
        self.assertEqual(self.both(self.source(text)),(42,42))

    def test_option_resource_is_accepted_as_parameter_and_direct_construction(self)->None:
        text=('func finish(o Option<Resource<Buffer>>) u32 !{memory.read,memory.write} {\n'
              '  match o {\n    Some(r) { return buffer.release(move(r)) + 40u32 }\n    None { return 1u32 }\n  }\n}\n'
              'func main() u32 !{memory.read,memory.write} {\n'
              '  let first Result<Resource<Buffer>,u32> = buffer.alloc(2u32)\n  match first {\n'
              '    Ok(buf) { return finish(Some<Resource<Buffer>>(move(buf))) + 2u32 }\n    Err(code) { return code }\n  }\n}\n')
        self.assertEqual(self.both(self.source(text)),(42,42))

    def test_no_resource_is_leaked_on_any_path_over_3000_cycles(self)->None:
        # The runtime owns 1024 buffer slots: one leaked Resource per cycle would exhaust them and change the result.
        text=self.SLOT+('func main() u32 !{memory.read,memory.write} {\n'
                        '  var i u32 = 0u32\n  var live u32 = 0u32\n'
                        '  for i < 3000u32 {\n    let s = slot(true)\n'
                        '    match s {\n      Some(r) { live = live + 1u32 }\n      None { live = live }\n    }\n'
                        '    let t = slot(false)\n    match t {\n      Some(r) { live = live + 1000u32 }\n      None { live = live }\n    }\n'
                        '    i = i + 1u32\n  }\n  if live == 3000u32 { return 42u32 }\n  return 1u32\n}\n')
        self.assertEqual(self.both(self.source(text)),(42,42))

    def test_linear_rules_are_rejected_without_artifact(self)->None:
        some='Some<Resource<Buffer>>(move(buf))'
        wrap=lambda body:('func main() u32 !{memory.read,memory.write} {\n  let first Result<Resource<Buffer>,u32> = buffer.alloc(1u32)\n'
                          '  match first {\n    Ok(buf) {\n'+body+'    }\n    Err(code) { return code }\n  }\n}\n')
        cases=(
            ('unmatched at scope exit',wrap(f'      let s Option<Resource<Buffer>> = {some}\n      return 0u32\n'),b'E_RESULT_UNHANDLED'),
            ('used twice',wrap(f'      let s Option<Resource<Buffer>> = {some}\n      let a = s\n      let b = s\n      return 0u32\n'),b'E_RESULT_MOVED'),
            ('source moved into Some',wrap(f'      let s Option<Resource<Buffer>> = {some}\n      let r = buffer.release(move(buf))\n      return r\n'),b'E_RESOURCE_MOVED'),
            ('abandoned struct field','struct Holder { slot Option<Resource<Buffer>> }\nfunc bad(h Holder) u32 { return 0u32 }\nfunc main() u32 { return 0u32 }\n',b'E_RESULT_UNHANDLED'),
            ('nested option must be consumed','func f(o Option<Option<Resource<Buffer>>>) u32 { return 0u32 }\nfunc main() u32 { return 0u32 }\n',b'E_RESULT_UNHANDLED'),
            ('tuple element','func f(o Tuple<u32,Option<Resource<Buffer>>>) u32 { return 0u32 }\nfunc main() u32 { return 0u32 }\n',b'E_RESULT_UNHANDLED'),
            ('array element','func f(o Array<Option<Resource<Buffer>>,2>) u32 { return 0u32 }\nfunc main() u32 { return 0u32 }\n',b'E_RESULT_UNHANDLED'),
            ('option of borrow','func f(o Option<Borrow<Buffer>>) u32 { return 0u32 }\nfunc main() u32 { return 0u32 }\n',b'E_TYPE'),
        )
        for label,text,code in cases:
            with self.subTest(label):
                self.rejected(text,code)

    def test_option_resource_cannot_be_captured_by_a_closure(self)->None:
        captured=self.SLOT+('func main() u32 !{memory.write} {\n  let s = slot(true)\n'
                            '  return closure(y u32) u32 { match s { Some(r) { return y } None { return y } } }(1u32)\n}\n')
        result=proc(OMNI,'check',self.source(captured,'cap.omni'))
        self.assertEqual(result.returncode,2,result.stderr); self.assertIn(b'E_CLOSURE_CAPTURE',result.stderr)

    def test_signature_only_use_is_also_wave21_fenced(self)->None:
        # No Some/None annotation anywhere: only the parameter type mentions Option<Resource>.
        text=('func finish(o Option<Resource<Buffer>>) u32 !{memory.write} {\n'
              '  match o {\n    Some(r) { return buffer.release(move(r)) }\n    None { return 0u32 }\n  }\n}\nfunc main() u32 { return 0u32 }\n')
        path=self.source(text); wave=proc(OMNI,'wave',path); self.assertEqual(wave.returncode,0,wave.stderr)
        self.assertTrue(wave.stdout.startswith(b'(omni-wave 21'))
        old=self.dir/'sig.owave'; old.write_bytes(wave.stdout.replace(b'(omni-wave 21',b'(omni-wave 20',1))
        result=proc(OMNI,'check',old); self.assertEqual(result.returncode,2); self.assertIn(b'E_VERSION',result.stderr)

    def test_representation_is_wave21_fenced_and_round_trips(self)->None:
        text=self.SLOT+('func main() u32 !{memory.read,memory.write} {\n  let a = slot(true)\n'
                        '  match a {\n    Some(r) { return buffer.len(borrow(r)) + 39u32 }\n    None { return 1u32 }\n  }\n}\n')
        path=self.source(text); wave=proc(OMNI,'wave',path); self.assertTrue(wave.stdout.startswith(b'(omni-wave 21'))
        owave=self.dir/'o.owave'; owave.write_bytes(wave.stdout); self.assertEqual(proc(OMNI,'wave',owave).stdout,wave.stdout)
        wire=self.dir/'o.owire'; self.assertEqual(proc(OMNI,'pack',path,'-o',wire).returncode,0)
        self.assertEqual(wire.read_bytes()[:8],b'OMCX\x15\x00\x00\x00'); self.assertEqual(proc(OMNI,'wave',wire).stdout,wave.stdout)
        rewire=self.dir/'o2.owire'; self.assertEqual(proc(OMNI,'pack',owave,'-o',rewire).returncode,0); self.assertEqual(rewire.read_bytes(),wire.read_bytes())
        onme=self.dir/'o.onme'; self.assertEqual(proc(OMNI,'onme',path,'-o',onme).returncode,0); self.assertEqual(proc(OMNI,'wave',onme).stdout,wave.stdout)
        for artifact in (path,owave,wire,onme): self.assertEqual(proc(OMNI,'eval',artifact).returncode,42,artifact.name)
        old=self.dir/'old.owave'; old.write_bytes(wave.stdout.replace(b'(omni-wave 21',b'(omni-wave 20',1))
        result=proc(OMNI,'check',old); self.assertEqual(result.returncode,2); self.assertIn(b'E_VERSION',result.stderr)
        raw=bytearray(wire.read_bytes()); raw[4]=20; oldwire=self.dir/'old.owire'; oldwire.write_bytes(bytes(raw))
        result=proc(OMNI,'check',oldwire); self.assertEqual(result.returncode,2); self.assertIn(b'E_VERSION',result.stderr)


class A83AllocatorAndCleanupContractTests(unittest.TestCase):
    """CP-03/CP-04: typed allocation outcomes and cleanup on every structured exit, with an external oracle.

    The runtime owns 1024 buffer slots and 16 MiB. Anything that leaked a Resource would change the outcome of a
    later allocation, so these programs measure leaks without trusting the checker's own bookkeeping.
    """

    def setUp(self)->None:
        self.tmp=tempfile.TemporaryDirectory(prefix='omni-a83-alloc-')
        self.dir=pathlib.Path(self.tmp.name)

    def tearDown(self)->None:
        self.tmp.cleanup()

    def source(self,text:str,name:str='program.omni')->pathlib.Path:
        path=self.dir/name
        path.write_text('module t\n'+text,encoding='utf-8')
        return path

    def both(self,path:pathlib.Path)->tuple[int,int]:
        evaluated=proc(OMNI,'eval',path)
        native=self.dir/(path.stem+'-native')
        built=proc(OMNI,'build',path,'-o',native,'--cache-dir',self.dir/'cache')
        self.assertEqual(built.returncode,0,built.stderr)
        return evaluated.returncode,proc(native).returncode

    PROBE=('func probe(n u32) u32 !{memory.read,memory.write} {\n'
           '  let r Result<Resource<Buffer>,u32> = buffer.alloc(n)\n  match r {\n'
           '    Ok(buf) { let x = buffer.release(move(buf))\n              return 42u32 }\n    Err(code) { return 100u32 + code }\n  }\n}\n')

    def test_allocation_outcome_codes_at_every_boundary(self)->None:
        text=self.PROBE+('func main() u32 !{memory.read,memory.write} {\n'
                         '  if probe(0u32) != 42u32 { return 1u32 }\n'
                         '  if probe(1048576u32) != 42u32 { return 2u32 }\n'
                         '  if probe(1048577u32) != 101u32 { return 3u32 }\n'
                         '  if probe(4294967295u32) != 101u32 { return 4u32 }\n'
                         '  return 42u32\n}\n')
        self.assertEqual(self.both(self.source(text)),(42,42))

    def test_total_bytes_exhaustion_is_typed_recoverable_and_restores_the_baseline(self)->None:
        text=('func hold(n u32) u32 !{memory.read,memory.write} {\n'
              '  let r Result<Resource<Buffer>,u32> = buffer.alloc(1048576u32)\n  match r {\n'
              '    Ok(buf) {\n      var out u32 = 42u32\n      if n > 0u32 { out = hold(n - 1u32) }\n'
              '      let x = buffer.release(move(buf))\n      return out\n    }\n    Err(code) { return 100u32 + code }\n  }\n}\n'
              'func main() u32 !{memory.read,memory.write} {\n'
              '  if hold(15u32) != 42u32 { return 1u32 }\n'      # 16 MiB held at once: still fits
              '  if hold(16u32) != 102u32 { return 2u32 }\n'     # the 17th MiB is a typed Err(2), no abort
              '  if hold(15u32) != 42u32 { return 3u32 }\n'      # everything came back after unwinding
              '  return 42u32\n}\n')
        self.assertEqual(self.both(self.source(text)),(42,42))

    def test_partial_construction_failure_releases_what_was_built_and_leaks_nothing(self)->None:
        # 15 MiB are held; make() then gets its first 1 MiB (16 MiB total) and fails on the second: Err(2)+10.
        # If the first buffer leaked, the repetition would fail already on the first allocation (plain Err(2)).
        text=('struct Pair { left Resource<Buffer>, right Resource<Buffer> }\n'
              'func make() Result<Pair,u32> !{memory.write} {\n'
              '  let first Result<Resource<Buffer>,u32> = buffer.alloc(1048576u32)\n  match first {\n'
              '    Ok(left) {\n      let second Result<Resource<Buffer>,u32> = buffer.alloc(1048576u32)\n      match second {\n'
              '        Ok(right) { return Ok<Pair,u32>(Pair { left: move(left), right: move(right) }) }\n'
              '        Err(code) { let r = buffer.release(move(left))\n                    return Err<Pair,u32>(code + r + 10u32) }\n      }\n    }\n'
              '    Err(code) { return Err<Pair,u32>(code) }\n  }\n}\n'
              'func fill(n u32) u32 !{memory.read,memory.write} {\n'
              '  let r Result<Resource<Buffer>,u32> = buffer.alloc(1048576u32)\n  match r {\n'
              '    Ok(buf) {\n      var out u32 = 0u32\n'
              '      if n == 1u32 {\n        let made Result<Pair,u32> = make()\n        match made {\n'
              '          Ok(pair) { let a = buffer.release(move(pair.left))\n                     let b = buffer.release(move(pair.right))\n                     out = 7u32 }\n'
              '          Err(code) { out = 100u32 + code }\n        }\n      }\n'
              '      if n > 1u32 { out = fill(n - 1u32) }\n'
              '      let x = buffer.release(move(buf))\n      return out\n    }\n    Err(code) { return 200u32 + code }\n  }\n}\n'
              'func main() u32 !{memory.read,memory.write} {\n'
              '  if fill(15u32) != 112u32 { return 1u32 }\n'
              '  if fill(15u32) != 112u32 { return 2u32 }\n'
              '  if fill(10u32) != 7u32 { return 3u32 }\n'
              '  return 42u32\n}\n')
        self.assertEqual(self.both(self.source(text)),(42,42))

    def test_cleanup_runs_on_every_structured_exit_over_3000_cycles(self)->None:
        text=('func exits(kind u32) u32 !{memory.read,memory.write} {\n'
              '  let r Result<Resource<Buffer>,u32> = buffer.alloc(4u32)\n  match r {\n'
              '    Ok(buf) {\n'
              '      if kind == 1u32 { return 1u32 }\n'                                       # early return, resource live
              '      var i u32 = 0u32\n'
              '      for i < 3u32 {\n'
              '        let inner Result<Resource<Buffer>,u32> = buffer.alloc(4u32)\n        match inner {\n'
              '          Ok(held) {\n            i = i + 1u32\n            if kind == 2u32 { continue }\n            if kind == 3u32 { break }\n          }\n'
              '          Err(code) { return 900u32 + code }\n        }\n      }\n'
              '      return 2u32\n    }\n    Err(code) { return 800u32 + code }\n  }\n}\n'
              'func main() u32 !{memory.read,memory.write} {\n'
              '  var n u32 = 0u32\n  var sum u32 = 0u32\n'
              '  for n < 3000u32 {\n'
              '    sum = sum + exits(0u32) + exits(1u32) + exits(2u32) + exits(3u32)\n'
              '    n = n + 1u32\n  }\n'
              '  if sum == 3000u32 * 7u32 { return 42u32 }\n  return 1u32\n}\n')    # per cycle: 2 + 1 + 2 + 2
        self.assertEqual(self.both(self.source(text)),(42,42))


class A83GenericStructTests(unittest.TestCase):
    """CP-05 (spec/GENERIC_STRUCT_CANDIDATE.md): generic structs monomorphize into ordinary records."""

    def setUp(self)->None:
        self.tmp=tempfile.TemporaryDirectory(prefix='omni-a83-gstruct-')
        self.dir=pathlib.Path(self.tmp.name)

    def tearDown(self)->None:
        self.tmp.cleanup()

    def source(self,text:str,name:str='program.omni')->pathlib.Path:
        path=self.dir/name
        path.write_text('module t\n'+text,encoding='utf-8')
        return path

    def both(self,path:pathlib.Path)->tuple[int,int]:
        evaluated=proc(OMNI,'eval',path)
        native=self.dir/(path.stem+'-native')
        built=proc(OMNI,'build',path,'-o',native,'--cache-dir',self.dir/'cache')
        self.assertEqual(built.returncode,0,built.stderr)
        return evaluated.returncode,proc(native).returncode

    def rejected(self,text:str,code:bytes)->None:
        path=self.source(text,'bad.omni'); result=proc(OMNI,'check',path)
        self.assertEqual(result.returncode,2,result.stderr); self.assertIn(code,result.stderr,result.stderr)
        output=self.dir/'never'
        self.assertEqual(proc(OMNI,'build',path,'-o',output,'--cache-dir',self.dir/'cache').returncode,2)
        self.assertFalse(output.exists())

    PAIR=('struct Pair<A, B> { first A, second B }\n'
          'func total(p Pair<u32,u8>) u32 { return p.first + u32(p.second) }\n')

    def test_generic_struct_runs_identically_in_evaluator_and_native(self)->None:
        text=self.PAIR+('func main() u32 {\n  let p Pair<u32,u8> = Pair<u32,u8> { first: 40u32, second: 2u8 }\n  return total(p)\n}\n')
        self.assertEqual(self.both(self.source(text)),(42,42))

    def test_one_record_per_distinct_argument_list_and_no_template_in_the_representation(self)->None:
        text=self.PAIR+('func main() u32 {\n  let a Pair<u32,u8> = Pair<u32,u8> { first: 1u32, second: 2u8 }\n'
                        '  let b Pair<u32,u8> = Pair<u32,u8> { first: 3u32, second: 4u8 }\n'
                        '  let c Pair<u8,u8> = Pair<u8,u8> { first: 5u8, second: 6u8 }\n  return total(a) + total(b) + u32(c.first)\n}\n')
        path=self.source(text); wave=proc(OMNI,'wave',path); self.assertEqual(wave.returncode,0,wave.stderr)
        self.assertTrue(wave.stdout.startswith(b'(omni-wave 22'))                         # rechecked authoring capsule
        self.assertIn(b'authoring-source',wave.stdout)
        self.assertIn(b'Pair<A,B>',wave.stdout); self.assertNotIn(b'Pair__g_',wave.stdout)
        self.assertEqual(self.both(path),(15,15))                                          # (1+2) + (3+4) + 5
        owave=self.dir/'g.owave'; owave.write_bytes(wave.stdout); self.assertEqual(proc(OMNI,'wave',owave).stdout,wave.stdout)
        wire=self.dir/'g.owire'; self.assertEqual(proc(OMNI,'pack',path,'-o',wire).returncode,0)
        self.assertEqual(wire.read_bytes()[:8],b'OMCX\x16\x00\x00\x00'); self.assertEqual(proc(OMNI,'wave',wire).stdout,wave.stdout)
        onme=self.dir/'g.onme'; self.assertEqual(proc(OMNI,'onme',path,'-o',onme).returncode,0); self.assertEqual(proc(OMNI,'wave',onme).stdout,wave.stdout)
        for artifact in (owave,wire,onme): self.assertEqual(proc(OMNI,"eval",artifact).returncode,15,artifact.name)

    def test_nested_generic_structs_and_generic_functions_over_them(self)->None:
        text=('struct Box<T> { item T }\n'
              'func unbox<T>(b Box<T>) T { return b.item }\n'
              'func main() u32 {\n  let inner Box<u32> = Box<u32> { item: 40u32 }\n'
              '  let outer Box<Box<u32>> = Box<Box<u32>> { item: inner }\n'
              '  let x Box<u32> = unbox<Box<u32>>(outer)\n  return unbox<u32>(x) + 2u32\n}\n')
        self.assertEqual(self.both(self.source(text)),(42,42))

    def test_generic_container_of_a_resource_keeps_every_ownership_rule(self)->None:
        base=('struct Box<T> { item T }\n'
              'func main() u32 !{memory.read,memory.write} {\n'
              '  let first Result<Resource<Buffer>,u32> = buffer.alloc(2u32)\n  match first {\n    Ok(buf) {\n'
              '      let b Box<Resource<Buffer>> = Box<Resource<Buffer>> { item: move(buf) }\n')
        ok=base+'      let n = buffer.len(borrow(b.item))\n      let r = buffer.release(move(b.item))\n      return n + r + 40u32\n    }\n    Err(code) { return code }\n  }\n}\n'
        self.assertEqual(self.both(self.source(ok)),(42,42))
        self.rejected(base+'      let copy = b\n      let r = buffer.release(move(b.item))\n      return r\n    }\n    Err(code) { return code }\n  }\n}\n',b'E_RESOURCE_ACCESS')
        self.rejected(base+'      let r = buffer.release(move(b.item))\n      let s = buffer.release(move(b.item))\n      return r + s\n    }\n    Err(code) { return code }\n  }\n}\n',b'E_RESOURCE_MOVED')

    def test_constraints_are_enforced_per_argument(self)->None:
        decl='struct Num<T: Integer> { v T }\n'
        self.assertEqual(self.both(self.source(decl+'func main() u32 {\n  let n Num<u32> = Num<u32> { v: 42u32 }\n  return n.v\n}\n')),(42,42))
        self.rejected(decl+'func main() u32 {\n  let n Num<bool> = Num<bool> { v: true }\n  return 0u32\n}\n',b'E_GENERIC_CONSTRAINT')
        self.rejected(decl+'func main() u32 {\n  let n Num<f32> = Num<f32> { v: 1.0f32 }\n  return 0u32\n}\n',b'E_GENERIC_CONSTRAINT')

    def test_arity_target_and_declaration_errors_produce_no_artifact(self)->None:
        cases=(
            ('arity mismatch','struct Pair<A, B> { a A, b B }\nfunc f(p Pair<u32>) u32 { return 0u32 }\nfunc main() u32 { return 0u32 }\n',b'E_GENERIC_ARGS'),
            ('initializer without arguments','struct Box<T> { item T }\nfunc main() u32 {\n  let b = Box { item: 1u32 }\n  return 0u32\n}\n',b'E_GENERIC_ARGS'),
            ('arguments on a non-generic type','struct Plain { a u32 }\nfunc f(p Plain<u32>) u32 { return 0u32 }\nfunc main() u32 { return 0u32 }\n',b'E_GENERIC_TARGET'),
            ('duplicate parameter','struct Bad<T, T> { a T }\nfunc main() u32 { return 0u32 }\n',b'E_GENERIC_DECL'),
            ('unknown constraint','struct Bad<T: Nope> { a T }\nfunc main() u32 { return 0u32 }\n',b'E_GENERIC_CONSTRAINT'),
            ('name collision with a plain struct','struct Same<T> { a T }\nstruct Same { b u32 }\nfunc main() u32 { return 0u32 }\n',b'E_DUPLICATE'),
            ('empty parameter list','struct Bad<> { a u32 }\nfunc main() u32 { return 0u32 }\n',b'E_'),
        )
        for label,text,code in cases:
            with self.subTest(label):
                self.rejected(text,code)

    def test_generic_struct_declared_in_another_module(self)->None:
        (self.dir/'lib.omni').write_text('module lib\npub struct Box<T> { item T }\nstruct Hidden<T> { item T }\n',encoding='utf-8')
        app=self.dir/'app.omni'
        app.write_text('module app\nimport l "lib.omni"\nfunc main() u32 {\n  let b l.Box<u32> = l.Box<u32> { item: 42u32 }\n  return b.item\n}\n',encoding='utf-8')
        self.assertEqual(proc(OMNI,'check',app).returncode,0,proc(OMNI,'check',app).stderr)
        self.assertEqual(self.both(app),(42,42))
        private=self.dir/'private.omni'
        private.write_text('module priv\nimport l "lib.omni"\nfunc main() u32 {\n  let b l.Hidden<u32> = l.Hidden<u32> { item: 1u32 }\n  return 0u32\n}\n',encoding='utf-8')
        result=proc(OMNI,'check',private); self.assertEqual(result.returncode,2); self.assertIn(b'E_VISIBILITY',result.stderr)

    def test_formatter_output_is_stable_and_equivalent(self)->None:
        text=self.PAIR+('func main() u32 {\n  let p Pair<u32,u8> = Pair<u32,u8> { first: 40u32, second: 2u8 }\n  return total(p)\n}\n')
        path=self.source(text); once=proc(OMNI,'fmt',path); self.assertEqual(once.returncode,0,once.stderr)
        formatted=self.dir/'formatted.omni'; formatted.write_bytes(once.stdout)
        twice=proc(OMNI,'fmt',formatted); self.assertEqual(twice.returncode,0,twice.stderr); self.assertEqual(twice.stdout,once.stdout)
        self.assertEqual(proc(OMNI,'eval',formatted).returncode,42)


class A83GenericEnumTests(unittest.TestCase):
    """CP-05 (spec/GENERIC_STRUCT_CANDIDATE.md §1b): generic enums monomorphize into ordinary enums."""

    def setUp(self)->None:
        self.tmp=tempfile.TemporaryDirectory(prefix='omni-a83-genum-')
        self.dir=pathlib.Path(self.tmp.name)

    def tearDown(self)->None:
        self.tmp.cleanup()

    def source(self,text:str,name:str='program.omni')->pathlib.Path:
        path=self.dir/name
        path.write_text('module t\n'+text,encoding='utf-8')
        return path

    def both(self,path:pathlib.Path)->tuple[int,int]:
        evaluated=proc(OMNI,'eval',path)
        native=self.dir/(path.stem+'-native')
        built=proc(OMNI,'build',path,'-o',native,'--cache-dir',self.dir/'cache')
        self.assertEqual(built.returncode,0,built.stderr)
        return evaluated.returncode,proc(native).returncode

    def rejected(self,text:str,code:bytes)->None:
        path=self.source(text,'bad.omni'); result=proc(OMNI,'check',path)
        self.assertEqual(result.returncode,2,result.stderr); self.assertIn(code,result.stderr,result.stderr)
        output=self.dir/'never'
        self.assertEqual(proc(OMNI,'build',path,'-o',output,'--cache-dir',self.dir/'cache').returncode,2)
        self.assertFalse(output.exists())

    EITHER=('enum Either<A, B> { Left(A), Right(B), Neither }\n'
            'func weight(e Either<u32,u8>) u32 {\n  match e {\n    Left(v) { return v }\n    Right(w) { return u32(w) + 100u32 }\n    Neither { return 7u32 }\n  }\n}\n')

    def test_every_variant_runs_identically_in_evaluator_and_native(self)->None:
        text=self.EITHER+('func main() u32 {\n  let a Either<u32,u8> = Either.Left<u32,u8>(20u32)\n'
                          '  let b Either<u32,u8> = Either.Right<u32,u8>(3u8)\n  let c Either<u32,u8> = Either.Neither<u32,u8>()\n'
                          '  return weight(a) + weight(b) + weight(c) - 100u32 - 20u32 + 12u32 + 19u32\n}\n')
        # 20 + 103 + 7 = 130 ; 130 - 120 + 31 = 41 ; +1 below keeps the oracle explicit
        text=text.replace('- 100u32 - 20u32 + 12u32 + 19u32','- 100u32 - 20u32 + 12u32 + 20u32')
        self.assertEqual(self.both(self.source(text)),(42,42))

    def test_one_enum_per_distinct_argument_list_and_wave18_is_unchanged(self)->None:
        text=self.EITHER+('func main() u32 {\n  let a Either<u32,u8> = Either.Left<u32,u8>(1u32)\n  let b Either<u32,u8> = Either.Left<u32,u8>(2u32)\n'
                          '  return weight(a) + weight(b)\n}\n')
        path=self.source(text); wave=proc(OMNI,'wave',path); self.assertEqual(wave.returncode,0,wave.stderr)
        self.assertTrue(wave.stdout.startswith(b'(omni-wave 22')); self.assertIn(b'authoring-source',wave.stdout)
        self.assertIn(b'Either<A,B>',wave.stdout); self.assertNotIn(b'Either__g_',wave.stdout)
        owave=self.dir/'e.owave'; owave.write_bytes(wave.stdout); self.assertEqual(proc(OMNI,'wave',owave).stdout,wave.stdout)
        wire=self.dir/'e.owire'; self.assertEqual(proc(OMNI,'pack',path,'-o',wire).returncode,0); self.assertEqual(proc(OMNI,'wave',wire).stdout,wave.stdout)
        onme=self.dir/'e.onme'; self.assertEqual(proc(OMNI,'onme',path,'-o',onme).returncode,0); self.assertEqual(proc(OMNI,'wave',onme).stdout,wave.stdout)
        for artifact in (path,owave,wire,onme): self.assertEqual(proc(OMNI,'eval',artifact).returncode,3,artifact.name)

    def test_generic_enum_carrying_a_generic_struct_and_a_resource(self)->None:
        text=('struct Box<T> { item T }\nenum Slot<T> { Full(Box<T>), Empty }\n'
              'func main() u32 !{memory.read,memory.write} {\n'
              '  let first Result<Resource<Buffer>,u32> = buffer.alloc(2u32)\n  match first {\n    Ok(buf) {\n'
              '      let s Slot<Resource<Buffer>> = Slot.Full<Resource<Buffer>>(Box<Resource<Buffer>> { item: move(buf) })\n'
              '      match s {\n        Full(b) { return buffer.release(move(b.item)) + 42u32 }\n        Empty { return 1u32 }\n      }\n    }\n'
              '    Err(code) { return code }\n  }\n}\n')
        self.assertEqual(self.both(self.source(text)),(42,42))

    def test_generic_enum_first_used_inside_a_generic_function_specialization(self)->None:
        # Slot<u32> only exists after mk<u32> is specialized, so its Box<u32> payload must be specialized in the same drain.
        text=('struct Box<T> { item T }\nenum Slot<T> { Full(Box<T>), Empty }\n'
              'func mk<T>(x T) Slot<T> { return Slot.Full<T>(Box<T> { item: x }) }\n'
              'func main() u32 {\n  let s = mk<u32>(42u32)\n  match s {\n    Full(b) { return b.item }\n    Empty { return 1u32 }\n  }\n}\n')
        self.assertEqual(self.both(self.source(text)),(42,42))

    def test_non_exhaustive_match_and_errors_produce_no_artifact(self)->None:
        cases=(
            ('non exhaustive','enum Either<A, B> { Left(A), Right(B) }\nfunc f(e Either<u32,u8>) u32 {\n  match e {\n    Left(v) { return v }\n  }\n}\nfunc main() u32 { return 0u32 }\n',b'E_MATCH_NON_EXHAUSTIVE'),
            ('arity mismatch','enum Either<A, B> { Left(A), Right(B) }\nfunc f(e Either<u32>) u32 { return 0u32 }\nfunc main() u32 { return 0u32 }\n',b'E_GENERIC_ARGS'),
            ('wrong payload type','enum Either<A, B> { Left(A), Right(B) }\nfunc main() u32 {\n  let e Either<u32,u8> = Either.Left<u32,u8>(true)\n  return 0u32\n}\n',b'E_TYPE'),
            ('constraint','enum Num<T: Integer> { V(T) }\nfunc main() u32 {\n  let e Num<bool> = Num.V<bool>(true)\n  return 0u32\n}\n',b'E_GENERIC_CONSTRAINT'),
            ('unknown variant','enum Either<A, B> { Left(A), Right(B) }\nfunc main() u32 {\n  let e Either<u32,u8> = Either.Nope<u32,u8>(1u32)\n  return 0u32\n}\n',b'E_'),
            ('collision with struct template','struct Same<T> { a T }\nenum Same<T> { A(T) }\nfunc main() u32 { return 0u32 }\n',b'E_DUPLICATE'),
        )
        for label,text,code in cases:
            with self.subTest(label):
                self.rejected(text,code)

    def test_generic_enum_declared_in_another_module(self)->None:
        (self.dir/'lib.omni').write_text('module lib\npub enum Maybe<T> { Just(T), Nothing }\nenum Hidden<T> { H(T) }\n',encoding='utf-8')
        app=self.dir/'app.omni'
        app.write_text('module app\nimport l "lib.omni"\nfunc get(m l.Maybe<u32>) u32 {\n  match m {\n    Just(v) { return v }\n    Nothing { return 0u32 }\n  }\n}\n'
                       'func main() u32 {\n  let m l.Maybe<u32> = l.Maybe.Just<u32>(42u32)\n  return get(m)\n}\n',encoding='utf-8')
        self.assertEqual(proc(OMNI,'check',app).returncode,0,proc(OMNI,'check',app).stderr)
        self.assertEqual(self.both(app),(42,42))
        private=self.dir/'private.omni'
        private.write_text('module priv\nimport l "lib.omni"\nfunc f(h l.Hidden<u32>) u32 { return 0u32 }\nfunc main() u32 { return 0u32 }\n',encoding='utf-8')
        result=proc(OMNI,'check',private); self.assertEqual(result.returncode,2); self.assertIn(b'E_VISIBILITY',result.stderr)

    def test_formatter_output_is_stable_and_equivalent(self)->None:
        text=self.EITHER+'func main() u32 {\n  let a Either<u32,u8> = Either.Left<u32,u8>(42u32)\n  return weight(a)\n}\n'
        path=self.source(text); once=proc(OMNI,'fmt',path); self.assertEqual(once.returncode,0,once.stderr)
        formatted=self.dir/'formatted.omni'; formatted.write_bytes(once.stdout)
        twice=proc(OMNI,'fmt',formatted); self.assertEqual(twice.returncode,0,twice.stderr); self.assertEqual(twice.stdout,once.stdout)
        self.assertEqual(proc(OMNI,'eval',formatted).returncode,42)


class A83TraitMethodTests(unittest.TestCase):
    """CP-05b (spec/TRAIT_METHODS_CANDIDATE.md): trait methods with static dispatch and an effect-subset rule."""

    def setUp(self)->None:
        self.tmp=tempfile.TemporaryDirectory(prefix='omni-a83-trait-')
        self.dir=pathlib.Path(self.tmp.name)

    def tearDown(self)->None:
        self.tmp.cleanup()

    def source(self,text:str,name:str='program.omni')->pathlib.Path:
        path=self.dir/name
        path.write_text('module t\n'+text,encoding='utf-8')
        return path

    def both(self,path:pathlib.Path)->tuple[int,int]:
        evaluated=proc(OMNI,'eval',path)
        native=self.dir/(path.stem+'-native')
        built=proc(OMNI,'build',path,'-o',native,'--cache-dir',self.dir/'cache')
        self.assertEqual(built.returncode,0,built.stderr)
        return evaluated.returncode,proc(native).returncode

    def rejected(self,text:str,code:bytes)->None:
        path=self.source(text,'bad.omni'); result=proc(OMNI,'check',path)
        self.assertEqual(result.returncode,2,result.stderr); self.assertIn(code,result.stderr,result.stderr)
        output=self.dir/'never'
        self.assertEqual(proc(OMNI,'build',path,'-o',output,'--cache-dir',self.dir/'cache').returncode,2)
        self.assertFalse(output.exists())

    SHAPES=('struct Circle { r u32 }\nstruct Square { s u32 }\n'
            'trait Shape { func area(x Self) u32 }\n'
            'impl Shape for Circle { func area(x Circle) u32 { return x.r * x.r * 3u32 } }\n'
            'impl Shape for Square { func area(x Square) u32 { return x.s * x.s } }\n'
            'func total<T: Shape>(x T) u32 { return Shape.area<T>(x) }\n')

    def test_static_dispatch_through_a_bounded_generic_function(self)->None:
        text=self.SHAPES+('func main() u32 {\n  let c Circle = Circle { r: 2u32 }\n  let q Square = Square { s: 5u32 }\n'
                          '  return total<Circle>(c) + total<Square>(q) + Shape.area<Square>(q) - 20u32\n}\n')
        self.assertEqual(self.both(self.source(text)),(42,42))                       # 12 + 25 + 25 - 20

    def test_representation_has_no_trait_or_impl_and_stays_wave18(self)->None:
        text=self.SHAPES+('func main() u32 {\n  let c Circle = Circle { r: 2u32 }\n  return total<Circle>(c)\n}\n')
        path=self.source(text); wave=proc(OMNI,'wave',path); self.assertEqual(wave.returncode,0,wave.stderr)
        self.assertTrue(wave.stdout.startswith(b'(omni-wave 22')); self.assertIn(b'trait Shape',wave.stdout); self.assertNotIn(b'area__impl_',wave.stdout)
        owave=self.dir/'t.owave'; owave.write_bytes(wave.stdout); self.assertEqual(proc(OMNI,'wave',owave).stdout,wave.stdout)
        wire=self.dir/'t.owire'; self.assertEqual(proc(OMNI,'pack',path,'-o',wire).returncode,0); self.assertEqual(proc(OMNI,'wave',wire).stdout,wave.stdout)
        onme=self.dir/'t.onme'; self.assertEqual(proc(OMNI,'onme',path,'-o',onme).returncode,0); self.assertEqual(proc(OMNI,'wave',onme).stdout,wave.stdout)
        for artifact in (path,owave,wire,onme): self.assertEqual(proc(OMNI,'eval',artifact).returncode,12,artifact.name)

    def test_impl_may_use_fewer_capabilities_than_the_trait_but_never_more(self)->None:
        base='struct S { v u32 }\ntrait Log { func emit(x Self) u32 !{memory.write} }\n'
        ok=base+'impl Log for S { func emit(x S) u32 { return x.v } }\nfunc main() u32 {\n  let s S = S { v: 42u32 }\n  return Log.emit<S>(s)\n}\n'
        self.assertEqual(self.both(self.source(ok)),(42,42))
        self.rejected(base+'impl Log for S { func emit(x S) u32 !{memory.write,io.print} { return x.v } }\nfunc main() u32 { return 0u32 }\n',b'E_TRAIT_EFFECT')

    def test_conformance_and_resolution_errors_produce_no_artifact(self)->None:
        head='struct Circle { r u32 }\nstruct Square { s u32 }\ntrait Shape { func area(x Self) u32 }\n'
        tail='func main() u32 { return 0u32 }\n'
        cases=(
            ('missing method',head+'impl Shape for Circle { }\n'+tail,b'E_TRAIT_METHOD'),
            ('method not in trait',head+'impl Shape for Circle {\n  func area(x Circle) u32 { return 1u32 }\n  func extra(x Circle) u32 { return 2u32 }\n}\n'+tail,b'E_TRAIT_METHOD'),
            ('duplicate method',head+'impl Shape for Circle {\n  func area(x Circle) u32 { return 1u32 }\n  func area(x Circle) u32 { return 2u32 }\n}\n'+tail,b'E_TRAIT_METHOD'),
            ('wrong parameter type',head+'impl Shape for Circle { func area(x u32) u32 { return x } }\n'+tail,b'E_TRAIT_METHOD'),
            ('wrong result type',head+'impl Shape for Circle { func area(x Circle) u8 { return 1u8 } }\n'+tail,b'E_TRAIT_METHOD'),
            ('wrong arity',head+'impl Shape for Circle { func area(x Circle, y u32) u32 { return y } }\n'+tail,b'E_TRAIT_METHOD'),
            ('no impl for the type',head+'impl Shape for Circle { func area(x Circle) u32 { return 1u32 } }\nfunc main() u32 {\n  let q Square = Square { s: 1u32 }\n  return Shape.area<Square>(q)\n}\n',b'E_TRAIT'),
            ('bound not satisfied',head+'impl Shape for Circle { func area(x Circle) u32 { return 1u32 } }\nfunc total<T: Shape>(x T) u32 { return Shape.area<T>(x) }\n'
                                       'func main() u32 {\n  let q Square = Square { s: 1u32 }\n  return total<Square>(q)\n}\n',b'E_GENERIC_CONSTRAINT'),
            ('method not declared by the trait',head+'impl Shape for Circle { func area(x Circle) u32 { return 1u32 } }\nfunc main() u32 {\n  let c Circle = Circle { r: 1u32 }\n  return Shape.volume<Circle>(c)\n}\n',b'E_TRAIT_METHOD'),
        )
        for label,text,code in cases:
            with self.subTest(label):
                self.rejected(text,code)

    def test_trait_declared_in_another_module(self)->None:
        (self.dir/'lib.omni').write_text('module lib\npub struct Sq { s u32 }\npub trait Area { func area(x Self) u32 }\n'
                                         'impl Area for Sq { func area(x Sq) u32 { return x.s * x.s } }\ntrait Hidden { func h(x Self) u32 }\n',encoding='utf-8')
        app=self.dir/'app.omni'
        app.write_text('module app\nimport l "lib.omni"\nfunc main() u32 {\n  let s l.Sq = l.Sq { s: 6u32 }\n  return l.Area.area<l.Sq>(s) + 6u32\n}\n',encoding='utf-8')
        self.assertEqual(proc(OMNI,'check',app).returncode,0,proc(OMNI,'check',app).stderr)
        self.assertEqual(self.both(app),(42,42))
        private=self.dir/'private.omni'
        private.write_text('module priv\nimport l "lib.omni"\nfunc main() u32 {\n  let s l.Sq = l.Sq { s: 1u32 }\n  return l.Hidden.h<l.Sq>(s)\n}\n',encoding='utf-8')
        result=proc(OMNI,'check',private); self.assertEqual(result.returncode,2); self.assertIn(b'E_VISIBILITY',result.stderr)

    def test_formatter_output_is_stable_and_equivalent(self)->None:
        text=self.SHAPES+('func main() u32 {\n  let q Square = Square { s: 6u32 }\n  return total<Square>(q) + 6u32\n}\n')
        path=self.source(text); once=proc(OMNI,'fmt',path); self.assertEqual(once.returncode,0,once.stderr)
        formatted=self.dir/'formatted.omni'; formatted.write_bytes(once.stdout)
        twice=proc(OMNI,'fmt',formatted); self.assertEqual(twice.returncode,0,twice.stderr); self.assertEqual(twice.stdout,once.stdout)
        self.assertEqual(proc(OMNI,'eval',formatted).returncode,42)


class A83TryOperatorTests(unittest.TestCase):
    """CP-05c (spec/TRY_PROPAGATION_CANDIDATE.md): postfix `?`, lowered to match before checking."""

    def setUp(self)->None:
        self.tmp=tempfile.TemporaryDirectory(prefix='omni-a83-try-')
        self.dir=pathlib.Path(self.tmp.name)

    def tearDown(self)->None:
        self.tmp.cleanup()

    def source(self,text:str,name:str='program.omni')->pathlib.Path:
        path=self.dir/name
        path.write_text('module t\n'+text,encoding='utf-8')
        return path

    def both(self,path:pathlib.Path)->tuple[int,int]:
        evaluated=proc(OMNI,'eval',path)
        native=self.dir/(path.stem+'-native')
        built=proc(OMNI,'build',path,'-o',native,'--cache-dir',self.dir/'cache')
        self.assertEqual(built.returncode,0,built.stderr)
        return evaluated.returncode,proc(native).returncode

    def rejected(self,text:str,code:bytes)->None:
        path=self.source(text,'bad.omni'); result=proc(OMNI,'check',path)
        self.assertEqual(result.returncode,2,result.stderr); self.assertIn(code,result.stderr,result.stderr)
        output=self.dir/'never'
        self.assertEqual(proc(OMNI,'build',path,'-o',output,'--cache-dir',self.dir/'cache').returncode,2)
        self.assertFalse(output.exists())

    PARSE=('func parse(x u32) Result<u32,u32> {\n  if x > 100u32 { return Err<u32,u32>(x) }\n  return Ok<u32,u32>(x + 1u32)\n}\n')

    def test_result_propagation_succeeds_and_fails_identically_in_evaluator_and_native(self)->None:
        text=self.PARSE+('func sum(a u32, b u32) Result<u32,u32> {\n  let x = parse(a)?\n  let y = parse(b)?\n  return Ok<u32,u32>(x + y)\n}\n'
                         'func main() u32 {\n  var ok u32 = 0u32\n  var bad u32 = 0u32\n'
                         '  match sum(10u32,30u32) {\n    Ok(v) { ok = v }\n    Err(e) { ok = 1u32 }\n  }\n'
                         '  match sum(10u32,200u32) {\n    Ok(v) { bad = 1u32 }\n    Err(e) { bad = e }\n  }\n'
                         '  if ok == 42u32 { if bad == 200u32 { return 42u32 } }\n  return 1u32\n}\n')
        self.assertEqual(self.both(self.source(text)),(42,42))

    def test_option_propagation(self)->None:
        text=('func half(x u32) Option<u32> {\n  if x % 2u32 == 1u32 { return None<u32>() }\n  return Some<u32>(x / 2u32)\n}\n'
              'func quarter(x u32) Option<u32> {\n  let h = half(x)?\n  let q = half(h)?\n  return Some<u32>(q)\n}\n'
              'func main() u32 {\n  var a u32 = 0u32\n  var b u32 = 7u32\n'
              '  match quarter(168u32) {\n    Some(v) { a = v }\n    None { a = 1u32 }\n  }\n'
              '  match quarter(170u32) {\n    Some(v) { b = 1u32 }\n    None { b = 0u32 }\n  }\n'
              '  if a == 42u32 { if b == 0u32 { return 42u32 } }\n  return 1u32\n}\n')
        self.assertEqual(self.both(self.source(text)),(42,42))

    def test_several_try_in_one_expression_and_in_conditions(self)->None:
        text=self.PARSE+('func total(a u32, b u32) Result<u32,u32> {\n  if parse(a)? > 5u32 {\n    return Ok<u32,u32>(parse(a)? + parse(b)?)\n  }\n  return Ok<u32,u32>(0u32)\n}\n'
                         'func main() u32 {\n  match total(10u32,30u32) {\n    Ok(v) { return v - 1u32 + 1u32 }\n    Err(e) { return 1u32 }\n  }\n}\n')
        self.assertEqual(self.both(self.source(text)),(42,42))                       # 11 + 31

    def test_resources_are_cleaned_up_on_every_early_return_over_3000_cycles(self)->None:
        # make() succeeds, then `parse(500)?` fails while the buffer is live. A leaked buffer would exhaust the
        # runtime's 1024 slots, make() would then fail with Err(2) and the counter would stop matching.
        text=self.PARSE+('func make() Result<Resource<Buffer>,u32> !{memory.write} { return buffer.alloc(4u32) }\n'
                         'func fail_after() Result<u32,u32> !{memory.read,memory.write} {\n  let buf = make()?\n  let n = parse(500u32)?\n'
                         '  let r = buffer.release(move(buf))\n  return Ok<u32,u32>(n + r)\n}\n'
                         'func main() u32 !{memory.read,memory.write} {\n  var i u32 = 0u32\n  var failures u32 = 0u32\n'
                         '  for i < 3000u32 {\n    match fail_after() {\n      Ok(v) { failures = 0u32 }\n      Err(e) { if e == 500u32 { failures = failures + 1u32 } }\n    }\n    i = i + 1u32\n  }\n'
                         '  if failures == 3000u32 { return 42u32 }\n  return 1u32\n}\n')
        self.assertEqual(self.both(self.source(text)),(42,42))

    def test_question_mark_inside_generic_functions_and_trait_impl_methods(self)->None:
        text=self.PARSE+('func pass<T>(x T) Result<T,u32> { return Ok<T,u32>(x) }\n'
                         'func twice<T>(x T) Result<T,u32> {\n  let y = pass<T>(x)?\n  return Ok<T,u32>(y)\n}\n'
                         'struct V { n u32 }\ntrait Check { func verify(x Self) Result<u32,u32> }\n'
                         'impl Check for V { func verify(x V) Result<u32,u32> {\n  let n = parse(x.n)?\n  return Ok<u32,u32>(n)\n} }\n'
                         'func main() u32 {\n  var a u32 = 0u32\n  var b u32 = 0u32\n'
                         '  match twice<u32>(21u32) {\n    Ok(v) { a = v }\n    Err(e) { a = 1u32 }\n  }\n'
                         '  let v V = V { n: 20u32 }\n'
                         '  match Check.verify<V>(v) {\n    Ok(w) { b = w }\n    Err(e) { b = 1u32 }\n  }\n'
                         '  return a + b\n}\n')
        self.assertEqual(self.both(self.source(text)),(42,42))                       # 21 + (20 + 1)

    def test_context_position_order_and_type_errors_produce_no_artifact(self)->None:
        cases=(
            ('function does not return Result/Option','func f() u32 {\n  let x = parse(1u32)?\n  return x\n}\nfunc main() u32 { return 0u32 }\n',b'E_TRY_CONTEXT'),
            ('loop condition','func f() Result<u32,u32> {\n  for parse(1u32)? > 0u32 {\n    return Ok<u32,u32>(1u32)\n  }\n  return Ok<u32,u32>(0u32)\n}\nfunc main() u32 { return 0u32 }\n',b'E_TRY_POSITION'),
            ('call evaluated before the question mark','func helper(x u32) u32 { return x }\nfunc f() Result<u32,u32> {\n  let z = helper(1u32) + parse(2u32)?\n  return Ok<u32,u32>(z)\n}\nfunc main() u32 { return 0u32 }\n',b'E_TRY_ORDER'),
            ('different error type','func narrow(x u32) Result<u32,u8> { return Ok<u32,u8>(1u32) }\nfunc f() Result<u32,u32> {\n  let z = narrow(1u32)?\n  return Ok<u32,u32>(z)\n}\nfunc main() u32 { return 0u32 }\n',b'E_TYPE'),
            ('not a Result','func f() Result<u32,u32> {\n  let z = 5u32?\n  return Ok<u32,u32>(z)\n}\nfunc main() u32 { return 0u32 }\n',b'E_TYPE'),
            ('Option inside a Result function','func opt() Option<u32> { return Some<u32>(1u32) }\nfunc f() Result<u32,u32> {\n  let z = opt()?\n  return Ok<u32,u32>(z)\n}\nfunc main() u32 { return 0u32 }\n',b'E_TYPE'),
            ('inside a closure','func f() Result<u32,u32> {\n  let z = closure(y u32) u32 { return parse(y)? }(1u32)\n  return Ok<u32,u32>(z)\n}\nfunc main() u32 { return 0u32 }\n',b'E_TRY_POSITION'),
        )
        for label,body,code in cases:
            with self.subTest(label):
                self.rejected(self.PARSE+body,code)

    def test_no_question_mark_survives_in_any_representation_and_the_formatter_is_stable(self)->None:
        text=self.PARSE+('func twice(a u32) Result<u32,u32> {\n  let x = parse(a)?\n  return Ok<u32,u32>(x + x)\n}\n'
                         'func main() u32 {\n  match twice(20u32) {\n    Ok(v) { return v }\n    Err(e) { return 1u32 }\n  }\n}\n')
        path=self.source(text); wave=proc(OMNI,'wave',path); self.assertEqual(wave.returncode,0,wave.stderr)
        self.assertTrue(wave.stdout.startswith(b'(omni-wave 18')); self.assertNotIn(b'?',wave.stdout)
        owave=self.dir/'q.owave'; owave.write_bytes(wave.stdout); self.assertEqual(proc(OMNI,'wave',owave).stdout,wave.stdout)
        wire=self.dir/'q.owire'; self.assertEqual(proc(OMNI,'pack',path,'-o',wire).returncode,0); self.assertEqual(proc(OMNI,'wave',wire).stdout,wave.stdout)
        for artifact in (path,owave,wire): self.assertEqual(proc(OMNI,'eval',artifact).returncode,42,artifact.name)
        once=proc(OMNI,'fmt',path); self.assertEqual(once.returncode,0,once.stderr)
        formatted=self.dir/'formatted.omni'; formatted.write_bytes(once.stdout)
        twice=proc(OMNI,'fmt',formatted); self.assertEqual(twice.returncode,0,twice.stderr); self.assertEqual(twice.stdout,once.stdout)
        self.assertEqual(proc(OMNI,'eval',formatted).returncode,42)


class A83RelatedLocationTests(unittest.TestCase):
    """CP-16: omni.diagnostic/1 gains an optional, additive `related` array (conflicting loan, move site)."""

    CONFLICT=('func main() u32 !{memory.read,memory.write} {\n  let first Result<Resource<Buffer>,u32> = buffer.alloc(2u32)\n  match first {\n    Ok(buf) {\n'
              '      let reader = borrow(buf)\n      let r = buffer.release(move(buf))\n      return buffer.len(reader) + r\n    }\n    Err(code) { return code }\n  }\n}\n')
    MOVED=('func main() u32 !{memory.read,memory.write} {\n  let first Result<Resource<Buffer>,u32> = buffer.alloc(2u32)\n  match first {\n    Ok(buf) {\n'
           '      let r = buffer.release(move(buf))\n      let n = buffer.len(borrow(buf))\n      return n + r\n    }\n    Err(code) { return code }\n  }\n}\n')

    def setUp(self)->None:
        self.tmp=tempfile.TemporaryDirectory(prefix='omni-a83-related-')
        self.dir=pathlib.Path(self.tmp.name)

    def tearDown(self)->None:
        self.tmp.cleanup()

    def write(self,body:str,name:str='program.omni')->tuple[pathlib.Path,list[str]]:
        text='module t\n'+body; path=self.dir/name; path.write_text(text,encoding='utf-8')
        return path,text.split('\n')

    @staticmethod
    def line_of(lines:list[str],needle:str)->int:
        return next(i for i,l in enumerate(lines,1) if needle in l)

    def test_conflicting_loan_points_back_to_where_it_was_created(self)->None:
        path,lines=self.write(self.CONFLICT)
        result=proc(OMNI,'check',path,'--diagnostic-format','json'); self.assertEqual(result.returncode,2)
        record=json.loads(result.stderr)
        self.assertEqual((record['schema'],record['code']),('omni.diagnostic/1','E_BORROW_CONFLICT'))
        self.assertEqual(record['span']['line'],self.line_of(lines,'buffer.release'))
        self.assertEqual(len(record['related']),1); related=record['related'][0]
        self.assertEqual(related['role'],'conflicting-loan'); self.assertEqual(related['span']['line'],self.line_of(lines,'let reader = borrow'))
        self.assertEqual(related['span']['coordinate'],'unicode-scalar-1-based'); self.assertTrue(related['source_uri'].startswith('file://'))
        text=proc(OMNI,'check',path).stderr.decode().splitlines()
        self.assertTrue(text[0].startswith('E_BORROW_CONFLICT:')); self.assertTrue(text[1].startswith('  nota (conflicting-loan): '))
        self.assertIn(f':{self.line_of(lines,"let reader = borrow")}:',text[1])

    def test_use_after_move_points_to_the_move(self)->None:
        path,lines=self.write(self.MOVED)
        record=json.loads(proc(OMNI,'check',path,'--diagnostic-format','json').stderr)
        self.assertEqual(record['code'],'E_RESOURCE_MOVED'); self.assertEqual(record['span']['line'],self.line_of(lines,'let n = buffer.len'))
        self.assertEqual([(r['role'],r['span']['line']) for r in record['related']],[('moved-here',self.line_of(lines,'buffer.release'))])

    def test_diagnostics_without_a_secondary_location_are_unchanged(self)->None:
        path,_=self.write('func main() u32 { return true }\n')
        raw=proc(OMNI,'check',path,'--diagnostic-format','json').stderr; record=json.loads(raw)
        self.assertEqual(record['code'],'E_TYPE'); self.assertNotIn('related',record); self.assertNotIn(b'"related"',raw)
        self.assertEqual(len(proc(OMNI,'check',path).stderr.decode().splitlines()),1)            # text: still one line


class A83CallbackPatternTests(unittest.TestCase):
    """CP-06 by composition: a callback is an environment struct that implements a trait and is passed to a bounded
    generic function. Static dispatch means it cannot outlive its environment, and an environment that owns a
    Resource follows every ownership rule (moved into the call, released inside it, nothing leaked)."""

    def setUp(self)->None:
        self.tmp=tempfile.TemporaryDirectory(prefix='omni-a83-callback-')
        self.dir=pathlib.Path(self.tmp.name)

    def tearDown(self)->None:
        self.tmp.cleanup()

    def source(self,text:str,name:str='program.omni')->pathlib.Path:
        path=self.dir/name
        path.write_text('module t\n'+text,encoding='utf-8')
        return path

    def both(self,path:pathlib.Path)->tuple[int,int]:
        evaluated=proc(OMNI,'eval',path)
        native=self.dir/(path.stem+'-native')
        built=proc(OMNI,'build',path,'-o',native,'--cache-dir',self.dir/'cache')
        self.assertEqual(built.returncode,0,built.stderr)
        return evaluated.returncode,proc(native).returncode

    COPY=('struct Adder { n u32 }\nstruct Doubler { k u32 }\ntrait Callback { func call(f Self, x u32) u32 }\n'
          'impl Callback for Adder { func call(f Adder, x u32) u32 { return f.n + x } }\n'
          'impl Callback for Doubler { func call(f Doubler, x u32) u32 { return x * f.k } }\n'
          'func run<F: Callback>(f F, x u32) u32 { return Callback.call<F>(f, x) }\n'
          'func twice<F: Callback>(f F, x u32) u32 {\n  let once = Callback.call<F>(f, x)\n  return Callback.call<F>(f, once)\n}\n')

    def test_environment_callbacks_are_passed_to_generic_code(self)->None:
        text=self.COPY+('func main() u32 {\n  let a Adder = Adder { n: 5u32 }\n  let d Doubler = Doubler { k: 3u32 }\n'
                        '  return run<Adder>(a, 10u32) + twice<Doubler>(d, 2u32) + twice<Adder>(a, 4u32) - 3u32 - 2u32\n}\n')
        self.assertEqual(self.both(self.source(text)),(42,42))                       # 15 + 18 + 14 - 5

    RESOURCE=('struct Owner { buf Resource<Buffer> }\ntrait Task { func consume(t Self, x u32) u32 !{memory.read,memory.write} }\n'
              'impl Task for Owner { func consume(t Owner, x u32) u32 !{memory.read,memory.write} {\n'
              '  let n = buffer.len(borrow(t.buf))\n  let r = buffer.release(move(t.buf))\n  return n + r + x\n} }\n'
              'func submit<T: Task>(t T, x u32) u32 !{memory.read,memory.write} { return Task.consume<T>(move(t), x) }\n')

    def test_environment_that_owns_a_resource_is_moved_into_the_call_and_released_there(self)->None:
        text=self.RESOURCE+('func main() u32 !{memory.read,memory.write} {\n  let first Result<Resource<Buffer>,u32> = buffer.alloc(4u32)\n  match first {\n'
                            '    Ok(b) { return submit<Owner>(Owner { buf: move(b) }, 38u32) }\n    Err(code) { return code }\n  }\n}\n')
        self.assertEqual(self.both(self.source(text)),(42,42))

    def test_a_bound_environment_is_moved_into_the_call_with_move(self)->None:
        text=self.RESOURCE+('func main() u32 !{memory.read,memory.write} {\n  let first Result<Resource<Buffer>,u32> = buffer.alloc(4u32)\n  match first {\n'
                            '    Ok(b) {\n      let o Owner = Owner { buf: move(b) }\n      return submit<Owner>(move(o), 38u32)\n    }\n    Err(code) { return code }\n  }\n}\n')
        self.assertEqual(self.both(self.source(text)),(42,42))

    def test_no_resource_leaks_across_3000_callbacks(self)->None:
        text=self.RESOURCE+('func main() u32 !{memory.read,memory.write} {\n  var i u32 = 0u32\n  var done u32 = 0u32\n  for i < 3000u32 {\n'
                            '    let first Result<Resource<Buffer>,u32> = buffer.alloc(4u32)\n    match first {\n'
                            '      Ok(b) { done = done + submit<Owner>(Owner { buf: move(b) }, 0u32) - 3u32 }\n      Err(code) { done = 0u32 }\n    }\n    i = i + 1u32\n  }\n'
                            '  if done == 3000u32 { return 42u32 }\n  return 1u32\n}\n')
        self.assertEqual(self.both(self.source(text)),(42,42))                       # each callback returns 4 (len) -> +1

    def test_a_callback_environment_cannot_be_used_after_it_was_moved_or_copied(self)->None:
        for label,body,code in (
            ('bound environment cannot be passed without move (would copy the Resource)','    Ok(b) {\n      let o Owner = Owner { buf: move(b) }\n      return submit<Owner>(o, 1u32)\n    }\n',b'E_RESOURCE_ACCESS'),
            ('environment used after it was moved into the call','    Ok(b) {\n      let o Owner = Owner { buf: move(b) }\n      let one = submit<Owner>(move(o), 1u32)\n      let two = submit<Owner>(move(o), 1u32)\n      return one + two\n    }\n',b'E_RESOURCE_MOVED'),
            ('no impl for the environment','    Ok(b) {\n      let r = buffer.release(move(b))\n      return submit<Adder2>(Adder2 { n: 1u32 }, r)\n    }\n',b'E_'),
            ('environment released twice','    Ok(b) {\n      let o = submit<Owner>(Owner { buf: move(b) }, 1u32)\n      let again = buffer.release(move(b))\n      return o + again\n    }\n',b'E_RESOURCE_MOVED'),
        ):
            with self.subTest(label):
                text=self.RESOURCE+'struct Adder2 { n u32 }\nfunc main() u32 !{memory.read,memory.write} {\n  let first Result<Resource<Buffer>,u32> = buffer.alloc(4u32)\n  match first {\n'+body+'    Err(code) { return code }\n  }\n}\n'
                path=self.source(text,'bad.omni'); result=proc(OMNI,'check',path)
                self.assertEqual(result.returncode,2,result.stderr); self.assertIn(code,result.stderr,result.stderr)


class A83AggregateMoveTests(unittest.TestCase):
    """CP-01b (spec/AGGREGATE_MOVE_CANDIDATE.md): move(r) of a struct that owns Resources, via the field-move machinery."""

    def setUp(self)->None:
        self.tmp=tempfile.TemporaryDirectory(prefix='omni-a83-aggmove-')
        self.dir=pathlib.Path(self.tmp.name)

    def tearDown(self)->None:
        self.tmp.cleanup()

    def source(self,text:str,name:str='program.omni')->pathlib.Path:
        path=self.dir/name
        path.write_text('module t\n'+text,encoding='utf-8')
        return path

    def both(self,path:pathlib.Path)->tuple[int,int]:
        evaluated=proc(OMNI,'eval',path)
        native=self.dir/(path.stem+'-native')
        built=proc(OMNI,'build',path,'-o',native,'--cache-dir',self.dir/'cache')
        self.assertEqual(built.returncode,0,built.stderr)
        return evaluated.returncode,proc(native).returncode

    def rejected(self,text:str,code:bytes)->None:
        path=self.source(text,'bad.omni'); result=proc(OMNI,'check',path)
        self.assertEqual(result.returncode,2,result.stderr); self.assertIn(code,result.stderr,result.stderr)
        output=self.dir/'never'
        self.assertEqual(proc(OMNI,'build',path,'-o',output,'--cache-dir',self.dir/'cache').returncode,2)
        self.assertFalse(output.exists())

    ALLOC='  let first Result<Resource<Buffer>,u32> = buffer.alloc(4u32)\n  match first {\n'
    DECL=('struct Inner { buf Resource<Buffer>, tag u32 }\nstruct Outer { id u32, inner Inner, spare Resource<Buffer> }\n'
          'func drain(o Outer) u32 !{memory.read,memory.write} {\n'
          '  let a = buffer.len(borrow(o.inner.buf))\n  let r1 = buffer.release(move(o.inner.buf))\n  let r2 = buffer.release(move(o.spare))\n'
          '  return o.id + o.inner.tag + a + r1 + r2\n}\n')

    def main_with(self,body:str)->str:
        return self.DECL+'func main() u32 !{memory.read,memory.write} {\n'+self.ALLOC+'    Ok(b) {\n      let c Result<Resource<Buffer>,u32> = buffer.alloc(2u32)\n      match c {\n        Ok(s) {\n'+body+'        }\n        Err(code) { return code }\n      }\n    }\n    Err(code) { return code }\n  }\n}\n'

    def test_nested_aggregate_is_moved_into_a_call_with_copy_fields_preserved(self)->None:
        text=self.main_with('          let o Outer = Outer { id: 30u32, inner: Inner { buf: move(b), tag: 8u32 }, spare: move(s) }\n          return drain(move(o))\n')
        self.assertEqual(self.both(self.source(text)),(42,42))                       # 30 + 8 + len 4 + 0 + 0

    def test_moving_twice_or_touching_a_moved_leaf_is_rejected(self)->None:
        base='          let o Outer = Outer { id: 1u32, inner: Inner { buf: move(b), tag: 2u32 }, spare: move(s) }\n'
        self.rejected(self.main_with(base+'          let x = drain(move(o))\n          let y = drain(move(o))\n          return x + y\n'),b'E_RESOURCE_MOVED')
        self.rejected(self.main_with(base+'          let x = drain(move(o))\n          return buffer.len(borrow(o.spare)) + x\n'),b'E_RESOURCE_MOVED')
        self.rejected(self.main_with(base+'          let early = buffer.release(move(o.spare))\n          return drain(move(o)) + early\n'),b'E_RESOURCE_MOVED')

    def test_a_live_loan_on_a_leaf_blocks_the_aggregate_move_and_points_at_the_loan(self)->None:
        text=self.main_with('          let o Outer = Outer { id: 1u32, inner: Inner { buf: move(b), tag: 2u32 }, spare: move(s) }\n'
                            '          let reader = borrow(o.spare)\n          let moved = drain(move(o))\n          return buffer.len(reader) + moved\n')
        self.rejected(text,b'E_BORROW_CONFLICT')
        record=json.loads(proc(OMNI,'check',self.dir/'bad.omni','--diagnostic-format','json').stderr)
        self.assertEqual([r['role'] for r in record['related']],['conflicting-loan'])

    def test_bare_use_and_resourceless_structs_keep_their_existing_errors(self)->None:
        self.rejected(self.main_with('          let o Outer = Outer { id: 1u32, inner: Inner { buf: move(b), tag: 2u32 }, spare: move(s) }\n          return drain(o)\n'),b'E_RESOURCE_ACCESS')
        self.rejected('struct Plain { n u32 }\nfunc take(p Plain) u32 { return p.n }\nfunc main() u32 {\n  let p Plain = Plain { n: 1u32 }\n  return take(move(p))\n}\n',b'E_RESOURCE_ACCESS')

    def test_the_callee_may_leave_leaves_to_automatic_cleanup_across_3000_moves(self)->None:
        text=('struct Pair { left Resource<Buffer>, right Resource<Buffer> }\n'
              'func ignore(p Pair) u32 { return 1u32 }\n'
              'func main() u32 !{memory.read,memory.write} {\n  var i u32 = 0u32\n  var done u32 = 0u32\n  for i < 3000u32 {\n'
              '    let a Result<Resource<Buffer>,u32> = buffer.alloc(4u32)\n    match a {\n      Ok(x) {\n        let c Result<Resource<Buffer>,u32> = buffer.alloc(4u32)\n        match c {\n'
              '          Ok(y) {\n            let p Pair = Pair { left: move(x), right: move(y) }\n            done = done + ignore(move(p))\n          }\n'
              '          Err(code) { let dropped = buffer.release(move(x))\n                      done = 0u32 }\n        }\n      }\n      Err(code) { done = 0u32 }\n    }\n    i = i + 1u32\n  }\n'
              '  if done == 3000u32 { return 42u32 }\n  return 1u32\n}\n')
        self.assertEqual(self.both(self.source(text)),(42,42))

    def test_representation_is_unchanged_and_round_trips(self)->None:
        text=self.main_with('          let o Outer = Outer { id: 30u32, inner: Inner { buf: move(b), tag: 8u32 }, spare: move(s) }\n          return drain(move(o))\n')
        path=self.source(text); wave=proc(OMNI,'wave',path); self.assertEqual(wave.returncode,0,wave.stderr)
        self.assertTrue(wave.stdout.startswith(b'(omni-wave 18'))
        owave=self.dir/'a.owave'; owave.write_bytes(wave.stdout); self.assertEqual(proc(OMNI,'wave',owave).stdout,wave.stdout)
        wire=self.dir/'a.owire'; self.assertEqual(proc(OMNI,'pack',path,'-o',wire).returncode,0); self.assertEqual(proc(OMNI,'wave',wire).stdout,wave.stdout)
        for artifact in (path,owave,wire): self.assertEqual(proc(OMNI,'eval',artifact).returncode,42,artifact.name)


class A83NominalMergeTests(unittest.TestCase):
    """Generalizable nominal resources: the nominal Resource<R> keeps its
    must-consume rule directly and in admitted containers; a record cannot erase its obligation."""

    TOK=('struct Tok { h u64 }\n'
         'func mint() Resource<Tok> {\n  return resource.seal(Tok { h: 7u64 })\n}\n'
         'func eat(t Resource<Tok>) u64 {\n  let r = resource.unseal(move(t))\n  return r.h\n}\n')

    def setUp(self)->None:
        self.tmp=tempfile.TemporaryDirectory(prefix='omni-a83-nominal-')
        self.dir=pathlib.Path(self.tmp.name)

    def tearDown(self)->None:
        self.tmp.cleanup()

    def source(self,text:str,name:str='program.omni')->pathlib.Path:
        path=self.dir/name
        path.write_text('module t\n'+text,encoding='utf-8')
        return path

    def rejected(self,text:str,code:bytes)->None:
        path=self.source(text,'bad.omni'); result=proc(OMNI,'check',path)
        self.assertEqual(result.returncode,2,result.stderr); self.assertIn(code,result.stderr,result.stderr)
        output=self.dir/'never'
        self.assertEqual(proc(OMNI,'build',path,'-o',output,'--cache-dir',self.dir/'cache').returncode,2)
        self.assertFalse(output.exists())

    def test_nominal_resource_consumed_runs_with_evaluator_native_parity(self)->None:
        path=self.source(self.TOK+'func main() u32 {\n  let t = mint()\n  let v = eat(move(t))\n  if v == 7u64 { return 0u32 }\n  return 1u32\n}\n')
        evaluated=proc(OMNI,'eval',path); native=self.dir/'native'
        self.assertEqual(proc(OMNI,'build',path,'-o',native,'--cache-dir',self.dir/'cache').returncode,0)
        self.assertEqual((evaluated.returncode,proc(native).returncode),(0,0),evaluated.stderr)

    def test_option_of_nominal_resource_cannot_be_copied(self)->None:
        self.rejected(self.TOK+'func dup(o Option<Resource<Tok>>) u32 {\n  let a = o\n  let b = o\n  return 0u32\n}\nfunc main() u32 { return 0u32 }\n',b'E_RESULT_MOVED')

    NOMINAL_SLOT=('func held(full bool) Option<Resource<Tok>> {\n'
                  '  if full { return Some<Resource<Tok>>(mint()) }\n  return None<Resource<Tok>>()\n}\n'
                  'func forward(o Option<Resource<Tok>>) Option<Resource<Tok>> { return o }\n'
                  'func finish(o Option<Resource<Tok>>) u32 {\n  match o {\n'
                  '    Some(t) { return u32(eat(move(t))) + 34u32 }\n    None { return 1u32 }\n  }\n}\n')

    def test_nominal_option_some_none_call_and_return_have_native_parity(self)->None:
        path=self.source(self.TOK+self.NOMINAL_SLOT+'func main() u32 { return finish(forward(held(true))) + finish(held(false)) }\n')
        evaluated=proc(OMNI,'eval',path); native=self.dir/'nominal-option-native'
        result=proc(OMNI,'build',path,'-o',native,'--cache-dir',self.dir/'cache')
        self.assertEqual(result.returncode,0,result.stderr); self.assertEqual((evaluated.returncode,proc(native).returncode),(42,42),evaluated.stderr)

    def test_nominal_option_does_not_discard_the_payload_obligation(self)->None:
        head=self.TOK+self.NOMINAL_SLOT
        for full in ('true','false'):
            self.rejected(head+'func main() u32 { let o = held('+full+'); return 0u32 }\n',b'E_RESULT_UNHANDLED')
        self.rejected(head+'func main() u32 { let o = held(true); match o { Some(t) { return 0u32 } None { return 0u32 } } }\n',b'E_RESOURCE_UNCONSUMED')
        self.rejected(self.TOK+'func main() u32 { let t = mint(); let o = Some<Resource<Tok>>(move(t)); let again = eat(move(t)); return 0u32 }\n',b'E_RESOURCE_MOVED')
        self.rejected(head+'func main() u32 { let o = held(true); return closure(x u32) u32 { return finish(o) + x }(0u32) }\n',b'E_CLOSURE_CAPTURE')
        for typ,code in (('Option<Option<Resource<Tok>>>',b'E_RESULT_UNHANDLED'),('Result<Option<Resource<Tok>>,u32>',b'E_RESULT_UNHANDLED'),('Tuple<u32,Option<Resource<Tok>>>',b'E_RESULT_UNHANDLED'),('Array<Option<Resource<Tok>>,2>',b'E_RESULT_UNHANDLED')):
            self.rejected(self.TOK+'func reject(x '+typ+') u32 { return 0u32 }\nfunc main() u32 { return 0u32 }\n',code)
        self.rejected(self.TOK+'struct Hidden { o Option<Resource<Tok>> }\nfunc bad(h Hidden) u32 { return 0u32 }\nfunc main() u32 { return 0u32 }\n',b'E_RESULT_UNHANDLED')

    def test_nominal_option_representations_preserve_obligations_and_identity(self)->None:
        path=self.source(self.TOK+self.NOMINAL_SLOT+'func main() u32 { return finish(held(true)) + finish(held(false)) }\n')
        wave=proc(OMNI,'wave',path); self.assertEqual(wave.returncode,0,wave.stderr); self.assertTrue(wave.stdout.startswith(b'(omni-wave 21'))
        ow=self.dir/'nominal.owave'; ow.write_bytes(wave.stdout)
        wire=self.dir/'nominal.owire'; self.assertEqual(proc(OMNI,'pack',path,'-o',wire).returncode,0)
        onme=self.dir/'nominal.onme'; self.assertEqual(proc(OMNI,'onme',path,'-o',onme).returncode,0)
        original=proc(OMNI,'memory',path); self.assertEqual(original.returncode,0,original.stderr)
        for derived in (ow,wire,onme):
            self.assertEqual(proc(OMNI,'eval',derived).returncode,42,derived.name)
            self.assertEqual(proc(OMNI,'memory',derived).stdout,original.stdout,derived.name)
        for old in (18,20):
            bad=self.dir/'old.owave'; bad.write_bytes(wave.stdout.replace(b'omni-wave 21',f'omni-wave {old}'.encode(),1))
            result=proc(OMNI,'check',bad); self.assertEqual(result.returncode,2,result.stderr); self.assertIn(b'E_VERSION',result.stderr)
            raw=bytearray(wire.read_bytes()); raw[4]=old; bad=self.dir/'old.owire'; bad.write_bytes(raw)
            result=proc(OMNI,'check',bad); self.assertEqual(result.returncode,2,result.stderr); self.assertIn(b'E_VERSION',result.stderr)

    def test_option_of_buffer_resource_stays_accepted_next_to_nominals(self)->None:
        text=self.TOK+A83OptionResourceTests.SLOT+('func main() u32 !{memory.read,memory.write} {\n  let a = slot(true)\n  var total u32 = 0u32\n'
                                                   '  match a {\n    Some(r) { total = total + buffer.len(borrow(r)) }\n    None { total = total + 100u32 }\n  }\n  return total - 3u32\n}\n')
        path=self.source(text); evaluated=proc(OMNI,'eval',path)
        self.assertEqual(evaluated.returncode,0,evaluated.stderr)

    def test_live_nominal_resource_is_unconsumed_at_every_exit(self)->None:
        self.rejected(self.TOK+'func main() u32 {\n  let t = mint()\n  return 0u32\n}\n',b'E_RESOURCE_UNCONSUMED')
        self.rejected(self.TOK+'func main() u32 {\n  let t = mint()\n  if true { return 0u32 }\n  let v = eat(move(t))\n  return 1u32\n}\n',b'E_RESOURCE_UNCONSUMED')

    def test_nominal_resource_cannot_be_abandoned_in_a_record_or_moved_twice(self)->None:
        self.rejected(self.TOK+'struct Holder { t Resource<Tok> }\nfunc use(h Holder) u32 {\n  return 0u32\n}\nfunc main() u32 {\n  return 0u32\n}\n',b'E_RESOURCE_UNCONSUMED')
        self.rejected(self.TOK+'func main() u32 {\n  let t = mint()\n  let a = eat(move(t))\n  let b = eat(move(t))\n  return 0u32\n}\n',b'E_RESOURCE_MOVED')

    def test_borrow_of_nominal_resource_reads_without_consuming(self)->None:
        text=self.TOK+('func peek_it(b Borrow<Tok>) u64 {\n  let r = resource.peek(b)\n  return r.h\n}\n'
                       'func main() u32 {\n  let t = mint()\n  let seen = peek_it(borrow(t))\n  let v = eat(move(t))\n'
                       '  if seen == v { return 0u32 }\n  return 1u32\n}\n')
        path=self.source(text); evaluated=proc(OMNI,'eval',path)
        self.assertEqual(evaluated.returncode,0,evaluated.stderr)


@unittest.skipUnless(shutil.which('qemu-system-i386') and shutil.which('clang') and shutil.which('ld'),'needs qemu-system-i386, clang and ld')
class A83BaremetalBootSmokeTests(unittest.TestCase):
    """CP-08/CP-09 (spec/TARGET_BAREMETAL_PROFILE_CANDIDATE.md): an Omni program with typed port I/O is compiled for the
    baremetal-i386-boot profile, linked as a PVH ELF and executed in QEMU; the same primitives are refused when hosted."""

    BOOT=('func main() u32 !{port.io,cpu.control} {\n'
          '  let a = port.out8(1016u32, 79u32)\n  let b = port.out8(1016u32, 75u32)\n  let c = port.out8(1016u32, 10u32)\n'
          '  let d = port.out32(244u32, 1u32)\n  return cpu.halt()\n}\n')
    LINKER=('ENTRY(omni_boot_entry32)\nPHDRS { text PT_LOAD FLAGS(5); data PT_LOAD FLAGS(6); note PT_NOTE; }\n'
            'SECTIONS {\n  . = 0x100000;\n  .text : { KEEP(*(.text.omni_entry)) *(.text .text.*) } :text\n  .rodata : { *(.rodata .rodata.*) } :text\n'
            '  .note.pvh : { KEEP(*(.note.pvh)) } :text :note\n  . = ALIGN(4096);\n  .data : { *(.data .data.*) } :data\n'
            '  .bss : { *(.bss .bss.* COMMON) } :data\n  /DISCARD/ : { *(.comment) *(.eh_frame) }\n}\n')
    CFLAGS=['-ffreestanding','-fno-builtin','-fno-stack-protector','-fno-pic','-fno-pie','-mno-sse','-mno-sse2','-mno-mmx','-mno-80387','-O2']

    def setUp(self)->None:
        self.tmp=tempfile.TemporaryDirectory(prefix='omni-a83-boot-')
        self.dir=pathlib.Path(self.tmp.name)

    def tearDown(self)->None:
        self.tmp.cleanup()

    def source(self,text:str,name:str='boot.omni')->pathlib.Path:
        path=self.dir/name
        path.write_text('module boot\n'+text,encoding='utf-8')
        return path

    def emit(self,path:pathlib.Path)->subprocess.CompletedProcess:
        return proc(OMNI,'emit-llvm',path,'--target-profile','baremetal-i386-boot','--service-module','boot','--entry-section','.text.omni_entry',
                    '--entry-address','1048576','--entry-stack','2097152','-o',self.dir/'boot.ll')

    def test_typed_port_io_boots_in_qemu_and_reports_on_serial(self)->None:
        path=self.source(self.BOOT)
        self.assertEqual(proc(OMNI,'check',path).returncode,0)
        self.assertEqual(self.emit(path).returncode,0)
        (self.dir/'link.ld').write_text(self.LINKER,encoding='utf-8')
        compiled=subprocess.run(['clang','-target','i386-unknown-none-elf',*self.CFLAGS,'-nostdlib','-c',str(self.dir/'boot.ll'),'-o',str(self.dir/'boot.o')],capture_output=True)
        self.assertEqual(compiled.returncode,0,compiled.stderr)
        linked=subprocess.run(['ld','-m','elf_i386','-nostdlib','-T',str(self.dir/'link.ld'),str(self.dir/'boot.o'),'-o',str(self.dir/'boot.elf')],capture_output=True)
        self.assertEqual(linked.returncode,0,linked.stderr)
        # The loader jumps to the address in the PVH note: it must be the entry stub itself (first symbol), not merely inside the image.
        symbols=subprocess.run(['nm','-n',str(self.dir/'boot.elf')],capture_output=True,text=True).stdout.splitlines()
        self.assertTrue(symbols and symbols[0].endswith(' T omni_boot_entry32') and symbols[0].startswith('00100000'),symbols[:3])
        notes=subprocess.run(['readelf','-nW',str(self.dir/'boot.elf')],capture_output=True,text=True).stdout
        self.assertIn('description data: 00 00 10 00',notes,notes)
        run=subprocess.run(['qemu-system-i386','-kernel',str(self.dir/'boot.elf'),'-display','none','-serial','stdio','-no-reboot',
                            '-device','isa-debug-exit,iobase=0xf4,iosize=0x04','-m','64'],capture_output=True,timeout=60)
        self.assertEqual(run.stdout,b'OK\n',run.stderr)
        self.assertEqual(run.returncode,3)  # isa-debug-exit value 1 -> (1 << 1) | 1

    def test_hardware_primitives_are_refused_when_hosted(self)->None:
        path=self.source(self.BOOT)
        hosted=proc(OMNI,'build',path,'-o',self.dir/'hosted','--cache-dir',self.dir/'cache')
        self.assertEqual(hosted.returncode,2,hosted.stderr); self.assertIn(b'E_TARGET_PROFILE',hosted.stderr)
        self.assertFalse((self.dir/'hosted').exists())

    def test_primitive_without_capability_and_bad_control_register_are_rejected(self)->None:
        missing=self.source('func main() u32 {\n  let a = port.out8(1016u32, 79u32)\n  return 0u32\n}\n','nocap.omni')
        result=proc(OMNI,'check',missing)
        self.assertEqual(result.returncode,2,result.stderr); self.assertIn(b'E_CAPABILITY',result.stderr)
        nocap_in=self.source('func main() u32 {\n  return port.in8(1016u32)\n}\n','nocap_in.omni')
        result=proc(OMNI,'check',nocap_in)
        self.assertEqual(result.returncode,2,result.stderr); self.assertIn(b'E_CAPABILITY',result.stderr)
        granted_in=self.source('func main() u32 !{port.io} {\n  return port.in8(1016u32)\n}\n','granted_in.omni')
        self.assertEqual(proc(OMNI,'check',granted_in).returncode,0)
        badcr=self.source('func main() u32 !{cpu.control} {\n  let a = cpu.read_cr(1)\n  return a\n}\n','badcr.omni')
        result=self.emit(badcr)
        self.assertEqual(result.returncode,2,result.stderr); self.assertIn(b'E_TARGET_PROFILE',result.stderr)


class A83HardwareFenceTests(unittest.TestCase):
    """G5 (spec/HARDWARE_REPRESENTATION_FENCE_CANDIDATE.md): machine primitives and nominal resources share the Wave21/OMC21 fence.
    Measured before the change: a program with atomics was written as Wire 18 and a core-v1.2.1.0 reader rejected it only with
    E_CAPABILITY ("unknown Wire capability"), i.e. an old version label over new semantics."""

    CASES={
        'atomic':('!{memory.atomic}','  let v u32 = atomic.load32(5308416u64, 4u32)\n  return 0u32\n'),
        'raw':('!{memory.raw}','  let v u32 = raw.load32(5308416u64)\n  return 0u32\n'),
        'port':('!{port.io}','  let v u32 = port.in8(1016u32)\n  return 0u32\n'),
        'cpu':('!{cpu.control}','  let v u32 = cpu.cpuid(1u32, 1u32)\n  return 0u32\n'),
        'tls':('!{memory.tls}','  let v u32 = tls.load32(16u64)\n  return 0u32\n'),
        'pcpu':('!{memory.pcpu}','  let v u64 = pcpu.load64(16u64)\n  return 0u32\n'),
        'tlscap':('!{memory.tls}','  return 0u32\n'),         # the capability alone is new semantics too
        'pcpucap':('!{memory.pcpu}','  return 0u32\n'),
        'nominal':('','  return 0u32\n'),
    }
    NOMINAL=('struct Tok { h u64 }\nfunc mint() Resource<Tok> {\n  return resource.seal(Tok { h: 7u64 })\n}\n'
             'func eat(t Resource<Tok>) u64 {\n  let r = resource.unseal(move(t))\n  return r.h\n}\n')

    def setUp(self)->None:
        self.tmp=tempfile.TemporaryDirectory(prefix='omni-a83-fence-')
        self.dir=pathlib.Path(self.tmp.name)

    def tearDown(self)->None:
        self.tmp.cleanup()

    def source(self,name:str)->pathlib.Path:
        caps,body=self.CASES[name]
        prelude=self.NOMINAL if name=='nominal' else ''
        path=self.dir/f'{name}.omni'
        path.write_text('module t\n'+prelude+'func main() u32 '+caps+' {\n'+body+'}\n' if caps else 'module t\n'+prelude+'func main() u32 {\n  let t = mint()\n  let v = eat(move(t))\n  return 0u32\n}\n',encoding='utf-8')
        return path

    def test_machine_primitives_and_nominal_resources_are_written_as_wave21_and_omc21(self)->None:
        for name in self.CASES:
            path=self.source(name)
            wave=proc(OMNI,'wave',path); self.assertEqual(wave.returncode,0,(name,wave.stderr))
            self.assertTrue(wave.stdout.startswith(b'(omni-wave 21'),(name,wave.stdout[:20]))
            wire=self.dir/f'{name}.owire'; self.assertEqual(proc(OMNI,'pack',path,'-o',wire).returncode,0,name)
            self.assertEqual(wire.read_bytes()[:8],b'OMCX\x15\x00\x00\x00',name)
            # the current reader accepts what the current writer produced, textual and binary
            (self.dir/f'{name}.owave').write_bytes(wave.stdout)
            self.assertEqual(proc(OMNI,'check',self.dir/f'{name}.owave').returncode,0,name)
            self.assertEqual(proc(OMNI,'check',wire).returncode,0,name)

    def test_relabelling_as_an_older_version_is_rejected_with_e_version(self)->None:
        for name in self.CASES:
            path=self.source(name)
            wave=proc(OMNI,'wave',path).stdout; wire=self.dir/f'{name}.owire'; self.assertEqual(proc(OMNI,'pack',path,'-o',wire).returncode,0)
            for old in (18,19,20):
                relabelled_wave=self.dir/f'{name}-as-wave{old}.owave'
                relabelled_wave.write_bytes(wave.replace(b'(omni-wave 21',f'(omni-wave {old}'.encode(),1))
                result=proc(OMNI,'check',relabelled_wave)
                self.assertEqual(result.returncode,2,(name,old,result.stderr)); self.assertIn(b'E_VERSION',result.stderr,(name,old,result.stderr))
                raw=bytearray(wire.read_bytes()); raw[4]=old
                relabelled_wire=self.dir/f'{name}-as-omc{old}.owire'; relabelled_wire.write_bytes(bytes(raw))
                result=proc(OMNI,'check',relabelled_wire)
                self.assertEqual(result.returncode,2,(name,old,result.stderr)); self.assertIn(b'E_VERSION',result.stderr,(name,old,result.stderr))

    def test_programs_without_the_new_semantics_keep_their_minimum_writer(self)->None:
        plain=self.dir/'plain.omni'; plain.write_text('module t\nfunc main() u32 { return 7u32 }\n',encoding='utf-8')
        self.assertTrue(proc(OMNI,'wave',plain).stdout.startswith(b'(omni-wave 18'))
        wire=self.dir/'plain.owire'; self.assertEqual(proc(OMNI,'pack',plain,'-o',wire).returncode,0)
        self.assertEqual(wire.read_bytes()[:8],b'OMCX\x12\x00\x00\x00')
        buffer_resource=self.dir/'buffer.omni'
        buffer_resource.write_text('module t\nfunc main() u32 !{memory.read,memory.write} {\n  let r Result<Resource<Buffer>,u32> = buffer.alloc(8u32)\n  match r {\n    Ok(b) { return buffer.len(borrow(b)) }\n    Err(code) { return code }\n  }\n}\n',encoding='utf-8')
        self.assertTrue(proc(OMNI,'wave',buffer_resource).stdout.startswith(b'(omni-wave 18'))  # Resource<Buffer> is not a nominal resource


class A83OsnmfNewSemanticsTests(unittest.TestCase):
    """C2 / CP-15: the OSNMF projection of the semantics added in this program (returned borrows, Option<Resource>, generic instances,
    nominal resources, machine capabilities) is derived from the checked program, is the same through every representation, keeps
    distinct identities distinct and rejects tampering. It carries no authority and no live state."""

    PROGRAMS={
        'shared':'func lend(b Borrow<Buffer>) Borrow<Buffer> !{memory.read} { return b }\nfunc main() u32 { return 0u32 }\n',
        'mutable':'func lend(b BorrowMut<Buffer>) BorrowMut<Buffer> !{memory.write} { return b }\nfunc main() u32 { return 0u32 }\n',
        'optres':'func slot() Option<Resource<Buffer>> !{memory.write} { return None<Resource<Buffer>>() }\nfunc main() u32 { return 0u32 }\n',
        'resbuf':'func slot() Result<Resource<Buffer>,u32> !{memory.write} { return buffer.alloc(8u32) }\nfunc main() u32 { return 0u32 }\n',
        'generic':'struct Pair<A, B> { a A, b B }\nfunc main() u32 {\n  let p Pair<u32, u8> = Pair<u32, u8> { a: 1u32, b: 2u8 }\n  let q Pair<u8, u8> = Pair<u8, u8> { a: 1u8, b: 2u8 }\n  return 0u32\n}\n',
        'nominal':'struct Tok { h u64 }\nfunc mint() Resource<Tok> {\n  return resource.seal(Tok { h: 7u64 })\n}\nfunc eat(t Resource<Tok>) u64 {\n  let r = resource.unseal(move(t))\n  return r.h\n}\nfunc main() u32 {\n  let t = mint()\n  let v = eat(move(t))\n  return 0u32\n}\n',
        'atomic':'func main() u32 !{memory.atomic} {\n  let v u32 = atomic.load32(5308416u64, 4u32)\n  return 0u32\n}\n',
        'tls':'func main() u32 !{memory.tls} {\n  let v u32 = tls.load32(16u64)\n  return 0u32\n}\n',
        'pcpu':'func main() u32 !{memory.pcpu} {\n  let v u32 = pcpu.load32(16u64)\n  return 0u32\n}\n',
        'plain':'func main() u32 { return 0u32 }\n',
    }

    def setUp(self)->None:
        self.tmp=tempfile.TemporaryDirectory(prefix='omni-a83-osnmf-')
        self.dir=pathlib.Path(self.tmp.name)

    def tearDown(self)->None:
        self.tmp.cleanup()

    def source(self,name:str)->pathlib.Path:
        path=self.dir/f'{name}.omni'
        path.write_text('module t\n'+self.PROGRAMS[name],encoding='utf-8')
        return path

    def memory(self,path:pathlib.Path)->bytes:
        result=proc(OMNI,'memory',path); self.assertEqual(result.returncode,0,(path.name,result.stderr))
        return result.stdout

    def nuclei(self,store:bytes)->list[dict]:
        return json.loads(store)['nuclei']

    def one(self,store:bytes,kind:str,name:str)->dict:
        found=[n for n in self.nuclei(store) if n['kind']==kind and n['name']==name]
        self.assertEqual(len(found),1,(kind,name,[(n['kind'],n['name']) for n in self.nuclei(store)]))
        return found[0]

    def test_projection_is_deterministic_and_identical_through_every_representation(self)->None:
        for name in self.PROGRAMS:
            path=self.source(name); store=self.memory(path)
            self.assertEqual(self.memory(path),store,name)                      # deterministic
            wire=self.dir/f'{name}.owire'; self.assertEqual(proc(OMNI,'pack',path,'-o',wire).returncode,0,name)
            wave=self.dir/f'{name}.owave'; wave.write_bytes(proc(OMNI,'wave',path).stdout)
            onme=self.dir/f'{name}.onme'; self.assertEqual(proc(OMNI,'onme',path,'-o',onme).returncode,0,name)
            for derived in (wire,wave,onme):
                self.assertEqual(self.memory(derived),store,(name,derived.suffix))  # Particle -> Wave/Wire/ONME -> OSNMF is lossless here

    def test_new_semantics_keep_distinct_identities_distinct(self)->None:
        shared,mutable=self.memory(self.source('shared')),self.memory(self.source('mutable'))
        a,b=self.one(shared,'function','lend'),self.one(mutable,'function','lend')
        self.assertNotEqual(a['type_id'],b['type_id'])                      # shared vs mutable returned borrow
        self.assertNotEqual(self.one(shared,'type','Borrow<Buffer>')['type_id'],self.one(mutable,'type','BorrowMut<Buffer>')['type_id'])
        optres,resbuf=self.memory(self.source('optres')),self.memory(self.source('resbuf'))
        self.assertNotEqual(self.one(optres,'type','Option<Resource<Buffer>>')['type_id'],self.one(optres,'type','Resource<Buffer>')['type_id'])
        self.assertEqual(self.one(optres,'type','Resource<Buffer>')['type_id'],self.one(resbuf,'type','Resource<Buffer>')['type_id'])  # same type, same id across programs
        generic=self.nuclei(self.memory(self.source('generic')))
        instances={n['type_id'] for n in generic if n['kind']=='record' and '__g_' in n['name']}
        self.assertEqual(len(instances),2)                                  # Pair<u32,u8> and Pair<u8,u8> are different types
        nominal=self.memory(self.source('nominal'))
        self.assertNotEqual(self.one(nominal,'type','Resource<t.Tok>')['type_id'],self.one(nominal,'type','Tok')['type_id'])
        # same visible name in two modules: different nominal identity
        (self.dir/'a.omni').write_text('module a\npub struct Tok { h u64 }\n',encoding='utf-8')
        (self.dir/'b.omni').write_text('module b\npub struct Tok { h u64 }\n',encoding='utf-8')
        app=self.dir/'app.omni'
        app.write_text('module app\nimport a "a.omni"\nimport b "b.omni"\nfunc fa(t Borrow<a.Tok>) u32 { return 0u32 }\nfunc fb(t Borrow<b.Tok>) u32 { return 0u32 }\nfunc main() u32 { return 0u32 }\n',encoding='utf-8')
        two=self.memory(app)
        ids={n['name']:n['type_id'] for n in self.nuclei(two) if n['kind']=='type' and n['name'].startswith('Borrow<')}
        self.assertEqual(len(ids),2,ids); self.assertEqual(len(set(ids.values())),2,ids)

    def test_machine_capability_is_a_nucleus_and_its_impact_is_traceable(self)->None:
        atomic,plain=self.memory(self.source('atomic')),self.memory(self.source('plain'))
        self.assertEqual(self.one(atomic,'capability','memory.atomic')['kind'],'capability')
        self.assertEqual([n for n in self.nuclei(plain) if n['kind']=='capability'],[])
        tls,pcpu=self.memory(self.source('tls')),self.memory(self.source('pcpu'))
        self.assertEqual([n['name'] for n in self.nuclei(tls) if n['kind']=='capability'],['memory.tls'])     # distinct authorities, distinct nuclei
        self.assertEqual([n['name'] for n in self.nuclei(pcpu) if n['kind']=='capability'],['memory.pcpu'])
        self.assertEqual(len({self.one(s,'function','main')['contract_id'] for s in (atomic,tls,pcpu,plain)}),4)
        # ContractID tracks the effect requirement: the same-shape function with and without the capability differs
        self.assertNotEqual(self.one(atomic,'function','main')['contract_id'],self.one(plain,'function','main')['contract_id'])
        omem=self.dir/'atomic.omem'; self.assertEqual(proc(OMNI,'memory-pack',self.source('atomic'),'-o',omem).returncode,0)
        summary=json.loads(proc(OMNI,'memory-summary',omem).stdout)
        self.assertEqual(summary['kinds']['capability'],1); self.assertIn('requires-capability',summary['relations'])
        self.assertFalse(summary['ai_required']); self.assertEqual(summary['source_files_scanned'],0)
        query=json.loads(proc(OMNI,'memory-query',omem,'--capability','memory.atomic').stdout)
        self.assertIn('main',[n['name'] for n in query['nuclei']]); self.assertTrue(query['edges'])
        self.assertTrue(query['unknown_edges_conservative'])
        impact=json.loads(proc(OMNI,'memory-impact',omem,'--entity','memory.atomic').stdout)
        self.assertTrue(impact['plan_only']); self.assertGreaterEqual(impact['affected_nodes'],2); self.assertIn('function',impact['kinds'])

    def test_tampered_or_relabelled_store_is_rejected(self)->None:
        omem=self.dir/'nominal.omem'; self.assertEqual(proc(OMNI,'memory-pack',self.source('nominal'),'-o',omem).returncode,0)
        self.assertEqual(proc(OMNI,'memory-summary',omem).returncode,0)
        raw=bytearray(omem.read_bytes()); at=raw.find(b'sha256:')+10; raw[at]=ord('0') if raw[at]!=ord('0') else ord('1')
        tampered=self.dir/'tampered.omem'; tampered.write_bytes(bytes(raw))
        result=proc(OMNI,'memory-summary',tampered); self.assertEqual(result.returncode,2); self.assertIn(b'E_OSNMF',result.stderr)
        relabelled=self.dir/'relabelled.omem'; relabelled.write_bytes(omem.read_bytes().replace(b'OSM2',b'OSM9',1))
        result=proc(OMNI,'memory-summary',relabelled); self.assertEqual(result.returncode,2); self.assertIn(b'E_VERSION',result.stderr)

    def test_projection_carries_no_addresses_live_state_or_runtime_authority(self)->None:
        store=self.memory(self.source('atomic')).decode()
        for needle in ('5308416','0x510000','pointer','handle'):
            self.assertNotIn(needle,store,needle)                           # the atomic address in the source is not exported
        authorities={a for n in self.nuclei(self.memory(self.source('atomic'))) for a in n.get('authority',{}).values()}
        self.assertTrue(authorities<={'compiler-authoritative','developer-declared'},authorities)


X64_TOOLS=('qemu-system-x86_64','clang','ld','as','objcopy','objdump','nm')


@unittest.skipUnless(all(shutil.which(t) for t in X64_TOOLS),'needs qemu-system-x86_64 and clang/binutils')
class X64Harness(unittest.TestCase):
    """Shared harness (no tests of its own) for the x86-64 freestanding conformance classes. G1/G2 of OMNI-CORE-PRO-FOUNDATION-001 v1.3.3 (spec/TARGET_BAREMETAL_PROFILE_CANDIDATE.md, spec/ATOMICS_CANDIDATE_ST09.md).

    Omni source -> emit-llvm baremetal-x86_64 with the Core-owned minimal provider (tests/x64/rt.omni) -> clang -O2 -> flat payload ->
    test-owned PVH adapter (tests/x64/boot64.S, which performs the 32->64 transition; it is NOT an Omni capability) -> QEMU, one vCPU.
    Proves single-CPU native execution only; it says nothing about SMP ordering."""

    X64=ROOT/'tests'/'x64'
    CFLAGS=['--target=x86_64-unknown-none-elf','-ffreestanding','-fno-builtin','-fno-stack-protector','-fno-pic','-fno-pie','-mno-red-zone',
            '-mno-sse','-mno-sse2','-mno-mmx','-mno-80387','-O2','-ffunction-sections']
    EXPECTED_SINGLE=['41','41','42','42','100','100','100','4294967295','1','4294967301','4294967301','4294967300','4294967300','9','9','9','3735928559']
    CAPS='!{io.print,memory.raw,memory.atomic,port.io,cpu.control}'

    def setUp(self)->None:
        self.tmp=tempfile.TemporaryDirectory(prefix='omni-a83-x64-')
        self.dir=pathlib.Path(self.tmp.name)
        for f in self.X64.iterdir():
            if f.is_file():
                shutil.copy(f,self.dir/f.name)

    def tearDown(self)->None:
        self.tmp.cleanup()

    def program(self,body:str,caps:str=CAPS,name:str='prog.omni')->pathlib.Path:
        path=self.dir/name
        path.write_text('module t\nimport rt "rt.omni"\nfunc main() u32 '+caps+' {\n'+body+'  return rt.finish(0u32)\n}\n',encoding='utf-8')
        return path

    def emit(self,source:pathlib.Path,out:str='prog.ll',extra:tuple=())->subprocess.CompletedProcess:
        (self.dir/out).unlink(missing_ok=True)  # emit-llvm refuses to overwrite (E_EXISTS); a stale file must not mask a missing artifact
        return subprocess.run([str(OMNI),'emit-llvm',str(source),'--target-profile','baremetal-x86_64','--service-module','rt',
                               '--entry-section','.text.omni_entry',*extra,'-o',str(self.dir/out)],capture_output=True,cwd=self.dir,
                              env={**os.environ,'OMNI_HOME':str(ROOT)},timeout=60)

    def sh(self,*cmd:str,timeout:int=120)->subprocess.CompletedProcess:
        result=subprocess.run(list(cmd),capture_output=True,cwd=self.dir,timeout=timeout)
        self.assertEqual(result.returncode,0,(cmd,result.stderr[-600:]))
        return result

    # An `sse2` image (--target-isa sse2) is compiled with SSE2 enabled and its adapter enables x87/SSE before any Omni code runs.
    SSE_CFLAGS=['--target=x86_64-unknown-none-elf','-ffreestanding','-fno-builtin','-fno-stack-protector','-fno-pic','-fno-pie','-mno-red-zone',
                '-msse2','-mno-mmx','-O2','-ffunction-sections']

    def build(self,source:pathlib.Path,*,ap_main:bool=False,emit_args:tuple=(),sse:bool=False)->pathlib.Path:
        emitted=self.emit(source,extra=emit_args); self.assertEqual(emitted.returncode,0,emitted.stderr)
        self.sh('clang',*(self.SSE_CFLAGS if sse else self.CFLAGS),'-c','prog.ll','-o','prog.o')
        keep=['-u','omni.fn.t.ap_main'] if ap_main else []  # ap_main is called by the AP trampoline, not by Omni code: keep it past --gc-sections
        self.sh('ld','-m','elf_x86_64','-nostdlib','--gc-sections',*keep,'-T','payload.ld','prog.o','-o','payload.elf')
        self.sh('objcopy','-O','binary','payload.elf','payload.bin')
        entry='0'
        if ap_main:
            found=[l.split()[0] for l in self.sh('nm','payload.elf').stdout.decode().splitlines() if l.split()[-1:]==['omni.fn.t.ap_main']]
            self.assertEqual(len(found),1,found); entry='0x'+found[0]
        self.sh('as','--32','--defsym','AP_ENTRY='+entry,*(('--defsym','SSE=1') if sse else ()),'-I','.','boot64.S','-o','boot.o')
        self.sh('ld','-m','elf_i386','-nostdlib','-T','link32.ld','boot.o','-o','boot.elf')
        return self.dir/'boot.elf'

    def boot(self,elf:pathlib.Path,smp:int=1)->tuple[int,str]:
        accel=['-accel','tcg,thread=multi'] if smp>1 else []  # real host threads per vCPU: contention is genuinely parallel
        run=subprocess.run(['qemu-system-x86_64',*accel,'-smp',str(smp),'-kernel',str(elf),'-display','none','-serial','stdio','-no-reboot',
                            '-device','isa-debug-exit,iobase=0xf4,iosize=0x04','-m','64'],capture_output=True,timeout=120)
        return run.returncode,run.stdout.decode()

    @staticmethod
    def reachable(ir:str,entry:str='omni_boot_entry')->set[str]:
        funcs={m.group(1):set(re.findall(r'@([\w.$]+)',m.group(2)))-{m.group(1)}
               for m in re.finditer(r'^define [^\n@]*@([\w.$]+)\([^\n]*\{\n(.*?)^\}',ir,re.S|re.M)}
        seen:set[str]=set(); todo=[entry]
        while todo:
            f=todo.pop()
            if f in seen or f not in funcs:
                continue
            seen.add(f); todo.extend(funcs[f])
        return seen


class A83X64AtomicTests(X64Harness):
    """G1-G4: atomics natively on one and two vCPUs, the service-contract split, alignment faults and the image-load regression."""

    def test_every_atomic_form_executes_natively_on_one_vcpu(self)->None:
        elf=self.build(self.dir/'atomic_single.omni')
        rc,serial=self.boot(elf)
        self.assertEqual(serial.split('\n')[:-1],self.EXPECTED_SINGLE,serial)
        self.assertEqual(rc,1)  # isa-debug-exit value 0 -> status 1: rt.finish(0)
        machine=self.sh('objdump','-d','--no-show-raw-insn','-M','intel','payload.elf').stdout.decode()
        xchg=r'(?<![a-z])xchg\s+[DQ]WORD PTR'  # not the substring of cmpxchg, not the `xchg ax,ax` padding nop
        counts={n:len(re.findall(n,machine)) for n in (r'lock cmpxchg',r'lock xadd',r'mfence',xchg)}
        # four CAS (2x32, 2x64), three fetch_add, one mfence (only the seq_cst fence has an instruction; acquire/release/acq_rel are
        # compiler barriers on x86) and the two seq_cst stores as xchg to memory (the release store is a plain mov)
        self.assertEqual(counts,{r'lock cmpxchg':4,r'lock xadd':3,r'mfence':1,xchg:2})
        # Orders weaker than seq_cst have no distinct x86 instruction, so the contract is also checked on the emitted IR, in program order.
        ir=(self.dir/'prog.ll').read_text(encoding='utf-8')
        ops=[]
        for line in ir.splitlines():
            for key,name in (('load atomic volatile','load'),('store atomic volatile','store'),('atomicrmw volatile add','add'),('cmpxchg volatile','cas'),('fence ','fence')):
                if key in line and ('= ' in line or line.strip().startswith(('store','fence'))):
                    ops.append((name,tuple(re.findall(r'\b(monotonic|acquire|release|acq_rel|seq_cst)\b',line)))); break
        S,A,R,Q,M='seq_cst','acquire','release','acq_rel','monotonic'
        self.assertEqual(ops,[('store',(S,)),('load',(S,)),('add',(S,)),('load',(A,)),('cas',(S,S)),('load',(M,)),('cas',(S,S)),('load',(S,)),
                              ('store',(R,)),('add',(Q,)),('load',(S,)),('store',(S,)),('load',(S,)),('add',(S,)),('load',(A,)),('cas',(S,A)),
                              ('load',(M,)),('cas',(Q,A)),('load',(S,)),('fence',(S,)),('fence',(Q,)),('fence',(A,)),('fence',(R,))])
        self.assertEqual(self.sh('nm','-u','payload.elf').stdout,b'')  # no undefined references in the linked payload
        first=self.sh('nm','-n','payload.elf').stdout.decode().splitlines()[0]
        self.assertTrue(first.endswith(' T omni_boot_entry'),first)

    def test_evaluator_agrees_with_native_values_and_faults(self)->None:
        # Single-flow evaluator model: same values and the same fault class as the native image; it proves no inter-CPU ordering.
        env={**os.environ,'OMNI_HOME':str(ROOT)}
        # The evaluator reports prints only when the program ends normally (a cpu.halt via rt.finish ends in E_TARGET_HALT with the
        # output withheld), so the value comparison uses the same program ending in a plain return.
        text=(self.dir/'atomic_single.omni').read_text(encoding='utf-8')
        self.assertIn('return rt.finish(0u32)',text)
        (self.dir/'atomic_eval.omni').write_text(text.replace('return rt.finish(0u32)','return 0u32'),encoding='utf-8')
        ev=subprocess.run([str(OMNI),'eval',str(self.dir/'atomic_eval.omni')],capture_output=True,cwd=self.dir,env=env,timeout=60)
        self.assertEqual(ev.returncode,0,ev.stderr)
        self.assertEqual(ev.stdout.decode().split('\n')[:-1],self.EXPECTED_SINGLE,ev.stderr)
        halting=subprocess.run([str(OMNI),'eval',str(self.dir/'atomic_single.omni')],capture_output=True,cwd=self.dir,env=env,timeout=60)
        self.assertIn(b'E_TARGET_HALT',halting.stderr); self.assertIn(b'debug_exit=0',halting.stderr)
        for label,address in (('misaligned','5308417u64'),('null','0u64')):
            bad=self.program('  print(atomic.load32('+address+', 4u32))\n',name=f'evalbad_{label}.omni')
            ev=subprocess.run([str(OMNI),'eval',str(bad)],capture_output=True,cwd=self.dir,env=env,timeout=60)
            self.assertIn(b'E_ATOMIC_ALIGN',ev.stderr,label)
            self.assertEqual(ev.stdout,b'',label)

    def test_required_signatures_are_distinguished_from_reachable_services(self)->None:
        source=self.dir/'atomic_single.omni'
        self.assertEqual(self.emit(source).returncode,0)
        ir=(self.dir/'prog.ll').read_text(encoding='utf-8')
        provider={n[len('omni.fn.rt.'):] for n in re.findall(r'@(omni\.fn\.rt\.[\w]+)\(',ir)}
        required={'begin','tick','enter','leave','trap','buf_alloc','buf_len','buf_release','buf_read8','buf_read32','buf_read64','buf_write8',
                  'buf_write32','buf_write64','out32','out64','print_u32','print_u64','cast_int'}
        self.assertTrue(required<=provider,required-provider)
        used={n[len('omni.fn.rt.'):] for n in self.reachable(ir) if n.startswith('omni.fn.rt.')}
        self.assertEqual(used&{'begin','tick','enter','leave','trap','print_u64'},{'begin','tick','enter','leave','trap','print_u64'})
        # Declared by the contract, implemented as explicit UNSUPPORTED, and NOT reached by this executable.
        unreached={'buf_alloc','buf_len','buf_release','buf_read8','buf_read32','buf_read64','buf_write8','buf_write32','buf_write64','out32','out64','cast_int','unsupported'}
        self.assertEqual(used&unreached,set(),used&unreached)

    def test_missing_or_mistyped_service_signature_is_rejected_without_artifact(self)->None:
        source=self.dir/'atomic_single.omni'
        rt=(self.dir/'rt.omni').read_text(encoding='utf-8')
        for label,mutated in (('missing buf_len',rt.replace('pub func buf_len(h u64) u32 !{port.io,cpu.control} { return unsupported() }\n','')),
                              ('mistyped out64',rt.replace('pub func out64() u64 { return 0u64 }','pub func out64() u32 { return 0u32 }'))):
            self.assertNotEqual(mutated,rt,label)
            (self.dir/'rt.omni').write_text(mutated,encoding='utf-8')
            (self.dir/'prog.ll').unlink(missing_ok=True)
            result=self.emit(source)
            self.assertEqual(result.returncode,2,(label,result.stderr)); self.assertIn(b'E_SERVICE_BINDING',result.stderr,label)
            self.assertFalse((self.dir/'prog.ll').exists(),label)

    def test_misaligned_and_null_atomics_fault_with_trap_11_never_silently(self)->None:
        forms={'load32':'print(atomic.load32(A, 4u32))','store32':'let r u32 = atomic.store32(A, 1u32, 4u32)',
               'cas32':'print(atomic.cas32(A, 0u32, 1u32, 4u32, 4u32))','fetch_add32':'print(atomic.fetch_add32(A, 1u32, 4u32))',
               'load64':'print(atomic.load64(A, 4u32))','store64':'let r u32 = atomic.store64(A, 1u64, 4u32)',
               'cas64':'print(atomic.cas64(A, 0u64, 1u64, 4u32, 4u32))','fetch_add64':'print(atomic.fetch_add64(A, 1u64, 4u32))'}
        for name,template in forms.items():
            wide=name.endswith('64')
            aligned='5308424u64' if wide else '5308416u64'
            for label,address in (('control',aligned),('unaligned','5308420u64' if wide else '5308417u64'),('null','0u64')):
                source=self.program('  '+template.replace('A',address)+'\n',name=f'{name}_{label}.omni')
                rc,serial=self.boot(self.build(source))
                if label=='control':
                    self.assertEqual(rc,1,(name,label,serial))
                else:
                    self.assertEqual(serial,'TRAP 11\n',(name,label)); self.assertEqual(rc,151,(name,label))  # ((64+11)<<1)|1
        # an address that is only known at run time is checked too, not just constants folded by the compiler
        dynamic=self.program('  let seed u32 = raw.store64(5308432u64, 5308417u64)\n  let a u64 = raw.load64(5308432u64)\n  print(atomic.load32(a, 4u32))\n',name='dynamic.omni')
        rc,serial=self.boot(self.build(dynamic))
        self.assertEqual((serial,rc),('TRAP 11\n',151))

    def test_invalid_orders_ops_and_authority_are_rejected_before_any_artifact(self)->None:
        cases=[('load release','print(atomic.load32(5308416u64, 2u32))',b'E_ATOMIC_ORDER'),
               ('load order out of range','print(atomic.load32(5308416u64, 5u32))',b'E_ATOMIC_ORDER'),
               ('store acquire','let r u32 = atomic.store32(5308416u64, 1u32, 1u32)',b'E_ATOMIC_ORDER'),
               ('store acq_rel','let r u32 = atomic.store64(5308424u64, 1u64, 3u32)',b'E_ATOMIC_ORDER'),
               ('fetch_add out of range','print(atomic.fetch_add32(5308416u64, 1u32, 9u32))',b'E_ATOMIC_ORDER'),
               ('cas failure release','print(atomic.cas32(5308416u64, 0u32, 1u32, 4u32, 2u32))',b'E_ATOMIC_ORDER'),
               ('cas failure above success','print(atomic.cas32(5308416u64, 0u32, 1u32, 1u32, 4u32))',b'E_ATOMIC_ORDER'),
               ('cas failure acquire over relaxed','print(atomic.cas64(5308424u64, 0u64, 1u64, 0u32, 1u32))',b'E_ATOMIC_ORDER'),
               ('fence relaxed','let f u32 = atomic.fence(0u32)',b'E_ATOMIC_ORDER'),
               ('non-literal order','let o u32 = 4u32\n  print(atomic.load32(5308416u64, o))',b'E_ATOMIC_ORDER'),
               ('unknown op','print(atomic.xchg32(5308416u64, 1u32, 4u32))',b'E_ATOMIC_OP'),
               ('unsupported width','print(atomic.load16(5308416u64, 4u32))',b'E_ATOMIC_OP'),
               ('wrong arity','print(atomic.load32(5308416u64))',b'E_ARITY'),
               ('address not u64','print(atomic.load32(5308416u32, 4u32))',b'E_TYPE')]
        for label,body,code in cases:
            (self.dir/'prog.ll').unlink(missing_ok=True)
            result=self.emit(self.program('  '+body+'\n',name='neg.omni'))
            self.assertEqual(result.returncode,2,(label,result.stderr)); self.assertIn(code,result.stderr,(label,result.stderr))
            self.assertFalse((self.dir/'prog.ll').exists(),label)
        # memory.raw does not imply memory.atomic, and memory.atomic does not imply memory.raw
        no_atomic=self.program('  print(atomic.load32(5308416u64, 4u32))\n',caps='!{io.print,memory.raw,port.io,cpu.control}',name='noatomic.omni')
        result=self.emit(no_atomic); self.assertEqual(result.returncode,2); self.assertIn(b'E_CAPABILITY',result.stderr)
        no_raw=self.program('  print(raw.load32(5308416u64))\n',caps='!{io.print,memory.atomic,port.io,cpu.control}',name='noraw.omni')
        result=self.emit(no_raw); self.assertEqual(result.returncode,2); self.assertIn(b'E_CAPABILITY',result.stderr)
        # hosted compilation refuses the primitives and leaves nothing behind
        hosted=subprocess.run([str(OMNI),'build',str(self.dir/'atomic_single.omni'),'-o',str(self.dir/'hosted'),'--cache-dir',str(self.dir/'cache')],
                              capture_output=True,cwd=self.dir,env={**os.environ,'OMNI_HOME':str(ROOT)},timeout=60)
        self.assertEqual(hosted.returncode,2,hosted.stderr); self.assertIn(b'E_TARGET_PROFILE',hosted.stderr)
        self.assertFalse((self.dir/'hosted').exists())

    def test_reaching_an_unsupported_service_fails_explicitly(self)->None:
        body=('  let r Result<Resource<Buffer>,u32> = buffer.alloc(8u32)\n  match r {\n    Ok(b) { print(buffer.len(borrow(b))) }\n    Err(code) { print(code) }\n  }\n')
        source=self.program(body,caps='!{io.print,memory.read,memory.write,port.io,cpu.control}',name='buffers.omni')
        ir_proc=self.emit(source); self.assertEqual(ir_proc.returncode,0,ir_proc.stderr)
        used={n[len('omni.fn.rt.'):] for n in self.reachable((self.dir/'prog.ll').read_text(encoding='utf-8')) if n.startswith('omni.fn.rt.')}
        self.assertIn('buf_alloc',used)  # now reachable: the contract signature is exercised ...
        rc,serial=self.boot(self.build(source))
        self.assertEqual((serial,rc),('UNS\n',253))  # ... and the provider says so instead of pretending: exit value 126 -> status 253

    def test_image_is_loaded_where_it_was_linked(self)->None:
        # Regression for a measured defect: an AT() in the adapter linker script shifted the payload's load address to 0x2f9000 while
        # its link address stayed 0x200000. The BSP still "worked" by sliding over a megabyte of zero bytes into the real code, and the
        # AP called an empty address. Two independent checks: the program headers, and the guest reading its own memory back.
        elf=self.build(self.dir/'loadcheck.omni',ap_main=False)
        headers=self.sh('readelf','-lW',str(elf)).stdout.decode()
        loads=[tuple(int(x,16) for x in m.groups()) for m in re.finditer(r'LOAD\s+0x[0-9a-f]+\s+0x([0-9a-f]+)\s+0x([0-9a-f]+)\s',headers)]
        self.assertIn((0x100000,0x100000),loads,loads)   # adapter: link == load
        self.assertIn((0x200000,0x200000),loads,loads)   # Omni payload: link == load
        self.assertIn((0x8000,0x120000),loads,loads)     # AP trampoline: runs at 0x8000, loaded above the page tables, copied by the adapter
        payload=(self.dir/'payload.bin').read_bytes()
        self.sh('objcopy','-O','binary','-j','.aptramp',str(elf),'aptramp.bin')
        tramp=(self.dir/'aptramp.bin').read_bytes()
        rc,serial=self.boot(elf)
        words=[int(x) for x in serial.split('\n')[:-1]]
        self.assertEqual(rc,1,serial)
        self.assertEqual(words,[int.from_bytes(payload[i:i+4],'little') for i in (0,4,8)]+[int.from_bytes(tramp[i:i+4],'little') for i in (0,4)],serial)
        self.assertNotEqual(words[0],0)

    def test_two_vcpus_execute_omni_and_atomic_increments_are_never_lost(self)->None:
        # G4. The application processor is woken by the test-owned adapter (INIT/SIPI sent from Omni on the BSP); ap_main is Omni code.
        n=200000
        elf=self.build(self.dir/'smp_counter.omni',ap_main=True)
        lost=[]
        for attempt in range(3):
            rc,serial=self.boot(elf,smp=2)
            lines=serial.split('\n')[:-1]
            self.assertEqual((rc,len(lines)),(1,8),(attempt,rc,serial))
            ap_id,atomic,plain,ack,bsp_bad,ap_bad,ap_slot,ap_spent=[int(x) for x in lines]
            self.assertEqual(ap_id,101,serial)    # the AP's own Omni code wrote apic_id + 100: CPU 1 really executed it
            self.assertEqual(atomic,2*n,serial)   # fetch_add from two CPUs on one cell: nothing lost, nothing duplicated
            self.assertEqual(ack,4661,serial)     # release/acquire hand-off of 4660 answered with 4660 + 1
            self.assertTrue(0<plain<=2*n,serial)
            self.assertEqual((bsp_bad,ap_bad),(0,0),serial)   # both CPUs recursed concurrently on their own stacks and every sum was right
            self.assertEqual((ap_slot,ap_spent),(1,1),serial) # the provider's accounting slot of CPU 1 is its own: initialized and spent apart
            lost.append(2*n-plain)
        # Instrument validity: a relaxed load + relaxed store pair (NOT a read-modify-write) must lose updates in at least one run,
        # otherwise this harness could not tell atomics from plain accesses and the equality above would prove nothing.
        self.assertTrue(any(l>0 for l in lost),lost)
        machine=self.sh('objdump','-d','--no-show-raw-insn','-M','intel','payload.elf').stdout.decode()
        # an unused fetch_add result is legitimately emitted as a locked add/inc rather than xadd; any of them is the atomic RMW
        self.assertRegex(machine,r'lock (xadd|add|inc)\b')
        # x86 (TSO) cannot show the difference between a release store and a relaxed one, so the publication protocol is checked on the
        # emitted IR: five release stores (AP up, GO, AP done, FLAG, ACK), the relaxed ones belong to the plain-counter control.
        ir=(self.dir/'prog.ll').read_text(encoding='utf-8')
        releases=[l for l in ir.splitlines() if 'store atomic volatile i32' in l and l.rstrip().endswith('release, align 4')]
        self.assertEqual(len(releases),5,releases)
        acquires=[l for l in ir.splitlines() if 'load atomic volatile i32' in l and 'acquire, align 4' in l]
        self.assertGreaterEqual(len(acquires),2,acquires)    # wait_flag spins with acquire loads

    def test_without_the_second_cpu_the_smp_program_fails_deterministically(self)->None:
        # -smp 1 must not look like success: the AP never answers, the wait is bounded and the program reports it explicitly.
        elf=self.build(self.dir/'smp_counter.omni',ap_main=True)
        self.assertEqual(self.boot(elf,smp=1),(5,'999\n'))  # finish(2) -> status 5


class A83X64ExceptionTests(X64Harness):
    """First interrupt/exception slice of CP-09/CP-12 (TARGET_BAREMETAL_PROFILE_CANDIDATE.md, exception sections). Omni builds the IDT and the
    handler is ordinary Omni code; the stubs and the iretq tail are emitted by the compiler. Single vCPU; no interrupts from devices yet."""

    RESUME=('--exception-handler','t.on_exception','--exception-resume')
    TERMINAL=('--exception-handler','t.on_exception')

    def layout(self)->dict:
        sections={}
        for m in re.finditer(r'\]\s+(\S+)\s+PROGBITS\s+([0-9a-f]+)\s+[0-9a-f]+\s+([0-9a-f]+)',self.sh('readelf','-SW','payload.elf').stdout.decode()):
            sections[m.group(1)]=(int(m.group(2),16),int(m.group(3),16))
        return sections

    def test_page_fault_is_handled_by_omni_code_and_the_instruction_is_reexecuted(self)->None:
        elf=self.build(self.dir/'exc_resume.omni',emit_args=self.RESUME)
        rc,serial=self.boot(elf)
        # 42 = the value read after the handler mapped the page; log: one exception, vector 14 (#PF), error 0 (not-present read), CR2
        self.assertEqual((rc,serial.split('\n')[:-1]),(1,['42','1','14','0','2147483648','8']),serial)
        machine=self.sh('objdump','-d','--no-show-raw-insn','-M','intel','payload.elf').stdout.decode()
        self.assertIn('iretq',machine)
        sections=self.layout()
        self.assertEqual(sections['.isr'][0],0x210000)   # where idt.omni points the gates
        self.assertTrue(all(a+s<=0x210000 for n,(a,s) in sections.items() if n!='.isr'),sections)  # nothing overlaps the stub table

    def test_terminal_mode_reports_the_fault_and_never_resumes(self)->None:
        elf=self.build(self.dir/'exc_gp.omni',emit_args=self.TERMINAL)
        rc,serial=self.boot(elf)
        self.assertEqual((rc,serial),(227,'13\n0\n'))  # #GP(0) from a non-canonical load; handler ends the guest with value 113 -> 227
        machine=self.sh('objdump','-d','--no-show-raw-insn','-M','intel','payload.elf').stdout.decode()
        self.assertNotIn('iretq',machine)               # the terminal tail has no resume path

    def test_without_an_idt_the_same_fault_ends_the_guest_instead_of_resuming(self)->None:
        # Control: remove the IDT installation and the faulting access cannot be recovered, so the "42" above comes from the handler.
        text=(self.dir/'exc_resume.omni').read_text(encoding='utf-8').replace('  let installed u32 = idt.install()\n','')
        self.assertNotIn('idt.install',text)
        (self.dir/'exc_noidt.omni').write_text(text,encoding='utf-8')
        elf=self.build(self.dir/'exc_noidt.omni',emit_args=self.RESUME)
        rc,serial=self.boot(elf)
        self.assertNotEqual((rc,serial.split('\n')[0]),(1,'42'),(rc,serial))

    def test_exception_options_are_validated_before_any_artifact(self)->None:
        (self.dir/'badsig.omni').write_text('module t\nimport rt "rt.omni"\nfunc on_exception() u32 { return 0u32 }\nfunc main() u32 !{port.io,cpu.control} { return rt.finish(0u32) }\n',encoding='utf-8')
        (self.dir/'badres.omni').write_text('module t\nimport rt "rt.omni"\nfunc on_exception(frame u64) u64 { return 0u64 }\nfunc main() u32 !{port.io,cpu.control} { return rt.finish(0u32) }\n',encoding='utf-8')
        cases=[('resume without handler','exc_resume.omni',('--exception-resume',),b'E_CLI'),
               ('handler does not exist','exc_resume.omni',('--exception-handler','t.nothere'),b'E_EXCEPTION_HANDLER'),
               ('handler without module','exc_resume.omni',('--exception-handler','on_exception'),b'E_EXCEPTION_HANDLER'),
               ('handler wrong arity','badsig.omni',self.TERMINAL,b'E_EXCEPTION_HANDLER'),
               ('handler wrong result','badres.omni',self.TERMINAL,b'E_EXCEPTION_HANDLER')]
        for label,program,extra,code in cases:
            result=self.emit(self.dir/program,extra=extra)
            self.assertEqual(result.returncode,2,(label,result.stderr)); self.assertIn(code,result.stderr,(label,result.stderr))
            self.assertFalse((self.dir/'prog.ll').exists(),label)
        # the i386 boot profile has no exception stubs
        result=subprocess.run([str(OMNI),'emit-llvm',str(self.dir/'exc_resume.omni'),'--target-profile','baremetal-i386-boot','--service-module','rt',
                               '--entry-address','1048576','--exception-handler','t.on_exception','-o',str(self.dir/'i386.ll')],capture_output=True,cwd=self.dir,
                              env={**os.environ,'OMNI_HOME':str(ROOT)},timeout=60)
        self.assertEqual(result.returncode,2,result.stderr); self.assertIn(b'E_TARGET_PROFILE',result.stderr)
        self.assertIn(b'--exception-handler requiere el perfil baremetal-x86_64',result.stderr)   # its own refusal, not the provider's
        self.assertFalse((self.dir/'i386.ll').exists())


class A83X64InterruptTests(X64Harness):
    """Asynchronous interrupts (CP-12 slice; TARGET_BAREMETAL_PROFILE_CANDIDATE.md K2). A periodic local-APIC timer interrupts a computation
    that runs with interrupts enabled; the resumable tail must restore the interrupted state exactly. Single vCPU, one vector, no scheduler."""

    IRQ=('--exception-handler','t.on_exception','--exception-resume','--isr-count','33')

    def test_timer_interrupts_do_not_disturb_the_interrupted_computation(self)->None:
        elf=self.build(self.dir/'irq_timer.omni',emit_args=self.IRQ)
        rc,serial=self.boot(elf)
        lines=serial.split('\n')[:-1]
        self.assertEqual((rc,len(lines)),(1,2),serial)
        self.assertEqual(int(lines[0]),3000000*2999999//2,serial)    # exact sum although the loop was interrupted
        self.assertGreaterEqual(int(lines[1]),2,serial)              # several asynchronous interrupts were taken and returned from

    def test_an_unmasked_legacy_pic_vector_is_reported_instead_of_ignored(self)->None:
        # Control for the setup step: without masking the 8259 the PIT's IRQ0 arrives as vector 8; the handler reports it (113-like exit),
        # it is never silently dropped or mistaken for the timer.
        text=(self.dir/'irq_timer.omni').read_text(encoding='utf-8')
        for needle in ('  let pic1 u32 = port.out8(33u32, 255u32)\n','  let pic2 u32 = port.out8(161u32, 255u32)\n'):
            self.assertIn(needle,text); text=text.replace(needle,'')
        (self.dir/'irq_nopic.omni').write_text(text,encoding='utf-8')
        rc,serial=self.boot(self.build(self.dir/'irq_nopic.omni',emit_args=self.IRQ))
        self.assertEqual(rc,(108<<1)|1,(rc,serial))                    # finish(100 + vector 8)


class A83X64Ring3Tests(X64Harness):
    """Privilege transitions (CP-12 slice; TARGET_BAREMETAL_PROFILE_CANDIDATE.md K1). Omni builds GDT, TSS and IDT, flips the U bit of the
    payload page and runs Omni code at CPL3. Single vCPU. The ring-0 side never trusts the user: any exception from CPL3 ends the session."""

    RING3=('--ring3-support','--thread-entry','rt.user_main','--exception-handler','t.on_exception','--exception-resume','--isr-extra-vector','48')

    def test_user_code_requests_a_service_is_isolated_from_supervisor_memory_and_cannot_execute_privileged_instructions(self)->None:
        elf=self.build(self.dir/'ring3.omni',emit_args=self.RING3)
        rc,serial=self.boot(elf)
        # session 1: service call through the DPL3 gate (vector 48, cs 0x23 = 35) adds 40 + 2 and ends the session with 42
        # session 2: a read of a supervisor-only page is #PF (14) with error code 5 = present | user
        # session 3: `cli` at CPL3 is #GP (13); ring 0 reports 1000 + vector for both faults
        self.assertEqual((rc,serial.split('\n')[:-1]),(1,['42','48','35','1014','14','5','1013','13']),serial)
        machine=self.sh('objdump','-d','--no-show-raw-insn','-M','intel','payload.elf').stdout.decode()
        self.assertIn('int    0x30',machine)       # cpu.trap3(48, ...)
        self.assertIn('iretq',machine)

    def test_user_code_carries_no_accounting_hook_that_would_touch_supervisor_memory(self)->None:
        self.assertEqual(self.emit(self.dir/'ring3.omni',extra=self.RING3).returncode,0)
        ir=(self.dir/'prog.ll').read_text(encoding='utf-8')
        body=re.search(r'^define [^\n@]*@omni\.fn\.rt\.user_main\([^\n]*\{\n(.*?)^\}',ir,re.S|re.M)
        self.assertIsNotNone(body)
        for hook in ('omni_tick','omni_enter','omni_leave','omni.fn.rt.tick','omni.fn.rt.enter','omni.fn.rt.leave'):
            self.assertNotIn(hook,body.group(1),hook)

    def test_ring3_options_and_privileged_operations_are_validated_before_any_artifact(self)->None:
        def program(name:str,caps:str,body:str)->pathlib.Path:
            path=self.dir/f'{name}.omni'; path.write_text('module t\nimport rt "rt.omni"\nfunc main() u32 '+caps+' {\n'+body+'  return rt.finish(0u32)\n}\n',encoding='utf-8'); return path
        low=program('lowvec','!{cpu.syscall,port.io,cpu.control}','  let r u64 = cpu.trap3(31u32, 1u64, 2u64, 3u64)\n')
        high=program('highvec','!{cpu.syscall,port.io,cpu.control}','  let r u64 = cpu.trap3(256u32, 1u64, 2u64, 3u64)\n')
        nocap=program('nocap','!{port.io,cpu.control}','  let r u64 = cpu.trap3(48u32, 1u64, 2u64, 3u64)\n')
        enter=program('enter','!{port.io,cpu.control}','  let r u64 = cpu.enter_ring3(1u64, 2u64, 3u64)\n')
        cases=[('trap3 vector below 32',low,(),b'E_TARGET_PROFILE'),('trap3 vector above 255',high,(),b'E_TARGET_PROFILE'),
               ('trap3 without cpu.syscall',nocap,(),b'E_CAPABILITY'),('enter_ring3 without --ring3-support',enter,(),b'E_TARGET_PROFILE'),
               ('isr-extra-vector below 32',enter,('--isr-extra-vector','10'),b'E_CLI')]
        for label,path,extra,code in cases:
            result=self.emit(path,extra=extra)
            self.assertEqual(result.returncode,2,(label,result.stderr)); self.assertIn(code,result.stderr,(label,result.stderr))
            self.assertFalse((self.dir/'prog.ll').exists(),label)
        self.assertEqual(self.emit(enter,extra=('--ring3-support',)).returncode,0)   # the same program is fine once the option is given
        result=subprocess.run([str(OMNI),'emit-llvm',str(enter),'--target-profile','baremetal-i386-boot','--service-module','rt','--entry-address','1048576',
                               '--ring3-support','-o',str(self.dir/'i386.ll')],capture_output=True,cwd=self.dir,env={**os.environ,'OMNI_HOME':str(ROOT)},timeout=60)
        self.assertEqual(result.returncode,2,result.stderr); self.assertIn(b'E_TARGET_PROFILE',result.stderr)
        self.assertIn(b'--ring3-support requiere el perfil baremetal-x86_64',result.stderr)
        self.assertFalse((self.dir/'i386.ll').exists())


class A83X64FpuTests(X64Harness):
    """CP-10 (spec/FPU_SSE_STATE_CANDIDATE.md): the freestanding x86-64 profile has an explicit ISA mode. `gpr` (default) rejects floating
    point; `sse2` allows it, honours the dynamic FP environment (constrained intrinsics) and offers the state primitives. Single vCPU, eager
    state preservation, QEMU TCG only; no XSAVE/AVX, no lazy switching."""

    SSE=('--target-isa','sse2')
    IRQ=('--exception-handler','t.on_exception','--exception-resume','--isr-count','33','--target-isa','sse2')

    def fp_program(self,name:str,body:str)->pathlib.Path:
        path=self.dir/f'{name}.omni'
        path.write_text('module t\nimport rt "rt.omni"\nfunc main() u32 !{io.print,memory.raw,port.io,cpu.control} {\n'+body+'  return rt.finish(0u32)\n}\n',encoding='utf-8')
        return path

    def lines(self,serial:str)->list[str]:
        return serial.split('\n')[:-1]

    def test_state_primitives_and_dynamic_rounding_are_observable_and_ordered(self)->None:
        elf=self.build(self.dir/'fpu_basic.omni',emit_args=self.SSE,sse=True)
        rc,serial=self.boot(elf)
        # MXCSR default; (1/3)*3 vs 1.0 under nearest / toward zero / up; fxsave -> change -> fxrstor brings the saved mode back
        self.assertEqual((rc,self.lines(serial)),(1,['8064','0','1','1','32640','24448']),serial)
        machine=self.sh('objdump','-d','--no-show-raw-insn','-M','intel','payload.elf').stdout.decode()
        for needle in ('fxsave64','fxrstor64','ldmxcsr','stmxcsr'):
            self.assertIn(needle,machine,needle)
        self.assertGreaterEqual(machine.count('divsd'),3)   # the three divisions were NOT merged across the MXCSR writes
        ir=(self.dir/'prog.ll').read_text(encoding='utf-8')
        self.assertIn('llvm.experimental.constrained.fdiv.f64',ir)
        self.assertIn('strictfp',ir)

    def test_two_threads_keep_their_own_fp_control_state_across_cooperative_switches(self)->None:
        elf=self.build(self.dir/'fpu_ctx.omni',emit_args=self.SSE+('--thread-entry','t.worker'),sse=True)
        rc,serial=self.boot(elf)
        # thread 1 (toward zero) and thread 2 (up): 2000 correct roundings and 2000 intact MXCSR modes each; main's own mode is back at the end
        self.assertEqual((rc,self.lines(serial)),(1,['2000','2000','2000','2000','8064','8064','1']),serial)   # 8064 = 0x1F80: each new context starts from the clean image

    def test_without_the_schedulers_save_and_restore_the_threads_leak_their_mode(self)->None:
        text=(self.dir/'fpu_ctx.omni').read_text(encoding='utf-8')
        for needle in ('    let i1 u32 = cpu.fxrstor(5509120u64)\n','    let o1 u32 = cpu.fxsave(5509120u64)\n','    let i2 u32 = cpu.fxrstor(5509632u64)\n','    let o2 u32 = cpu.fxsave(5509632u64)\n'):
            self.assertIn(needle,text); text=text.replace(needle,'')
        (self.dir/'fpu_ctx_leaky.omni').write_text(text,encoding='utf-8')
        elf=self.build(self.dir/'fpu_ctx_leaky.omni',emit_args=self.SSE+('--thread-entry','t.worker'),sse=True)
        rc,serial=self.boot(elf)
        values=[int(x) for x in self.lines(serial)[:4]]
        self.assertNotEqual(values,[2000,2000,2000,2000],serial)    # the control proves the 2000s above come from the state travelling with the thread

    def test_an_interrupt_handler_that_uses_floating_point_leaves_the_interrupted_sum_exact_only_with_save_fpu(self)->None:
        elf=self.build(self.dir/'fpu_irq.omni',emit_args=self.IRQ+('--exception-save-fpu',),sse=True)
        rc,serial=self.boot(elf)
        lines=self.lines(serial)
        self.assertEqual((rc,lines[0]),(1,'1'),serial)                 # the 2,000,000-term sum is exact
        self.assertGreaterEqual(int(lines[1]),2,serial)                # across several asynchronous interrupts
        # F7 (no `and $-16` before fxsave64) is EQUIVALENT, not a test gap: the CPU aligns rsp to 16 on every delivery, every stub pushes exactly
        # [error-or-0][vector] and the tail pushes 9 registers, so rsp is 16-aligned at the tail for error-code and no-error-code vectors alike.
        # The handler's frame argument (= rsp + 72) is therefore 8 mod 16 on the timer path here and on the #PF path in the exception test.
        self.assertEqual(lines[2],'8',serial)
        machine=self.sh('objdump','-d','--no-show-raw-insn','-M','intel','payload.elf').stdout.decode()
        self.assertIn('fxsave64',machine); self.assertIn('fxrstor64',machine)
        elf=self.build(self.dir/'fpu_irq.omni',emit_args=self.IRQ,sse=True)   # same program, option removed
        rc,serial=self.boot(elf)
        self.assertEqual((rc,self.lines(serial)[0]),(1,'0'),serial)    # the handler corrupted the interrupted computation

    def test_floating_point_and_state_primitives_are_rejected_in_the_default_gpr_image(self)->None:
        result=self.emit(self.dir/'fpu_basic.omni')
        self.assertEqual(result.returncode,2,result.stderr); self.assertIn(b'E_TARGET_PROFILE',result.stderr); self.assertIn(b'sse2',result.stderr)
        self.assertFalse((self.dir/'prog.ll').exists())
        for name,body in (('fxsave','  let s u32 = cpu.fxsave(5374976u64)\n'),('fxrstor','  let s u32 = cpu.fxrstor(5374976u64)\n'),
                          ('read_mxcsr','  let s u32 = cpu.read_mxcsr()\n'),('write_mxcsr','  let s u32 = cpu.write_mxcsr(8064u32)\n'),('fninit','  let s u32 = cpu.fninit()\n')):
            result=self.emit(self.fp_program(name,body))
            self.assertEqual(result.returncode,2,(name,result.stderr)); self.assertIn(b'E_TARGET_PROFILE',result.stderr,name); self.assertIn(b'--target-isa sse2',result.stderr,name)
            self.assertFalse((self.dir/'prog.ll').exists(),name)
        # floating-point TYPES are refused by themselves (no state primitive involved): a gpr image never touches an XMM register
        for name,body in (('f64_local','  let f f64 = f64(raw.load32(5373952u64))\n  let g f64 = f * f\n'),
                          ('f32_local','  let f f32 = f32(raw.load32(5373952u64))\n  let g f32 = f + f\n')):
            result=self.emit(self.fp_program(name,body))
            self.assertEqual(result.returncode,2,(name,result.stderr)); self.assertIn(b'E_TARGET_PROFILE',result.stderr,name); self.assertIn(b'f32/f64',result.stderr,name)
            self.assertFalse((self.dir/'prog.ll').exists(),name)
        # services the profile does not define are named instead of failing at link time
        for name,body in (('float_to_int','  let f f64 = f64(raw.load32(5373952u64))\n  let n u32 = u32(f)\n'),('print_float','  let f f64 = f64(raw.load32(5373952u64))\n  print(f)\n')):
            result=self.emit(self.fp_program(name,body),extra=self.SSE)
            self.assertEqual(result.returncode,2,(name,result.stderr)); self.assertIn(b'E_TARGET_PROFILE',result.stderr,name)
            self.assertFalse((self.dir/'prog.ll').exists(),name)

    def test_misaligned_null_and_invalid_state_images_trap_with_code_12(self)->None:
        clean='  let fcw u32 = raw.store32(5374976u64, 895u32)\n  let mx u32 = raw.store32(5374976u64 + 24u64, 8064u32)\n'
        cases=[('misaligned_save','  let s u32 = cpu.fxsave(5374977u64)\n'),('null_save','  let s u32 = cpu.fxsave(0u64)\n'),
               ('misaligned_restore',clean+'  let s u32 = cpu.fxrstor(5374984u64)\n'),
               ('reserved_bits_in_image',clean+'  let bad u32 = raw.store32(5374976u64 + 24u64, 4294967295u32)\n  let s u32 = cpu.fxrstor(5374976u64)\n'),
               ('reserved_bits_in_write','  let s u32 = cpu.write_mxcsr(4294967295u32)\n'),
               ('bit_6_daz_is_outside_the_default_mask','  let s u32 = cpu.write_mxcsr(8128u32)\n'),   # 0x1FC0: MXCSR_MASK 0 means 0xFFBF, bit 6 excluded
               ('bit_16_reserved','  let s u32 = cpu.write_mxcsr(73600u32)\n')]                  # 0x11F80
        for name,body in cases:
            rc,serial=self.boot(self.build(self.fp_program(name,body),emit_args=self.SSE,sse=True))
            self.assertEqual((rc,serial),(153,'TRAP 12\n'),(name,rc,serial))    # trap code 12 -> exit value 64 + 12 -> status ((76 << 1) | 1)
        # the whole mask 0xFFBF itself is accepted, so the rejections above are about the reserved bits and not about writing MXCSR at all
        ok=self.fp_program('accepts','  let a u32 = cpu.write_mxcsr(8064u32)\n  let b u32 = cpu.write_mxcsr(65471u32)\n  let c u32 = cpu.write_mxcsr(8064u32)\n  print(bit.and(cpu.read_mxcsr(), 65472u32))\n')
        rc,serial=self.boot(self.build(ok,emit_args=self.SSE,sse=True))
        self.assertEqual((rc,serial),(1,'8064\n'),(rc,serial))

    def test_isa_and_save_fpu_options_are_validated_before_any_artifact(self)->None:
        base=self.fp_program('plain','')
        cases=[('unknown isa',('--target-isa','avx'),b'E_CLI'),
               ('save-fpu without resume',('--target-isa','sse2','--exception-save-fpu'),b'E_CLI'),
               ('save-fpu without sse2',('--exception-handler','t.nothere','--exception-resume','--exception-save-fpu'),b'E_TARGET_PROFILE')]
        for label,extra,code in cases:
            result=self.emit(base,extra=extra)
            self.assertEqual(result.returncode,2,(label,result.stderr)); self.assertIn(code,result.stderr,(label,result.stderr))
            self.assertFalse((self.dir/'prog.ll').exists(),label)
        for label,args in (('isa on the i386 boot profile',('--target-profile','baremetal-i386-boot','--service-module','rt','--entry-address','1048576','--target-isa','sse2')),
                           ('isa without a profile',('--target-isa','sse2'))):
            result=subprocess.run([str(OMNI),'emit-llvm',str(base),*args,'-o',str(self.dir/'x.ll')],capture_output=True,cwd=self.dir,
                                  env={**os.environ,'OMNI_HOME':str(ROOT)},timeout=60)
            self.assertEqual(result.returncode,2,(label,result.stderr)); self.assertTrue(b'E_TARGET_PROFILE' in result.stderr or b'E_CLI' in result.stderr,(label,result.stderr))
            if 'i386' in label: self.assertIn(b'requieren el perfil baremetal-x86_64',result.stderr,(label,result.stderr))
            self.assertFalse((self.dir/'x.ll').exists(),label)


class A83X64GuardTests(X64Harness):
    """CP-14 first slice: interrupt guards and spinlocks whose guards are nominal affine resources (tests/x64/irq.omni, spin.omni), mutual
    exclusion on two vCPUs, and the reason acquisition disables interrupts. Not claimed: no-migration, quiescence, fairness, priority."""

    IRQ=('--exception-handler','t.on_exception','--exception-resume','--isr-count','33')

    def lines(self,serial:str)->list[str]:
        return serial.split('\n')[:-1]

    def test_irq_guard_restores_the_state_it_found_never_enables_unconditionally_and_nests(self)->None:
        rc,serial=self.boot(self.build(self.dir/'guard_irq.omni'))
        # IF is bit 9 (512). enabled -> guard -> restore: 0 inside, 512 after; disabled -> guard -> restore stays 0; nested: 0 then 512
        self.assertEqual((rc,self.lines(serial)),(1,['0','512','0','0','512']),serial)

    def test_lock_handle_keeps_address_and_interrupt_state_for_every_64_bit_address(self)->None:
        # DT review: the handle used to pack the interrupt state in bit 63 of the address, which loses higher-half addresses. The state now
        # travels in bit 0 (a lock cell is 4-byte aligned), so no address bit is spent.
        rc,serial=self.boot(self.build(self.dir/'spin_pack.omni'))
        self.assertEqual((rc,self.lines(serial)),(1,['20','1','0']),serial)       # 10 (address, flags) pairs x 2 checks; IF read from bit 9 only
        # a misaligned cell is refused before the lock is taken (trap 11 from the first compare-and-swap), so the bit-0 encoding can never be ambiguous
        head='module t\nimport rt "rt.omni"\nimport spin "spin.omni"\nfunc main() u32 !{memory.atomic,port.io,cpu.control} {\n'
        (self.dir/'lock_misaligned.omni').write_text(head+'  let g = spin.acquire(5309441u64, 100u32)\n  let r u32 = spin.release(move(g))\n  return rt.finish(0u32)\n}\n',encoding='utf-8')
        rc,serial=self.boot(self.build(self.dir/'lock_misaligned.omni'))
        self.assertEqual((rc,serial),((75<<1)|1,'TRAP 11\n'),serial)

    def test_spinlock_gives_mutual_exclusion_between_two_vcpus(self)->None:
        elf=self.build(self.dir/'lock_smp.omni',ap_main=True)
        lost=[]
        for attempt in range(2):
            rc,serial=self.boot(elf,smp=2)
            values=[int(x) for x in self.lines(serial)]
            self.assertEqual((rc,len(values)),(1,4),(attempt,rc,serial))
            ap_id,locked,unlocked,lock_word=values
            self.assertEqual(ap_id,101,serial)         # CPU 1 ran Omni code
            self.assertEqual(locked,200000,serial)     # 2 x 100000 relaxed load+store pairs, exact under the lock
            self.assertEqual(lock_word,0,serial)       # and the lock is free at the end
            lost.append(200000-unlocked)
        self.assertTrue(any(l>0 for l in lost),lost)   # the same loop without the lock loses updates: the harness can tell the difference
        # x86 cannot show a missing acquire/release, so the lock's ordering is checked on the emitted IR: the CAS that takes the lock is
        # acq_rel (failure: acquire) and the store that frees it is a release store of 0.
        ir=(self.dir/'prog.ll').read_text(encoding='utf-8')
        self.assertRegex(ir,r'cmpxchg volatile ptr %t\d+, i32 0, i32 1 acq_rel acquire, align 4')
        cas=re.findall(r'cmpxchg volatile[^\n]*',ir)
        self.assertGreaterEqual(len(cas),2,cas)                  # acquire and acquire_noirq are both lowered; EVERY compare-and-swap of the library is acq_rel
        for line in cas: self.assertIn('acq_rel acquire',line,line)
        self.assertRegex(ir,r'store atomic volatile i32 0, ptr %t\d+ release, align 4')

    def test_lock_with_interrupts_disabled_is_exact_and_without_it_the_handler_deadlocks(self)->None:
        rc,serial=self.boot(self.build(self.dir/'lock_irq.omni',emit_args=self.IRQ))
        total,interrupts,lock_word,restored,leaked=[int(x) for x in self.lines(serial)]
        self.assertEqual(rc,1,serial)
        self.assertGreaterEqual(interrupts,2,serial)
        self.assertEqual(restored,1,serial)        # the guard gave back the enabled state it found (a few interrupts alone do not show that)
        self.assertEqual(leaked,0,serial)          # and a lock taken without touching interrupts inside a handler left them off
        self.assertEqual(total-interrupts,100000,serial)   # main's 100000 critical sections plus one per interrupt: never interleaved
        self.assertEqual(lock_word,0,serial)
        text=(self.dir/'lock_irq.omni').read_text(encoding='utf-8')
        needle='    let g = spin.acquire(5309440u64, 2000000u32)\n    let v u32 = atomic.load32(5309504u64, 0u32)\n    let s u32 = atomic.store32(5309504u64, v + 1u32, 0u32)\n    let r u32 = spin.release(move(g))\n  }\n  let fl'
        self.assertIn(needle,text)
        (self.dir/'lock_irq_noirq.omni').write_text(text.replace(needle,needle.replace('spin.acquire(','spin.acquire_noirq(')),encoding='utf-8')
        rc,serial=self.boot(self.build(self.dir/'lock_irq_noirq.omni',emit_args=self.IRQ))
        self.assertEqual(rc,(95<<1)|1,(rc,serial))          # an interrupt landed inside the critical section: bounded spin -> reported deadlock

    def test_the_compiler_enforces_the_guard_obligations_and_section_restrictions(self)->None:
        head='module t\nimport rt "rt.omni"\nimport spin "spin.omni"\nimport irq "irq.omni"\n'
        caps='!{memory.atomic,port.io,cpu.control}'
        cases=[('leaked lock',head+'func main() u32 '+caps+' {\n  let g = spin.acquire(5309440u64, 100u32)\n  return 0u32\n}\n',b'E_RESOURCE_UNCONSUMED'),
               ('double release',head+'func main() u32 '+caps+' {\n  let g = spin.acquire(5309440u64, 100u32)\n  let a u32 = spin.release(move(g))\n  let b u32 = spin.release(move(g))\n  return 0u32\n}\n',b'E_RESOURCE_MOVED'),
               ('early return leaks',head+'func main() u32 '+caps+' {\n  let g = spin.acquire(5309440u64, 100u32)\n  if atomic.load32(5309504u64, 4u32) == 1u32 {\n    return 1u32\n  }\n  let a u32 = spin.release(move(g))\n  return 0u32\n}\n',b'E_RESOURCE_UNCONSUMED'),
               ('leaked irq guard',head+'func main() u32 !{cpu.control} {\n  let g = irq.save()\n  return 0u32\n}\n',b'E_RESOURCE_UNCONSUMED'),
               ('guard used after release',head+'func main() u32 '+caps+' {\n  let g = spin.acquire(5309440u64, 100u32)\n  let a u32 = spin.release(move(g))\n  let c u32 = spin.release(g)\n  return 0u32\n}\n',b'E_RESOURCE'),
               # the critical-section helpers declare no memory.write, so an allocation anywhere below them is a compile-time error
               ('allocation inside the section',head+'func alloc_it() u32 !{memory.write} {\n  let r Result<Resource<Buffer>,u32> = buffer.alloc(8u32)\n  match r {\n    Ok(b) { return buffer.len(borrow(b)) }\n    Err(code) { return code }\n  }\n}\nfunc middle() u32 !{memory.atomic} {\n  return alloc_it()\n}\nfunc main() u32 '+caps+' {\n  let g = spin.acquire(5309440u64, 100u32)\n  let n u32 = middle()\n  let a u32 = spin.release(move(g))\n  return n\n}\n',b'E_CAPABILITY')]
        for label,source,code in cases:
            path=self.dir/'neg.omni'; path.write_text(source,encoding='utf-8')
            result=self.emit(path)
            self.assertEqual(result.returncode,2,(label,result.stderr)); self.assertIn(code,result.stderr,(label,result.stderr))
            self.assertFalse((self.dir/'prog.ll').exists(),label)
        # control: releasing on both paths compiles
        ok=self.dir/'ok.omni'
        ok.write_text(head+'func main() u32 '+caps+' {\n  let g = spin.acquire(5309440u64, 100u32)\n  if atomic.load32(5309504u64, 4u32) == 1u32 {\n    let a u32 = spin.release(move(g))\n    return 1u32\n  }\n  let b u32 = spin.release(move(g))\n  return 0u32\n}\n',encoding='utf-8')
        self.assertEqual(self.emit(ok).returncode,0)

    def test_read_flags_needs_the_x86_64_target_profile(self)->None:
        path=self.dir/'flags.omni'
        path.write_text('module t\nimport rt "rt.omni"\nfunc main() u32 !{port.io,cpu.control} {\n  let f u64 = cpu.read_flags()\n  return rt.finish(0u32)\n}\n',encoding='utf-8')
        self.assertEqual(self.emit(path).returncode,0)
        result=subprocess.run([str(OMNI),'emit-llvm',str(path),'--target-profile','baremetal-i386-boot','--service-module','rt','--entry-address','1048576','-o',str(self.dir/'i386.ll')],
                              capture_output=True,cwd=self.dir,env={**os.environ,'OMNI_HOME':str(ROOT)},timeout=60)
        self.assertEqual(result.returncode,2,result.stderr); self.assertIn(b'E_TARGET_PROFILE',result.stderr)
        # the provider's own `cpu.trap3` also needs x86-64, so the refusal of cpu.read_flags is checked on a program that does not import it
        lone=self.dir/'lone_flags.omni'; lone.write_text('module boot\nfunc main() u32 !{cpu.control} {\n  let f u64 = cpu.read_flags()\n  return 0u32\n}\n',encoding='utf-8')
        result=subprocess.run([str(OMNI),'emit-llvm',str(lone),'--target-profile','baremetal-i386-boot','--service-module','boot','--entry-section','.text.omni_entry','--entry-address','1048576','--entry-stack','2097152','-o',str(self.dir/'i386.ll')],
                              capture_output=True,cwd=self.dir,env={**os.environ,'OMNI_HOME':str(ROOT)},timeout=60)
        self.assertEqual(result.returncode,2,result.stderr); self.assertIn(b'cpu.read_flags requiere el perfil baremetal-x86_64',result.stderr)
        hosted=subprocess.run([str(OMNI),'build',str(path),'-o',str(self.dir/'hosted'),'--cache-dir',str(self.dir/'cache')],capture_output=True,cwd=self.dir,
                              env={**os.environ,'OMNI_HOME':str(ROOT)},timeout=60)
        self.assertEqual(hosted.returncode,2,hosted.stderr); self.assertIn(b'E_TARGET_PROFILE',hosted.stderr)


class A83X64TlsTests(X64Harness):
    """CP-11 substrate (spec/TLS_AND_PERCPU_CANDIDATE.md): checked FS/GS-relative blocks. NOT the typed thread-local surface; CP-11 stays open."""

    THREAD=('--thread-entry','t.worker')

    def lines(self,serial:str)->list[str]:
        return serial.split('\n')[:-1]

    def test_two_threads_use_the_same_offsets_and_see_their_own_values_from_a_template(self)->None:
        rc,serial=self.boot(self.build(self.dir/'tls_threads.omni',emit_args=self.THREAD))
        # first read 7 (template, memory was poisoned) x2; 64-bit pattern ok x2; 1000/1000 correct reads per thread; final values 1999 and 2999; markers
        self.assertEqual((rc,self.lines(serial)),(1,['7','7','1','1','1000','1000','1999','2999','3735879681','3735879682']),serial)

    def test_each_cpu_has_its_own_block_and_the_control_on_a_shared_block_loses_updates(self)->None:
        elf=self.build(self.dir/'pcpu_smp.omni',ap_main=True)
        for attempt in range(2):
            rc,serial=self.boot(elf,smp=2)
            self.assertEqual((rc,self.lines(serial)),(1,['200000','200000','100','101']),(attempt,serial))   # exact counters, tags identify the CPUs
        text=(self.dir/'pcpu_smp.omni').read_text(encoding='utf-8')
        self.assertIn('let g u32 = set_gs(5836800u64)',text)
        (self.dir/'pcpu_shared.omni').write_text(text.replace('let g u32 = set_gs(5836800u64)','let g u32 = set_gs(5832704u64)'),encoding='utf-8')
        elf=self.build(self.dir/'pcpu_shared.omni',ap_main=True)
        shared=[]
        for attempt in range(2):
            rc,serial=self.boot(elf,smp=2)
            first,second=[int(x) for x in self.lines(serial)[:2]]
            shared.append(first)
            self.assertEqual(second,0,serial)              # CPU 1 never touched its own block
        self.assertTrue(any(v<400000 for v in shared),shared)   # two CPUs on one block: a plain load+store pair loses updates

    def test_every_access_outside_a_valid_block_traps_with_code_13(self)->None:
        head=('module t\nimport rt "rt.omni"\n\nfunc set_fs(base u64) u32 !{cpu.control} {\n'
              '  return cpu.wrmsr(3221225728u32, u32(bit.and(base, 4294967295u64)), u32(bit.shr(base, 32u32)))\n}\n\n'
              'func block(dst u64, magic u64) u32 !{memory.raw} {\n  let m u32 = raw.store64(dst, magic)\n  let s u32 = raw.store64(dst + 8u64, 256u64)\n'
              '  let a u32 = raw.store64(dst + 16u64, 111u64)\n  return raw.store64(dst + 248u64, 953482740045u64)\n}\n\n'
              'func main() u32 !{io.print,memory.raw,memory.tls,port.io,cpu.control} {\n'
              '  let made u32 = block(5767168u64, 3554268455816285519u64)\n  let other u32 = block(5771264u64, 3553414118101634383u64)\n')
        tail='  return rt.finish(0u32)\n}\n'
        def run(name:str,body:str)->tuple[int,str]:
            path=self.dir/f'{name}.omni'; path.write_text(head+body+tail,encoding='utf-8')
            return self.boot(self.build(path))
        set_ok='  let on u32 = set_fs(5767168u64)\n'
        # the in-bounds edge is fine: last 4 bytes (252) and last 8 bytes (248, = 222<<32 | 333) of a 256-byte block, and the first data word
        rc,serial=run('tls_edge',set_ok+'  print(tls.load32(252u64))\n  print(tls.load64(248u64))\n  print(tls.load64(16u64))\n')
        self.assertEqual((rc,self.lines(serial)),(1,['222','953482740045','111']),serial)
        cases=[('unset_base','  print(tls.load32(16u64))\n'),
               ('inside_the_header',set_ok+'  print(tls.load32(8u64))\n'),
               ('first_header_word',set_ok+'  print(tls.load32(0u64))\n'),
               ('last_header_byte',set_ok+'  print(tls.load32(15u64))\n'),
               ('past_the_size_by_one',set_ok+'  print(tls.load32(253u64))\n'),
               ('wide_load_past_the_size',set_ok+'  print(tls.load64(252u64))\n'),
               ('store_past_the_size',set_ok+'  let s u32 = tls.store32(256u64, 1u32)\n'),
               ('wrapping_offset',set_ok+'  print(tls.load64(18446744073709551608u64))\n'),
               ('torn_down_block',set_ok+'  print(tls.load32(16u64))\n  let down u32 = raw.store64(5767168u64, 0u64)\n  print(tls.load32(16u64))\n'),
               ('block_of_the_other_kind','  let on u32 = set_fs(5771264u64)\n  print(tls.load32(16u64))\n')]
        for name,body in cases:
            rc,serial=run(name,body)
            self.assertEqual(rc,(77<<1)|1,(name,rc,serial)); self.assertTrue(serial.endswith('TRAP 13\n'),(name,serial))   # exit value 64 + 13
            self.assertNotIn('222',serial,name)       # nothing from the block was read before the trap
        # the torn-down case does read once while the block was valid, then traps
        rc,serial=run('torn_down_again',set_ok+'  print(tls.load32(16u64))\n  let down u32 = raw.store64(5767168u64, 0u64)\n  print(tls.load32(16u64))\n')
        self.assertEqual(serial,'111\nTRAP 13\n',serial)

    def test_block_accessors_are_validated_before_any_artifact(self)->None:
        def program(name:str,caps:str,body:str)->pathlib.Path:
            path=self.dir/f'{name}.omni'
            path.write_text('module t\nimport rt "rt.omni"\nfunc main() u32 '+caps+' {\n'+body+'  return rt.finish(0u32)\n}\n',encoding='utf-8'); return path
        base='!{port.io,cpu.control'
        cases=[('tls without capability',program('a',base+'}','  let v u32 = tls.load32(16u64)\n'),b'E_CAPABILITY'),
               ('raw does not grant tls',program('b',base+',memory.raw}','  let v u32 = tls.load32(16u64)\n'),b'E_CAPABILITY'),
               ('tls does not grant pcpu',program('c',base+',memory.tls}','  let v u32 = pcpu.load32(16u64)\n'),b'E_CAPABILITY'),
               ('pcpu does not grant tls',program('d',base+',memory.pcpu}','  let v u32 = tls.load32(16u64)\n'),b'E_CAPABILITY'),
               ('offset must be u64',program('e',base+',memory.tls}','  let v u32 = tls.load32(16u32)\n'),b'E_TYPE'),
               ('store value width',program('f',base+',memory.tls}','  let v u32 = tls.store64(16u64, 1u32)\n'),b'E_TYPE'),
               ('store32 takes a u32',program('f2',base+',memory.tls}','  let v u32 = tls.store32(16u64, 1u64)\n'),b'E_TYPE'),
               ('load64 yields u64',program('f3',base+',memory.pcpu}','  let v u32 = pcpu.load64(16u64)\n'),b'E_TYPE'),
               ('load32 yields u32',program('f4',base+',memory.pcpu}','  let v u64 = pcpu.load32(16u64)\n'),b'E_TYPE'),
               ('arity',program('g',base+',memory.tls}','  let v u32 = tls.store32(16u64)\n'),b'E_ARITY'),
               ('no 8-bit access',program('h',base+',memory.tls}','  let v u32 = tls.load8(16u64)\n'),b'E_UNDEFINED')]
        for label,path,code in cases:
            result=self.emit(path)
            self.assertEqual(result.returncode,2,(label,result.stderr)); self.assertIn(code,result.stderr,(label,result.stderr))
            self.assertFalse((self.dir/'prog.ll').exists(),label)
        ok=program('ok',base+',memory.tls,memory.pcpu}','  let v u32 = tls.load32(16u64)\n  let w u64 = pcpu.load64(16u64)\n  let s u32 = pcpu.store32(16u64, v)\n')
        self.assertEqual(self.emit(ok).returncode,0)
        # Each refusal is checked on a program with NO other machine dependency, and the message must name the builtin: an earlier version imported
        # the x86-64 provider, whose own `cpu.trap3` made the i386 refusal pass even with the builtin's own profile check removed (mutant T18).
        for kind,call,cap in (('tls','tls.load32(16u64)','memory.tls'),('pcpu','pcpu.store64(16u64, 1u64)','memory.pcpu')):
            lone=self.dir/f'lone_{kind}.omni'; lone.write_text(f'module boot\nfunc main() u32 !{{{cap}}} {{\n  let v u32 = {call}\n  return 0u32\n}}\n',encoding='utf-8')
            name=call.split('(')[0].encode()
            i386=subprocess.run([str(OMNI),'emit-llvm',str(lone),'--target-profile','baremetal-i386-boot','--service-module','boot','--entry-section','.text.omni_entry','--entry-address','1048576','--entry-stack','2097152','-o',str(self.dir/'i386.ll')],
                                capture_output=True,cwd=self.dir,env={**os.environ,'OMNI_HOME':str(ROOT)},timeout=60)
            self.assertEqual(i386.returncode,2,(kind,i386.stderr)); self.assertIn(b'E_TARGET_PROFILE',i386.stderr,kind)
            self.assertIn(name+b' requiere el perfil baremetal-x86_64',i386.stderr,(kind,i386.stderr))
            self.assertFalse((self.dir/'i386.ll').exists(),kind)
            hosted=subprocess.run([str(OMNI),'build',str(lone),'-o',str(self.dir/'hosted'),'--cache-dir',str(self.dir/'cache')],capture_output=True,cwd=self.dir,
                                  env={**os.environ,'OMNI_HOME':str(ROOT)},timeout=60)
            self.assertEqual(hosted.returncode,2,(kind,hosted.stderr)); self.assertIn(b'E_TARGET_PROFILE',hosted.stderr,kind); self.assertIn(name,hosted.stderr,kind)
            evaluated=proc(OMNI,'eval',lone)       # the evaluator has no FS/GS: it refuses by itself, with its own message
            self.assertEqual(evaluated.returncode,2,(kind,evaluated.stderr)); self.assertIn(b'E_TARGET_PROFILE',evaluated.stderr,kind)
            self.assertIn(b'evaluador',evaluated.stderr,(kind,evaluated.stderr))


class A83X64QuiescenceTests(X64Harness):
    """CP-14 second slice (spec/QUIESCENCE_CANDIDATE.md): epoch-based safe retirement written in Omni (tests/x64/epoch.omni). Not claimed: callbacks,
    batching, preemption, no-migration enforcement."""

    def lines(self,serial:str)->list[str]:
        return serial.split('\n')[:-1]

    def test_the_reader_never_sees_a_retired_object_after_the_grace_period(self)->None:
        elf=self.build(self.dir/'epoch_smp.omni',ap_main=True)
        for attempt in range(2):
            rc,serial=self.boot(elf,smp=2)
            # poison seen 0 times; more than 1000 sections completed; epoch 1 + 3000 advances; the reader's slot is quiescent at the end
            self.assertEqual((rc,self.lines(serial)),(1,['0','1','3001','0']),(attempt,serial))
        # x86 cannot show a missing fence, so the protocol's ordering is checked on the emitted IR
        ir=(self.dir/'prog.ll').read_text(encoding='utf-8')
        def body(name:str)->str:
            found=re.search(r'define [^\n]*@omni\.fn\.'+re.escape(name)+r'\(.*?\n}\n',ir,re.S); self.assertIsNotNone(found,name); return found.group(0)
        enter,leave,advance,wait=body('epoch.enter'),body('epoch.exit'),body('epoch.advance'),body('epoch.wait')
        self.assertRegex(enter,r'store atomic volatile i32 %t\d+, ptr %t\d+ seq_cst, align 4')     # the slot publication...
        self.assertIn('fence seq_cst',enter)                                                        # ...is fenced before the caller loads the pointer
        self.assertRegex(leave,r'store atomic volatile i32 0, ptr %t\d+ release, align 4')         # leaving releases the section's reads
        self.assertRegex(advance,r'cmpxchg volatile ptr %t\d+, i32 %t\d+, i32 %t\d+ seq_cst seq_cst, align 4')   # the epoch advance is a full barrier (a compare-and-swap that refuses to wrap the counter)
        self.assertRegex(wait,r'load atomic volatile i32, ptr %t\d+ seq_cst, align 4')             # and the slot is read after it with seq_cst
        self.assertRegex(body('t.reader'),r'load atomic volatile i64, ptr %t\d+ seq_cst, align 8')   # the reader's pointer load is ordered after its slot publication
        self.assertRegex(body('t.writer'),r'store atomic volatile i64 %t\d+, ptr %t\d+ seq_cst, align 8')   # the pointer publication in the writer

    def test_without_the_grace_period_the_reader_sees_retired_objects(self)->None:
        text=(self.dir/'epoch_smp.omni').read_text(encoding='utf-8')
        needle='    let e u32 = epoch.advance(5898240u64)\n    let w u32 = epoch.wait(5898304u64, e, 100000000u32)\n'
        self.assertIn(needle,text)
        (self.dir/'epoch_nograce.omni').write_text(text.replace(needle,''),encoding='utf-8')
        elf=self.build(self.dir/'epoch_nograce.omni',ap_main=True)
        seen=[]
        for attempt in range(3):
            rc,serial=self.boot(elf,smp=2)
            seen.append(int(self.lines(serial)[0]))
        self.assertTrue(all(v>0 for v in seen),seen)     # the harness can tell the difference, every time

    def test_wait_returns_for_a_quiescent_slot_and_reports_a_stuck_reader_as_a_deadlock(self)->None:
        # The two-vCPU reader re-enters constantly, which would also satisfy a `wait` that never accepts a quiescent slot (mutant Q5): so the
        # two boundary cases are checked alone, on one vCPU.
        head='module t\nimport rt "rt.omni"\nimport epoch "epoch.omni"\nfunc main() u32 !{io.print,memory.atomic,port.io,cpu.control} {\n  let g0 u32 = atomic.store32(5898240u64, 1u32, 4u32)\n'
        tail='  return rt.finish(0u32)\n}\n'
        quiet=self.dir/'epoch_quiet.omni'
        quiet.write_text(head+'  let z u32 = atomic.store32(5898304u64, 0u32, 4u32)\n  let e u32 = epoch.advance(5898240u64)\n  print(epoch.wait(5898304u64, e, 1000u32))\n  print(e)\n'+tail,encoding='utf-8')
        rc,serial=self.boot(self.build(quiet))
        self.assertEqual((rc,self.lines(serial)),(1,['1','2']),serial)           # quiescent slot: no wait at all
        later=self.dir/'epoch_later.omni'
        later.write_text(head+'  let s u32 = atomic.store32(5898304u64, 2u32, 4u32)\n  let e u32 = epoch.advance(5898240u64)\n  print(epoch.wait(5898304u64, e, 1000u32))\n'+tail,encoding='utf-8')
        rc,serial=self.boot(self.build(later))
        self.assertEqual((rc,self.lines(serial)),(1,['1']),serial)               # a reader that entered at the new epoch (2 >= 2) is not waited for
        stuck=self.dir/'epoch_stuck.omni'
        stuck.write_text(head+'  let s u32 = atomic.store32(5898304u64, 1u32, 4u32)\n  let e u32 = epoch.advance(5898240u64)\n  print(epoch.wait(5898304u64, e, 1000u32))\n'+tail,encoding='utf-8')
        rc,serial=self.boot(self.build(stuck))
        self.assertEqual((rc,serial),((95<<1)|1,''),serial)                      # entered before the advance and never left: bounded wait -> deadlock 95

    def test_the_compiler_enforces_that_every_read_section_is_left_exactly_once(self)->None:
        head='module t\nimport rt "rt.omni"\nimport epoch "epoch.omni"\nfunc main() u32 !{memory.atomic,port.io,cpu.control} {\n'
        cases=[('leaked section',head+'  let g = epoch.enter(5898240u64, 5898304u64)\n  return 0u32\n}\n',b'E_RESOURCE_UNCONSUMED'),
               ('double exit',head+'  let g = epoch.enter(5898240u64, 5898304u64)\n  let a u32 = epoch.exit(move(g))\n  let b u32 = epoch.exit(move(g))\n  return 0u32\n}\n',b'E_RESOURCE_MOVED'),
               ('early return leaks',head+'  let g = epoch.enter(5898240u64, 5898304u64)\n  if atomic.load32(5898560u64, 4u32) == 1u32 {\n    return 1u32\n  }\n  let a u32 = epoch.exit(move(g))\n  return 0u32\n}\n',b'E_RESOURCE_UNCONSUMED')]
        for label,source,code in cases:
            path=self.dir/'case.omni'; path.write_text(source,encoding='utf-8')
            result=self.emit(path)
            self.assertEqual(result.returncode,2,(label,result.stderr)); self.assertIn(code,result.stderr,(label,result.stderr))
            self.assertFalse((self.dir/'prog.ll').exists(),label)
        ok=self.dir/'ok.omni'; ok.write_text(head+'  let g = epoch.enter(5898240u64, 5898304u64)\n  let a u32 = epoch.exit(move(g))\n  return rt.finish(0u32)\n}\n',encoding='utf-8')
        self.assertEqual(self.emit(ok).returncode,0)


class A83X64ThreadLocalTests(X64Harness):
    """CP-11 typed surface (spec/THREAD_LOCAL_CANDIDATE.md): `thread_local NAME Type = literal`, tls.get/set/init/block_size/teardown, compiler-owned layout and
    template. Dynamic TLS, PT_TLS, non-integer variables and per-CPU typed variables are not provided."""

    THREAD=('--thread-entry','t.worker')
    HEAD=('module t\nimport rt "rt.omni"\nthread_local counter u64 = 7u64\nthread_local flag u8 = 3u8\n'
          'func set_fs(base u64) u32 !{cpu.control} {\n'
          '  return cpu.wrmsr(3221225728u32, u32(bit.and(base, 4294967295u64)), u32(bit.shr(base, 32u32)))\n}\n')
    CAPS='!{io.print,memory.raw,memory.tls,port.io,cpu.control}'

    def lines(self,serial:str)->list[str]:
        return serial.split('\n')[:-1]

    def program(self,name:str,body:str,caps:str|None=None,head:str|None=None)->pathlib.Path:
        path=self.dir/f'{name}.omni'
        path.write_text((head if head is not None else self.HEAD)+'func main() u32 '+(caps if caps is not None else self.CAPS)+' {\n'+body+'  return rt.finish(0u32)\n}\n',encoding='utf-8')
        return path

    def go(self,name:str,body:str)->tuple[int,str]:
        return self.boot(self.build(self.program(name,body)))

    def test_two_threads_use_the_same_symbols_with_different_values_from_the_template(self)->None:
        rc,serial=self.boot(self.build(self.dir/'tls_typed.omni',emit_args=self.THREAD))
        # first values correct x2 (template, memory was poisoned); 1000 correct reads x2; i16 delta correct x2; ticks (library module) 1101 x2;
        # flag 1 and 2; final counters 1999 and 2999 in the right blocks; block size 48
        self.assertEqual((rc,self.lines(serial)),(1,['1','1','1000','1000','1','1','1101','1101','1','2','1999','2999','48']),serial)

    def test_the_compiler_emits_the_layout_and_the_template(self)->None:
        self.build(self.dir/'tls_typed.omni',emit_args=self.THREAD)
        ir=(self.dir/'prog.ll').read_text(encoding='utf-8')
        found=re.search(r'@omni\.tls\.template = internal constant \[(\d+) x i8\] c"([^"]*)"',ir); self.assertIsNotNone(found)
        image=bytes(int(x,16) for x in re.findall(r'\\([0-9A-F]{2})',found.group(2)))
        self.assertEqual(len(image),int(found.group(1))); self.assertEqual(len(image),48)
        self.assertEqual(image[0:8],b'OMNITLS1'); self.assertEqual(int.from_bytes(image[8:16],'little'),48)   # header: magic, block size
        # entry module first, declaration order, natural alignment: counter u64@16, flag u8@24, delta i16@26, mark u32@28, then the library's ticks u32@32
        self.assertEqual(int.from_bytes(image[16:24],'little'),7)
        self.assertEqual(image[24],3); self.assertEqual(image[25],0)
        self.assertEqual(int.from_bytes(image[26:28],'little'),0xFFFB)             # -5 as two's complement i16
        self.assertEqual(int.from_bytes(image[28:32],'little'),4660)
        self.assertEqual(int.from_bytes(image[32:36],'little'),100)
        self.assertEqual(image[36:48],bytes(12))                                     # padding to a multiple of 16
        # the accessors are constant-offset FS accesses checked against the header, not calls
        machine=self.sh('objdump','-d','--no-show-raw-insn','payload.elf').stdout.decode()
        self.assertRegex(machine,r'%fs:0x10'); self.assertRegex(machine,r'%fs:0x20'); self.assertNotRegex(machine,r'call\s+\S+ <(omni_)?tls[._]')

    def test_every_misuse_of_a_block_traps_with_code_13_and_the_good_path_works(self)->None:
        init='  let made u32 = u32(tls.init(5767168u64))\n  let on u32 = set_fs(5767168u64)\n'
        rc,serial=self.go('tl_ok',init+'  print(tls.get(counter))\n  let a u32 = tls.set(counter, 5u64)\n  print(tls.get(counter))\n  print(tls.get(flag))\n')
        self.assertEqual((rc,self.lines(serial)),(1,['7','5','3']),serial)
        rc,serial=self.go('tl_reinit',init+'  let a u32 = tls.set(counter, 99u64)\n  print(tls.get(counter))\n  let again u32 = u32(tls.init(5767168u64))\n  print(tls.get(counter))\n')
        self.assertEqual((rc,self.lines(serial)),(1,['99','7']),serial)                     # init on a live block resets it
        cases=[('unset_base','  print(tls.get(counter))\n',[]),
               ('before_init','  let on u32 = set_fs(5767168u64)\n  let z u32 = raw.store64(5767168u64, 0u64)\n  print(tls.get(counter))\n',[]),
               ('after_teardown',init+'  print(tls.get(counter))\n  let down u32 = tls.teardown()\n  print(tls.get(counter))\n',['7']),
               ('double_teardown',init+'  let down u32 = tls.teardown()\n  let again u32 = tls.teardown()\n  print(1u32)\n',[]),
               ('set_after_teardown',init+'  let down u32 = tls.teardown()\n  let s u32 = tls.set(counter, 1u64)\n  print(1u32)\n',[]),
               ('size_too_small',init+'  let small u32 = raw.store64(5767176u64, 16u64)\n  print(tls.get(counter))\n',[]),
               ('size_edge_first_variable_fits',init+'  let edge u32 = raw.store64(5767176u64, 24u64)\n  print(tls.get(counter))\n  print(tls.get(flag))\n',['7']),
               ('init_misaligned','  let made u32 = u32(tls.init(5767169u64))\n  print(1u32)\n',[]),
               ('init_null','  let made u32 = u32(tls.init(0u64))\n  print(1u32)\n',[])]
        for name,body,before in cases:
            rc,serial=self.go('tl_'+name,body)
            self.assertEqual(rc,(77<<1)|1,(name,rc,serial)); self.assertEqual(self.lines(serial),before+['TRAP 13'],(name,serial))

    def test_declarations_and_uses_are_checked_before_any_artifact(self)->None:
        init='  let made u32 = u32(tls.init(5767168u64))\n'
        cases=[('unknown name',self.program('e1',init+'  print(tls.get(nothere))\n'),b'E_THREAD_LOCAL'),
               ('argument is not a name',self.program('e2',init+'  print(tls.get(5u32))\n'),b'E_THREAD_LOCAL'),
               ('value of another type',self.program('e3',init+'  let s u32 = tls.set(flag, 1u32)\n'),b'E_TYPE'),
               ('set takes a value',self.program('e4',init+'  let s u32 = tls.set(counter)\n'),b'E_ARITY'),
               ('get takes only a name',self.program('e5',init+'  print(tls.get(counter, counter))\n'),b'E_ARITY'),
               ('block_size takes nothing',self.program('e6',init+'  print(tls.block_size(1u32))\n'),b'E_ARITY'),
               ('no memory.tls',self.program('e7',init+'  print(tls.get(counter))\n',caps='!{io.print,memory.raw,port.io,cpu.control}'),b'E_CAPABILITY'),
               ('init needs memory.raw',self.program('e8',init,caps='!{io.print,memory.tls,port.io,cpu.control}'),b'E_CAPABILITY'),
               ('memory.pcpu is not memory.tls',self.program('e9',init+'  print(tls.get(counter))\n',caps='!{io.print,memory.raw,memory.pcpu,port.io,cpu.control}'),b'E_CAPABILITY'),
               ('a thread-local cannot be borrowed',self.program('e10',init+'  let b = borrow(counter)\n'),b'E_UNDEFINED'),
               ('init without any variable',self.program('e11',init,head='module t\nimport rt "rt.omni"\n'),b'E_THREAD_LOCAL'),
               ('block_size without any variable',self.program('e12','  print(tls.block_size())\n',head='module t\nimport rt "rt.omni"\n'),b'E_THREAD_LOCAL')]
        (self.dir/'other.omni').write_text('module other\nthread_local secret u32 = 1u32\npub func f() u32 { return 0u32 }\n',encoding='utf-8')
        cases.append(('another module\'s variable',self.program('e13',init+'  print(tls.get(secret))\n',head='module t\nimport rt "rt.omni"\nimport other "other.omni"\n'),b'E_THREAD_LOCAL'))
        declarations=[('float type','thread_local x f64 = 1.0f64\n',b'E_THREAD_LOCAL'),
                      ('bool type','thread_local x bool = true\n',b'E_THREAD_LOCAL'),
                      ('expression initial value','thread_local x u32 = 1u32 + 2u32\n',b'E_THREAD_LOCAL'),
                      ('name as initial value','thread_local x u32 = counter\n',b'E_THREAD_LOCAL'),
                      ('initial value of another type','thread_local x u64 = 7u32\n',b'E_TYPE'),
                      ('unsigned overflow','thread_local x u8 = 256u8\n',b'E_OVERFLOW_LITERAL'),
                      ('signed positive overflow','thread_local x i8 = 128i8\n',b'E_OVERFLOW_LITERAL'),
                      ('signed negative overflow','thread_local x i8 = -129i8\n',b'E_OVERFLOW_LITERAL'),
                      ('negative unsigned','thread_local x u32 = -1\n',b'E_THREAD_LOCAL'),
                      ('duplicate','thread_local counter u32 = 1\n',b'E_DUPLICATE'),
                      ('exported','pub thread_local x u32 = 1\n',b'E_THREAD_LOCAL')]
        for label,decl,code in declarations:
            cases.append((label,self.program('d_'+label.replace(' ','_'),'',head=self.HEAD+decl),code))
        for label,path,code in cases:
            result=self.emit(path)
            self.assertEqual(result.returncode,2,(label,result.stderr)); self.assertIn(code,result.stderr,(label,result.stderr))
            self.assertFalse((self.dir/'prog.ll').exists(),label)
        # the extreme values of every type are accepted
        edges=('thread_local a u8 = 255u8\nthread_local b u16 = 65535u16\nthread_local c u32 = 4294967295u32\nthread_local d u64 = 18446744073709551615u64\n'
               'thread_local e i8 = -128i8\nthread_local f i16 = -32768i16\nthread_local g i32 = -2147483648i32\nthread_local h i64 = -9223372036854775808i64\nthread_local i i64 = 9223372036854775807i64\n')
        ok=self.program('edges','  print(tls.block_size())\n',head='module t\nimport rt "rt.omni"\n'+edges)
        self.assertEqual(self.emit(ok).returncode,0)
        ir=(self.dir/'prog.ll').read_text(encoding='utf-8')
        found=re.search(r'@omni\.tls\.template = internal constant \[(\d+) x i8\] c"([^"]*)"',ir); image=bytes(int(x,16) for x in re.findall(r'\\([0-9A-F]{2})',found.group(2)))
        self.assertEqual(int.from_bytes(image[8:16],'little'),len(image))
        self.assertEqual(image[16],255); self.assertEqual(int.from_bytes(image[18:20],'little'),65535); self.assertEqual(int.from_bytes(image[20:24],'little'),4294967295)
        self.assertEqual(int.from_bytes(image[24:32],'little'),2**64-1); self.assertEqual(image[32],0x80)                       # i8 -128
        self.assertEqual(int.from_bytes(image[34:36],'little'),0x8000); self.assertEqual(int.from_bytes(image[36:40],'little'),0x80000000)
        self.assertEqual(int.from_bytes(image[40:48],'little'),2**63); self.assertEqual(int.from_bytes(image[48:56],'little'),2**63-1)

    def test_other_targets_and_the_evaluator_refuse_thread_locals_explicitly(self)->None:
        use=self.program('hosted','  let made u32 = u32(tls.init(5767168u64))\n')
        plain=self.dir/'plain_decl.omni'; plain.write_text('module t\nthread_local counter u64 = 7u64\nfunc main() u32 { return 0u32 }\n',encoding='utf-8')
        # hosted LLVM and the evaluator never accept a program that declares or uses one silently
        for label,command in (('hosted build, unused declaration',[str(OMNI),'build',str(plain),'-o',str(self.dir/'h1'),'--cache-dir',str(self.dir/'c1')]),
                              ('hosted build, use',[str(OMNI),'build',str(use),'-o',str(self.dir/'h2'),'--cache-dir',str(self.dir/'c2')])):
            result=subprocess.run(command,capture_output=True,cwd=self.dir,env={**os.environ,'OMNI_HOME':str(ROOT)},timeout=60)
            self.assertEqual(result.returncode,2,(label,result.stderr)); self.assertIn(b'E_TARGET_PROFILE',result.stderr,label)
        evaluated=proc(OMNI,'eval',use); self.assertEqual(evaluated.returncode,2,evaluated.stderr)
        self.assertIn(b'E_TARGET_PROFILE',evaluated.stderr); self.assertIn(b'evaluador',evaluated.stderr)
        # the i386 boot profile has no FS/GS blocks: the declaration alone is refused
        lone=self.dir/'lone_decl.omni'; lone.write_text('module boot\nthread_local counter u64 = 7u64\nfunc main() u32 { return 0u32 }\n',encoding='utf-8')
        result=subprocess.run([str(OMNI),'emit-llvm',str(lone),'--target-profile','baremetal-i386-boot','--service-module','boot','--entry-section','.text.omni_entry',
                               '--entry-address','1048576','--entry-stack','2097152','-o',str(self.dir/'i386.ll')],capture_output=True,cwd=self.dir,env={**os.environ,'OMNI_HOME':str(ROOT)},timeout=60)
        self.assertEqual(result.returncode,2,result.stderr); self.assertIn(b'thread_local requiere el perfil baremetal-x86_64',result.stderr)
        self.assertFalse((self.dir/'i386.ll').exists())

    def test_representations_fence_round_trip_and_osnmf_agree(self)->None:
        path=self.dir/'tls_typed.omni'
        wave=proc(OMNI,'wave',path); self.assertEqual(wave.returncode,0,wave.stderr); self.assertTrue(wave.stdout.startswith(b'(omni-wave 21'))
        self.assertIn(b'(thread-local counter u64 7)',wave.stdout); self.assertIn(b'(thread-local delta i16 -5)',wave.stdout)
        wire=self.dir/'t.owire'; self.assertEqual(proc(OMNI,'pack',path,'-o',wire).returncode,0); self.assertEqual(wire.read_bytes()[:8],b'OMCX\x15\x00\x00\x00')
        owave=self.dir/'t.owave'; owave.write_bytes(wave.stdout)
        self.assertEqual(proc(OMNI,'check',owave).returncode,0); self.assertEqual(proc(OMNI,'check',wire).returncode,0)
        self.assertEqual(proc(OMNI,'wave',owave).stdout,wave.stdout)                    # Wave -> program -> Wave is stable
        onme=self.dir/'t.onme'; self.assertEqual(proc(OMNI,'onme',path,'-o',onme).returncode,0)
        formatted=proc(OMNI,'fmt',path); self.assertEqual(formatted.returncode,0,formatted.stderr)
        self.assertIn(b'thread_local counter u64 = 7u64',formatted.stdout); self.assertIn(b'thread_local delta i16 = -5i16',formatted.stdout)
        # an older label over this semantics is a version error, never a silent reinterpretation
        for old in (18,19,20):
            relabelled=self.dir/f'old{old}.owave'; relabelled.write_bytes(wave.stdout.replace(b'(omni-wave 21',f'(omni-wave {old}'.encode(),1))
            result=proc(OMNI,'check',relabelled); self.assertEqual(result.returncode,2,(old,result.stderr)); self.assertIn(b'E_VERSION',result.stderr,old)
            raw=bytearray(wire.read_bytes()); raw[4]=old; relabelled_wire=self.dir/f'old{old}.owire'; relabelled_wire.write_bytes(bytes(raw))
            result=proc(OMNI,'check',relabelled_wire); self.assertEqual(result.returncode,2,(old,result.stderr)); self.assertIn(b'E_VERSION',result.stderr,old)
        # the declaration alone (no tls.* call anywhere) is new semantics too: Wave21/OMC21 and E_VERSION when relabelled
        only=self.dir/'only_decl.omni'; only.write_text('module t\nthread_local counter u64 = 7u64\nfunc main() u32 { return 0u32 }\n',encoding='utf-8')
        only_wave=proc(OMNI,'wave',only); self.assertTrue(only_wave.stdout.startswith(b'(omni-wave 21'),only_wave.stdout[:20])
        only_wire=self.dir/'only.owire'; self.assertEqual(proc(OMNI,'pack',only,'-o',only_wire).returncode,0); self.assertEqual(only_wire.read_bytes()[:8],b'OMCX\x15\x00\x00\x00')
        for old in (18,19,20):
            relabelled=self.dir/f'only{old}.owave'; relabelled.write_bytes(only_wave.stdout.replace(b'(omni-wave 21',f'(omni-wave {old}'.encode(),1))
            result=proc(OMNI,'check',relabelled); self.assertEqual(result.returncode,2,(old,result.stderr)); self.assertIn(b'E_VERSION',result.stderr,old)
            raw=bytearray(only_wire.read_bytes()); raw[4]=old; relabelled_wire=self.dir/f'only{old}.owire'; relabelled_wire.write_bytes(bytes(raw))
            result=proc(OMNI,'check',relabelled_wire); self.assertEqual(result.returncode,2,(old,result.stderr)); self.assertIn(b'E_VERSION',result.stderr,old)
        # a damaged trailer is rejected
        damaged=bytearray(wire.read_bytes()); damaged[-1]^=0xFF
        broken=self.dir/'broken.owire'; broken.write_bytes(bytes(damaged[:-3])); result=proc(OMNI,'check',broken); self.assertEqual(result.returncode,2,result.stderr)
        # OSNMF is derived from the checked program and is the same through every representation
        store=proc(OMNI,'memory',path); self.assertEqual(store.returncode,0,store.stderr)
        for derived in (wire,owave,onme): self.assertEqual(proc(OMNI,'memory',derived).stdout,store.stdout,derived.name)
        nuclei=json.loads(store.stdout)['nuclei']
        found={(n['module'],n['name']) for n in nuclei if n['kind']=='thread-local'}
        self.assertEqual(found,{('t','counter'),('t','flag'),('t','delta'),('t','mark'),('tlslib','ticks')})
        # content changes with the initial value, the contract with the type; neither depends on a layout offset
        def nucleus(source:str,name:str)->dict:
            variant=self.dir/'variant.omni'; variant.write_text(source,encoding='utf-8')
            return [n for n in json.loads(proc(OMNI,'memory',variant).stdout)['nuclei'] if n['kind']=='thread-local' and n['name']==name][0]
        base=nucleus('module t\nthread_local x u32 = 7\nfunc main() u32 { return 0u32 }\n','x')
        other_value=nucleus('module t\nthread_local x u32 = 8\nfunc main() u32 { return 0u32 }\n','x')
        other_type=nucleus('module t\nthread_local x u64 = 7u64\nfunc main() u32 { return 0u32 }\n','x')
        moved=nucleus('module t\nthread_local pad u8 = 1u8\nthread_local x u32 = 7\nfunc main() u32 { return 0u32 }\n','x')
        self.assertNotEqual(base['content_id'],other_value['content_id']); self.assertEqual(base['contract_id'],other_value['contract_id'])
        self.assertNotEqual(base['contract_id'],other_type['contract_id'])
        self.assertEqual((base['content_id'],base['contract_id']),(moved['content_id'],moved['contract_id']))   # same variable, different offset: same identity


class A83X64LayoutTests(X64Harness):
    """CP-07 (spec/NATIVE_LAYOUT_CANDIDATE.md): C-rules native layout and `packed struct`, the compile-time queries layout.size/align/offset, and typed
    access to raw memory (raw.read<R>/raw.write<R>) over plain records. Address-domain types, static data and bit-fields are not provided."""

    RECORDS=('struct Mixed { a u8, b u32, c u16, d u64 }\n'
             'struct Wide { a u8, d u64, e u8 }\n'
             'struct Tiny { a u8, b u8, c u16 }\n'
             'struct Nest { tag u8, inner Mixed, tail u8 }\n'
             'packed struct Gate { lo u16, sel u16, ist u8, flags u8, mid u16, hi u32, zero u32 }\n'
             'packed struct Pk { x u8, y u32, z u16 }\n'
             'packed struct PNest { head u8, inner Mixed, last u16 }\n')
    NAMES=('Mixed','Wide','Tiny','Nest','Gate','Pk','PNest')
    FIELDS={'Mixed':('a','b','c','d'),'Wide':('a','d','e'),'Tiny':('a','b','c'),'Nest':('tag','inner','tail'),
            'Gate':('lo','sel','ist','flags','mid','hi','zero'),'Pk':('x','y','z'),'PNest':('head','inner','last')}

    def lines(self,serial:str)->list[str]:
        return serial.split('\n')[:-1]

    def queries(self)->str:
        body=''
        for name in self.NAMES:
            body+=f'  print(layout.size<{name}>())\n  print(layout.align<{name}>())\n'
            for field in self.FIELDS[name]: body+=f'  print(layout.offset<{name}>({field}))\n'
        return body

    def oracle(self,ir:pathlib.Path,triple:str,module:str)->dict[str,list[int]]:
        """The independent answer: LLVM's own layout of the very struct types the compiler emitted."""
        text=ir.read_text(encoding='utf-8').replace('target triple = "x86_64-unknown-none-elf"',f'target triple = "{triple}"').replace('target triple = "i386-unknown-none-elf"',f'target triple = "{triple}"')
        extra=''
        for name in self.NAMES:
            ty=f'%omni.type.{module}.{name}'
            extra+=f'@o_size_{name} = constant i64 ptrtoint (ptr getelementptr ({ty}, ptr null, i32 1) to i64)\n'
            extra+=f'@o_align_{name} = constant i64 ptrtoint (ptr getelementptr ({{ i8, {ty} }}, ptr null, i32 0, i32 1) to i64)\n'   # ABI alignment = offset of the record after an i8
            for index,_ in enumerate(self.FIELDS[name]):
                extra+=f'@o_off_{name}_{index} = constant i64 ptrtoint (ptr getelementptr ({ty}, ptr null, i32 0, i32 {index}) to i64)\n'
        source=self.dir/'oracle.ll'; source.write_text(text+extra,encoding='utf-8')
        done=subprocess.run(['clang','-target',triple,'-S','-O0','-x','ir',str(source),'-o',str(self.dir/'oracle.s')],capture_output=True)
        self.assertEqual(done.returncode,0,done.stderr)
        asm=(self.dir/'oracle.s').read_text(encoding='utf-8')
        result={}
        for name in self.NAMES:
            def quad(label:str)->int: return int(re.search(rf'^{label}:\n\s*\.quad\s+(?:0\+)?(\d+)',asm,re.M).group(1))
            size=quad(f'o_size_{name}'); align=quad(f'o_align_{name}')
            offsets=[quad(f'o_off_{name}_{i}') for i,_ in enumerate(self.FIELDS[name])]
            result[name]=[size,align]+offsets
        return result

    def test_layout_answers_match_llvm_on_x86_64_and_on_i386(self)->None:
        source=self.dir/'queries.omni'
        source.write_text('module t\nimport rt "rt.omni"\n'+self.RECORDS+'func main() u32 !{io.print,port.io,cpu.control} {\n'+self.queries()+'  return rt.finish(0u32)\n}\n',encoding='utf-8')
        rc,serial=self.boot(self.build(source))
        omni=[int(x) for x in self.lines(serial)]
        oracle=self.oracle(self.dir/'prog.ll','x86_64-unknown-none-elf','t')
        flat=[v for name in self.NAMES for v in oracle[name]]
        self.assertEqual(omni,flat)                                       # the constants the compiled image prints == LLVM's own layout of the same types
        # i386 profile: u64 aligns to 4, so the answers differ from x86-64 and must still equal LLVM's i386 layout
        boot='module boot\n'+self.RECORDS+'func out(v u64) u32 !{port.io} {\n  return port.out8(1016u32, u32(v))\n}\nfunc main() u32 !{port.io,cpu.control} {\n'
        for name in self.NAMES:
            boot+=f'  let s{name} u32 = out(layout.size<{name}>())\n  let a{name} u32 = out(layout.align<{name}>())\n'
            for field in self.FIELDS[name]: boot+=f'  let o{name}{field} u32 = out(layout.offset<{name}>({field}))\n'
        boot+='  let d u32 = port.out32(244u32, 1u32)\n  return cpu.halt()\n}\n'
        path=self.dir/'boot.omni'; path.write_text(boot,encoding='utf-8')
        done=proc(OMNI,'emit-llvm',path,'--target-profile','baremetal-i386-boot','--service-module','boot','--entry-section','.text.omni_entry','--entry-address','1048576','--entry-stack','2097152','-o',self.dir/'boot.ll')
        self.assertEqual(done.returncode,0,done.stderr)
        (self.dir/'link.ld').write_text(A83BaremetalBootSmokeTests.LINKER,encoding='utf-8')
        self.sh('clang','-target','i386-unknown-none-elf',*A83BaremetalBootSmokeTests.CFLAGS,'-nostdlib','-c','boot.ll','-o','boot32.o')
        self.sh('ld','-m','elf_i386','-nostdlib','-T','link.ld','boot32.o','-o','boot32.elf')
        run=subprocess.run(['qemu-system-i386','-kernel',str(self.dir/'boot32.elf'),'-display','none','-serial','stdio','-no-reboot','-device','isa-debug-exit,iobase=0xf4,iosize=0x04','-m','64'],capture_output=True,timeout=60)
        oracle32=self.oracle(self.dir/'boot.ll','i386-unknown-none-elf','boot')
        flat32=[v for name in self.NAMES for v in oracle32[name]]
        self.assertEqual(list(run.stdout),flat32,run.stderr)
        self.assertNotEqual(flat,flat32)                                  # the two targets really differ (u64 alignment): the comparison is not vacuous
        self.assertEqual(oracle['Mixed'][:2],[24,8]); self.assertEqual(oracle32['Mixed'][:2],[20,4])
        self.assertEqual(oracle['Gate'][:2],[16,1]); self.assertEqual(oracle['PNest'][:2],[27,1])

    def test_typed_access_writes_zero_padding_and_never_assumes_alignment(self)->None:
        rc,serial=self.boot(self.build(self.dir/'layout_rw.omni'))
        expected=['24','8','0','4','8','16','16','1','8','12','40','8','32','7','5',             # layout answers
                  '0','0','0','0','1','2','3','4','2','4',                                          # Mixed: padding bytes zero, fields at offsets, read back
                  '52','18','18','2882400018','170','170','4660','2882400018',                       # Gate at an odd address: bytes, neighbours still 0xAA, read back
                  '0','0','0','0','0','7','8','6','7',                                               # Nest: every padding byte zero, nested fields, read back
                  '16909060','6','170','170','16909060']                                              # Pk at an odd address
        self.assertEqual((rc,self.lines(serial)),(1,expected),serial)

    def test_misaligned_or_null_native_access_traps_with_code_14(self)->None:
        head='module t\nimport rt "rt.omni"\nstruct Mixed { a u8, b u32, c u16, d u64 }\npacked struct Pk { x u8, y u32, z u16 }\nfunc main() u32 !{io.print,memory.raw,port.io,cpu.control} {\n'
        value='Mixed { a: 1u8, b: 2u32, c: 3u16, d: 4u64 }'
        cases=[('read_misaligned','  let m Mixed = raw.read<Mixed>(6029313u64)\n  print(m.b)\n'),
               ('write_misaligned','  let w u32 = raw.write<Mixed>(6029316u64, '+value+')\n  print(1u32)\n'),
               ('read_null','  let m Mixed = raw.read<Mixed>(0u64)\n  print(m.b)\n'),
               ('packed_null','  let m Pk = raw.read<Pk>(0u64)\n  print(m.y)\n')]
        for name,body in cases:
            path=self.dir/f'{name}.omni'; path.write_text(head+body+'  return rt.finish(0u32)\n}\n',encoding='utf-8')
            rc,serial=self.boot(self.build(path))
            self.assertEqual(rc,(78<<1)|1,(name,rc,serial)); self.assertEqual(self.lines(serial),['TRAP 14'],(name,serial))     # exit value 64 + 14
        ok=self.dir/'odd_ok.omni'
        ok.write_text(head+'  let w u32 = raw.write<Pk>(6029315u64, Pk { x: 1u8, y: 2u32, z: 3u16 })\n  let m Pk = raw.read<Pk>(6029315u64)\n  print(m.y)\n  return rt.finish(0u32)\n}\n',encoding='utf-8')
        rc,serial=self.boot(self.build(ok)); self.assertEqual((rc,self.lines(serial)),(1,['2']),serial)

    def test_a_typed_read_above_4_gib_keeps_all_64_bits_of_the_address(self)->None:
        rc,serial=self.boot(self.build(self.dir/'layout_high.omni',emit_args=('--exception-handler','t.on_exception')))
        self.assertEqual((rc,self.lines(serial)),((100<<1)|1,['14','4294971392']),serial)     # #PF, CR2 = 0x100001000 exactly

    def test_misuse_is_rejected_at_compile_time(self)->None:
        counter=[0]
        def prog(body:str,records:str='struct Mixed { a u8, b u32 }\n',caps:str='!{io.print,memory.raw,port.io,cpu.control}',extra:str='')->pathlib.Path:
            counter[0]+=1; path=self.dir/f'case{counter[0]}.omni'; path.write_text('module t\nimport rt "rt.omni"\n'+extra+records+'func main() u32 '+caps+' {\n'+body+'  return rt.finish(0u32)\n}\n',encoding='utf-8'); return path
        (self.dir/'other.omni').write_text('module other\nstruct Hidden { a u32 }\npub struct Shown { a u32 }\n',encoding='utf-8')
        cases=[('record with a bool field',prog('  print(layout.size<Bad>())\n','struct Bad { a u8, b bool }\n'),b'E_LAYOUT'),
               ('record with a Text field',prog('  print(layout.size<Bad>())\n','struct Bad { a u8, b Text }\n'),b'E_LAYOUT'),
               ('nested non-plain record',prog('  print(layout.size<Outer>())\n','struct In { a Text }\nstruct Outer { x In }\n'),b'E_LAYOUT'),
               ('type argument is not a record',prog('  print(layout.size<u32>())\n'),b'E_LAYOUT'),
               ('missing type argument',prog('  print(layout.size())\n'),b'E_LAYOUT'),
               ('unknown field',prog('  print(layout.offset<Mixed>(nothere))\n'),b'E_LAYOUT'),
               ('field is not a name',prog('  print(layout.offset<Mixed>(3u32))\n'),b'E_LAYOUT'),
               ('size takes no argument',prog('  print(layout.size<Mixed>(1u32))\n'),b'E_ARITY'),
               ('write of another type',prog('  let w u32 = raw.write<Mixed>(6029312u64, 7u32)\n'),b'E_TYPE'),
               ('read needs a u64 address',prog('  let m Mixed = raw.read<Mixed>(1u32)\n'),b'E_TYPE'),
               ('read without memory.raw',prog('  let m Mixed = raw.read<Mixed>(6029312u64)\n',caps='!{io.print,port.io,cpu.control}'),b'E_CAPABILITY'),
               ('write without memory.raw',prog('  let w u32 = raw.write<Mixed>(6029312u64, Mixed { a: 1u8, b: 2u32 })\n',caps='!{io.print,port.io,cpu.control}'),b'E_CAPABILITY'),
               ('private record of another module',prog('  print(layout.size<other.Hidden>())\n',extra='import other "other.omni"\n'),b'E_VISIBILITY'),
               ('packed generic',prog('  print(1u32)\n','packed struct Box<T> { a T }\n'),b'E_LAYOUT')]
        for label,path,code in cases:
            result=self.emit(path)
            self.assertEqual(result.returncode,2,(label,result.stderr)); self.assertIn(code,result.stderr,(label,result.stderr))
            self.assertFalse((self.dir/'prog.ll').exists(),label)
            checked=proc(OMNI,'check',path)         # the checker alone must refuse it: lowering is not the line of defence (mutant M14)
            self.assertEqual(checked.returncode,2,(label,'check',checked.stderr)); self.assertIn(code,checked.stderr,(label,'check',checked.stderr))
        shown=prog('  print(layout.size<other.Shown>())\n',extra='import other "other.omni"\n'); self.assertEqual(self.emit(shown).returncode,0)
        # the record is named in the call text, so a Wave that names a record the caller may not see must be refused by the checker as well (mutant M15):
        # take the valid bundle and make the record private
        wave=proc(OMNI,'wave',shown); self.assertEqual(wave.returncode,0,wave.stderr)
        self.assertIn(b'(struct Shown (visibility public)',wave.stdout)
        forged=self.dir/'forged.owave'; forged.write_bytes(wave.stdout.replace(b'(struct Shown (visibility public)',b'(struct Shown (visibility private)',1))
        result=proc(OMNI,'check',forged); self.assertEqual(result.returncode,2,result.stderr); self.assertIn(b'E_VISIBILITY',result.stderr)
        # an instantiation of a generic record is a concrete record and has a layout; the template itself has none
        generic=prog('  print(layout.size<Box<u64>>())\n  print(layout.offset<Box<u64>>(a))\n','struct Box<T> { tag u8, a T }\n'); self.assertEqual(self.emit(generic).returncode,0)
        rc,serial=self.boot(self.build(generic)); self.assertEqual(self.lines(serial),['16','8'],serial)

    def test_hosted_and_the_evaluator_answer_layout_queries_but_refuse_raw_access(self)->None:
        queries=self.dir/'q.omni'
        queries.write_text('module t\n'+self.RECORDS+'func main() u32 !{io.print} {\n  print(layout.size<Mixed>())\n  print(layout.offset<Mixed>(d))\n  print(layout.size<Gate>())\n  return 0u32\n}\n',encoding='utf-8')
        evaluated=proc(OMNI,'eval',queries); self.assertEqual(evaluated.returncode,0,evaluated.stderr); self.assertEqual(evaluated.stdout.decode().split(),['24','16','16'])
        built=proc(OMNI,'build',queries,'-o',self.dir/'q','--cache-dir',self.dir/'cache'); self.assertEqual(built.returncode,0,built.stderr)
        native=subprocess.run([str(self.dir/'q')],capture_output=True); self.assertEqual(native.stdout.decode().split(),['24','16','16'])
        access=self.dir/'a.omni'
        access.write_text('module t\nstruct S { a u32 }\nfunc main() u32 !{memory.raw} {\n  let m S = raw.read<S>(4096u64)\n  return m.a\n}\n',encoding='utf-8')
        result=proc(OMNI,'build',access,'-o',self.dir/'a','--cache-dir',self.dir/'cache2')   # a hosted binary has no raw memory: refused, never silently compiled
        self.assertEqual(result.returncode,2,result.stderr); self.assertIn(b'E_TARGET_PROFILE',result.stderr)
        # differential: the evaluator's sparse memory and the native image, running the SAME statements, print the same bytes
        text=(self.dir/'layout_rw.omni').read_text(encoding='utf-8')
        for old,new in (('import rt "rt.omni"\n',''),('!{io.print,memory.raw,port.io,cpu.control}','!{io.print,memory.raw}'),('return rt.finish(0u32)','return 0u32')):
            self.assertIn(old,text); text=text.replace(old,new)
        (self.dir/'layout_rw_eval.omni').write_text(text,encoding='utf-8')
        evaluated=proc(OMNI,'eval',self.dir/'layout_rw_eval.omni'); self.assertEqual(evaluated.returncode,0,evaluated.stderr)
        rc,serial=self.boot(self.build(self.dir/'layout_rw.omni'))
        self.assertEqual(evaluated.stdout.decode().split(),self.lines(serial))
        # and it refuses a misaligned native access the way the native image traps
        mis=self.dir/'mis.omni'
        mis.write_text('module t\nstruct S { a u8, d u64 }\nfunc main() u32 !{memory.raw} {\n  let m S = raw.read<S>(4097u64)\n  return 0u32\n}\n',encoding='utf-8')
        result=proc(OMNI,'eval',mis); self.assertEqual(result.returncode,2,result.stderr); self.assertIn(b'E_LAYOUT',result.stderr)

    def test_representations_fence_round_trip_and_osnmf_agree(self)->None:
        path=self.dir/'rep.omni'
        path.write_text('module t\n'+self.RECORDS+'func main() u32 !{io.print} {\n  print(layout.size<Gate>())\n  return 0u32\n}\n',encoding='utf-8')
        wave=proc(OMNI,'wave',path); self.assertEqual(wave.returncode,0,wave.stderr); self.assertTrue(wave.stdout.startswith(b'(omni-wave 21'))
        self.assertIn(b'(packed)',wave.stdout); self.assertIn(b'layout.size<t.Gate>',wave.stdout)         # the record travels in the call text
        wire=self.dir/'rep.owire'; self.assertEqual(proc(OMNI,'pack',path,'-o',wire).returncode,0); self.assertEqual(wire.read_bytes()[:8],b'OMCX\x15\x00\x00\x00')
        owave=self.dir/'rep.owave'; owave.write_bytes(wave.stdout)
        self.assertEqual(proc(OMNI,'check',owave).returncode,0); self.assertEqual(proc(OMNI,'check',wire).returncode,0); self.assertEqual(proc(OMNI,'wave',owave).stdout,wave.stdout)
        onme=self.dir/'rep.onme'; self.assertEqual(proc(OMNI,'onme',path,'-o',onme).returncode,0)
        formatted=proc(OMNI,'fmt',path).stdout; self.assertIn(b'packed struct Gate',formatted); self.assertNotIn(b'packed struct Mixed',formatted)
        self.assertIn(b'layout.size<t.Gate>()',formatted)
        for old in (18,19,20):
            relabelled=self.dir/f'rep{old}.owave'; relabelled.write_bytes(wave.stdout.replace(b'(omni-wave 21',f'(omni-wave {old}'.encode(),1))
            result=proc(OMNI,'check',relabelled); self.assertEqual(result.returncode,2,(old,result.stderr)); self.assertIn(b'E_VERSION',result.stderr,old)
            raw=bytearray(wire.read_bytes()); raw[4]=old; rw=self.dir/f'rep{old}.owire'; rw.write_bytes(bytes(raw))
            result=proc(OMNI,'check',rw); self.assertEqual(result.returncode,2,(old,result.stderr)); self.assertIn(b'E_VERSION',result.stderr,old)
        # a layout query alone (no packed record) and a packed record alone (no query) are each new semantics
        for label,source in (('query only','module t\nstruct S { a u32 }\nfunc main() u32 !{io.print} {\n  print(layout.size<S>())\n  return 0u32\n}\n'),
                             ('packed only','module t\npacked struct S { a u8, b u32 }\nfunc main() u32 { return 0u32 }\n')):
            only=self.dir/'only.omni'; only.write_text(source,encoding='utf-8')
            w=proc(OMNI,'wave',only); self.assertTrue(w.stdout.startswith(b'(omni-wave 21'),(label,w.stdout[:20]))
            relabelled=self.dir/'only_old.owave'; relabelled.write_bytes(w.stdout.replace(b'(omni-wave 21',b'(omni-wave 20',1))
            result=proc(OMNI,'check',relabelled); self.assertEqual(result.returncode,2,(label,result.stderr)); self.assertIn(b'E_VERSION',result.stderr,label)
        store=proc(OMNI,'memory',path); self.assertEqual(store.returncode,0,store.stderr)
        for derived in (wire,owave,onme): self.assertEqual(proc(OMNI,'memory',derived).stdout,store.stdout,derived.name)
        def record(source:str,name:str)->dict:
            variant=self.dir/'variant.omni'; variant.write_text(source,encoding='utf-8')
            return [n for n in json.loads(proc(OMNI,'memory',variant).stdout)['nuclei'] if n['kind']=='record' and n['name']==name][0]
        plain=record('module t\nstruct S { a u8, b u32 }\nfunc main() u32 { return 0u32 }\n','S')
        packed=record('module t\npacked struct S { a u8, b u32 }\nfunc main() u32 { return 0u32 }\n','S')
        self.assertNotEqual(plain['content_id'],packed['content_id']); self.assertNotEqual(plain['contract_id'],packed['contract_id'])    # packing is part of the identity


class A83KernelSdkContractTests(X64Harness):
    """Core-owned CLI/link fixtures for the observed consumer builder flags; no product sources are built."""

    def test_i386_boot_stack_handoff_and_x64_builder_flags(self)->None:
        source=self.dir/'boot32.omni'
        source.write_text('module boot32\nfunc main() u32 !{port.io,cpu.control} { let x = port.out32(244u32,0u32); return cpu.halt() }\n',encoding='utf-8')
        self.sh(str(OMNI),'emit-llvm',str(source),'--target-profile','baremetal-i386-boot','--service-module','boot32',
                '--entry-section','.text.omni_entry','--entry-address','1048576','--entry-stack','69206016',
                '--entry-handoff-store','16777472','-o','boot32.ll')
        flags=['--target=i386-unknown-none-elf','-ffreestanding','-fno-builtin','-fno-stack-protector','-fno-pic','-fno-pie',
               '-mno-red-zone','-mno-sse','-mno-sse2','-mno-mmx','-mno-80387','-fno-asynchronous-unwind-tables','-fno-unwind-tables','-O2']
        self.sh('clang',*flags,'-c','boot32.ll','-o','boot32.o')
        self.sh('objcopy','-O','elf64-x86-64','boot32.o','boot32.x64.o')
        (self.dir/'boot32.ld').write_text('ENTRY(omni_boot_entry32)\nSECTIONS { . = 0x100000; .text : { *(.text.omni_entry) *(.text*) } .note : { *(.note*) } }\n')
        self.sh('ld','-m','elf_i386','-nostdlib','-T','boot32.ld','boot32.o','-o','boot32.elf')
        self.assertEqual(self.sh('nm','-u','boot32.elf').stdout,b'')
        guest=subprocess.run(['qemu-system-x86_64','-kernel',str(self.dir/'boot32.elf'),'-display','none','-serial','stdio','-no-reboot',
                              '-device','isa-debug-exit,iobase=0xf4,iosize=0x04','-m','128'],capture_output=True,timeout=30)
        self.assertEqual(guest.returncode,1,guest.stderr)
        source=self.dir/'contract.omni'
        source.write_text('module t\nimport rt "rt.omni"\nfunc fault(frame u64) u32 { return 0u32 }\nfunc worker() u32 { return 0u32 }\n'
                          'func main() u32 !{port.io,cpu.control} { return rt.finish(0u32) }\n',encoding='utf-8')
        elf=self.build(source,emit_args=('--exception-handler','t.fault','--exception-resume','--ring3-support',
                                       '--isr-extra-vector','128','--isr-count','48','--thread-entry','t.worker'))
        self.assertEqual(self.boot(elf),(1,''))
        store=self.dir/'contract.omem'
        self.sh(str(OMNI),'memory-pack',str(source),'-o',str(store))
        self.sh(str(OMNI),'memory-summary',str(store))


class A83CrossModuleTraitTests(unittest.TestCase):
    """CP-05 (spec/CROSS_MODULE_TRAITS_CANDIDATE.md): `impl alias.Trait for LocalType`, and library generics instantiated with a type that lives in the
    caller's module (possibly private), without that module becoming an import of the library."""

    LIB=('module shapes\npub trait Area { func area(x Self) u32 }\ntrait Hidden { func h(x Self) u32 }\n'
         'pub func total<T: Area>(a T, b T) u32 {\n  return Area.area<T>(a) + Area.area<T>(b)\n}\n'
         'pub func twice<T: Area>(a T) u32 { return total<T>(a, a) }\n')
    MAIN=('module app\nimport shapes "shapes.omni"\nstruct Sq { s u32 }\nstruct Rect { w u32, h u32 }\n'
          'impl shapes.Area for Sq { func area(x Sq) u32 { return x.s * x.s } }\n'
          'impl shapes.Area for Rect { func area(x Rect) u32 { return x.w * x.h } }\n')

    def setUp(self)->None:
        self.tmp=tempfile.TemporaryDirectory(prefix='omni-a83-xtrait-')
        self.dir=pathlib.Path(self.tmp.name)
        (self.dir/'shapes.omni').write_text(self.LIB,encoding='utf-8')

    def tearDown(self)->None:
        self.tmp.cleanup()

    def program(self,body:str,name:str='app.omni',head:str|None=None)->pathlib.Path:
        path=self.dir/name; path.write_text((head if head is not None else self.MAIN)+'func main() u32 {\n'+body+'}\n',encoding='utf-8'); return path

    def test_a_library_generic_runs_with_impls_that_live_in_the_callers_module(self)->None:
        path=self.program('  return shapes.total<Sq>(Sq { s: 3u32 }, Sq { s: 4u32 }) + shapes.twice<Rect>(Rect { w: 2u32, h: 3u32 }) - 12u32\n')
        evaluated=proc(OMNI,'eval',path); native=self.dir/'app-native'
        self.assertEqual(proc(OMNI,'build',path,'-o',native,'--cache-dir',self.dir/'cache').returncode,0)
        self.assertEqual(evaluated.returncode,25,evaluated.stderr)               # 9 + 16 + 12 - 12
        self.assertEqual(proc(native).returncode,25)

    def test_the_library_does_not_gain_an_import_and_every_representation_agrees(self)->None:
        path=self.program('  return shapes.total<Sq>(Sq { s: 3u32 }, Sq { s: 4u32 })\n')
        wave=proc(OMNI,'wave',path); self.assertEqual(wave.returncode,0,wave.stderr)
        text=wave.stdout.decode()
        text=proc(OMNI,'fmt',path).stdout.decode(); start=text.index('module shapes'); end=len(text)
        self.assertNotIn('import app',text[start:end])  # actual checked module has no reverse import
        owave=self.dir/'app.owave'; owave.write_bytes(wave.stdout)
        wire=self.dir/'app.owire'; self.assertEqual(proc(OMNI,'pack',path,'-o',wire).returncode,0)
        onme=self.dir/'app.onme'; self.assertEqual(proc(OMNI,'onme',path,'-o',onme).returncode,0)
        for derived in (owave,wire):
            self.assertEqual(proc(OMNI,'check',derived).returncode,0,derived.name)           # the generated bodies still resolve after the round trip
        self.assertEqual(proc(OMNI,'wave',owave).stdout,wave.stdout)
        self.assertEqual(proc(OMNI,'eval',owave).returncode,25); self.assertEqual(proc(OMNI,'eval',wire).returncode,25)
        # Capsule rechecking preserves authoring templates and the concrete semantic graph.
        store=proc(OMNI,'memory',path).stdout
        for derived in (owave,wire,onme): self.assertEqual(proc(OMNI,'memory',derived).stdout,store,derived.name)

    def test_generated_spelling_never_grants_private_type_access(self)->None:
        (self.dir/'shapes.omni').write_text(self.LIB+'struct Secret { value u32 }\n',encoding='utf-8')
        for name in ('forge__g_1234','forge__impl_1234'):
            source=('module app\nimport shapes "shapes.omni"\n'
                    'func '+name+'(s shapes.Secret) u32 { return s.value }\n'
                    'func main() u32 { return 0u32 }\n')
            path=self.dir/'forge.omni'; path.write_text(source,encoding='utf-8')
            result=proc(OMNI,'check',path)
            self.assertEqual(result.returncode,2,result.stderr); self.assertIn(b'E_VISIBILITY',result.stderr)
        # Instantiating a generic must not grant privileges to unrelated source types.
        path=self.dir/'forge.omni'
        path.write_text('module app\nimport shapes "shapes.omni"\n'
                        'func forge<T>(x T) u32 { let s shapes.Secret = shapes.Secret { value: 1u32 }; return s.value }\n'
                        'func main() u32 { return forge<u32>(0u32) }\n',encoding='utf-8')
        result=proc(OMNI,'check',path); self.assertEqual(result.returncode,2,result.stderr); self.assertIn(b'E_VISIBILITY',result.stderr)
        # Ordinary serialized functions with generated-looking names get the same strict checker.
        bundled='bundle app { module shapes { struct Secret { value u32 } } module app { import shapes = shapes; func forged__g_123(s shapes.Secret) u32 { return s.value } func main() u32 { return 0u32 } } }'
        capsule='(omni-wave 22 (authoring-source '+json.dumps(bundled)+'))'
        path=self.dir/'forge.owave'; path.write_text(capsule,encoding='utf-8')
        result=proc(OMNI,'check',path); self.assertEqual(result.returncode,2,result.stderr); self.assertIn(b'E_VISIBILITY',result.stderr)

    def test_capsule_downgrade_malformed_and_ordinary_ir_forgery_fail_closed(self)->None:
        path=self.program('  return shapes.total<Sq>(Sq { s: 3u32 }, Sq { s: 4u32 })\n')
        wave=proc(OMNI,'wave',path); self.assertEqual(wave.returncode,0,wave.stderr)
        wire=self.dir/'capsule.owire'; self.assertEqual(proc(OMNI,'pack',path,'-o',wire).returncode,0)
        for old in (18,20,21,23):
            bad=self.dir/'bad.owave'; bad.write_bytes(wave.stdout.replace(b'omni-wave 22',f'omni-wave {old}'.encode(),1))
            result=proc(OMNI,'check',bad); self.assertEqual(result.returncode,2,(old,result.stderr)); self.assertIn(b'E_VERSION',result.stderr)
            data=bytearray(wire.read_bytes()); data[4]=old; bad=self.dir/'bad.owire'; bad.write_bytes(data)
            result=proc(OMNI,'check',bad); self.assertEqual(result.returncode,2,(old,result.stderr)); self.assertIn(b'E_VERSION',result.stderr)
        for data in (wire.read_bytes()[:-1],wire.read_bytes()+b'junk'):
            bad=self.dir/'bad.owire'; bad.write_bytes(data); self.assertEqual(proc(OMNI,'check',bad).returncode,2)
        plain=self.dir/'plain.omni'
        plain.write_text('bundle app { module shapes { pub struct Secret { value u32 } } module app { import shapes = shapes; func forged__g_123(s shapes.Secret) u32 { return s.value } func main() u32 { return 0u32 } } }',encoding='utf-8')
        original=proc(OMNI,'wave',plain); self.assertEqual(original.returncode,0,original.stderr)
        bad=self.dir/'bad.owave'; bad.write_bytes(original.stdout.replace(b'(struct Secret (visibility public)',b'(struct Secret (visibility private)',1))
        result=proc(OMNI,'check',bad); self.assertEqual(result.returncode,2,result.stderr); self.assertIn(b'E_VISIBILITY',result.stderr)
        ordinary=self.dir/'ordinary.owire'; self.assertEqual(proc(OMNI,'pack',plain,'-o',ordinary).returncode,0)
        data=bytearray(ordinary.read_bytes()); offset=data.index(b'Secret')+len(b'Secret'); self.assertEqual(data[offset],1); data[offset]=0
        bad=self.dir/'bad.owire'; bad.write_bytes(data); result=proc(OMNI,'check',bad)
        self.assertEqual(result.returncode,2,result.stderr); self.assertIn(b'E_VISIBILITY',result.stderr)

    def test_orphans_privacy_and_missing_pieces_are_rejected(self)->None:
        cases=[('foreign trait for a foreign type',self.MAIN+'impl shapes.Area for u32 { func area(x u32) u32 { return x } }\n',b'E_TRAIT_COHERENCE'),
               ('private trait of another module',self.MAIN+'struct Other { v u32 }\nimpl shapes.Hidden for Other { func h(x Other) u32 { return x.v } }\n',b'E_VISIBILITY'),
               ('alias that is not imported',self.MAIN+'struct Other { v u32 }\nimpl nowhere.Area for Other { func area(x Other) u32 { return x.v } }\n',b'E_TRAIT'),
               ('trait that does not exist',self.MAIN+'struct Other { v u32 }\nimpl shapes.Nothing for Other { func area(x Other) u32 { return x.v } }\n',b'E_TRAIT'),
               ('method missing from the impl',self.MAIN+'struct Other { v u32 }\nimpl shapes.Area for Other { }\n',b'E_TRAIT_METHOD'),
               ('impl exceeds the trait capabilities',self.MAIN+'struct Other { v u32 }\nimpl shapes.Area for Other { func area(x Other) u32 !{memory.write} { return x.v } }\n',b'E_TRAIT_EFFECT'),
               ('duplicate impl',self.MAIN+'impl shapes.Area for Sq { func area(x Sq) u32 { return 0u32 } }\n',b'E_TRAIT_COHERENCE')]
        for label,head,code in cases:
            path=self.program('  return 0u32\n',head=head)
            result=proc(OMNI,'check',path); self.assertEqual(result.returncode,2,(label,result.stderr)); self.assertIn(code,result.stderr,(label,result.stderr))
        missing=self.program('  return shapes.total<Other>(Other { v: 1u32 }, Other { v: 2u32 })\n',head=self.MAIN+'struct Other { v u32 }\n')
        result=proc(OMNI,'check',missing); self.assertEqual(result.returncode,2,result.stderr); self.assertIn(b'E_GENERIC_CONSTRAINT',result.stderr)
        # a private type of the caller is a legal generic argument: the caller has validated it, the library only carries its canonical key
        private=self.program('  return shapes.total<Sq>(Sq { s: 1u32 }, Sq { s: 2u32 })\n'); self.assertEqual(proc(OMNI,'check',private).returncode,0)


class A83X64CallbackTests(X64Harness):
    """CP-06 (spec/CALLBACK_REGISTRY_CANDIDATE.md): register / use later / retire a callable with a retained environment, safe against a call in flight on
    another CPU, with exact disposal and detection of late calls. The callable family is a plain environment record plus a Handler impl (static selection)."""

    def lines(self,serial:str)->list[str]:
        return serial.split('\n')[:-1]

    def test_register_use_retire_late_and_reused_slot_calls_on_one_cpu(self)->None:
        rc,serial=self.boot(self.build(self.dir/'cb_basic.omni'))
        # 15, 16 = base 10 + x; disposed once; late call: 1001 (slot not live); second registration reuses the slot: the OLD handle is 1002 (generation), the new
        # handle works (28); a handle for an idle address is refused (1001), a token whose address bits were moved on the live slot is refused (1003); disposed
        # twice in total; first and last byte of the environment are poisoned (221); a slot whose generations are spent has no next generation (0): it is never wrapped to 1 (009A CBREG-01)
        self.assertEqual((rc,self.lines(serial)),(1,['15','16','1','1001','1002','28','1001','1003','2','221','221','0']),serial)

    def test_registering_over_a_live_slot_or_beyond_the_handle_range_ends_the_guest_with_93(self)->None:
        head=('module t\nimport rt "rt.omni"\nimport cbreg "cbreg.omni"\nstruct Adder { base u32, closed u64 }\n'
              'impl cbreg.Handler for Adder {\n  func call(h Adder, x u32) u32 !{memory.raw} { return h.base + x }\n  func dispose(h Adder) u32 !{memory.atomic} { return 0u32 }\n}\n'
              'func main() u32 !{memory.raw,memory.atomic,port.io,cpu.control} {\n')
        env='Adder { base: 1u32, closed: 6094976u64 }'
        cases=[('live_slot','  let a = cbreg.register<Adder>(6094848u64, '+env+')\n  let b = cbreg.register<Adder>(6094848u64, '+env+')\n  let x u32 = cbreg.retire<Adder>(move(a), 6095360u64, 6095424u64, 10u32)\n  let y u32 = cbreg.retire<Adder>(move(b), 6095360u64, 6095424u64, 10u32)\n'),
               ('slot_beyond_2_pow_40','  let a = cbreg.register<Adder>(1099511627776u64, '+env+')\n  let x u32 = cbreg.retire<Adder>(move(a), 6095360u64, 6095424u64, 10u32)\n')]
        for name,body in cases:
            path=self.dir/f'{name}.omni'; path.write_text(head+body+'  return rt.finish(0u32)\n}\n',encoding='utf-8')
            rc,serial=self.boot(self.build(path)); self.assertEqual(rc,(93<<1)|1,(name,rc,serial))

    def test_registration_is_published_only_after_environment_writes(self)->None:
        result=self.emit(self.dir/'cb_basic.omni'); self.assertEqual(result.returncode,0,result.stderr)
        ir=(self.dir/'prog.ll').read_text(encoding='utf-8')
        functions=re.findall(r'^define[^\n]*@omni\.fn\.cbreg\.register__g_[0-9a-f]+[^\n]*\{\n(.*?)^}',ir,re.M|re.S)
        self.assertEqual(len(functions),1,ir[:1000]); body=functions[0]
        writes=list(re.finditer(r'store volatile ',body))
        publications=list(re.finditer(r'store atomic volatile i32 1, ptr [^\n]+ release, align 4',body))
        self.assertTrue(writes,body); self.assertEqual(len(publications),1,body)
        self.assertGreater(publications[0].start(),writes[-1].start(),body)

    def test_callback_wrong_nominal_type_is_refused_before_read_or_disposal(self)->None:
        head=('module t\nimport rt "rt.omni"\nimport cbreg "cbreg.omni"\n'
              'struct A { v u64 }\nstruct B { v u64 }\nstruct Big { a u64, b u64, c u64 }\n')
        for name in ('A','B','Big'):
            head+=('impl cbreg.Handler for '+name+' {\n'
                   '  func call(h '+name+', x u32) u32 !{memory.raw} { return 99u32 }\n'
                   '  func dispose(h '+name+') u32 !{memory.atomic} { return 0u32 }\n}\n')
        for wrong in ('B','Big'):
            body=('func main() u32 !{io.print,memory.raw,memory.atomic,port.io,cpu.control} {\n'
                  '  let g0 u32 = atomic.store32(6095360u64, 1u32, 4u32)\n'
                  '  let r = cbreg.register<A>(6094848u64, A { v: 1u64 })\n'
                  '  let token = cbreg.handle(borrow(r))\n'
                  '  let call = cbreg.fire<'+wrong+'>(6094848u64, token, 0u32)\n'
                  '  match call { Ok(v) { print(v) } Err(code) { print(code) } }\n'
                  '  let closed = cbreg.retire<A>(move(r), 6095360u64, 6095424u64, 10u32)\n'
                  '  return rt.finish(0u32)\n}\n')
            path=self.dir/'wrongtype.omni'; path.write_text(head+body,encoding='utf-8')
            rc,serial=self.boot(self.build(path)); self.assertEqual((rc,serial),(1,'4\n'),wrong)
            path.write_text((head+body).replace('cbreg.retire<A>','cbreg.retire<'+wrong+'>'),encoding='utf-8')
            rc,serial=self.boot(self.build(path)); self.assertEqual((rc,serial),(187,'4\n'),wrong)

    def test_a_retired_environment_is_never_seen_by_a_call_in_flight_on_the_other_cpu(self)->None:
        elf=self.build(self.dir/'cb_smp.omni',ap_main=True)
        for attempt in range(2):
            rc,serial=self.boot(elf,smp=2)
            # no call saw a torn or poisoned environment; more than 100 calls were served; every one of the 2000 environments was disposed exactly once; slot idle
            self.assertEqual((rc,self.lines(serial)),(1,['0','1','2000','0']),(attempt,serial))

    def test_without_the_quiescence_wait_a_call_in_flight_sees_the_poisoned_environment(self)->None:
        library=(self.dir/'cbreg.omni').read_text(encoding='utf-8')
        needle='  let e u32 = epoch.advance(gen)\n  let w u32 = epoch.wait(reader_slot, e, attempts)\n'
        self.assertIn(needle,library)
        (self.dir/'cbreg.omni').write_text(library.replace(needle,''),encoding='utf-8')
        elf=self.build(self.dir/'cb_smp.omni',ap_main=True)
        seen=[]
        for attempt in range(3):
            rc,serial=self.boot(elf,smp=2); seen.append(int(self.lines(serial)[0]))
        self.assertTrue(all(v>0 for v in seen),seen)

    def test_the_compiler_enforces_registration_obligations_and_environment_shape(self)->None:
        head=('module t\nimport rt "rt.omni"\nimport cbreg "cbreg.omni"\nstruct Adder { base u32, closed u64 }\n'
              'impl cbreg.Handler for Adder {\n  func call(h Adder, x u32) u32 !{memory.raw} { return h.base + x }\n  func dispose(h Adder) u32 !{memory.atomic} { return 0u32 }\n}\n')
        main='func main() u32 !{memory.raw,memory.atomic,port.io,cpu.control} {\n'
        reg='  let r = cbreg.register<Adder>(6094848u64, Adder { base: 1u32, closed: 6094976u64 })\n'
        cases=[('registration never retired',head+main+reg+'  return 0u32\n}\n',b'E_RESOURCE_UNCONSUMED'),
               ('registration retired twice',head+main+reg+'  let a u32 = cbreg.retire<Adder>(move(r), 6095360u64, 6095424u64, 10u32)\n  let b u32 = cbreg.retire<Adder>(move(r), 6095360u64, 6095424u64, 10u32)\n  return 0u32\n}\n',b'E_RESOURCE_MOVED'),
               ('early return leaks the registration',head+main+reg+'  if atomic.load32(6095488u64, 4u32) == 1u32 {\n    return 1u32\n  }\n  let a u32 = cbreg.retire<Adder>(move(r), 6095360u64, 6095424u64, 10u32)\n  return 0u32\n}\n',b'E_RESOURCE_UNCONSUMED'),
               ('environment that is not plain data (Text)','module t\nimport rt "rt.omni"\nimport cbreg "cbreg.omni"\nstruct Bad { name Text }\n'
                'impl cbreg.Handler for Bad {\n  func call(h Bad, x u32) u32 !{memory.raw} { return x }\n  func dispose(h Bad) u32 !{memory.atomic} { return 0u32 }\n}\n'
                +main+'  let r = cbreg.register<Bad>(6094848u64, Bad { name: "x" })\n  let a u32 = cbreg.retire<Bad>(move(r), 6095360u64, 6095424u64, 10u32)\n  return 0u32\n}\n',b'E_LAYOUT'),
               ('handler that needs more authority than the trait grants',head.replace('func call(h Adder, x u32) u32 !{memory.raw} { return h.base + x }','func call(h Adder, x u32) u32 !{memory.raw,memory.write} { return h.base + x }')+main+'  return 0u32\n}\n',b'E_TRAIT_EFFECT'),
               ('a type without an impl cannot be registered',head+'struct Mute { v u32 }\n'+main+'  let r = cbreg.register<Mute>(6094848u64, Mute { v: 1u32 })\n  let a u32 = cbreg.retire<Mute>(move(r), 6095360u64, 6095424u64, 10u32)\n  return 0u32\n}\n',b'E_GENERIC_CONSTRAINT')]
        for label,source,code in cases:
            path=self.dir/'case.omni'; path.write_text(source,encoding='utf-8')
            result=self.emit(path)
            self.assertEqual(result.returncode,2,(label,result.stderr)); self.assertIn(code,result.stderr,(label,result.stderr))
            self.assertFalse((self.dir/'prog.ll').exists(),label)


class A83LinearEnumTests(unittest.TestCase):
    """CP-01 (spec/OWNERSHIP_COMPOSITION_CANDIDATE.md): an enum with a Resource payload is a linear value, pending like Result/Option<Resource>: consumed
    exactly once by match, by being moved into a call, or by being returned. It may not hide inside another container."""

    SLOT=('enum Slot { Empty, Full(Resource<Buffer>) }\n'
          'func make(full bool) Slot !{memory.write} {\n  if full {\n    let first Result<Resource<Buffer>,u32> = buffer.alloc(3u32)\n    match first {\n'
          '      Ok(buf) { return Slot.Full(move(buf)) }\n      Err(code) { return Slot.Empty() }\n    }\n  }\n  return Slot.Empty()\n}\n')
    TOK=('struct Tok { h u64 }\nenum Held { Nothing, Has(Resource<Tok>) }\n'
         'func mint() Resource<Tok> { return resource.seal(Tok { h: 7u64 }) }\n'
         'func eat(t Resource<Tok>) u64 {\n  let r = resource.unseal(move(t))\n  return r.h\n}\n'
         'func hold(on bool) Held {\n  if on { return Held.Has(mint()) }\n  return Held.Nothing()\n}\n')

    def setUp(self)->None:
        self.tmp=tempfile.TemporaryDirectory(prefix='omni-a83-linenum-')
        self.dir=pathlib.Path(self.tmp.name)

    def tearDown(self)->None:
        self.tmp.cleanup()

    def source(self,text:str,name:str='program.omni')->pathlib.Path:
        path=self.dir/name
        path.write_text('module t\n'+text,encoding='utf-8')
        return path

    def both(self,path:pathlib.Path)->tuple[int,int]:
        evaluated=proc(OMNI,'eval',path)
        native=self.dir/(path.stem+'-native')
        built=proc(OMNI,'build',path,'-o',native,'--cache-dir',self.dir/'cache')
        self.assertEqual(built.returncode,0,built.stderr)
        return evaluated.returncode,proc(native).returncode

    def rejected(self,text:str,code:bytes,label:str='')->None:
        path=self.source(text,'bad.omni'); result=proc(OMNI,'check',path)
        self.assertEqual(result.returncode,2,(label,result.stderr)); self.assertIn(code,result.stderr,(label,result.stderr))
        output=self.dir/'never'
        self.assertEqual(proc(OMNI,'build',path,'-o',output,'--cache-dir',self.dir/'cache').returncode,2,label)
        self.assertFalse(output.exists(),label)

    def test_full_and_empty_variants_are_matched_with_evaluator_native_parity(self)->None:
        text=self.SLOT+('func main() u32 !{memory.read,memory.write} {\n  var total u32 = 0u32\n  let a = make(true)\n'
                        '  match a {\n    Full(r) { total = total + buffer.len(borrow(r)) }\n    Empty { total = total + 100u32 }\n  }\n'
                        '  let b = make(false)\n  match b {\n    Full(r) { total = total + 100u32 }\n    Empty { total = total + 20u32 }\n  }\n  return total + 19u32\n}\n')
        self.assertEqual(self.both(self.source(text)),(42,42))                         # 3 + 20 + 19

    def test_the_value_moves_into_a_call_and_out_of_a_function(self)->None:
        text=self.SLOT+('func finish(s Slot) u32 !{memory.read,memory.write} {\n  match s {\n    Full(r) { return buffer.release(move(r)) + 40u32 }\n    Empty { return 1u32 }\n  }\n}\n'
                        'func main() u32 !{memory.read,memory.write} {\n  let s = make(true)\n  return finish(s) + 2u32 + finish(make(false)) - 1u32\n}\n')
        self.assertEqual(self.both(self.source(text)),(42,42))                         # finish(full) = release (0) + 40, finish(empty) = 1: 40 + 2 + 1 - 1

    def test_no_resource_is_leaked_on_any_path_over_3000_cycles(self)->None:
        text=self.SLOT+('func main() u32 !{memory.read,memory.write} {\n  var i u32 = 0u32\n  var live u32 = 0u32\n'
                        '  for i < 3000u32 {\n    let s = make(true)\n    match s {\n      Full(r) { live = live + 1u32 }\n      Empty { live = live }\n    }\n'
                        '    let t = make(false)\n    match t {\n      Full(r) { live = live + 1000u32 }\n      Empty { live = live }\n    }\n    i = i + 1u32\n  }\n'
                        '  if live == 3000u32 { return 42u32 }\n  return 1u32\n}\n')
        self.assertEqual(self.both(self.source(text)),(42,42))                         # 1024 runtime slots: a single leak per cycle would change the result

    def test_a_nominal_resource_payload_must_be_consumed_in_the_arm(self)->None:
        good=self.TOK+('func main() u32 {\n  let h = hold(true)\n  match h {\n    Has(t) { return u32(eat(move(t))) + 35u32 }\n    Nothing { return 1u32 }\n  }\n}\n')
        self.assertEqual(self.both(self.source(good)),(42,42))
        self.rejected(self.TOK+('func main() u32 {\n  let h = hold(true)\n  match h {\n    Has(t) { return 1u32 }\n    Nothing { return 2u32 }\n  }\n}\n'),b'E_RESOURCE_UNCONSUMED','nominal payload dropped in the arm')

    def test_linear_enum_rules_are_rejected_without_artifact(self)->None:
        wrap=lambda body:self.SLOT+'func main() u32 !{memory.read,memory.write} {\n'+body+'}\n'
        cases=(
            ('unmatched at scope exit',wrap('  let s = make(true)\n  return 0u32\n'),b'E_RESULT_UNHANDLED'),
            ('used twice',wrap('  let s = make(true)\n  let a = s\n  let b = s\n  return 0u32\n'),b'E_RESULT_MOVED'),
            ('consumed inside a loop it does not own',wrap('  let s = make(true)\n  var i u32 = 0u32\n  for i < 2u32 {\n    match s {\n      Full(r) { i = i + 1u32 }\n      Empty { i = i + 1u32 }\n    }\n  }\n  return 0u32\n'),b'E_RESULT_FLOW'),
            ('abandoned struct field',self.SLOT+'struct Holder { s Slot }\nfunc bad(h Holder) u32 { return 0u32 }\nfunc main() u32 { return 0u32 }\n',b'E_RESULT_UNHANDLED'),
            ('inside Option must be consumed',self.SLOT+'func f(o Option<Slot>) u32 { return 0u32 }\nfunc main() u32 { return 0u32 }\n',b'E_RESULT_UNHANDLED'),
            ('tuple element',self.SLOT+'func f(o Tuple<u32,Slot>) u32 { return 0u32 }\nfunc main() u32 { return 0u32 }\n',b'E_RESULT_UNHANDLED'),
            ('array element',self.SLOT+'func f(o Array<Slot,2>) u32 { return 0u32 }\nfunc main() u32 { return 0u32 }\n',b'E_RESULT_UNHANDLED'),
            ('borrow payload','enum Bad { B(Borrow<Buffer>) }\nfunc main() u32 { return 0u32 }\n',b'E_TYPE'),
        )
        for label,text,code in cases:
            with self.subTest(label): self.rejected(text,code,label)

    def test_nominal_layout_identity_is_deterministic_and_not_just_size(self)->None:
        text=('struct A { v u64 }\nstruct B { v u64 }\n'
              'func main() u32 {\n  var different u32 = 0u32\n'
              '  for i in 0u32..1u32 { different = different }\n')
        for word in range(4):
            text+=('  if layout.identity<A>('+str(word)+'u32) != layout.identity<B>('+str(word)+'u32) { different = different + 1u32 }\n')
        text+='  if different == 4u32 { return 42u32 }\n  return 1u32\n}\n'
        path=self.source(text); self.assertEqual(self.both(path),(42,42))
        expected=proc(OMNI,'eval',path).returncode
        wave=proc(OMNI,'wave',path); self.assertEqual(wave.returncode,0,wave.stderr)
        ow=self.dir/'id.owave'; ow.write_bytes(wave.stdout)
        wire=self.dir/'id.owire'; self.assertEqual(proc(OMNI,'pack',path,'-o',wire).returncode,0)
        onme=self.dir/'id.onme'; self.assertEqual(proc(OMNI,'onme',path,'-o',onme).returncode,0)
        for rep in (ow,wire,onme):
            self.assertEqual(proc(OMNI,'eval',rep).returncode,expected,rep.name)
            self.assertEqual(proc(OMNI,'memory',rep).stdout,proc(OMNI,'memory',path).stdout,rep.name)
        for argument in ('4u32','4294967295u32','true'):
            self.rejected('struct A { v u64 }\nfunc main() u32 { let id = layout.identity<A>('+argument+') return 0u32 }\n',b'E_')

    OWNED_RECORD=('struct Owned { r Resource<Buffer> }\nenum Bag { Empty, Full(Owned) }\n'
                  'func make_record() Bag !{memory.write} {\n  let allocated = buffer.alloc(4u32)\n  match allocated {\n'
                  '    Ok(b) { return Bag.Full(Owned { r: move(b) }) }\n    Err(code) { return Bag.Empty() }\n  }\n}\n'
                  'func consume_record(b Bag) u32 !{memory.read,memory.write} {\n  match b {\n'
                  '    Full(o) { return buffer.len(borrow(o.r)) }\n    Empty { return 0u32 }\n  }\n}\n')

    def test_inferred_products_cannot_hide_linear_values(self)->None:
        for expression in ('tuple(make(true))','array(make(true))','array.fill(make(true),2u32)',
                           'tuple(slot(true))','array(slot(true))','array.fill(slot(true),2u32)'):
            text=self.SLOT+A83OptionResourceTests.SLOT+'func main() u32 !{memory.read,memory.write} { let hidden='+expression+'; return 0u32 }\n'
            self.rejected(text,b'E_RESULT_UNHANDLED' if expression.startswith(('tuple(','array(')) else b'E_PRODUCT_LINEAR',expression)
        # CP-01: Array<Owned,2> (Resource<Buffer> leaves, no pending sum) is an owning product now; the parameter is cleaned on exit.
        accepted=self.source(self.OWNED_RECORD+'func f(x Array<Owned,2>) u32 { return 0u32 }\nfunc main() u32 { return 0u32 }\n')
        self.assertEqual(proc(OMNI,'check',accepted).returncode,0)
        for typ in ('Array<Bag,2>',):
            self.rejected(self.OWNED_RECORD+'func f(x '+typ+') u32 { return 0u32 }\nfunc main() u32 { return 0u32 }\n',b'E_RESULT_UNHANDLED',typ)
        admitted=self.OWNED_RECORD+'func take(x Tuple<Owned,u32>) u32 { return tuple.get(x,1u32) }\nfunc main() u32 !{memory.read,memory.write} { let b = make_record(); match b { Full(o) { return take(tuple(move(o),42u32)) } Empty { return 0u32 } } }\n'
        self.assertEqual(self.both(self.source(admitted)),(42,42))
        for typ in ('Option<Result<u32,u32>>',):
            self.rejected(self.OWNED_RECORD+'func f(x '+typ+') u32 { return 0u32 }\nfunc main() u32 { return 0u32 }\n',b'E_RESULT_UNHANDLED',typ)
        self.rejected(self.OWNED_RECORD+'func f(x Option<Owned>) u32 { return 0u32 }\nfunc main() u32 { return 0u32 }\n',b'E_RESULT_UNHANDLED')

    def test_owned_match_payload_cannot_be_discarded_as_wildcard(self)->None:
        self.rejected(self.TOK+'func main() u32 { let h=hold(true); match h { Has(_) { return 0u32 } Nothing { return 0u32 } } }\n',b'E_RESOURCE_UNCONSUMED')
        self.rejected(self.SLOT+'func main() u32 !{memory.write} { let h=make(true); match h { Full(_) { return 0u32 } Empty { return 0u32 } } }\n',b'E_RESOURCE_UNCONSUMED')
        self.rejected(self.OWNED_RECORD+'func main() u32 !{memory.write} { let h=make_record(); match h { Full(_) { return 0u32 } Empty { return 0u32 } } }\n',b'E_RESOURCE_UNCONSUMED')
        copy='func main() u32 { let x=Some<u32>(1u32); match x { Some(_) { return 42u32 } None { return 1u32 } } }\n'
        self.assertEqual(self.both(self.source(copy)),(42,42))

    def test_enum_record_payload_keeps_recursive_ownership_and_cleanup(self)->None:
        main=('func main() u32 !{memory.read,memory.write} { var i u32=0u32; var total u32=0u32;\n'
              'for i < 3000u32 { let value=make_record(); total=total+consume_record(value); i=i+1u32 }\n'
              'if total == 12000u32 { return 42u32 }\nreturn 1u32 }\n')
        path=self.source(self.OWNED_RECORD+main); self.assertEqual(self.both(path),(42,42))
        for body,code in (('let a=make_record(); let b=a; let c=a; return 0u32',b'E_RESULT_MOVED'),
                          ('let a=make_record(); return 0u32',b'E_RESULT_UNHANDLED'),
                          ('var a=make_record(); return consume_record(a)',b'E_RESULT_MUTABLE')):
            self.rejected(self.OWNED_RECORD+'func main() u32 !{memory.read,memory.write} { '+body+' }\n',code)
        wave=proc(OMNI,'wave',path); self.assertEqual(wave.returncode,0,wave.stderr); self.assertTrue(wave.stdout.startswith(b'(omni-wave 21'))
        ow=self.dir/'record.owave'; ow.write_bytes(wave.stdout)
        wire=self.dir/'record.owire'; self.assertEqual(proc(OMNI,'pack',path,'-o',wire).returncode,0)
        onme=self.dir/'record.onme'; self.assertEqual(proc(OMNI,'onme',path,'-o',onme).returncode,0)
        memory=proc(OMNI,'memory',path); self.assertEqual(memory.returncode,0,memory.stderr)
        for derived in (ow,wire,onme):
            self.assertEqual(proc(OMNI,'memory',derived).stdout,memory.stdout,derived.name)
        for old in (18,20):
            bad=self.dir/'old.owave'; bad.write_bytes(wave.stdout.replace(b'omni-wave 21',f'omni-wave {old}'.encode(),1))
            result=proc(OMNI,'check',bad); self.assertEqual(result.returncode,2,result.stderr); self.assertIn(b'E_VERSION',result.stderr)
            raw=bytearray(wire.read_bytes()); raw[4]=old; bad=self.dir/'old.owire'; bad.write_bytes(raw)
            result=proc(OMNI,'check',bad); self.assertEqual(result.returncode,2,result.stderr); self.assertIn(b'E_VERSION',result.stderr)

    def test_pending_values_cannot_be_overwritten_through_var(self)->None:
        buffer=A83OptionResourceTests.SLOT+'func main() u32 !{memory.read,memory.write} { var o = slot(true); o = None<Resource<Buffer>>(); match o { Some(r) { let x=buffer.release(move(r)); return 0u32 } None { return 0u32 } } }\n'
        nominal=A83NominalMergeTests.TOK+A83NominalMergeTests.NOMINAL_SLOT+'func main() u32 { var o=held(true); o=held(false); return finish(o) }\n'
        enum=self.SLOT+'func main() u32 !{memory.read,memory.write} { var s=make(true); s=Slot.Empty(); match s { Full(r) { return 0u32 } Empty { return 0u32 } } }\n'
        for label,text in (('Buffer Option',buffer),('nominal Option',nominal),('resource enum',enum)):
            self.rejected(text,b'E_RESULT_MUTABLE',label)
        ordinary='enum Copy { A, B }\nfunc main() u32 { var o=Some<u32>(1u32); o=None<u32>(); var e=Copy.A(); e=Copy.B(); match o { Some(v) { return 1u32 } None { match e { A { return 1u32 } B { return 42u32 } } } } }\n'
        self.assertEqual(self.both(self.source(ordinary)),(42,42))

    def test_early_return_preserves_the_linear_obligation(self)->None:
        text=self.SLOT+('func main() u32 !{memory.write} {\n  let s = make(true)\n  if true { return 1u32 }\n'
                        '  match s { Full(r) { return 0u32 } Empty { return 0u32 } }\n}\n')
        self.rejected(text,b'E_RESULT_UNHANDLED','early return with live enum')

    def test_a_linear_enum_cannot_be_captured_by_a_closure(self)->None:
        captured=self.SLOT+('func main() u32 !{memory.write} {\n  let s = make(true)\n'
                            '  return closure(y u32) u32 { match s { Full(r) { return y } Empty { return y } } }(1u32)\n}\n')
        result=proc(OMNI,'check',self.source(captured,'cap.omni'))
        self.assertEqual(result.returncode,2,result.stderr); self.assertIn(b'E_CLOSURE_CAPTURE',result.stderr)

    def test_representations_fence_and_round_trip(self)->None:
        text=self.SLOT+'func main() u32 !{memory.read,memory.write} {\n  let s = make(true)\n  match s {\n    Full(r) { return buffer.len(borrow(r)) }\n    Empty { return 0u32 }\n  }\n}\n'
        path=self.source(text)
        wave=proc(OMNI,'wave',path); self.assertEqual(wave.returncode,0,wave.stderr); self.assertTrue(wave.stdout.startswith(b'(omni-wave 21'),wave.stdout[:20])
        wire=self.dir/'p.owire'; self.assertEqual(proc(OMNI,'pack',path,'-o',wire).returncode,0); self.assertEqual(wire.read_bytes()[:8],b'OMCX\x15\x00\x00\x00')
        owave=self.dir/'p.owave'; owave.write_bytes(wave.stdout)
        onme=self.dir/'p.onme'; self.assertEqual(proc(OMNI,'onme',path,'-o',onme).returncode,0)
        for derived in (owave,wire): self.assertEqual(proc(OMNI,'check',derived).returncode,0,derived.name)
        self.assertEqual(proc(OMNI,'wave',owave).stdout,wave.stdout)
        store=proc(OMNI,'memory',path).stdout
        for derived in (owave,wire,onme): self.assertEqual(proc(OMNI,'memory',derived).stdout,store,derived.name)
        for old in (18,19,20):
            relabelled=self.dir/f'old{old}.owave'; relabelled.write_bytes(wave.stdout.replace(b'(omni-wave 21',f'(omni-wave {old}'.encode(),1))
            result=proc(OMNI,'check',relabelled); self.assertEqual(result.returncode,2,(old,result.stderr)); self.assertIn(b'E_VERSION',result.stderr,old)
            raw=bytearray(wire.read_bytes()); raw[4]=old; rw=self.dir/f'old{old}.owire'; rw.write_bytes(bytes(raw))
            result=proc(OMNI,'check',rw); self.assertEqual(result.returncode,2,(old,result.stderr)); self.assertIn(b'E_VERSION',result.stderr,old)
        # the declaration alone (no use) is new semantics too
        only=self.source(self.SLOT+'func main() u32 { return 0u32 }\n','only.omni')
        w=proc(OMNI,'wave',only); self.assertTrue(w.stdout.startswith(b'(omni-wave 21'),w.stdout[:20])


class A83X64PinTests(X64Harness):
    """CP-14 third slice (spec/NO_MIGRATION_CANDIDATE.md): a pin guard detects that a context was resumed on another CPU. Prevention is a scheduler
    policy and is not claimed."""

    THREAD=('--thread-entry','t.worker')

    def lines(self,serial:str)->list[str]:
        return serial.split('\n')[:-1]

    def variant(self,name:str,mode:int,strict:bool=False)->pathlib.Path:
        text=(self.dir/'pin_migrate.omni').read_text(encoding='utf-8')
        self.assertIn('  let mode u32 = 0u32\n',text)
        text=text.replace('  let mode u32 = 0u32\n',f'  let mode u32 = {mode}u32\n')
        if strict:
            self.assertIn('pin.exit(move(g))',text); text=text.replace('pin.exit(move(g))','pin.exit_strict(move(g))')
        path=self.dir/f'{name}.omni'; path.write_text(text,encoding='utf-8'); return path

    def test_a_section_resumed_on_another_cpu_is_reported_in_both_directions(self)->None:
        # status 10 + (0 = same CPU, 1 = moved); then the CPU id at entry and at exit; then "thread finished", then the CPU that prints the report (always 0)
        for name,mode,expected in (('cpu0_to_cpu1',0,['11','0','1','1','0']),('cpu1_to_cpu0',2,['11','1','0','1','0']),('stays_on_cpu0',1,['10','0','0','1','0'])):
            elf=self.build(self.variant(name,mode),ap_main=True,emit_args=self.THREAD)
            for attempt in range(2):
                rc,serial=self.boot(elf,smp=2)
                self.assertEqual((rc,self.lines(serial)),(1,expected),(name,attempt,serial))

    def test_strict_exit_ends_the_guest_when_the_context_moved_and_not_otherwise(self)->None:
        rc,serial=self.boot(self.build(self.variant('strict_moved',0,strict=True),ap_main=True,emit_args=self.THREAD),smp=2)
        self.assertEqual(rc,(94<<1)|1,(rc,serial))                 # exit value 94: never continues with CPU-local data
        rc,serial=self.boot(self.build(self.variant('strict_stays',1,strict=True),ap_main=True,emit_args=self.THREAD),smp=2)
        self.assertEqual((rc,self.lines(serial)),(1,['10','0','0','1','0']),serial)

    def test_the_compiler_enforces_that_every_pinned_section_is_ended_exactly_once(self)->None:
        head='module t\nimport rt "rt.omni"\nimport pin "pin.omni"\nfunc main() u32 !{port.io,cpu.control} {\n'
        cases=[('leaked section',head+'  let g = pin.enter()\n  return 0u32\n}\n',b'E_RESOURCE_UNCONSUMED'),
               ('ended twice',head+'  let g = pin.enter()\n  let a u32 = pin.exit(move(g))\n  let b u32 = pin.exit(move(g))\n  return 0u32\n}\n',b'E_RESOURCE_MOVED'),
               ('early return leaks',head+'  let g = pin.enter()\n  if pin.cpu_id() == 1u32 {\n    return 1u32\n  }\n  let a u32 = pin.exit(move(g))\n  return 0u32\n}\n',b'E_RESOURCE_UNCONSUMED')]
        for label,source,code in cases:
            path=self.dir/'case.omni'; path.write_text(source,encoding='utf-8')
            result=self.emit(path)
            self.assertEqual(result.returncode,2,(label,result.stderr)); self.assertIn(code,result.stderr,(label,result.stderr))
            self.assertFalse((self.dir/'prog.ll').exists(),label)
        ok=self.dir/'ok.omni'; ok.write_text(head+'  let g = pin.enter()\n  let a u32 = pin.exit(move(g))\n  return rt.finish(a)\n}\n',encoding='utf-8')
        self.assertEqual(self.emit(ok).returncode,0)


class A83X64ContextTests(X64Harness):
    """Cooperative context switch (CP-12 first slice; TARGET_BAREMETAL_PROFILE_CANDIDATE.md K3). The scheduler is the test's main; Core
    provides only cpu.switch_context, cpu.thread_trampoline and --thread-entry. Single vCPU, no preemption, no FPU/SSE or TLS state yet."""

    THREAD=('--thread-entry','t.worker')

    def test_two_threads_alternate_and_each_keeps_its_own_state(self)->None:
        elf=self.build(self.dir/'ctx_switch.omni',emit_args=self.THREAD)
        rc,serial=self.boot(elf)
        # thread 1 ends at 1000 + 5000, thread 2 at 2000 + 5000; main completed 5001 rounds; 10002 switches in each direction
        self.assertEqual((rc,serial.split('\n')[:-1]),(1,['6000','7000','5001']),serial)
        machine=self.sh('objdump','-d','--no-show-raw-insn','-M','intel','payload.elf').stdout.decode()
        body=machine.split('<omni_switch_context>:')[1].split('\n\n')[0]
        for reg in ('rbx','rbp','r12','r13','r14','r15','rsp'):
            self.assertRegex(body,rf'mov\s+QWORD PTR \[rdi(\+0x[0-9a-f]+)?\],{reg}',reg)   # every callee-saved register is saved ...
            self.assertRegex(body,rf'mov\s+{reg},QWORD PTR \[rsi(\+0x[0-9a-f]+)?\]',reg)   # ... and loaded from the other context
        self.assertIn('ret',body)
        # ABI: a fresh context starts after a `ret` that leaves rsp = 8 (mod 16); the trampoline must align it before `call`, because SysV
        # requires rsp + 8 = 0 (mod 16) at function entry. Nothing in a gpr image notices (no aligned stack accesses), an sse2 image would.
        trampoline=machine.split('<omni_thread_trampoline>:')[1].split('\n\n')[0]
        self.assertRegex(trampoline,r'and\s+rsp,0xfffffffffffffff0')
        self.assertLess(trampoline.index('and'),trampoline.index('call'))

    def test_thread_entry_and_switch_options_are_validated_before_any_artifact(self)->None:
        (self.dir/'badentry.omni').write_text('module t\nimport rt "rt.omni"\nfunc worker(x u32) u32 { return x }\nfunc main() u32 !{port.io,cpu.control} { return rt.finish(0u32) }\n',encoding='utf-8')
        cases=[('entry with parameters','badentry.omni',self.THREAD,b'E_THREAD_ENTRY'),
               ('entry does not exist','ctx_switch.omni',('--thread-entry','t.nothere'),b'E_THREAD_ENTRY'),
               ('switch without --thread-entry','ctx_switch.omni',(),b'E_TARGET_PROFILE')]
        for label,program,extra,code in cases:
            result=self.emit(self.dir/program,extra=extra)
            self.assertEqual(result.returncode,2,(label,result.stderr)); self.assertIn(code,result.stderr,(label,result.stderr))
            self.assertFalse((self.dir/'prog.ll').exists(),label)
        result=subprocess.run([str(OMNI),'emit-llvm',str(self.dir/'ctx_switch.omni'),'--target-profile','baremetal-i386-boot','--service-module','rt',
                               '--entry-address','1048576','--thread-entry','t.worker','-o',str(self.dir/'i386.ll')],capture_output=True,cwd=self.dir,
                              env={**os.environ,'OMNI_HOME':str(ROOT)},timeout=60)
        self.assertEqual(result.returncode,2,result.stderr); self.assertIn(b'E_TARGET_PROFILE',result.stderr)
        self.assertFalse((self.dir/'i386.ll').exists())


if __name__=='__main__':
    unittest.main(verbosity=2)
