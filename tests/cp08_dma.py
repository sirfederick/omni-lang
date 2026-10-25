#!/usr/bin/env python3
"""CP-08 rows 8.5 and 8.6 (spec/MMIO_PORTS_CANDIDATE.md, examples/storage/dma.omni): an operation the device performs on its own keeps its storage alive until the device is done.

MODEL (evaluator, RAM standing in for the device): the storage is a Block the program owns; `start` turns it into an InFlight (the program no longer holds a Block, so nothing can read, write or
free the storage), and only `finish` gives the Block back, and only when the status register of the device reads zero. Dropping an InFlight does not compile; giving it up is the explicit `abandon`.
EMULATION (QEMU TCG): the device is the local APIC timer: the doorbell is its initial count, the status register is its current count, and it really runs down in time. The first `finish`, made
at once, finds the device busy and gives the InFlight back; after the count reaches zero `finish` gives the Block back with the data intact.
"""
from __future__ import annotations
import shutil
import unittest
from cp08_mmio import RamCase, reg, RAM, STORAGE
from language_0_8_3_alpha8 import ROOT, OMNI, proc, X64Harness

BUF = ('struct Buf { tag u32 }\nimpl mmio.Region for Buf {\n  func base() u64 { return 4195328u64 }\n  func size() u64 { return 64u64 }\n}\n')
DEVICE = RAM + BUF + reg('Door', 0, 4, 'Writable') + reg('Busy', 4, 4, 'Readable', 'Writable') + reg('NoDoor', 1000, 4, 'Writable')


class TransferCase(RamCase):
    def setUp(self):
        super().setUp()
        shutil.copy(STORAGE / 'dma.omni', self.dir / 'dma.omni')

    def source(self, text, name='program.omni'):
        return super().source('import dma "dma.omni"\n' + text, name)


class TransferModelTests(TransferCase):
    def test_the_storage_is_ours_again_only_when_the_device_is_done_and_the_data_is_intact(self):
        self.run_eval(DEVICE +
            'func main() u32 !{memory.raw} {\n  var code u32 = 0u32\n  let mp = mmio.map<Ram>()\n  match mp { Ok(m) {\n    let c = dma.claim<Buf>()\n    match c { Ok(b) {\n'
            '      let w = dma.write32<Buf>(borrow_mut(b), 8u32, 3735928559u32)\n      match w { Ok(d) { } Err(e) { code = 1u32 } }\n'
            '      let busy = mmio.write<Ram,Busy>(borrow_mut(m), 1u64)\n      match busy { Ok(d) { } Err(e) { code = 2u32 } }\n'
            '      let s = dma.start<Ram,Buf,Door>(borrow_mut(m), move(b), 7u64)\n'
            '      match s { Ok(t) {\n'
            # the device is busy: the first finish gives the in-flight storage back, still not ours
            '        let early = dma.finish<Ram,Buf,Busy>(borrow(m), move(t))\n'
            '        match early {\n          Ok(back) { code = 3u32\n            let z u32 = dma.release<Buf>(move(back)) }\n'
            '          Err(still) {\n'
            '            let fin = dma.finished<Ram,Busy>(borrow(m))\n            match fin { Ok(v) { if v { code = 4u32 } } Err(e) { code = 5u32 } }\n'
            # the device finishes (its status reads zero)
            '            let off = mmio.write<Ram,Busy>(borrow_mut(m), 0u64)\n            match off { Ok(d) { } Err(e) { code = 6u32 } }\n'
            '            let fin2 = dma.finished<Ram,Busy>(borrow(m))\n            match fin2 { Ok(v) { if !v { code = 7u32 } } Err(e) { code = 8u32 } }\n'
            '            let late = dma.finish<Ram,Buf,Busy>(borrow(m), move(still))\n'
            '            match late {\n              Ok(back) {\n                let r = dma.read32<Buf>(borrow(back), 8u32)\n                match r { Ok(v) { if v != 3735928559u32 { code = 9u32 } } Err(e) { code = 10u32 } }\n'
            '                let z u32 = dma.release<Buf>(move(back))\n              }\n'
            '              Err(again) { code = 11u32\n                let z u32 = dma.abandon<Buf>(move(again)) }\n            }\n          }\n        }\n'
            '      } Err(back) { code = 12u32\n        let z u32 = dma.release<Buf>(move(back)) } }\n'
            '    } Err(e) { code = 13u32 } }\n    let u = mmio.unmap<Ram>(move(m))\n  } Err(e) { code = 14u32 } }\n  if code != 0u32 { return code }\n  return 42u32\n}\n')

    def test_a_doorbell_that_cannot_be_rung_starts_nothing_and_the_block_comes_back(self):
        self.run_eval(DEVICE +
            'func main() u32 !{memory.raw} {\n  var code u32 = 0u32\n  let mp = mmio.map<Ram>()\n  match mp { Ok(m) {\n    let c = dma.claim<Buf>()\n    match c { Ok(b) {\n'
            '      let w = dma.write32<Buf>(borrow_mut(b), 0u32, 77u32)\n      match w { Ok(d) { } Err(e) { code = 1u32 } }\n'
            '      let s = dma.start<Ram,Buf,NoDoor>(borrow_mut(m), move(b), 7u64)\n'
            '      match s {\n        Ok(t) { code = 2u32\n          let z u32 = dma.abandon<Buf>(move(t)) }\n'
            '        Err(back) {\n          let r = dma.read32<Buf>(borrow(back), 0u32)\n          match r { Ok(v) { if v != 77u32 { code = 3u32 } } Err(e) { code = 4u32 } }\n'
            '          let z u32 = dma.release<Buf>(move(back))\n        }\n      }\n'
            '    } Err(e) { code = 5u32 } }\n    let u = mmio.unmap<Ram>(move(m))\n  } Err(e) { code = 6u32 } }\n  if code != 0u32 { return code }\n  return 42u32\n}\n')

    def test_the_block_is_bounded_and_a_region_that_cannot_be_claimed_says_so(self):
        self.run_eval(RAM + BUF +
            'struct Empty { tag u32 }\nimpl mmio.Region for Empty {\n  func base() u64 { return 4195328u64 }\n  func size() u64 { return 0u64 }\n}\n'
            'func main() u32 !{memory.raw} {\n  var code u32 = 0u32\n'
            '  let e0 = dma.claim<Empty>()\n  match e0 { Ok(b) { code = 1u32\n    let z u32 = dma.release<Empty>(move(b)) } Err(e) { if e != 3u32 { code = 2u32 } } }\n'
            '  let c = dma.claim<Buf>()\n  match c { Ok(b) {\n'
            '    let o1 = dma.read32<Buf>(borrow(b), 64u32)\n    match o1 { Ok(v) { code = 3u32 } Err(e) { if e != 1u32 { code = 4u32 } } }\n'
            '    let o2 = dma.write32<Buf>(borrow_mut(b), 62u32, 1u32)\n    match o2 { Ok(v) { code = 5u32 } Err(e) { if e != 2u32 { code = 6u32 } } }\n'
            '    let o3 = dma.write32<Buf>(borrow_mut(b), 60u32, 9u32)\n    match o3 { Ok(v) { } Err(e) { code = 7u32 } }\n'
            '    let z u32 = dma.release<Buf>(move(b))\n  } Err(e) { code = 8u32 } }\n  if code != 0u32 { return code }\n  return 42u32\n}\n')

    def test_a_block_that_wraps_the_address_space_cannot_be_claimed(self):
        self.run_eval(RAM + 'struct Wrap { tag u32 }\nimpl mmio.Region for Wrap {\n  func base() u64 { return 18446744073709551612u64 }\n  func size() u64 { return 8u64 }\n}\n'
                      'struct Edge { tag u32 }\nimpl mmio.Region for Edge {\n  func base() u64 { return 18446744073709551608u64 }\n  func size() u64 { return 8u64 }\n}\n'
                      'func main() u32 !{memory.raw} {\n  var code u32 = 0u32\n'
                      '  let w = dma.claim<Wrap>()\n  match w { Ok(b) { code = 1u32\n    let z u32 = dma.release<Wrap>(move(b)) } Err(e) { if e != 3u32 { code = 2u32 } } }\n'
                      '  let k = dma.claim<Edge>()\n  match k { Ok(b) {\n    let z u32 = dma.release<Edge>(move(b)) } Err(e) { code = 3u32 } }\n'
                      '  if code != 0u32 { return code }\n  return 42u32\n}\n')

    def test_while_the_device_may_be_using_the_storage_the_program_cannot_touch_free_or_forget_it(self):
        head = DEVICE + 'func main() u32 !{memory.raw} {\n  let mp = mmio.map<Ram>()\n  match mp { Ok(m) {\n    let c = dma.claim<Buf>()\n    match c { Ok(b) {\n'
        tail = '    } Err(e) { return e } }\n    let u = mmio.unmap<Ram>(move(m))\n    return 0u32\n  } Err(e) { return e } }\n}\n'
        start = '      let s = dma.start<Ram,Buf,Door>(borrow_mut(m), move(b), 7u64)\n'
        cases = [
            ('reading the block after the device was started',
             head + start + '      let r = dma.read32<Buf>(borrow(b), 0u32)\n      match s { Ok(t) { let z u32 = dma.abandon<Buf>(move(t)) } Err(back) { let z u32 = dma.release<Buf>(move(back)) } }\n' + tail, b'E_RESOURCE_MOVED'),
            ('releasing the block after the device was started',
             head + start + '      let z0 u32 = dma.release<Buf>(move(b))\n      match s { Ok(t) { let z u32 = dma.abandon<Buf>(move(t)) } Err(back) { let z u32 = dma.release<Buf>(move(back)) } }\n' + tail, b'E_RESOURCE_MOVED'),
            ('a lend of the block that is still in use when the device is started',
             head + '      let keep = borrow(b)\n' + start + '      let r = dma.read32<Buf>(keep, 0u32)\n      match s { Ok(t) { let z u32 = dma.abandon<Buf>(move(t)) } Err(back) { let z u32 = dma.release<Buf>(move(back)) } }\n' + tail, b'E_BORROW_CONFLICT'),
            ('forgetting the in-flight storage',
             head + start + '      match s { Ok(t) { code_placeholder } Err(back) { let z u32 = dma.release<Buf>(move(back)) } }\n'.replace('code_placeholder', 'let n u32 = 0u32') + tail, b'E_RESOURCE_UNCONSUMED'),
            ('finishing the same transfer twice',
             head + start + '      match s { Ok(t) {\n        let a = dma.finish<Ram,Buf,Busy>(borrow(m), move(t))\n        let b2 = dma.finish<Ram,Buf,Busy>(borrow(m), move(t))\n'
             '        match a { Ok(x) { let z u32 = dma.release<Buf>(move(x)) } Err(y) { let z u32 = dma.abandon<Buf>(move(y)) } }\n'
             '        match b2 { Ok(x) { let z u32 = dma.release<Buf>(move(x)) } Err(y) { let z u32 = dma.abandon<Buf>(move(y)) } }\n      } Err(back) { let z u32 = dma.release<Buf>(move(back)) } }\n' + tail, b'E_RESOURCE_MOVED'),
            ('opening the in-flight storage from outside its module',
             head + start + '      match s { Ok(t) { let inner dma.InFlight<Buf> = resource.unseal(move(t)) } Err(back) { let z u32 = dma.release<Buf>(move(back)) } }\n' + tail, b'E_RESOURCE_PRIVATE'),
        ]
        for label, program, code in cases:
            with self.subTest(label):
                path = self.source(program, 'bad.omni')
                checked = proc(OMNI, 'check', path)
                self.assertEqual(checked.returncode, 2, (label, checked.stderr))
                self.assertIn(code, checked.stderr, (label, checked.stderr))


class TimerDeviceTests(X64Harness):
    """EMULATION: the local APIC timer is the device. Initial count = doorbell, current count = status (it reads zero when the count has run down)."""
    def setUp(self):
        super().setUp()
        for name in ('addr', 'mmio', 'dma'):
            shutil.copy(STORAGE / (name + '.omni'), self.dir / (name + '.omni'))

    def lines(self, serial):
        return serial.split('\n')[:-1]

    def test_the_block_comes_back_only_after_the_timer_has_run_down(self):
        path = self.dir / 'timer_dma.omni'
        path.write_text('module t\nimport rt "rt.omni"\nimport mmio "mmio.omni"\nimport dma "dma.omni"\n'
            'struct Lapic { tag u32 }\nimpl mmio.Region for Lapic {\n  func base() u64 { return 4276092928u64 }\n  func size() u64 { return 4096u64 }\n}\n'
            'struct Mem { tag u32 }\nimpl mmio.Region for Mem {\n  func base() u64 { return 6291456u64 }\n  func size() u64 { return 64u64 }\n}\n' +
            reg('LvtTimer', 800, 4, 'Writable') + reg('Divide', 992, 4, 'Writable') + reg('InitialCount', 896, 4, 'Writable') + reg('CurrentCount', 912, 4, 'Readable') +
            'func main() u32 !{io.print,memory.raw,port.io,cpu.control} {\n  let mp = mmio.map<Lapic>()\n  match mp { Ok(m) {\n'
            '    let lvt = mmio.write<Lapic,LvtTimer>(borrow_mut(m), 65536u64)\n    match lvt { Ok(d) { } Err(e) { print(900u32 + e) } }\n'      # masked, one-shot
            '    let div = mmio.write<Lapic,Divide>(borrow_mut(m), 11u64)\n    match div { Ok(d) { } Err(e) { print(900u32 + e) } }\n'         # divide by 1
            '    let c = dma.claim<Mem>()\n    match c { Ok(b) {\n'
            '      let w = dma.write32<Mem>(borrow_mut(b), 8u32, 3735928559u32)\n      match w { Ok(d) { } Err(e) { print(900u32 + e) } }\n'
            '      let s = dma.start<Lapic,Mem,InitialCount>(borrow_mut(m), move(b), 4000000u64)\n'
            '      match s { Ok(t) {\n'
            '        let early = dma.finish<Lapic,Mem,CurrentCount>(borrow(m), move(t))\n'
            '        match early {\n          Ok(back) { print(111u32)\n            let z u32 = dma.release<Mem>(move(back)) }\n'
            '          Err(still) {\n            print(1u32)\n'                                                                                       # busy: the storage did not come back
            '            var spins u32 = 0u32\n            var done bool = false\n'
            '            for spins < 50000000u32 {\n              if done { spins = 50000000u32 } else {\n'
            '                let f = dma.finished<Lapic,CurrentCount>(borrow(m))\n                match f { Ok(v) { done = v } Err(e) { spins = 50000000u32 } }\n'
            '                spins = spins + 1u32\n              }\n            }\n'
            '            if done { print(2u32) } else { print(3u32) }\n'
            '            let late = dma.finish<Lapic,Mem,CurrentCount>(borrow(m), move(still))\n'
            '            match late {\n              Ok(back) {\n                let r = dma.read32<Mem>(borrow(back), 8u32)\n                match r { Ok(v) { print(v) } Err(e) { print(900u32 + e) } }\n'
            '                let z u32 = dma.release<Mem>(move(back))\n              }\n'
            '              Err(again) { print(4u32)\n                let z u32 = dma.abandon<Mem>(move(again)) }\n            }\n          }\n        }\n'
            '      } Err(back) { print(222u32)\n        let z u32 = dma.release<Mem>(move(back)) } }\n'
            '    } Err(e) { print(800u32 + e) } }\n    let u = mmio.unmap<Lapic>(move(m))\n  } Err(e) { print(700u32 + e) } }\n  return rt.finish(0u32)\n}\n', encoding='utf-8')
        rc, serial = self.boot(self.build(path))
        # busy at once (1), then the timer ran down (2), then the block is ours again and the data we wrote before starting is intact
        self.assertEqual((rc, self.lines(serial)), (1, ['1', '2', '3735928559']), serial)


if __name__ == '__main__':
    unittest.main()
