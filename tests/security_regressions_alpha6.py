#!/usr/bin/env python3
from __future__ import annotations
import hashlib, json, os, pathlib, subprocess, tempfile, unittest
ROOT=pathlib.Path(__file__).resolve().parents[1]
OMNI=pathlib.Path(os.environ.get('OMNI_TEST_BIN',ROOT/'bin/linux-x86_64/omni'))
def proc(*args,timeout=30,env=None):
    e={**os.environ,'OMNI_HOME':str(ROOT)}
    if env:e.update(env)
    return subprocess.run([str(x) for x in args],capture_output=True,timeout=timeout,env=e)
def hfile(p:pathlib.Path)->str:
    h=hashlib.sha256()
    with p.open('rb') as f:
        for chunk in iter(lambda:f.read(1024*1024),b''):h.update(chunk)
    return h.hexdigest()

class CrossTrackHardeningTests(unittest.TestCase):
    def setUp(self): self.tmp=tempfile.TemporaryDirectory(prefix='omni-a5-sec-'); self.d=pathlib.Path(self.tmp.name)
    def tearDown(self): self.tmp.cleanup()
    def source(self,text:str,name='a.omni'):
        p=self.d/name; p.write_text(text,encoding='utf-8'); return p
    def assert_closed(self,r,needle=None):
        self.assertNotEqual(r.returncode,0,(r.stdout,r.stderr))
        if needle:self.assertIn(needle.encode(),r.stderr)

    def test_textual_particle_embedded_nul_fails_closed(self):
        p=self.d/'nul.omni'; p.write_bytes(b'module t\x00\nfunc main() u32 { return 0 }\n')
        self.assert_closed(proc(OMNI,'check',p),'E_UTF8')

    def test_textual_wave_embedded_nul_fails_closed(self):
        w=proc(OMNI,'wave',ROOT/'examples/hola.omni'); self.assertEqual(w.returncode,0,w.stderr)
        p=self.d/'nul.owave'; raw=bytearray(w.stdout); raw.insert(len(raw)//2,0); p.write_bytes(raw)
        self.assert_closed(proc(OMNI,'check',p),'E_UTF8')

    def test_wire_text_nul_is_not_c_string_truncated(self):
        src=self.source('module t func main() u32 !{io.print} { print("XYZ"); return 0 }')
        w=self.d/'x.owire'; self.assertEqual(proc(OMNI,'pack',src,'-o',w).returncode,0)
        raw=bytearray(w.read_bytes()); pos=raw.find(b'XYZ'); self.assertGreaterEqual(pos,0); raw[pos+1]=0
        bad=self.d/'bad.owire'; bad.write_bytes(raw)
        self.assert_closed(proc(OMNI,'check',bad),'E_UTF8')

    def test_bytes_can_contain_nul_without_truncation(self):
        src=self.source('''module t
func main() u32 !{io.print,memory.read,memory.write} {
  let allocation = buffer.alloc(3)
  match allocation {
    Ok(buf) {
      let a = buffer.write_u8(borrow_mut(buf),0,65)
      match a { Ok(x) { print(x) } Err(e) { let released = buffer.release(move(buf)); return e } }
      let z = buffer.write_u8(borrow_mut(buf),1,0)
      match z { Ok(x) { print(x) } Err(e) { let released = buffer.release(move(buf)); return e } }
      let b = buffer.write_u8(borrow_mut(buf),2,66)
      match b { Ok(x) { print(x) } Err(e) { let released = buffer.release(move(buf)); return e } }
      let frozen = buffer.freeze(move(buf))
      match frozen {
        Ok(bytes) {
          print(bytes.len(bytes))
          let text = bytes.to_text(bytes)
          match text { Ok(t) { print(t) } Err(e) { print(e) } }
        }
        Err(e) { return e }
      }
    }
    Err(e) { return e }
  }
  return 0
}''')
        e=proc(OMNI,'eval',src); self.assertEqual(e.returncode,0,e.stderr); self.assertEqual(e.stdout,b'1\n1\n1\n3\n1\n')
        out=self.d/'app'; b=proc(OMNI,'build',src,'-o',out,'--no-cache'); self.assertEqual(b.returncode,0,b.stderr)
        n=proc(out); self.assertEqual((n.returncode,n.stdout),(0,e.stdout),n.stderr)

    def test_unknown_capability_particle_wave_wire_all_fail_closed(self):
        p=self.source('module t func main() u32 !{zz.print} { return 0 }')
        self.assert_closed(proc(OMNI,'check',p),'E_CAPABILITY')
        good=self.source('module t func main() u32 !{io.print} { print(1); return 0 }','good.omni')
        wave=proc(OMNI,'wave',good); self.assertEqual(wave.returncode,0,wave.stderr)
        bw=self.d/'bad.owave'; bw.write_bytes(wave.stdout.replace(b'io.print',b'zz.print',1)); self.assert_closed(proc(OMNI,'check',bw),'E_CAPABILITY')
        wire=self.d/'good.owire'; self.assertEqual(proc(OMNI,'pack',good,'-o',wire).returncode,0)
        raw=wire.read_bytes(); self.assertIn(b'io.print',raw); bad=self.d/'bad.owire'; bad.write_bytes(raw.replace(b'io.print',b'zz.print',1)); self.assert_closed(proc(OMNI,'check',bad),'E_CAPABILITY')

    def test_transitive_capability_bypass_is_rejected(self):
        p=self.source('module t func helper() u32 !{io.print} { print(1); return 0 } func main() u32 { return helper() }')
        self.assert_closed(proc(OMNI,'check',p),'E_CAPABILITY')

    def test_semantic_downgrade_matrix_wave_and_wire_fails_closed(self):
        features={
            3:'module t func main() u32 { let x Text="x"; return text.len(x) }',
            4:'module t func main() u32 !{io.print} { print(1); return 0 }',
            5:'module t func main() u32 { let b Bytes=bytes.from_text("x"); return bytes.len(b) }',
            6:'module t func main() u32 { let x Option<u32>=Some<u32>(1u32); match x { Some(v) { return v } None { return 0 } } }',
            7:'module t func main() u32 { let x u64=1u64; return u32(x) }',
            8:'module t\nenum E { A, B, }\nfunc main() u32 { let e E=E.A(); match e { A { return 1 } B { return 2 } } }',
            9:'module t func main() u32 { let x Tuple<u32,bool>=tuple(1u32,true); return tuple.get(x,0u32) }',
            10:'module t func main() u32 { let a Array<u32,2>=array(1u32,2u32); let v View<u32>=view(a); return view.get(v,0u32) }',
        }
        for introduced,src_text in features.items():
            with self.subTest(version=introduced):
                src=self.source(src_text,f'v{introduced}.omni'); c=proc(OMNI,'check',src); self.assertEqual(c.returncode,0,c.stderr)
                wave=proc(OMNI,'wave',src); self.assertEqual(wave.returncode,0,wave.stderr); self.assertTrue(wave.stdout.startswith(b'(omni-wave 18'))
                fakew=self.d/f'v{introduced}-as{introduced-1}.owave'; fakew.write_bytes(wave.stdout.replace(b'(omni-wave 18',f'(omni-wave {introduced-1}'.encode(),1))
                self.assert_closed(proc(OMNI,'check',fakew))
                wire=self.d/f'v{introduced}.owire'; self.assertEqual(proc(OMNI,'pack',src,'-o',wire).returncode,0)
                raw=wire.read_bytes(); self.assertEqual(raw[:8],b'OMCX\x12\x00\x00\x00')
                downgraded=f'OMC{introduced-1}'.encode()+raw[8:]
                fakeb=self.d/f'v{introduced}-as{introduced-1}.owire'; fakeb.write_bytes(downgraded)
                self.assert_closed(proc(OMNI,'check',fakeb))

    def test_unknown_extended_wire_version_fails_closed(self):
        good=self.source('module t func main() u32 { return 0 }')
        out=self.d/'good.owire'; self.assertEqual(proc(OMNI,'pack',good,'-o',out).returncode,0)
        raw=bytearray(out.read_bytes()); self.assertEqual(raw[:4],b'OMCX'); raw[4:8]=(23).to_bytes(4,'little')
        bad=self.d/'bad-version.owire'; bad.write_bytes(raw)
        self.assert_closed(proc(OMNI,'check',bad),'E_VERSION')

    def test_provider_hashes_match_python_standard_sha256(self):
        src=self.source('module t func main() u32 { return 0 }')
        m=proc(OMNI,'manifest',src); self.assertEqual(m.returncode,0,m.stderr); data=json.loads(m.stdout)
        wave=proc(OMNI,'wave',src); self.assertEqual(wave.returncode,0,wave.stderr)
        self.assertEqual(data['program_content_id'],'sha256:'+hashlib.sha256(wave.stdout).hexdigest())
        by_path={(src.parent/pathlib.Path(x['path'])).resolve():x['sha256'] for x in data['sources']}
        self.assertEqual(by_path[src.resolve()],hfile(src))

    def test_build_receipt_binds_exact_provenance(self):
        src=self.source('module t func main() u32 { return 7 }'); out=self.d/'app'
        b=proc(OMNI,'build',src,'-o',out,'--no-cache'); self.assertEqual(b.returncode,0,b.stderr)
        r=json.loads(pathlib.Path(str(out)+'.ometa.json').read_text())
        self.assertEqual(r['schema'],'omni.build-receipt/2'); self.assertEqual(r['artifact_sha256'],hfile(out))
        self.assertEqual(r['provenance']['omni_compiler_sha256'],hfile(OMNI.resolve()))
        self.assertEqual(r['provenance']['runtime_sha256'],hfile(ROOT/'runtime/omni_runtime.c'))
        self.assertEqual(r['provenance']['backend_identity_sha256'],hashlib.sha256(r['provenance']['backend_identity'].encode()).hexdigest())
        self.assertEqual(r['wave_writer'],18); self.assertEqual(r['wire_profile'],'OMC18')
        sources={(src.parent/pathlib.Path(x['path'])).resolve():x['sha256'] for x in r['provenance']['source_files']}
        self.assertEqual(sources[src.resolve()],hfile(src))

    def test_same_toolchain_same_input_reproducible_binary(self):
        src=self.source('module t func main() u32 { return 9 }'); a=self.d/'a'; b=self.d/'b'
        x=proc(OMNI,'build',src,'-o',a,'--no-cache'); y=proc(OMNI,'build',src,'-o',b,'--no-cache')
        self.assertEqual(x.returncode,0,x.stderr); self.assertEqual(y.returncode,0,y.stderr); self.assertEqual(hfile(a),hfile(b)); self.assertEqual(a.read_bytes(),b.read_bytes())

if __name__=='__main__': unittest.main(verbosity=2)
