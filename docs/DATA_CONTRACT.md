# PSX Research Lab — Data Contract

**Canonical Timezone:** `Asia/Karachi` (PKT: UTC+5)  
**System Audit Timezone:** `UTC` (ISO 8601)  
**Data Provenance:** Recorded for every observation (`source`, `fetched_at_utc`, `trading_date`, `payload_sha256`)

---

## 1. Daily Bar Contract (`daily_bars`)
- **Identity:** `(source, symbol, trading_date, revision)`
- **Open / Close / Volume:** Non-negative, finite numbers.
- **High / Low Nullability:** In primary source `psx-dps`, the `eod(symbol)` endpoint returns `[date, open, close, volume]` and does not supply daily high/low. Consequently, `high` and `low` are **nullable**. The system explicitly does NOT fabricate high/low when missing.
- **Revisioning:** Revisions increment from `0`. Only the latest accepted revision has `is_active = 1`.

## 2. Whole-Market Snapshot Contract (`snapshots`)
- **Coverage:** Approximately 496 actively trading tickers in a single HTTP request to `/market-watch`.
- **Session Semantics:** Captured with `Asia/Karachi` session indicator (`PRE_OPEN`, `REGULAR_SESSION`, `FRIDAY_BREAK`, `POST_CLOSE`).
- **Listed vs Trading:** `symbols()` contains ~1,029 listed entities. Absence from daily snapshot indicates no trades occurred today, not delisting.

## 3. Intraday Tick Sequence Contract (`intraday_ticks`)
- **Identity:** `(symbol, trading_date, sequence_id)`
- **Sequence Preservation:** PSX frequently reports identical trades (e.g. 500 shares at 135.00 multiple times within the same second). The primary key relies on the monotonic `sequence_id` to prevent dropped ticks.

## 4. Upstream Budget Contract
- Rolling 24-hour limit: `<= 250 requests`.
- Failure mode: Fail closed. If remaining count is `0`, all adapters immediately abort and preserve the previous valid serving version.

## 5. Quarantine Criteria
A record is quarantined (`is_quarantined = 1`, `quarantine_reason = '...'`) if:
1. `close <= 0` or `open <= 0` or `volume < 0`
2. `high` and `low` are non-null but `high < low`
3. Prices contain `NaN` or non-numeric tokens
4. Missing required symbol or invalid date string
Quarantined records are stored for audit but excluded from active backtesting and terminal views.
