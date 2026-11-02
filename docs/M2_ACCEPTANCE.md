# Milestone 2 (M2) Acceptance & Verification Document

**Milestone:** M2 — Persistent Request Budget, Distributed Lease, Durable Archiving, & Fail-Closed Remediation  
**Status:** ACCEPTED & LOCKED  
**Verification Date:** 2026-11-02  
**Sign-off Criteria:** Zero fail-open behavior in CI/production, remote state optimistic concurrency, pre-reservation request accounting surviving runner crashes, cumulative daily manifests, readback verification of committed blobs, and multi-tier operational status reporting.

---

## 1. M2 Scope & Objectives

Milestone 2 hardens the data persistence, concurrency, and reliability layers:
- Cross-run distributed lease coordination eliminating split-brain execution across GitHub runners.
- Durable quota pre-reservation committed to remote storage before physical socket connections.
- Raw payload archiving into date-sharded compressed gzip files (`raw/YYYY/MM/DD/*.json.gz`).
- Cumulative daily manifests aggregating verified files and execution cycle history.
- Cryptographic readback verification after every remote commit.
- Strict multi-tier lifecycle statuses eliminating false-positive monitoring alerts.

---

## 2. Requirement Verification Matrix

| Requirement | Specification Contract | Implementation Artifact | Status | Verification Evidence |
| :--- | :--- | :--- | :--- | :--- |
| **Fail-Closed Budgeting** | Missing tokens or remote errors must abort immediately in CI. | `collector/persistent_budget.py` | **VERIFIED** | Unit test `test_persistent_coordinator_fails_closed_in_ci_without_token` passed. |
| **Durable Pre-Reservation** | Quota reserved remotely before socket request; survives crashes. | `PersistentCoordinator.reserve_request()` | **VERIFIED** | Chaos test `test_crash_between_quota_reservation_and_network_request` passed. |
| **Optimistic Concurrency** | HTTP 409 conflict handling with jittered backoff. | `PersistentCoordinator.save_remote_state()` | **VERIFIED** | Unit test `test_persistent_coordinator_optimistic_concurrency_retry` passed. |
| **Non-Clobbering Lease Release** | Lease release preserves competitor leases and merges request logs. | `PersistentCoordinator.release_lease()` | **VERIFIED** | Unit test `test_lease_release_does_not_clobber_competitor_lease_or_requests` passed. |
| **Durable Archival** | Raw payloads stored compressed in private repository. | `collector/archive.py` | **VERIFIED** | Live Run `41386016819` committed compressed shard to `MahadImran/psx-research-data`. |
| **Cumulative Manifests** | Daily manifest merges files across all daily poll cycles without data loss. | `DurableArchiveManager.commit_daily_manifest()` | **VERIFIED** | Unit test `test_archive_manager_cumulative_manifest_merging` passed. |
| **Readback Verification** | Remote commits validated by immediate GET and SHA-256 check. | `DurableArchiveManager._commit_file()` | **VERIFIED** | Unit test `test_archive_manager_commits_with_readback_verification` passed. |
| **Granular Status Reporting** | Distinguish full success, unchanged data, archive committed, and failures. | `collector/pipeline.py` | **VERIFIED** | Runner Run `41386086661` returned `MARKET_CLOSED` with zero false-positive alerts. |

---

## 3. Engineering Evidence & Runner Artifacts

### 3.1 Live Verification on GitHub Runner
- **Run ID:** `41386016819`
- **Workflow:** `Bounded Durable Archive Verification`
- **Output Steps Verified:**
  1. `[INFO] Initialized PersistentCoordinator for runner gha-41386016819`
  2. `[INFO] Successfully acquired persistent lease for runner gha-41386016819`
  3. `[INFO] Pre-reserved request quota for endpoint /dps_table.php` (committed to remote GitHub state)
  4. `[INFO] Successfully extracted 1 live index records from PSX DPS`
  5. `[INFO] Successfully committed raw/2026/11/02/dps_index_summary_gha-41386016819.json.gz (SHA: 6d50694e...)`
  6. `[INFO] Readback verification SUCCESS for raw/2026/11/02/dps_index_summary_gha-41386016819.json.gz`
  7. `[INFO] Daily manifest committed with 1 verified files`
  8. `[INFO] Lease cleanly released and history merged for runner gha-41386016819`

### 3.2 Automated Test Coverage for M2
- `test_persistent_budget.py`:
  - `test_persistent_coordinator_lease_lifecycle`: PASS
  - `test_persistent_coordinator_budget_fuse_enforcement`: PASS
  - `test_persistent_coordinator_fails_closed_in_ci_without_token`: PASS
  - `test_persistent_coordinator_fails_closed_when_repo_inaccessible`: PASS
  - `test_persistent_coordinator_optimistic_concurrency_retry`: PASS
  - `test_pre_reservation_commits_before_request_and_survives_crash`: PASS
  - `test_reserve_request_fails_closed_when_lease_expired`: PASS
  - `test_lease_release_does_not_clobber_competitor_lease_or_requests`: PASS
  - `test_lease_renewal_lifecycle`: PASS
- `test_archive.py`:
  - `test_archive_manager_stages_sharded_gzip`: PASS
  - `test_archive_manager_fails_closed_in_production_without_token`: PASS
  - `test_archive_manager_commits_with_readback_verification`: PASS
  - `test_archive_manager_readback_hash_mismatch_raises`: PASS
  - `test_archive_manager_idempotent_existing_file`: PASS
  - `test_archive_manager_cumulative_manifest_merging`: PASS

---

## 4. Milestone 2 Acceptance Sign-off

Milestone 2 satisfies all remediation requirements set forth in the M2 Acceptance Review. Concurrency is provably atomic, budget accounting is crash-safe, and raw market data is durably preserved.
