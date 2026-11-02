# PSX Research Lab — Operational Runbook

## 1. Routine Verification Commands
- `make doctor` / `pnpm doctor`: Verify toolchain, dependencies, environment, and cost posture.
- `make test`: Run complete automated test suite (TypeScript Vitest + Python Pytest).
- `make probe`: Execute bounded local probe against PSX data portal or offline fixtures.

## 2. Handling Upstream 429 / 503 Cooldown
1. When an upstream error occurs, `CooldownManager` records the timestamp and sets `cooldown_until`.
2. Inspect cooldown status:
   ```bash
   cat ~/.psx_cooldown_state.json
   ```
3. To view current 24-hour request count:
   ```bash
   cat ~/.psx_budget_state.json
   ```
4. Never rotate IP proxies or bypass cooldowns. Wait for the cooldown window to elapse.

## 3. Investigating Stale Data Badge
If the terminal UI displays `STALE DATA (LAST GOOD: YYYY-MM-DD HH:MM PKT)`:
1. Check GitHub Actions collector workflow runs:
   ```bash
   gh run list --workflow=collector.yml
   ```
2. Verify if GitHub Actions scheduled runs were delayed by GitHub infrastructure.
3. Check Healthchecks.io ping status.
4. If a scheduled run was skipped, trigger a manual dispatch:
   ```bash
   gh workflow run collector.yml
   ```

## 4. Disaster Recovery & Offline Mode
If PSX upstream is completely unreachable:
- Terminal continues serving the latest accepted snapshot from Cloudflare D1/KV.
- Backtesting engine continues to operate offline in the browser using cached and historical datasets.
- Gemini AI strategy compilation remains available as long as Gemini free quota allows.
