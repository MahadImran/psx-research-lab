# PSX Research Lab — Foundation Risk Register

**Status:** ACTIVE & MONITORED  
**Last Updated:** 2026-11-03  
**Scope:** Milestones 0, 1, and 2 Foundation Architecture, Security, Data Integrity, and Cost Controls  

---

## 1. Risk Matrix Overview

| Risk ID | Category | Severity | Likelihood | Status | Title & Brief Summary |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **FR-01** | Concurrency | HIGH | HIGH | **RESOLVED** | Ephemeral runner state loss on crash before socket request |
| **FR-02** | Data Durability | CRITICAL | HIGH | **RESOLVED** | Daily manifest overwrite erasing morning poll cycles |
| **FR-03** | Security | HIGH | MEDIUM | **RESOLVED** | Check-then-act race condition in replay attack protection |
| **FR-04** | Data Integrity | MEDIUM | HIGH | **RESOLVED** | Geometry violations in OHLC bars (`High < max(Open, Close)`) |
| **FR-05** | Security | HIGH | LOW | **RESOLVED** | Accidental credential leakage in CI logs via monitoring tracebacks |
| **FR-06** | Reliability | HIGH | MEDIUM | **RESOLVED** | False-positive success reporting when cloud ingestion fails |
| **FR-07** | Reliability | MEDIUM | MEDIUM | **RESOLVED** | GitHub REST API edge replication lag causing false readback failures |
| **FR-08** | Data Quality | LOW | MEDIUM | **RESOLVED** | Nullable High/Low in PSX DPS index summary tables |
| **FR-11** | Data Durability | HIGH | HIGH | **RESOLVED** | Raw archive object overwrite violating strict immutability |
| **FR-12** | Security | HIGH | MEDIUM | **RESOLVED** | Cloudflare Access authorization bypass when unconfigured |
| **FR-13** | Security & Concurrency | HIGH | MEDIUM | **RESOLVED** | KV-only fallback in HMAC nonce verification race conditions |
| **FR-14** | Data Integrity | HIGH | MEDIUM | **RESOLVED** | Multi-batch D1 staging leaving unverified partial data queryable |
| **FR-15** | Performance & Quota | MEDIUM | HIGH | **RESOLVED** | Redundant archive writes of unchanged intraday market snapshots |
| **FR-09** | External | HIGH | LOW | **MONITORED** | Upstream PSX DPS endpoint breaking changes or anti-scraping blocks |
| **FR-10** | Cost & Quota | LOW | LOW | **MONITORED** | GitHub Actions 2,000 free runner minutes exhaustion |

---

## 2. Detailed Findings & Remediation Register

### FR-01: Ephemeral Runner State Loss on Crash Before Socket Execution
- **Severity:** HIGH  
- **Vulnerability:** Request quota was recorded in memory and written remotely only after completing network operations. A runner crashing or terminated by GitHub mid-execution failed to account for upstream attempts, enabling potential upstream rate limit violations.
- **Remediation:** Implemented `PersistentCoordinator.reserve_request()` in `persistent_budget.py`. Quota reservations are committed remotely to `state/budget_and_lease.json` using optimistic concurrency *before* the physical socket request is initiated.
- **Verification Proof:**
  - Automated Chaos Test: `test_crash_between_quota_reservation_and_network_request` in `services/collector/tests/test_adversarial_failures.py`.
  - Live GitHub Runner Run: Run `41386016819` verified atomic reservation prior to raw DPS extraction.

### FR-02: Daily Manifest Overwrite Erasing Morning Poll Cycles
- **Severity:** CRITICAL  
- **Vulnerability:** Each collector run wrote `manifests/{trading_date}.json` containing only the raw files staged during that specific execution, unintentionally wiping out the catalog of files committed in earlier intraday runs.
- **Remediation:** Refactored `DurableArchiveManager.commit_daily_manifest()` in `archive.py` to read existing remote daily manifests, compute the union set of `verifiedArchiveFiles`, and preserve an immutable array of historical `cycles`.
- **Verification Proof:**
  - Automated Unit Test: `test_archive_manager_cumulative_manifest_merging` in `test_archive.py`.
  - Chaos Test: `test_same_day_collection_collision_preserves_all_files` in `test_adversarial_failures.py`.

### FR-03: Check-Then-Act Race Condition in Nonce Replay Protection
- **Severity:** HIGH  
- **Vulnerability:** KV check-then-set for HMAC request nonces allowed simultaneous identical requests to pass validation during KV replication windows.
- **Remediation:** Anchored nonce replay protection in Cloudflare D1 via an atomic SQL insert (`INSERT INTO seen_nonces (nonce, timestamp_sec)`). The database enforces primary key uniqueness atomically; duplicate nonces instantly fail with HTTP 401. KV is retained as an optional edge cache only.
- **Verification Proof:**
  - Vitest Unit Tests: `apps/api/src/__tests__/api.test.ts` (9 tests passed).
  - Schema definition: `apps/api/src/db/schema.sql`.

### FR-04: Geometry Violations in OHLC Daily Bars
- **Severity:** MEDIUM  
- **Vulnerability:** Corrupted or out-of-order upstream ticks could generate daily candles where `High` was less than `Close` or `Low` was greater than `Open`.
- **Remediation:** Enforced strict geometric invariants in `QuarantineAuditor.audit_daily_bar()` (`quarantine.py`). Candles violating `High >= max(Open, Close)` or `Low <= min(Open, Close)` are rejected and quarantined.
- **Verification Proof:**
  - Unit Tests: `test_quarantine_rejects_high_lower_than_close_or_open` and `test_quarantine_rejects_low_higher_than_close_or_open` in `test_quarantine.py`.
  - Chaos Test: `services/collector/tests/test_quarantine.py` (all 7 quarantine tests passed).

### FR-05: Accidental Credential Leakage in CI Logs
- **Severity:** HIGH  
- **Vulnerability:** Healthchecks monitoring URLs contain secret ping UUIDs. If an exception occurred during HTTP pinging, Python's default traceback could write the raw URL into Actions console logs.
- **Remediation:** Added `HealthchecksNotifier._clean_url()` which strips the secret ping UUID from log strings and error messages, replacing it with `[REDACTED_UUID]`.
- **Verification Proof:**
  - Unit Test: `test_healthchecks_redacts_secret_url_on_errors` in `test_healthchecks.py`.
  - GitHub Actions Runner Logs: Run `41386086661` shows `HEALTHCHECKS_PING_URL: ***` and sanitized console messages.

### FR-06: False-Positive Success Reporting
- **Severity:** HIGH  
- **Vulnerability:** `pipeline.py` returned success when archiving succeeded even if ingestion failed, signaling false health to external monitoring.
- **Remediation:** Introduced explicit multi-tier lifecycle statuses (`SUCCESS`, `DATA_UNCHANGED`, `ARCHIVE_COMMITTED_INGEST_PENDING`, `ARCHIVE_FAILED`, `INGEST_FAILED`, `MARKET_CLOSED`). Heartbeats send `/fail` on archive or fatal ingestion errors.
- **Verification Proof:**
  - Unit Tests: `test_pipeline_fails_closed_on_archive_failure` and `test_pipeline_reports_ingest_failure` in `test_pipeline.py`.
  - Chaos Test: `test_false_positive_heartbeat_prevention` in `test_adversarial_failures.py`.

### FR-07: GitHub REST API Edge Replication Lag Causing False Readback Failures
- **Severity:** MEDIUM  
- **Vulnerability:** Immediately after a successful HTTP 201 write to GitHub Contents API, an immediate GET could hit an out-of-sync edge replica returning 404 or an older SHA.
- **Remediation:** Implemented bounded exponential backoff in `read_remote_file()` (up to 3 retries with 0.75s initial delay) and cache-busting request headers.
- **Verification Proof:**
  - Live GitHub Runner Run: Run `41386016819` verified readback verification across 8 steps without transient false negatives.

### FR-08: Nullable High/Low in PSX DPS Index Summary Tables
- **Severity:** LOW  
- **Vulnerability:** PSX DPS index summary tables frequently omit intraday High and Low values for benchmark indices. Rigid schemas expecting non-null floats dropped valid index data.
- **Remediation:** Modified `DailyBarSchema` and `QuarantineAuditor` to treat `high` and `low` as nullable floats (`Optional[float]`). Introduced `dataGrade` (`GRADE_B` for nullable High/Low; `GRADE_A` for complete OHLC).
- **Verification Proof:**
  - Unit Tests: `test_quarantine_accepts_valid_bar_with_nullable_high_low` in `test_quarantine.py`.
  - Schema Contract: `packages/shared/src/schemas/market.ts`.

### FR-11: Raw Archive Object Overwrite Violating Strict Immutability
- **Severity:** HIGH  
- **Vulnerability:** `DurableArchiveManager._commit_file()` previously allowed updating an existing path if the remote SHA was retrieved, risking accidental or malicious overwrite of historical raw response payloads.
- **Remediation:** Enforced strict raw object immutability in `archive.py`. For any path under `raw/`, if the file exists with differing content, the commit raises `ArchiveCommitError` ("Immutability violation... raw archive objects are strictly immutable"). Idempotent re-commits with identical content are recognized as clean no-ops.
- **Verification Proof:**
  - Unit Test: `test_archive_manager_immutability_violation_raises` in `test_archive.py`.
  - Live GitHub Runner Verification: Run `41687650867` Step 8 rejected a tampered content overwrite attempt and Step 9 confirmed clean idempotency.

### FR-12: Cloudflare Access Authorization Bypass When Unconfigured
- **Severity:** HIGH  
- **Vulnerability:** `verifyCloudflareAccess` middleware defaulted to `requireAccess = false` if omitted in handler invocations, potentially allowing unauthenticated public requests to hit edge ingestion endpoints when Access credentials were missing.
- **Remediation:** Refactored `verifyCloudflareAccess` in `apps/api/src/middleware/auth.ts` to fail closed by default (`requireAccess !== false`). Missing Access environment variables or missing `CF-Access-Authenticated-User-Email` headers immediately return HTTP 403. Gated `/v1/admin/ingest` with `requireAccess: true`.
- **Verification Proof:**
  - Vitest Unit Tests: `apps/api/src/__tests__/api.test.ts` (`should reject 403 when access is required but credentials are missing in worker env`, `should reject 403 when CF-Access-Authenticated-User-Email header is missing`).

### FR-13: KV-Only Fallback in HMAC Nonce Verification Race Conditions
- **Severity:** HIGH  
- **Vulnerability:** `verifyAndRecordNonce` allowed falling back to KV-only nonce storage when D1 was unavailable, introducing a distributed check-then-set race condition where replay attacks could slip past during KV eventual consistency windows.
- **Remediation:** Removed the KV-only fallback in `apps/api/src/middleware/auth.ts`. Cloudflare D1 is now the sole authoritative atomic store using SQLite `PRIMARY KEY (nonce)` constraint enforcement. If the D1 binding is absent, the middleware fails closed with HTTP 401. KV serves strictly as an optional performance read cache.
- **Verification Proof:**
  - Vitest Unit Tests: `apps/api/src/__tests__/api.test.ts` (`should reject 401 when D1 binding is missing`).

### FR-14: Multi-Batch D1 Staging Atomicity and Two-Phase Publication
- **Severity:** HIGH  
- **Vulnerability:** Multi-batch D1 inserts could fail mid-stream, leaving partial, unverified market data visible and active in production tables for user queries.
- **Remediation:** Implemented a two-phase staging and publication protocol in `apps/api/src/index.ts`. All staged records (`raw_ingestions`, `daily_bars`, `snapshots`) are written with `is_active = 0` and status `'STAGING'`. Only after all batches succeed is an atomic publication transaction executed setting `is_active = 1` and status `'ACCEPTED'`. If any batch fails, the ingestion is marked `'FAILED'`. Duplicate submissions of the same `ingestion_id` return HTTP 200 idempotently.
- **Verification Proof:**
  - Vitest Unit Tests: `apps/api/src/__tests__/api.test.ts` (19 / 19 passed across workspace).
  - Schema migration: `apps/api/src/db/schema.sql`.

### FR-15: Redundant Archive Writes of Unchanged Intraday Market Snapshots
- **Severity:** MEDIUM  
- **Vulnerability:** When the market is static, repeated polling cycles wrote duplicate multi-kilobyte snapshot shards to GitHub Git history, consuming Git repository storage and unnecessary runner minutes.
- **Remediation:** Implemented persistent, source- and trading-date-aware snapshot hash caching (`snapshot_hashes`) inside `state/budget_and_lease.json`. `pipeline.py` compares the SHA-256 hash of new snapshots against `coordinator.get_last_snapshot_hash(source, trading_date)`. If identical, it records status `DATA_UNCHANGED` and safely skips redundant archive commits.
- **Verification Proof:**
  - Unit Test: `test_durable_snapshot_deduplication_skips_duplicate_archive` in `test_pipeline.py`.
  - Persistent Coordinator Tests: `test_persistent_coordinator_lease_lifecycle` in `test_persistent_budget.py`.

---

## 3. Residual & Monitored Risks

### FR-09: Upstream PSX DPS Endpoint Breaking Changes
- **Category:** External Dependency  
- **Severity:** HIGH  
- **Likelihood:** LOW–MEDIUM  
- **Mitigation Strategy:**
  - The collector uses defensive HTML parsing (`vendor/psx_dps/parsing.py`) resilient against missing table tags and unclosed elements.
  - Raw HTML and JSON payloads are archived unparsed into gzip shards. If an upstream format changes, raw data is preserved, and parsers can be updated retrospectively.
  - Fail-closed design logs quarantine events and alerts via Healthchecks on consecutive parsing failures.

### FR-10: GitHub Actions Runner Minute Quota Depletion
- **Category:** Operational Limits ($0.00 Spend)  
- **Severity:** LOW  
- **Likelihood:** LOW  
- **Mitigation Strategy:**
  - Fast execution time: average collector cycle runs in 14–25 seconds.
  - Schedule limited to trading hours only (~45 runs/day = ~560 minutes/month out of 2,000 free minutes).
  - Unattended schedule cron is currently disabled (`workflow_dispatch` only) during foundation lockdown.
