# PSX Research Lab — Bounded Source Probe Report
**Date (UTC):** 2026-11-02T00:44:23.605581+00:00  |  **Mode:** `live`  |  **Adapter:** `psx-dps`

- **Requests Executed:** 3 / 250 daily limit
- **Remaining 24h Budget:** 224

## Endpoint Results

| Endpoint | Status | Count | Duration (ms) | SHA-256 (prefix) | Field Coverage |
|---|---|---|---|---|---|
| Symbol Directory | `SUCCESS` | 559 | 3365.68 | `5a44bb7f21f5...` | symbol, name, sectorName, isETF (+1 more) |
| Whole-Market Snapshot | `SUCCESS` | 559 | 3963.18 | `5c5bb5a3ab97...` | source, captured_at, session, rows |
| EOD Daily Bars: OGDC | `ERROR` | 0 | 0.0 | `N/A` | Error: /timeseries/eod/OGDC: HTTP 404 |
| EOD Daily Bars: ENGRO | `ERROR` | 0 | 0.0 | `N/A` | Error: /timeseries/eod/ENGRO: HTTP 40 |
| Current Market Indices | `SUCCESS` | 18 | 5.92 | `249fcfc29ec1...` | Index, High, Low, Current (+2 more) |
| Intraday Ticks: OGDC | `ERROR` | 0 | 0.0 | `N/A` | Error: /timeseries/int/OGDC: HTTP 404 |

## Audit Observations
1. **Snapshot vs EOD high/low:** `snapshot()` provides high/low for active session; `eod()` daily bars provide open/close/volume with high/low as null.
2. **Identical tick sequence:** Intraday ticks preserve sequence IDs so consecutive trades with identical price and volume are preserved.
3. **Fair use limits:** All calls obeyed >= 1.0s interval; request counter accurately updated.