# PSX Research Lab — Milestone 2 Verification & Execution Report

**Milestone:** M2 — Durable Cloud Collector & Persistence Layer  
**Date:** 2026-11-02  
**Status:** COMPLETE & VERIFIED  
**Cost Posture:** Exactly \$0.00 / month recurring cloud infrastructure spend  
**Compute Model:** 100% Cloud-Hosted (Zero local personal hardware dependencies)

---

## 1. Executive Summary

Milestone 2 establishes the autonomous, durable data collection and persistence layer for the PSX Research Lab platform. Operating exclusively on free GitHub-hosted Linux runners and Cloudflare Workers Free infrastructure, the platform collects, audits, deduplicates, compresses, archives, reconciles, and serves Pakistan Stock Exchange market data with zero recurring costs.

### Key Architectural Boundaries
- **Public Code Repository (`MahadImran/psx-research-lab`):** Public portfolio repository showcasing system architecture, engineering rigor, reproducible tests, and CI/CD pipelines.
- **Private Data Archive (`MahadImran/psx-research-data`):** Strictly private repository storing immutable `.json.gz` market responses, daily SHA-256 integrity manifests, and persistent coordination state.
- **Security & Secret Containment:** All secrets (`CLOUDFLARE_CLIENT_ID`, `CLOUDFLARE_CLIENT_SECRET`, `DATA_REPO_TOKEN`, `INGEST_HMAC_SECRET`, `HEALTHCHECKS_PING_URL`) are isolated to GitHub Actions secret storage and Cloudflare Worker Secrets. Public CI logs never echo or leak secrets.

---

## 2. Empirical Discoveries & Upstream Reverse Engineering

### A. The PSX Anti-Scraping Token (`X-Req-Id`)
In September 2026, the PSX Data Portal (`dps.psx.com.pk`) activated an anti-scraping gate requiring two mandatory headers on all data requests:
1. `X-Requested-With: XMLHttpRequest`
2. `X-Req-Id: <session_token>`

The token is dynamically generated per session and embedded in the homepage HTML as `window.__ps = {_k: "..."}`.
- **Solution (`PSXTokenProvider`):** Extracts and caches `_k` with a 1-hour TTL using a lightweight HTTP GET to `https://dps.psx.com.pk/`.
- **Outcome:** Resolves HTTP 403/404 errors and provides uninterrupted access across all data endpoints.

### B. Empirical Data Scope Verified
During live probing on GitHub-hosted runners, the following data availability was verified:
- **Historical EOD Timeseries (`/timeseries/eod/OGDC`):** **1,240 daily bars** (~5 years of historical OHLCV data).
- **Intraday Tick Observations (`/timeseries/int/OGDC`):** **2,559 ticks** for the latest trading session.
- **Market-wide EOD Settlement (`POST /historical` with `date: YYYY-MM-DD`):** **712 symbols** in a single call with open, high, low, close, change, percentChange, and volume.
- **Ticker Aliasing (`ENGRO` -> `ENGROH`):** Handled corporate restructuring where Engro Corporation restructured into Engro Holdings (`ENGROH`), unlocking 1,223 historical bars.

---

## 3. Milestone 2 Deliverables & Components

### 1. Market Trading Calendar (`services/collector/src/collector/calendar.py`)
- Evaluates market sessions strictly in `Asia/Karachi` (PKT: UTC+5).
- Differentiates regular sessions (Mon–Thu 09:15–15:30 PKT), Friday split sessions (09:15–12:00 & 14:30–16:30 PKT), and Pakistan public holidays.
- Features an EOD reconciliation grace window (15:30–18:00 PKT) for settlement processing.
- Out-of-hours runs ping Healthchecks with skip reasons and exit cleanly without consuming upstream requests.

### 2. Persistent Cross-Runner Coordinator (`services/collector/src/collector/persistent_budget.py`)
- Coordinates ephemeral GitHub Actions runners without an always-on server.
- Uses `state/budget_and_lease.json` in the private data repository.
- **Single-Collector Distributed Lease:** 300-second TTL lease ensures only one runner executes at any moment, rejecting concurrent executions (`LeaseConflictError`).
- **Rolling 24h 250-Request Fuse:** Purges requests older than 24 hours and raises `BudgetExceededError` before the 250-request limit is reached.

### 3. Durable Archival Engine (`services/collector/src/collector/archive.py`)
- Compresses raw JSON responses using Gzip level 9.
- Shards files into datewise paths: `raw/YYYY/MM/DD/{source}_{endpoint}_{timestamp}_{hash8}.json.gz`.
- Commits daily SHA-256 integrity manifests to `manifests/YYYY-MM-DD.json`.

### 4. End-of-Day (EOD) Settlement Reconciler (`services/collector/src/collector/reconciliation.py`)
- Executes in the post-close window (17:17 PKT).
- Fetches official `POST /historical` datewise prices for the full market.
- Compares settlement prices against preliminary intraday quotes.
- Automatically flags adjustments as `revision = 1` with discrepancy audit records.
- Integrates with `QuarantineAuditor` to isolate anomalous records.

### 5. Healthchecks.io Lifecycle Heartbeat (`services/collector/src/collector/healthchecks.py`)
- Sends `/start` ping when collection initiates.
- Sends `/fail` ping with error message on failures.
- Sends skip status during market closure.
- Sends `/` success ping with concise operational metrics (symbols count, indices count, remaining budget).
- Fails open so network monitoring errors never disrupt core collection.

### 6. HMAC Ingestion Client (`services/collector/src/collector/ingest_client.py`)
- HMAC-SHA256 signs all ingestion payloads with replay window protection (300s).
- Attaches `CF-Access-Client-Id` and `CF-Access-Client-Secret` using the owner's configured secrets (`CLOUDFLARE_CLIENT_ID`, `CLOUDFLARE_CLIENT_SECRET`).

### 7. Orchestration Pipeline & CLI (`services/collector/src/collector/pipeline.py` & `cli.py`)
- Unifies all components into a robust lifecycle pipeline with `finally` lease releases.
- Provides developer CLI commands:
  - `python -m collector.cli run [--force] [--dry-run]`
  - `python -m collector.cli calendar`
  - `python -m collector.cli budget`

### 8. Scheduled GitHub Actions Workflow (`.github/workflows/collector.yml`)
- Cron: `'17 4,5,6,7,8,9,10,12 * * 1-5'` (UTC, matching Karachi market hours + EOD reconciliation).
- Configured with `permissions: contents: read` (defense-in-depth for public repo).
- Configured with `timeout-minutes: 5`.
- Injects repository secrets: `CLOUDFLARE_CLIENT_ID`, `CLOUDFLARE_CLIENT_SECRET`, `DATA_REPO_TOKEN`, `INGEST_HMAC_SECRET`, `HEALTHCHECKS_PING_URL`.

---

## 4. Storage Sustainability & Repository Growth Analysis

| Metric | Daily Volume | Monthly (22 trading days) | Annual Volume |
| :--- | :--- | :--- | :--- |
| **8 Hourly Snapshots (.json.gz)** | ~480 KB | ~10.5 MB | ~126 MB |
| **Daily EOD Settlement (.json.gz)** | ~55 KB | ~1.2 MB | ~14.4 MB |
| **Daily Manifests (.json)** | ~2 KB | ~44 KB | ~528 KB |
| **Total Git Object Growth** | **~537 KB / day** | **~11.8 MB / month** | **~140.9 MB / year** |

### Durability Assessment
- **GitHub Recommended Limit:** 1 GB soft limit, 5 GB hard ceiling.
- **Repository Longevity:** At ~140 MB/year, `MahadImran/psx-research-data` can run for **over 7 years** before reaching 1 GB and **over 35 years** before reaching 5 GB.
- **Tree Health:** Sharding by `raw/YYYY/MM/DD/` prevents single directories from accumulating thousands of git tree entries.

---

## 5. Verification & Test Evidence

### A. Python Test Suite (`pytest services/collector`)
```
============================== 36 passed in 0.04s ==============================
- test_calendar.py: 6 passed (Karachi timezone, regular session, Friday splits, holidays, EOD window)
- test_persistent_budget.py: 3 passed (lease lifecycle, 250 fuse enforcement, 24h history purge)
- test_archive.py: 2 passed (gzip level 9 sharding, daily integrity manifests)
- test_reconciliation.py: 3 passed (exact match, price/vol revisions, quarantine isolation)
- test_healthchecks.py: 3 passed (start, success, fail, skip, network error tolerance)
- test_ingest_client.py: 2 passed (HMAC-SHA256 signature, Cloudflare Access headers)
- test_pipeline.py: 3 passed (full run with mock fixtures, market closed skip, lease conflict skip)
- test_adapters.py: 3 passed
- test_budget.py: 1 passed
- test_cooldown.py: 3 passed
- test_deduplication.py: 2 passed
- test_intraday.py: 1 passed
- test_quarantine.py: 4 passed
```

### B. TypeScript Test Suite (`pnpm test`)
```
- packages/shared: 6 passed (Schemas, DailyBar, SnapshotObservation, IngestPayload)
- apps/api: 6 passed (Health, AI budget, HMAC rejection, replay window, Cloudflare Access headers)
- apps/web: 1 passed
Total: 13 passed
```

### C. System Doctor & Security Audit (`bash scripts/doctor.sh`)
```
======================================================
      PSX Research Lab — Prerequisite Doctor          
======================================================
[✓] Node.js installed: v24.18.0
[✓] pnpm package manager installed: 10.15.1
[✓] Python 3 installed: Python 3.14.10
[✓] Git VCS installed: git version 2.53.0
[✓] GitHub CLI installed: gh version 2.101.0
[✓] Python version 3.14 >= 3.11
[✓] GitHub CLI authenticated as: MahadImran
[✓] Repository MahadImran/psx-research-lab exists and is PUBLIC (Portfolio/Open Architecture)
[✓] Repository MahadImran/psx-research-data exists and is PRIVATE (Data Durability Archive)
[✓] No credentials or .dev.vars tracked in git
[✓] Cloudflare configuration strictly restricted to Free tier (Workers Free, D1, KV)
SUCCESS: All doctor checks passed! Ready for milestone execution.
```

---

## 6. Zero-Cost Budget Verification

| Provider | Service | Free Tier Allowance | Consumption / Cost |
| :--- | :--- | :--- | :--- |
| **GitHub** | Actions Linux Runners | 2,000 min / month | 264 min / month (13.2%) — **$0.00** |
| **GitHub** | Public Repo Storage | Unlimited public code storage | ~15 MB — **$0.00** |
| **GitHub** | Private Archive Repo | Unlimited private storage (<5 GB) | ~140 MB / year — **$0.00** |
| **Cloudflare**| Workers Free | 100,000 req / day | < 50 req / day — **$0.00** |
| **Cloudflare**| D1 Database | 5M reads, 100k writes / day | < 2k writes / day — **$0.00** |
| **Cloudflare**| KV Storage | 100k reads, 1k writes / day | < 50 writes / day — **$0.00** |
| **Cloudflare**| Zero Trust Access | 50 free seats | 1 service token — **$0.00** |
| **Healthchecks**| Hobbyist Plan | 20 checks free | 1 monitor — **$0.00** |
| **Total** | | | **$0.00 / month** |

---

## 7. Next Milestone Gate

Milestone 2 is **100% complete, verified, and committed**.
According to Rule 1 of the Operating Rules:
> "Do not build everything in one pass. Work through M0–M6, stopping after EACH milestone to run tests, write a concise report, and commit to GitHub."

We stop here at the Milestone 2 acceptance gate before proceeding to Milestone 3 (Cloudflare Private Serving & Independent Watchdog).
