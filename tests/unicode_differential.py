#!/usr/bin/env python3
from __future__ import annotations
import os, pathlib, subprocess, tempfile

ROOT=pathlib.Path(__file__).resolve().parents[1]
OMNI=pathlib.Path(os.environ.get("OMNI_TEST_BIN",ROOT/"bin/linux-x86_64/omni"))

def run(*args,timeout=90):
    return subprocess.run([str(x) for x in args],capture_output=True,timeout=timeout,
                          env={**os.environ,"OMNI_HOME":str(ROOT)})

cases=[
"""module t
func main() u32 {
  return text.scalar_len("Aé🙂")
}
""",
"""module t
func main() u32 {
  let c Result<Char,u32> = text.scalar_at("Aé🙂",1u32)
  match c { Ok(ch) { return char.codepoint(ch) } Err(e) { return e } }
}
""",
"""module t
func main() u32 {
  let c Result<Char,u32> = char.from_u32(128578u32)
  match c { Ok(ch) { let t Result<Text,u32> = text.from_char(ch); match t { Ok(x) { return text.scalar_len(x) } Err(e) { return e } } } Err(e) { return e } }
}
""",
"""module t
func main() u32 {
  let c Result<Char,u32> = char.from_u32(55296u32)
  match c { Ok(ch) { return 9 } Err(e) { return e } }
}
""",
"""module t
func main() u32 {
  let a Text = "é"
  let b Text = "é"
  if !text.equals(a,b) { return 1 }
  return 0
}
""",
"""module t
func main() u32 {
  let a Result<Char,u32> = char.from_u32(65u32)
  match a { Ok(x) { let b Result<Char,u32> = char.from_u32(233u32); match b { Ok(y) { if x<y { return 1 } return 0 } Err(e) { return e } } } Err(e) { return e } }
}
""",
"""module t
func main() u32 {
  if text.len("é🙂")==text.byte_len("é🙂") { return text.scalar_len("é🙂") }
  return 0
}
""",
"""module t
func main() u32 {
  let z Result<Char,u32> = char.from_u32(0u32)
  match z { Ok(ch) { let t Result<Text,u32> = text.from_char(ch); match t { Ok(x) { return 9 } Err(e) { return e } } } Err(e) { return 8 } }
}
"""
]

with tempfile.TemporaryDirectory(prefix="omni-unicode-diff-") as td:
    d=pathlib.Path(td)
    observations=0
    for i,source in enumerate(cases):
        src=d/f"u{i}.omni"; src.write_text(source,encoding="utf-8")
        chk=run(OMNI,"check",src)
        if chk.returncode!=0:
            raise SystemExit(f"unicode differential check {i} failed: {chk.stderr.decode(errors='replace')}")
        ev=run(OMNI,"eval",src)
        exe=d/f"u{i}"
        build=run(OMNI,"build",src,"-o",exe,"--no-cache")
        if build.returncode!=0:
            raise SystemExit(f"unicode differential build {i} failed: {build.stderr.decode(errors='replace')}")
        native=run(exe)
        if (ev.returncode,ev.stdout)!=(native.returncode,native.stdout):
            raise SystemExit(
                f"unicode differential case {i}: eval={(ev.returncode,ev.stdout)!r} "
                f"native={(native.returncode,native.stdout)!r} "
                f"evalerr={ev.stderr!r} nativeerr={native.stderr!r}"
            )
        observations+=1

print(f"unicode evaluator/native differential: {observations}/{len(cases)} MATCH")
