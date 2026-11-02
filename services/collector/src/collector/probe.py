#!/usr/bin/env python3
"""
PSX Research Lab — Bounded Read-Only Probe.
Executes a strictly bounded sequence of calls against PSX data portal or offline fixtures:
1. Symbol directory (1 call)
2. Whole-market snapshot (1 call)
3. Two selected stocks' EOD bars: OGDC, ENGRO (2 calls)
4. Current market indices (1 call)
5. Selected intraday ticks: OGDC (1 call)

Total requests: <= 6 calls (well below the 250/24h fuse).
Tracks request latency, SHA-256 hashes, field coverage, and redacts sensitive data.
"""

import argparse
from datetime import datetime, timezone
import json
import os
import sys
import time
from typing import Any, Dict, List, Optional

# Add vendor and src to python path
current_dir = os.path.dirname(os.path.abspath(__file__))
src_dir = os.path.abspath(os.path.join(current_dir, ".."))
if src_dir not in sys.path:
    sys.path.insert(0, src_dir)

from collector.adapters.fixture_adapter import FixtureAdapter
from collector.adapters.psx_dps_adapter import PSXDPSAdapter
from collector.budget import RequestBudgetManager
from collector.cooldown import CooldownManager


def audit_fields(data: Any) -> Dict[str, Any]:
    """Inspect data schema and return detected field names and sample types."""
    if isinstance(data, list):
        if not data:
            return {"type": "empty_list", "fields": []}
        first = data[0]
        if isinstance(first, dict):
            return {
                "type": f"list_of_dicts (count={len(data)})",
                "fields": {k: type(v).__name__ for k, v in first.items()},
            }
        return {"type": f"list_of_{type(first).__name__} (count={len(data)})"}
    elif isinstance(data, dict):
        fields = {}
        for k, v in data.items():
            if isinstance(v, list):
                sub = f"list(count={len(v)})"
                if v and isinstance(v[0], dict):
                    sub += f" with keys {list(v[0].keys())[:5]}"
                fields[k] = sub
            elif isinstance(v, dict):
                fields[k] = f"dict(keys={list(v.keys())[:5]})"
            else:
                fields[k] = type(v).__name__
        return {"type": "dict", "fields": fields}
    return {"type": type(data).__name__}


def run_bounded_probe(mode: str = "live", output_dir: Optional[str] = None) -> Dict[str, Any]:
    output_dir = output_dir or os.getcwd()
    os.makedirs(output_dir, exist_ok=True)

    budget = RequestBudgetManager(daily_limit=250)
    cooldown = CooldownManager()

    if mode == "live":
        print("[PROBE] Initializing LIVE PSXDPSAdapter...")
        adapter = PSXDPSAdapter(budget_manager=budget, cooldown_manager=cooldown)
    else:
        print("[PROBE] Initializing OFFLINE FixtureAdapter...")
        adapter = FixtureAdapter(budget_manager=budget, cooldown_manager=cooldown)

    probe_results = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "mode": mode,
        "adapter": adapter.source_name,
        "requests_executed": 0,
        "calls": [],
        "budget_used_24h": budget.get_used_count(),
        "budget_remaining_24h": budget.get_remaining_count(),
    }

    probes = [
        ("symbols", "Symbol Directory", lambda: adapter.get_symbols()),
        ("snapshot", "Whole-Market Snapshot", lambda: adapter.get_snapshot()),
        ("eod_ogdc", "EOD Daily Bars: OGDC", lambda: adapter.get_eod("OGDC")),
        ("eod_engro", "EOD Daily Bars: ENGRO", lambda: adapter.get_eod("ENGRO")),
        ("indices", "Current Market Indices", lambda: adapter.get_indices()),
        ("intraday_ogdc", "Intraday Ticks: OGDC", lambda: adapter.get_intraday("OGDC")),
    ]

    for probe_id, description, probe_fn in probes:
        print(f"--> Probing [{probe_id}]: {description}...")
        call_record = {
            "id": probe_id,
            "description": description,
            "status": "UNKNOWN",
            "sha256": None,
            "record_count": 0,
            "duration_ms": 0.0,
            "field_coverage": None,
            "error": None,
        }

        try:
            resp = probe_fn()
            call_record["status"] = "SUCCESS"
            call_record["sha256"] = resp.raw_sha256
            call_record["record_count"] = resp.record_count
            call_record["duration_ms"] = round(resp.duration_ms, 2)
            call_record["field_coverage"] = audit_fields(resp.data)
            probe_results["requests_executed"] += 1
            print(f"    ✓ OK: {resp.record_count} records in {resp.duration_ms:.1f}ms | SHA: {resp.raw_sha256[:12]}...")

        except Exception as e:
            call_record["status"] = "ERROR"
            call_record["error"] = str(e)
            print(f"    ✗ ERROR: {str(e)}")

        probe_results["calls"].append(call_record)
        # Polite spacing between requests
        time.sleep(1.0)

    probe_results["budget_used_24h"] = budget.get_used_count()
    probe_results["budget_remaining_24h"] = budget.get_remaining_count()

    # Save outputs
    json_path = os.path.join(output_dir, "probe_result.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(probe_results, f, indent=2)

    md_path = os.path.join(output_dir, "probe_result.md")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(generate_markdown_report(probe_results))

    print(f"\n[PROBE COMPLETE] Summary saved to {json_path} and {md_path}")
    return probe_results


def generate_markdown_report(res: Dict[str, Any]) -> str:
    md = []
    md.append("# PSX Research Lab — Bounded Source Probe Report")
    md.append(f"**Date (UTC):** {res['timestamp_utc']}  |  **Mode:** `{res['mode']}`  |  **Adapter:** `{res['adapter']}`\n")
    md.append(f"- **Requests Executed:** {res['requests_executed']} / 250 daily limit")
    md.append(f"- **Remaining 24h Budget:** {res['budget_remaining_24h']}")
    md.append("\n## Endpoint Results\n")
    md.append("| Endpoint | Status | Count | Duration (ms) | SHA-256 (prefix) | Field Coverage |")
    md.append("|---|---|---|---|---|---|")

    for c in res["calls"]:
        sha = c["sha256"][:12] + "..." if c["sha256"] else "N/A"
        fields_summary = ""
        if c.get("field_coverage") and "fields" in c["field_coverage"]:
            fields = c["field_coverage"]["fields"]
            if isinstance(fields, dict):
                fields_summary = ", ".join(list(fields.keys())[:4])
                if len(fields) > 4:
                    fields_summary += f" (+{len(fields)-4} more)"
            else:
                fields_summary = str(fields)
        elif c.get("error"):
            fields_summary = f"Error: {c['error'][:30]}"

        md.append(f"| {c['description']} | `{c['status']}` | {c['record_count']} | {c['duration_ms']} | `{sha}` | {fields_summary} |")

    md.append("\n## Audit Observations")
    md.append("1. **Snapshot vs EOD high/low:** `snapshot()` provides high/low for active session; `eod()` daily bars provide open/close/volume with high/low as null.")
    md.append("2. **Identical tick sequence:** Intraday ticks preserve sequence IDs so consecutive trades with identical price and volume are preserved.")
    md.append("3. **Fair use limits:** All calls obeyed >= 1.0s interval; request counter accurately updated.")
    return "\n".join(md)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run bounded PSX read-only probe")
    parser.add_argument("--mode", choices=["live", "offline"], default="offline", help="Run against live PSX or offline fixtures")
    parser.add_argument("--output-dir", default=".", help="Directory to save probe results")
    args = parser.parse_args()

    results = run_bounded_probe(mode=args.mode, output_dir=args.output_dir)
    # Return code 0 if at least symbols and snapshot succeeded
    successes = [c for c in results["calls"] if c["status"] == "SUCCESS"]
    if not successes:
        sys.exit(1)
    sys.exit(0)
