# Milestone 1 (M1) Acceptance & Verification Document

**Milestone:** M1 — Data Acquisition & Single Collector Architecture  
**Status:** ACCEPTED & LOCKED  
**Verification Date:** 2026-11-02  
**Sign-off Criteria:** Real live upstream responses recorded on GitHub runners, single-collector ownership, session token negotiation, defensive parsing, strict request rate limits, and 429 cooldowns.

---

## 1. M1 Scope & Objectives

Milestone 1 implements the data acquisition tier for Pakistan Stock Exchange market data:
- Dedicated collector engine owning all outbound PSX requests.
- Multi-source adapter architecture: `psx-dps` as primary, `psxdata` as fallback, and historical seed fixtures.
- Dynamic session cookie and token provider (`PSXTokenProvider`).
- Strict request rate limiting and 429 `Retry-After` cooldown mechanics.
- Defensive HTML table fragment extraction resilient against malformed markup.
- Live runner verification against live PSX endpoints without proxy rotation or source flooding.

---

## 2. Requirement Verification Matrix

| Requirement | Specification Contract | Implementation Artifact | Status | Verification Evidence |
| :--- | :--- | :--- | :--- | :--- |
| **Single Collector Ownership** | Only one active collector processes upstream data at any time. | `services/collector/src/collector/persistent_budget.py` | **VERIFIED** | Lease mechanism prevents concurrent runners from hitting upstream simultaneously. |
| **Primary Adapter (`psx-dps`)** | Direct acquisition from official PSX DPS endpoints. | `collector/vendor/psx_dps/` | **VERIFIED** | Live index and quote scraping verified on GitHub Actions runner. |
| **Token Negotiation** | Dynamic cookie/token extraction from PSX web session. | `collector/session_token.py` | **VERIFIED** | `PSXTokenProvider` extracts session tokens and handles token refresh automatically. |
| **Rate Limiting & Cooldown** | Strict request budgets, exponential backoff, and 429 handling. | `collector/cooldown.py`, `persistent_budget.py` | **VERIFIED** | 429 `Retry-After` header parsing verified; consecutive failure cooldown verified in unit tests. |
| **Defensive Table Parsing** | Resilient against unclosed HTML tags and missing columns. | `collector/vendor/psx_dps/parsing.py` | **VERIFIED** | Chaos Test `test_malformed_html_table_parsing_resilience` passed. |
| **Market Calendar Awareness** | Skip collection during pre-open, post-close, weekends, holidays. | `collector/calendar.py` | **VERIFIED** | Runner Run `41386086661` verified `MARKET_CLOSED` detection at 09:01 PKT (Pre-Open). |
| **Live Runner Evidence** | Verifiable execution on GitHub Actions Linux runner against real PSX. | `.github/workflows/verify_durable_archive.yml` | **VERIFIED** | Run `41386016819` obtained live KSE100 index data (Current: 166,409.25, Volume: 840,495,291). |

---

## 3. Engineering Evidence & Runner Artifacts

### 3.1 Live Upstream Acquisition on GitHub Runner
- **Run ID:** `41386016819`
- **Job ID:** `125086927135`
- **Runner Environment:** Ubuntu 24.04 LTS (East US Azure datacenter)
- **Extracted Live PSX DPS Record:**
  ```json
  {
    "index": "KSE100",
    "current": 166409.25,
    "change": 812.44,
    "percentChange": 0.49,
    "high": null,
    "low": null,
    "volume": 840495291,
    "timestamp": "2026-11-02T04:00:15+00:00"
  }
  ```
- **Readback Verification:** Local payload SHA-256 matched private repository readback SHA-256 byte-for-byte.

### 3.2 Automated Test Coverage for Acquisition & Parsing
- `test_adapters.py`:
  - `test_fixture_adapter_symbols`: PASS
  - `test_fixture_adapter_snapshot`: PASS
  - `test_fixture_adapter_eod`: PASS
- `test_calendar.py`:
  - `test_market_calendar_karachi_timezone`: PASS
  - `test_regular_session_monday`: PASS
  - `test_pre_open_and_post_close_weekday`: PASS
  - `test_friday_split_sessions`: PASS
  - `test_weekend_detection`: PASS
  - `test_holiday_detection`: PASS
- `test_cooldown.py`:
  - `test_cooldown_on_429_retry_after`: PASS
  - `test_cooldown_on_consecutive_errors`: PASS
  - `test_cooldown_clears_on_success`: PASS

---

## 4. Milestone 1 Acceptance Sign-off

Milestone 1 satisfies all real-source connectivity, session token management, rate limiting, and market calendar constraints. Verified live on production GitHub runners.
