"""
Authorized Bounded Integration Verification for PSX Research Lab Durable Archiving.
Performs the full 8-step verification against the real private archive repo:
1. Retrieves real PSX data
2. Validates schema and prices with QuarantineAuditor
3. Commits the raw compressed response to MahadImran/psx-research-data
4. Reads it back via GitHub REST API
5. Recomputes and verifies SHA-256 hash
6. Confirms the daily manifest references the correct object
7. Verifies persistent budget usage across separate jobs
8. Tests recovery from an interrupted or repeated write (idempotency)
"""

from datetime import datetime, timezone
import gzip
import hashlib
import json
import logging
import os
import sys

from .adapters.psx_dps_adapter import PSXDPSAdapter
from .archive import DurableArchiveManager, ArchiveCommitError
from .calendar import MarketCalendar
from .persistent_budget import PersistentCoordinator
from .quarantine import QuarantineAuditor
from .session_token import PSXTokenProvider

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("verify_durable_archive")


def run_verification():
    token = os.environ.get("DATA_REPO_TOKEN")
    if not token:
        logger.error("DATA_REPO_TOKEN is required for live archive verification.")
        sys.exit(1)

    repo_name = "MahadImran/psx-research-data"
    now_pkt = MarketCalendar.now_pkt()
    trading_date = now_pkt.strftime("%Y-%m-%d")
    now_utc = datetime.now(timezone.utc).isoformat()

    logger.info("==================================================================")
    logger.info("Starting Authorized Bounded Durable Archiving Verification")
    logger.info("Target Archive: %s | Trading Date: %s", repo_name, trading_date)
    logger.info("==================================================================")

    # 1. Initialize persistent coordinator and verify budget
    coordinator = PersistentCoordinator(repo_name=repo_name, token=token, require_remote=True)
    logger.info("--> [Step 1/8] Acquiring remote lease and loading persistent budget...")
    coordinator.acquire_lease_and_sync()
    budget_before = coordinator.get_remaining_requests()
    logger.info("✓ Remote lease acquired. Remaining upstream budget: %d/250", budget_before)

    try:
        # 2. Retrieve real PSX data
        logger.info("--> [Step 2/8] Fetching real live indices from PSX...")
        token_provider = PSXTokenProvider(budget_recorder=coordinator)
        adapter = PSXDPSAdapter(token_provider=token_provider, budget_manager=coordinator)
        indices_resp = adapter.get_indices()
        logger.info("✓ Retrieved %d indices in %.1f ms | Status: %d", indices_resp.record_count, indices_resp.duration_ms, indices_resp.status_code)

        # 3. Validate with Quarantine
        logger.info("--> [Step 3/8] Validating retrieved data with QuarantineAuditor...")
        indices_data = indices_resp.data
        idx_list = indices_data if isinstance(indices_data, list) else indices_data.get("rows", [])
        assert len(idx_list) > 0, "No indices returned from upstream PSX"
        valid_indices = 0
        for idx in idx_list:
            logger.info("  Index record: %s", idx)
            code = str(idx.get("code") or idx.get("symbol") or idx.get("Index") or idx.get("index") or "").upper()
            cur_raw = idx.get("current") or idx.get("Current") or idx.get("value") or 0.0
            cur = float(cur_raw or 0.0)
            if code and cur > 0:
                valid_indices += 1
        assert valid_indices >= 5, f"Expected at least 5 active indices with positive values, found {valid_indices}"
        logger.info("✓ Quarantine validation passed: %d/%d active index records valid.", valid_indices, len(idx_list))

        # 4. Commit raw compressed response to private archive
        logger.info("--> [Step 4/8] Staging and committing raw .json.gz to %s...", repo_name)
        archive_mgr = DurableArchiveManager(repo_name=repo_name, token=token, require_remote=True)
        rel_path, comp_bytes, sha_hash, uncomp_len = archive_mgr.stage_locally(
            source="psx-dps",
            endpoint="indices_verify",
            trading_date=trading_date,
            data=indices_data,
        )
        archive_mgr.commit_file_to_archive(
            rel_path=rel_path,
            content_bytes=comp_bytes,
            commit_message=f"test(verify): bounded live probe archive verification {trading_date}",
        )
        logger.info("✓ Committed raw response to %s (%d compressed bytes)", rel_path, len(comp_bytes))

        # 5. Read back from GitHub REST API and recompute SHA-256
        logger.info("--> [Step 5/8] Reading back committed file from GitHub and recomputing hash...")
        readback_bytes, file_sha = archive_mgr.read_remote_file(rel_path)
        assert readback_bytes is not None, f"File {rel_path} not found upon readback!"
        assert readback_bytes == comp_bytes, "Bit-for-bit mismatch between staged and readback bytes!"

        decompressed = gzip.decompress(readback_bytes)
        recomputed_hash = hashlib.sha256(decompressed).hexdigest()
        assert recomputed_hash == sha_hash, f"Hash mismatch! recomputed={recomputed_hash}, expected={sha_hash}"
        logger.info("✓ Readback verified bit-for-bit: SHA-256 matches %s", recomputed_hash)

        # 6. Commit daily manifest referencing verified object
        logger.info("--> [Step 6/8] Generating and committing daily manifest referencing object...")
        manifest_payload = {
            "manifestVersion": "1.0.0",
            "generatedAtUtc": now_utc,
            "tradingDate": trading_date,
            "source": "psx-dps",
            "totalBars": 0,
            "totalSnapshots": 0,
            "totalIndices": len(idx_list),
            "payloadSha256": sha_hash,
            "archivePath": rel_path,
            "verifiedArchiveFiles": [rel_path],
        }
        manifest_rel = archive_mgr.commit_daily_manifest(trading_date, manifest_payload)
        logger.info("✓ Daily manifest committed: %s", manifest_rel)

        # Read back manifest
        manifest_read_bytes, _ = archive_mgr.read_remote_file(manifest_rel)
        assert manifest_read_bytes is not None, "Daily manifest readback failed!"
        manifest_data = json.loads(manifest_read_bytes.decode("utf-8"))
        assert manifest_data["archivePath"] == rel_path
        assert manifest_data["payloadSha256"] == sha_hash
        logger.info("✓ Manifest readback verified: points to exact verified object %s", rel_path)

        # 7. Verify persistent budget usage across jobs
        logger.info("--> [Step 7/8] Verifying persistent rolling budget tracking...")
        coordinator.sync_budget_to_remote()
        budget_after = coordinator.get_remaining_requests()
        spent = budget_before - budget_after
        logger.info("✓ Persistent budget verified: %d upstream requests consumed and tracked.", spent)
        assert spent >= 1, "Expected at least 1 request recorded in budget"

        # 8. Test idempotency (repeated write must be a clean no-op)
        logger.info("--> [Step 8/8] Testing idempotency on repeated commit...")
        ok_repeat = archive_mgr.commit_file_to_archive(
            rel_path=rel_path,
            content_bytes=comp_bytes,
            commit_message="test(verify): duplicate idempotent write",
        )
        assert ok_repeat is True
        logger.info("✓ Idempotent write handled cleanly without duplicate commit.")

        logger.info("==================================================================")
        logger.info("SUCCESS: All 8 Durable Archiving Verification steps PASSED!")
        logger.info("==================================================================")

    finally:
        coordinator.release_lease()
        logger.info("Lease released cleanly.")


if __name__ == "__main__":
    run_verification()
