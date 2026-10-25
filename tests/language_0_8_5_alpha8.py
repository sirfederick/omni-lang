#!/usr/bin/env python3
from __future__ import annotations

import os
import pathlib
import subprocess
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
OMNI = pathlib.Path(os.environ.get("OMNI_TEST_BIN", ROOT / "bin/linux-x86_64/omni"))


def proc(*args: object) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run([str(arg) for arg in args], capture_output=True, timeout=20,
                          env={**os.environ, "OMNI_HOME": str(ROOT)})


class A85TaskScopeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="omni-a85-")
        self.dir = pathlib.Path(self.tmp.name)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def source(self, text: str) -> pathlib.Path:
        path = self.dir / "program.omni"
        path.write_text(text, encoding="utf-8")
        return path

    def test_join_is_deterministic_and_fenced_as_wave19(self) -> None:
        source = self.source("""module t
func main() u32 {
  task_scope {
    spawn child = 40u32 + 2u32;
    let outcome = join(child);
    match outcome { Ok(value) { return value; } Err(code) { return code; } }
  }
}
""")
        self.assertEqual(proc(OMNI, "check", source).returncode, 0)
        wave = proc(OMNI, "wave", source)
        self.assertEqual(wave.returncode, 0, wave.stderr)
        self.assertTrue(wave.stdout.startswith(b"(omni-wave 19"))
        wire = self.dir / "task.owire"
        self.assertEqual(proc(OMNI, "pack", source, "-o", wire).returncode, 0)
        raw = wire.read_bytes()
        self.assertEqual(raw[:8], b"OMCX\x13\x00\x00\x00")
        self.assertEqual(proc(OMNI, "check", wire).returncode, 0)
        old = self.dir / "task-as-omc18.owire"
        old.write_bytes(raw[:4] + (18).to_bytes(4, "little") + raw[8:])
        downgraded = proc(OMNI, "check", old)
        self.assertEqual(downgraded.returncode, 2)
        self.assertIn(b"E_WIRE", downgraded.stderr)
        self.assertEqual(proc(OMNI, "eval", source).returncode, 42)
        native = self.dir / "native"
        self.assertEqual(proc(OMNI, "build", source, "-o", native).returncode, 0)
        self.assertEqual(proc(native).returncode, 42)

    def test_orphaned_child_is_rejected(self) -> None:
        source = self.source("""module t
func main() u32 { task_scope { spawn child = 1u32; } return 0u32; }
""")
        result = proc(OMNI, "check", source)
        self.assertEqual(result.returncode, 2)
        self.assertIn(b"E_TASK_ORPHAN", result.stderr)

    def test_cancel_consumes_the_handle_with_a_typed_outcome(self) -> None:
        source = self.source("""module t
func main() u32 { task_scope { spawn child = 42u32; let outcome = cancel(child); match outcome { Ok(code) { return code; } Err(code) { return code; } } } }
""")
        self.assertEqual(proc(OMNI, "check", source).returncode, 0)
        self.assertEqual(proc(OMNI, "eval", source).returncode, 1)
        native = self.dir / "native-cancel"
        self.assertEqual(proc(OMNI, "build", source, "-o", native).returncode, 0)
        self.assertEqual(proc(native).returncode, 1)

    def test_logical_deadline_is_typed_and_deterministic(self) -> None:
        source = self.source("""module t
func main() u32 { task_scope { spawn child = 7u32; let outcome = deadline(child, 0u32); match outcome { Ok(value) { return value; } Err(code) { return code; } } } }
""")
        self.assertEqual(proc(OMNI, "check", source).returncode, 0)
        self.assertEqual(proc(OMNI, "eval", source).returncode, 4)
        native = self.dir / "native-deadline"
        self.assertEqual(proc(OMNI, "build", source, "-o", native).returncode, 0)
        self.assertEqual(proc(native).returncode, 4)

    def test_task_handle_escape_is_rejected(self) -> None:
        source = self.source("""module t
func main() u32 { task_scope { spawn child = 1u32; let forged = child; let result = join(child); match result { Ok(value) { return value; } Err(code) { return code; } } } }
""")
        result = proc(OMNI, "check", source)
        self.assertEqual(result.returncode, 2)
        self.assertIn(b"E_TASK_HANDLE_ESCAPE", result.stderr)

    def test_spawn_outside_scope_is_rejected(self) -> None:
        source = self.source("module t\nfunc main() u32 { spawn child = 1u32; return 0u32; }\n")
        result = proc(OMNI, "check", source)
        self.assertEqual(result.returncode, 2)
        self.assertIn(b"E_TASK_SCOPE", result.stderr)

    def test_bounded_channel_backpressure_close_and_drain(self) -> None:
        source = self.source("""module t
func main() u32 {
  let stream = channel<u32>(1u32);
  let first = send(stream, 7u32);
  match first { Ok(sent) {
  let second = send(stream, 9u32);
  match second {
    Ok(unexpected) { return unexpected; }
    Err(backpressure) {
      let received = receive(stream);
      match received {
        Ok(item) {
          match item {
            Some(value) {
              let closed = close(stream);
              match closed { Ok(closed_code) {
              let drained = receive(stream);
              match drained {
                Ok(final_item) { match final_item { Some(other) { return other; } None { return value; } } }
                Err(code) { return code; }
              }
              } Err(code) { return code; } }
            }
            None { return 90u32; }
          }
        }
        Err(code) { return code; }
      }
    }
  }
  } Err(code) { return code; } }
}
""")
        self.assertEqual(proc(OMNI, "check", source).returncode, 0)
        self.assertEqual(proc(OMNI, "eval", source).returncode, 7)
        native = self.dir / "native-channel"
        self.assertEqual(proc(OMNI, "build", source, "-o", native).returncode, 0)
        self.assertEqual(proc(native).returncode, 7)

    def test_send_after_close_and_zero_capacity_reject(self) -> None:
        after_close = self.source("""module t
func main() u32 { let stream = channel<u32>(1u32); let closed = close(stream); let bad = send(stream, 1u32); return 0u32; }
""")
        result = proc(OMNI, "check", after_close)
        self.assertEqual(result.returncode, 2)
        self.assertIn(b"E_CHANNEL_CLOSED", result.stderr)
        zero = self.source("module t\nfunc main() u32 { let stream = channel<u32>(0u32); return 0u32; }\n")
        result = proc(OMNI, "check", zero)
        self.assertEqual(result.returncode, 2)
        self.assertIn(b"E_CHANNEL_CAPACITY", result.stderr)

    def test_native_runtime_context_is_fresh_per_invocation(self) -> None:
        # This is intentionally a narrow ABI-level regression: two contexts in
        # one host process must not share an A85 channel table or queued value.
        harness = self.dir / "runtime_context.c"
        harness.write_text("""#include <stdint.h>
void omni_runtime_begin(void); void omni_runtime_end(void);
uint64_t omni_channel_new(uint32_t); uint32_t omni_channel_send(uint64_t, uint64_t);
uint32_t omni_channel_receive(uint64_t, uint64_t *);
int main(void) {
  uint64_t value = 0;
  omni_runtime_begin();
  uint64_t first = omni_channel_new(1);
  if (first != 1 || omni_channel_send(first, 7) != 0 || omni_channel_receive(first, &value) != 0 || value != 7) return 1;
  omni_runtime_end();
  omni_runtime_begin();
  uint64_t second = omni_channel_new(1);
  if (second != 1 || omni_channel_receive(second, &value) != 3) return 2;
  omni_runtime_end();
  return 0;
}
""", encoding="utf-8")
        native = self.dir / "runtime-context"
        compiler = os.environ.get("CC", "clang")
        compiled = proc(compiler, "-std=c11", "-Wall", "-Wextra", "-Werror", harness,
                        ROOT / "runtime/omni_runtime.c", "-o", native)
        self.assertEqual(compiled.returncode, 0, compiled.stderr)
        self.assertEqual(proc(native).returncode, 0)


if __name__ == "__main__":
    unittest.main()
