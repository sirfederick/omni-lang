#!/usr/bin/env python3
from __future__ import annotations
import json, os, pathlib, subprocess, tempfile

ROOT=pathlib.Path(__file__).resolve().parents[1]
OMNI=pathlib.Path(os.environ.get("OMNI_TEST_BIN",ROOT/"bin/linux-x86_64/omni"))

def run(*args,timeout=45):
    return subprocess.run([str(x) for x in args],capture_output=True,timeout=timeout,
                          env={**os.environ,"OMNI_HOME":str(ROOT)})

cases=[
"""module t
func main() u32 !{memory.read,memory.write} {
  let allocation = buffer.alloc(4)
  match allocation {
    Ok(buf) {
      let n = buffer.len(borrow(buf))
      let released = buffer.release(move(buf))
      return n
    }
    Err(e) { return e }
  }
}""",
"""module t
func main() u32 !{memory.read,memory.write} {
  let allocation = buffer.alloc(6)
  match allocation {
    Ok(buf) {
      let shared = borrow(buf)
      let n = buffer.len(shared)
      let released = buffer.release(move(buf))
      return n
    }
    Err(e) { return e }
  }
}""",
"""module t
func main() u32 !{memory.read,memory.write} {
  let allocation = buffer.alloc(8)
  match allocation {
    Ok(buf) {
      let exclusive = borrow_mut(buf)
      let write = buffer.write_u8(exclusive,0,9)
      match write {
        Ok(x) { }
        Err(e) { }
      }
      let n = buffer.len(exclusive)
      let released = buffer.release(move(buf))
      return n
    }
    Err(e) { return e }
  }
}"""
]

with tempfile.TemporaryDirectory(prefix="omni-alpha8-memory-diff-") as td:
    d=pathlib.Path(td)
    observations=0
    for i,source in enumerate(cases):
        src=d/f"c{i}.omni"
        src.write_text(source,encoding="utf-8")
        ev=run(OMNI,"eval",src)
        exe=d/f"c{i}"
        build=run(OMNI,"build",src,"-o",exe,"--no-cache")
        if build.returncode!=0:
            raise SystemExit(f"build case {i} failed: {build.stderr.decode(errors='replace')}")
        native=run(exe)
        if (ev.returncode,ev.stdout)!=(native.returncode,native.stdout):
            raise SystemExit(
                f"alpha8 memory differential case {i}: "
                f"eval={(ev.returncode,ev.stdout)!r} native={(native.returncode,native.stdout)!r} "
                f"evalerr={ev.stderr!r} nativeerr={native.stderr!r}"
            )
        observations+=1
print(f"alpha8 memory/authority differential: {observations}/{len(cases)} MATCH")

# Reached only after the original assertions/comparisons have all succeeded.
print(json.dumps({"schema": 'omni.memory_authority-differential/1', "status": "PASS",
                  "observations": observations, "checks": {
    'all_evaluator_native_cases': observations == len(cases) and observations > 0,
}}))
