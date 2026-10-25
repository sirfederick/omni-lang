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
  var s u32 = 0u32
  for x in 1u32..5u32 { s=s+x }
  return s
}
""",
"""module t
func main() u32 {
  var s u32 = 0u32
  for x in 1u32..=5u32 { s=s+x }
  return s
}
""",
"""module t
func main() u32 {
  let r Range<u32> = 2u32..6u32
  var c u32 = 0u32
  for _ in r { c=c+1u32 }
  return c
}
""",
"""module t
func main() u32 {
  var c u32 = 0u32
  for x in 3u32..3u32 { c=c+1u32 }
  for x in 3u32..=3u32 { c=c+1u32 }
  return c
}
""",
"""module t
func main() u32 {
  var c u32 = 0u32
  for x in 9u32..3u32 { c=c+1u32 }
  return c
}
""",
"""module t
func main() u32 {
  var c u32 = 0u32
  for x in 4294967295u32..=4294967295u32 { c=c+1u32 }
  return c
}
""",
"""module t
func main() u32 {
  var s u32 = 0u32
  for x in 0u32..10u32 {
    if x==2u32 { continue }
    if x==5u32 { break }
    s=s+x
  }
  return s
}
""",
"""module t
func main() u32 {
  let r Range<u32> = 1u32..=3u32
  let pair Tuple<Range<u32>,u32> = tuple(r,7u32)
  let rr Range<u32> = tuple.get(pair,0u32)
  var s u32 = 0u32
  for x in rr { s=s+x }
  return s
}
"""
]

with tempfile.TemporaryDirectory(prefix="omni-range-diff-") as td:
    d=pathlib.Path(td)
    observations=0
    for i,source in enumerate(cases):
        src=d/f"r{i}.omni"; src.write_text(source,encoding="utf-8")
        chk=run(OMNI,"check",src)
        if chk.returncode!=0:
            raise SystemExit(f"range differential check {i} failed: {chk.stderr.decode(errors='replace')}")
        ev=run(OMNI,"eval",src)
        exe=d/f"r{i}"
        build=run(OMNI,"build",src,"-o",exe,"--no-cache")
        if build.returncode!=0:
            raise SystemExit(f"range differential build {i} failed: {build.stderr.decode(errors='replace')}")
        native=run(exe)
        if (ev.returncode,ev.stdout)!=(native.returncode,native.stdout):
            raise SystemExit(
                f"range differential case {i}: eval={(ev.returncode,ev.stdout)!r} "
                f"native={(native.returncode,native.stdout)!r} "
                f"evalerr={ev.stderr!r} nativeerr={native.stderr!r}"
            )
        observations+=1

print(f"range evaluator/native differential: {observations}/{len(cases)} MATCH")
