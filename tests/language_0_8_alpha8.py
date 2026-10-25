#!/usr/bin/env python3
from __future__ import annotations
import json, os, pathlib, subprocess, tempfile, unittest

ROOT=pathlib.Path(__file__).resolve().parents[1]
OMNI=pathlib.Path(os.environ.get("OMNI_TEST_BIN", ROOT/"bin/linux-x86_64/omni"))

def proc(*args,timeout=45):
    return subprocess.run([str(x) for x in args],capture_output=True,timeout=timeout,
                          env={**os.environ,"OMNI_HOME":str(ROOT)})

class Alpha8MemoryAuthorityTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix="omni-a8-")
        self.d=pathlib.Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def source(self,text,name="main.omni"):
        p=self.d/name
        p.write_text(text,encoding="utf-8")
        return p

    def check_ok(self,text):
        r=proc(OMNI,"check",self.source(text))
        self.assertEqual(r.returncode,0,r.stderr)
        return r

    def check_err(self,text,code):
        r=proc(OMNI,"check",self.source(text))
        self.assertEqual(r.returncode,2,r.stderr)
        self.assertIn(code.encode(),r.stderr)
        return r

    def test_version_and_representation_fence(self):
        self.assertEqual(proc(OMNI,"--version").stdout.strip(),b"omni "+(ROOT/"VERSION").read_bytes().strip())
        p=self.source("module t func main() u32 { return 0 }")
        w=proc(OMNI,"wave",p)
        self.assertEqual(w.returncode,0,w.stderr)
        self.assertTrue(w.stdout.startswith(b"(omni-wave 18"))
        wire=self.d/"x.owire"
        q=proc(OMNI,"pack",p,"-o",wire)
        self.assertEqual(q.returncode,0,q.stderr)
        raw=wire.read_bytes()
        self.assertEqual(raw[:4],b"OMCX")
        self.assertEqual(int.from_bytes(raw[4:8],"little"),18)

    def test_a8_ownership_engine_replaces_buffer_specific_state_authority(self):
        src=(ROOT/"compiler/src/check.cpp").read_text(encoding="utf-8")
        self.assertNotIn("resourceState",src)
        for token in ("OwnershipClass","OwnershipState","OwnershipEntry","OwnershipLedger",
                      "tracksOwnership","requiresDropObligation","mergeOwnership"):
            self.assertIn(token,src)
        self.assertIn("Uninitialized, Live, Moved, Dropped",src)

    def test_resource_valid_move_discharge_remains_admitted(self):
        self.check_ok("""module t
func main() u32 !{memory.write} {
  let allocation = buffer.alloc(8)
  match allocation {
    Ok(buf) {
      let released = buffer.release(move(buf))
    }
    Err(e) { return e }
  }
  return 0
}""")

    def test_resource_double_move_rejected_by_generic_ledger(self):
        self.check_err("""module t
func main() u32 !{memory.write} {
  let allocation = buffer.alloc(8)
  match allocation {
    Ok(buf) {
      let first = buffer.release(move(buf))
      let second = buffer.release(move(buf))
    }
    Err(e) { return e }
  }
  return 0
}""","E_RESOURCE_MOVED")

    def test_live_resource_scope_exit_is_cleaned_in_wave18(self):
        self.check_ok("""module t
func main() u32 !{memory.write} {
  let allocation = buffer.alloc(8)
  match allocation {
    Ok(buf) {
      return 0
    }
    Err(e) { return e }
  }
}""")

    def test_branch_join_requires_same_ownership_state(self):
        self.check_err("""module t
func main() u32 !{memory.write} {
  let allocation = buffer.alloc(8)
  match allocation {
    Ok(buf) {
      if true {
        let released = buffer.release(move(buf))
      } else {
      }
      return 0
    }
    Err(e) { return e }
  }
}""","E_RESOURCE_FLOW")

    def test_copy_values_are_not_accidentally_linearized(self):
        self.check_ok("""module t
func main() u32 {
  let a u32 = 7
  let b u32 = a
  let c u32 = a
  return b+c
}""")


    def test_persistent_shared_loans_can_coexist(self):
        self.check_ok("""module t
func main() u32 !{memory.read,memory.write} {
  let allocation = buffer.alloc(8)
  match allocation {
    Ok(buf) {
      let a = borrow(buf)
      let b = borrow(buf)
      let n1 = buffer.len(a)
      let n2 = buffer.len(b)
      let released = buffer.release(move(buf))
      return n1+n2
    }
    Err(e) { return e }
  }
}""")

    def test_persistent_exclusive_loan_allows_mutation(self):
        self.check_ok("""module t
func main() u32 !{memory.read,memory.write} {
  let allocation = buffer.alloc(8)
  match allocation {
    Ok(buf) {
      let m = borrow_mut(buf)
      let write = buffer.write_u8(m,0,7)
      match write {
        Ok(x) { }
        Err(e) { }
      }
      let n = buffer.len(m)
      let released = buffer.release(move(buf))
      return n
    }
    Err(e) { return e }
  }
}""")

    def test_shared_then_exclusive_overlap_is_rejected(self):
        self.check_err("""module t
func main() u32 !{memory.read,memory.write} {
  let allocation = buffer.alloc(8)
  match allocation {
    Ok(buf) {
      let shared = borrow(buf)
      let exclusive = borrow_mut(buf)
      let n = buffer.len(shared)
      let released = buffer.release(move(buf))
      return n
    }
    Err(e) { return e }
  }
}""","E_BORROW_CONFLICT")

    def test_two_exclusive_loans_are_rejected(self):
        self.check_err("""module t
func main() u32 !{memory.read,memory.write} {
  let allocation = buffer.alloc(8)
  match allocation {
    Ok(buf) {
      let first = borrow_mut(buf)
      let second = borrow_mut(buf)
      let n = buffer.len(first)
      let released = buffer.release(move(buf))
      return n
    }
    Err(e) { return e }
  }
}""","E_BORROW_CONFLICT")

    def test_move_while_persistent_loan_is_live_is_rejected(self):
        self.check_err("""module t
func main() u32 !{memory.read,memory.write} {
  let allocation = buffer.alloc(8)
  match allocation {
    Ok(buf) {
      let shared = borrow(buf)
      let released = buffer.release(move(buf))
      let n = buffer.len(shared)
      return n
    }
    Err(e) { return e }
  }
}""","E_BORROW_CONFLICT")

    def test_statement_last_use_releases_loan_before_lexical_scope_end(self):
        self.check_ok("""module t
func main() u32 !{memory.read,memory.write} {
  let allocation = buffer.alloc(8)
  match allocation {
    Ok(buf) {
      let shared = borrow(buf)
      let n = buffer.len(shared)
      let released = buffer.release(move(buf))
      return n
    }
    Err(e) { return e }
  }
}""")

    def test_nested_statement_use_keeps_outer_loan_until_statement_finishes(self):
        self.check_ok("""module t
func main() u32 !{memory.read,memory.write} {
  let allocation = buffer.alloc(8)
  match allocation {
    Ok(buf) {
      let shared = borrow(buf)
      if true {
        let n = buffer.len(shared)
      } else {
      }
      let released = buffer.release(move(buf))
      return 0
    }
    Err(e) { return e }
  }
}""")

    def test_local_borrow_must_be_immutable_direct_loan(self):
        self.check_err("""module t
func main() u32 !{memory.write} {
  let allocation = buffer.alloc(8)
  match allocation {
    Ok(buf) {
      var shared = borrow(buf)
      let released = buffer.release(move(buf))
      return 0
    }
    Err(e) { return e }
  }
}""","E_BORROW_ESCAPE")
        self.check_err("""module t
func main() u32 !{memory.read,memory.write} {
  let allocation = buffer.alloc(8)
  match allocation {
    Ok(buf) {
      let shared = borrow(buf)
      let alias = shared
      let n = buffer.len(shared)
      let released = buffer.release(move(buf))
      return n
    }
    Err(e) { return e }
  }
}""","E_BORROW_ESCAPE")

    def test_local_loan_origin_blocks_move_inside_user_call(self):
        self.check_err("""module t
func consume(view Borrow<Buffer>, owned Resource<Buffer>) u32 !{memory.read,memory.write} {
  let n = buffer.len(view)
  let released = buffer.release(move(owned))
  return n
}
func main() u32 !{memory.read,memory.write} {
  let allocation = buffer.alloc(8)
  match allocation {
    Ok(buf) {
      let shared = borrow(buf)
      return consume(shared,move(buf))
    }
    Err(e) { return e }
  }
}""","E_BORROW_CONFLICT")

    def test_borrow_diagnostics_are_stable_memory_resource_codes(self):
        d=json.loads(proc(OMNI,"diagnostics").stdout)
        by_code={x["code"]:x["category"] for x in d["codes"]}
        self.assertEqual(by_code["E_BORROW_CONFLICT"],"memory-resource")
        self.assertEqual(by_code["E_BORROW_ESCAPE"],"memory-resource")
        self.assertEqual(by_code["E_BORROW_EXPIRED"],"memory-resource")


    def test_persistent_shared_loan_is_fenced_from_wave11_and_omc11(self):
        p=self.source("""module t
func main() u32 !{memory.read,memory.write} {
  let allocation = buffer.alloc(8)
  match allocation {
    Ok(buf) {
      let shared = borrow(buf)
      let n = buffer.len(shared)
      let released = buffer.release(move(buf))
      return n
    }
    Err(e) { return e }
  }
}""","persistent-fence.omni")
        w=proc(OMNI,"wave",p);self.assertEqual(w.returncode,0,w.stderr)
        oldw=self.d/"persistent-wave11.owave"
        oldw.write_bytes(w.stdout.replace(b"(omni-wave 18",b"(omni-wave 11",1))
        rw=proc(OMNI,"check",oldw);self.assertEqual(rw.returncode,2,rw.stderr);self.assertIn(b"E_VERSION",rw.stderr)
        wire=self.d/"persistent.omc12";q=proc(OMNI,"pack",p,"-o",wire);self.assertEqual(q.returncode,0,q.stderr)
        raw=bytearray(wire.read_bytes());self.assertEqual(int.from_bytes(raw[4:8],"little"),18);raw[4:8]=(11).to_bytes(4,"little")
        oldbin=self.d/"persistent-omc11.owire";oldbin.write_bytes(raw)
        rb=proc(OMNI,"check",oldbin);self.assertEqual(rb.returncode,2,rb.stderr);self.assertIn(b"E_VERSION",rb.stderr)

    def test_historical_temporary_shared_borrow_remains_wave11_omc11_compatible(self):
        p=self.source("""module t
func main() u32 !{memory.read,memory.write} {
  let allocation = buffer.alloc(8)
  match allocation {
    Ok(buf) {
      let n = buffer.len(borrow(buf))
      let released = buffer.release(move(buf))
      return n
    }
    Err(e) { return e }
  }
}""","temporary-compat.omni")
        w=proc(OMNI,"wave",p);self.assertEqual(w.returncode,0,w.stderr)
        oldw=self.d/"temporary-wave11.owave";oldw.write_bytes(w.stdout.replace(b"(omni-wave 18",b"(omni-wave 11",1))
        rw=proc(OMNI,"check",oldw);self.assertEqual(rw.returncode,0,rw.stderr)
        wire=self.d/"temporary.omc12";q=proc(OMNI,"pack",p,"-o",wire);self.assertEqual(q.returncode,0,q.stderr)
        raw=bytearray(wire.read_bytes());raw[4:8]=(11).to_bytes(4,"little")
        oldbin=self.d/"temporary-omc11.owire";oldbin.write_bytes(raw)
        rb=proc(OMNI,"check",oldbin);self.assertEqual(rb.returncode,0,rb.stderr)


    def test_borrow_and_borrowmut_have_distinct_type_identity(self):
        shared=json.loads(proc(OMNI,"type","describe","Borrow<Buffer>").stdout)
        exclusive=json.loads(proc(OMNI,"type","describe","BorrowMut<Buffer>").stdout)
        self.assertNotEqual(shared["type_id"],exclusive["type_id"])
        self.assertEqual(shared["name"],"Borrow<Buffer>")
        self.assertEqual(exclusive["name"],"BorrowMut<Buffer>")

    def test_shared_borrow_cannot_call_mutating_buffer_api(self):
        self.check_err("""module t
func main() u32 !{memory.write} {
  let allocation = buffer.alloc(8)
  match allocation {
    Ok(buf) {
      let shared = borrow(buf)
      let write = buffer.write_u8(shared,0,7)
      let released = buffer.release(move(buf))
      return 0
    }
    Err(e) { return e }
  }
}""","E_TYPE")

    def test_direct_call_scoped_shared_exclusive_alias_conflict(self):
        self.check_err("""module t
func inspect_pair(a Borrow<Buffer>, b BorrowMut<Buffer>) u32 !{memory.read} {
  return buffer.len(a)+buffer.len(b)
}
func main() u32 !{memory.read,memory.write} {
  let allocation = buffer.alloc(8)
  match allocation {
    Ok(buf) {
      let n = inspect_pair(borrow(buf),borrow_mut(buf))
      let released = buffer.release(move(buf))
      return n
    }
    Err(e) { return e }
  }
}""","E_BORROW_CONFLICT")

    def test_exclusive_local_loan_executes_in_evaluator(self):
        p=self.source("""module t
func write_one(m BorrowMut<Buffer>) u32 !{memory.write} {
  let result = buffer.write_u8(m,0,9)
  match result {
    Ok(x) { return x }
    Err(e) { return e }
  }
}
func main() u32 !{memory.read,memory.write} {
  let allocation = buffer.alloc(8)
  match allocation {
    Ok(buf) {
      let m = borrow_mut(buf)
      let wrote = write_one(m)
      let n = buffer.len(m)
      let released = buffer.release(move(buf))
      return n
    }
    Err(e) { return e }
  }
}""","exclusive-eval.omni")
        r=proc(OMNI,"eval",p)
        self.assertEqual(r.returncode,8,r.stderr)


    def test_outer_loan_stays_live_through_nested_branch_statement(self):
        self.check_err("""module t
func main() u32 !{memory.read,memory.write} {
  let allocation = buffer.alloc(8)
  match allocation {
    Ok(buf) {
      let shared = borrow(buf)
      if true {
        let released = buffer.release(move(buf))
      } else {
        let n = buffer.len(shared)
      }
      return 0
    }
    Err(e) { return e }
  }
}""","E_BORROW_CONFLICT")

    def test_inner_scope_loan_is_retired_at_scope_exit(self):
        self.check_ok("""module t
func main() u32 !{memory.read,memory.write} {
  let allocation = buffer.alloc(8)
  match allocation {
    Ok(buf) {
      if true {
        let shared = borrow(buf)
        let n = buffer.len(shared)
      } else {
      }
      let released = buffer.release(move(buf))
      return 0
    }
    Err(e) { return e }
  }
}""")

    def test_outer_loan_used_inside_loop_can_end_after_loop_statement(self):
        self.check_ok("""module t
func main() u32 !{memory.read,memory.write} {
  let allocation = buffer.alloc(8)
  match allocation {
    Ok(buf) {
      let shared = borrow(buf)
      for false {
        let n = buffer.len(shared)
      }
      let released = buffer.release(move(buf))
      return 0
    }
    Err(e) { return e }
  }
}""")


    def test_borrowmut_cannot_enter_plain_generic_or_product_storage(self):
        self.check_err("""module t
func inspect<T:Plain>(x T) u32 { return 0 }
func main() u32 !{memory.write} {
  let allocation = buffer.alloc(8)
  match allocation {
    Ok(buf) {
      let exclusive = borrow_mut(buf)
      return inspect<BorrowMut<Buffer>>(exclusive)
    }
    Err(e) { return e }
  }
}""","E_GENERIC_CONSTRAINT")
        self.check_err("""module t
func main() u32 !{memory.write} {
  let allocation = buffer.alloc(8)
  match allocation {
    Ok(buf) {
      let exclusive = borrow_mut(buf)
      let pair = tuple(exclusive,1u32)
      return 0
    }
    Err(e) { return e }
  }
}""","E_PRODUCT_LINEAR")


    def test_resource_parameter_is_cleaned_before_return_in_wave18(self):
        self.check_ok("""module t
func leak(x Resource<Buffer>) u32 {
  return 0
}
func main() u32 { return 0 }
""")

    def test_resource_parameter_can_be_consumed_before_return(self):
        self.check_ok("""module t
func consume(x Resource<Buffer>) u32 !{memory.write} {
  let released = buffer.release(move(x))
  return released
}
func main() u32 !{memory.write} {
  let allocation = buffer.alloc(8)
  match allocation {
    Ok(buf) { return consume(move(buf)) }
    Err(e) { return e }
  }
}""")

    def test_both_returning_branches_may_discharge_same_owner(self):
        self.check_ok("""module t
func choose(x Resource<Buffer>, flag bool) u32 !{memory.write} {
  if flag {
    let released = buffer.release(move(x))
    return 1
  } else {
    let released = buffer.release(move(x))
    return 2
  }
}
func main() u32 !{memory.write} {
  let allocation = buffer.alloc(8)
  match allocation {
    Ok(buf) { return choose(move(buf),true) }
    Err(e) { return e }
  }
}""")

    def test_return_edge_cleans_live_resource_in_only_one_branch(self):
        self.check_ok("""module t
func choose(x Resource<Buffer>, flag bool) u32 !{memory.write} {
  if flag {
    let released = buffer.release(move(x))
    return 1
  } else {
    return 2
  }
}
func main() u32 { return 0 }
""")


    def test_borrowmut_onme2_round_trip_preserves_wave12_semantics(self):
        p=self.source("""module t
func main() u32 !{memory.read,memory.write} {
  let allocation = buffer.alloc(8)
  match allocation {
    Ok(buf) {
      let exclusive = borrow_mut(buf)
      let write = buffer.write_u8(exclusive,0,7)
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
}""","onme-borrowmut.omni")
        wave=proc(OMNI,"wave",p);self.assertEqual(wave.returncode,0,wave.stderr)
        self.assertTrue(wave.stdout.startswith(b"(omni-wave 18"))
        encoded=self.d/"borrowmut.onme"
        enc=proc(OMNI,"onme",p,"-o",encoded);self.assertEqual(enc.returncode,0,enc.stderr)
        self.assertTrue(encoded.read_bytes().startswith(b"ONME2\n"))
        decoded=proc(OMNI,"wave",encoded);self.assertEqual(decoded.returncode,0,decoded.stderr)
        self.assertEqual(wave.stdout,decoded.stdout)
        checked=proc(OMNI,"check",encoded);self.assertEqual(checked.returncode,0,checked.stderr)

    def test_osnmf_exposes_distinct_shared_and_exclusive_loan_typeids(self):
        p=self.source("""module t
func inspect(shared Borrow<Buffer>, exclusive BorrowMut<Buffer>) u32 !{memory.read} {
  return buffer.len(shared)+buffer.len(exclusive)
}
func main() u32 { return 0 }
""","osnmf-borrow-types.omni")
        r=proc(OMNI,"memory",p);self.assertEqual(r.returncode,0,r.stderr)
        data=json.loads(r.stdout)
        types={n["name"]:n for n in data["nuclei"] if n["kind"]=="type"}
        self.assertIn("Borrow<Buffer>",types)
        self.assertIn("BorrowMut<Buffer>",types)
        self.assertNotEqual(types["Borrow<Buffer>"]["type_id"],types["BorrowMut<Buffer>"]["type_id"])


    def test_borrow_layout_descriptors_are_explicitly_non_addressable(self):
        shared=json.loads(proc(OMNI,"type","layout","Borrow<Buffer>").stdout)
        exclusive=json.loads(proc(OMNI,"type","layout","BorrowMut<Buffer>").stdout)
        resource=json.loads(proc(OMNI,"type","layout","Resource<Buffer>").stdout)
        self.assertFalse(shared["zero_copy_candidate"])
        self.assertFalse(exclusive["zero_copy_candidate"])
        self.assertFalse(resource["zero_copy_candidate"])
        self.assertFalse(shared["portable_address"])
        self.assertFalse(exclusive["portable_address"])
        self.assertFalse(resource["portable_address"])
        self.assertEqual(shared["ownership"],"borrowed-shared-readonly")
        self.assertEqual(exclusive["ownership"],"borrowed-exclusive-mutable")
        self.assertEqual(resource["ownership"],"owned-resource-opaque")


    def test_type_descriptor_v2_matches_osnmf_canonical_typeids(self):
        p=self.source("""module t
func inspect(shared Borrow<Buffer>, exclusive BorrowMut<Buffer>, n u32) u32 !{memory.read} {
  return buffer.len(shared)+buffer.len(exclusive)+n
}
func main() u32 { return 0 }
""","typeid-parity.omni")
        memory=proc(OMNI,"memory",p)
        self.assertEqual(memory.returncode,0,memory.stderr)
        nuclei={n["name"]:n["type_id"] for n in json.loads(memory.stdout)["nuclei"] if n["kind"]=="type"}
        for typename in ("u32","Borrow<Buffer>","BorrowMut<Buffer>"):
            desc_proc=proc(OMNI,"type","describe",typename)
            self.assertEqual(desc_proc.returncode,0,desc_proc.stderr)
            desc=json.loads(desc_proc.stdout)
            self.assertEqual(desc["schema"],"omni.type-descriptor/2")
            self.assertEqual(desc["type_identity_domain"],"omni.type/1")
            self.assertEqual(desc["type_id"],nuclei[typename])
            self.assertEqual(desc["legacy_descriptor_schema"],"omni.type-descriptor/1")
            self.assertIn("legacy_descriptor_identity_material",desc)
            self.assertIn("legacy_descriptor_id",desc)
            self.assertNotEqual(desc["type_id"],desc["legacy_descriptor_id"])

    def test_canonical_typeid_is_stable_and_domain_separated(self):
        a=json.loads(proc(OMNI,"type","describe","Borrow<Buffer>").stdout)
        b=json.loads(proc(OMNI,"type","describe","Borrow<Buffer>").stdout)
        m=json.loads(proc(OMNI,"type","describe","BorrowMut<Buffer>").stdout)
        self.assertEqual(a["type_id"],b["type_id"])
        self.assertNotEqual(a["type_id"],m["type_id"])
        self.assertEqual(a["canonical_identity_material"],"Borrow<Buffer>")
        self.assertEqual(m["canonical_identity_material"],"BorrowMut<Buffer>")
        self.assertTrue(a["type_id"].startswith("sha256:"))


    def test_outer_call_loan_survives_later_argument_evaluation(self):
        self.check_err("""module t
func nested(x BorrowMut<Buffer>) u32 !{memory.read} {
  return buffer.len(x)
}
func outer(x Borrow<Buffer>, n u32) u32 !{memory.read} {
  return buffer.len(x)+n
}
func main() u32 !{memory.read,memory.write} {
  let allocation = buffer.alloc(8)
  match allocation {
    Ok(buf) {
      let n = outer(borrow(buf),nested(borrow_mut(buf)))
      let released = buffer.release(move(buf))
      return n
    }
    Err(e) { return e }
  }
}""","E_BORROW_CONFLICT")

    def test_nested_temporary_borrow_may_end_before_later_move_argument(self):
        self.check_ok("""module t
func consume(n u32, owned Resource<Buffer>) u32 !{memory.write} {
  let released = buffer.release(move(owned))
  return n
}
func main() u32 !{memory.read,memory.write} {
  let allocation = buffer.alloc(8)
  match allocation {
    Ok(buf) {
      return consume(buffer.len(borrow(buf)),move(buf))
    }
    Err(e) { return e }
  }
}""")

if __name__=="__main__":
    unittest.main(verbosity=2)
