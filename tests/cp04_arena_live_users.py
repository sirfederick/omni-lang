#!/usr/bin/env python3
"""CP-04 row 4.8 (liberación de arena con usuarios vivos), the part that depends on the borrow rules (CP-02).

The arena (examples/storage/arena.omni) is a bump allocator over a Resource<Buffer> that its caller owns. Its users are of two kinds: a BLOCK (plain data: offset, size and epoch,
valid for one epoch, refused with outcome 4 after `reset`) and a BORROW of the buffer it is read or written through. This file shows what happens to each when the arena is reclaimed:
the blocks go stale (typed), the buffer cannot be released while a borrow of it is still in use, and after the release no block can be used at all (no buffer to use it on).
"""
from __future__ import annotations
import shutil
import unittest
from cp02_borrowed_containers import ContainerCase
from language_0_8_3_alpha8 import ROOT

STORAGE = ROOT / 'examples' / 'storage'


class ArenaCase(ContainerCase):
    def setUp(self):
        super().setUp()
        shutil.copy(STORAGE / 'arena.omni', self.dir / 'arena.omni')

    def source(self, text, name='program.omni'):
        return super().source('import arena "arena.omni"\n' + text, name)


class ArenaLiveUserTests(ArenaCase):
    HEAD = ('func main() u32 !{memory.read,memory.write} {\n  let a = buffer.alloc(64u32)\n  match a { Ok(b) {\n    var code u32 = 0u32\n    let s0 = arena.new_state()\n'
            '    let g = arena.alloc(borrow_mut(b), s0, 16u32, 8u32)\n    match g { Ok(gr) {\n')

    def test_reclaiming_the_arena_makes_every_live_block_stale_and_the_next_ones_zeroed(self):
        self.both(self.source(self.HEAD +
            '      let w = arena.write_u32(borrow_mut(b), gr.state, gr.block, 0u32, 1234u32)\n      match w { Ok(d) { } Err(e) { code = 1u32 } }\n'
            '      let rs = arena.reset(borrow_mut(b), gr.state)\n      match rs { Ok(s1) {\n'
            '        let old = arena.read_u32(borrow(b), s1, gr.block, 0u32)\n        match old { Ok(v) { code = 2u32 } Err(e) { if e != 4u32 { code = 3u32 } } }\n'
            '        let g2 = arena.alloc(borrow_mut(b), s1, 16u32, 8u32)\n        match g2 { Ok(gr2) {\n'
            '          let fresh = arena.read_u32(borrow(b), gr2.state, gr2.block, 0u32)\n          match fresh { Ok(v) { if v != 0u32 { code = 4u32 } } Err(e) { code = 5u32 } }\n'
            '        } Err(e) { code = 6u32 } }\n'
            '      } Err(e) { code = 7u32 } }\n'
            '    } Err(e) { code = 8u32 } }\n    let z u32 = buffer.release(move(b))\n    if code != 0u32 { return code }\n    return 42u32\n  } Err(e) { return e } }\n}\n'))

    def test_the_buffer_cannot_be_released_while_a_borrow_of_it_is_still_in_use(self):
        self.rejected(self.HEAD.replace('    let s0 = arena.new_state()\n', '    let live = borrow(b)\n    let s0 = arena.new_state()\n') +
            '      let z u32 = buffer.release(move(b))\n      let r = arena.read_u32(live, gr.state, gr.block, 0u32)\n      match r { Ok(v) { } Err(e) { } }\n'
            '    } Err(e) { code = 8u32 } }\n    return code\n  } Err(e) { return e } }\n}\n', b'E_BORROW_CONFLICT')

    def test_after_the_release_no_block_can_be_used(self):
        self.rejected(self.HEAD +
            '      let z u32 = buffer.release(move(b))\n      let r = arena.read_u32(borrow(b), gr.state, gr.block, 0u32)\n      match r { Ok(v) { } Err(e) { } }\n'
            '    } Err(e) { code = 8u32 } }\n    return code\n  } Err(e) { return e } }\n}\n', b'E_RESOURCE_MOVED')


if __name__ == '__main__':
    unittest.main()
