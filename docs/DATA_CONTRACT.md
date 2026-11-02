# PSX Research Lab — Data Contract

**Canonical Market Timezone:** `Asia/Karachi` (PKT: UTC+5)  
**System Audit Timezone:** `UTC` (ISO 8601)  
**Data Provenance:** Recorded for every observation (`source`, `fetched_at_utc`, `trading_date`, `payload_sha256`)  
**Storage Architecture:** Dual-Repository (Public App / Private Data Archive)

---

## 1. Primary Upstream Source: `dps.psx.com.pk` (`psx-dps`)

### Authentication & Header Enforcement
Since September 2026, PSX enforces an anti-scraping session token:
- **Session Token Extraction:** Extracted dynamically from `https://dps.psx.com.pk/` via regex pattern `window\.__ps\s*=\s*(\{.*?\})` -> property `_k`.
- **Mandatory Headers:**
  - `X-Req-Id: <_k token>`
  - `X-Requested-With: XMLHttpRequest`
  - `Referer: https://dps.psx.com.pk/`
  - `Accept-Encoding: gzip, deflate`
- **Tls Pinning & Health Discovery:** TLS connections validate real hostname `dps.psx.com.pk` with SNI against pinned IP addresses. Node health is probed against `/indices` (returns 200 with 18 indices across all active nodes).

### Empirical Endpoint Verified Shapes
1. **Whole-Market Board Snapshot:**
   - Path: `/market-watch` (or `/data/symbol-position` fallback via 559 `ALLSHR` constituents)
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
   - `ENGRO` was restructured into `ENGROH` (Engro Holdings Ltd) and `EFERT`. Requests for `ENGRO` are mapped to `ENGROH` to retrieve all 1,223 daily bars and 876 intraday ticks.

---

## 2. Daily Bar Contract (`daily_bars`)
- **Identity:** `(source, symbol, trading_date, revision)`
- **Open / Close / Volume:** Non-negative, finite numbers.
- **Revisioning:** Revisions increment from `0`. Only the latest accepted revision has `is_active = 1`.
- **Settlement Discrepancies:** When post-close settlement prices from `POST /historical` adjust preliminary intraday quotes, a new revision (`revision = 1`) is created with an audit trail in `discrepancies`.

---

## 3. Storage Sustainability & Repository Growth

### Storage Growth Analysis
- **Daily Snapshot:** 8 hourly runs/trading day * ~60 KB compressed `.json.gz` = **~480 KB / trading day**.
- **Daily EOD Datewise Settlement:** 1 file/trading day * ~55 KB compressed = **~55 KB / trading day**.
- **Daily Manifest:** 1 file/trading day * ~2 KB = **~2 KB / trading day**.
- **Monthly Volume (22 trading days):** ~11.8 MB / month.
- **Annual Volume:** **~140 MB / year**.

### Sustainability Limits
- **GitHub Repository Recommendation:** 1 GB soft recommendation, 5 GB hard ceiling.
- **Projected Lifespan:** At ~140 MB/year, `MahadImran/psx-research-data` can operate for **over 7 years** before reaching 1 GB, and over 35 years before reaching 5 GB.
- **Tree Health:** All files are sharded into `raw/YYYY/MM/DD/` and `manifests/YYYY-MM-DD.json`, preventing directory bloat and maintaining fast git operations.

---

## 4. Integrity Manifest Contract (`manifests/YYYY-MM-DD.json`)
```json
{
  "manifestVersion": "1.0.0",
  "generatedAtUtc": "2026-11-02T12:17:00Z",
  "tradingDate": "2026-11-02",
  "source": "psx-dps",
  "totalBars": 712,
  "totalSnapshots": 496,
  "totalIndices": 18,
  "payloadSha256": "8f3...64-char-hex",
  "archivePath": "raw/2026/11/02/psx-dps_snapshot_121700Z_4a8b1c2d.json.gz"
}
```

---

## 5. Quarantine Criteria
A record is quarantined (`is_quarantined = 1`, `quarantine_reason = '...'`) if:
1. `close <= 0` or `open <= 0` or `volume < 0`
2. `high` and `low` are non-null but `high < low`
3. Prices contain `NaN` or non-numeric tokens
4. Missing required symbol or invalid date format
Quarantined records are isolated and excluded from active serving.
