import pytest
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

from collector.storage import StorageManager


def test_deduplication_detects_identical_hashes():
    data1 = {"symbol": "OGDC", "close": 136.2, "volume": 1000}
    data2 = {"symbol": "OGDC", "close": 136.2, "volume": 1000}
    data3 = {"symbol": "OGDC", "close": 137.0, "volume": 1200}

    hash1 = StorageManager.hash_payload(data1)
    hash2 = StorageManager.hash_payload(data2)
    hash3 = StorageManager.hash_payload(data3)

    assert hash1 == hash2
    assert hash1 != hash3

    # Duplicate poll detected
    assert StorageManager.is_duplicate_poll(hash2, hash1) is True
    # Different data detected
    assert StorageManager.is_duplicate_poll(hash3, hash1) is False


def test_stage_response_compresses_and_hashes(tmp_path):
    data = [{"symbol": "OGDC", "price": 136.0} for _ in range(50)]
    out_dir = str(tmp_path / "stage")
    file_path, sha_hash, byte_size = StorageManager.stage_response(
        output_dir=out_dir,
        source="psx-dps",
        endpoint="snapshot",
        trading_date="2026-10-30",
        data=data
    )

    assert os.path.exists(file_path)
    assert file_path.endswith(".json.gz")
    assert len(sha_hash) == 64
    assert byte_size > 0
