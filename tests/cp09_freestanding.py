#!/usr/bin/env python3
"""CP-09 rows 9.2 and 9.4 (spec/TARGET_BAREMETAL_PROFILE_CANDIDATE.md): what a freestanding image is made of and which ABI promises are in the artifact itself.

9.2  A 64-bit freestanding image takes interrupts on the stack its own code runs on, so a leaf function must never use the SysV red zone. The promise is carried by the ARTIFACT (every function the
     compiler emits is `noredzone`), not by a flag the consumer must remember: a backend that is not told `-mno-red-zone` still produces code without red-zone accesses. The control is the same IR
     with the attribute removed, which does use the red zone (so the check can fail).
9.4  The transitive closure of the final ELF: no undefined symbol, no libc or runtime-hosted symbol, no dynamic loading, nothing but the program object in the link, and an image that is only code
     and read-only data (no writable load segment, no `.data` / `.bss` / `.got` / `.plt` / `.init_array`): mutable state is program-owned memory or `thread_local`, never an ambient global.
"""
from __future__ import annotations
import re
import unittest
import cp08_mmio
from language_0_8_3_alpha8 import X64Harness
import shutil
STORAGE = cp08_mmio.STORAGE

# A leaf function that needs more live values than there are registers: the backend has to spill, and in a leaf function with the red zone allowed it spills BELOW %rsp. Constant addresses and
# bitwise operations only: no arithmetic overflow check and no bounds check, so there is no call to a fault routine and the function is a genuine leaf.
def _spill():
    ops = ['xor', 'or', 'and']
    forward = 'v0'
    for i in range(1, 24):
        forward = 'bit.%s(%s, v%d)' % (ops[i % 3], forward, i)
    backward = 'v23'
    for i in range(22, -1, -1):
        backward = 'bit.%s(%s, v%d)' % (ops[(i + 1) % 3], backward, i)
    return ('pub func spill() u64 !{memory.raw} {\n' +
            ''.join('  let v%d u64 = raw.load64(%du64)\n' % (i, 1048576 + 8 * i) for i in range(24)) +
            '  return bit.xor(%s, %s)\n}\n' % (forward, backward))


SPILL = _spill()


class FreestandingBase(X64Harness):
    def setUp(self):
        super().setUp()
        for name in ('addr', 'mmio', 'dma'):
            shutil.copy(STORAGE / (name + '.omni'), self.dir / (name + '.omni'))

    HANDLER = ('--exception-handler', 't.on_exception')
    HANDLER_SOURCE = 'func on_exception(frame u64) u32 !{io.print,port.io,cpu.control} { return rt.finish(1u32) }\n'

    def program(self, body='', extra=''):
        # the leaf lives in the service module (uninstrumented code, so it really is a leaf): the harness's own provider plus one function
        with open(self.dir / 'rt.omni', 'a', encoding='utf-8') as provider:
            provider.write('\n' + SPILL)
        text = ('module t\nimport rt "rt.omni"\n' + extra + self.HANDLER_SOURCE +
                'func main() u32 !{io.print,memory.raw,port.io,cpu.control} {\n  print(rt.spill())\n' + body + '  return rt.finish(0u32)\n}\n')
        path = self.dir / 'closure.omni'
        path.write_text(text, encoding='utf-8')
        return path


class RedZoneTests(FreestandingBase):
    def objdump(self, obj):
        return self.sh('objdump', '-d', '--no-show-raw-insn', '-M', 'intel', obj).stdout.decode()

    def below_stack_pointer(self, text):
        """Accesses at a negative displacement from %rsp: the red zone."""
        return re.findall(r'\[rsp-0x[0-9a-f]+\]', text)

    def test_an_image_without_an_exception_table_keeps_exactly_the_ir_it_always_had(self):
        # no drift: the attribute belongs to the feature (an exception/interrupt table), not to every freestanding program
        path = self.program()
        emitted = self.emit(path)
        self.assertEqual(emitted.returncode, 0, emitted.stderr)
        self.assertNotIn('noredzone', (self.dir / 'prog.ll').read_text(encoding='utf-8'))

    def test_every_function_of_an_image_with_an_exception_table_carries_noredzone_and_the_backend_flag_is_not_needed(self):
        path = self.program()
        emitted = self.emit(path, extra=self.HANDLER)
        self.assertEqual(emitted.returncode, 0, emitted.stderr)
        ir = (self.dir / 'prog.ll').read_text(encoding='utf-8')
        defines = [l for l in ir.splitlines() if l.startswith('define ')]
        self.assertGreater(len(defines), 5)
        self.assertEqual([l for l in defines if ' noredzone' not in l], [])
        # the backend is NOT given -mno-red-zone: the attribute alone keeps the code out of the red zone
        flags = [f for f in self.CFLAGS if f != '-mno-red-zone']
        self.sh('clang', *flags, '-c', 'prog.ll', '-o', 'safe.o')
        self.assertEqual(self.below_stack_pointer(self.objdump('safe.o')), [])

    def test_the_control_without_the_attribute_and_without_the_flag_does_use_the_red_zone(self):
        path = self.program()
        self.assertEqual(self.emit(path, extra=self.HANDLER).returncode, 0)
        ir = (self.dir / 'prog.ll').read_text(encoding='utf-8')
        (self.dir / 'control.ll').write_text(ir.replace(' noredzone', ''), encoding='utf-8')
        flags = [f for f in self.CFLAGS if f != '-mno-red-zone']
        self.sh('clang', *flags, '-c', 'control.ll', '-o', 'control.o')
        self.assertTrue(self.below_stack_pointer(self.objdump('control.o')), 'the spilling leaf function must use the red zone when nothing forbids it')

    def test_a_32_bit_profile_is_not_given_an_attribute_it_does_not_have(self):
        path = self.program()
        self.assertEqual(self.emit(path).returncode, 0)
        # the i386 boot profile has no red zone at all; the x86-64 attribute must not leak into it
        done = self.run_i386_emit(path)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertNotIn(b'noredzone', (self.dir / 'i386.ll').read_bytes())

    def run_i386_emit(self, path):
        import os, subprocess
        from language_0_8_3_alpha8 import OMNI, ROOT
        (self.dir / 'i386.ll').unlink(missing_ok=True)
        (self.dir / 'boot.omni').write_text('module boot\npub func enter() u32 { return 0u32 }\n', encoding='utf-8')
        (self.dir / 'i386.omni').write_text('module t\nimport boot "boot.omni"\nfunc main() u32 { return boot.enter() }\n', encoding='utf-8')
        return subprocess.run([str(OMNI), 'emit-llvm', str(self.dir / 'i386.omni'), '--target-profile', 'baremetal-i386-boot', '--service-module', 'boot', '--entry-section', '.text.omni_entry', '--entry-address', '1048576',
                               '-o', str(self.dir / 'i386.ll')], capture_output=True, cwd=self.dir, env={**os.environ, 'OMNI_HOME': str(ROOT)}, timeout=60)


class ElfClosureTests(FreestandingBase):
    HOSTED = {'memcpy', 'memset', 'memmove', 'memcmp', 'strlen', 'malloc', 'calloc', 'realloc', 'free', 'printf', 'puts', 'abort', 'exit', '__stack_chk_fail', '__stack_chk_guard',
              '__cxa_atexit', '__cxa_finalize', '__dso_handle', '_start', '__libc_start_main', 'dlopen', 'dlsym', '__tls_get_addr', 'omni_runtime_start'}

    def elf(self):
        reg = cp08_mmio.RegisterArtifactTests.PROGRAM
        text = reg.replace('module t\nimport rt "rt.omni"\nimport mmio "mmio.omni"\n', 'module t\nimport rt "rt.omni"\nimport mmio "mmio.omni"\nimport dma "dma.omni"\n')
        path = self.dir / 'closure.omni'
        path.write_text(text, encoding='utf-8')
        self.build(path)
        return self.dir / 'payload.elf'

    def test_the_final_image_depends_on_nothing_outside_itself(self):
        elf = self.elf()
        self.assertEqual(self.sh('nm', '-u', str(elf)).stdout, b'')                       # no undefined symbol
        defined = [l.split()[-1] for l in self.sh('nm', str(elf)).stdout.decode().splitlines() if l.strip()]
        self.assertEqual(sorted(set(defined) & self.HOSTED), [])                           # no libc / hosted-runtime symbol
        self.assertTrue(any(n.startswith('omni.fn.') for n in defined))
        headers = self.sh('readelf', '-lW', str(elf)).stdout.decode()
        self.assertNotRegex(headers, r'\bINTERP\b')
        self.assertNotRegex(headers, r'\bDYNAMIC\b')
        sections = self.sh('readelf', '-SW', str(elf)).stdout.decode()
        names = re.findall(r'\]\s+(\.[\w.]+)', sections)
        for banned in ('.interp', '.dynamic', '.dynsym', '.dynstr', '.got', '.got.plt', '.plt', '.init', '.fini', '.init_array', '.fini_array', '.ctors', '.dtors', '.tdata', '.tbss'):
            self.assertNotIn(banned, names, names)

    def test_the_image_is_code_and_read_only_data_with_no_writable_load_segment(self):
        elf = self.elf()
        headers = self.sh('readelf', '-lW', str(elf)).stdout.decode()
        loads = [l.split() for l in headers.splitlines() if l.split()[:1] == ['LOAD']]
        self.assertTrue(loads, headers)
        for fields in loads:
            # LOAD offset vaddr paddr filesz memsz flags... align: nothing is zero-filled at load time (no bss) and nothing is writable
            self.assertEqual(int(fields[4], 16), int(fields[5], 16), fields)
            self.assertNotIn('W', ''.join(fields[6:-1]), fields)
        names = re.findall(r'\]\s+(\.[\w.]+)', self.sh('readelf', '-SW', str(elf)).stdout.decode())
        self.assertNotIn('.data', names)
        self.assertNotIn('.bss', names)

    def test_the_link_is_the_program_object_alone(self):
        self.elf()
        self.sh('ld', '-m', 'elf_x86_64', '-nostdlib', '--gc-sections', '-T', 'payload.ld', '-Map=closure.map', 'prog.o', '-o', 'mapped.elf')
        text = (self.dir / 'closure.map').read_text()
        inputs = set(re.findall(r'^\s*\S+\s+0x[0-9a-f]+\s+0x[0-9a-f]+\s+(\S+\.o)\s*$', text, re.M)) | set(re.findall(r'^\s+0x[0-9a-f]+\s+0x[0-9a-f]+\s+(\S+\.o)\s*$', text, re.M))
        self.assertEqual(inputs, {'prog.o'}, text[:1500])
        self.assertNotRegex(text, r'\.(a|so)\b')


class ProfileMixingTests(FreestandingBase):
    """9.5: a feature that belongs to one profile is refused, by name, in another - at emission, before any artifact exists. (Floating point and the FP-state primitives in the default
    general-register image are covered by A83X64FpuTests.)"""

    def refuse(self, label, source, profile, extra=(), message=None):
        import os, subprocess
        from language_0_8_3_alpha8 import OMNI, ROOT
        path = self.dir / 'mix.omni'
        path.write_text(source, encoding='utf-8')
        out = self.dir / 'mix.ll'
        out.unlink(missing_ok=True)
        args = [str(OMNI), 'emit-llvm', str(path)]
        if profile == 'baremetal-x86_64':
            args += ['--target-profile', profile, '--service-module', 'rt', '--entry-section', '.text.omni_entry']
        elif profile == 'baremetal-i386-boot':
            args += ['--target-profile', profile, '--service-module', 'rt', '--entry-section', '.text.omni_entry', '--entry-address', '1048576']
        args += [*extra, '-o', str(out)]
        done = subprocess.run(args, capture_output=True, cwd=self.dir, env={**os.environ, 'OMNI_HOME': str(ROOT)}, timeout=60)
        self.assertEqual(done.returncode, 2, (label, done.stderr))
        self.assertIn(b'E_TARGET_PROFILE', done.stderr, label)
        if message:
            self.assertIn(message.encode(), done.stderr, label)
        self.assertFalse(out.exists(), label)

    def test_what_belongs_to_one_profile_is_refused_in_the_others(self):
        x64_head = 'module t\nimport rt "rt.omni"\n'
        i386_head = 'module t\nimport rt "rt.omni"\n'
        main = 'func main() u32 !{cpu.control} {\n%s  return 0u32\n}\n'
        cases = [
            ('a hosted image has no CPU control', x64_head + 'func main() u32 !{cpu.syscall} {\n  let t u64 = cpu.trap3(40u32, 0u64, 0u64, 0u64)\n  return 0u32\n}\n', None, (), 'bare-metal'),
            ('an allocator service the profile does not define', x64_head + 'struct Tok { h u64 }\nfunc main() u32 !{memory.read,memory.write} {\n  let a = slots.alloc<Tok>(2u32)\n  match a { Ok(b) {\n    let z = slots.release(move(b))\n    match z { Ok(k) { return 0u32 } Err(back) { return 1u32 } }\n  } Err(code) { return code } }\n}\n', 'baremetal-x86_64', (), 'hospedado'),
            ('thread-local blocks need FS/GS of the 64-bit profile', 'module t\nimport rt "rt.omni"\nthread_local n u32 = 1u32\nfunc main() u32 { return 0u32 }\n', 'baremetal-i386-boot', (), 'baremetal-x86_64'),
            ('thread-local blocks have no hosted image either', 'module t\nthread_local n u32 = 1u32\nfunc main() u32 { return 0u32 }\n', None, (), 'baremetal-x86_64'),
            ('a control register of the 64-bit profile', i386_head + main % '  let c u64 = cpu.read_cr64(2u32)\n', 'baremetal-i386-boot', (), 'baremetal-x86_64'),
            ('the FP ISA is a 64-bit option', i386_head + 'func main() u32 { return 0u32 }\n', 'baremetal-i386-boot', ('--target-isa', 'sse2'), 'baremetal-x86_64'),
            ('ring 3 is a 64-bit option', i386_head + 'func main() u32 { return 0u32 }\n', 'baremetal-i386-boot', ('--ring3-support',), 'baremetal-x86_64'),
            ('an unknown profile is named', x64_head + 'func main() u32 { return 0u32 }\n', None, ('--target-profile', 'baremetal-arm64', '--service-module', 'rt'), 'baremetal-arm64'),
        ]
        for label, source, profile, extra, message in cases:
            with self.subTest(label):
                self.refuse(label, source, profile, extra, message)


if __name__ == '__main__':
    unittest.main()
