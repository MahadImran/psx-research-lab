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
    assert len(m1.get("cycles", [])) == 1  # 1st cycle is represented in cycle ledger

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
    assert len(m2.get("cycles", [])) == 2  # Both cycles 1 and 2 preserved in history


def test_raw_archive_object_immutability_rejects_content_change():
    """
    Proves Item 1: Raw archive objects under raw/ are strictly immutable.
    Attempting to overwrite an existing path with differing content must raise ArchiveCommitError.
    """
    mgr = DurableArchiveManager(token="test-token", repo_name="test/repo", require_remote=True)
    rel_path = "raw/2026/11/02/test_snapshot.json.gz"

    content_v1 = b"original-raw-content"
    content_v2 = b"different-modified-content"

    with patch.object(mgr, "read_remote_file") as mock_read:
        # File already exists with content_v1
        mock_read.return_value = (content_v1, "sha-v1")

        # Attempt to write content_v2 must raise ArchiveCommitError
        with pytest.raises(ArchiveCommitError) as exc_info:
            mgr.commit_file_to_archive(rel_path, content_v2, "attempted overwrite")
        assert "Immutability violation" in str(exc_info.value)
        assert "strictly immutable" in str(exc_info.value)


def test_corrupt_manifest_fails_closed_and_preserves_backup(tmp_path):
    """
    Proves Item 1: Unreadable or corrupt manifests must fail closed, preserve a backup
    of the corrupt payload for recovery, and never overwrite the manifest with incomplete state.
    """
    local_dir = str(tmp_path / "archive")
    mgr = DurableArchiveManager(token=None, local_archive_dir=local_dir, require_remote=False)
    trading_date = "2026-11-02"
    manifest_rel = f"manifests/{trading_date}.json"

    # Write corrupt unparseable JSON to existing manifest location
    full_manifest_path = os.path.join(local_dir, manifest_rel)
    os.makedirs(os.path.dirname(full_manifest_path), exist_ok=True)
    corrupt_bytes = b'{"manifestVersion": "1.0.0", "corrupt_truncated_json": '
    with open(full_manifest_path, "wb") as f:
        f.write(corrupt_bytes)

    # Attempting to commit a new manifest must fail closed
    new_payload = {
        "manifestVersion": "1.0.0",
        "generatedAtUtc": "2026-11-02T10:00:00Z",
        "tradingDate": trading_date,
        "source": "psx-dps",
        "totalBars": 10,
        "totalSnapshots": 100,
        "totalIndices": 18,
        "payloadSha256": "hash-new",
        "verifiedArchiveFiles": ["raw/2026/11/02/new_data.json.gz"],
    }

    with pytest.raises(ArchiveCommitError) as exc_info:
        mgr.commit_daily_manifest(trading_date, new_payload)

    assert "Corrupt or unreadable existing manifest" in str(exc_info.value)

    # Verify corrupt file was preserved (not overwritten by incomplete new_payload)
    with open(full_manifest_path, "rb") as f:
        assert f.read() == corrupt_bytes

    # Verify a corrupted backup copy was saved in manifests/ directory
    manifests_dir = os.path.join(local_dir, "manifests")
    files = os.listdir(manifests_dir)
    corrupted_backups = [f for f in files if f.startswith(f"corrupted_{trading_date}")]
    assert len(corrupted_backups) >= 1

