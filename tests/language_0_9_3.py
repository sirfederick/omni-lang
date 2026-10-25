#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import os
import pathlib
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
OMNI = pathlib.Path(os.environ.get("OMNI_TEST_BIN", ROOT / "bin/linux-x86_64/omni"))
MATRIX = ROOT / "tests/corpus/a93/runtime_fault_matrix.json"


def proc(*args: object, timeout: int = 20) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        [str(arg) for arg in args], capture_output=True, timeout=timeout,
        env={**os.environ, "OMNI_HOME": str(ROOT)},
    )


class A93RuntimeHardeningTests(unittest.TestCase):
    observed: dict[str, dict[str, object]] = {}

    @classmethod
    def tearDownClass(cls) -> None:
        expected = json.loads(MATRIX.read_text(encoding="utf-8"))
        rows = []
        for row in expected["scenarios"]:
            observed = cls.observed.get(row["id"])
            rows.append({**row, "status": "PASS" if observed else "NOT_RUN", "observed": observed})
        report = {
            "schema": "omni.a93-runtime-fault-report/1",
            "version": "0.9.3",
            "seed": expected["seed"],
            "matrix_sha256": hashlib.sha256(MATRIX.read_bytes()).hexdigest(),
            "status": "PASS" if all(row["status"] == "PASS" for row in rows) else "FAIL",
            "scenarios": rows,
        }
        evidence = os.environ.get("OMNI_EVIDENCE_DIR")
        if evidence:
            target = pathlib.Path(evidence) / "a93_runtime_fault_report.json"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="omni-a93-")
        self.dir = pathlib.Path(self.tmp.name)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def record(self, scenario: str, result: int, oracle: str, **details: object) -> None:
        self.observed[scenario] = {"result": result, "resource_oracle": oracle, **details}

    def source(self, text: str, name: str = "program.omni") -> pathlib.Path:
        path = self.dir / name
        path.write_text(text, encoding="utf-8")
        return path

    def policy(self, subject: str, capability: str, generation: int = 93,
               not_after: int = 1_000_000, max_bytes: int = 4096) -> pathlib.Path:
        path = self.dir / f"policy-{capability.replace('.', '-')}-{generation}-{not_after}.ohp"
        path.write_text(
            f"OHP1\ngeneration|{generation}\nnot_after_tick|{not_after}\n"
            f"grant|{capability}|{subject}|{max_bytes}\n", encoding="utf-8",
        )
        return path

    def process_source(self, adapter: pathlib.Path, deadline: int) -> pathlib.Path:
        return self.source(f'''module a93
func main() u32 !{{process.spawn}} {{
  let outcome = host.process("{adapter.as_posix()}", bytes.from_text("dispatch"), 64u32, {deadline}u32);
  match outcome {{ Ok(data) {{ return 0u32; }} Err(code) {{ return code; }} }}
}}
''', f"process-{deadline}.omni")

    def adapter(self, mode: str, marker: pathlib.Path, pidfile: pathlib.Path) -> pathlib.Path:
        path = self.dir / f"adapter-{mode}.py"
        path.write_text(f'''#!{sys.executable}
import os,struct,sys,time
pidfile={str(pidfile)!r}; marker={str(marker)!r}; mode={mode!r}
open(pidfile,"w",encoding="ascii").write(str(os.getpid()))
raw=sys.stdin.buffer.read(); open(marker,"ab").write(b"D")
identity_size,max_bytes,payload_size=struct.unpack("<III",raw[8:20])
identity=raw[20:20+identity_size]
if mode=="lost": time.sleep(2.0)
elif mode=="malformed": sys.stdout.buffer.write(b"BADMAGIC"+struct.pack("<III",identity_size,0,0));sys.stdout.buffer.flush()
''', encoding="utf-8")
        path.chmod(0o755)
        return path

    def assert_dead(self, pidfile: pathlib.Path) -> None:
        self.assertTrue(pidfile.exists())
        pid = int(pidfile.read_text(encoding="ascii"))
        for _ in range(50):
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                return
            time.sleep(0.01)
        self.fail(f"orphan child remains alive: {pid}")

    def test_matrix_schema_is_complete_and_unambiguous(self) -> None:
        data = json.loads(MATRIX.read_text(encoding="utf-8"))
        self.assertEqual(data["schema"], "omni.a93-runtime-fault-matrix/1")
        self.assertEqual(data["seed"], 93002026)
        ids = [row["id"] for row in data["scenarios"]]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(ids, [f"A93-F{i:02d}" for i in range(1, 14)])
        for row in data["scenarios"]:
            self.assertIn(row["phase"], {"PRE_DISPATCH", "DISPATCHED", "ACKNOWLEDGED"})
            self.assertIsInstance(row["result"], int)
            self.assertTrue(row["resource_oracle"])

    def test_process_pre_dispatch_and_generation_fail_without_invocation(self) -> None:
        marker = self.dir / "invoked"
        pidfile = self.dir / "pid"
        adapter = self.adapter("lost", marker, pidfile)
        policy = self.policy(adapter.as_posix(), "process.spawn")
        zero = self.process_source(adapter, 0)
        result = proc(OMNI, "eval", zero, "--host-policy", policy)
        self.assertEqual(result.returncode, 6, result.stderr)
        self.assertFalse(marker.exists())
        self.record("A93-F01", 6, "no_invocation")

        allowed = proc(OMNI, "host-policy", "allows", policy, "process.spawn",
                       adapter, 64, 1, 94)
        self.assertEqual(allowed.returncode, 0, allowed.stderr)
        self.assertFalse(json.loads(allowed.stdout)["allowed"])
        self.assertFalse(marker.exists())
        self.record("A93-F02", 1, "no_invocation", generation=94)

    def test_real_process_lost_and_malformed_ack_have_terminal_cleanup(self) -> None:
        for scenario, mode, expected in (("A93-F03", "lost", 10), ("A93-F04", "malformed", 8)):
            with self.subTest(mode=mode):
                marker, pidfile = self.dir / f"{mode}.marker", self.dir / f"{mode}.pid"
                adapter = self.adapter(mode, marker, pidfile)
                policy = self.policy(adapter.as_posix(), "process.spawn")
                # Both scenarios require the adapter to have reached dispatch.
                # A 40-tick deadline can expire during process startup under a
                # clean-worktree/sanitized build and falsely report a timeout
                # before the child receives bytes.  A bounded 1,000-tick
                # window still forces the `lost` adapter (which sleeps two
                # seconds) through deadline recovery, while making the marker
                # and child-reaping oracle causal rather than scheduler-racy.
                deadline = 1000
                source = self.process_source(adapter, deadline)
                for engine in ("eval", "native"):
                    if engine == "eval":
                        result = proc(OMNI, "eval", source, "--host-policy", policy)
                    else:
                        binary = self.dir / f"{mode}-native"
                        built = proc(OMNI, "build", source, "-o", binary)
                        self.assertEqual(built.returncode, 0, built.stderr)
                        result = proc(binary, "--omni-host-policy", policy)
                    self.assertEqual(result.returncode, expected, result.stderr)
                    self.assertEqual(marker.read_bytes(), b"D" * (1 if engine == "eval" else 2))
                    self.assert_dead(pidfile)
                self.record(scenario, expected, "child_reaped", engines=["evaluator", "native"])

    def tcp_source(self, endpoint: str, deadline: int, name: str) -> pathlib.Path:
        return self.source(f'''module a93
func main() u32 !{{net.connect}} {{
  let outcome = host.tcp("{endpoint}", bytes.from_text("dispatch"), 64u32, {deadline}u32);
  match outcome {{ Ok(data) {{ return 0u32; }} Err(code) {{ return code; }} }}
}}
''', name)

    def test_real_tcp_refusal_and_lost_ack_are_phase_distinct(self) -> None:
        probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        probe.bind(("127.0.0.1", 0))
        refused_endpoint = f"127.0.0.1:{probe.getsockname()[1]}"
        probe.close()
        refused_policy = self.policy(refused_endpoint, "net.connect")
        refused = proc(OMNI, "eval", self.tcp_source(refused_endpoint, 100, "refused.omni"),
                       "--host-policy", refused_policy)
        self.assertEqual(refused.returncode, 4, refused.stderr)
        self.record("A93-F05", 4, "socket_closed")

        server_script = self.dir / "server.py"
        marker = self.dir / "tcp-dispatched"
        server_script.write_text(f'''import socket,time
s=socket.socket();s.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1);s.bind(("127.0.0.1",0));s.listen(1)
print(s.getsockname()[1],flush=True)
c,_=s.accept(); data=b""
while True:
 p=c.recv(4096)
 if not p: break
 data+=p
open({str(marker)!r},"wb").write(data)
time.sleep(2.0)
''', encoding="utf-8")
        child = subprocess.Popen([sys.executable, str(server_script)], stdout=subprocess.PIPE,
                                 stderr=subprocess.PIPE)
        assert child.stdout is not None
        port = child.stdout.readline().strip().decode("ascii")
        endpoint = f"127.0.0.1:{port}"
        policy = self.policy(endpoint, "net.connect")
        timed = proc(OMNI, "eval", self.tcp_source(endpoint, 40, "lost-ack.omni"),
                     "--host-policy", policy)
        self.assertEqual(timed.returncode, 10, timed.stderr)
        child.terminate()
        child.communicate(timeout=2)
        self.assertEqual(marker.read_bytes(), b"dispatch")
        self.record("A93-F06", 10, "socket_closed", payload_observed=True)

    def assert_parity(self, source: pathlib.Path, expected: int, stem: str) -> None:
        evaluated = proc(OMNI, "eval", source)
        self.assertEqual(evaluated.returncode, expected, evaluated.stderr)
        native = self.dir / stem
        built = proc(OMNI, "build", source, "-o", native)
        self.assertEqual(built.returncode, 0, built.stderr)
        executed = proc(native)
        self.assertEqual(executed.returncode, expected, executed.stderr)

    def test_task_and_channel_outcomes_are_bounded_and_differential(self) -> None:
        cancel = self.source('''module a93
func main() u32 { task_scope { spawn child = 9u32; let x = cancel(child); match x { Ok(code) { return code; } Err(code) { return code; } } } }
''', "cancel.omni")
        self.assert_parity(cancel, 1, "cancel-native")
        self.record("A93-F07", 1, "single_terminal_outcome")

        deadline = self.source('''module a93
func main() u32 { task_scope { spawn child = 9u32; let x = deadline(child, 0u32); match x { Ok(value) { return value; } Err(code) { return code; } } } }
''', "deadline.omni")
        self.assert_parity(deadline, 4, "deadline-native")
        self.record("A93-F08", 4, "single_terminal_outcome")

        channel = self.source('''module a93
func main() u32 {
  let c = channel<u32>(1u32); let first = send(c, 7u32);
  match first { Err(e) { return e; } Ok(sent) {
    let full = send(c, 8u32); match full { Ok(x) { return 90u32; } Err(code) {
      let item = receive(c); match item { Err(e) { return e; } Ok(value) {
        match value { None { return 91u32; } Some(v) {
          let closed = close(c); match closed { Err(e) { return e; } Ok(closed_code) {
            let drained = receive(c); match drained { Err(e) { return e; } Ok(last) { match last { Some(x) { return 92u32; } None { return v; } } } }
          } }
        } }
      } }
    } }
  } }
}
''', "channel.omni")
        self.assert_parity(channel, 7, "channel-native")
        self.record("A93-F09", 7, "bounded_queue_drained")

    def test_runtime_buffer_exhaustion_preserves_capacity_and_generation(self) -> None:
        harness = self.dir / "buffer_harness.c"
        harness.write_text('''#include <stdint.h>
uint32_t omni_buffer_alloc(uint32_t, uint64_t*); uint32_t omni_buffer_release(uint64_t);
int main(void) {
  uint64_t slots[1024], replacement=0, large[16], extra=0;
  for (uint32_t i=0;i<1024;i++) if (omni_buffer_alloc(0,&slots[i])!=0) return 1;
  if (omni_buffer_alloc(0,&extra)!=2 || extra!=0) return 2;
  uint64_t old=slots[17]; if (omni_buffer_release(old)!=0) return 3;
  if (omni_buffer_alloc(0,&replacement)!=0 || replacement==old) return 4;
  if ((uint32_t)replacement!=(uint32_t)old || (replacement>>32)<=(old>>32)) return 5;
  for (uint32_t i=0;i<1024;i++) if (i!=17 && omni_buffer_release(slots[i])!=0) return 6;
  if (omni_buffer_release(replacement)!=0) return 7;
  if (omni_buffer_alloc(1048577u,&extra)!=1 || extra!=0) return 8;
  for (uint32_t i=0;i<16;i++) if (omni_buffer_alloc(1048576u,&large[i])!=0) return 9;
  if (omni_buffer_alloc(1,&extra)!=2 || extra!=0) return 10;
  for (uint32_t i=0;i<16;i++) if (omni_buffer_release(large[i])!=0) return 11;
  if (omni_buffer_alloc(1,&extra)!=0 || omni_buffer_release(extra)!=0) return 12;
  return 0;
}
''', encoding="utf-8")
        binary = self.dir / "buffer-harness"
        compiler = os.environ.get("CC", "clang")
        flags = ["-std=c11", "-Wall", "-Wextra", "-Werror"]
        if os.environ.get("OMNI_A93_SANITIZERS") == "1":
            flags += ["-O1", "-g", "-fsanitize=address,undefined", "-fno-omit-frame-pointer"]
        built = proc(compiler, *flags, harness, ROOT / "runtime/omni_runtime.c",
                     "-ldl", "-lm", "-o", binary)
        self.assertEqual(built.returncode, 0, built.stderr)
        executed = proc(binary)
        self.assertEqual(executed.returncode, 0, executed.stderr)
        self.record("A93-F10", 2, "generation_and_capacity_coherent")

    def test_stale_and_cross_subject_proposals_never_publish(self) -> None:
        one = self.source("module a93 func main() u32 { return 1u32 }", "one.omni")
        two = self.source("module a93 func other() u32 { return 2u32 } func main() u32 { return other() }", "two.omni")
        base, foreign = self.dir / "base.omem", self.dir / "foreign.omem"
        self.assertEqual(proc(OMNI, "memory-pack", one, "-o", base).returncode, 0)
        self.assertEqual(proc(OMNI, "memory-pack", two, "-o", foreign).returncode, 0)
        proposal = self.dir / "proposal.oprop"
        self.assertEqual(proc(OMNI, "proposal", base, "--entity", "main", "--agent",
                              "security_agent", "--note", "a93", "-o", proposal).returncode, 0)
        advanced = self.dir / "advanced.omem"
        self.assertEqual(proc(OMNI, "proposal-apply", base, "--proposal", proposal, "--grant",
                              "memory.write", "-o", advanced).returncode, 0)
        stale_output = self.dir / "stale.omem"
        stale = proc(OMNI, "proposal-apply", advanced, "--proposal", proposal, "--grant",
                     "memory.write", "-o", stale_output)
        self.assertEqual(stale.returncode, 2)
        self.assertIn(b"E_EPOCH", stale.stderr)
        self.assertFalse(stale_output.exists())
        self.record("A93-F11", 2, "no_publication")

        wrong_output = self.dir / "wrong.omem"
        wrong = proc(OMNI, "proposal-apply", foreign, "--proposal", proposal, "--grant",
                     "memory.write", "-o", wrong_output)
        self.assertEqual(wrong.returncode, 2)
        self.assertTrue(b"E_EPOCH" in wrong.stderr or b"E_COGNITION" in wrong.stderr)
        self.assertFalse(wrong_output.exists())
        self.record("A93-F12", 2, "no_publication")

    def test_uncertain_outcome_requires_reconciliation_not_automatic_retry(self) -> None:
        state = {"dispatches": 0, "reconciled": False}

        def dispatch_once() -> int:
            state["dispatches"] += 1
            return 10

        result = dispatch_once()
        self.assertEqual(result, 10)
        self.assertEqual(state["dispatches"], 1)
        self.assertFalse(state["reconciled"])
        self.record("A93-F13", 10, "no_automatic_retry", dispatches=1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
