# PSX Research Lab — Data Quality Audit & Source Specification

**Status:** AWAITING OWNER ACCEPTANCE  
**Date:** 2026-11-03  
**Target:** Pakistan Stock Exchange (PSX) Data Ingestion & Storage Pipeline  

---

## 1. Upstream Data Sources & Format Reality

PSX Research Lab interfaces with upstream PSX data interfaces to extract historical and intraday market observations.

### 1.1 Source Inventory & Endpoints

| Source Adapter | Upstream Host | Ingestion Mode | Data Granularity | Authentication |
| :--- | :--- | :--- | :--- | :--- |
| **`psx-dps` (Primary)** | `dps.psx.com.pk` | HTTP GET / POST | Intraday Snapshots, EOD Summary, Index Aggregates | Dynamic Session Token & Cookie |
| **`psxdata` (Secondary)** | `psxdata.com` | HTTP GET | Historical Daily EOD Bars, Sector Breakdowns | Unauthenticated Web Endpoint |
| **`psxpert` (Historical Seed)** | Offline Archive Fixtures | Static File Ingestion | Multi-Year Daily OHLCV Seed | Static / Local File Archive |

---

## 2. PSX Data Schema Realities & Nullability Rules

A critical finding of our empirical source audit is that **upstream PSX feeds exhibit distinct payload structures across different endpoints and session timings**.

### 2.1 Index Summary Table (`/dps_table.php`)
- **Observed Behavior:** Upstream HTML table fragments for benchmark indices (`KSE100`, `KSE30`, `KMI30`, `ALLSHR`, etc.) provide High, Low, Current, and Change fields. However, secondary index rows and auxiliary feeds can intermittently omit or zero intraday High and Low values.
- **Empirical Runner Extraction Example (Job ID `125086927135`, Timestamp `2026-11-02T04:00:28.190Z`):**
  ```json
  {
    "Index": "KSE100",
    "High": "167338.72",
    "Low": "166326.69",
    "Current": "166409.25",
    "Change": "0",
    "% Change": "0"
  }
  ```
- **Architectural Decision:** To ensure resilience against auxiliary index feeds where High and Low are not published, schema definitions in `packages/shared/src/schemas/market.ts` and `QuarantineAuditor` treat `high` and `low` as `Optional[float]` (`dataGrade: GRADE_B`). When High and Low are provided, geometric invariants are strictly enforced.

### 2.2 Whole-Market Equity Snapshot (`/market-watch`)
- **Observed Behavior:** The PSX DPS whole-market equity watch endpoint reliably yields **500 active symbols** with complete OHLCV parameters (Open, High, Low, Current/Close, Volume).
- **Geometric Invariants Enforced (`GRADE_A`):**
  $$\text{High} \ge \max(\text{Open}, \text{Close})$$
  $$\text{Low} \le \min(\text{Open}, \text{Close})$$
  $$\text{High} \ge \text{Low}$$
  $$\text{Volume} \ge 0$$
  $$\text{Close} > 0 \quad \text{and} \quad \text{Open} > 0$$

---

## 3. Data Quality Classification System

To guarantee that downstream backtesting and analytics engines never consume corrupted records while preserving valid index observations, we introduced a 4-tier Data Quality Grade:

```mermaid
flowchart TD
    Raw[Raw Upstream Record] --> Parse[HTML / JSON Parser]
    Parse --> Sanitize[Sanitize Types & Strip Formatting]
    Sanitize --> QA{Quarantine Auditor}
    
    QA -->|Negative Price / NaN / Geometry Violation| Quarantined[QUARANTINE: Isolated in Table]
    QA -->|Complete OHLCV + Geometric Invariants Pass| GradeA[GRADE_A: Production Tier]
    QA -->|Valid Price + Nullable High/Low| GradeB[GRADE_B: Production Index Tier]
    QA -->|Volume-Only / Synthetic Baseline| GradeC[GRADE_C: Analytical Marker]
```

### 3.1 Grade Definitions

| Grade | Identifier | Characteristics | Allowed Destinations |
| :--- | :--- | :--- | :--- |
| **Tier 1** | `GRADE_A` | Full OHLCV candle. `High >= max(Open, Close)`, `Low <= min(Open, Close)`. No nulls. | Production D1 `daily_bars`, Backtester, Analytics Engine |
| **Tier 2** | `GRADE_B` | Valid Close/Current price and Volume. Nullable High/Low (Index summaries). | Production D1 `daily_bars`, Benchmark Tracking |
| **Tier 3** | `GRADE_C` | Synthetic baseline or partial volume tick without full price bounds. | Diagnostic Analytics, Volume Aggregation |
| **Quarantine** | `QUARANTINE` | Geometric violations, negative prices, NaNs, missing timestamps. | Quarantine Logs, Alert Trigger; **Blocked from Backtester** |

---

## 4. Sanitization & Normalization Protocol

Before validation and archiving, all raw inputs undergo deterministic normalization:
1. **Number Formatting:** Pakistani numerical formatting (e.g. `166,409.25` with commas) is cleaned and parsed to standard IEEE 754 floating-point numbers.
2. **Timestamp Alignment:**
   - Raw dates are anchored to the Karachi market timezone (`Asia/Karachi`, UTC+5).
   - Ingestion timestamps are stored in strict ISO 8601 UTC format (`YYYY-MM-DDTHH:MM:SSZ`).
3. **Symbol Canonicalization:**
   - Equity tickers are trimmed and capitalized (e.g. `"SYS " -> "SYS"`).
   - Benchmark index tickers are mapped to canonical constants (`KSE100`, `KSE30`, `KMI30`, `ALLSHR`).
4. **Idempotent Deduplication:**
   - Payloads are hashed using SHA-256 (`recordHash`).
   - Identical hashes across consecutive polling cycles are classified as `DATA_UNCHANGED` to prevent duplicate D1 writes.

---

## 5. Known Upstream Limitations & Tolerances

1. **DPS Index Scraping Latency:** PSX DPS updates index web fragments asynchronously; intraday ticks can lag physical floor execution by 30–90 seconds.
2. **End-of-Day Settlement Adjustments:** Final closing prices may undergo minor official revisions up to 30 minutes post-session close (16:30 PKT). The reconciliation module detects and logs price revisions (`PRICE_REVISION_DETECTED`).
3. **Historical Data Gaps:** Historical seed data prior to 2018 may contain intermittent holidays without formal notices. The calendar validator treats unannounced closures gracefully as `MARKET_CLOSED`.

---

## 6. Market Data Coverage Classification Matrix

| Data Stream / Capability | Coverage Status | Evidence & Rationale |
| :--- | :--- | :--- |
| **Market Benchmark Indices** | **PASS** | 18 live indices retrieved from PSX DPS and archived; verified on GitHub runners `41386016819` and `41687650867`. |
| **Whole-Market Stock Snapshot** | **PASS** | 500 active equity symbols retrieved via `/market-watch` and archived; verified on runner `41687650867`. |
| **Historical Daily EOD Bars** | **PARTIAL** | Upstream adapter and parsing verified with fixtures and probe workflow (`probe.yml`); full multi-year archive backfill deferred to Milestone 3 to honor the 250 requests/day budget ceiling. |
| **Full-Session Intraday Stream** | **PARTIAL / DEFERRED** | Intraday snapshot schema, deduplication, and quarantine verified; scheduled polling during market sessions is deferred to Milestone 3 when scheduled cron is enabled. |
