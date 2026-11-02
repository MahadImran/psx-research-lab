import pytest
from unittest.mock import patch, MagicMock
import base64
import gzip
import json
import urllib.error
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

from collector.archive import DurableArchiveManager, ArchiveCommitError, ArchiveCredentialsError


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


def test_archive_manager_fails_closed_in_production_without_token():
    mgr = DurableArchiveManager(token=None, require_remote=True)
    with pytest.raises(ArchiveCredentialsError) as exc_info:
        mgr.commit_file_to_archive("raw/2026/11/02/test.json.gz", b"data", "test commit")
    assert "DATA_REPO_TOKEN required" in str(exc_info.value)


def test_archive_manager_commits_with_readback_verification(tmp_path):
    archive_dir = str(tmp_path / "archive")
    mgr = DurableArchiveManager(token="fake-token", repo_name="test/repo", local_archive_dir=archive_dir)

    test_content = b"compressed-market-data-bytes"
    b64_content = base64.b64encode(test_content).decode("utf-8")

    # Mock urllib calls:
    # 1. read_remote_file pre-check -> 404 (not exists)
    # 2. commit PUT -> 201 Created
    # 3. readback verification GET -> 200 OK with identical content
    with patch("urllib.request.urlopen") as mock_urlopen:
        mock_pre_err = urllib.error.HTTPError("url", 404, "Not Found", {}, None)

        mock_put_resp = MagicMock(status=201)
        mock_put_resp.__enter__.return_value = mock_put_resp

        mock_get_resp = MagicMock(status=200)
        mock_get_resp.read.return_value = json.dumps({
            "sha": "blob-sha-123",
            "content": b64_content,
        }).encode("utf-8")
        mock_get_resp.__enter__.return_value = mock_get_resp

        mock_urlopen.side_effect = [
            mock_pre_err,   # pre-check
            mock_put_resp,  # PUT
            mock_get_resp,  # Readback
        ]

        ok = mgr.commit_file_to_archive("raw/2026/11/02/file.json.gz", test_content, "commit msg")
        assert ok is True


def test_archive_manager_readback_hash_mismatch_raises():
    mgr = DurableArchiveManager(token="fake-token", repo_name="test/repo")
    test_content = b"original-content"
    tampered_content = b"tampered-corrupted-bytes"
    b64_tampered = base64.b64encode(tampered_content).decode("utf-8")

    with patch("urllib.request.urlopen") as mock_urlopen:
        mock_pre_err = urllib.error.HTTPError("url", 404, "Not Found", {}, None)

        mock_put_resp = MagicMock(status=201)
        mock_put_resp.__enter__.return_value = mock_put_resp

        mock_get_resp = MagicMock(status=200)
        mock_get_resp.read.return_value = json.dumps({
            "sha": "blob-sha-123",
            "content": b64_tampered,
        }).encode("utf-8")
        mock_get_resp.__enter__.return_value = mock_get_resp

        mock_urlopen.side_effect = [
            mock_pre_err,
            mock_put_resp,
            mock_get_resp,
        ]

        with pytest.raises(ArchiveCommitError) as exc_info:
            mgr.commit_file_to_archive("raw/2026/11/02/corrupt.json.gz", test_content, "commit msg")
        assert "Readback verification hash mismatch" in str(exc_info.value)


def test_archive_manager_idempotent_existing_file():
    mgr = DurableArchiveManager(token="fake-token", repo_name="test/repo")
    test_content = b"already-archived-content"
    b64_content = base64.b64encode(test_content).decode("utf-8")

    with patch("urllib.request.urlopen") as mock_urlopen:
        mock_get_resp = MagicMock(status=200)
        mock_get_resp.read.return_value = json.dumps({
            "sha": "blob-sha-123",
            "content": b64_content,
        }).encode("utf-8")
        mock_get_resp.__enter__.return_value = mock_get_resp

        mock_urlopen.return_value = mock_get_resp

        # Pre-check returns matching content -> skips PUT entirely!
        ok = mgr.commit_file_to_archive("raw/2026/11/02/existing.json.gz", test_content, "commit msg")
        assert ok is True
        assert mock_urlopen.call_count == 1


def test_archive_manager_cumulative_manifest_merging(tmp_path):
    """
    Proves Critical Issue C: Multiple collections on the same trading day
    accumulate verifiedArchiveFiles and cycles rather than erasing earlier runs.
    """
    local_dir = str(tmp_path / "archive")
    mgr = DurableArchiveManager(token=None, local_archive_dir=local_dir, require_remote=False)

    trading_date = "2026-11-02"

    # Cycle 1: Morning collection
    c1_payload = {
        "manifestVersion": "1.0.0",
        "generatedAtUtc": "2026-11-02T04:30:00Z",
        "tradingDate": trading_date,
        "source": "psx-dps",
        "totalBars": 0,
        "totalSnapshots": 100,
        "totalIndices": 18,
        "payloadSha256": "hash-c1",
        "verifiedArchiveFiles": ["raw/2026/11/02/snapshot_043000Z.json.gz"],
    }
    manifest_rel = mgr.commit_daily_manifest(trading_date, c1_payload)

    # Read back cycle 1 manifest
    m1_bytes, _ = mgr.read_remote_file(manifest_rel)
    m1 = json.loads(m1_bytes.decode("utf-8"))
    assert m1["verifiedArchiveFiles"] == ["raw/2026/11/02/snapshot_043000Z.json.gz"]
    assert len(m1.get("cycles", [])) == 0  # 1st cycle doesn't have existing prior cycles

    # Cycle 2: Afternoon collection on same trading day
    c2_payload = {
        "manifestVersion": "1.0.0",
        "generatedAtUtc": "2026-11-02T09:30:00Z",
        "tradingDate": trading_date,
        "source": "psx-dps",
        "totalBars": 50,
        "totalSnapshots": 100,
        "totalIndices": 18,
        "payloadSha256": "hash-c2",
        "verifiedArchiveFiles": ["raw/2026/11/02/eod_reconciled_093000Z.json.gz"],
    }
    mgr.commit_daily_manifest(trading_date, c2_payload)

    # Read back merged manifest
    m2_bytes, _ = mgr.read_remote_file(manifest_rel)
    m2 = json.loads(m2_bytes.decode("utf-8"))

    # Both archive files must be listed!
    assert "raw/2026/11/02/snapshot_043000Z.json.gz" in m2["verifiedArchiveFiles"]
    assert "raw/2026/11/02/eod_reconciled_093000Z.json.gz" in m2["verifiedArchiveFiles"]
    assert len(m2["verifiedArchiveFiles"]) == 2
    assert len(m2.get("cycles", [])) == 1  # Cycle 1 preserved in history

