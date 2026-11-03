"""
PSX Research Lab — Durable Collector Orchestration Pipeline.
Integrates MarketCalendar, Healthchecks, PersistentCoordinator,
PSXDPSAdapter, QuarantineAuditor, DurableArchiveManager, and IngestClient.
Fails closed: never swallows archive or persistence errors.
"""

from datetime import datetime, timezone
import hashlib
import json
import logging
import os
import sys
import uuid
from typing import Any, Dict, List, Optional

from .adapters.psx_dps_adapter import PSXDPSAdapter
from .archive import DurableArchiveManager, ArchiveCommitError, ArchiveCredentialsError
from .calendar import MarketCalendar
from .healthchecks import HealthchecksNotifier
from .ingest_client import IngestClient
from .persistent_budget import (
    PersistentCoordinator,
    BudgetExceededError,
    LeaseConflictError,
    RemoteStateError,
)
from .quarantine import QuarantineAuditor
from .reconciliation import EODReconciler
from .session_token import PSXTokenProvider

logger = logging.getLogger(__name__)


class CollectorPipeline:
    def __init__(
        self,
        adapter: Optional[PSXDPSAdapter] = None,
        coordinator: Optional[PersistentCoordinator] = None,
        archive_manager: Optional[DurableArchiveManager] = None,
        healthchecks: Optional[HealthchecksNotifier] = None,
        ingest_client: Optional[IngestClient] = None,
        reconciler: Optional[EODReconciler] = None,
        token_provider: Optional[PSXTokenProvider] = None,
    ):
        self.coordinator = coordinator or PersistentCoordinator()
        self.token_provider = token_provider or PSXTokenProvider(budget_recorder=self.coordinator)
        self.adapter = adapter or PSXDPSAdapter(
            token_provider=self.token_provider,
            budget_manager=self.coordinator,
        )
        # Ensure transport uses persistent coordinator for all low-level calls
        if hasattr(self.adapter, "client") and hasattr(self.adapter.client, "transport"):
            self.adapter.client.transport.budget_recorder = self.coordinator

        self.archive_manager = archive_manager or DurableArchiveManager()
        self.healthchecks = healthchecks or HealthchecksNotifier()
        self.ingest_client = ingest_client or IngestClient()
        self.reconciler = reconciler or EODReconciler(source_name="psx-dps")

    def run(
        self,
        force: bool = False,
        force_eod: bool = False,
        dry_run: bool = False,
    ) -> Dict[str, Any]:
        """
        Executes a single scheduled collector cycle.
        Returns execution telemetry dictionary with precise status semantics:
        - FULLY_SUCCESSFUL_CYCLE
        - ARCHIVE_COMMITTED_INGEST_PENDING
        - DATA_UNCHANGED
        - ARCHIVE_FAILED
        - INGEST_FAILED
        - SOURCE_UNAVAILABLE
        - MARKET_CLOSED
        - SKIPPED_LEASE_CONFLICT
        - BUDGET_EXHAUSTED
        """
        run_id = f"run-{uuid.uuid4().hex[:12]}"
        now_pkt = MarketCalendar.now_pkt()
        trading_date = now_pkt.strftime("%Y-%m-%d")
        now_utc = datetime.now(timezone.utc).isoformat()

        logger.info("Starting collector cycle %s for %s (%s PKT)", run_id, trading_date, now_pkt.strftime("%H:%M:%S"))

        # 1. Calendar validation
        should_run, reason = MarketCalendar.should_scheduled_collector_run()
        if not should_run and not force:
            logger.info("Collector skipped: %s", reason)
            self.healthchecks.ping_skip(reason)
            return {
                "runId": run_id,
                "status": "MARKET_CLOSED",
                "reason": reason,
                "tradingDate": trading_date,
            }

        # 2. Healthchecks start ping
        self.healthchecks.ping_start()

        # 3. Distributed lease acquisition & persistent budget sync (fails closed on remote errors)
        try:
            self.coordinator.acquire_lease_and_sync()
        except LeaseConflictError as e:
            logger.warning("Lease conflict detected: %s", e)
            self.healthchecks.ping_skip(f"Lease conflict: {e}")
            return {
                "runId": run_id,
                "status": "SKIPPED_LEASE_CONFLICT",
                "reason": str(e),
            }
        except RemoteStateError as e:
            logger.error("Remote coordination state failed: %s", e)
            self.healthchecks.ping_fail(f"Remote state error: {e}")
            raise

        try:
            remaining_budget = self.coordinator.get_remaining_requests()
            if remaining_budget < 3:
                msg = f"Insufficient 24h budget fuse remaining: {remaining_budget}/250"
                logger.error(msg)
                self.healthchecks.ping_fail(msg)
                return {
                    "runId": run_id,
                    "status": "BUDGET_EXHAUSTED",
                    "remainingBudget": remaining_budget,
                }

            # 4. Ingestion & Archive Data Structures
            ingest_bars: List[Dict[str, Any]] = []
            ingest_snapshot: Optional[Dict[str, Any]] = None
            ingest_indices: List[Dict[str, Any]] = []
            archived_files: List[str] = []

            # 5. Market-wide Snapshot Extraction
            logger.info("Fetching market-wide snapshot from PSX...")
            try:
                snapshot_resp = self.adapter.get_snapshot()
            except Exception as e:
                logger.error("PSX snapshot fetch failed: %s", e)
                self.healthchecks.ping_fail(f"PSX snapshot failure: {e}")
                return {
                    "runId": run_id,
                    "status": "SOURCE_UNAVAILABLE",
                    "error": str(e),
                }

            snapshot_data = snapshot_resp.data
            raw_rows = snapshot_data.get("rows", [])
            observations: List[Dict[str, Any]] = []

            for row in raw_rows:
                sym = str(row.get("symbol", "")).upper()
                cur = float(row.get("current", 0.0) or 0.0)
                chg = float(row.get("change", 0.0) or 0.0)
                pct = float(row.get("percentChange", 0.0) or 0.0)
                vol = int(row.get("volume", 0) or 0)
                if sym and cur > 0:
                    observations.append({
                        "symbol": sym,
                        "current": cur,
                        "change": chg,
                        "changePercent": pct,
                        "volume": vol,
                        "high": float(row.get("high")) if row.get("high") is not None else None,
                        "low": float(row.get("low")) if row.get("low") is not None else None,
                    })

            snapshot_sha256 = snapshot_resp.raw_sha256
            batch_id = str(uuid.uuid4())

            # 6. Durable, source-specific, trading-date-aware deduplication check
            last_snapshot_hash = self.coordinator.get_last_snapshot_hash("psx-dps", trading_date)
            is_duplicate = (last_snapshot_hash == snapshot_sha256) and not force
            if is_duplicate:
                logger.info("Data unchanged since last poll for %s on %s (SHA-256 identical).", "psx-dps", trading_date)

            if observations and not is_duplicate:
                ingest_snapshot = {
                    "source": "psx-dps",
                    "batchId": batch_id,
                    "tradingDate": trading_date,
                    "fetchedAtUtc": now_utc,
                    "totalSymbols": len(observations),
                    "observations": observations,
                    "rawSha256": snapshot_sha256,
                }

                # Stage locally and commit to private archive (with readback verification)
                if not dry_run:
                    rel_path, comp_bytes, sha_hash, _ = self.archive_manager.stage_locally(
                        source="psx-dps",
                        endpoint="snapshot",
                        trading_date=trading_date,
                        data=snapshot_data,
                    )
                    # Must fail closed if remote archive commit fails
                    try:
                        self.archive_manager.commit_file_to_archive(
                            rel_path=rel_path,
                            content_bytes=comp_bytes,
                            commit_message=f"data(snapshot): {trading_date} batch {batch_id[:8]}",
                        )
                        archived_files.append(rel_path)
                        # Record durable snapshot hash in coordinator state
                        self.coordinator.record_snapshot_hash("psx-dps", trading_date, snapshot_sha256)
                    except (ArchiveCommitError, ArchiveCredentialsError) as e:
                        logger.error("Durable archive failure while saving snapshot: %s", e)
                        self.healthchecks.ping_fail(f"Archive failure for snapshot: {e}")
                        return {
                            "runId": run_id,
                            "status": "ARCHIVE_FAILED",
                            "error": str(e),
                            "archivedFiles": archived_files,
                            "tradingDate": trading_date,
                        }

            # 7. Active Indices Extraction (Distinct fetch vs archive failure boundaries)
            indices_data = None
            if self.coordinator.get_remaining_requests() > 2:
                logger.info("Fetching active market indices...")
                try:
                    indices_resp = self.adapter.get_indices()
                    indices_data = indices_resp.data
                except Exception as e:
                    logger.warning("Optional indices fetch failed (non-fatal): %s", e)
                    indices_data = None

            if indices_data is not None:
                idx_list = indices_data if isinstance(indices_data, list) else indices_data.get("rows", [])
                for idx in idx_list:
                    code = str(idx.get("code") or idx.get("symbol") or idx.get("Index") or idx.get("index") or "").upper()
                    cur_raw = idx.get("current") or idx.get("Current") or idx.get("value") or 0.0
                    cur = float(cur_raw or 0.0)
                    if code and cur > 0:
                        ingest_indices.append({
                            "code": code,
                            "current": cur,
                            "change": float(idx.get("change") or idx.get("Change") or 0.0),
                            "changePercent": float(idx.get("percentChange") or idx.get("% Change") or 0.0),
                            "volume": int(float(idx.get("volume") or idx.get("Volume") or 0)),
                            "tradingDate": trading_date,
                            "fetchedAtUtc": now_utc,
                        })

                if not dry_run and idx_list and not is_duplicate:
                    rel_path, comp_bytes, _, _ = self.archive_manager.stage_locally(
                        source="psx-dps",
                        endpoint="indices",
                        trading_date=trading_date,
                        data=indices_data,
                    )
                    try:
                        self.archive_manager.commit_file_to_archive(
                            rel_path=rel_path,
                            content_bytes=comp_bytes,
                            commit_message=f"data(indices): {trading_date}",
                        )
                        archived_files.append(rel_path)
                    except (ArchiveCommitError, ArchiveCredentialsError) as e:
                        logger.error("Durable archive failure while saving indices: %s", e)
                        msg = f"Archive failure for indices: {e}"
                        self.healthchecks.ping_fail(msg)
                        return {
                            "runId": run_id,
                            "status": "PARTIAL_ARCHIVE_FAILED",
                            "error": str(e),
                            "archivedFiles": archived_files,
                            "tradingDate": trading_date,
                        }

            # 8. EOD Settlement Reconciliation (during post-close window or if force_eod)
            reconciliation_summary: Optional[Dict[str, Any]] = None
            is_post_close = "post_close" in reason.lower() or force_eod
            if is_post_close and self.coordinator.get_remaining_requests() > 2:
                logger.info("Running EOD Settlement Reconciliation for %s...", trading_date)
                try:
                    eod_resp = self.adapter.get_historical_date(trading_date)
                    eod_records = eod_resp.data if isinstance(eod_resp.data, list) else eod_resp.data.get("rows", [])
                    reconciliation_summary = self.reconciler.reconcile_trading_day(
                        trading_date=trading_date,
                        official_records=eod_records,
                        preliminary_snapshots=observations,
                    )
                    ingest_bars = reconciliation_summary.get("bars", [])

                    if not dry_run and eod_records:
                        rel_path, comp_bytes, _, _ = self.archive_manager.stage_locally(
                            source="psx-dps",
                            endpoint="historical_date",
                            trading_date=trading_date,
                            data=eod_resp.data,
                        )
                        self.archive_manager.commit_file_to_archive(
                            rel_path=rel_path,
                            content_bytes=comp_bytes,
                            commit_message=f"data(eod): {trading_date} official settlement",
                        )
                        archived_files.append(rel_path)
                except Exception as e:
                    logger.error("EOD reconciliation failed: %s", e)
                    self.healthchecks.ping_fail(f"EOD reconciliation error: {e}")
                    raise

            # 9. Create and Commit Daily Manifest (ONLY referencing successfully verified files)
            manifest_payload = {
                "manifestVersion": "1.0.0",
                "generatedAtUtc": now_utc,
                "tradingDate": trading_date,
                "source": "psx-dps",
                "totalBars": len(ingest_bars),
                "totalSnapshots": len(observations),
                "totalIndices": len(ingest_indices),
                "payloadSha256": snapshot_sha256,
                "archivePath": archived_files[0] if archived_files else None,
                "verifiedArchiveFiles": archived_files,
            }

            if not dry_run and archived_files:
                try:
                    self.archive_manager.commit_daily_manifest(trading_date, manifest_payload)
                except (ArchiveCommitError, ArchiveCredentialsError) as e:
                    logger.error("Durable daily manifest commit failed: %s", e)
                    self.healthchecks.ping_fail(f"Daily manifest commit failure: {e}")
                    return {
                        "runId": run_id,
                        "status": "ARCHIVE_FAILED",
                        "error": str(e),
                        "archivedFiles": archived_files,
                        "tradingDate": trading_date,
                    }

            # 10. Ingest to Cloudflare API (if API configured and reachable)
            ingest_payload = {
                "manifest": manifest_payload,
                "bars": ingest_bars,
                "snapshot": ingest_snapshot,
                "indices": ingest_indices,
                "collectorRunId": run_id,
                "timestamp": int(datetime.now(timezone.utc).timestamp()),
                "nonce": uuid.uuid4().hex,
            }

            ingest_status = "PENDING"
            if not dry_run and (ingest_bars or ingest_snapshot or ingest_indices):
                if self.ingest_client.api_url and self.ingest_client.api_url.startswith("http"):
                    ok, code, resp_data = self.ingest_client.send_ingestion(ingest_payload)
                    if ok:
                        ingest_status = "ACCEPTED"
                    else:
                        ingest_status = "FAILED"
                        logger.error("Cloudflare Ingestion API failed (HTTP %d): %s", code, resp_data)
                        self.healthchecks.ping_fail(f"Cloudflare Ingest HTTP {code}: {resp_data.get('reason', 'Failed')}")
                        return {
                            "runId": run_id,
                            "status": "INGEST_FAILED",
                            "httpStatus": code,
                            "archivedFiles": archived_files,
                            "remainingBudget": self.coordinator.get_remaining_requests(),
                        }
                else:
                    ingest_status = "NOT_CONFIGURED"

            # 11. Final Status Determination & Healthchecks Notification
            final_status = "FULLY_SUCCESSFUL_CYCLE"
            if is_duplicate:
                final_status = "DATA_UNCHANGED"
            elif ingest_status in ("NOT_CONFIGURED", "PENDING"):
                final_status = "ARCHIVE_COMMITTED_INGEST_PENDING"

            remaining_after = self.coordinator.get_remaining_requests()
            summary_msg = (
                f"{final_status} {trading_date} [{run_id}]: "
                f"symbols={len(observations)}, "
                f"indices={len(ingest_indices)}, "
                f"bars={len(ingest_bars)}, "
                f"archived={len(archived_files)}, "
                f"budget_remaining={remaining_after}/250"
            )
            self.healthchecks.ping_success(summary_msg)

            return {
                "runId": run_id,
                "status": final_status,
                "tradingDate": trading_date,
                "snapshotSymbolsCount": len(observations),
                "indicesCount": len(ingest_indices),
                "reconciledBarsCount": len(ingest_bars),
                "reconciliation": reconciliation_summary,
                "archivedFiles": archived_files,
                "remainingBudget": remaining_after,
                "ingestStatus": ingest_status,
            }

        except (ArchiveCommitError, ArchiveCredentialsError) as e:
            logger.error("Durable archive failure: %s", e)
            self.healthchecks.ping_fail(f"Archive failure [{run_id}]: {e}")
            return {
                "runId": run_id,
                "status": "ARCHIVE_FAILED",
                "error": str(e),
                "remainingBudget": self.coordinator.get_remaining_requests(),
            }
        except Exception as e:
            logger.exception("Collector execution failed: %s", e)
            self.healthchecks.ping_fail(f"Collector error [{run_id}]: {e}")
            raise
        finally:
            # Sync persistent budget and release lease
            try:
                self.coordinator.release_lease()
            except Exception as e:
                logger.warning("Failed to release lease cleanly: %s", e)
