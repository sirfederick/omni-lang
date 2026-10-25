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
func main() u32 !{io.print} {
  let x f32 = 1.5f32+2.25f32
  print(x)
  return 0
}
""",
"""module t
func main() u32 !{io.print} {
  let x f64 = 9.0f64/4.0f64
  print(x)
  return 0
}
""",
"""module t
func main() u32 {
  let x u32 = u32(7.9f64)
  return x
}
""",
"""module t
func main() u32 {
  let x f64 = f64(21u32)
  return u32(x/2.0f64)
}
""",
"""module t
func main() u32 {
  let x f64 = -5.5f64
  if x < 0.0f64 { return 1 }
  return 0
}
""",
"""module t
func main() u32 !{io.print} {
  let z f64 = 0.0f64
  let n f64 = z/z
  print(n==n)
  print(n!=n)
  return 0
}
""",
"""module t
func main() u32 {
  let x f32 = 2.5e-1f32
  if x==0.25f32 { return 1 }
  return 0
}
""",
"""module t
func main() u32 {
  let x f64 = 1e2f64
  let y f32 = f32(x)
  return u32(y)
}
"""
]

with tempfile.TemporaryDirectory(prefix="omni-float-diff-") as td:
    d=pathlib.Path(td)
    observations=0
    for i,source in enumerate(cases):
        src=d/f"c{i}.omni"; src.write_text(source,encoding="utf-8")
        chk=run(OMNI,"check",src)
        if chk.returncode!=0:
            raise SystemExit(f"float differential check {i} failed: {chk.stderr.decode(errors='replace')}")
        ev=run(OMNI,"eval",src)
        exe=d/f"c{i}"
        build=run(OMNI,"build",src,"-o",exe,"--no-cache")
        if build.returncode!=0:
            raise SystemExit(f"float differential build {i} failed: {build.stderr.decode(errors='replace')}")
        native=run(exe)
        if (ev.returncode,ev.stdout)!=(native.returncode,native.stdout):
            raise SystemExit(
                f"float differential case {i}: eval={(ev.returncode,ev.stdout)!r} "
                f"native={(native.returncode,native.stdout)!r} "
                f"evalerr={ev.stderr!r} nativeerr={native.stderr!r}"
            )
        observations+=1

print(f"float evaluator/native differential: {observations}/{len(cases)} MATCH")
