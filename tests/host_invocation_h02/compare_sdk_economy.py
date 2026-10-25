#!/usr/bin/env python3
"""Verify a same-host public C SDK economy comparison without inventing an SLA."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path


def read(path: str) -> dict:
    return json.loads(Path(path).read_text())


def index(report: dict) -> dict:
    return {row['fixture']: row for row in report['fixtures']}


def main() -> None:
    if len(sys.argv) != 5:
        raise SystemExit('usage: compare_sdk_economy.py BASELINE CANDIDATE BASELINE_SHA CANDIDATE_SHA')
    baseline, candidate = read(sys.argv[1]), read(sys.argv[2])
    baseline_sha, candidate_sha = sys.argv[3:]
    checks = {
        'schema': baseline.get('schema') == candidate.get('schema') == 'omni.host-sdk-economy/1',
        'source_sha': baseline.get('source_sha') == baseline_sha and candidate.get('source_sha') == candidate_sha,
        'host': baseline.get('host') == candidate.get('host'),
        'iterations': baseline['fixtures'][0]['iterations'] == candidate['fixtures'][0]['iterations'],
        'warmup': baseline['fixtures'][0]['warmup'] == candidate['fixtures'][0]['warmup'],
        'thread_profile': baseline.get('thread_counts') == candidate.get('thread_counts') == [1],
        'hot_path': not baseline.get('hot_path_json') and not candidate.get('hot_path_json') and not baseline.get('extra_process_hop') and not candidate.get('extra_process_hop'),
    }
    before, after = index(baseline), index(candidate)
    checks['fixtures'] = set(before) == set(after) == {'echo', 'echo_choice', 'echo_nested'}
    comparison = []
    if all(checks.values()):
        for name in sorted(before):
            left, right = before[name], after[name]
            same_payload = (left['payload_request_bytes'], left['payload_result_bytes']) == (right['payload_request_bytes'], right['payload_result_bytes'])
            checks[f'{name}_payload'] = same_payload
            comparison.append({
                'fixture': name,
                'payload_bytes': left['payload_request_bytes'],
                'encode_mean_ratio': round(right['encode_latency']['mean_ns'] / left['encode_latency']['mean_ns'], 4),
                'decode_mean_ratio': round(right['decode_latency']['mean_ns'] / left['decode_latency']['mean_ns'], 4),
                'throughput_ratio': round(right['roundtrip_throughput_per_second'] / left['roundtrip_throughput_per_second'], 4),
                'rss_delta_kib_baseline': left['rss_delta_kib'],
                'rss_delta_kib_candidate': right['rss_delta_kib'],
            })
    report = {
        'schema': 'omni.host-sdk-economy-comparison/1',
        'baseline_source_sha': baseline_sha,
        'candidate_source_sha': candidate_sha,
        'checks': checks,
        'status': 'PASS' if all(checks.values()) else 'FAIL',
        'comparison': comparison,
        'interpretation': 'Characterization only; no universal latency SLA or multithread guarantee is asserted.',
    }
    if path := os.environ.get('OMNI_SDK_ECONOMY_COMPARISON_PATH'):
        Path(path).write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, sort_keys=True))
    raise SystemExit(report['status'] != 'PASS')


if __name__ == '__main__':
    main()
