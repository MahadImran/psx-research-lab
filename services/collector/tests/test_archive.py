import pytest
import gzip
import json
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

from collector.archive import DurableArchiveManager


def test_archive_manager_stages_sharded_gzip(tmp_path):
    archive_dir = str(tmp_path / "archive")
    mgr = DurableArchiveManager(token=None, local_archive_dir=archive_dir)

    payload = [{"symbol": "OGDC", "price": 136.5} for _ in range(100)]
    rel_path, comp_bytes, sha_hash, uncomp_len = mgr.stage_locally(
        source="psx-dps",
        endpoint="snapshot",
        trading_date="2026-11-02",
        data=payload,
    )

    # 1. Sharded by raw/YYYY/MM/DD/
    assert rel_path.startswith("raw/2026/11/02/psx-dps_snapshot_")
    assert rel_path.endswith(".json.gz")

    # 2. Local file exists and decompresses cleanly
    full_path = os.path.join(archive_dir, rel_path)
    assert os.path.exists(full_path)

    with gzip.open(full_path, "rt") as f:
        decompressed_data = json.load(f)
    assert len(decompressed_data) == 100
    assert decompressed_data[0]["symbol"] == "OGDC"

    # 3. Compression efficiency: gzip size < uncompressed size
    assert len(comp_bytes) < uncomp_len


def test_archive_manager_commits_daily_manifest(tmp_path):
    archive_dir = str(tmp_path / "archive")
    mgr = DurableArchiveManager(token=None, local_archive_dir=archive_dir)

    manifest_data = {
        "manifestVersion": "1.0.0",
        "tradingDate": "2026-11-02",
        "source": "psx-dps",
        "totalBars": 500,
        "totalSnapshots": 500,
        "totalIndices": 18,
        "payloadSha256": "a" * 64,
    }

    rel_manifest = mgr.commit_daily_manifest("2026-11-02", manifest_data)
    assert rel_manifest == "manifests/2026-11-02.json"

    full_path = os.path.join(archive_dir, rel_manifest)
    assert os.path.exists(full_path)

    with open(full_path, "r") as f:
        saved = json.load(f)
    assert saved["tradingDate"] == "2026-11-02"
    assert saved["totalBars"] == 500
