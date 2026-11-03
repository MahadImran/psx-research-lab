import pytest
from unittest.mock import patch, MagicMock
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

from collector.adapters.base import UpstreamResponse
from collector.archive import DurableArchiveManager, ArchiveCommitError
from collector.healthchecks import HealthchecksNotifier
from collector.ingest_client import IngestClient
from collector.persistent_budget import PersistentCoordinator, LeaseConflictError
from collector.pipeline import CollectorPipeline
from collector.reconciliation import EODReconciler


def test_pipeline_skips_when_market_closed():
    pipeline = CollectorPipeline()
    # Mock should_scheduled_collector_run to return False
    with patch("collector.calendar.MarketCalendar.should_scheduled_collector_run", return_value=(False, "Market closed (WEEKEND)")):
        with patch.object(pipeline.healthchecks, "ping_skip") as mock_skip:
            res = pipeline.run(force=False)
            assert res["status"] == "MARKET_CLOSED"
            assert "WEEKEND" in res["reason"]
            mock_skip.assert_called_once()


def test_pipeline_skips_on_lease_conflict():
    pipeline = CollectorPipeline()
    with patch("collector.calendar.MarketCalendar.should_scheduled_collector_run", return_value=(True, "Market active")):
        with patch.object(pipeline.coordinator, "acquire_lease_and_sync", side_effect=LeaseConflictError("Lease held by other runner")):
            with patch.object(pipeline.healthchecks, "ping_skip") as mock_skip:
                res = pipeline.run(force=True)
                assert res["status"] == "SKIPPED_LEASE_CONFLICT"
                mock_skip.assert_called_once()


def test_pipeline_full_run_with_fixtures(tmp_path):
    archive_dir = str(tmp_path / "archive")
    state_file = str(tmp_path / "state.json")

    mock_coordinator = PersistentCoordinator(token=None, local_state_file=state_file, daily_limit=250, require_remote=False)
    mock_archive = DurableArchiveManager(token=None, local_archive_dir=archive_dir, require_remote=False)
    mock_hc = HealthchecksNotifier(ping_url="https://hc-ping.com/test-uuid")

    # Mock adapter responses
    mock_adapter = MagicMock()
    mock_adapter.get_snapshot.return_value = UpstreamResponse(
        source="psx-dps",
        endpoint="snapshot",
        data={
            "rows": [
                {"symbol": "OGDC", "current": 136.5, "change": 1.2, "percentChange": 0.88, "volume": 50000},
                {"symbol": "ENGROH", "current": 285.0, "change": -2.0, "percentChange": -0.7, "volume": 12000},
            ]
        },
        raw_sha256="e" * 64,
        record_count=2,
        duration_ms=45.0,
        status_code=200,
    )
    mock_adapter.get_indices.return_value = UpstreamResponse(
        source="psx-dps",
        endpoint="indices",
        data=[
            {"code": "KSE100", "current": 85500.0, "change": 350.0, "percentChange": 0.41, "volume": 120000000}
        ],
        raw_sha256="f" * 64,
        record_count=1,
        duration_ms=30.0,
        status_code=200,
    )

    mock_ingest = MagicMock()
    mock_ingest.api_url = "https://api.psxresearchlab.com"
    mock_ingest.send_ingestion.return_value = (True, 200, {"status": "ACCEPTED"})

    pipeline = CollectorPipeline(
        adapter=mock_adapter,
        coordinator=mock_coordinator,
        archive_manager=mock_archive,
        healthchecks=mock_hc,
        ingest_client=mock_ingest,
    )

    with patch.object(mock_hc, "ping_start") as mock_start, \
         patch.object(mock_hc, "ping_success") as mock_success:

        res = pipeline.run(force=True, dry_run=False)

        assert res["status"] == "FULLY_SUCCESSFUL_CYCLE"
        assert res["snapshotSymbolsCount"] == 2
        assert res["indicesCount"] == 1
        assert res["ingestStatus"] == "ACCEPTED"
        assert len(res["archivedFiles"]) in (2, 3)

        mock_start.assert_called_once()
        mock_success.assert_called_once()
        mock_ingest.send_ingestion.assert_called_once()

        # Check lease was released in finally
        state = mock_coordinator.load_remote_state()
        assert state.get("lease") is None


def test_pipeline_fails_closed_on_archive_failure(tmp_path):
    archive_dir = str(tmp_path / "archive")
    state_file = str(tmp_path / "state.json")

    mock_coordinator = PersistentCoordinator(token=None, local_state_file=state_file, daily_limit=250, require_remote=False)
    mock_archive = MagicMock()
    mock_archive.stage_locally.return_value = ("raw/2026/11/02/file.json.gz", b"fake", "hash", 100)
    mock_archive.commit_file_to_archive.side_effect = ArchiveCommitError("Remote git commit failed (HTTP 500)")

    mock_hc = HealthchecksNotifier(ping_url="https://hc-ping.com/test-uuid")

    mock_adapter = MagicMock()
    mock_adapter.get_snapshot.return_value = UpstreamResponse(
        source="psx-dps",
        endpoint="snapshot",
        data={"rows": [{"symbol": "OGDC", "current": 136.0, "volume": 100}]},
        raw_sha256="a" * 64,
        record_count=1,
        duration_ms=20.0,
        status_code=200,
    )

    pipeline = CollectorPipeline(
        adapter=mock_adapter,
        coordinator=mock_coordinator,
        archive_manager=mock_archive,
        healthchecks=mock_hc,
    )

    with patch.object(mock_hc, "ping_fail") as mock_fail:
        res = pipeline.run(force=True, dry_run=False)
        assert res["status"] == "ARCHIVE_FAILED"
        assert "Remote git commit failed" in res["error"]
        mock_fail.assert_called_once()


def test_pipeline_reports_ingest_failure(tmp_path):
    archive_dir = str(tmp_path / "archive")
    state_file = str(tmp_path / "state.json")

    mock_coordinator = PersistentCoordinator(token=None, local_state_file=state_file, daily_limit=250, require_remote=False)
    mock_archive = DurableArchiveManager(token=None, local_archive_dir=archive_dir, require_remote=False)
    mock_hc = HealthchecksNotifier(ping_url="https://hc-ping.com/test-uuid")

    mock_adapter = MagicMock()
    mock_adapter.get_snapshot.return_value = UpstreamResponse(
        source="psx-dps",
        endpoint="snapshot",
        data={"rows": [{"symbol": "OGDC", "current": 136.0, "volume": 100}]},
        raw_sha256="a" * 64,
        record_count=1,
        duration_ms=20.0,
        status_code=200,
    )
    mock_adapter.get_indices.return_value = UpstreamResponse(
        source="psx-dps",
        endpoint="indices",
        data=[],
        raw_sha256="b" * 64,
        record_count=0,
        duration_ms=10.0,
        status_code=200,
    )

    mock_ingest = MagicMock()
    mock_ingest.api_url = "https://api.psxresearchlab.com"
    mock_ingest.send_ingestion.return_value = (False, 401, {"reason": "HMAC signature failed"})

    pipeline = CollectorPipeline(
        adapter=mock_adapter,
        coordinator=mock_coordinator,
        archive_manager=mock_archive,
        healthchecks=mock_hc,
        ingest_client=mock_ingest,
    )

    with patch.object(mock_hc, "ping_fail") as mock_fail:
        res = pipeline.run(force=True, dry_run=False)
        assert res["status"] == "INGEST_FAILED"
        assert res["httpStatus"] == 401
        mock_fail.assert_called_once()


def test_snapshot_archive_success_followed_by_index_archive_failure_reports_partial_failure(tmp_path):
    """
    Proves Item 3: When snapshot archives successfully, but index archiving fails,
    the pipeline MUST return PARTIAL_ARCHIVE_FAILED and emit ping_fail, never
    misrepresenting the run as complete.
    """
    archive_dir = str(tmp_path / "archive")
    state_file = str(tmp_path / "state.json")

    mock_coordinator = PersistentCoordinator(token=None, local_state_file=state_file, daily_limit=250, require_remote=False)
    mock_archive = DurableArchiveManager(token=None, local_archive_dir=archive_dir, require_remote=False)
    mock_hc = HealthchecksNotifier(ping_url="https://hc-ping.com/test-uuid")

    mock_adapter = MagicMock()
    mock_adapter.get_snapshot.return_value = UpstreamResponse(
        source="psx-dps",
        endpoint="snapshot",
        data={"rows": [{"symbol": "OGDC", "current": 136.0, "volume": 100}]},
        raw_sha256="s" * 64,
        record_count=1,
        duration_ms=20.0,
        status_code=200,
    )
    mock_adapter.get_indices.return_value = UpstreamResponse(
        source="psx-dps",
        endpoint="indices",
        data=[{"code": "KSE100", "current": 85000.0, "volume": 1000}],
        raw_sha256="i" * 64,
        record_count=1,
        duration_ms=20.0,
        status_code=200,
    )

    pipeline = CollectorPipeline(
        adapter=mock_adapter,
        coordinator=mock_coordinator,
        archive_manager=mock_archive,
        healthchecks=mock_hc,
    )

    # Let snapshot archive succeed, but mock index commit to fail
    orig_commit = mock_archive.commit_file_to_archive
    def commit_side_effect(rel_path, content_bytes, commit_message):
        if "indices" in rel_path:
            raise ArchiveCommitError("Remote GitHub API timed out committing indices shard")
        return orig_commit(rel_path, content_bytes, commit_message)

    with patch.object(mock_archive, "commit_file_to_archive", side_effect=commit_side_effect), \
         patch.object(mock_hc, "ping_fail") as mock_fail:

        res = pipeline.run(force=True, dry_run=False)

        assert res["status"] == "PARTIAL_ARCHIVE_FAILED"
        assert len(res["archivedFiles"]) == 1  # Snapshot was archived
        assert "snapshot" in res["archivedFiles"][0]
        assert "Remote GitHub API timed out" in res["error"]
        mock_fail.assert_called_once()


def test_durable_snapshot_deduplication_skips_duplicate_archive(tmp_path):
    """
    Proves Item 5: When identical observations arrive on the same trading day,
    the pipeline skips re-archiving duplicate objects and reports DATA_UNCHANGED.
    When a distinct observation arrives, it archives the new object and updates the recorded hash.
    """
    archive_dir = str(tmp_path / "archive")
    state_file = str(tmp_path / "state.json")

    mock_coordinator = PersistentCoordinator(token=None, local_state_file=state_file, daily_limit=250, require_remote=False)
    mock_archive = DurableArchiveManager(token=None, local_archive_dir=archive_dir, require_remote=False)
    mock_hc = HealthchecksNotifier(ping_url=None)

    mock_adapter = MagicMock()
    # Cycle 1: Snapshot hash '1111...'
    mock_adapter.get_snapshot.return_value = UpstreamResponse(
        source="psx-dps",
        endpoint="snapshot",
        data={"rows": [{"symbol": "SYS", "current": 450.0, "volume": 5000}]},
        raw_sha256="1" * 64,
        record_count=1,
        duration_ms=20.0,
        status_code=200,
    )
    mock_adapter.get_indices.return_value = UpstreamResponse(
        source="psx-dps",
        endpoint="indices",
        data=[],
        raw_sha256="0" * 64,
        record_count=0,
        duration_ms=10.0,
        status_code=200,
    )

    pipeline = CollectorPipeline(
        adapter=mock_adapter,
        coordinator=mock_coordinator,
        archive_manager=mock_archive,
        healthchecks=mock_hc,
    )

    with patch("collector.pipeline.MarketCalendar.get_market_session", return_value=("REGULAR_SESSION", True)):
        # Run 1: Distinct snapshot -> archived
        res1 = pipeline.run(force=False, dry_run=False)
        assert any("snapshot" in f for f in res1["archivedFiles"])
        assert mock_coordinator.get_last_snapshot_hash("psx-dps", res1["tradingDate"]) == "1" * 64

        # Run 2: Exact same snapshot hash -> skipped (no duplicate snapshot archived!)
        res2 = pipeline.run(force=False, dry_run=False)
        assert res2["status"] == "DATA_UNCHANGED"
        assert len(res2["archivedFiles"]) == 0

        # Run 3: Distinct new price -> archives new snapshot object and updates hash
        mock_adapter.get_snapshot.return_value = UpstreamResponse(
            source="psx-dps",
            endpoint="snapshot",
            data={"rows": [{"symbol": "SYS", "current": 455.0, "volume": 6000}]},
            raw_sha256="2" * 64,
            record_count=1,
            duration_ms=20.0,
            status_code=200,
        )
        res3 = pipeline.run(force=False, dry_run=False)
        assert any("snapshot" in f for f in res3["archivedFiles"])
        assert mock_coordinator.get_last_snapshot_hash("psx-dps", res3["tradingDate"]) == "2" * 64
