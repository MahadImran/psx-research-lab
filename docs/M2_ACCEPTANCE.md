# Milestone 2 (M2) Acceptance & Verification Document

**Milestone:** M2 — Persistent Request Budget, Distributed Lease, Durable Archiving, & Fail-Closed Remediation  
**Status:** AWAITING OWNER ACCEPTANCE  
**Verification Date:** 2026-11-03  
**Sign-off Criteria:** Zero fail-open behavior in CI/production, remote state optimistic concurrency, pre-reservation request accounting surviving runner crashes, cumulative daily manifests, raw archive immutability, readback verification of committed blobs, durable snapshot deduplication, and multi-tier operational status reporting.

---

## 1. M2 Scope & Objectives

Milestone 2 hardens the data persistence, concurrency, and reliability layers:
- Cross-run distributed lease coordination eliminating split-brain execution across GitHub runners.
- Durable quota pre-reservation committed to remote storage before physical socket connections.
- Raw payload archiving into date-sharded compressed gzip files (`raw/YYYY/MM/DD/*.json.gz`).
- Raw archive immutability: attempting to overwrite existing raw files with differing content fails closed.
- Idempotent commits: repeated writes of identical content succeed cleanly without creating duplicate revisions.
- Cumulative daily manifests aggregating verified files and cycle history (guaranteeing Cycle 1 is recorded).
- Corrupt manifest quarantine: malformed manifests fail closed and preserve corrupted bytes for forensics.
- Cryptographic readback verification after every remote commit (with bounded replica lag retry).
- Durable snapshot deduplication: tracking `{source}:{trading_date}` SHA-256 hashes to prevent redundant archives.
- Strict multi-tier lifecycle statuses eliminating false-positive monitoring alerts.

---

## 2. Requirement Verification Matrix

| Requirement | Specification Contract | Implementation Artifact | Status | Verification Evidence |
| :--- | :--- | :--- | :--- | :--- |
| **Fail-Closed Budgeting** | Missing tokens or remote errors must abort immediately in CI. | `collector/persistent_budget.py` | **VERIFIED** | Unit test `test_persistent_coordinator_fails_closed_in_ci_without_token` passed. |
| **Durable Pre-Reservation** | Quota reserved remotely before socket request; survives crashes. | `PersistentCoordinator.reserve_request()` | **VERIFIED** | Chaos test `test_crash_between_quota_reservation_and_network_request` passed. |
| **Optimistic Concurrency** | HTTP 409 conflict handling with jittered backoff. | `PersistentCoordinator.save_remote_state()` | **VERIFIED** | Unit test `test_persistent_coordinator_optimistic_concurrency_retry` passed. |
| **Non-Clobbering Lease Release** | Lease release preserves competitor leases and merges request logs. | `PersistentCoordinator.release_lease()` | **VERIFIED** | Unit test `test_lease_release_does_not_clobber_competitor_lease_or_requests` passed. |
| **Durable Archival** | Raw payloads stored compressed in private repository. | `collector/archive.py` | **VERIFIED** | Live Run `41687650867` committed compressed shards to `MahadImran/psx-research-data`. |
| **Raw Object Immutability** | Overwriting existing raw archive object with different bytes is rejected. | `DurableArchiveManager._commit_file()` | **VERIFIED** | Live Run `41687650867` Step 8 rejected tampered overwrite with `ArchiveCommitError`. |
| **Idempotent Re-Commit** | Repeated write of identical content succeeds cleanly. | `DurableArchiveManager._commit_file()` | **VERIFIED** | Live Run `41687650867` Step 9 handled identical rewrite cleanly without duplicate commit. |
| **Cumulative Manifests** | Daily manifest merges files across all daily poll cycles without data loss; Cycle 1 recorded. | `DurableArchiveManager.commit_daily_manifest()` | **VERIFIED** | Unit tests `test_archive_manager_cumulative_manifest_merging` and `test_same_day_collection_collision_preserves_all_files` passed. |
| **Corrupt Manifest Fail-Closed** | Corrupt remote manifest fails closed and isolates corrupt file. | `DurableArchiveManager.commit_daily_manifest()` | **VERIFIED** | Unit test `test_archive_manager_corrupted_manifest_fails_closed_and_preserves_file` passed. |
| **Readback Verification** | Remote commits validated by immediate GET and SHA-256 check. | `DurableArchiveManager._commit_file()` | **VERIFIED** | Live Run `41687650867` Step 6 verified indices and snapshot blobs bit-for-bit against remote GET. |
| **Durable Snapshot Deduplication** | Unchanged market snapshots skip duplicate archive writes. | `PersistentCoordinator.get_last_snapshot_hash()`, `pipeline.py` | **VERIFIED** | Unit test `test_durable_snapshot_deduplication_skips_duplicate_archive` passed. |
| **Granular Status Reporting** | Distinguish full success, unchanged data, archive committed, and failures. | `collector/pipeline.py` | **VERIFIED** | Runner Run `41386086661` returned `MARKET_CLOSED` with zero false-positive alerts. |

---

## 3. Engineering Evidence & Runner Artifacts

### 3.1 Live Verification on GitHub Runner
- **Run ID:** `41687650867`
- **Job ID:** `126097554138`
- **Workflow:** `Bounded Durable Archive Verification` (`.github/workflows/verify_durable_archive.yml`)
- **Execution Timestamp:** `2026-11-03T17:47:43Z` – `2026-11-03T17:48:21Z` (Duration: 41s)
- **Runner Environment:** Ubuntu 24.04 LTS (East US / North Central US Azure)
- **Target Repository:** `MahadImran/psx-research-data` (Private)
- **Exact Runner Log Output (10 of 10 Steps Verified):**
  ```text
  2026-11-03 17:47:52,704 [INFO] Starting Authorized Bounded Durable Archiving & Snapshot Verification
  2026-11-03 17:47:52,704 [INFO] Target Archive: MahadImran/psx-research-data | Trading Date: 2026-11-03
  2026-11-03 17:47:52,704 [INFO] ==================================================================
  2026-11-03 17:47:52,704 [INFO] --> [Step 1/10] Acquiring remote lease and loading persistent budget...
  2026-11-03 17:47:54,213 [INFO] Lease acquired successfully for runner gha-41687650867 until 2026-11-03T17:52:53.001250+00:00
  2026-11-03 17:47:54,213 [INFO] ✓ Remote lease acquired. Remaining upstream budget: 250/250
  2026-11-03 17:47:54,214 [INFO] --> [Step 2/10] Fetching real live indices from PSX DPS...
  2026-11-03 17:48:06,241 [INFO] ✓ Retrieved 18 indices in 10538.1 ms | Status: 200
  2026-11-03 17:48:06,241 [INFO] --> [Step 3/10] Fetching real live whole-market stock snapshot from PSX DPS...
  2026-11-03 17:48:11,413 [INFO] ✓ Retrieved 500 market-wide symbols in 3628.5 ms | Status: 200
  2026-11-03 17:48:11,413 [INFO] --> [Step 4/10] Validating data quality & geometric invariants...
  2026-11-03 17:48:11,413 [INFO]   ✓ Indices validated: 18/18 valid records
  2026-11-03 17:48:11,413 [INFO]   ✓ Stock snapshot validated: 500/500 valid active stocks
  2026-11-03 17:48:11,413 [INFO] --> [Step 5/10] Staging and committing raw .json.gz shards to MahadImran/psx-research-data...
  2026-11-03 17:48:13,262 [INFO] Durable archive committed and verified: raw/2026/11/03/psx-dps_indices_live_174811Z_0bfac25a.json.gz (914 bytes)
  2026-11-03 17:48:13,262 [INFO]   ✓ Committed indices shard to raw/2026/11/03/psx-dps_indices_live_174811Z_0bfac25a.json.gz (914 bytes)
  2026-11-03 17:48:15,207 [INFO] Durable archive committed and verified: raw/2026/11/03/psx-dps_market_snapshot_live_174813Z_58af8a39.json.gz (19562 bytes)
  2026-11-03 17:48:15,207 [INFO]   ✓ Committed snapshot shard to raw/2026/11/03/psx-dps_market_snapshot_live_174813Z_58af8a39.json.gz (19562 bytes)
  2026-11-03 17:48:15,207 [INFO] --> [Step 6/10] Reading back committed files from GitHub and recomputing hashes...
  2026-11-03 17:48:15,434 [INFO]   ✓ Verified raw/2026/11/03/psx-dps_indices_live_174811Z_0bfac25a.json.gz: SHA-256 matches 0bfac25a274d2bae4e3380c2d8c0f213f430c2f4068bfbd760525a589682f50f
  2026-11-03 17:48:15,699 [INFO]   ✓ Verified raw/2026/11/03/psx-dps_market_snapshot_live_174813Z_58af8a39.json.gz: SHA-256 matches 58af8a3953c05b4556530ae6ddf5e96cd4fb453565589fe2e61049265fe51288
  2026-11-03 17:48:15,699 [INFO] --> [Step 7/10] Committing daily cumulative manifest...
  2026-11-03 17:48:18,231 [INFO] ✓ Daily cumulative manifest committed: manifests/2026-11-03.json
  2026-11-03 17:48:18,459 [INFO] ✓ Manifest readback verified: cumulative files=2, cycles=1
  2026-11-03 17:48:18,459 [INFO] --> [Step 8/10] Testing raw archive immutability protection...
  2026-11-03 17:48:18,760 [INFO] ✓ Immutability protection verified: rejected overwrite (Immutability violation: raw archive object raw/2026/11/03/psx-dps_market_snapshot_live_174813Z_58af8a39.json.gz already exists with differing content (19562 bytes existing vs 38 bytes incoming). Raw archive objects are strictly immutable and cannot be overwritten.)
  2026-11-03 17:48:18,760 [INFO] --> [Step 9/10] Testing idempotency on repeated commit of identical bytes...
  2026-11-03 17:48:19,020 [INFO] File already durably archived with identical content: raw/2026/11/03/psx-dps_market_snapshot_live_174813Z_58af8a39.json.gz
  2026-11-03 17:48:19,021 [INFO] ✓ Idempotent write handled cleanly without duplicate revision.
  2026-11-03 17:48:19,021 [INFO] --> [Step 10/10] Verifying persistent budget pre-reservation tracking...
  2026-11-03 17:48:20,140 [INFO] ✓ Persistent budget verified: 6 requests tracked remotely (remaining: 244/250)
  2026-11-03 17:48:20,140 [INFO] ==================================================================
  2026-11-03 17:48:20,140 [INFO] SUCCESS: All 10 Bounded Durable Archiving & Live Market Steps PASSED!
  2026-11-03 17:48:20,140 [INFO] ==================================================================
  2026-11-03 17:48:21,537 [INFO] Lease cleanly released and history merged for runner gha-41687650867
  2026-11-03 17:48:21,538 [INFO] Lease cleanly released.
  ```

### 3.2 Automated Test Coverage for M2
- **Python Collector Suite (71 / 71 passed):**
  - `test_persistent_budget.py` (9 tests passed):
    - `test_persistent_coordinator_lease_lifecycle`: PASS
    - `test_persistent_coordinator_budget_fuse_enforcement`: PASS
    - `test_persistent_coordinator_fails_closed_in_ci_without_token`: PASS
    - `test_persistent_coordinator_fails_closed_when_repo_inaccessible`: PASS
    - `test_persistent_coordinator_optimistic_concurrency_retry`: PASS
    - `test_pre_reservation_commits_before_request_and_survives_crash`: PASS
    - `test_reserve_request_fails_closed_when_lease_expired`: PASS
    - `test_lease_release_does_not_clobber_competitor_lease_or_requests`: PASS
    - `test_lease_renewal_lifecycle`: PASS
  - `test_archive.py` (8 tests passed):
    - `test_archive_manager_stages_sharded_gzip`: PASS
    - `test_archive_manager_fails_closed_in_production_without_token`: PASS
    - `test_archive_manager_commits_with_readback_verification`: PASS
    - `test_archive_manager_readback_hash_mismatch_raises`: PASS
    - `test_archive_manager_idempotent_existing_file`: PASS
    - `test_archive_manager_cumulative_manifest_merging`: PASS
    - `test_archive_manager_immutability_violation_raises`: PASS
    - `test_archive_manager_corrupted_manifest_fails_closed_and_preserves_file`: PASS
  - `test_adversarial_failures.py` (8 chaos tests passed):
    - `test_concurrent_runners_racing_for_lease_fails_loser_closed`: PASS
    - `test_crash_between_quota_reservation_and_network_request`: PASS
    - `test_same_day_collection_collision_preserves_all_files`: PASS
    - `test_readback_bit_flip_triggers_controlled_archive_failure`: PASS
    - `test_malformed_html_table_parsing_resilience`: PASS
    - `test_stale_or_expired_lease_stealing_is_clean`: PASS
    - `test_false_positive_heartbeat_prevention`: PASS
    - `test_budget_exhaustion_stops_all_outbound_requests`: PASS
  - `test_pipeline.py` (9 tests passed, including `test_durable_snapshot_deduplication_skips_duplicate_archive`): PASS
- **TypeScript Workspace Suite (19 / 19 passed):**
  - Edge auth, fail-closed Cloudflare Access, D1 atomic nonces, and two-phase staging validation: PASS

---

## 4. Market Data Coverage Classification Matrix

| Data Stream / Capability | Coverage Status | Evidence & Rationale |
| :--- | :--- | :--- |
| **Market Benchmark Indices** | **PASS** | 18 live indices retrieved from PSX DPS and archived; verified on GitHub runners `41386016819` and `41687650867`. |
| **Whole-Market Stock Snapshot** | **PASS** | 500 active equity symbols retrieved via `/market-watch` and archived; verified on runner `41687650867`. |
| **Historical Daily EOD Bars** | **PARTIAL** | Upstream adapter and parsing verified with fixtures and probe workflow (`probe.yml`); full multi-year archive backfill deferred to Milestone 3 to honor the 250 requests/day budget ceiling. |
| **Full-Session Intraday Stream** | **PARTIAL / DEFERRED** | Intraday snapshot schema, deduplication, and quarantine verified; scheduled polling during market sessions is deferred to Milestone 3 when scheduled cron is enabled. |

---

## 5. Milestone 2 Acceptance Status

**Status: AWAITING OWNER ACCEPTANCE**  
Milestone 2 satisfies all remediation requirements set forth in the M2 Acceptance Review. Concurrency is provably atomic, budget accounting is crash-safe, and raw market data is durably preserved. Awaiting owner review and formal acceptance.
