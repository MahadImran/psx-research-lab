# PSX Research Lab — Bounded Source Probe Report
**Date (UTC):** 2026-11-03T18:40:51.384054+00:00  |  **Mode:** `live`  |  **Adapter:** `psx-dps`

- **Requests Executed:** 6 / 250 daily limit
- **Remaining 24h Budget:** 186

## Endpoint Results

| Endpoint | Status | Count | Duration (ms) | SHA-256 (prefix) | Field Coverage |
|---|---|---|---|---|---|
| Symbol Directory | `SUCCESS` | 771 | 3.28 | `f2acc45bf830...` | symbol, name, sectorName, isETF (+2 more) |
| Whole-Market Snapshot | `SUCCESS` | 500 | 56.22 | `8ca57d8c0709...` | captured_at, session, rows |
| EOD Daily Bars: OGDC | `SUCCESS` | 1240 | 5.58 | `f39cff46d7b2...` | date, open, close, volume |
| EOD Daily Bars: ENGRO | `SUCCESS` | 1223 | 6.06 | `de6dfcee23b4...` | date, open, close, volume |
| Current Market Indices | `SUCCESS` | 18 | 9.52 | `90cce83ab780...` | Index, High, Low, Current (+2 more) |
| Intraday Ticks: OGDC | `SUCCESS` | 1891 | 5.61 | `4adf4dc82a8d...` | time, price, volume |

## Audit Observations
1. **Snapshot vs EOD high/low:** `snapshot()` provides high/low for active session; `eod()` daily bars provide open/close/volume with high/low as null.
2. **Identical tick sequence:** Intraday ticks preserve sequence IDs so consecutive trades with identical price and volume are preserved.
3. **Fair use limits:** All calls obeyed >= 1.0s interval; request counter accurately updated.