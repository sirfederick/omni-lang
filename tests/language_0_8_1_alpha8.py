#!/usr/bin/env python3
from __future__ import annotations
import json, os, pathlib, subprocess, tempfile, unittest

ROOT=pathlib.Path(__file__).resolve().parents[1]
OMNI=pathlib.Path(os.environ.get("OMNI_TEST_BIN",ROOT/"bin/linux-x86_64/omni"))

def proc(*args,timeout=45):
    return subprocess.run([str(x) for x in args],capture_output=True,timeout=timeout,
                          env={**os.environ,"OMNI_HOME":str(ROOT)})

class Alpha81DataLanguageTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix="omni-a81-")
        self.d=pathlib.Path(self.tmp.name)
    def tearDown(self): self.tmp.cleanup()
    def source(self,text,name="main.omni"):
        p=self.d/name; p.write_text(text,encoding="utf-8"); return p
    def check_ok(self,text):
        r=proc(OMNI,"check",self.source(text)); self.assertEqual(r.returncode,0,r.stderr)
    def check_err(self,text,code):
        r=proc(OMNI,"check",self.source(text)); self.assertEqual(r.returncode,2,r.stderr); self.assertIn(code.encode(),r.stderr)

    def test_version_and_tranche_contract(self):
        self.assertEqual(proc(OMNI,"--version").stdout.strip(),b"omni "+(ROOT/"VERSION").read_bytes().strip())
        spec=(ROOT/"spec/DATA_LANGUAGE_0_8_1.md").read_text(encoding="utf-8")
        plan=(ROOT/"docs/A8_T1_LANGUAGE_USABILITY_FOUNDATION.md").read_text(encoding="utf-8")
        for token in ("f32","f64","Unicode","0.8.2-alpha.8","0.8.3-alpha.8","Vector<T>","Owned<T>"):
            self.assertIn(token,spec+plan)

    def test_float_type_identity_and_layout(self):
        f32=json.loads(proc(OMNI,"type","describe","f32").stdout)
        f64=json.loads(proc(OMNI,"type","describe","f64").stdout)
        self.assertEqual((f32["kind"],f32["width_bits"],f32["ieee754"]),("float",32,True))
        self.assertEqual((f64["kind"],f64["width_bits"],f64["ieee754"]),("float",64,True))
        self.assertNotEqual(f32["type_id"],f64["type_id"])
        l32=json.loads(proc(OMNI,"type","layout","f32").stdout)
        l64=json.loads(proc(OMNI,"type","layout","f64").stdout)
        self.assertEqual((l32["size_bytes"],l32["alignment_bytes"]),(4,4))
        self.assertEqual((l64["size_bytes"],l64["alignment_bytes"]),(8,8))

    def test_float_eval_native_match(self):
        src=ROOT/"examples/floats.omni"
        ev=proc(OMNI,"eval",src)
        self.assertEqual(ev.returncode,7,ev.stderr)
        self.assertEqual(ev.stdout,b"3.75\n2.25\n3\n7\n")
        exe=self.d/"floats"
        b=proc(OMNI,"build",src,"-o",exe,"--no-cache",timeout=90)
        self.assertEqual(b.returncode,0,b.stderr)
        native=proc(exe)
        self.assertEqual((native.returncode,native.stdout),(ev.returncode,ev.stdout),native.stderr)

    def test_explicit_float_suffix_is_required(self):
        self.check_err("""module t
func main() u32 {
  let x f64 = 1.5
  return 0
}
""","E_NUMBER")

    def test_negative_and_scientific_float_literals(self):
        self.check_ok("""module t
func main() u32 {
  let a f64 = -1.5f64
  let b f64 = 1e2f64
  let c f32 = 2.5e-1f32
  if a < b { return u32(c*4.0f32) }
  return 0
}
""")

    def test_float_composes_with_array_tuple_and_scalar_generic(self):
        p=self.source("""module t
func identity<T:Scalar>(x T) T { return x }
func main() u32 {
  let values Array<f32,2> = array(1.0f32,2.0f32)
  let second f32 = array.get(values,1u32)
  let pair Tuple<f32,f64> = tuple(second,identity<f64>(3.5f64))
  let left f32 = tuple.get(pair,0u32)
  let right f64 = tuple.get(pair,1u32)
  return u32(left)+u32(right)
}
""","float-products.omni")
        ev=proc(OMNI,"eval",p); self.assertEqual(ev.returncode,5,ev.stderr)
        exe=self.d/"float-products"
        b=proc(OMNI,"build",p,"-o",exe,"--no-cache",timeout=90); self.assertEqual(b.returncode,0,b.stderr)
        native=proc(exe); self.assertEqual(native.returncode,5,native.stderr)

    def test_float_casts_are_explicit_and_range_checked(self):
        p=self.source("""module t
func main() u32 {
  let a f64 = f64(3u32)
  let b u32 = u32(7.9f64)
  return b+u32(a)
}
""")
        ev=proc(OMNI,"eval",p); self.assertEqual(ev.returncode,10,ev.stderr)
        exe=self.d/"casts"; b=proc(OMNI,"build",p,"-o",exe,"--no-cache",timeout=90); self.assertEqual(b.returncode,0,b.stderr)
        native=proc(exe); self.assertEqual(native.returncode,10,native.stderr)

    def test_float_nan_comparisons_follow_ieee(self):
        p=self.source("""module t
func main() u32 !{io.print} {
  let z f64 = 0.0f64
  let n f64 = z/z
  print(n==n)
  print(n!=n)
  print(n<1.0f64)
  return 0
}
""","nan.omni")
        ev=proc(OMNI,"eval",p); self.assertEqual(ev.returncode,0,ev.stderr); self.assertEqual(ev.stdout,b"false\ntrue\nfalse\n")
        exe=self.d/"nan"; b=proc(OMNI,"build",p,"-o",exe,"--no-cache",timeout=90); self.assertEqual(b.returncode,0,b.stderr)
        native=proc(exe); self.assertEqual((native.returncode,native.stdout),(0,ev.stdout),native.stderr)

    def test_float_integer_only_operators_fail_closed(self):
        for op in ("%", "+%", "+|"):
            with self.subTest(op=op):
                self.check_err(f"""module t
func main() u32 {{
  let x f64 = 3.0f64 {op} 2.0f64
  return 0
}}
""","E_TYPE")

    def test_float_semantics_remain_wave13_omc13_compatible_and_fail_below_13(self):
        p=self.source("""module t
func main() u32 {
  let x f64 = 1.25f64
  if x > 1.0f64 { return 1 }
  return 0
}
""","float-fence.omni")
        wave=proc(OMNI,"wave",p); self.assertEqual(wave.returncode,0,wave.stderr)
        self.assertTrue(wave.stdout.startswith(b"(omni-wave 18"))

        as13=self.d/"float-wave13.owave"
        as13.write_bytes(wave.stdout.replace(b"(omni-wave 18",b"(omni-wave 13",1))
        r13=proc(OMNI,"check",as13); self.assertEqual(r13.returncode,0,r13.stderr)

        as12=self.d/"float-wave12.owave"
        as12.write_bytes(wave.stdout.replace(b"(omni-wave 18",b"(omni-wave 12",1))
        r12=proc(OMNI,"check",as12); self.assertEqual(r12.returncode,2,r12.stderr); self.assertIn(b"E_VERSION",r12.stderr)

        wire=self.d/"float.omc15"; q=proc(OMNI,"pack",p,"-o",wire); self.assertEqual(q.returncode,0,q.stderr)
        raw=bytearray(wire.read_bytes()); self.assertEqual(raw[:4],b"OMCX"); self.assertEqual(int.from_bytes(raw[4:8],"little"),18)

        raw13=bytearray(raw); raw13[4:8]=(13).to_bytes(4,"little")
        omc13=self.d/"float-omc13.owire"; omc13.write_bytes(raw13)
        b13=proc(OMNI,"check",omc13); self.assertEqual(b13.returncode,0,b13.stderr)

        raw12=bytearray(raw); raw12[4:8]=(12).to_bytes(4,"little")
        omc12=self.d/"float-omc12.owire"; omc12.write_bytes(raw12)
        b12=proc(OMNI,"check",omc12); self.assertEqual(b12.returncode,2,b12.stderr); self.assertIn(b"E_VERSION",b12.stderr)

    def test_alpha8_borrowmut_semantics_remain_readable_as_wave12_omc12(self):
        p=self.source("""module t
func main() u32 !{memory.read,memory.write} {
  let allocation = buffer.alloc(8)
  match allocation {
    Ok(buf) {
      let exclusive = borrow_mut(buf)
      let write = buffer.write_u8(exclusive,0,7)
      match write { Ok(x) { } Err(e) { } }
      let n = buffer.len(exclusive)
      let released = buffer.release(move(buf))
      return n
    }
    Err(e) { return e }
  }
}
""","alpha8-borrowmut-compat.omni")

        wave=proc(OMNI,"wave",p); self.assertEqual(wave.returncode,0,wave.stderr)
        oldw=self.d/"borrowmut-wave12.owave"
        oldw.write_bytes(wave.stdout.replace(b"(omni-wave 18",b"(omni-wave 12",1))
        rw=proc(OMNI,"check",oldw)
        self.assertEqual(rw.returncode,0,rw.stderr)

        wire=self.d/"borrowmut.omc15"
        q=proc(OMNI,"pack",p,"-o",wire); self.assertEqual(q.returncode,0,q.stderr)
        raw=bytearray(wire.read_bytes()); self.assertEqual(int.from_bytes(raw[4:8],"little"),18)
        raw[4:8]=(12).to_bytes(4,"little")
        oldbin=self.d/"borrowmut-omc12.owire"; oldbin.write_bytes(raw)
        rb=proc(OMNI,"check",oldbin)
        self.assertEqual(rb.returncode,0,rb.stderr)

    def test_unicode_char_type_identity_layout_and_scalar_generic(self):
        d=json.loads(proc(OMNI,"type","describe","Char").stdout)
        self.assertEqual((d["kind"],d["width_bits"]),("unicode-scalar",32))
        layout=json.loads(proc(OMNI,"type","layout","Char").stdout)
        self.assertEqual((layout["size_bytes"],layout["alignment_bytes"]),(4,4))
        p=self.source("""module t
func identity<T:Scalar>(x T) T { return x }
func main() u32 {
  let c Result<Char,u32> = char.from_u32(233u32)
  match c { Ok(ch) { return char.codepoint(identity<Char>(ch)) } Err(e) { return e } }
}
""","char-generic.omni")
        ev=proc(OMNI,"eval",p); self.assertEqual(ev.returncode,233,ev.stderr)
        exe=self.d/"char-generic"; b=proc(OMNI,"build",p,"-o",exe,"--no-cache",timeout=90); self.assertEqual(b.returncode,0,b.stderr)
        native=proc(exe); self.assertEqual(native.returncode,233,native.stderr)

    def test_unicode_text_byte_scalar_lengths_and_access_eval_native(self):
        src=ROOT/"examples/unicode_text.omni"
        ev=proc(OMNI,"eval",src)
        self.assertEqual(ev.returncode,3,ev.stderr)
        self.assertEqual(ev.stdout,"7\n3\né\n233\n🙂\n".encode())
        exe=self.d/"unicode_text"
        b=proc(OMNI,"build",src,"-o",exe,"--no-cache",timeout=90); self.assertEqual(b.returncode,0,b.stderr)
        native=proc(exe); self.assertEqual((native.returncode,native.stdout),(ev.returncode,ev.stdout),native.stderr)

    def test_text_len_remains_byte_compatible(self):
        p=self.source("""module t
func main() u32 {
  let s Text = "é🙂"
  if text.len(s)==text.byte_len(s) { return text.scalar_len(s) }
  return 0
}
""","text-lengths.omni")
        ev=proc(OMNI,"eval",p); self.assertEqual(ev.returncode,2,ev.stderr)

    def test_invalid_unicode_scalar_and_scalar_oob_are_recoverable(self):
        p=self.source("""module t
func main() u32 {
  let bad Result<Char,u32> = char.from_u32(55296u32)
  match bad {
    Ok(ch) { return 9 }
    Err(e) {
      let oob Result<Char,u32> = text.scalar_at("é",1u32)
      match oob { Ok(ch) { return 8 } Err(e2) { return e+e2 } }
    }
  }
}
""","unicode-errors.omni")
        ev=proc(OMNI,"eval",p); self.assertEqual(ev.returncode,2,ev.stderr)
        exe=self.d/"unicode-errors"; b=proc(OMNI,"build",p,"-o",exe,"--no-cache",timeout=90); self.assertEqual(b.returncode,0,b.stderr)
        native=proc(exe); self.assertEqual(native.returncode,2,native.stderr)

    def test_nul_char_is_valid_but_text_conversion_fails_recoverably(self):
        p=self.source("""module t
func main() u32 {
  let z Result<Char,u32> = char.from_u32(0u32)
  match z {
    Ok(ch) {
      let t Result<Text,u32> = text.from_char(ch)
      match t { Ok(x) { return 9 } Err(e) { return e } }
    }
    Err(e) { return 8 }
  }
}
""","nul-char.omni")
        ev=proc(OMNI,"eval",p); self.assertEqual(ev.returncode,1,ev.stderr)
        exe=self.d/"nul-char"; b=proc(OMNI,"build",p,"-o",exe,"--no-cache",timeout=90); self.assertEqual(b.returncode,0,b.stderr)
        native=proc(exe); self.assertEqual(native.returncode,1,native.stderr)

    def test_text_equality_is_exact_without_implicit_normalization(self):
        p=self.source("""module t
func main() u32 {
  let composed Text = "é"
  let decomposed Text = "é"
  if text.equals(composed,composed) {
    if !text.equals(composed,decomposed) { return 1 }
  }
  return 0
}
""","text-equality.omni")
        ev=proc(OMNI,"eval",p); self.assertEqual(ev.returncode,1,ev.stderr)
        exe=self.d/"text-equality"; b=proc(OMNI,"build",p,"-o",exe,"--no-cache",timeout=90); self.assertEqual(b.returncode,0,b.stderr)
        native=proc(exe); self.assertEqual(native.returncode,1,native.stderr)

    def test_char_order_is_by_codepoint(self):
        p=self.source("""module t
func main() u32 {
  let a Result<Char,u32> = char.from_u32(65u32)
  match a {
    Ok(x) {
      let b Result<Char,u32> = char.from_u32(233u32)
      match b { Ok(y) { if x<y { return 1 } return 0 } Err(e) { return e } }
    }
    Err(e) { return e }
  }
}
""","char-order.omni")
        ev=proc(OMNI,"eval",p); self.assertEqual(ev.returncode,1,ev.stderr)

    def test_unicode_wave14_omc14_fence_and_float_wave13_compatibility(self):
        p=self.source("""module t
func main() u32 {
  let c Result<Char,u32> = text.scalar_at("é",0u32)
  match c { Ok(ch) { return char.codepoint(ch) } Err(e) { return e } }
}
""","unicode-fence.omni")
        wave=proc(OMNI,"wave",p); self.assertEqual(wave.returncode,0,wave.stderr)
        self.assertTrue(wave.stdout.startswith(b"(omni-wave 18"))
        oldw=self.d/"unicode-wave13.owave"; oldw.write_bytes(wave.stdout.replace(b"(omni-wave 18",b"(omni-wave 13",1))
        rw=proc(OMNI,"check",oldw); self.assertEqual(rw.returncode,2,rw.stderr); self.assertIn(b"E_VERSION",rw.stderr)

        wire=self.d/"unicode.omc15"; q=proc(OMNI,"pack",p,"-o",wire); self.assertEqual(q.returncode,0,q.stderr)
        raw=bytearray(wire.read_bytes()); self.assertEqual(int.from_bytes(raw[4:8],"little"),18); raw[4:8]=(13).to_bytes(4,"little")
        oldbin=self.d/"unicode-omc13.owire"; oldbin.write_bytes(raw)
        rb=proc(OMNI,"check",oldbin); self.assertEqual(rb.returncode,2,rb.stderr); self.assertIn(b"E_VERSION",rb.stderr)

    def test_unicode_onme2_round_trip(self):
        p=self.source("""module t
func main() u32 {
  let c Result<Char,u32> = text.scalar_at("🙂",0u32)
  match c { Ok(ch) { return 1 } Err(e) { return e } }
}
""","unicode-onme.omni")
        wave=proc(OMNI,"wave",p); self.assertEqual(wave.returncode,0,wave.stderr)
        encoded=self.d/"unicode.onme"; enc=proc(OMNI,"onme",p,"-o",encoded); self.assertEqual(enc.returncode,0,enc.stderr)
        decoded=proc(OMNI,"wave",encoded); self.assertEqual(decoded.returncode,0,decoded.stderr); self.assertEqual(decoded.stdout,wave.stdout)

    def test_a813_data_control_example_eval_native_match(self):
        src=ROOT/"examples/data_control.omni"
        ev=proc(OMNI,"eval",src)
        self.assertEqual(ev.returncode,100,ev.stderr)
        self.assertEqual(ev.stdout,b"40\n")
        exe=self.d/"data_control"
        b=proc(OMNI,"build",src,"-o",exe,"--no-cache",timeout=90)
        self.assertEqual(b.returncode,0,b.stderr)
        native=proc(exe)
        self.assertEqual((native.returncode,native.stdout),(ev.returncode,ev.stdout),native.stderr)

    def test_tuple_destructuring_arity_and_non_tuple_fail_closed(self):
        self.check_err("""module t
func main() u32 {
  let (a,b) = tuple(1u32,2u32,3u32)
  return a
}
""","E_PATTERN_ARITY")
        self.check_err("""module t
func main() u32 {
  let (a,b) = 1u32
  return a
}
""","E_PATTERN")

    def test_tuple_destructuring_wildcard_creates_no_binding(self):
        p=self.source("""module t
func main() u32 {
  let (a,_,c) = tuple(10u32,20u32,30u32)
  return a+c
}
""","tuple-destructure.omni")
        ev=proc(OMNI,"eval",p); self.assertEqual(ev.returncode,40,ev.stderr)
        exe=self.d/"tuple-destructure"; b=proc(OMNI,"build",p,"-o",exe,"--no-cache",timeout=90); self.assertEqual(b.returncode,0,b.stderr)
        native=proc(exe); self.assertEqual(native.returncode,40,native.stderr)

    def test_index_syntax_array_and_view(self):
        p=self.source("""module t
func main() u32 {
  let a Array<u32,3> = array(5u32,7u32,11u32)
  let v View<u32> = view(a)
  return a[1u32]+v[2u32]
}
""","index.omni")
        ev=proc(OMNI,"eval",p); self.assertEqual(ev.returncode,18,ev.stderr)
        exe=self.d/"index"; b=proc(OMNI,"build",p,"-o",exe,"--no-cache",timeout=90); self.assertEqual(b.returncode,0,b.stderr)
        native=proc(exe); self.assertEqual(native.returncode,18,native.stderr)

    def test_index_syntax_preserves_checked_bounds(self):
        p=self.source("""module t
func main() u32 {
  let a Array<u32,2> = array(1u32,2u32)
  return a[2u32]
}
""","index-oob.omni")
        ev=proc(OMNI,"eval",p); self.assertNotEqual(ev.returncode,0)
        self.assertIn(b"E_BOUNDS",ev.stderr)
        exe=self.d/"index-oob"; b=proc(OMNI,"build",p,"-o",exe,"--no-cache",timeout=90); self.assertEqual(b.returncode,0,b.stderr)
        native=proc(exe); self.assertNotEqual(native.returncode,0); self.assertIn(b"E_BOUNDS",native.stderr)

    def test_index_rejects_text_and_non_u32_index(self):
        self.check_err("""module t
func main() u32 {
  let s Text = "abc"
  let x = s[0u32]
  return 0
}
""","E_INDEX_TYPE")
        self.check_err("""module t
func main() u32 {
  let a Array<u32,2> = array(1u32,2u32)
  return a[1u8]
}
""","E_TYPE")

    def test_break_continue_outside_loop_are_rejected(self):
        self.check_err("""module t
func main() u32 {
  break
  return 0
}
""","E_LOOP_CONTROL")
        self.check_err("""module t
func main() u32 {
  continue
  return 0
}
""","E_LOOP_CONTROL")

    def test_continue_for_each_advances_and_break_targets_innermost_loop(self):
        p=self.source("""module t
func main() u32 {
  let a Array<u32,4> = array(1u32,2u32,3u32,4u32)
  var total u32 = 0u32
  for x in a {
    if x==2u32 { continue }
    if x==4u32 { break }
    total = total+x
  }
  return total
}
""","loop-control.omni")
        ev=proc(OMNI,"eval",p); self.assertEqual(ev.returncode,4,ev.stderr)
        exe=self.d/"loop-control"; b=proc(OMNI,"build",p,"-o",exe,"--no-cache",timeout=90); self.assertEqual(b.returncode,0,b.stderr)
        native=proc(exe); self.assertEqual(native.returncode,4,native.stderr)

    def test_break_cannot_consume_outer_result(self):
        self.check_err("""module t
func main() u32 {
  let r Result<u32,u32> = Ok<u32,u32>(1u32)
  for true {
    match r { Ok(_) { } Err(_) { } }
    break
  }
  return 0
}
""","E_RESULT_FLOW")

    def test_break_cannot_move_outer_resource(self):
        self.check_err("""module t
func main() u32 !{memory.write} {
  let allocation = buffer.alloc(1u32)
  match allocation {
    Ok(buf) {
      for true {
        let released = buffer.release(move(buf))
        break
      }
      return 0
    }
    Err(e) { return e }
  }
}
""","E_RESOURCE_FLOW")

    def test_wildcard_payload_patterns_result_option_enum(self):
        p=self.source("""module t
enum E { V(u32), N }
func main() u32 {
  let r Result<u32,u32> = Ok<u32,u32>(7u32)
  match r { Ok(_) { } Err(_) { return 9 } }
  let o Option<u32> = Some<u32>(8u32)
  match o { Some(_) { } None { return 8 } }
  let e E = E.V(3u32)
  match e { V(_) { return 1 } N { return 2 } }
}
""","wildcards.omni")
        ev=proc(OMNI,"eval",p); self.assertEqual(ev.returncode,1,ev.stderr)
        exe=self.d/"wildcards"; b=proc(OMNI,"build",p,"-o",exe,"--no-cache",timeout=90); self.assertEqual(b.returncode,0,b.stderr)
        native=proc(exe); self.assertEqual(native.returncode,1,native.stderr)

    def test_a813_wave15_omc15_downgrade_fence(self):
        p=ROOT/"examples/data_control.omni"
        wave=proc(OMNI,"wave",p); self.assertEqual(wave.returncode,0,wave.stderr)
        self.assertTrue(wave.stdout.startswith(b"(omni-wave 18"))
        oldw=self.d/"data-control-wave14.owave"
        oldw.write_bytes(wave.stdout.replace(b"(omni-wave 18",b"(omni-wave 14",1))
        rw=proc(OMNI,"check",oldw); self.assertEqual(rw.returncode,2,rw.stderr); self.assertIn(b"E_VERSION",rw.stderr)

        wire=self.d/"data-control.omc15"; q=proc(OMNI,"pack",p,"-o",wire); self.assertEqual(q.returncode,0,q.stderr)
        raw=bytearray(wire.read_bytes()); self.assertEqual(int.from_bytes(raw[4:8],"little"),18)
        raw[4:8]=(14).to_bytes(4,"little")
        oldbin=self.d/"data-control-omc14.owire"; oldbin.write_bytes(raw)
        rb=proc(OMNI,"check",oldbin); self.assertEqual(rb.returncode,2,rb.stderr); self.assertIn(b"E_VERSION",rb.stderr)

    def test_a812_unicode_semantics_remain_wave14_omc14_compatible(self):
        p=ROOT/"examples/unicode_text.omni"
        wave=proc(OMNI,"wave",p); self.assertEqual(wave.returncode,0,wave.stderr)
        self.assertTrue(wave.stdout.startswith(b"(omni-wave 18"))
        oldw=self.d/"unicode-wave14.owave"; oldw.write_bytes(wave.stdout.replace(b"(omni-wave 18",b"(omni-wave 14",1))
        rw=proc(OMNI,"check",oldw); self.assertEqual(rw.returncode,0,rw.stderr)

        wire=self.d/"unicode.omc15"; q=proc(OMNI,"pack",p,"-o",wire); self.assertEqual(q.returncode,0,q.stderr)
        raw=bytearray(wire.read_bytes()); self.assertEqual(int.from_bytes(raw[4:8],"little"),18); raw[4:8]=(14).to_bytes(4,"little")
        oldbin=self.d/"unicode-omc14.owire"; oldbin.write_bytes(raw)
        rb=proc(OMNI,"check",oldbin); self.assertEqual(rb.returncode,0,rb.stderr)

    def test_a813_onme2_round_trip_and_formatter(self):
        p=ROOT/"examples/data_control.omni"
        wave=proc(OMNI,"wave",p); self.assertEqual(wave.returncode,0,wave.stderr)
        encoded=self.d/"data-control.onme"; enc=proc(OMNI,"onme",p,"-o",encoded); self.assertEqual(enc.returncode,0,enc.stderr)
        decoded=proc(OMNI,"wave",encoded); self.assertEqual(decoded.returncode,0,decoded.stderr); self.assertEqual(decoded.stdout,wave.stdout)

        src=self.d/"fmt.omni"; src.write_text(p.read_text(encoding="utf-8"),encoding="utf-8")
        first=proc(OMNI,"fmt",src); self.assertEqual(first.returncode,0,first.stderr)
        canonical=self.d/"fmt-canonical.omni"; canonical.write_bytes(first.stdout)
        second=proc(OMNI,"fmt",canonical); self.assertEqual(second.returncode,0,second.stderr)
        self.assertEqual(second.stdout,first.stdout)

    def test_legacy_wave14_and_omc14_remain_readable(self):
        for ext in ("owave","owire"):
            p=ROOT/"reference/compat"/f"legacy14.{ext}"
            self.assertTrue(p.is_file(),p)
            r=proc(OMNI,"check",p)
            self.assertEqual(r.returncode,0,(ext,r.stderr))

    def test_a814_range_type_identity_and_layout(self):
        d=json.loads(proc(OMNI,"type","describe","Range<u32>").stdout)
        self.assertEqual((d["kind"],d["element_type"]),("range","u32"))
        layout=json.loads(proc(OMNI,"type","layout","Range<u32>").stdout)
        self.assertEqual((layout["size_bytes"],layout["alignment_bytes"]),(12,4))
        self.assertEqual(layout["field_offsets"],[0,4,8])

    def test_a814_range_example_eval_native_match(self):
        src=ROOT/"examples/ranges.omni"
        ev=proc(OMNI,"eval",src)
        self.assertEqual(ev.returncode,22,ev.stderr)
        self.assertEqual(ev.stdout,b"22\n")
        exe=self.d/"ranges"
        b=proc(OMNI,"build",src,"-o",exe,"--no-cache",timeout=90)
        self.assertEqual(b.returncode,0,b.stderr)
        native=proc(exe)
        self.assertEqual((native.returncode,native.stdout),(ev.returncode,ev.stdout),native.stderr)

    def test_range_exclusive_inclusive_empty_and_equal_bounds(self):
        p=self.source("""module t
func main() u32 {
  var count u32 = 0u32
  for x in 3u32..3u32 { count = count+1u32 }
  for x in 3u32..=3u32 { count = count+1u32 }
  for x in 5u32..2u32 { count = count+1u32 }
  return count
}
""","range-bounds.omni")
        ev=proc(OMNI,"eval",p); self.assertEqual(ev.returncode,1,ev.stderr)
        exe=self.d/"range-bounds"; b=proc(OMNI,"build",p,"-o",exe,"--no-cache",timeout=90); self.assertEqual(b.returncode,0,b.stderr)
        native=proc(exe); self.assertEqual(native.returncode,1,native.stderr)

    def test_inclusive_u32_max_terminates_without_wraparound(self):
        p=self.source("""module t
func main() u32 {
  var count u32 = 0u32
  for x in 4294967295u32..=4294967295u32 { count = count+1u32 }
  return count
}
""","range-max.omni")
        ev=proc(OMNI,"eval",p); self.assertEqual(ev.returncode,1,ev.stderr)
        exe=self.d/"range-max"; b=proc(OMNI,"build",p,"-o",exe,"--no-cache",timeout=90); self.assertEqual(b.returncode,0,b.stderr)
        native=proc(exe); self.assertEqual(native.returncode,1,native.stderr)

    def test_range_is_first_class_and_for_wildcard_is_supported(self):
        p=self.source("""module t
func main() u32 {
  let r Range<u32> = 2u32..5u32
  var count u32 = 0u32
  for _ in r { count = count+1u32 }
  return count
}
""","range-first-class.omni")
        ev=proc(OMNI,"eval",p); self.assertEqual(ev.returncode,3,ev.stderr)
        exe=self.d/"range-first-class"; b=proc(OMNI,"build",p,"-o",exe,"--no-cache",timeout=90); self.assertEqual(b.returncode,0,b.stderr)
        native=proc(exe); self.assertEqual(native.returncode,3,native.stderr)

    def test_range_endpoints_and_type_are_u32_only(self):
        self.check_err("""module t
func main() u32 {
  let r Range<i32> = 1u32..2u32
  return 0
}
""","E_RANGE_TYPE")
        self.check_err("""module t
func main() u32 {
  let r = 1u8..2u8
  return 0
}
""","E_TYPE")

    def test_a814_wave16_omc16_downgrade_fence(self):
        p=ROOT/"examples/ranges.omni"
        wave=proc(OMNI,"wave",p); self.assertEqual(wave.returncode,0,wave.stderr)
        self.assertTrue(wave.stdout.startswith(b"(omni-wave 18"))
        oldw=self.d/"range-wave15.owave"; oldw.write_bytes(wave.stdout.replace(b"(omni-wave 18",b"(omni-wave 15",1))
        rw=proc(OMNI,"check",oldw); self.assertEqual(rw.returncode,2,rw.stderr); self.assertIn(b"E_VERSION",rw.stderr)

        wire=self.d/"range.omc16"; q=proc(OMNI,"pack",p,"-o",wire); self.assertEqual(q.returncode,0,q.stderr)
        raw=bytearray(wire.read_bytes()); self.assertEqual(int.from_bytes(raw[4:8],"little"),18); raw[4:8]=(15).to_bytes(4,"little")
        oldbin=self.d/"range-omc15.owire"; oldbin.write_bytes(raw)
        rb=proc(OMNI,"check",oldbin); self.assertEqual(rb.returncode,2,rb.stderr); self.assertIn(b"E_VERSION",rb.stderr)

    def test_a813_semantics_remain_wave15_omc15_compatible(self):
        p=ROOT/"examples/data_control.omni"
        wave=proc(OMNI,"wave",p); self.assertEqual(wave.returncode,0,wave.stderr)
        self.assertTrue(wave.stdout.startswith(b"(omni-wave 18"))
        oldw=self.d/"data-control-wave15.owave"; oldw.write_bytes(wave.stdout.replace(b"(omni-wave 18",b"(omni-wave 15",1))
        rw=proc(OMNI,"check",oldw); self.assertEqual(rw.returncode,0,rw.stderr)

        wire=self.d/"data-control.omc16"; q=proc(OMNI,"pack",p,"-o",wire); self.assertEqual(q.returncode,0,q.stderr)
        raw=bytearray(wire.read_bytes()); self.assertEqual(int.from_bytes(raw[4:8],"little"),18); raw[4:8]=(15).to_bytes(4,"little")
        oldbin=self.d/"data-control-omc15.owire"; oldbin.write_bytes(raw)
        rb=proc(OMNI,"check",oldbin); self.assertEqual(rb.returncode,0,rb.stderr)

    def test_a814_onme2_round_trip_and_formatter(self):
        p=ROOT/"examples/ranges.omni"
        wave=proc(OMNI,"wave",p); self.assertEqual(wave.returncode,0,wave.stderr)
        encoded=self.d/"range.onme"; enc=proc(OMNI,"onme",p,"-o",encoded); self.assertEqual(enc.returncode,0,enc.stderr)
        decoded=proc(OMNI,"wave",encoded); self.assertEqual(decoded.returncode,0,decoded.stderr); self.assertEqual(decoded.stdout,wave.stdout)

        src=self.d/"range-fmt.omni"; src.write_text(p.read_text(encoding="utf-8"),encoding="utf-8")
        first=proc(OMNI,"fmt",src); self.assertEqual(first.returncode,0,first.stderr)
        canonical=self.d/"range-fmt-canonical.omni"; canonical.write_bytes(first.stdout)
        second=proc(OMNI,"fmt",canonical); self.assertEqual(second.returncode,0,second.stderr)
        self.assertEqual(second.stdout,first.stdout)

    def test_legacy_wave15_and_omc15_remain_readable(self):
        for ext in ("owave","owire"):
            p=ROOT/"reference/compat"/f"legacy15.{ext}"
            self.assertTrue(p.is_file(),p)
            r=proc(OMNI,"check",p)
            self.assertEqual(r.returncode,0,(ext,r.stderr))

    def test_float_onme2_round_trip_preserves_wave13_semantics(self):
        p=self.source("""module t
func main() u32 {
  let x f64 = 1.25f64
  if x > 1.0f64 { return 1 }
  return 0
}
""","float-onme.omni")
        wave=proc(OMNI,"wave",p); self.assertEqual(wave.returncode,0,wave.stderr)
        encoded=self.d/"float.onme"
        enc=proc(OMNI,"onme",p,"-o",encoded); self.assertEqual(enc.returncode,0,enc.stderr)
        self.assertTrue(encoded.read_bytes().startswith(b"ONME2\n"))
        decoded=proc(OMNI,"wave",encoded); self.assertEqual(decoded.returncode,0,decoded.stderr)
        self.assertEqual(decoded.stdout,wave.stdout)
        checked=proc(OMNI,"check",encoded); self.assertEqual(checked.returncode,0,checked.stderr)

    def test_legacy_wave13_and_omc13_remain_readable(self):
        for ext in ("owave","owire"):
            p=ROOT/"reference/compat"/f"legacy13.{ext}"
            self.assertTrue(p.is_file(),p)
            r=proc(OMNI,"check",p)
            self.assertEqual(r.returncode,0,(ext,r.stderr))

    def test_legacy_wave12_and_omc12_remain_readable(self):
        for ext in ("owave","owire"):
            p=ROOT/"reference/compat"/f"legacy12.{ext}"
            self.assertTrue(p.is_file(),p)
            r=proc(OMNI,"check",p)
            self.assertEqual(r.returncode,0,(ext,r.stderr))

if __name__=="__main__":
    unittest.main(verbosity=2)
