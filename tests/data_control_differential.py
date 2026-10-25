#!/usr/bin/env python3
from __future__ import annotations
import json, os, pathlib, subprocess, tempfile

ROOT=pathlib.Path(__file__).resolve().parents[1]
OMNI=pathlib.Path(os.environ.get("OMNI_TEST_BIN",ROOT/"bin/linux-x86_64/omni"))

def run(*args,timeout=90):
    return subprocess.run([str(x) for x in args],capture_output=True,timeout=timeout,
                          env={**os.environ,"OMNI_HOME":str(ROOT)})

cases=[
"""module t
func main() u32 {
  let (a,b) = tuple(3u32,7u32)
  return a+b
}
""",
"""module t
func main() u32 {
  let (a,_,c) = tuple(10u32,20u32,30u32)
  return a+c
}
""",
"""module t
func main() u32 {
  let a Array<u32,3> = array(5u32,7u32,11u32)
  return a[1u32]+a[2u32]
}
""",
"""module t
func main() u32 {
  let a Array<u32,3> = array(5u32,7u32,11u32)
  let v View<u32> = view(a)
  return v[0u32]+v[2u32]
}
""",
"""module t
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
""",
"""module t
func main() u32 {
  var x u32 = 0u32
  for x<10u32 {
    x=x+1u32
    if x<3u32 { continue }
    if x==5u32 { break }
  }
  return x
}
""",
"""module t
enum E { V(u32), N }
func main() u32 {
  let e E = E.V(9u32)
  match e { V(_) { return 1 } N { return 2 } }
}
""",
"""module t
func main() u32 {
  let r Result<u32,u32> = Ok<u32,u32>(9u32)
  match r { Ok(_) { return 1 } Err(_) { return 2 } }
}
"""
]

with tempfile.TemporaryDirectory(prefix="omni-data-control-diff-") as td:
    d=pathlib.Path(td)
    observations=0
    for i,source in enumerate(cases):
        src=d/f"d{i}.omni"; src.write_text(source,encoding="utf-8")
        chk=run(OMNI,"check",src)
        if chk.returncode!=0:
            raise SystemExit(f"data/control differential check {i} failed: {chk.stderr.decode(errors='replace')}")
        ev=run(OMNI,"eval",src)
        exe=d/f"d{i}"
        build=run(OMNI,"build",src,"-o",exe,"--no-cache")
        if build.returncode!=0:
            raise SystemExit(f"data/control differential build {i} failed: {build.stderr.decode(errors='replace')}")
        native=run(exe)
        if (ev.returncode,ev.stdout)!=(native.returncode,native.stdout):
            raise SystemExit(
                f"data/control differential case {i}: eval={(ev.returncode,ev.stdout)!r} "
                f"native={(native.returncode,native.stdout)!r} "
                f"evalerr={ev.stderr!r} nativeerr={native.stderr!r}"
            )
        observations+=1

print(f"data/control evaluator/native differential: {observations}/{len(cases)} MATCH")

# Reached only after the original assertions/comparisons have all succeeded.
print(json.dumps({"schema": 'omni.data_control-differential/1', "status": "PASS",
                  "observations": observations, "checks": {
    'all_evaluator_native_cases': observations == len(cases) and observations > 0,
}}))
