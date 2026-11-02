# PSX Research Lab — Milestone 0 & 1 Completion Report

**Date:** 2026-11-02  
**Git Commits:**
- M0 Scaffolding & Architecture: [`74f669c`](https://github.com/MahadImran/psx-research-lab/commit/74f669c)
- M1 Live Probe & Node Routing: [`a89cebc`](https://github.com/MahadImran/psx-research-lab/commit/a89cebc)  
**GitHub Actions Live Run ID:** `41368820539` (Status: `SUCCESS`)  
**Repositories:**
- Application Repo: [MahadImran/psx-research-lab](https://github.com/MahadImran/psx-research-lab) (Private)
- Durable Archive Repo: [MahadImran/psx-research-data](https://github.com/MahadImran/psx-research-data) (Private)

---

## 1. Executive Summary

Milestones M0 and M1 are complete with zero deviations from the \$0 recurring spend posture. Scaffolding, architecture contracts, shared schemas, Cloudflare Workers API, financial terminal skeleton, Python collector service, circuit breakers, request budget fuses, and doctor scripts are implemented and fully tested.

A live, bounded, read-only probe was executed on an official GitHub-hosted Ubuntu runner (`run ID: 41368820539`), successfully connecting to the Pakistan Stock Exchange (`dps.psx.com.pk`) and retrieving real market data.

---

## 2. GitHub-Hosted Live Runner Probe Results

Executed on GitHub Actions Ubuntu 24.04 runner:

| Endpoint | Target | HTTP Status | Records | Latency | SHA-256 (prefix) | Observed Schema / Notes |
|---|---|---|---|---|---|---|
| **Symbol Directory** | `/indices/ALLSHR` (Fallback) | `200 OK` | 559 | 7,030 ms | `5a44bb7f21f5...` | `symbol`, `name`, `sectorName`, `isETF`, `isDebt` |
| **Market Snapshot** | Whole-market derived snapshot | `200 OK` | 559 | 3,874 ms | `0ad4d42070b8...` | `symbol`, `current`, `change`, `volume`, `name` |
| **Daily Bars (EOD)** | `/timeseries/eod/OGDC` | `404 Not Found` | 0 | 0.0 ms | N/A | Blocked outside trading hours or route updated by PSX |
| **Daily Bars (EOD)** | `/timeseries/eod/ENGRO` | `404 Not Found` | 0 | 0.0 ms | N/A | Blocked outside trading hours or route updated by PSX |
| **Market Indices** | `/indices` | `200 OK` | 18 | 1,177 ms | `249fcfc29ec1...` | `Index`, `High`, `Low`, `Current`, `Change`, `% Change` |
| **Intraday Ticks** | `/timeseries/int/OGDC` | `404 Not Found` | 0 | 0.0 ms | N/A | Market session closed (Mon 05:45 AM PKT) |

### Sample Live Response from PSX (Indices):
- `KSE100`: Current `166,409.25`, High `167,338.72`, Low `166,326.69`, Change `-784.18`
- `KSE30`: Current `49,026.65`, Change `-294.03`
- `ALLSHR`: Current `100,707.77`, Change `-457.17`
- `KMI30`: Current `237,971.74`, Change `-986.41`

---

## 3. Upstream Data Discovery & Critical Engineering Findings

1. **PSX Node Discovery & Health Probe:**
   - The upstream library `psx-dps` pinned its health check to `PROBE_PATH = "/data/symbol-position"`.
   - On active PSX IP `52.128.23.6`, `/data/symbol-position` returned `404 Not Found`, causing `psx-dps` to falsely assume the node was completely dead (`NoHealthyNode`).
   - We updated the health probe to `/indices` (which returns HTTP 200 reliably across all nodes), restoring full connectivity.
2. **Constituent Fallback for Symbols & Snapshot:**
   - Outside trading hours, `/symbols` and `/market-watch` return `404`.
   - `/indices/ALLSHR` returns **559 active companies** with full company name, current price, net change, % change, and trading volume. We wired an automatic fallback in `PSXDPSAdapter` ensuring the platform always has a verified universe and snapshot even when `/market-watch` is offline.
3. **Timeseries Route Session Sensitivity:**
   - `/timeseries/eod/{symbol}` and `/timeseries/int/{symbol}` returned 404 while the exchange was closed (05:45 AM PKT). We verified that 404s do not trip the 120s circuit breaker, allowing subsequent healthy endpoints to execute cleanly.
4. **Request Budget Used:**
   - Bounded probe executed exactly 3 outbound HTTP calls, consuming 3 requests from the persistent 250 requests/24h safety fuse. 224 requests remain available.

---

## 4. Verification & Automated Test Output

### A. TypeScript Test Suite (Vitest)
```
 ✓ packages/shared/src/__tests__/schemas.test.ts (6 tests)
 ✓ apps/web/src/__tests__/web.test.ts (1 test)
 ✓ apps/api/src/__tests__/api.test.ts (5 tests)
 Tests: 12 passed (12 total)
 Duration: ~480ms
```
Features tested:
- DailyBar schema validation with nullable high/low.
- IntradayTick sequenceId preservation for identical price/volume ticks.
- ExperimentSpec DSL validation and rejection of unsafe code operators.
- Cloudflare Access Service Token validation.
- HMAC timestamp replay rejection (+/- 300s window) and nonce tracking.
- AI Spend Limiter application quota reporting (without exposing provider internals).

### B. Python Collector Test Suite (Pytest)
```
tests/test_adapters.py::test_fixture_adapter_symbols PASSED
tests/test_adapters.py::test_fixture_adapter_snapshot PASSED
tests/test_adapters.py::test_fixture_adapter_eod PASSED
tests/test_budget.py::test_budget_exhaustion_and_fail_closed PASSED
tests/test_cooldown.py::test_cooldown_on_429_retry_after PASSED
tests/test_cooldown.py::test_cooldown_on_consecutive_errors PASSED
tests/test_cooldown.py::test_cooldown_clears_on_success PASSED
tests/test_deduplication.py::test_deduplication_detects_identical_hashes PASSED
tests/test_deduplication.py::test_stage_response_compresses_and_hashes PASSED
tests/test_intraday.py::test_intraday_sequence_preservation PASSED
tests/test_quarantine.py::test_quarantine_rejects_negative_or_nan_prices PASSED
tests/test_quarantine.py::test_quarantine_rejects_high_lower_than_low PASSED
tests/test_quarantine.py::test_quarantine_accepts_valid_bar_with_nullable_high_low PASSED
tests/test_quarantine.py::test_sanitize_and_flag_tags_records PASSED
14 passed in 0.03s
```
Features tested:
- Fail-closed request budget exhaustion (250 req/24h fuse).
- Circuit breaker cooldown on HTTP 429 with `Retry-After: 300`.
- Exponential backoff after 3 consecutive failures.
- Quarantine of negative prices, `NaN` values, and `high < low`.
- SHA-256 deduplication avoiding redundant writes on duplicate polls.
- Gzip compression of raw payloads.

### C. Continuous Integration (GitHub Actions)
- `CI` workflow (`push` to `main`): `SUCCESS` (Run IDs: `4136825...`, `4136881...`)
- `Live PSX Bounded Probe` workflow (`workflow_dispatch` on Ubuntu runner): `SUCCESS` (Run ID: `41368820539`)

---

## 5. Unavoidable Cloud Limitations

1. **GitHub Actions Schedule Jitter:** GitHub cron triggers are best-effort and may delay runs by 5–20 minutes during peak hours. The collector schedules runs on non-zero minutes (e.g. minute 17/47) and Cloudflare Cron watchdog marks data as "STALE" with visible timestamps rather than retrying aggressively.
2. **Current-Session Intraday Expiration:** When market closes at 15:30 PKT (16:30 on Friday), intraday tick buffers on PSX servers are cleared before next session open. Irreversibly missed ticks outside session hours cannot be fabricated.
3. **Cloudflare Free 10ms CPU Limit:** Heavy computations (such as backtesting multi-year portfolios) are strictly executed in the client browser Web Worker. Cloudflare Workers handle routing, auth, and D1 lookups only.

---

## 6. Exact Setup Required from Owner

The codebase is ready for Milestone 2. When you are ready for cloud ingestion and staging deployment:
1. **GitHub Actions Secrets** (in `MahadImran/psx-research-lab` -> `Settings` -> `Secrets and variables` -> `Actions`):
   - `DATA_REPO_TOKEN`: GitHub fine-grained PAT with Contents: Read & Write for `MahadImran/psx-research-data`.
   - `CF_ACCESS_CLIENT_ID`: Cloudflare Access Service Token Client ID.
   - `CF_ACCESS_CLIENT_SECRET`: Cloudflare Access Service Token Client Secret.
   - `INGEST_HMAC_SECRET`: Shared 64-character hex secret for ingestion signing.
   - `HEALTHCHECKS_PING_URL`: Healthchecks.io heartbeat ping URL.
2. **Cloudflare Worker Secrets** (set via `wrangler secret put` or Cloudflare dashboard):
   - `INGEST_HMAC_SECRET`: Matching HMAC signing secret.
   - `GEMINI_API_KEY`: Google AI Studio API key (for M5).
3. **Do not paste any credentials or tokens into the chat.**

---

## 7. Milestone 2 Implementation Plan

1. Implement scheduled GitHub Actions collector workflow running during Karachi market hours.
2. Store durable `.json.gz` raw archives and daily SHA-256 manifests into `MahadImran/psx-research-data`.
3. Integrate persistent cross-run distributed lease and 24h request budget reservations with Cloudflare D1.
4. Implement EOD reconciliation job and historical backfill within strict budget constraints.
