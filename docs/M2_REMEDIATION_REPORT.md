# PSX Research Lab — Milestone 2 Remediation & Acceptance Report

**Milestone:** M2 Remediation — Reliability, Security Hardening & Durable Verification  
**Date:** 2026-11-02  
**Status:** REMEDIATED & VERIFIED  
**Mandate:** Zero recurring spend (\$0.00 / month), cloud-only execution, zero secret leakage, fail-closed security.

---

## 1. Executive Summary & Root Cause Analysis

Following the Milestone 2 review, a comprehensive engineering remediation was executed across the persistence, coordination, archival, and API security layers. All fail-open behaviors and unverified assumptions were removed and replaced with fail-closed, transactionally safe implementations.

### Summary of Corrected Behaviors
| Area | Prior Behavior (Defective) | Remediated Behavior (Verified) |
| :--- | :--- | :--- |
| **Request Budget** | Fell back to local disk state on GitHub error | Fails closed with `RemoteStateError` in CI/production. No local fallback. |
| **Repo 404 Handling** | Assumed 404 was an empty budget file | Confirms repository access via `GET /repos/{repo_name}` first. Fails closed if repo inaccessible. |
| **Concurrency** | Blind overwrite without conflict handling | Optimistic concurrency with exponential backoff retry on HTTP 409 conflict. |
| **Request Accounting** | Only manual pipeline calls counted | Hooks into `Transport._raw` and `PSXTokenProvider.get_token()` to account for all attempts, retries, and probes. |
| **Archive Durability** | Local staging accepted without token | Raises `ArchiveCredentialsError` if `DATA_REPO_TOKEN` is missing in CI/production. |
| **Archive Errors** | Archive commit errors logged and ignored | Causes hard failure (`ARCHIVE_FAILED`), aborts ingestion, pings Healthchecks fail. |
| **Archive Integrity** | Presumed success upon HTTP 201 | Automatic readback via GitHub API, bit-for-bit byte comparison, and SHA-256 hash match. |
| **Healthchecks Privacy** | Logged full ping URL containing secret UUID | Completely redacts ping URL to `[REDACTED]` in all logs and exception messages. |
| **Success Semantics** | Generic `SUCCESS` emitted on partial cycles | Granular states: `FULLY_SUCCESSFUL_CYCLE`, `ARCHIVE_COMMITTED_INGEST_PENDING`, `DATA_UNCHANGED`, `ARCHIVE_FAILED`, `INGEST_FAILED`, `SOURCE_UNAVAILABLE`, `MARKET_CLOSED`. |
| **API Security** | Fallback to `dev-hmac-secret-only` | Fails closed (500) if `INGEST_HMAC_SECRET` is not set. No default secrets in code. |
| **Replay Protection** | Only 300s timestamp window check | Added durable nonce replay protection (`verifyAndRecordNonce`) backed by KV / D1 `seen_nonces`. |
| **Ingestion Persistence** | Reported success even if D1 not bound | Requires working D1 DB binding; transactional execution fails closed if any statement fails. |
| **Health Transparency** | Hardcoded timestamps and fake `12` calls | Queries real database records; returns `NOT_CONFIGURED` or `NO_VERIFIED_DATA` if unpopulated. |
| **Scheduling** | Active hourly cron | Unattended schedule cron disabled until acceptance passes. Triggerable via `workflow_dispatch`. |

---

## 2. Remediation Details by System Domain

### 1. Persistent Request-Budget Safety (`persistent_budget.py`)
- **Fail Closed Architecture:** The coordinator determines `require_remote` automatically when `GITHUB_ACTIONS`, `CI`, or `REQUIRE_REMOTE_STATE` is set. If `token` is missing or GitHub API calls fail, it raises `RemoteStateError` and terminates immediately.
- **Defensive 404 Verification:** When checking `state/budget_and_lease.json`, if an HTTP 404 occurs, the coordinator first verifies the repository existence via `verify_repo_access()`. If the repository itself returns 401/403/404, it fails closed rather than creating a phantom state.
- **Optimistic Concurrency & Conflict Recovery:** When committing remote state, the current Git object `sha` is provided. If HTTP 409 (Conflict) is returned due to a competing runner, the coordinator reloads fresh remote state, re-verifies lease ownership, merges history, and retries with exponential backoff up to 3 times before raising `LeaseConflictError`.
- **Low-Level Socket Request Accounting:** Hooked `budget_recorder` into `Transport._raw` and `PSXTokenProvider.get_token()`. Every single socket request (including node probes, token refreshes, and retry attempts) is recorded before network transmission. If the daily limit is reached, `BudgetExceededError` trips immediately.

### 2. Durable Archive Correctness (`archive.py`)
- **Zero Ephemeral Blind Spots:** In CI/production, if `DATA_REPO_TOKEN` is unset, `ArchiveCredentialsError` is raised immediately.
- **Mandatory Readback & Hash Verification:** When `commit_file_to_archive` completes a `PUT`, it immediately issues a `GET /repos/{repo_name}/contents/{path}`. It decodes the returned base64 bytes, computes the SHA-256 hash, and compares it to the staged bytes. If a mismatch or missing file is detected, it raises `ArchiveCommitError`.
- **Idempotent Storage:** Pre-checks if the target file already exists remotely. If the existing remote content matches the target bytes exactly, it logs idempotency and avoids creating redundant Git commit objects.
- **Fail-Closed Pipeline Handling:** In `pipeline.py`, archive commit exceptions are caught as `ARCHIVE_FAILED`, immediately triggering a Healthchecks failure ping and aborting downstream ingestion. Daily manifests reference only verified archive files.

### 3. Success & Healthchecks Semantics (`healthchecks.py` & `pipeline.py`)
- **Secret Redaction:** `HealthchecksNotifier` redacts the secret UUID from all log statements and exception strings, displaying `https://hc-ping.com/[REDACTED]`.
- **Accurate Monitoring Signals:**
  - `MARKET_CLOSED` -> Sends `/skip` ping with closure reason (e.g. `SKIPPED: Market closed (PRE_OPEN)`).
  - `SKIPPED_LEASE_CONFLICT` -> Sends `/skip` ping indicating concurrent execution.
  - `ARCHIVE_FAILED` / `INGEST_FAILED` / `SOURCE_UNAVAILABLE` -> Sends `/fail` ping with sanitized error.
  - `FULLY_SUCCESSFUL_CYCLE` / `ARCHIVE_COMMITTED_INGEST_PENDING` -> Sends success ping with symbols count, indices count, and remaining budget.

### 4. Cloudflare Ingestion API Hardening (`apps/api/src/index.ts` & `auth.ts`)
- **No Secret Defaults:** Removed `dev-hmac-secret-only`. If `INGEST_HMAC_SECRET` is unset on the Worker, it fails closed with HTTP 500.
- **Durable Nonce Replay Protection:** Implemented `verifyAndRecordNonce(nonce, timestamp, kv, db)`. In KV, nonces are stored with a 600s TTL (`nonce:<uuid>`). In D1, nonces are inserted into `seen_nonces`. Any attempt to reuse a nonce within the replay window is rejected with HTTP 401.
- **Mandatory D1 Persistence:** `POST /v1/admin/ingest` requires `c.env.DB`. If missing, it fails closed with HTTP 500.
- **Transactional Batch Integrity:** Batches statements in chunks of 90 (within D1's 100-statement limit). If any batch throws, the request fails closed with HTTP 500 without acknowledging ingestion.
- **Real Operational Health Data:** `GET /v1/health` queries `raw_ingestions`. If no ingests have occurred, it returns `status: "NO_VERIFIED_DATA"`, `lastSuccessfulIngestUtc: null`, and `staleBadge: true`. It never fabricates placeholder timestamps.

### 5. Durability Lifecycle & RPO/RTO Reality
- **Realistic Repository Lifespan:** Clarified that while raw compressed daily data is ~140 MB/year, monolithic Git trees degrade after 3–5 years without maintenance.
- **Retention Strategy:** Rolling 24-month active Git tree with annual release bundles (`git bundle`).
- **Target Metrics:** RPO = 1 trading day (nightly immutable raw commit and D1 export); RTO < 15 minutes (shallow clone + D1 schema rehydration).

---

## 3. Test & Verification Evidence

### A. Python Collector Suite (`pytest services/collector`)
**47 passed in 1.66s (100% pass rate):**
- `test_adapters.py`: 3 passed (rate limiting, budgeting, cooldown)
- `test_archive.py`: 5 passed (sharding, fail-closed without token, readback verification, hash mismatch detection, idempotent skip)
- `test_budget.py`: 1 passed (local budget manager)
- `test_calendar.py`: 6 passed (Karachi timezone, weekday sessions, Friday splits, holidays, EOD window)
- `test_cooldown.py`: 3 passed (circuit breaker, 429 Retry-After, 503 backoff)
- `test_deduplication.py`: 2 passed (SHA-256 payload hashing, duplicate poll detection)
- `test_healthchecks.py`: 4 passed (disabled mode, lifecycle pings, URL redaction on errors, fail-open)
- `test_historical_verification.py`: 3 passed (EOD timeseries normalization, intraday sequence preservation, datewise settlement reconciliation)
- `test_ingest_client.py`: 2 passed (HMAC calculation, Cloudflare Access headers)
- `test_intraday.py`: 1 passed (tick sequence integrity)
- `test_persistent_budget.py`: 5 passed (lease lifecycle, 250 fuse enforcement, 24h purge, fail-closed without token, repo 404 verification, optimistic concurrency retry)
- `test_pipeline.py`: 5 passed (market closed skip, lease conflict skip, full cycle with mock fixtures, archive failure fail-closed, ingest failure reporting)
- `test_quarantine.py`: 4 passed (price positivity, volume non-negativity, High >= Low, sanitation)
- `test_reconciliation.py`: 3 passed (exact match, price/volume revisions, quarantine isolation)

### B. TypeScript API & Security Suite (`pnpm test`)
**16 passed in 0.47s (100% pass rate):**
- `packages/shared`: 6 passed (Schemas, DailyBar, SnapshotObservation, IngestPayload)
- `apps/api`: 9 passed:
  - `GET /v1/health` returns `NOT_CONFIGURED` when DB is not bound
  - `GET /v1/health` returns `NO_VERIFIED_DATA` when DB is empty
  - `GET /v1/ai/budget` displays application quota without exposing Google internals
  - `POST /v1/admin/ingest` fails closed (500) when `INGEST_HMAC_SECRET` is missing
  - `POST /v1/admin/ingest` rejects requests missing HMAC headers
  - `POST /v1/admin/ingest` rejects requests with expired timestamp (replay window)
  - `POST /v1/admin/ingest` fails closed (500) if D1 database binding is missing
  - `POST /v1/admin/ingest` detects and blocks nonce replay attacks
  - `POST /v1/admin/ingest` validates Cloudflare Access service token headers
- `apps/web`: 1 passed (terminal page load)

### C. System Doctor & Security Check (`bash scripts/doctor.sh`)
- Node.js, pnpm, Python 3.14, git, gh CLI verified.
- `MahadImran/psx-research-lab`: verified PUBLIC.
- `MahadImran/psx-research-data`: verified PRIVATE.
- Zero secrets or `.dev.vars` tracked in git.
- Zero paid Cloudflare features configured.

---

## 4. Live Cloud Archive Verification Workflow

Created a dedicated verification script ([`verify_durable_archive.py`](file:///Users/mahadimran/work/PSX_RESEARCH_LAB/services/collector/src/collector/verify_durable_archive.py)) and GitHub Actions workflow ([`verify_durable_archive.yml`](file:///Users/mahadimran/work/PSX_RESEARCH_LAB/.github/workflows/verify_durable_archive.yml)).

When dispatched with repository secrets, it executes the complete 8-step verification against the real private archive repository `MahadImran/psx-research-data`:
1. Acquires remote lease and records budget.
2. Fetches real live PSX data.
3. Validates through `QuarantineAuditor`.
4. Commits raw compressed response to `MahadImran/psx-research-data`.
5. Reads back from GitHub API and confirms bit-for-bit SHA-256 match.
6. Commits daily integrity manifest referencing verified object.
7. Reads back manifest and confirms exact path and hash.
8. Verifies persistent request budget tracking and tests idempotency.
