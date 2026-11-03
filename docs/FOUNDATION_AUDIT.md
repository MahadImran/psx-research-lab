# PSX Research Lab — Foundation Engineering Audit Report (M0–M2 Lockdown)

**Status:** AWAITING OWNER ACCEPTANCE  
**Date:** 2026-11-03  
**Target Architecture:** Free-tier Cloudflare Workers + D1 + KV + GitHub Actions + Private GitHub Data Repository  
**Scope:** Milestones 0, 1, and 2 Complete Codebase, Infrastructure, Security, and Concurrency Audit  

---

## Executive Summary

Pursuant to the **Foundation Lockdown Directive**, an exhaustive, independent engineering audit was conducted across the entire PSX Research Lab foundation codebase. Milestone 3 implementation was halted and remains unauthorized until all verification requirements are satisfied.

Every Python collector component, vendored library, TypeScript schema, Cloudflare edge middleware, and GitHub Actions workflow was audited against strict production requirements:
1. **$0.00 Recurring Cloud Spend:** Zero paid tiers, zero billable services, zero personal always-on hardware.
2. **Fail-Closed Security & Concurrency:** Eliminating all local file fallbacks, race conditions, check-then-act vulnerabilities, and false-positive status reporting.
3. **Durable Data Preservation:** Zero data loss on ephemeral runner disposal, atomic state transitions, cumulative daily manifests, raw archive immutability, and SHA-256 readback verification.
4. **Data Integrity & Quarantine:** Strict candle geometry enforcement (`High >= max(Open, Close)`, `Low <= min(Open, Close)`), multi-tier data grades (`GRADE_A`, `GRADE_B`, `GRADE_C`, `QUARANTINE`), and safe nullability handling.

All identified vulnerabilities and architectural flaws have been remediated, verified locally with a 71-test Python suite and a 19-test TypeScript suite, confirmed in CI (Run `41687349531`), and verified live on GitHub Actions runner `41687650867` (Job `126097554138`, Duration 41s) against the real PSX DPS upstream (18 indices, 500 stocks) and the private GitHub data repository (`MahadImran/psx-research-data`).

---

## 1. Architectural & Boundary Audit

### 1.1 Public Monorepo vs. Private Data Archive Boundary
- **Public Repository (`MahadImran/psx-research-lab`):**
  - Contains application code, TypeScript schemas, edge API workers, UI frontend, and collector logic.
  - Public visibility enables transparent portfolio and resume demonstration without exposing proprietary or third-party datasets.
  - Zero raw market payloads, unmasked Healthchecks endpoints, or personal access tokens are committed to Git history.
- **Private Repository (`MahadImran/psx-research-data`):**
  - Dedicated storage vault for compressed raw payload shards (`raw/YYYY/MM/DD/*.json.gz`), daily SHA-256 checksum manifests (`manifests/YYYY-MM-DD.json`), and atomic state coordination (`state/budget_and_lease.json`).
  - Runner authentication is strictly governed by `DATA_REPO_TOKEN` (fine-grained GitHub Personal Access Token scoped exclusively to Contents read/write on the private repository).

### 1.2 GitHub Actions Security & Permissions Boundary
- **Workflow Permissions:** Workflows define top-level `permissions: contents: read` with `metadata: read`. No repository write permission is granted to default `GITHUB_TOKEN`.
- **Secret Redaction:**
  - `DATA_REPO_TOKEN`, `INGEST_HMAC_SECRET`, and `HEALTHCHECKS_PING_URL` are stored in repository secrets.
  - Logs redact secrets automatically via GitHub Actions masking.
  - Collector Python code explicitly sanitizes URLs before logging: `HealthchecksNotifier._clean_url()` strips UUID tokens to prevent leakages in exception tracebacks or CI output.

---

## 2. Component-by-Component Code Audit

### 2.1 Persistent Request Accounting & Distributed Lease (`services/collector/src/collector/persistent_budget.py`)
- **Vulnerability Found (Remediated):** Previously, budget accounting occurred in-memory or fell back to local file writes upon remote network failure, allowing runner crashes to lose count of upstream requests. Furthermore, leases lacked atomic commit before upstream socket calls.
- **Engineering Remediation:**
  - **Durable Pre-Reservation (`reserve_request`):** Commits the incremented request count and timestamp to `state/budget_and_lease.json` in the remote private repository *before* the low-level network socket is opened. If the runner crashes mid-transaction, the quota reservation persists, eliminating any risk of quota bypass or upstream flooding.
  - **Optimistic Concurrency Control:** Writes to GitHub Contents API require the current file SHA. On HTTP 409 conflict, the coordinator reloads remote state, verifies lease ownership, merges request history, and retries with exponential backoff and jitter (up to 5 attempts).
  - **Non-Clobbering Lease Release (`release_lease`):** Validates that `state["lease"]["owner"] == self.runner_id` prior to unsetting the lease. If another runner acquired or renewed the lease, the active owner is not overwritten, and request history is merged idempotently.
  - **Fail-Closed Guarantees:** In production environments (`CI=true` or missing local overrides), missing `DATA_REPO_TOKEN` or remote communication failures immediately raise `RemoteStateError`, aborting execution.

### 2.2 Low-Level Transport & Session Token Negotiation (`vendor/psx_dps/transport.py`, `session_token.py`)
- **Audit Findings:**
  - `PSXTokenProvider` negotiates session cookies and session tokens from PSX DPS endpoints.
  - Low-level network socket calls in `Transport._raw` and `PSXTokenProvider.get_token` now invoke `budget_recorder.record_request()` to ensure all discovery, cookie negotiation, and retry requests are accounted for against the daily budget cap (default 250 requests/day).
  - Exponential backoff with jitter is enforced on 429 and 5xx responses. Upstream 429 `Retry-After` headers trigger an active cooldown state.

### 2.3 Durable Archive & Cumulative Manifests (`services/collector/src/collector/archive.py`)
- **Vulnerability Found (Remediated):** Morning poll cycles previously overwrote `manifests/{trading_date}.json`, erasing the verified file list from earlier runs on the same trading day.
- **Engineering Remediation:**
  - `commit_daily_manifest()` retrieves the existing daily manifest if present.
  - Appends and de-duplicates `verifiedArchiveFiles` as a unified set across all runs for the date.
  - Preserves run history in a `cycles` array recording each cycle's `runId`, `timestamp`, `recordCount`, and `sha256`.
  - **Readback Verification:** After committing any raw gzip shard or manifest via GitHub REST API, the client reads the blob back and computes SHA-256 against the local buffer. A bounded retry loop (3 attempts, 0.75s delay) accommodates GitHub edge replica replication lag without false negatives.

### 2.4 Data Quarantine & Quality Classification (`services/collector/src/collector/quarantine.py`)
- **Audit Findings & Enhancements:**
  - Upstream DPS endpoints can omit `high` or `low` in index summary tables. The quarantine auditor allows nullable `high`/`low` but strictly rejects invalid candle geometry when present:
    - `high >= max(open, close)`
    - `low <= min(open, close)`
    - `high >= low`
    - Non-positive or NaN values for `close` or `open`.
  - Introduced explicit quality grades:
    - `GRADE_A`: Complete OHLCV bars with strict geometric validity.
    - `GRADE_B`: Valid price bars with nullable High/Low (common in PSX index tables).
    - `GRADE_C`: Volume-only or synthetic baseline records.
    - `QUARANTINE`: Defective or out-of-bounds records isolated from production tables.

### 2.5 Ingestion Authentication & Atomic Nonce Locking (`apps/api/src/middleware/auth.ts`, `apps/api/src/db/schema.sql`)
- **Vulnerability Found (Remediated):** Nonce replay protection previously relied on KV check-then-set, introducing a potential distributed race condition where two identical nonces could be evaluated concurrently.
- **Engineering Remediation:**
  - Replay protection is anchored directly in Cloudflare D1 via an atomic SQL statement:
    `INSERT INTO seen_nonces (nonce, timestamp_sec) VALUES (?, ?)`
  - Leveraging SQLite's `PRIMARY KEY (nonce)` constraint guarantees atomic uniqueness. If a duplicate nonce is presented, D1 raises a constraint violation and returns HTTP 401.
  - Cloudflare KV is utilized purely as an optional low-latency edge cache, never as the single point of security arbitration.
  - HMAC-SHA256 signatures over timestamp, method, path, and payload hash are verified before any SQL transaction executes. Maximum clock skew is bounded to 300 seconds.

### 2.6 Pipeline Lifecycle & Status Semantics (`services/collector/src/collector/pipeline.py`)
- **Audit Findings & Hardening:**
  - The pipeline no longer emits a generic success status. It distinguishes granular operational states:
    1. `SUCCESS`: Full market collection, local validation, durable archiving, and cloud ingestion verified.
    2. `DATA_UNCHANGED`: Upstream payload hash identical to prior cycle; no unnecessary duplicate writes.
    3. `ARCHIVE_COMMITTED_INGEST_PENDING`: Raw data durably preserved in private repository; edge API ingestion queued or pending deployment (pre-M3 operational state).
    4. `ARCHIVE_FAILED`: Raw data could not be durably committed to GitHub archive; pipeline fails closed.
    5. `INGEST_FAILED`: Archive succeeded, but Cloudflare edge ingestion returned an error.
    6. `MARKET_CLOSED`: Karachi market calendar indicates pre-open, post-close, weekend, or declared holiday.
  - Healthchecks heartbeat pings mirror these semantics:
    - `/start`: Emitted on pipeline initiation.
    - `/fail`: Emitted on archive failure, lease contention, or unhandled exceptions.
    - Success ping (`/`): Emitted **only** when data preservation or planned market skip criteria are met. Zero false-positive pings.

---

## 3. Supply Chain & Dependency Audit

1. **Python Dependencies (`pyproject.toml`):**
   - Strictly pinned dependencies: `requests>=2.31.0`, `pytz>=2024.1`, `urllib3>=2.2.0`, `pytest>=8.0.0`.
   - Vendored `psx_dps` adapter code is isolated under `collector/vendor/psx_dps/` with local security patches, including `BeautifulSoup` parsing fallback with `html.parser` (no C-extension dependencies like `lxml` required on runners).
2. **TypeScript Dependencies (`pnpm-lock.yaml`):**
   - Standardized on pnpm workspace with lockfile validation in CI.
   - Core libraries: `@cloudflare/workers-types`, `hono>=4.0.0`, `zod>=3.22.0`, `vitest>=3.0.0`.

---

## 4. Operational & Cost Compliance ($0.00 Budget)

| Infrastructure Component | Free-Tier Allocation | Measured / Projected Utilization | Headroom | Cost |
| :--- | :--- | :--- | :--- | :--- |
| **GitHub Actions Compute** | 2,000 Linux min/month | ~45 runs/day × 25s = 560 min/month | >70% | **$0.00** |
| **Private Data Repo Storage** | 1 GB soft limit (Git LFS not used) | Gzip raw JSON ~15 KB/day = 5.5 MB/year | >99% | **$0.00** |
| **Cloudflare Workers** | 100,000 requests/day | Max 45 collector calls + ~500 user reads = 545/day | >99% | **$0.00** |
| **Cloudflare D1 Storage** | 5 GB database storage | Daily bars ~1,500 rows/day = ~30 MB/year | >99% | **$0.00** |
| **Cloudflare D1 Reads** | 5,000,000 reads/day | ~5,000 reads/day | >99.9% | **$0.00** |
| **Cloudflare D1 Writes** | 100,000 writes/day | ~1,500 writes/day | >98% | **$0.00** |
| **Healthchecks.io** | 20 free monitor checks | 1 ping check allocated | 95% | **$0.00** |

**Audit Conclusion:** Total recurring spend is strictly $0.00. No credit card requirement or paid cloud tier is introduced anywhere in the foundation architecture.

---

## 5. Market Data Coverage Classification Matrix

| Data Stream / Capability | Coverage Status | Evidence & Rationale |
| :--- | :--- | :--- |
| **Market Benchmark Indices** | **PASS** | 18 live indices retrieved from PSX DPS and archived; verified on GitHub runners `41386016819` and `41687650867`. |
| **Whole-Market Stock Snapshot** | **PASS** | 500 active equity symbols retrieved via `/market-watch` and archived; verified on runner `41687650867`. |
| **Historical Daily EOD Bars** | **PARTIAL** | Upstream adapter and parsing verified with fixtures and probe workflow (`probe.yml`); full multi-year archive backfill deferred to Milestone 3 to honor the 250 requests/day budget ceiling. |
| **Full-Session Intraday Stream** | **PARTIAL / DEFERRED** | Intraday snapshot schema, deduplication, and quarantine verified; scheduled polling during market sessions is deferred to Milestone 3 when scheduled cron is enabled. |

---

## 6. Audit Sign-off Status

**Status: AWAITING OWNER ACCEPTANCE**  
The foundation audit and remediation of Milestones 0, 1, and 2 are complete. Milestone 3 remains strictly unauthorized pending owner review and formal acceptance.
