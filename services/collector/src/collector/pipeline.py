"""
PSX Research Lab — Durable Collector Orchestration Pipeline.
Integrates MarketCalendar, Healthchecks, PersistentCoordinator,
PSXDPSAdapter, QuarantineAuditor, DurableArchiveManager, and IngestClient.
Runs cleanly within GitHub Actions Ubuntu runners.
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
from .archive import DurableArchiveManager
from .calendar import MarketCalendar
from .healthchecks import HealthchecksNotifier
from .ingest_client import IngestClient
from .persistent_budget import PersistentCoordinator, BudgetExceededError, LeaseConflictError
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
        self.token_provider = token_provider or PSXTokenProvider()
        self.adapter = adapter or PSXDPSAdapter(token_provider=self.token_provider)
        self.coordinator = coordinator or PersistentCoordinator()
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
        Returns execution telemetry dictionary.
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
                "status": "SKIPPED",
                "reason": reason,
                "tradingDate": trading_date,
            }

        # 2. Healthchecks start ping
        self.healthchecks.ping_start()

        # 3. Distributed lease acquisition & budget synchronization
        try:
            self.coordinator.acquire_lease_and_sync()
        except LeaseConflictError as e:
            logger.warning("Lease conflict detected: %s", e)
            self.healthchecks.ping_skip(str(e))
            return {
                "runId": run_id,
                "status": "SKIPPED_LEASE_CONFLICT",
                "reason": str(e),
            }

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

            # 4. Ingest and Archival Data Structures
            ingest_bars: List[Dict[str, Any]] = []
            ingest_snapshot: Optional[Dict[str, Any]] = None
            ingest_indices: List[Dict[str, Any]] = []
            archived_files: List[str] = []

            # 5. Market-wide Snapshot Extraction
            logger.info("Fetching market-wide snapshot from PSX...")
            self.coordinator.record_request("snapshot")
            snapshot_resp = self.adapter.get_snapshot()

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

            if observations:
                ingest_snapshot = {
                    "source": "psx-dps",
                    "batchId": batch_id,
                    "tradingDate": trading_date,
                    "fetchedAtUtc": now_utc,
                    "totalSymbols": len(observations),
                    "observations": observations,
                    "rawSha256": snapshot_sha256,
                }

                # Stage and archive compressed raw response
                if not dry_run:
                    rel_path, comp_bytes, sha_hash, _ = self.archive_manager.stage_locally(
                        source="psx-dps",
                        endpoint="snapshot",
                        trading_date=trading_date,
                        data=snapshot_data,
                    )
                    archived_files.append(rel_path)
                    try:
                        self.archive_manager.commit_file_to_archive(
                            rel_path=rel_path,
                            content_bytes=comp_bytes,
                            commit_message=f"data(snapshot): {trading_date} batch {batch_id[:8]}",
                        )
                    except Exception as e:
                        logger.warning("Could not commit snapshot to remote archive: %s", e)

            # 6. Active Indices Extraction
            if self.coordinator.get_remaining_requests() > 2:
                logger.info("Fetching active market indices...")
                self.coordinator.record_request("indices")
                indices_resp = self.adapter.get_indices()
                indices_data = indices_resp.data

                # Normalise indices
                idx_list = indices_data if isinstance(indices_data, list) else indices_data.get("rows", [])
                for idx in idx_list:
                    code = str(idx.get("code") or idx.get("symbol") or idx.get("index") or "").upper()
                    cur = float(idx.get("current", 0.0) or idx.get("value", 0.0) or 0.0)
                    if code and cur > 0:
                        ingest_indices.append({
                            "code": code,
                            "current": cur,
                            "change": float(idx.get("change", 0.0) or 0.0),
                            "changePercent": float(idx.get("percentChange", 0.0) or 0.0),
                            "volume": int(idx.get("volume", 0) or 0),
                            "tradingDate": trading_date,
                            "fetchedAtUtc": now_utc,
                        })

                if not dry_run and idx_list:
                    rel_path, comp_bytes, _, _ = self.archive_manager.stage_locally(
                        source="psx-dps",
                        endpoint="indices",
                        trading_date=trading_date,
                        data=indices_data,
                    )
                    archived_files.append(rel_path)
                    try:
                        self.archive_manager.commit_file_to_archive(
                            rel_path=rel_path,
                            content_bytes=comp_bytes,
                            commit_message=f"data(indices): {trading_date}",
                        )
                    except Exception as e:
                        logger.warning("Could not commit indices to remote archive: %s", e)

            # 7. EOD Settlement Reconciliation (during post-close window or if force_eod)
            reconciliation_summary: Optional[Dict[str, Any]] = None
            is_post_close = "post_close" in reason.lower() or force_eod
            if is_post_close and self.coordinator.get_remaining_requests() > 2:
                logger.info("Running EOD Settlement Reconciliation for %s...", trading_date)
                self.coordinator.record_request(f"history_date/{trading_date}")
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
                        archived_files.append(rel_path)
                        try:
                            self.archive_manager.commit_file_to_archive(
                                rel_path=rel_path,
                                content_bytes=comp_bytes,
                                commit_message=f"data(eod): {trading_date} official settlement",
                            )
                        except Exception as e:
                            logger.warning("Could not commit EOD to remote archive: %s", e)
                except Exception as e:
                    logger.warning("EOD reconciliation fetch failed: %s", e)

            # 8. Create and Commit Daily Manifest
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
            }

            if not dry_run:
                try:
                    self.archive_manager.commit_daily_manifest(trading_date, manifest_payload)
                except Exception as e:
                    logger.warning("Could not commit daily manifest: %s", e)

            # 9. Ingest to Cloudflare API
            ingest_payload = {
                "manifest": manifest_payload,
                "bars": ingest_bars,
                "snapshot": ingest_snapshot,
                "indices": ingest_indices,
                "collectorRunId": run_id,
                "timestamp": int(datetime.now(timezone.utc).timestamp()),
                "nonce": uuid.uuid4().hex,
            }

            ingest_success = False
            if not dry_run and (ingest_bars or ingest_snapshot or ingest_indices):
                ingest_success, status_code, resp_body = self.ingest_client.send_ingestion(ingest_payload)
                logger.info("Ingest API result: %s (status %d)", ingest_success, status_code)

            # 10. Healthchecks Success Heartbeat
            remaining_after = self.coordinator.get_remaining_requests()
            summary_msg = (
                f"OK {trading_date} [{run_id}]: "
                f"snapshot_symbols={len(observations)}, "
                f"indices={len(ingest_indices)}, "
                f"reconciled_bars={len(ingest_bars)}, "
                f"remaining_requests={remaining_after}/250"
            )
            self.healthchecks.ping_success(summary_msg)

            return {
                "runId": run_id,
                "status": "SUCCESS",
                "tradingDate": trading_date,
                "snapshotSymbolsCount": len(observations),
                "indicesCount": len(ingest_indices),
                "reconciledBarsCount": len(ingest_bars),
                "reconciliation": reconciliation_summary,
                "archivedFiles": archived_files,
                "remainingBudget": remaining_after,
                "ingestSuccess": ingest_success,
            }

        except Exception as e:
            logger.exception("Collector execution failed: %s", e)
            self.healthchecks.ping_fail(f"Collector error [{run_id}]: {e}")
            raise
        finally:
            # Always cleanly release distributed lease
            try:
                self.coordinator.release_lease()
            except Exception as e:
                logger.warning("Failed to release lease: %s", e)
