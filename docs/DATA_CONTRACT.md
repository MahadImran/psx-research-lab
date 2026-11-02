# PSX Research Lab — Data Contract

**Canonical Market Timezone:** `Asia/Karachi` (PKT: UTC+5)  
**System Audit Timezone:** `UTC` (ISO 8601)  
**Data Provenance:** Recorded for every observation (`source`, `fetched_at_utc`, `trading_date`, `payload_sha256`)  
**Storage Architecture:** Dual-Repository (Public App / Private Data Archive)

---

## 1. Primary Upstream Source: `dps.psx.com.pk` (`psx-dps`)

### Authentication & Header Enforcement
- **Dynamic Session Token:** Extracted dynamically from `https://dps.psx.com.pk/` via `PSXTokenProvider`.
- **Mandatory Headers:**
  - `X-Req-Id: <_k token>`
  - `X-Requested-With: XMLHttpRequest`
  - `Referer: https://dps.psx.com.pk/`
  - `Accept-Encoding: gzip, deflate`

### Empirical Endpoint Verified Shapes
1. **Whole-Market Board Snapshot:**
   - Path: `/market-watch`
   - Scope: ~496 actively trading tickers in a single HTTP call
   - Payload: Array of `[symbol, current, change, percentChange, volume, high, low]`
2. **Historical EOD Timeseries:**
   - Path: `/timeseries/eod/<SYMBOL>`
   - Scope: 1,240 daily bars (~5 years of trading history) per symbol
   - Fields: `[trading_date, open, close, volume]`
   - High/Low Nullability: High/Low are omitted in `/timeseries/eod/` responses and therefore nullable in `daily_bars`. They are never fabricated.
3. **Intraday Tick Observations:**
   - Path: `/timeseries/int/<SYMBOL>`
   - Scope: 2,500+ tick observations per liquid symbol (e.g. `OGDC`, `ENGROH`)
   - Sequence preservation: monotonic `sequence_id` preserves identical price/volume ticks.
4. **Market-wide EOD Settlement by Date (EOD Reconciliation):**
   - Path: `POST /historical` with body `{"date": "YYYY-MM-DD"}`
   - Scope: 712 symbols for that trading day
   - Fields: `open`, `high`, `low`, `close`, `change`, `percentChange`, `volume`
5. **Ticker Aliases & Restructurings:**
   - `ENGRO` restructured into `ENGROH` and `EFERT`. Requests for `ENGRO` map to `ENGROH`.

---

## 2. Daily Bar Contract (`daily_bars`)
- **Identity:** `(source, symbol, trading_date, revision)`
- **Open / Close / Volume:** Non-negative, finite numbers.
- **Revisioning:** Revisions increment from `0`. Only the latest accepted revision has `is_active = 1`.
- **Settlement Discrepancies:** When post-close settlement prices from `POST /historical` adjust preliminary intraday quotes, a new revision (`revision = 1`) is created with an audit trail in `discrepancies`.
- **Data Quality Grades:**
  - `GRADE_A`: Complete OHLCV bars satisfying strict geometric invariants.
  - `GRADE_B`: Valid price bars with nullable High/Low (benchmark indices).
  - `GRADE_C`: Volume-only or synthetic baseline records.
  - `QUARANTINE`: Isolated defective records.

---

## 3. Storage Sustainability & Repository Growth

### Storage Growth Analysis
- **Daily Snapshot:** 8 hourly runs/trading day * ~60 KB compressed `.json.gz` = **~480 KB / trading day**.
- **Daily EOD Datewise Settlement:** 1 file/trading day * ~55 KB compressed = **~55 KB / trading day**.
- **Daily Manifest:** 1 file/trading day * ~2 KB = **~2 KB / trading day**.
- **Monthly Volume (22 trading days):** ~11.8 MB / month.
- **Annual Volume:** **~140 MB / year**.

### Realistic Durability Limits & Lifecycle Management
- **Annual Growth:** ~140 MB / year of compressed `.json.gz` files.
- **Git Repository Dynamics:**
  - **Years 1–3 (< 500 MB):** Direct Git tree operations and API commits perform efficiently. Shallow clones (`fetch-depth: 1`) in GitHub Actions remain under 5 seconds.
  - **Years 3–5 (500 MB – 1 GB):** Reaches GitHub's soft recommended repository size.
  - **Mitigation & Retention Strategy:** Annual archive releases (`git bundle` or release tarballs) preserve long-term history while active working repository keeps recent 24-month rolling history.
- **Recovery Objectives (RPO / RTO):**
  - **RPO (Recovery Point Objective):** 1 trading day (nightly immutable raw commit).
  - **RTO (Recovery Time Objective):** < 15 minutes (shallow clone from private GitHub archive + D1 batch schema rehydration).

---

## 4. Cumulative Integrity Manifest Contract (`manifests/YYYY-MM-DD.json`)
```json
{
  "manifestVersion": "1.0.0",
  "tradingDate": "2026-11-02",
  "generatedAtUtc": "2026-11-02T04:00:28Z",
  "verifiedArchiveFiles": [
    "raw/2026/11/02/dps_index_summary_gha-41386016819.json.gz",
    "raw/2026/11/02/dps_snapshot_gha-41386016819.json.gz"
  ],
  "cycles": [
    {
      "runId": "gha-41386016819",
      "timestamp": "2026-11-02T04:00:28Z",
      "recordCount": 1,
      "sha256": "6d50694ec3269d0d8cb30bfd30a47f02ea26871a9bf28151f11e9f131a4cbb79"
    }
  ]
}
```

---

## 5. Quarantine & Geometry Criteria
A record is quarantined (`is_quarantined = 1`, `quarantine_reason = '...'`, `dataGrade = 'QUARANTINE'`) if:
1. `close <= 0` or `open <= 0` or `volume < 0`
2. `high` and `low` are non-null and `high < low`
3. Geometric candle violation: `high < max(open, close)` or `low > min(open, close)`
4. Prices contain `NaN` or non-numeric tokens
5. Missing required symbol or invalid date format
