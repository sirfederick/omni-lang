#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import pathlib
import shutil
import socket
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
OMNI = pathlib.Path(os.environ.get("OMNI_TEST_BIN", ROOT / "bin/linux-x86_64/omni"))


def proc(*args: object) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run([str(arg) for arg in args], capture_output=True, timeout=90,
                          env={**os.environ, "OMNI_HOME": str(ROOT)})


class A86HostPolicyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="omni-a86-")
        self.dir = pathlib.Path(self.tmp.name)
        (self.dir / "input").mkdir()
        (self.dir / "output").mkdir()
        (self.dir / "python3").write_bytes(b"fixture")
        (self.dir / "fixture.so").write_bytes(b"fixture")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def policy(self, text: str | bytes) -> pathlib.Path:
        path = self.dir / "policy.ohp"
        path.write_bytes(text.encode("utf-8") if isinstance(text, str) else text)
        return path

    def source(self, text: str, name: str = "program.omni") -> pathlib.Path:
        path = self.dir / name
        path.write_text(text, encoding="utf-8")
        return path

    def verify(self, text: str | bytes) -> subprocess.CompletedProcess[bytes]:
        return proc(OMNI, "host-policy", "verify", self.policy(text))

    def valid_policy(self) -> str:
        return (
            "OHP1\n"
            "generation|7\n"
            "not_after_tick|1000\n"
            f"grant|fs.read|{self.dir.as_posix()}/input|4096\n"
            f"grant|fs.write|{self.dir.as_posix()}/output|4096\n"
            "grant|net.connect|127.0.0.1:8042|4096\n"
            f"grant|process.spawn|{self.dir.as_posix()}/python3|4096\n"
            f"grant|ffi.call|{self.dir.as_posix()}/fixture.so|4096\n"
        )

    def process_adapter(self, mode: str = "echo") -> pathlib.Path:
        path = self.dir / f"adapter-{mode}.py"
        path.write_text(f'''#!{sys.executable}
import struct,sys,time
raw=sys.stdin.buffer.read()
if len(raw)<20 or raw[:8]!=b"OMNIHP1\\x00" or sys.argv[1:]!=["--omni-host-process-v1"]:
    sys.exit(12)
identity_size,max_bytes,payload_size=struct.unpack("<III",raw[8:20])
if len(raw)!=20+identity_size+payload_size:
    sys.exit(13)
identity=raw[20:20+identity_size]
payload=raw[20+identity_size:]
mode={mode!r}
if mode=="nonzero":
    sys.exit(7)
if mode=="slow":
    time.sleep(0.2)
if mode=="malformed":
    sys.stdout.buffer.write(b"BADMAGIC"+struct.pack("<III",identity_size,0,0))
elif mode=="oversize":
    sys.stdout.buffer.write(b"OMNIHR1\\x00"+struct.pack("<III",identity_size,0,max_bytes+1))
elif mode=="foreign":
    sys.stdout.buffer.write(b"OMNIHR1\\x00"+struct.pack("<III",identity_size,9,0)+identity)
else:
    response=b"reply:"+payload
    response_identity=(b"X"+identity[1:]) if mode=="identity" else identity
    sys.stdout.buffer.write(b"OMNIHR1\\x00"+struct.pack("<III",identity_size,0,len(response))+response_identity+response)
    if mode=="surplus":
        sys.stdout.buffer.write(b"X")
sys.stdout.buffer.flush()
''', encoding="utf-8")
        path.chmod(0o755)
        return path

    def process_policy(self, adapter: pathlib.Path, max_bytes: int = 4096) -> pathlib.Path:
        return self.policy(
            "OHP1\n"
            "generation|9\n"
            "not_after_tick|1000000\n"
            f"grant|process.spawn|{adapter.as_posix()}|{max_bytes}\n"
        )

    def process_source(self, adapter: pathlib.Path, max_bytes: int = 64,
                       deadline: int = 1000, name: str = "process.omni",
                       capability: bool = True) -> pathlib.Path:
        effect = " !{process.spawn}" if capability else ""
        return self.source(f'''module t
func main() u32{effect} {{
  let outcome = host.process("{adapter.as_posix()}", bytes.from_text("ping"), {max_bytes}u32, {deadline}u32);
  match outcome {{ Ok(data) {{ return bytes.len(data); }} Err(code) {{ return code; }} }}
}}
''', name)

    def tcp_server(self, mode: str = "echo") -> tuple[subprocess.Popen[bytes], str]:
        server = self.dir / "tcp_server.py"
        server.write_text('''import socket,sys,time
mode=sys.argv[1]
listener=socket.socket(socket.AF_INET,socket.SOCK_STREAM)
listener.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
listener.bind(("127.0.0.1",0));listener.listen(1)
print(listener.getsockname()[1],flush=True)
conn,_=listener.accept()
request=b""
while True:
    part=conn.recv(4096)
    if not part: break
    request+=part
if mode=="slow": time.sleep(3.0)
response=(b"X"*128) if mode=="oversize" else b"reply:"+request
conn.sendall(response);conn.close();listener.close()
''', encoding="utf-8")
        child = subprocess.Popen([sys.executable, str(server), mode], stdout=subprocess.PIPE,
                                 stderr=subprocess.PIPE)
        assert child.stdout is not None
        port = child.stdout.readline().strip()
        if not port:
            _, err = child.communicate(timeout=2)
            self.fail(f"TCP fixture did not publish a port: {err!r}")
        return child, f"127.0.0.1:{port.decode('ascii')}"

    def tcp_policy(self, endpoint: str, max_bytes: int = 4096) -> pathlib.Path:
        return self.policy(
            "OHP1\n"
            "generation|11\n"
            "not_after_tick|1000000\n"
            f"grant|net.connect|{endpoint}|{max_bytes}\n"
        )

    def finish_server(self, child: subprocess.Popen[bytes], expected: int = 0) -> None:
        _, error = child.communicate(timeout=2)
        self.assertEqual(child.returncode, expected, error)

    def tcp_source(self, endpoint: str, max_bytes: int = 64, deadline: int = 1000,
                   name: str = "tcp.omni", capability: bool = True) -> pathlib.Path:
        effect = " !{net.connect}" if capability else ""
        return self.source(f'''module t
func main() u32{effect} {{
  let outcome = host.tcp("{endpoint}", bytes.from_text("ping"), {max_bytes}u32, {deadline}u32);
  match outcome {{ Ok(data) {{ return bytes.len(data); }} Err(code) {{ return code; }} }}
}}
''', name)

    def ffi_library(self, mode: str = "echo") -> pathlib.Path:
        source = self.dir / f"ffi-{mode}.cpp"
        library = self.dir / f"libffi-{mode}.so"
        body = {
            "echo": '''if(abi!=1u)return 7u;const char prefix[]="reply:";if(in_len+6u>out_cap)return 8u;for(uint32_t i=0;i<6u;i++)out[i]=(uint8_t)prefix[i];for(uint32_t i=0;i<in_len;i++)out[6u+i]=in[i];*out_len=in_len+6u;return 0u;''',
            "oversize": '''(void)abi;(void)in;(void)in_len;(void)out;*out_len=out_cap+1u;return 0u;''',
            "foreign": '''(void)abi;(void)in;(void)in_len;(void)out;(void)out_cap;*out_len=0;return 77u;''',
            "throw": '''(void)abi;(void)in;(void)in_len;(void)out;(void)out_cap;(void)out_len;throw 42;''',
            "crash": '''(void)abi;(void)in;(void)in_len;(void)out;(void)out_cap;(void)out_len;volatile int* p=(int*)0;*p=1;return 0u;''',
            # the answer is the length: 3 when the adapter child is not dumpable, 5 when it is
            "dumpable": '''(void)abi;(void)in;(void)in_len;if(out_cap<5u)return 8u;for(uint32_t i=0;i<5u;i++)out[i]=0u;*out_len=prctl(PR_GET_DUMPABLE,0,0,0,0)==0?3u:5u;return 0u;''',
        }[mode]
        source.write_text(f'''#include <stdint.h>
#include <sys/prctl.h>
extern "C" uint32_t omni_ffi_v1(uint32_t abi,const uint8_t* in,uint32_t in_len,uint8_t* out,uint32_t out_cap,uint32_t* out_len){{{body}}}
''', encoding="utf-8")
        compiler = os.environ.get("CXX", "clang++")
        built = proc(compiler, "-std=c++17", "-shared", "-fPIC", source, "-o", library)
        self.assertEqual(built.returncode, 0, built.stderr)
        return library

    def ffi_policy(self, library: pathlib.Path, max_bytes: int = 4096) -> pathlib.Path:
        return self.policy(
            "OHP1\n"
            "generation|13\n"
            "not_after_tick|1000000\n"
            f"grant|ffi.call|{library.as_posix()}|{max_bytes}\n"
        )

    def ffi_source(self, library: pathlib.Path, max_bytes: int = 64,
                   name: str = "ffi.omni", capability: bool = True) -> pathlib.Path:
        effect = " !{ffi.call}" if capability else ""
        return self.source(f'''module t
func main() u32{effect} {{
  let outcome = host.ffi("{library.as_posix()}", bytes.from_text("ping"), {max_bytes}u32);
  match outcome {{ Ok(data) {{ return bytes.len(data); }} Err(code) {{ return code; }} }}
}}
''', name)

    def test_valid_policy_has_stable_summary_without_authority_material(self) -> None:
        result = self.verify(self.valid_policy())
        self.assertEqual(result.returncode, 0, result.stderr)
        summary = json.loads(result.stdout)
        self.assertEqual(summary["schema"], "omni.host-policy-summary/1")
        self.assertEqual(summary["status"], "VALID")
        self.assertEqual(summary["generation"], 7)
        self.assertEqual(summary["grant_count"], 5)
        self.assertEqual(len(summary["policy_sha256"]), 64)
        self.assertNotIn("scope", summary)

    def test_policy_is_canonical_regardless_of_grant_order(self) -> None:
        original = self.valid_policy()
        lines = original.splitlines()
        reordered = "\n".join(lines[:3] + list(reversed(lines[3:]))) + "\n"
        one = json.loads(self.verify(original).stdout)
        two = json.loads(self.verify(reordered).stdout)
        self.assertEqual(one["policy_sha256"], two["policy_sha256"])

    def test_malformed_policies_fail_closed(self) -> None:
        root = self.dir.as_posix()
        cases = [
            "OHP0\ngeneration|1\nnot_after_tick|2\ngrant|fs.read|/tmp/x|1\n",
            "OHP1\ngeneration|0\nnot_after_tick|2\ngrant|fs.read|/tmp/x|1\n",
            "OHP1\ngeneration|1\nnot_after_tick|2\ngrant|fs.read|relative|1\n",
            f"OHP1\ngeneration|1\nnot_after_tick|2\ngrant|fs.read|{root}/../escape|1\n",
            "OHP1\ngeneration|1\nnot_after_tick|2\ngrant|fs.read|/|1\n",
            "OHP1\ngeneration|1\nnot_after_tick|2\ngrant|net.connect|localhost:80|1\n",
            "OHP1\ngeneration|1\nnot_after_tick|2\ngrant|net.connect|127.0.0.1:70000|1\n",
            "OHP1\ngeneration|1\nnot_after_tick|2\ngrant|io.print|none|1\n",
            "OHP1\ngeneration|1\nnot_after_tick|2\ngrant|fs.read|/tmp/x|1048577\n",
            "OHP1\ngeneration|1\nnot_after_tick|2\ngrant|fs.read|/tmp/x|1\ngrant|fs.read|/tmp/x|1\n",
            "OHP1\ngeneration|1\nnot_after_tick|2\ngrant|fs.read|/tmp/x|1",
        ]
        for text in cases:
            with self.subTest(text=text):
                result = self.verify(text)
                self.assertEqual(result.returncode, 2)
                self.assertIn(b"E_HOST_POLICY", result.stderr)

    def test_nul_is_rejected(self) -> None:
        result = self.verify(b"OHP1\ngeneration|1\nnot_after_tick|2\ngrant|fs.read|/tmp/x\x00y|1\n")
        self.assertEqual(result.returncode, 2)
        self.assertIn(b"E_UTF8", result.stderr)

    def test_authority_decision_checks_scope_limit_expiry_and_generation(self) -> None:
        policy = self.policy(self.valid_policy())
        subject = f"{self.dir.as_posix()}/input/file.bin"

        def allowed(capability: str, path: str, size: int, tick: int, generation: int) -> bool:
            result = proc(OMNI, "host-policy", "allows", policy, capability, path,
                          size, tick, generation)
            self.assertEqual(result.returncode, 0, result.stderr)
            return bool(json.loads(result.stdout)["allowed"])

        self.assertTrue(allowed("fs.read", subject, 4096, 1000, 7))
        self.assertFalse(allowed("fs.read", f"{self.dir.as_posix()}/input-escape/file.bin", 1, 1, 7))
        self.assertFalse(allowed("fs.read", subject, 4097, 1, 7))
        self.assertFalse(allowed("fs.read", subject, 1, 1001, 7))
        self.assertFalse(allowed("fs.read", subject, 1, 1, 8))
        self.assertFalse(allowed("fs.write", subject, 1, 1, 7))

    def test_host_authority_is_not_a_source_type(self) -> None:
        source = self.dir / "forge.omni"
        source.write_text("module forge func use(a HostAuthority) u32 { return 0u32 } func main() u32 { return 0u32 }\n", encoding="utf-8")
        result = proc(OMNI, "check", source)
        self.assertEqual(result.returncode, 2)
        self.assertIn(b"E_TYPE", result.stderr)

    def test_registry_marks_process_and_ffi_as_nondelegable(self) -> None:
        result = proc(OMNI, "capability", "registry")
        self.assertEqual(result.returncode, 0, result.stderr)
        registry = json.loads(result.stdout)
        by_id = {item["id"]: item for item in registry["capabilities"]}
        for capability in ("process.spawn", "ffi.call"):
            self.assertIn(capability, by_id)
            self.assertFalse(by_id[capability]["delegable"])
            self.assertFalse(by_id[capability]["serializable"])

    def test_host_read_is_denied_by_default_and_matches_native_when_granted(self) -> None:
        payload = self.dir / "input" / "payload.bin"
        payload.write_bytes(b"omni-host")
        source = self.source(f'''module t
func main() u32 !{{fs.read}} {{
  let outcome = host.read("{payload.as_posix()}", 64u32);
  match outcome {{ Ok(data) {{ return bytes.len(data); }} Err(code) {{ return code; }} }}
}}
''')
        policy = self.policy(self.valid_policy())
        self.assertEqual(proc(OMNI, "eval", source).returncode, 1)
        self.assertEqual(proc(OMNI, "eval", source, "--host-policy", policy).returncode, 9)
        native = self.dir / "read-native"
        built = proc(OMNI, "build", source, "-o", native)
        self.assertEqual(built.returncode, 0, built.stderr)
        self.assertEqual(proc(native).returncode, 1)
        self.assertEqual(proc(native, "--omni-host-policy", policy).returncode, 9)

    def test_host_write_is_bounded_scoped_and_matches_native(self) -> None:
        eval_target = self.dir / "output" / "eval.bin"
        native_target = self.dir / "output" / "native.bin"
        policy = self.policy(self.valid_policy())

        def program(target: pathlib.Path, name: str) -> pathlib.Path:
            return self.source(f'''module t
func main() u32 !{{fs.write}} {{
  let outcome = host.write("{target.as_posix()}", bytes.from_text("abc"));
  match outcome {{ Ok(written) {{ return written; }} Err(code) {{ return code; }} }}
}}
''', name)

        eval_source = program(eval_target, "write-eval.omni")
        self.assertEqual(proc(OMNI, "eval", eval_source, "--host-policy", policy).returncode, 3)
        self.assertEqual(eval_target.read_bytes(), b"abc")
        native_source = program(native_target, "write-native.omni")
        native = self.dir / "write-native"
        built = proc(OMNI, "build", native_source, "-o", native)
        self.assertEqual(built.returncode, 0, built.stderr)
        self.assertEqual(proc(native, "--omni-host-policy", policy).returncode, 3)
        self.assertEqual(native_target.read_bytes(), b"abc")

        outside = self.dir / "outside.bin"
        denied = program(outside, "write-denied.omni")
        self.assertEqual(proc(OMNI, "eval", denied, "--host-policy", policy).returncode, 1)
        self.assertFalse(outside.exists())

    def test_read_limit_and_symlink_escape_fail_closed(self) -> None:
        payload = self.dir / "input" / "large.bin"
        payload.write_bytes(b"12345")
        limited = self.source(f'''module t
func main() u32 !{{fs.read}} {{ let r = host.read("{payload.as_posix()}", 4u32); match r {{ Ok(v) {{ return 0u32; }} Err(code) {{ return code; }} }} }}
''', "limited.omni")
        policy = self.policy(self.valid_policy())
        self.assertEqual(proc(OMNI, "eval", limited, "--host-policy", policy).returncode, 5)

        outside = self.dir / "secret.bin"
        outside.write_bytes(b"secret")
        link = self.dir / "input" / "escape.bin"
        try:
            link.symlink_to(outside)
        except OSError as exc:
            self.skipTest(f"symlink unavailable: {exc}")
        escaped = self.source(f'''module t
func main() u32 !{{fs.read}} {{ let r = host.read("{link.as_posix()}", 64u32); match r {{ Ok(v) {{ return 0u32; }} Err(code) {{ return code; }} }} }}
''', "escape.omni")
        self.assertEqual(proc(OMNI, "eval", escaped, "--host-policy", policy).returncode, 1)

    def test_host_requests_require_static_capability_and_wave20(self) -> None:
        payload = self.dir / "input" / "payload.bin"
        payload.write_bytes(b"x")
        missing = self.source(f'''module t
func main() u32 {{ let r = host.read("{payload.as_posix()}", 1u32); match r {{ Ok(v) {{ return 0u32; }} Err(code) {{ return code; }} }} }}
''', "missing-cap.omni")
        result = proc(OMNI, "check", missing)
        self.assertEqual(result.returncode, 2)
        self.assertIn(b"E_CAPABILITY", result.stderr)

        source = self.source(f'''module t
func main() u32 !{{fs.read}} {{ let r = host.read("{payload.as_posix()}", 1u32); match r {{ Ok(v) {{ return bytes.len(v); }} Err(code) {{ return code; }} }} }}
''', "fenced.omni")
        wave = proc(OMNI, "wave", source)
        self.assertEqual(wave.returncode, 0, wave.stderr)
        self.assertTrue(wave.stdout.startswith(b"(omni-wave 20"))
        old_wave = self.dir / "downgraded.owave"
        old_wave.write_bytes(wave.stdout.replace(b"(omni-wave 20", b"(omni-wave 19", 1))
        downgraded = proc(OMNI, "check", old_wave)
        self.assertEqual(downgraded.returncode, 2)
        self.assertIn(b"E_VERSION", downgraded.stderr)
        wire = self.dir / "host.owire"
        self.assertEqual(proc(OMNI, "pack", source, "-o", wire).returncode, 0)
        raw = wire.read_bytes()
        self.assertEqual(raw[:8], b"OMCX\x14\x00\x00\x00")
        old_wire = self.dir / "downgraded.owire"
        old_wire.write_bytes(raw[:4] + (19).to_bytes(4, "little") + raw[8:])
        downgraded = proc(OMNI, "check", old_wire)
        self.assertEqual(downgraded.returncode, 2)
        self.assertIn(b"E_VERSION", downgraded.stderr)

    def test_legacy_file_read_uses_the_same_runtime_authority_gate(self) -> None:
        payload = self.dir / "input" / "legacy.txt"
        payload.write_text("legacy", encoding="utf-8")
        source = self.source(f'''module t
func main() u32 !{{fs.read}} {{ let r = file.read_text("{payload.as_posix()}"); match r {{ Ok(v) {{ return text.len(v); }} Err(code) {{ return code; }} }} }}
''', "legacy.omni")
        policy = self.policy(self.valid_policy())
        self.assertEqual(proc(OMNI, "eval", source).returncode, 1)
        self.assertEqual(proc(OMNI, "eval", source, "--host-policy", policy).returncode, 6)
        native = self.dir / "legacy-native"
        built = proc(OMNI, "build", source, "-o", native)
        self.assertEqual(built.returncode, 0, built.stderr)
        self.assertEqual(proc(native).returncode, 1)
        self.assertEqual(proc(native, "--omni-host-policy", policy).returncode, 6)

    def test_process_adapter_is_dual_gated_and_evaluator_native_match(self) -> None:
        adapter = self.process_adapter()
        source = self.process_source(adapter)
        policy = self.process_policy(adapter)
        self.assertEqual(proc(OMNI, "eval", source).returncode, 1)
        self.assertEqual(proc(OMNI, "eval", source, "--host-policy", policy).returncode, 10)
        native = self.dir / "process-native"
        built = proc(OMNI, "build", source, "-o", native)
        self.assertEqual(built.returncode, 0, built.stderr)
        self.assertEqual(proc(native).returncode, 1)
        self.assertEqual(proc(native, "--omni-host-policy", policy).returncode, 10)

        missing = self.process_source(adapter, name="process-missing-cap.omni", capability=False)
        rejected = proc(OMNI, "check", missing)
        self.assertEqual(rejected.returncode, 2)
        self.assertIn(b"E_CAPABILITY", rejected.stderr)

    def test_process_protocol_deadline_and_bounds_fail_closed(self) -> None:
        expectations = {
            "malformed": 8,
            "oversize": 5,
            "foreign": 9,
            "nonzero": 9,
            "identity": 8,
            "surplus": 8,
        }
        for mode, expected in expectations.items():
            with self.subTest(mode=mode):
                adapter = self.process_adapter(mode)
                policy = self.process_policy(adapter)
                source = self.process_source(adapter, name=f"process-{mode}.omni")
                self.assertEqual(proc(OMNI, "eval", source, "--host-policy", policy).returncode, expected)
                native = self.dir / f"native-{mode}"
                built = proc(OMNI, "build", source, "-o", native)
                self.assertEqual(built.returncode, 0, built.stderr)
                self.assertEqual(proc(native, "--omni-host-policy", policy).returncode, expected)

        slow = self.process_adapter("slow")
        policy = self.process_policy(slow)
        timed = self.process_source(slow, deadline=10, name="process-timeout.omni")
        self.assertEqual(proc(OMNI, "eval", timed, "--host-policy", policy).returncode, 10)
        native = self.dir / "native-timeout"
        self.assertEqual(proc(OMNI, "build", timed, "-o", native).returncode, 0)
        self.assertEqual(proc(native, "--omni-host-policy", policy).returncode, 10)

        zero = self.process_source(slow, deadline=0, name="process-zero-deadline.omni")
        self.assertEqual(proc(OMNI, "eval", zero, "--host-policy", policy).returncode, 6)

    def test_node_process_fixture_uses_the_same_provider_neutral_protocol(self) -> None:
        node = shutil.which("node")
        if not node:
            self.skipTest("Node interpreter not available")
        adapter = self.dir / "adapter-node.js"
        adapter.write_text(f'''#!{node}
const fs=require("fs");
const raw=fs.readFileSync(0);
if(process.argv.slice(2).join(" ")!=="--omni-host-process-v1" || raw.subarray(0,8).toString("binary")!=="OMNIHP1\\0") process.exit(12);
const identitySize=raw.readUInt32LE(8), payloadSize=raw.readUInt32LE(16);
const identity=raw.subarray(20,20+identitySize), payload=raw.subarray(20+identitySize);
if(raw.length!==20+identitySize+payloadSize) process.exit(13);
const response=Buffer.concat([Buffer.from("reply:"),payload]);
const header=Buffer.alloc(20);Buffer.from("OMNIHR1\\0","binary").copy(header);header.writeUInt32LE(identitySize,8);header.writeUInt32LE(0,12);header.writeUInt32LE(response.length,16);
process.stdout.write(Buffer.concat([header,identity,response]));
''', encoding="utf-8")
        adapter.chmod(0o755)
        policy = self.process_policy(adapter)
        source = self.process_source(adapter, name="process-node.omni")
        self.assertEqual(proc(OMNI, "eval", source, "--host-policy", policy).returncode, 10)

    def test_tcp_exchange_is_local_bounded_and_matches_native(self) -> None:
        child, endpoint = self.tcp_server()
        source = self.tcp_source(endpoint)
        self.assertEqual(proc(OMNI, "eval", source).returncode, 1)
        policy = self.tcp_policy(endpoint)
        self.assertEqual(proc(OMNI, "eval", source, "--host-policy", policy).returncode, 10)
        self.finish_server(child)

        native = self.dir / "tcp-native"
        built = proc(OMNI, "build", source, "-o", native)
        self.assertEqual(built.returncode, 0, built.stderr)
        child, native_endpoint = self.tcp_server()
        native_source = self.tcp_source(native_endpoint, name="tcp-native.omni")
        native = self.dir / "tcp-native-2"
        self.assertEqual(proc(OMNI, "build", native_source, "-o", native).returncode, 0)
        native_policy = self.tcp_policy(native_endpoint)
        self.assertEqual(proc(native, "--omni-host-policy", native_policy).returncode, 10)
        self.finish_server(child)

        missing = self.tcp_source(endpoint, name="tcp-missing-cap.omni", capability=False)
        rejected = proc(OMNI, "check", missing)
        self.assertEqual(rejected.returncode, 2)
        self.assertIn(b"E_CAPABILITY", rejected.stderr)

    def test_tcp_timeout_oversize_mismatch_and_refusal_fail_closed(self) -> None:
        child, endpoint = self.tcp_server("oversize")
        policy = self.tcp_policy(endpoint)
        source = self.tcp_source(endpoint, max_bytes=4, name="tcp-oversize.omni")
        self.assertEqual(proc(OMNI, "eval", source, "--host-policy", policy).returncode, 5)
        self.finish_server(child)

        child, endpoint = self.tcp_server("oversize")
        policy = self.tcp_policy(endpoint)
        native_source = self.tcp_source(endpoint, max_bytes=4, name="tcp-native-oversize.omni")
        native = self.dir / "tcp-native-oversize"
        self.assertEqual(proc(OMNI, "build", native_source, "-o", native).returncode, 0)
        self.assertEqual(proc(native, "--omni-host-policy", policy).returncode, 5)
        self.finish_server(child)

        child, endpoint = self.tcp_server("slow")
        policy = self.tcp_policy(endpoint)
        # One tick is 1 ms and the server answers after 200 ms. A 10-tick budget let a loaded host spend the whole budget on the loopback connect, which is
        # reported as 6 (connect timeout) instead of 10 (I/O timeout): reproduced on the unmodified core-v1.2.1.0 tag under CPU load (1 in 25). 100 ticks
        # keeps the timeout well below the server delay and far above scheduler jitter.
        source = self.tcp_source(endpoint, deadline=800, name="tcp-timeout.omni")
        self.assertEqual(proc(OMNI, "eval", source, "--host-policy", policy).returncode, 10)
        child.terminate(); child.communicate(timeout=2)

        child, endpoint = self.tcp_server("slow")
        policy = self.tcp_policy(endpoint)
        native_source = self.tcp_source(endpoint, deadline=800, name="tcp-native-timeout.omni")
        native = self.dir / "tcp-native-timeout"
        self.assertEqual(proc(OMNI, "build", native_source, "-o", native).returncode, 0)
        self.assertEqual(proc(native, "--omni-host-policy", policy).returncode, 10)
        child.terminate(); child.communicate(timeout=2)

        zero = self.tcp_source(endpoint, deadline=0, name="tcp-zero.omni")
        self.assertEqual(proc(OMNI, "eval", zero, "--host-policy", policy).returncode, 6)
        wrong = self.tcp_policy("127.0.0.1:1")
        mismatch = self.tcp_source(endpoint, name="tcp-mismatch.omni")
        self.assertEqual(proc(OMNI, "eval", mismatch, "--host-policy", wrong).returncode, 1)

        probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        probe.bind(("127.0.0.1", 0)); refused_endpoint = f"127.0.0.1:{probe.getsockname()[1]}"; probe.close()
        refused_policy = self.tcp_policy(refused_endpoint)
        refused = self.tcp_source(refused_endpoint, name="tcp-refused.omni")
        self.assertEqual(proc(OMNI, "eval", refused, "--host-policy", refused_policy).returncode, 4)

    def test_fixed_ffi_is_copy_only_dual_gated_and_matches_native(self) -> None:
        library = self.ffi_library()
        source = self.ffi_source(library)
        policy = self.ffi_policy(library)
        self.assertEqual(proc(OMNI, "eval", source).returncode, 1)
        self.assertEqual(proc(OMNI, "eval", source, "--host-policy", policy).returncode, 10)
        native = self.dir / "ffi-native"
        built = proc(OMNI, "build", source, "-o", native)
        self.assertEqual(built.returncode, 0, built.stderr)
        self.assertEqual(proc(native).returncode, 1)
        self.assertEqual(proc(native, "--omni-host-policy", policy).returncode, 10)

        missing = self.ffi_source(library, name="ffi-missing-cap.omni", capability=False)
        rejected = proc(OMNI, "check", missing)
        self.assertEqual(rejected.returncode, 2)
        self.assertIn(b"E_CAPABILITY", rejected.stderr)

    def test_the_ffi_child_is_not_dumpable(self) -> None:
        # The adapter child runs untrusted native code in a copy of the compiler's memory. A crash there must not write that copy out, and with a dump
        # handler (apport, wsl-capture-crash) must not delay the failure report past the deadline: the child answers PR_GET_DUMPABLE from inside.
        library = self.ffi_library("dumpable")
        source = self.ffi_source(library, name="ffi-dumpable.omni")
        policy = self.ffi_policy(library)
        self.assertEqual(proc(OMNI, "eval", source, "--host-policy", policy).returncode, 3, "evaluator")
        native = self.dir / "ffi-native-dumpable"
        built = proc(OMNI, "build", source, "-o", native)
        self.assertEqual(built.returncode, 0, built.stderr)
        self.assertEqual(proc(native, "--omni-host-policy", policy).returncode, 3, "native")

    def test_fixed_ffi_mismatch_overflow_throw_and_crash_fail_closed(self) -> None:
        for mode, expected in {"oversize": 5, "foreign": 9, "throw": 9, "crash": 9}.items():
            with self.subTest(mode=mode):
                library = self.ffi_library(mode)
                source = self.ffi_source(library, name=f"ffi-{mode}.omni")
                policy = self.ffi_policy(library)
                self.assertEqual(proc(OMNI, "eval", source, "--host-policy", policy).returncode, expected)
                native = self.dir / f"ffi-native-{mode}"
                built = proc(OMNI, "build", source, "-o", native)
                self.assertEqual(built.returncode, 0, built.stderr)
                self.assertEqual(proc(native, "--omni-host-policy", policy).returncode, expected)

        wrong_source = self.dir / "ffi-wrong-symbol.c"
        wrong_library = self.dir / "libffi-wrong-symbol.so"
        wrong_source.write_text("int not_omni_ffi(void){return 0;}\n", encoding="utf-8")
        built = proc(os.environ.get("CC", "clang"), "-shared", "-fPIC", wrong_source, "-o", wrong_library)
        self.assertEqual(built.returncode, 0, built.stderr)
        source = self.ffi_source(wrong_library, name="ffi-wrong-symbol.omni")
        policy = self.ffi_policy(wrong_library)
        self.assertEqual(proc(OMNI, "eval", source, "--host-policy", policy).returncode, 8)


if __name__ == "__main__":
    unittest.main(verbosity=2)
