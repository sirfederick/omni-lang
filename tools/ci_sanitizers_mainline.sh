#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
EVIDENCE="${OMNI_EVIDENCE_DIR:-$ROOT/evidence}"
VERSION="$(tr -d '\r\n' < "$ROOT/VERSION")"
EVIDENCE_LABEL="${VERSION//[^[:alnum:]]/_}"
cd "$ROOT"
mkdir -p "$EVIDENCE"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

OMNI_CRYPTO_LIBS="${OMNI_CRYPTO_LIBS:--lcrypto}" python3 "$ROOT/tools/build_compiler.py" --output "$TMP/omni" --jobs "${OMNI_BUILD_JOBS:-2}" --sanitizers --quiet
export OMNI_HOME="$ROOT" OMNI_TEST_BIN="$TMP/omni" PYTHONDONTWRITEBYTECODE=1
export ASAN_OPTIONS=detect_leaks=1:halt_on_error=1 UBSAN_OPTIONS=halt_on_error=1

python3 -B tests/language_sanitizer_smoke.py 2>&1 | tee "$EVIDENCE/sanitizer_compiler_${EVIDENCE_LABEL}.txt"
python3 -B tests/security_regressions_alpha6.py 2>&1 | tee "$EVIDENCE/security_regressions_sanitized_${EVIDENCE_LABEL}.txt"
python3 -B tests/language_0_7_alpha7.py 2>&1 | tee "$EVIDENCE/living_system_conformance_sanitized_${EVIDENCE_LABEL}.txt"
python3 -B tests/language_0_8_alpha8.py 2>&1 | tee "$EVIDENCE/memory_authority_conformance_sanitized_${EVIDENCE_LABEL}.txt"
python3 -B tests/memory_authority_differential.py 2>&1 | tee "$EVIDENCE/memory_authority_differential_sanitized_${EVIDENCE_LABEL}.txt"
python3 -B tests/language_0_8_1_alpha8.py 2>&1 | tee "$EVIDENCE/data_language_conformance_sanitized_${EVIDENCE_LABEL}.txt"
python3 -B tests/language_0_8_2_alpha8.py 2>&1 | tee "$EVIDENCE/a82_conformance_sanitized_${EVIDENCE_LABEL}.txt"
# Core 1.3 suites. These instrument the COMPILER (ASan/UBSan); the LLVM executables they build and the QEMU guests are not instrumented,
# so each report below states the compiler scope only. A suite that skips its guarded cases still exits 0: the skip count is part of the
# evidence (see run_test_matrix.py --no-skips), not something this exit code proves.
python3 -B tests/option_owning_record.py 2>&1 | tee "$EVIDENCE/option_owning_record_sanitized_${EVIDENCE_LABEL}.txt"
python3 -B tests/language_0_8_3_alpha8.py 2>&1 | tee "$EVIDENCE/a83_conformance_sanitized_${EVIDENCE_LABEL}.txt"
python3 -B tests/language_1_3_hardware_primitives.py 2>&1 | tee "$EVIDENCE/hardware_primitives_sanitized_${EVIDENCE_LABEL}.txt"
python3 -B tests/cp04_dynamic_storage.py 2>&1 | tee "$EVIDENCE/dynamic_storage_sanitized_${EVIDENCE_LABEL}.txt"
python3 -B tests/robustness_limits.py 2>&1 | tee "$EVIDENCE/robustness_limits_sanitized_${EVIDENCE_LABEL}.txt"
python3 -B tests/cp02_borrowed_containers.py 2>&1 | tee "$EVIDENCE/borrowed_containers_sanitized_${EVIDENCE_LABEL}.txt"
python3 -B tests/cp01_generic_resources.py 2>&1 | tee "$EVIDENCE/generic_resources_sanitized_${EVIDENCE_LABEL}.txt"
python3 -B tests/cp01_owned_slots.py 2>&1 | tee "$EVIDENCE/owned_slots_sanitized_${EVIDENCE_LABEL}.txt"
python3 -B tests/cp03_cleanup_failure.py 2>&1 | tee "$EVIDENCE/cleanup_failure_sanitized_${EVIDENCE_LABEL}.txt"
python3 -B tests/cp06_callable_registry.py 2>&1 | tee "$EVIDENCE/callable_registry_sanitized_${EVIDENCE_LABEL}.txt"
python3 -B tests/cp05_collections.py 2>&1 | tee "$EVIDENCE/collections_sanitized_${EVIDENCE_LABEL}.txt"
python3 -B tests/cp02_windows.py 2>&1 | tee "$EVIDENCE/windows_sanitized_${EVIDENCE_LABEL}.txt"
python3 -B tests/cp02_adversarial.py 2>&1 | tee "$EVIDENCE/adversarial_sanitized_${EVIDENCE_LABEL}.txt"
python3 -B tests/cp05_packages.py 2>&1 | tee "$EVIDENCE/packages_sanitized_${EVIDENCE_LABEL}.txt"
python3 -B tests/cp04_arena_live_users.py 2>&1 | tee "$EVIDENCE/arena_users_sanitized_${EVIDENCE_LABEL}.txt"
python3 -B tests/cp07_address_domains.py 2>&1 | tee "$EVIDENCE/address_domains_sanitized_${EVIDENCE_LABEL}.txt"
python3 -B tests/cp07_casts.py 2>&1 | tee "$EVIDENCE/casts_sanitized_${EVIDENCE_LABEL}.txt"
python3 -B tests/cp07_static_data.py 2>&1 | tee "$EVIDENCE/static_data_sanitized_${EVIDENCE_LABEL}.txt"
python3 -B tests/cp07_static_assert.py 2>&1 | tee "$EVIDENCE/static_assert_sanitized_${EVIDENCE_LABEL}.txt"
python3 -B tests/cp07_target.py 2>&1 | tee "$EVIDENCE/target_sanitized_${EVIDENCE_LABEL}.txt"
python3 -B tests/cp07_endian.py 2>&1 | tee "$EVIDENCE/endian_sanitized_${EVIDENCE_LABEL}.txt"
python3 -B tests/cp08_mmio.py 2>&1 | tee "$EVIDENCE/mmio_sanitized_${EVIDENCE_LABEL}.txt"
python3 -B tests/cp08_dma.py 2>&1 | tee "$EVIDENCE/dma_sanitized_${EVIDENCE_LABEL}.txt"
python3 -B tests/cp08_fields.py 2>&1 | tee "$EVIDENCE/fields_sanitized_${EVIDENCE_LABEL}.txt"
python3 -B tests/cp08_raw_boundary.py 2>&1 | tee "$EVIDENCE/raw_boundary_sanitized_${EVIDENCE_LABEL}.txt"
python3 -B tests/cp09_freestanding.py 2>&1 | tee "$EVIDENCE/freestanding_sanitized_${EVIDENCE_LABEL}.txt"
python3 -B tests/cp09_linkage.py 2>&1 | tee "$EVIDENCE/linkage_sanitized_${EVIDENCE_LABEL}.txt"
python3 -B tests/cp10_state.py 2>&1 | tee "$EVIDENCE/cpu_state_sanitized_${EVIDENCE_LABEL}.txt"
python3 -B tests/cp10_simd.py 2>&1 | tee "$EVIDENCE/simd_sanitized_${EVIDENCE_LABEL}.txt"
python3 -B tests/cp11_tls_irq.py 2>&1 | tee "$EVIDENCE/tls_irq_sanitized_${EVIDENCE_LABEL}.txt"
python3 -B tests/cp12_frames.py 2>&1 | tee "$EVIDENCE/frames_sanitized_${EVIDENCE_LABEL}.txt"
python3 -B tests/cp12_stacks.py 2>&1 | tee "$EVIDENCE/stacks_sanitized_${EVIDENCE_LABEL}.txt"
python3 -B tests/cp16_diagnostics.py 2>&1 | tee "$EVIDENCE/diagnostics_sanitized_${EVIDENCE_LABEL}.txt"
python3 -B tests/cp16_single_checker.py 2>&1 | tee "$EVIDENCE/single_checker_sanitized_${EVIDENCE_LABEL}.txt"
python3 -B tests/cp16_tooling.py 2>&1 | tee "$EVIDENCE/tooling_sanitized_${EVIDENCE_LABEL}.txt"
python3 -B tests/cp17_distribution.py 2>&1 | tee "$EVIDENCE/distribution_sanitized_${EVIDENCE_LABEL}.txt"
python3 -B tests/cp17_semantic_exports.py 2>&1 | tee "$EVIDENCE/semantic_exports_sanitized_${EVIDENCE_LABEL}.txt"
python3 -B tests/cp18_traceability.py 2>&1 | tee "$EVIDENCE/traceability_sanitized_${EVIDENCE_LABEL}.txt"
# Storage runtime scope (a different check from the compiler instrumentation above): the same suites again with the native executables AND the C runtime built under
# ASan/UBSan (OMNI_NATIVE_SANITIZE=1: emit-llvm + clang -fsanitize=address,undefined over runtime/omni_runtime.c), so a defect in the buffer/slot runtime is seen.
OMNI_NATIVE_SANITIZE=1 python3 -B tests/cp02_borrowed_containers.py 2>&1 | tee "$EVIDENCE/borrowed_containers_native_sanitized_${EVIDENCE_LABEL}.txt"
OMNI_NATIVE_SANITIZE=1 python3 -B tests/cp01_generic_resources.py 2>&1 | tee "$EVIDENCE/generic_resources_native_sanitized_${EVIDENCE_LABEL}.txt"
OMNI_NATIVE_SANITIZE=1 python3 -B tests/cp01_owned_slots.py 2>&1 | tee "$EVIDENCE/owned_slots_native_sanitized_${EVIDENCE_LABEL}.txt"
OMNI_NATIVE_SANITIZE=1 python3 -B tests/cp03_cleanup_failure.py 2>&1 | tee "$EVIDENCE/cleanup_failure_native_sanitized_${EVIDENCE_LABEL}.txt"
OMNI_NATIVE_SANITIZE=1 python3 -B tests/cp06_callable_registry.py 2>&1 | tee "$EVIDENCE/callable_registry_native_sanitized_${EVIDENCE_LABEL}.txt"
OMNI_NATIVE_SANITIZE=1 python3 -B tests/cp05_collections.py 2>&1 | tee "$EVIDENCE/collections_native_sanitized_${EVIDENCE_LABEL}.txt"
OMNI_NATIVE_SANITIZE=1 python3 -B tests/cp02_windows.py 2>&1 | tee "$EVIDENCE/windows_native_sanitized_${EVIDENCE_LABEL}.txt"
OMNI_NATIVE_SANITIZE=1 python3 -B tests/cp02_adversarial.py 2>&1 | tee "$EVIDENCE/adversarial_native_sanitized_${EVIDENCE_LABEL}.txt"
OMNI_NATIVE_SANITIZE=1 python3 -B tests/cp07_static_data.py 2>&1 | tee "$EVIDENCE/static_data_native_sanitized_${EVIDENCE_LABEL}.txt"
OMNI_NATIVE_SANITIZE=1 python3 -B tests/cp07_static_assert.py 2>&1 | tee "$EVIDENCE/static_assert_native_sanitized_${EVIDENCE_LABEL}.txt"
OMNI_NATIVE_SANITIZE=1 python3 -B tests/cp07_target.py 2>&1 | tee "$EVIDENCE/target_native_sanitized_${EVIDENCE_LABEL}.txt"
OMNI_NATIVE_SANITIZE=1 python3 -B tests/cp07_endian.py 2>&1 | tee "$EVIDENCE/endian_native_sanitized_${EVIDENCE_LABEL}.txt"
OMNI_NATIVE_SANITIZE=1 python3 -B tests/cp08_fields.py 2>&1 | tee "$EVIDENCE/fields_native_sanitized_${EVIDENCE_LABEL}.txt"
OMNI_NATIVE_SANITIZE=1 python3 -B tests/cp10_simd.py 2>&1 | tee "$EVIDENCE/simd_native_sanitized_${EVIDENCE_LABEL}.txt"
python3 -B tests/language_0_9_2.py 2>&1 | tee "$EVIDENCE/a92_semantic_conformance_sanitized_${EVIDENCE_LABEL}.txt"
OMNI_A93_SANITIZERS=1 python3 -B tests/language_0_9_3.py 2>&1 | tee "$EVIDENCE/a93_runtime_hardening_sanitized_${EVIDENCE_LABEL}.txt"
python3 -B tests/language_0_9_4.py 2>&1 | tee "$EVIDENCE/a94_systemic_durability_sanitized_${EVIDENCE_LABEL}.txt"
python3 -B tests/language_0_9_5.py 2>&1 | tee "$EVIDENCE/a95_interop_profile_sanitized_${EVIDENCE_LABEL}.txt"
python3 -B tests/language_0_9_7.py 2>&1 | tee "$EVIDENCE/a97_operations_maintenance_sanitized_${EVIDENCE_LABEL}.txt"
python3 -B tests/language_0_9_6.py 2>&1 | tee "$EVIDENCE/a96_security_supply_chain_sanitized_${EVIDENCE_LABEL}.txt"
python3 -B tests/float_differential.py 2>&1 | tee "$EVIDENCE/float_differential_sanitized_${EVIDENCE_LABEL}.txt"
python3 -B tests/unicode_differential.py 2>&1 | tee "$EVIDENCE/unicode_differential_sanitized_${EVIDENCE_LABEL}.txt"
python3 -B tests/data_control_differential.py 2>&1 | tee "$EVIDENCE/data_control_differential_sanitized_${EVIDENCE_LABEL}.txt"
python3 -B tests/range_differential.py 2>&1 | tee "$EVIDENCE/range_differential_sanitized_${EVIDENCE_LABEL}.txt"
python3 -B tools/mutate_formats.py --binary "$TMP/omni" --cases 150 --report "$EVIDENCE/mutations_sanitized_${EVIDENCE_LABEL}.json" >/dev/null

mkdir -p "$TMP/a92-root"
cat > "$TMP/a92-missing.omni" <<EOF
module a92_sanitized
func main() u32 !{fs.read} {
  let result = host.read("$TMP/a92-root/missing.bin", 64u32);
  match result { Ok(data) { return bytes.len(data); } Err(code) { return code; } }
}
EOF
cat > "$TMP/a92-policy.ohp" <<EOF
OHP1
generation|1
not_after_tick|1000
grant|fs.read|$TMP/a92-root|4096
EOF
"$TMP/omni" emit-llvm "$TMP/a92-missing.omni" -o "$TMP/a92-missing.ll"
clang -O1 -g -fsanitize=address,undefined -fno-omit-frame-pointer "$TMP/a92-missing.ll" runtime/omni_runtime.c -o "$TMP/a92-missing"
set +e
"$TMP/a92-missing" --omni-host-policy "$TMP/a92-policy.ohp" > "$EVIDENCE/runtime_sanitized_a92_${EVIDENCE_LABEL}.txt" 2> "$EVIDENCE/runtime_sanitized_a92_${EVIDENCE_LABEL}.err.txt"
a92_rc=$?
set -e
[[ "$a92_rc" -eq 3 ]] || { echo "unexpected A92 missing-path rc=$a92_rc" >&2; exit 1; }
[[ ! -s "$EVIDENCE/runtime_sanitized_a92_${EVIDENCE_LABEL}.err.txt" ]] || { cat "$EVIDENCE/runtime_sanitized_a92_${EVIDENCE_LABEL}.err.txt" >&2; exit 1; }

for name in resource_buffer numeric adt_enum product_types borrowed_views generics_iteration borrow_mut floats unicode_text data_control ranges; do
  "$TMP/omni" emit-llvm "examples/$name.omni" -o "$TMP/$name.ll"
  clang -O1 -g -fsanitize=address,undefined -fno-omit-frame-pointer "$TMP/$name.ll" runtime/omni_runtime.c -o "$TMP/$name"
  set +e
  "$TMP/$name" > "$EVIDENCE/runtime_sanitized_${name}_${EVIDENCE_LABEL}.txt" 2> "$EVIDENCE/runtime_sanitized_${name}_${EVIDENCE_LABEL}.err.txt"
  rc=$?
  set -e
  if [[ "$name" == "borrowed_views" ]]; then
    [[ "$rc" -eq 50 ]] || { echo "unexpected borrowed_views rc=$rc" >&2; exit 1; }
  elif [[ "$name" == "generics_iteration" ]]; then
    [[ "$rc" -eq 42 ]] || { echo "unexpected generics_iteration rc=$rc" >&2; exit 1; }
  elif [[ "$name" == "borrow_mut" ]]; then
    [[ "$rc" -eq 8 ]] || { echo "unexpected borrow_mut rc=$rc" >&2; exit 1; }
  elif [[ "$name" == "floats" ]]; then
    [[ "$rc" -eq 7 ]] || { echo "unexpected floats rc=$rc" >&2; exit 1; }
  elif [[ "$name" == "unicode_text" ]]; then
    [[ "$rc" -eq 3 ]] || { echo "unexpected unicode_text rc=$rc" >&2; exit 1; }
  elif [[ "$name" == "data_control" ]]; then
    [[ "$rc" -eq 100 ]] || { echo "unexpected data_control rc=$rc" >&2; exit 1; }
  elif [[ "$name" == "ranges" ]]; then
    [[ "$rc" -eq 22 ]] || { echo "unexpected ranges rc=$rc" >&2; exit 1; }
  else
    [[ "$rc" -eq 0 ]] || { echo "unexpected $name rc=$rc" >&2; exit 1; }
  fi
  [[ ! -s "$EVIDENCE/runtime_sanitized_${name}_${EVIDENCE_LABEL}.err.txt" ]] || { cat "$EVIDENCE/runtime_sanitized_${name}_${EVIDENCE_LABEL}.err.txt" >&2; exit 1; }
done

printf 'mainline %s ASan/UBSan smoke: PASS\n' "$VERSION" | tee -a "$EVIDENCE/sanitizer_compiler.txt"
